"""Task-set integrity validation.

A task is valid only if, measured in the real sandbox:

1. the fixture environment builds and the repository's own tests pass at the task base;
2. the protected acceptance tests FAIL at the task base (they detect the unmet requirement);
3. the reference solution passes acceptance with no regressions;
4. the reference solution stays inside the task's allowed paths;
5. the request text does not leak solution code verbatim.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from modernisation.config import Settings, get_settings
from modernisation.evaluation.acceptance import AcceptanceRunner
from modernisation.evaluation.taskset import BenchmarkTask, solution_diff, taskset_hash


def leaked_lines(task: BenchmarkTask, diff: str) -> list[str]:
    request = " ".join(task.request.split())
    leaks = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            code = " ".join(line[1:].split())
            if len(code) >= 30 and code in request:
                leaks.append(code)
    return leaks


def validate_task(task: BenchmarkTask, eval_dir: Path, runner: AcceptanceRunner, cache_key: str) -> dict[str, Any]:
    problems: list[str] = []
    base = runner.base_summary(task, cache_key)
    if not base.get("env_ok"):
        problems.append(f"base environment failed: {str(base.get('error'))[-500:]}")
        return {"id": task.id, "valid": False, "problems": problems}
    pytest_base = base["summary"].get("pytest", {})
    if not pytest_base.get("passed") or pytest_base.get("failures") or pytest_base.get("errors"):
        problems.append(f"repository tests do not pass at task base: {pytest_base.get('failing', [])[:3]}")
    if not pytest_base.get("tests"):
        problems.append("repository has no collected tests at task base")

    # acceptance must fail at the base
    ws = runner._workspace(task, "validate-base")
    from modernisation.execution.pyenv import ensure_env, read_dependency_spec

    spec = read_dependency_spec(ws.repo_dir, runner.settings.sandbox_python)
    env = ensure_env(spec, runner.sandbox, runner.settings)
    at_base = runner.run_acceptance_only(task, ws, env.path, spec.src_layout)
    ws.destroy()
    if at_base["passed"]:
        problems.append("acceptance tests already pass at the task base (they do not detect the requirement)")
    base_failure_kind = "collection_error" if at_base.get("exit_code") in (2, 3, 4) else "test_failure"

    diff = solution_diff(task, eval_dir, runner.root / "solutions")
    if not diff.strip():
        problems.append("reference solution is empty")
    outcome = runner.evaluate(task, diff, cache_key)
    if not outcome.passed:
        problems.append(
            f"reference solution fails evaluation: {outcome.failure_category} "
            f"{json.dumps(outcome.acceptance.get('failing', outcome.details))[:600]} "
            f"{outcome.regression.get('reasons', '')}"
        )
    leaks = leaked_lines(task, diff)
    if leaks:
        problems.append(f"request leaks solution code: {leaks[:2]}")
    return {
        "id": task.id,
        "repo": task.repo,
        "category": task.category,
        "split": task.split,
        "valid": not problems,
        "problems": problems,
        "base_tests": pytest_base.get("tests"),
        "acceptance_tests": outcome.acceptance.get("tests"),
        "acceptance_at_base": {
            "exit_code": at_base.get("exit_code"),
            "kind": base_failure_kind,
            "failures": at_base.get("failures"),
            "errors": at_base.get("errors"),
        },
        "solution_files": sorted({line[6:] for line in diff.splitlines() if line.startswith("+++ b/")}),
    }


def validate(eval_dir: Path, tasks: list[BenchmarkTask], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    runner = AcceptanceRunner(eval_dir, settings)
    key = taskset_hash(eval_dir)
    results = [validate_task(t, eval_dir, runner, key) for t in tasks]
    return {
        "taskset_version": key,
        "tasks": len(results),
        "valid": sum(r["valid"] for r in results),
        "by_category": dict(Counter(r.get("category") for r in results)),
        "by_split": dict(Counter(r.get("split") for r in results)),
        "results": results,
    }
