"""Benchmark task-set loading, fixture repository construction and version hashing.

Layout (all paths relative to the ``evaluation/`` directory)::

    repos/<repo>/base/...                 fixture project at its clean baseline (own test suite passes)
    repos/<repo>/wheelhouse.txt           exact package pins needed by the repo and its tasks
    tasks/<task_id>/task.yaml             metadata + maintenance request (the only text the agent sees)
    tasks/<task_id>/setup/...             overlay applied to the baseline to create the task's base commit
    tasks/<task_id>/solution/...          reference solution overlay (held out; used only for validation)
    tasks/<task_id>/acceptance/test_*.py  protected acceptance tests (never mounted into agent workspaces)

Each task becomes its own single-commit git repository so that no other revision (for example the clean
baseline a bug was injected into) is reachable from the agent's repository.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = ("dependency_upgrade", "deprecated_api_migration", "bug_fix")
SPLITS = ("dev", "heldout")
FIXTURE_AUTHOR = {
    "GIT_AUTHOR_NAME": "Benchmark Fixture",
    "GIT_AUTHOR_EMAIL": "fixtures@benchmark.invalid",
    "GIT_COMMITTER_NAME": "Benchmark Fixture",
    "GIT_COMMITTER_EMAIL": "fixtures@benchmark.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}


class TaskSetError(ValueError):
    pass


@dataclass
class BenchmarkTask:
    id: str
    repo: str
    category: str
    split: str
    title: str
    request: str
    allowed_paths: list[str]
    root: Path
    setup_delete: list[str] = field(default_factory=list)
    acceptance_pytest_args: list[str] = field(default_factory=list)
    regression: bool = True
    max_attempts: int = 3
    notes: str = ""

    @property
    def setup_dir(self) -> Path:
        return self.root / "setup"

    @property
    def solution_dir(self) -> Path:
        return self.root / "solution"

    @property
    def acceptance_dir(self) -> Path:
        return self.root / "acceptance"


def load_task(path: Path) -> BenchmarkTask:
    data: dict[str, Any] = yaml.safe_load((path / "task.yaml").read_text())
    required = ("id", "repo", "category", "split", "title", "request", "allowed_paths")
    missing = [k for k in required if k not in data]
    if missing:
        raise TaskSetError(f"{path}: missing keys {missing}")
    if data["id"] != path.name:
        raise TaskSetError(f"{path}: id {data['id']!r} must equal directory name")
    if data["category"] not in CATEGORIES:
        raise TaskSetError(f"{path}: unknown category {data['category']!r}")
    if data["split"] not in SPLITS:
        raise TaskSetError(f"{path}: unknown split {data['split']!r}")
    acceptance = data.get("acceptance") or {}
    return BenchmarkTask(
        id=data["id"],
        repo=data["repo"],
        category=data["category"],
        split=data["split"],
        title=data["title"],
        request=str(data["request"]).strip(),
        allowed_paths=list(data["allowed_paths"]),
        root=path,
        setup_delete=list(data.get("setup_delete") or []),
        acceptance_pytest_args=[str(a) for a in acceptance.get("pytest_args", [])],
        regression=bool(data.get("regression", True)),
        max_attempts=int(data.get("max_attempts", 3)),
        notes=str(data.get("notes", "")),
    )


def load_tasks(eval_dir: Path, *, split: str | None = None, ids: list[str] | None = None) -> list[BenchmarkTask]:
    tasks = [load_task(p) for p in sorted((eval_dir / "tasks").iterdir()) if (p / "task.yaml").is_file()]
    if split and split != "all":
        tasks = [t for t in tasks if t.split == split]
    if ids:
        wanted = set(ids)
        tasks = [t for t in tasks if t.id in wanted]
    return tasks


def taskset_hash(eval_dir: Path) -> str:
    """Content hash over every task file and every fixture baseline file."""
    digest = hashlib.sha256()
    for sub in ("tasks", "repos"):
        root = eval_dir / sub
        for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            digest.update(str(path.relative_to(eval_dir)).encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()[:16]


def _overlay(src: Path, dest: Path) -> list[str]:
    changed: list[str] = []
    if not src.is_dir():
        return changed
    for path in sorted(p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        rel = path.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        # copyfile, not copy2: preserving source mtimes lets git's stat cache miss same-size changes
        shutil.copyfile(path, target)
        changed.append(str(rel))
    return changed


def _git(cwd: Path, *args: str) -> str:
    import os

    env = {**os.environ, **FIXTURE_AUTHOR, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout


def materialise(task: BenchmarkTask, eval_dir: Path, dest: Path, *, with_solution: bool = False) -> str:
    """Create ``dest`` as a single-commit git repository holding the task base. Returns the commit SHA.

    With ``with_solution`` a second commit containing the reference solution is added (validation only).
    """
    if dest.exists():
        shutil.rmtree(dest)
    base = eval_dir / "repos" / task.repo / "base"
    if not base.is_dir():
        raise TaskSetError(f"fixture repository {task.repo!r} has no base/ directory")
    shutil.copytree(
        base,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        copy_function=shutil.copyfile,
    )
    _overlay(task.setup_dir, dest)
    for rel in task.setup_delete:
        (dest / rel).unlink(missing_ok=True)
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", f"{task.repo}: maintenance baseline")
    sha = _git(dest, "rev-parse", "HEAD").strip()
    if with_solution:
        _overlay(task.solution_dir, dest)
        _git(dest, "add", "--renormalize", ".")  # re-hash content; never trust the stat cache
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "-m", "reference solution")
    return sha


def solution_diff(task: BenchmarkTask, eval_dir: Path, scratch: Path) -> str:
    repo = scratch / f"{task.id}-solution"
    base_sha = materialise(task, eval_dir, repo, with_solution=True)
    return _git(repo, "diff", "--binary", base_sha, "HEAD")
