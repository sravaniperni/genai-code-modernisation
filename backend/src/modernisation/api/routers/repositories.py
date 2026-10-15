from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modernisation.api.deps import get_session, require_token
from modernisation.api.schemas import ImpactRequest, IndexRequest, RepositoryCreate, RetrieveRequest
from modernisation.config import get_settings
from modernisation.db.models import IndexSnapshot, Repository, SnapshotFile, Task
from modernisation.repository_intelligence.git_ops import GitError
from modernisation.repository_intelligence.indexer import git_for, index_commit, latest_snapshot
from modernisation.repository_intelligence.retrieval import (
    find_references,
    impact_analysis,
    load_snapshot,
    retrieve,
    symbol_search,
    text_search,
)
from modernisation.services import repositories as repo_service

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


def _repo(session: Session, repo_id: int) -> Repository:
    repo = session.get(Repository, repo_id)
    if repo is None:
        raise HTTPException(404, "repository not found")
    return repo


def _snapshot_dict(s: IndexSnapshot | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "id": s.id,
        "commit_sha": s.commit_sha,
        "ref": s.ref,
        "status": s.status,
        "files_total": s.files_total,
        "blobs_parsed": s.blobs_parsed,
        "blobs_reused": s.blobs_reused,
        "symbols_total": s.symbols_total,
        "languages": s.languages,
        "duration_ms": s.duration_ms,
        "finished_at": s.finished_at,
        "error": s.error,
    }


def _repo_dict(session: Session, repo: Repository) -> dict[str, Any]:
    counts = dict(
        session.execute(
            select(Task.state, func.count()).where(Task.repository_id == repo.id).group_by(Task.state)
        ).all()
    )
    return {
        "id": repo.id,
        "name": repo.name,
        "source_kind": repo.source_kind,
        "source": repo.source,
        "github_full_name": repo.github_full_name,
        "default_branch": repo.default_branch,
        "created_at": repo.created_at,
        "latest_snapshot": _snapshot_dict(latest_snapshot(session, repo.id)),
        "task_counts": counts,
    }


def _snapshot_for(session: Session, repo: Repository, ref: str | None) -> IndexSnapshot:
    if ref:
        try:
            return index_commit(session, repo, ref)
        except (GitError, ValueError) as exc:
            raise HTTPException(400, f"cannot index ref {ref!r}: {exc}") from exc
    snap = latest_snapshot(session, repo.id)
    if snap is None:
        try:
            snap = index_commit(session, repo, repo.default_branch)
        except (GitError, ValueError) as exc:
            raise HTTPException(400, f"repository has no index and default branch cannot be indexed: {exc}") from exc
    return snap


@router.get("")
def list_repositories(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_repo_dict(session, r) for r in session.scalars(select(Repository).order_by(Repository.name))]


@router.post("", dependencies=[Depends(require_token)], status_code=201)
def create_repository(body: RepositoryCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    settings = get_settings()
    try:
        if body.kind == "local":
            repo = repo_service.register_local(
                session, body.name or body.source.rstrip("/").split("/")[-1], body.source, settings
            )
        else:
            repo = repo_service.register_github(session, body.source, settings, name=body.name)
    except repo_service.RepositoryAccessDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, GitError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return _repo_dict(session, repo)


@router.get("/{repo_id}")
def get_repository(repo_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _repo_dict(session, _repo(session, repo_id))


@router.post("/{repo_id}/refresh", dependencies=[Depends(require_token)])
def refresh_repository(repo_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    repo = _repo(session, repo_id)
    try:
        git = repo_service.refresh(repo)
    except GitError as exc:
        raise HTTPException(502, f"fetch failed: {exc}") from exc
    return {"branches": git.branches()}


@router.post("/{repo_id}/index", dependencies=[Depends(require_token)])
def index_repository(repo_id: int, body: IndexRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    repo = _repo(session, repo_id)
    snap = _snapshot_for(session, repo, body.ref or repo.default_branch)
    return _snapshot_dict(snap) or {}


@router.get("/{repo_id}/snapshots")
def list_snapshots(repo_id: int, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _repo(session, repo_id)
    snaps = session.scalars(
        select(IndexSnapshot)
        .where(IndexSnapshot.repository_id == repo_id)
        .order_by(IndexSnapshot.created_at.desc())
        .limit(50)
    )
    return [_snapshot_dict(s) or {} for s in snaps]


@router.get("/{repo_id}/branches")
def branches(repo_id: int, session: Session = Depends(get_session)) -> dict[str, str]:
    return git_for(_repo(session, repo_id)).branches()


@router.get("/{repo_id}/commits")
def commits(
    repo_id: int, ref: str | None = None, limit: int = Query(20, ge=1, le=200), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    repo = _repo(session, repo_id)
    try:
        return [c.__dict__ for c in git_for(repo).log(ref or repo.default_branch, limit)]
    except (GitError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{repo_id}/tree")
def tree(repo_id: int, ref: str | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    repo = _repo(session, repo_id)
    snap = _snapshot_for(session, repo, ref)
    files = session.scalars(select(SnapshotFile).where(SnapshotFile.snapshot_id == snap.id).order_by(SnapshotFile.path))
    return {
        "snapshot": _snapshot_dict(snap),
        "files": [
            {"path": f.path, "language": f.language, "is_test": f.is_test, "is_config": f.is_config, "size": f.size}
            for f in files
        ],
    }


@router.get("/{repo_id}/file")
def file_content(
    repo_id: int, path: str, ref: str | None = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    repo = _repo(session, repo_id)
    snap = _snapshot_for(session, repo, ref)
    data = load_snapshot(session, snap)
    rec = data.files.get(path)
    if rec is None:
        raise HTTPException(404, "file not found in snapshot")
    syms = sorted(data.symbols.get(path, []), key=lambda s: s.start_line)
    return {
        "repository": repo.name,
        "commit_sha": snap.commit_sha,
        "path": path,
        "language": rec.language,
        "is_test": rec.is_test,
        "is_config": rec.is_config,
        "module": rec.module,
        "content": data.contents.get(path),
        "binary_or_large": path not in data.contents,
        "symbols": [
            {
                "name": s.name,
                "qualified_name": s.qualified_name,
                "kind": s.kind,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "signature": s.signature,
            }
            for s in syms
        ],
        "imports": [
            {"module": i.module, "name": i.name, "alias": i.alias, "level": i.level, "line": i.line}
            for i in data.imports.get(path, [])
        ],
    }


@router.get("/{repo_id}/search")
def search(
    repo_id: int,
    q: str = Query(min_length=1, max_length=300),
    mode: str = Query("text", pattern="^(text|regex|symbol|references)$"),
    ref: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    repo = _repo(session, repo_id)
    snap = _snapshot_for(session, repo, ref)
    data = load_snapshot(session, snap)
    if mode in ("text", "regex"):
        try:
            hits = text_search(data, q, regex=mode == "regex", limit=limit)
        except Exception as exc:  # invalid regex
            raise HTTPException(400, f"invalid pattern: {exc}") from exc
    elif mode == "symbol":
        hits = symbol_search(data, q, limit=limit)
    else:
        qualifier, _, name = q.rpartition(".")
        hits = find_references(data, name or q, qualifier or None, limit=limit)
    return {"commit_sha": snap.commit_sha, "mode": mode, "results": hits}


@router.post("/{repo_id}/retrieve")
def retrieve_context(repo_id: int, body: RetrieveRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    repo = _repo(session, repo_id)
    snap = _snapshot_for(session, repo, body.ref)
    data = load_snapshot(session, snap)
    refs = retrieve(data, body.request, category=body.category.value if body.category else None, limit=body.limit)
    return {"commit_sha": snap.commit_sha, "references": [r.to_dict() for r in refs]}


@router.post("/{repo_id}/impact")
def impact(repo_id: int, body: ImpactRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    repo = _repo(session, repo_id)
    snap = _snapshot_for(session, repo, body.ref)
    return impact_analysis(load_snapshot(session, snap), body.paths, body.symbols)
