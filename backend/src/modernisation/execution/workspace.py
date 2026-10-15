"""Per-job working copies.

A workspace is a private clone of the repository mirror checked out (detached) at the task's base commit.
Its state is always reproducible from the database: ``base commit + recorded cumulative diff``. Before
each attempt the workspace is reset to the base commit and the previous diff re-applied, so files created
by test runs never leak into a patch and a crashed job can be rebuilt exactly.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from modernisation.agents.edits import Edit, EditError, apply_edits
from modernisation.config import Settings, get_settings
from modernisation.execution.policy import ChangePolicy, PolicyViolation, safe_target
from modernisation.execution.sandbox import Mount, prepare_writable_dir
from modernisation.repository_intelligence.git_ops import GitError, GitRepo, run_git

EXCLUDES = """__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
.coverage.*
htmlcov/
*.egg-info/
.tox/
.nox/
.hypothesis/
"""


class WorkspaceError(RuntimeError):
    pass


@dataclass
class AppliedChange:
    diff: str
    files_changed: list[str]


class Workspace:
    def __init__(
        self, job_key: str, mirror: GitRepo, base_commit: str, settings: Settings | None = None, label: str = "agent"
    ):
        self.settings = settings or get_settings()
        self.mirror = mirror
        self.base_commit = base_commit
        self.root = (self.settings.workspaces_dir / job_key / label).resolve()
        self.repo_dir = self.root / "repo"
        self.out_dir = self.root / "out"

    # --------------------------------------------------------------------------------------------------
    def _git(self, *args: str, check: bool = True, input_bytes: bytes | None = None) -> str:
        proc = run_git(["-c", "safe.directory=*", *args], cwd=self.repo_dir, check=check, input_bytes=input_bytes)
        return proc.stdout.decode("utf-8", "replace")

    def create(self) -> None:
        if not self.mirror.has_commit(self.base_commit):
            raise WorkspaceError(f"base commit {self.base_commit} is not present in the repository mirror")
        if (self.repo_dir / ".git").exists():
            self.reset()
            return
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        run_git(
            ["clone", "--quiet", "--no-checkout", "--no-hardlinks", "--", str(self.mirror.path), str(self.repo_dir)]
        )
        (self.repo_dir / ".git" / "info").mkdir(parents=True, exist_ok=True)
        (self.repo_dir / ".git" / "info" / "exclude").write_text(EXCLUDES)
        self._git("checkout", "--quiet", "--detach", self.base_commit)
        self.verify_base()
        self._prepare_permissions()

    def verify_base(self) -> None:
        head = self._git("rev-parse", "HEAD").strip()
        if head != self.base_commit:
            raise WorkspaceError(f"workspace HEAD {head} does not match expected base {self.base_commit}")

    def reset(self) -> None:
        self._git("reset", "--quiet", "--hard", self.base_commit)
        self._git("clean", "-ffdxq")
        self.verify_base()
        self._prepare_permissions()

    def _prepare_permissions(self) -> None:
        prepare_writable_dir(self.repo_dir, self.settings)
        prepare_writable_dir(self.out_dir, self.settings)

    def destroy(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def mounts(self) -> list[Mount]:
        return [Mount(self.repo_dir, "/work", writable=True), Mount(self.out_dir, "/out", writable=True)]

    @staticmethod
    def hidden_paths() -> list[str]:
        # The sandbox never sees git metadata (no hook/config tampering, no history mining).
        return ["/work/.git"]

    # --------------------------------------------------------------------------------------------------
    def read(self, rel_path: str) -> str | None:
        target = safe_target(self.repo_dir, rel_path)
        if not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return None

    def apply_diff(self, diff: str, policy: ChangePolicy) -> None:
        if not diff.strip():
            return
        for path in self.paths_in_diff(diff):
            policy.check_path(path)
        try:
            self._git("apply", "--whitespace=nowarn", "--binary", "-", input_bytes=diff.encode())
        except GitError as exc:
            raise WorkspaceError(f"recorded diff no longer applies: {exc}") from exc
        self._prepare_permissions()

    @staticmethod
    def paths_in_diff(diff: str) -> list[str]:
        paths: list[str] = []
        for line in diff.splitlines():
            if line.startswith("diff --git "):
                parts = line.split(" ")
                for token in parts[2:4]:
                    if token.startswith(("a/", "b/")):
                        paths.append(token[2:])
        return list(dict.fromkeys(paths))

    def apply_edits(self, edits: list[Edit], policy: ChangePolicy) -> AppliedChange:
        """Validate and apply model edits; nothing is written unless every edit is valid."""
        if not edits:
            raise EditError("no_edits", "the response contained no SEARCH/REPLACE blocks")
        files: dict[str, str | None] = {}
        normalised: list[Edit] = []
        for edit in edits:
            path = policy.check_path(edit.path)
            normalised.append(Edit(path, edit.search, edit.replace, whole_file=edit.whole_file))
            if path not in files:
                files[path] = self.read(path)
                target = safe_target(self.repo_dir, path)
                if target.exists() and files[path] is None:
                    raise EditError("binary_file", f"{path} is not a UTF-8 text file", path)
        if len(files) > policy.max_files:
            raise PolicyViolation("too_many_files", f"edit touches {len(files)} files (limit {policy.max_files})")
        updated = apply_edits(files, normalised)
        for path, content in updated.items():
            policy.check_content(path, files.get(path), content)
        for path, content in updated.items():
            if content == files.get(path):
                continue
            target = safe_target(self.repo_dir, path)
            if content is None:
                target.unlink(missing_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
        self._prepare_permissions()
        return self.current_change()

    def current_change(self) -> AppliedChange:
        # Re-hash tracked files from content: a same-size edit within the stat cache's time
        # granularity would otherwise be invisible to git.
        self._git("add", "--renormalize", ".")
        self._git("add", "-A")
        diff = self._git("diff", "--cached", "--binary", self.base_commit)
        names = [n for n in self._git("diff", "--cached", "--name-only", self.base_commit).splitlines() if n]
        return AppliedChange(diff=diff, files_changed=names)
