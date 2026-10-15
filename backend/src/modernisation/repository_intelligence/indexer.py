"""Commit-aware repository indexing.

An index snapshot describes a repository at one exact commit. File contents and their parse results are
stored once per git blob SHA, so indexing a later commit only parses blobs that changed (incremental
indexing); unchanged files are linked to the existing parse results.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from modernisation.config import get_settings
from modernisation.db.models import (
    Blob,
    BlobImport,
    BlobReference,
    BlobSymbol,
    IndexSnapshot,
    Repository,
    SnapshotFile,
)
from modernisation.repository_intelligence.git_ops import GitRepo
from modernisation.repository_intelligence.languages import detect_language, is_config_path, is_test_path
from modernisation.repository_intelligence.python_parser import parse_python

log = logging.getLogger(__name__)

MAX_CONTENT_BYTES = 1_000_000
BATCH = 500


def mirror_path(repo: Repository) -> Path:
    return get_settings().repos_dir / f"{repo.id}.git"


def git_for(repo: Repository) -> GitRepo:
    return GitRepo(mirror_path(repo))


def _decode(data: bytes) -> str | None:
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def index_commit(session: Session, repo: Repository, ref: str) -> IndexSnapshot:
    """Index ``repo`` at ``ref`` (branch, tag or SHA). Idempotent per (repository, commit)."""
    git = git_for(repo)
    sha = git.resolve(ref)
    snapshot = session.scalar(
        select(IndexSnapshot).where(IndexSnapshot.repository_id == repo.id, IndexSnapshot.commit_sha == sha)
    )
    if snapshot is not None and snapshot.status == "ready":
        return snapshot
    if snapshot is None:
        snapshot = IndexSnapshot(repository_id=repo.id, commit_sha=sha, ref=ref, status="running")
        session.add(snapshot)
        session.flush()
    else:
        # A previous run was interrupted or failed: clear partial rows and redo.
        session.query(SnapshotFile).filter(SnapshotFile.snapshot_id == snapshot.id).delete()
        snapshot.status = "running"
        snapshot.error = None
    session.commit()

    started = time.monotonic()
    try:
        entries = git.ls_tree(sha)
        blob_shas = sorted({e.sha for e in entries})
        known: set[str] = set()
        for i in range(0, len(blob_shas), 5000):
            chunk = blob_shas[i : i + 5000]
            known.update(session.scalars(select(Blob.sha).where(Blob.sha.in_(chunk))))
        missing = [s for s in blob_shas if s not in known]
        lang_by_blob = {e.sha: detect_language(e.path) for e in entries}

        parsed = 0
        symbols_rows: list[dict[str, object]] = []
        import_rows: list[dict[str, object]] = []
        ref_rows: list[dict[str, object]] = []
        blob_rows: list[dict[str, object]] = []

        def flush() -> None:
            if blob_rows:
                session.execute(insert(Blob), blob_rows)
                blob_rows.clear()
            if symbols_rows:
                session.execute(insert(BlobSymbol), symbols_rows)
                symbols_rows.clear()
            if import_rows:
                session.execute(insert(BlobImport), import_rows)
                import_rows.clear()
            if ref_rows:
                session.execute(insert(BlobReference), ref_rows)
                ref_rows.clear()

        for blob_sha, data in git.read_blobs(missing):
            language = lang_by_blob.get(blob_sha)
            text = _decode(data) if len(data) <= MAX_CONTENT_BYTES else None
            status, error = "skipped", None
            if language == "python" and text is not None:
                try:
                    result = parse_python(data)
                    status = "parsed" if not result.has_errors else "partial"
                    parsed += 1
                    for s in result.symbols:
                        symbols_rows.append(
                            dict(
                                blob_sha=blob_sha,
                                name=s.name[:300],
                                qualified_name=s.qualified_name[:600],
                                kind=s.kind,
                                start_line=s.start_line,
                                end_line=s.end_line,
                                signature=s.signature,
                                docstring=s.docstring,
                                parent=s.parent,
                            )
                        )
                    for imp in result.imports:
                        import_rows.append(
                            dict(
                                blob_sha=blob_sha,
                                module=imp.module[:400],
                                name=imp.name,
                                alias=imp.alias,
                                level=imp.level,
                                line=imp.line,
                            )
                        )
                    for r in result.references:
                        ref_rows.append(
                            dict(
                                blob_sha=blob_sha,
                                name=r.name[:300],
                                qualifier=r.qualifier,
                                kind=r.kind,
                                line=r.line,
                                column=r.column,
                            )
                        )
                except Exception as exc:  # parser bugs must not abort the whole index
                    status, error = "error", str(exc)[:500]
            blob_rows.append(
                dict(
                    sha=blob_sha,
                    language=language,
                    size=len(data),
                    line_count=text.count("\n") + (0 if text.endswith("\n") else 1) if text else 0,
                    is_binary=text is None and b"\0" in data[:8192],
                    content=text,
                    parse_status=status,
                    parse_error=error,
                )
            )
            if len(blob_rows) >= BATCH or len(ref_rows) >= 20 * BATCH:
                flush()
        flush()

        file_rows = [
            dict(
                snapshot_id=snapshot.id,
                path=e.path,
                blob_sha=e.sha,
                language=lang_by_blob.get(e.sha),
                is_test=is_test_path(e.path),
                is_config=is_config_path(e.path),
                size=e.size,
            )
            for e in entries
        ]
        for i in range(0, len(file_rows), 2000):
            session.execute(insert(SnapshotFile), file_rows[i : i + 2000])

        symbols_total = (
            session.scalar(
                select(func.count())
                .select_from(BlobSymbol)
                .join(SnapshotFile, SnapshotFile.blob_sha == BlobSymbol.blob_sha)
                .where(SnapshotFile.snapshot_id == snapshot.id)
            )
            or 0
        )
        snapshot.files_total = len(entries)
        snapshot.blobs_parsed = parsed
        snapshot.blobs_reused = len(known)
        snapshot.symbols_total = int(symbols_total)
        snapshot.languages = dict(Counter(lang or "other" for lang in (lang_by_blob.get(e.sha) for e in entries)))
        snapshot.status = "ready"
        snapshot.duration_ms = int((time.monotonic() - started) * 1000)
        snapshot.finished_at = datetime.now(UTC)
        session.commit()
        log.info(
            "indexed repository",
            extra={
                "repository": repo.name,
                "commit": sha,
                "files": len(entries),
                "parsed": parsed,
                "reused": len(known),
            },
        )
        return snapshot
    except Exception as exc:
        session.rollback()
        failed = session.get(IndexSnapshot, snapshot.id)
        assert failed is not None
        failed.status = "failed"
        failed.error = str(exc)[:2000]
        session.commit()
        raise


def latest_snapshot(session: Session, repository_id: int) -> IndexSnapshot | None:
    return session.scalar(
        select(IndexSnapshot)
        .where(IndexSnapshot.repository_id == repository_id, IndexSnapshot.status == "ready")
        .order_by(IndexSnapshot.finished_at.desc())
        .limit(1)
    )
