"""Independent acceptance evaluation of a candidate change.

Runs entirely outside the agent workflow: a fresh checkout of the task base, the candidate diff applied
under the task's change policy, a dependency environment built from the *candidate's* manifests, the
repository's own suite compared against the task base (regression), and the protected acceptance tests
mounted read-only at ``/acceptance``. The acceptance tests are copied from the task directory only at
this point; the agent workflow never sees them.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from modernisation.config import Settings, get_settings
from modernisation.evaluation.taskset import BenchmarkTask, materialise
from modernisation.execution.checks import CheckRunner, _parse_junit, compare_to_baseline, summarise
from modernisation.execution.policy import ChangePolicy, PolicyViolation
from modernisation.execution.pyenv import ensure_env, python_path, read_dependency_spec
from modernisation.execution.sandbox import Limits, Mount, Sandbox
from modernisation.execution.workspace import Workspace, WorkspaceError
from modernisation.repository_intelligence.git_ops import GitRepo


@dataclass
class AcceptanceOutcome:
    passed: bool
    failure_category: str | None
    env_ok: bool
    acceptance: dict[str, Any] = field(default_factory=dict)
    regression: dict[str, Any] = field(default_factory=dict)
    policy_violations: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AcceptanceRunner:
    def __init__(self, eval_dir: Path, settings: Settings | None = None, sandbox: Sandbox | None = None):
        self.eval_dir = eval_dir
        self.settings = settings or get_settings()
        self.sandbox = sandbox or Sandbox(self.settings)
        self.checks = CheckRunner(self.sandbox, self.settings)
        self.root = (self.settings.data_dir / "benchmark").resolve()

    # ------------------------------------------------------------------------------------------------
    def _base_repo(self, task: BenchmarkTask) -> tuple[GitRepo, str]:
        dest = self.root / "acceptance-sources" / task.id
        sha = materialise(task, self.eval_dir, dest)
        return GitRepo(dest), sha

    def _workspace(self, task: BenchmarkTask, label: str) -> Workspace:
        repo, sha = self._base_repo(task)
        ws = Workspace(f"acceptance-{task.id}", repo, sha, self.settings, label=label)
        ws.destroy()
        ws.create()
        return ws

    def base_summary(self, task: BenchmarkTask, cache_key: str) -> dict[str, Any]:
        cache = self.root / "base-results" / f"{task.id}-{cache_key}.json"
        if cache.is_file():
            return dict(json.loads(cache.read_text()))
        ws = self._workspace(task, "base")
        spec = read_dependency_spec(ws.repo_dir, self.settings.sandbox_python)
        env = ensure_env(spec, self.sandbox, self.settings)
        result: dict[str, Any]
        if not env.ok:
            result = {"env_ok": False, "error": env.error}
        else:
            outcomes = self.checks.run(ws, env.path, spec, phase="base", label="base")
            result = {"env_ok": True, "summary": summarise(outcomes)}
        ws.destroy()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result))
        return result

    def _acceptance_copy(self, task: BenchmarkTask) -> Path:
        dest = self.root / "acceptance-tests" / task.id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(task.acceptance_dir, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for p in [dest, *dest.rglob("*")]:
            p.chmod(0o755 if p.is_dir() else 0o644)
        return dest

    def run_acceptance_only(
        self, task: BenchmarkTask, ws: Workspace, env_path: Path, src_layout: bool
    ) -> dict[str, Any]:
        tests = self._acceptance_copy(task)
        mounts = [*ws.mounts(), Mount(env_path, "/env"), Mount(tests, "/acceptance")]
        from modernisation.execution.pyenv import DependencySpec

        spec = DependencySpec([], [], src_layout, self.settings.sandbox_python)
        argv = [
            "/env/bin/python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--rootdir=/acceptance",
            "-o",
            "junit_family=xunit2",
            "--junitxml=/out/junit-acceptance.xml",
            *task.acceptance_pytest_args,
            "/acceptance",
        ]
        res = self.sandbox.run(
            argv,
            mounts=mounts,
            env={"PYTHONPATH": python_path(spec), "REPO_ROOT": "/work"},
            limits=Limits.from_settings(self.settings),
            hide=ws.hidden_paths(),
        )
        summary = _parse_junit(ws.out_dir / "junit-acceptance.xml")
        summary.pop("passed_ids", None)
        return {
            "passed": res.exit_code == 0 and not res.timed_out,
            "exit_code": res.exit_code,
            "timed_out": res.timed_out,
            "duration_ms": res.duration_ms,
            **summary,
            "output_tail": (res.stdout[-3000:] + res.stderr[-1500:]),
        }

    def evaluate(self, task: BenchmarkTask, diff: str | None, cache_key: str = "v") -> AcceptanceOutcome:
        if not diff or not diff.strip():
            return AcceptanceOutcome(False, "no_patch", env_ok=False)
        policy = ChangePolicy(allowed_paths=task.allowed_paths)
        violations: list[str] = []
        for path in Workspace.paths_in_diff(diff):
            try:
                policy.check_path(path)
            except PolicyViolation as exc:
                violations.append(f"{exc.code}: {path}")
        if violations:
            return AcceptanceOutcome(False, "prohibited_action", env_ok=False, policy_violations=violations)
        base = self.base_summary(task, cache_key)
        ws = self._workspace(task, "candidate")
        try:
            originals = {p: ws.read(p) for p in Workspace.paths_in_diff(diff)}
            ws.apply_diff(diff, policy)
            for path, old in originals.items():
                try:
                    policy.check_content(path, old, ws.read(path))
                except PolicyViolation as exc:
                    violations.append(f"{exc.code}: {path}")
            if violations:
                return AcceptanceOutcome(False, "prohibited_action", env_ok=False, policy_violations=violations)
        except WorkspaceError as exc:
            return AcceptanceOutcome(False, "patch_does_not_apply", env_ok=False, details={"error": str(exc)})
        spec = read_dependency_spec(ws.repo_dir, self.settings.sandbox_python)
        env = ensure_env(spec, self.sandbox, self.settings)
        if not env.ok:
            ws.destroy()
            return AcceptanceOutcome(
                False, "dependency_install_failed", env_ok=False, details={"error": (env.error or "")[-2000:]}
            )
        regression: dict[str, Any] = {"skipped": True}
        if task.regression:
            outcomes = self.checks.run(
                ws, env.path, spec, phase="regression", label="regression", changed_files=Workspace.paths_in_diff(diff)
            )
            regression = compare_to_baseline((base.get("summary") or {}), summarise(outcomes))
        acceptance = self.run_acceptance_only(task, ws, env.path, spec.src_layout)
        ws.destroy()
        if not acceptance["passed"]:
            category = "acceptance_failed"
        elif task.regression and not regression.get("acceptable", False):
            category = "regression_failed"
        else:
            category = None
        return AcceptanceOutcome(category is None, category, env_ok=True, acceptance=acceptance, regression=regression)
