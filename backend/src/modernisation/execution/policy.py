"""Deterministic change policy.

These rules are enforced in code on every proposed edit and again on the final diff. They do not depend
on the model following instructions, so prompt-injected repository content cannot widen what the agent
is permitted to change.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from modernisation.repository_intelligence.languages import is_test_path

ALWAYS_FORBIDDEN = [
    ".git",
    ".git/**",
    "**/.git/**",
    ".github/workflows/**",
    ".gitmodules",
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/id_rsa*",
]

TEST_WEAKENING_PATTERNS = [
    re.compile(r"@pytest\.mark\.(skip|skipif|xfail)\b"),
    re.compile(r"\bpytest\.(skip|xfail)\("),
    re.compile(r"@unittest\.(skip|skipIf|skipUnless|expectedFailure)\b"),
    re.compile(r"\bcollect_ignore\b"),
    re.compile(r"--deselect|--ignore[= ]"),
]
TEST_FUNC_RE = re.compile(r"^\s*(async\s+)?def\s+(test_\w+)", re.MULTILINE)


class PolicyViolation(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ChangePolicy:
    allowed_paths: list[str] = field(default_factory=list)  # globs; empty means whole repository
    forbidden_paths: list[str] = field(default_factory=list)
    allow_test_changes: bool = True
    allow_workflow_changes: bool = False
    max_files: int = 25
    max_file_bytes: int = 512_000

    def normalise(self, raw: str) -> str:
        """Validate a repository-relative path and return its normalised POSIX form."""
        if not raw or "\0" in raw:
            raise PolicyViolation("invalid_path", "empty or NUL-containing path")
        if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw):
            raise PolicyViolation("absolute_path", f"absolute paths are not allowed: {raw!r}")
        p = PurePosixPath(raw.replace("\\", "/"))
        if any(part == ".." for part in p.parts):
            raise PolicyViolation("path_traversal", f"path traversal is not allowed: {raw!r}")
        norm = str(PurePosixPath(*[part for part in p.parts if part not in ("", ".")]))
        if norm in ("", "."):
            raise PolicyViolation("invalid_path", f"invalid path {raw!r}")
        return norm

    def check_path(self, raw: str) -> str:
        path = self.normalise(raw)
        forbidden = list(ALWAYS_FORBIDDEN) + list(self.forbidden_paths)
        if self.allow_workflow_changes:
            forbidden.remove(".github/workflows/**")
        for pattern in forbidden:
            if _match(path, pattern):
                raise PolicyViolation("forbidden_path", f"{path} matches protected pattern {pattern!r}")
        if self.allowed_paths and not any(_match(path, pattern) for pattern in self.allowed_paths):
            raise PolicyViolation("out_of_scope", f"{path} is outside the authorised scope {self.allowed_paths}")
        if is_test_path(path) and not self.allow_test_changes:
            raise PolicyViolation("test_change_forbidden", f"test files may not be modified in this task: {path}")
        return path

    def check_content(self, path: str, old: str | None, new: str | None) -> None:
        if new is not None and len(new.encode()) > self.max_file_bytes:
            raise PolicyViolation("file_too_large", f"{path} would exceed {self.max_file_bytes} bytes")
        if not is_test_path(path):
            return
        if new is None:
            raise PolicyViolation("test_deleted", f"deleting test file {path} is not allowed")
        old_tests = set(m.group(2) for m in TEST_FUNC_RE.finditer(old or ""))
        new_tests = set(m.group(2) for m in TEST_FUNC_RE.finditer(new))
        removed = old_tests - new_tests
        if removed:
            raise PolicyViolation("test_removed", f"removing tests is not allowed: {sorted(removed)[:5]} in {path}")
        for pattern in TEST_WEAKENING_PATTERNS:
            old_hits = len(pattern.findall(old or ""))
            new_hits = len(pattern.findall(new))
            if new_hits > old_hits:
                raise PolicyViolation("test_weakened", f"adding skip/xfail/deselect markers is not allowed ({path})")


def _match(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return (
            path == prefix
            or path.startswith(prefix + "/")
            or (prefix.startswith("**/") and f"/{prefix[3:]}/" in f"/{path}/")
        )
    if pattern.startswith("**/"):
        return fnmatch.fnmatchcase(PurePosixPath(path).name, pattern[3:]) or fnmatch.fnmatchcase(path, pattern[3:])
    return False


def safe_target(workspace: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` inside ``workspace`` refusing any symlink component or escape."""
    root = workspace.resolve()
    target = root / rel_path
    current = root
    for part in PurePosixPath(rel_path).parts:
        current = current / part
        if current.is_symlink():
            raise PolicyViolation("symlink_path", f"refusing to write through symlink {rel_path}")
    resolved = Path(os.path.realpath(target))
    if os.path.commonpath([str(root), str(resolved)]) != str(root):
        raise PolicyViolation("path_escape", f"{rel_path} resolves outside the workspace")
    return target
