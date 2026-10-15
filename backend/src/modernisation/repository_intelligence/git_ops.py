"""Thin, safe wrapper over the git command line.

Commands are always passed as argument lists (never through a shell), run with a scrubbed environment
(no credential helpers, no interactive prompts, no user/system git config) and a timeout.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
# Refs we accept from API callers: branch/tag names or SHAs, no option injection, no ranges.
SAFE_REF_RE = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/\-]{1,200}$")


class GitError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str):
        shown = " ".join(a for a in args if not a.startswith("-c") and "=" not in a)[:120]
        super().__init__(f"git {shown} failed ({returncode}): {stderr.strip()[:500]}")
        self.returncode = returncode
        self.stderr = stderr


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/nonexistent",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ASKPASS": "/bin/false",
        "LC_ALL": "C",
    }
    # Outbound HTTPS may need a proxy and CA bundle; these carry no repository credentials.
    for key in ("HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy", "SSL_CERT_FILE", "GIT_SSL_CAINFO"):
        if key in os.environ:
            env[key] = os.environ[key]
    if extra:
        env.update(extra)
    return env


def run_git(
    args: list[str],
    cwd: Path | None = None,
    *,
    input_bytes: bytes | None = None,
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    base = ["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=always"]
    proc = subprocess.run(
        base + args,
        cwd=cwd,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        env=git_env(env),
        check=False,
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or proc.stdout.decode("utf-8", "replace")
        raise GitError(args, proc.returncode, detail)
    return proc


def validate_ref(ref: str) -> str:
    if not SAFE_REF_RE.match(ref):
        raise ValueError(f"unsafe or malformed git ref: {ref!r}")
    return ref


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    kind: str
    sha: str
    size: int
    path: str


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    author: str
    authored_at: str
    subject: str


class GitRepo:
    """Operations against a (usually bare) repository directory."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def git(self, *args: str, timeout: float = 120.0, input_bytes: bytes | None = None) -> str:
        proc = run_git(list(args), cwd=self.path, timeout=timeout, input_bytes=input_bytes)
        return proc.stdout.decode("utf-8", "replace")

    def resolve(self, ref: str) -> str:
        validate_ref(ref)
        out = self.git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").strip()
        if not SHA_RE.match(out):
            raise GitError(["rev-parse", ref], 1, f"unexpected output {out!r}")
        return out

    def has_commit(self, sha: str) -> bool:
        proc = run_git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=self.path, check=False)
        return proc.returncode == 0

    def ls_tree(self, sha: str) -> list[TreeEntry]:
        raw = run_git(["ls-tree", "-r", "-l", "-z", "--full-tree", sha], cwd=self.path).stdout
        entries: list[TreeEntry] = []
        for record in raw.split(b"\0"):
            if not record:
                continue
            meta, _, path = record.partition(b"\t")
            mode, kind, obj, size = meta.decode().split(None, 3)
            if kind != "blob":
                continue  # submodules (commit entries) are not indexed
            entries.append(
                TreeEntry(mode, kind, obj, int(size) if size.strip() != "-" else 0, path.decode("utf-8", "replace"))
            )
        return entries

    def read_blobs(self, shas: Iterable[str]) -> Iterator[tuple[str, bytes]]:
        """Stream blob contents with a single `git cat-file --batch` process."""
        wanted = list(dict.fromkeys(shas))
        if not wanted:
            return
        proc = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=self.path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=git_env(),
        )
        assert proc.stdin is not None and proc.stdout is not None
        try:
            for sha in wanted:
                proc.stdin.write(sha.encode() + b"\n")
                proc.stdin.flush()
                header = proc.stdout.readline().decode().split()
                if len(header) < 3 or header[1] == "missing":
                    continue
                size = int(header[2])
                data = proc.stdout.read(size)
                proc.stdout.read(1)  # trailing newline
                yield sha, data
        finally:
            proc.stdin.close()
            proc.wait(timeout=30)

    def read_file(self, sha: str, path: str) -> bytes:
        return run_git(["show", f"{sha}:{path}"], cwd=self.path).stdout

    def log(self, ref: str, limit: int = 20) -> list[CommitInfo]:
        validate_ref(ref)
        out = self.git("log", f"-n{int(limit)}", "--format=%H%x1f%an%x1f%aI%x1f%s", "--end-of-options", ref)
        commits = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append(CommitInfo(*parts))
        return commits

    def branches(self) -> dict[str, str]:
        out = self.git("for-each-ref", "--format=%(refname:short)%09%(objectname)", "refs/heads")
        result = {}
        for line in out.splitlines():
            name, _, sha = line.partition("\t")
            result[name] = sha
        return result

    def changed_paths(self, old: str, new: str) -> list[tuple[str, str]]:
        out = self.git("diff", "--name-status", "--no-renames", old, new)
        result = []
        for line in out.splitlines():
            status, _, path = line.partition("\t")
            result.append((status, path))
        return result

    def grep(
        self, sha: str, pattern: str, *, fixed: bool = True, ignore_case: bool = True, max_count: int = 200
    ) -> list[tuple[str, int, str]]:
        args = ["grep", "-n", "-I", "--no-color", f"--max-count={max_count}"]
        if fixed:
            args.append("-F")
        if ignore_case:
            args.append("-i")
        args += ["-e", pattern, sha]
        proc = run_git(args, cwd=self.path, check=False)
        if proc.returncode not in (0, 1):
            raise GitError(args, proc.returncode, proc.stderr.decode("utf-8", "replace"))
        hits = []
        prefix = f"{sha}:"
        for line in proc.stdout.decode("utf-8", "replace").splitlines():
            if line.startswith(prefix):
                line = line[len(prefix) :]
            path, _, rest = line.partition(":")
            lineno, _, text = rest.partition(":")
            if lineno.isdigit():
                hits.append((path, int(lineno), text))
        return hits


def mirror_repository(
    clone_url: str, dest: Path, *, timeout: float = 600.0, extra_env: dict[str, str] | None = None
) -> GitRepo:
    """Create or refresh a bare mirror at ``dest``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if (dest / "HEAD").exists():
        run_git(["remote", "set-url", "origin", clone_url], cwd=dest)
        run_git(
            ["fetch", "--prune", "origin", "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"],
            cwd=dest,
            timeout=timeout,
            env=extra_env,
        )
    else:
        run_git(["clone", "--mirror", "--", clone_url, str(dest)], timeout=timeout, env=extra_env)
    return GitRepo(dest)
