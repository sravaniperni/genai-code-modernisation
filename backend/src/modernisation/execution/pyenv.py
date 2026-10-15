"""Python dependency environments for sandboxed checks.

Environments are built inside the sandbox from an offline wheelhouse (no network) and cached by a hash of
the dependency specification, so tasks on the same repository revision reuse one environment. Cached
environments are mounted read-only into check runs, which prevents one job from tampering with an
environment another job will use.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modernisation.config import Settings, get_settings
from modernisation.execution.sandbox import CommandResult, Limits, Mount, Sandbox, prepare_writable_dir

REQUIREMENT_FILES = [
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements_dev.txt",
    "requirements_test.txt",
    "dev-requirements.txt",
    "test-requirements.txt",
]
TEST_EXTRAS = ("test", "tests", "testing", "dev")
TOOLS = ["pytest"]


@dataclass
class DependencySpec:
    requirements: list[str]
    sources: list[str]
    src_layout: bool
    python: str
    tools: list[str] = field(default_factory=list)

    def key(self) -> str:
        blob = json.dumps({"r": self.requirements, "p": self.python, "t": self.tools}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:20]


@dataclass
class EnvResult:
    key: str
    path: Path
    ok: bool
    reused: bool
    logs: list[CommandResult]
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "ok": self.ok,
            "reused": self.reused,
            "error": self.error,
            "steps": [
                {"argv": r.argv, "exit_code": r.exit_code, "duration_ms": r.duration_ms, "timed_out": r.timed_out}
                for r in self.logs
            ],
        }


def _req_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-e", "--", "-r", "-c", "git+", "http")):
            continue
        lines.append(line)
    return lines


def read_dependency_spec(repo_dir: Path, python: str) -> DependencySpec:
    reqs: list[str] = []
    sources: list[str] = []
    pyproject = repo_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        project = data.get("project", {})
        reqs += [str(r) for r in project.get("dependencies", [])]
        optional = project.get("optional-dependencies", {})
        for extra in TEST_EXTRAS:
            reqs += [str(r) for r in optional.get(extra, [])]
        groups = data.get("dependency-groups", {})
        for group in TEST_EXTRAS:
            reqs += [r for r in groups.get(group, []) if isinstance(r, str)]
        sources.append("pyproject.toml")
    for name in REQUIREMENT_FILES:
        path = repo_dir / name
        if path.is_file():
            reqs += _req_lines(path.read_text(encoding="utf-8", errors="replace"))
            sources.append(name)
    normalised = sorted(dict.fromkeys(re.sub(r"\s+", "", r) for r in reqs if r))
    tools = [t for t in TOOLS if not any(re.match(rf"^{t}\b", r, re.I) for r in normalised)]
    return DependencySpec(normalised, sources, (repo_dir / "src").is_dir(), python, tools)


def ensure_env(
    spec: DependencySpec, sandbox: Sandbox, settings: Settings | None = None, network: bool = False
) -> EnvResult:
    settings = settings or get_settings()
    key = spec.key()
    envs = settings.envs_dir.resolve()
    envs.mkdir(parents=True, exist_ok=True)
    final = envs / key
    lock_path = envs / f"{key}.lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (final / ".ready").is_file():
            return EnvResult(key, final, True, True, [])
        building = envs / f"{key}.building"
        if building.exists():
            shutil.rmtree(building)
        prepare_writable_dir(building, settings)
        (building / ".requirements.txt").write_text("\n".join(spec.requirements + spec.tools) + "\n")
        prepare_writable_dir(building, settings)
        mounts = [Mount(building, "/env", writable=True)]
        pip_args = ["/env/bin/python", "-m", "pip", "install", "--quiet", "--no-input"]
        if settings.wheelhouse_dir is not None and not network:
            mounts.append(Mount(settings.wheelhouse_dir.resolve(), "/wheelhouse"))
            pip_args += ["--no-index", "--find-links", "/wheelhouse"]
        else:
            pip_args += ["--only-binary=:all:"]  # never execute sdist build scripts
        limits = Limits.from_settings(settings)
        limits.timeout_s = max(limits.timeout_s, 600)
        logs: list[CommandResult] = []
        steps = [
            [settings.sandbox_python, "-m", "venv", "/env"],
            [*pip_args, "-r", "/env/.requirements.txt"],
            ["/env/bin/python", "-m", "pip", "check"],
        ]
        for argv in steps:
            result = sandbox.run(
                argv, mounts=mounts, cwd="/env", limits=limits, network=network and settings.wheelhouse_dir is None
            )
            logs.append(result)
            if not result.ok:
                tail = (result.stderr or result.stdout)[-2000:]
                return EnvResult(
                    key,
                    building,
                    False,
                    False,
                    logs,
                    error=f"environment step failed ({' '.join(argv[:4])}...): {tail}",
                )
        (building / ".ready").write_text(json.dumps({"requirements": spec.requirements, "tools": spec.tools}))
        building.rename(final)
        return EnvResult(key, final, True, False, logs)


def python_path(spec: DependencySpec) -> str:
    return "/work/src:/work" if spec.src_layout else "/work"
