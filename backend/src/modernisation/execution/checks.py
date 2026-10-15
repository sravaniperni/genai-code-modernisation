"""Build/test/lint checks for Python repositories and regression comparison against a baseline."""

from __future__ import annotations

import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modernisation.config import Settings, get_settings
from modernisation.execution.pyenv import DependencySpec, python_path
from modernisation.execution.sandbox import CommandResult, Limits, Mount, Sandbox
from modernisation.execution.workspace import Workspace

SYNTAX_SCRIPT = (
    "import ast, sys\n"
    "bad = 0\n"
    "for f in sys.argv[1:]:\n"
    "    try:\n"
    "        ast.parse(open(f, 'rb').read(), f)\n"
    "    except SyntaxError as e:\n"
    "        bad += 1; print(f'{f}:{e.lineno}: {e.msg}')\n"
    "sys.exit(1 if bad else 0)\n"
)


@dataclass
class CheckOutcome:
    name: str
    result: CommandResult
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.summary.get("passed", self.result.ok))


def _parse_junit(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"junit": False}
    try:
        root = ET.parse(path).getroot()  # noqa: S314
    except ET.ParseError:
        return {"junit": False}
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    failing: list[dict[str, str]] = []
    passed_ids: list[str] = []
    for case in root.iter("testcase"):
        counts["tests"] += 1
        node_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        failure = case.find("failure")
        error = case.find("error")
        if failure is not None or error is not None:
            el = failure if failure is not None else error
            assert el is not None
            counts["failures" if failure is not None else "errors"] += 1
            failing.append(
                {"id": node_id, "message": (el.get("message") or "")[:300], "detail": (el.text or "")[-1500:]}
            )
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
        else:
            passed_ids.append(node_id)
    return {"junit": True, **counts, "failing": failing, "passed_ids": passed_ids}


def _configured_tools(repo_dir: Path) -> set[str]:
    tools: set[str] = set()
    pyproject = repo_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            tool = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("tool", {})
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            tool = {}
        if "ruff" in tool:
            tools.add("ruff")
        if "mypy" in tool:
            tools.add("mypy")
    if (repo_dir / "ruff.toml").is_file() or (repo_dir / ".ruff.toml").is_file():
        tools.add("ruff")
    if (repo_dir / "mypy.ini").is_file():
        tools.add("mypy")
    return tools


class CheckRunner:
    def __init__(self, sandbox: Sandbox, settings: Settings | None = None):
        self.sandbox = sandbox
        self.settings = settings or get_settings()

    def run(
        self,
        workspace: Workspace,
        env_path: Path,
        spec: DependencySpec,
        *,
        phase: str,
        changed_files: list[str] | None = None,
        extra_mounts: list[Mount] | None = None,
        pytest_args: list[str] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        label: str | None = None,
    ) -> list[CheckOutcome]:
        mounts = [*workspace.mounts(), Mount(env_path, "/env", writable=False), *(extra_mounts or [])]
        env = {"PYTHONPATH": python_path(spec)}
        limits = Limits.from_settings(self.settings)
        hide = workspace.hidden_paths()
        outcomes: list[CheckOutcome] = []
        tag = label or phase

        py_files = [f for f in (changed_files or []) if f.endswith(".py")]
        if py_files:
            existing = [f for f in py_files if (workspace.repo_dir / f).is_file()]
            if existing:
                res = self.sandbox.run(
                    ["/env/bin/python", "-c", SYNTAX_SCRIPT, *existing],
                    mounts=mounts,
                    env=env,
                    limits=limits,
                    cancel_check=cancel_check,
                    hide=hide,
                )
                outcomes.append(CheckOutcome("syntax", res, {"passed": res.ok, "files": existing}))
                if not res.ok:
                    return outcomes  # tests cannot be meaningful with syntax errors

        junit = f"/out/junit-{tag}.xml"
        argv = [
            "/env/bin/python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "junit_family=xunit2",
            f"--junitxml={junit}",
            *(pytest_args or []),
        ]
        res = self.sandbox.run(argv, mounts=mounts, env=env, limits=limits, cancel_check=cancel_check, hide=hide)
        summary = _parse_junit(workspace.out_dir / f"junit-{tag}.xml")
        # pytest exit codes: 0 ok, 1 failures, 2 interrupted/collection error, 3 internal, 4 usage, 5 none collected
        summary["exit_code"] = res.exit_code
        summary["collection_error"] = res.exit_code in (2, 3, 4)
        summary["no_tests"] = res.exit_code == 5
        summary["passed"] = res.exit_code in (0, 5) and not res.timed_out
        outcomes.append(CheckOutcome("pytest", res, summary))

        tools = _configured_tools(workspace.repo_dir)
        if "ruff" in tools and (env_path / "bin" / "ruff").exists():
            targets = py_files or ["."]
            res = self.sandbox.run(
                ["/env/bin/ruff", "check", "--no-cache", "--output-format", "concise", *targets],
                mounts=mounts,
                env=env,
                limits=limits,
                cancel_check=cancel_check,
                hide=hide,
            )
            diagnostics = [line for line in res.stdout.splitlines() if ":" in line and not line.startswith("Found")]
            outcomes.append(
                CheckOutcome(
                    "ruff", res, {"passed": res.ok, "diagnostics": diagnostics[:200], "count": len(diagnostics)}
                )
            )
        if "mypy" in tools and (env_path / "bin" / "mypy").exists():
            res = self.sandbox.run(
                ["/env/bin/python", "-m", "mypy", "--no-incremental", "--cache-dir=/tmp/mypy", "."],
                mounts=mounts,
                env=env,
                limits=limits,
                cancel_check=cancel_check,
                hide=hide,
            )
            errors = [line for line in res.stdout.splitlines() if ": error:" in line]
            outcomes.append(CheckOutcome("mypy", res, {"passed": res.ok, "errors": errors[:200], "count": len(errors)}))

        res = self.sandbox.run(
            ["/env/bin/python", "-m", "pip", "check"],
            mounts=mounts,
            env=env,
            limits=limits,
            cancel_check=cancel_check,
            hide=hide,
        )
        outcomes.append(CheckOutcome("pip_check", res, {"passed": res.ok}))
        return outcomes


def summarise(outcomes: list[CheckOutcome]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for o in outcomes:
        out[o.name] = {
            "passed": o.passed,
            "exit_code": o.result.exit_code,
            "timed_out": o.result.timed_out,
            "duration_ms": o.result.duration_ms,
            **{k: v for k, v in o.summary.items() if k not in {"passed_ids", "detail"}},
        }
        if o.name == "pytest":
            out[o.name]["passed_ids"] = o.summary.get("passed_ids", [])
    return out


def compare_to_baseline(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Decide whether ``current`` checks are acceptable relative to the pre-change ``baseline``."""
    reasons: list[str] = []
    if "syntax" in current and not current["syntax"]["passed"]:
        reasons.append("syntax errors in changed files")
    cur_py = current.get("pytest", {})
    base_py = baseline.get("pytest", {})
    if cur_py.get("timed_out"):
        reasons.append("test run timed out")
    if cur_py.get("collection_error") and not base_py.get("collection_error"):
        reasons.append("test collection failed")
    base_failing = {f["id"] for f in base_py.get("failing", [])}
    base_passing = set(base_py.get("passed_ids", []))
    cur_failing = {f["id"] for f in cur_py.get("failing", [])}
    new_failures = sorted(cur_failing - base_failing)
    regressions = sorted(cur_failing & base_passing)
    fixed = sorted(base_failing - cur_failing)
    if new_failures:
        reasons.append(f"{len(new_failures)} failing test(s) not failing at baseline")
    if base_py.get("tests", 0) and cur_py.get("tests", 0) < base_py.get("tests", 0):
        reasons.append(f"test count dropped from {base_py.get('tests')} to {cur_py.get('tests')}")
    for tool in ("ruff", "mypy"):
        if tool in current and current[tool].get("count", 0) > baseline.get(tool, {}).get("count", 0):
            reasons.append(f"new {tool} findings")
    if (
        "pip_check" in current
        and not current["pip_check"]["passed"]
        and baseline.get("pip_check", {}).get("passed", True)
    ):
        reasons.append("dependency conflicts reported by pip check")
    return {
        "acceptable": not reasons,
        "reasons": reasons,
        "new_failures": new_failures,
        "regressions": regressions,
        "fixed": fixed,
        "still_failing": sorted(cur_failing & base_failing),
    }
