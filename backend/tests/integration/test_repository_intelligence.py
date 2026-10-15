"""Repository intelligence against real git repositories and a real PostgreSQL index."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from modernisation.repository_intelligence.indexer import git_for, index_commit
from modernisation.repository_intelligence.retrieval import (
    find_references,
    impact_analysis,
    load_snapshot,
    retrieve,
    symbol_search,
    text_search,
)
from modernisation.services.repositories import RepositoryAccessDenied, register_local
from tests.helpers import BUG_REQUEST, commit_change

pytestmark = pytest.mark.postgres


def test_register_rejects_paths_outside_authorised_roots(session: Session, tmp_path: Path):
    with pytest.raises(RepositoryAccessDenied):
        register_local(session, "evil", str(tmp_path))
    with pytest.raises(RepositoryAccessDenied):
        register_local(session, "evil2", "/etc")


def test_index_extracts_files_symbols_and_flags(session: Session, sample_repo: Path):
    repo = register_local(session, "inventory", str(sample_repo))
    snap = index_commit(session, repo, "main")
    assert snap.status == "ready"
    assert snap.files_total == 8
    assert snap.symbols_total >= 10
    data = load_snapshot(session, snap)
    assert data.files["tests/test_pricing.py"].is_test
    assert data.files["pyproject.toml"].is_config
    assert data.files["src/inventory/pricing.py"].module == "inventory.pricing"
    names = {s.qualified_name for s in data.symbols["src/inventory/pricing.py"]}
    assert {"apply_discount", "order_total", "is_bulk", "BULK_THRESHOLD"} <= names


def test_indexing_is_idempotent_and_incremental(session: Session, sample_repo: Path):
    repo = register_local(session, "inventory", str(sample_repo))
    first = index_commit(session, repo, "main")
    again = index_commit(session, repo, "main")
    assert again.id == first.id  # same commit -> same snapshot

    new_sha = commit_change(
        sample_repo,
        "src/inventory/pricing.py",
        (sample_repo / "src/inventory/pricing.py").read_text() + "\n\nMAX_DISCOUNT = 90\n",
    )
    from modernisation.services.repositories import refresh

    refresh(repo)
    second = index_commit(session, repo, new_sha)
    assert second.id != first.id and second.commit_sha == new_sha
    # Only the changed blob is parsed; the other seven files reuse cached parse results.
    assert second.blobs_parsed == 1
    assert second.blobs_reused == 7
    data = load_snapshot(session, second)
    assert any(s.name == "MAX_DISCOUNT" for s in data.symbols["src/inventory/pricing.py"])
    # The old snapshot still reflects the old commit (commit-aware index).
    old = load_snapshot(session, first)
    assert not any(s.name == "MAX_DISCOUNT" for s in old.symbols["src/inventory/pricing.py"])


def test_retrieval_acceptance_for_python_bug_report(session: Session, sample_repo: Path):
    """Acceptance criterion: implementation, related tests and configuration with reproducible references."""
    repo = register_local(session, "inventory", str(sample_repo))
    snap = index_commit(session, repo, "main")
    data = load_snapshot(session, snap)
    refs = retrieve(data, BUG_REQUEST, category="bug_fix", limit=20)
    assert refs, "retrieval returned nothing"
    for r in refs:
        assert r.repository == "inventory" and r.commit_sha == snap.commit_sha
        assert r.path in data.files and 1 <= r.start_line <= r.end_line
        assert r.retrieval_method in {"keyword", "symbol", "reference", "import_graph", "test_link", "config"}

    top = refs[0]
    assert top.path == "src/inventory/pricing.py"
    assert top.symbol == "apply_discount"
    assert {"keyword", "symbol"} <= set(top.methods), top.methods
    lines = data.contents[top.path].splitlines()[top.start_line - 1 : top.end_line]
    assert any("percent / 1000" in line for line in lines), "reference range must contain the faulty line"

    test_refs = [r for r in refs if r.is_test]
    assert any(r.path == "tests/test_pricing.py" for r in test_refs)
    assert any(r.retrieval_method in ("test_link", "reference", "keyword") for r in test_refs)
    assert any(r.is_config and r.path == "pyproject.toml" for r in refs)

    # Reproducible: identical request on the same snapshot yields identical references.
    again = retrieve(data, BUG_REQUEST, category="bug_fix", limit=20)
    assert [(r.path, r.start_line, r.end_line) for r in again] == [(r.path, r.start_line, r.end_line) for r in refs]


def test_search_symbols_references_and_impact(session: Session, sample_repo: Path):
    repo = register_local(session, "inventory", str(sample_repo))
    data = load_snapshot(session, index_commit(session, repo, "main"))
    hits = text_search(data, "percent / 1000")
    assert [(h["path"], h["symbol"]) for h in hits] == [("src/inventory/pricing.py", "apply_discount")]
    syms = symbol_search(data, "order_total")
    assert syms[0]["path"] == "src/inventory/pricing.py" and syms[0]["kind"] == "function"
    refs = find_references(data, "apply_discount")
    assert {r["path"] for r in refs} == {"src/inventory/pricing.py", "tests/test_pricing.py"}
    impact = impact_analysis(data, ["src/inventory/pricing.py"], ["apply_discount"])
    dependents = {d["path"] for d in impact["dependents"]}
    assert {"src/inventory/report.py", "src/inventory/__init__.py", "tests/test_pricing.py"} <= dependents
    assert "tests/test_report.py" in impact["tests"]  # transitive via report.py


def test_git_ops_reject_option_injection(session: Session, sample_repo: Path):
    repo = register_local(session, "inventory", str(sample_repo))
    git = git_for(repo)
    for bad in ("--upload-pack=touch /tmp/pwned", "main..HEAD", "-n1"):
        with pytest.raises(ValueError):
            git.resolve(bad)


def test_same_size_same_second_edit_is_detected(session: Session, sample_repo: Path):
    """Regression test: git's stat cache must not hide a same-size change with an unchanged mtime.

    Reproduces the failure seen when fixture files were copied with preserved mtimes: the index records
    a past mtime, the content changes without changing size or mtime, and a plain ``git add -A`` misses it.
    """
    import os

    from modernisation.execution.workspace import Workspace

    repo = register_local(session, "inventory", str(sample_repo))
    git = git_for(repo)
    ws = Workspace("stat-race", git, git.resolve("main"))
    ws.create()
    target = ws.repo_dir / "src/inventory/pricing.py"
    past = 1_600_000_000_000_000_000  # 2020-09-13, well before the index write time
    os.utime(target, ns=(past, past))
    ws._git("update-index", "--refresh")  # index now records the past mtime; entry is not racy
    content = target.read_text().replace("BULK_THRESHOLD = 10", "BULK_THRESHOLD = 20")
    assert len(content.encode()) == target.stat().st_size
    target.write_text(content)
    os.utime(target, ns=(past, past))  # identical size and mtime to the cached stat
    change = ws.current_change()
    assert change.files_changed == ["src/inventory/pricing.py"]
    assert "BULK_THRESHOLD = 20" in change.diff
    ws.destroy()


def test_source_repository_owned_by_another_user(session: Session, sample_repo: Path):
    """Regression: in containers the API/worker uid differs from the source repository owner."""
    import os

    for root, dirs, files in os.walk(sample_repo):
        for name in [*dirs, *files]:
            os.lchown(os.path.join(root, name), 4242, 4242)
    os.chown(sample_repo, 4242, 4242)
    repo = register_local(session, "foreign-owner", str(sample_repo))
    snap = index_commit(session, repo, "main")
    assert snap.status == "ready" and snap.files_total == 8
