"""Static integrity checks of the benchmark task set (no sandbox needed; run in CI).

Dynamic validation (acceptance fails at base, reference passes) is done by
``python -m modernisation.evaluation validate`` and recorded in evaluation/validation-report.json.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from modernisation.evaluation.taskset import load_tasks, taskset_hash
from modernisation.execution.policy import ChangePolicy, PolicyViolation

EVAL_DIR = Path(__file__).resolve().parents[3] / "evaluation"
TASKS = load_tasks(EVAL_DIR) if (EVAL_DIR / "tasks").is_dir() else []

pytestmark = pytest.mark.skipif(not TASKS, reason="benchmark task set not present")


def test_planned_counts():
    by_cat = Counter(t.category for t in TASKS)
    assert len(TASKS) == 100
    assert by_cat == {"dependency_upgrade": 40, "deprecated_api_migration": 30, "bug_fix": 30}
    assert Counter(t.split for t in TASKS) == {"dev": 20, "heldout": 80}
    assert len({t.repo for t in TASKS}) == 5


def test_frozen_lock_matches_task_set():
    lock_path = EVAL_DIR / "TASKSET.lock"
    assert lock_path.is_file(), "task set must be frozen before final evaluation"
    lock = json.loads(lock_path.read_text())
    assert lock["taskset_version"] == taskset_hash(EVAL_DIR), "task set changed after it was frozen"
    assert lock["tasks"] == len(TASKS)


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_task_layout_and_scope(task):
    assert task.acceptance_dir.is_dir() and list(task.acceptance_dir.glob("test_*.py")), "no acceptance tests"
    assert task.solution_dir.is_dir() and any(p.is_file() for p in task.solution_dir.rglob("*")), "no solution"
    assert (EVAL_DIR / "repos" / task.repo / "base").is_dir()
    policy = ChangePolicy(allowed_paths=task.allowed_paths)
    for path in task.solution_dir.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            rel = str(path.relative_to(task.solution_dir))
            try:
                policy.check_path(rel)
            except PolicyViolation as exc:  # pragma: no cover - reported as failure
                pytest.fail(f"reference solution touches a disallowed path: {exc}")


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_request_does_not_leak_solution(task):
    request = " ".join(task.request.split())
    base = EVAL_DIR / "repos" / task.repo / "base"
    for path in task.solution_dir.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".txt", ".toml", ".cfg"}:
            continue
        rel = path.relative_to(task.solution_dir)
        start = task.setup_dir / rel if (task.setup_dir / rel).is_file() else base / rel
        before = set(start.read_text().splitlines()) if start.is_file() else set()
        for line in path.read_text().splitlines():
            code = " ".join(line.split())
            if line not in before and len(code) >= 30:
                assert code not in request, f"request contains solution line: {code!r}"


def test_acceptance_tests_never_inside_fixture_repositories():
    for repo in (EVAL_DIR / "repos").iterdir():
        assert not list(repo.rglob("acceptance")), f"{repo.name} contains an acceptance directory"


def test_validation_report_covers_frozen_set():
    report_path = EVAL_DIR / "validation-report.json"
    assert report_path.is_file(), "run the validator and commit evaluation/validation-report.json"
    report = json.loads(report_path.read_text())
    assert report["taskset_version"] == taskset_hash(EVAL_DIR)
    assert report["tasks"] == len(TASKS) and report["valid"] == len(TASKS)
