"""Isolated command execution.

Untrusted repository code (installation steps, test suites, generated patches) runs through
:class:`Sandbox`. The bubblewrap backend provides:

* separate user, PID, IPC, UTS, cgroup and network namespaces (no network unless explicitly granted)
* a minimal read-only root (``/usr`` only) with a private ``/tmp``; host home directories, ``/root``,
  ``/etc``, sockets (including any Docker socket) and other jobs' workspaces are simply not mounted
* execution as a dedicated unprivileged host uid, so ``RLIMIT_NPROC`` is enforced and an escape from the
  namespaces lands in an unprivileged account
* an empty environment: no host variables, therefore no credentials, are inherited
* rlimits (address space, file size, open files, processes, core dumps) and cgroup v1 memory/pids limits
  where the host allows it
* a wall-clock timeout and cooperative cancellation that kill the whole process tree
* bounded stdout/stderr capture (head and tail are kept)

Residual risks (shared kernel, no seccomp filter, no disk quota) are documented in docs/SECURITY.md.
"""

from __future__ import annotations

import contextlib
import logging
import os
import resource
import shutil
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from modernisation.config import Settings, get_settings

log = logging.getLogger(__name__)

CGROUP_ROOT = Path("/sys/fs/cgroup")


@dataclass
class Mount:
    host: Path
    target: str
    writable: bool = False


@dataclass
class Limits:
    timeout_s: float = 300.0
    memory_mb: int = 2048
    max_processes: int = 256
    max_file_mb: int = 256
    max_open_files: int = 1024
    output_limit_kb: int = 256
    tmp_size_mb: int = 512

    @classmethod
    def from_settings(cls, settings: Settings) -> Limits:
        return cls(
            timeout_s=settings.sandbox_command_timeout_s,
            memory_mb=settings.sandbox_memory_mb,
            max_processes=settings.sandbox_max_processes,
            max_file_mb=settings.sandbox_max_file_mb,
            output_limit_kb=settings.sandbox_output_limit_kb,
        )


@dataclass
class CommandResult:
    argv: list[str]
    exit_code: int | None
    duration_ms: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    isolation: str = "bubblewrap"
    cgroup_enforced: bool = False
    limits: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled


class SandboxUnavailable(RuntimeError):
    pass


class _BoundedReader(threading.Thread):
    """Drain a pipe, keeping the first and last ``limit/2`` bytes."""

    def __init__(self, stream: object, limit: int):
        super().__init__(daemon=True)
        self.stream = stream
        self.limit = max(1024, limit)
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def run(self) -> None:
        half = self.limit // 2
        read = self.stream.read  # type: ignore[attr-defined]
        while True:
            chunk = read(65536)
            if not chunk:
                break
            self.total += len(chunk)
            if len(self.head) < half:
                take = half - len(self.head)
                self.head.extend(chunk[:take])
                chunk = chunk[take:]
            if chunk:
                self.tail.extend(chunk)
                if len(self.tail) > half:
                    del self.tail[: len(self.tail) - half]

    def text(self) -> tuple[str, bool]:
        truncated = self.total > len(self.head) + len(self.tail)
        body = bytes(self.head)
        if truncated:
            body += f"\n...[{self.total - len(self.head) - len(self.tail)} bytes truncated]...\n".encode()
        body += bytes(self.tail)
        return body.decode("utf-8", "replace"), truncated


class _CGroup:
    """Best-effort cgroup v1 memory+pids limits (requires root on the host)."""

    def __init__(self, memory_mb: int, max_processes: int):
        self.name = f"modernisation/{uuid.uuid4().hex[:12]}"
        self.paths: list[Path] = []
        self.enforced = False
        if os.geteuid() != 0:
            return
        try:
            mem = CGROUP_ROOT / "memory" / self.name
            pids = CGROUP_ROOT / "pids" / self.name
            if not (CGROUP_ROOT / "memory").is_dir() or not (CGROUP_ROOT / "pids").is_dir():
                return
            mem.mkdir(parents=True)
            self.paths.append(mem)
            (mem / "memory.limit_in_bytes").write_text(str(memory_mb * 1024 * 1024))
            swap = mem / "memory.memsw.limit_in_bytes"
            if swap.exists():
                swap.write_text(str(memory_mb * 1024 * 1024))
            pids.mkdir(parents=True)
            self.paths.append(pids)
            (pids / "pids.max").write_text(str(max_processes))
            self.enforced = True
        except OSError as exc:
            log.warning("cgroup limits unavailable", extra={"error": str(exc)})
            self.cleanup()
            self.enforced = False

    def attach_self(self) -> None:
        for path in self.paths:
            (path / "cgroup.procs").write_text(str(os.getpid()))

    def cleanup(self) -> None:
        for path in self.paths:
            try:
                # move any stragglers out, then remove the group
                procs = (path / "cgroup.procs").read_text().split() if (path / "cgroup.procs").exists() else []
                for pid in procs:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(int(pid), signal.SIGKILL)
                time.sleep(0.05)
                path.rmdir()
            except OSError:
                pass
        self.paths = []


class Sandbox:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.backend = self.settings.sandbox_backend
        if self.backend == "bubblewrap" and shutil.which("bwrap") is None:
            raise SandboxUnavailable("bubblewrap (bwrap) is not installed; see docs/SECURITY.md")
        if self.backend == "unsandboxed":
            log.warning("UNSANDBOXED execution mode: repository code runs without namespace isolation")
        self.uid = self.settings.sandbox_uid
        self.gid = self.settings.sandbox_gid
        if self.uid == 0:
            raise SandboxUnavailable("sandbox uid must not be 0")

    # -------------------------------------------------------------------------------------------------
    def _bwrap_argv(
        self,
        argv: list[str],
        mounts: list[Mount],
        cwd: str,
        env: dict[str, str],
        network: bool,
        limits: Limits,
        hide: list[str],
    ) -> list[str]:
        cmd = [
            "bwrap",
            "--ro-bind",
            "/usr",
            "/usr",
            "--symlink",
            "usr/lib",
            "/lib",
            "--symlink",
            "usr/lib64",
            "/lib64",
            "--symlink",
            "usr/bin",
            "/bin",
            "--symlink",
            "usr/sbin",
            "/sbin",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--size",
            str(limits.tmp_size_mb * 1024 * 1024),
            "--tmpfs",
            "/tmp",
            "--dir",
            "/etc",
        ]
        for etc in ("/etc/alternatives", "/etc/ld.so.cache", "/etc/localtime"):
            if os.path.exists(etc):
                cmd += ["--ro-bind", etc, etc]
        if network:
            for etc in ("/etc/resolv.conf", "/etc/hosts", "/etc/ssl", "/etc/ca-certificates"):
                if os.path.exists(etc):
                    cmd += ["--ro-bind", etc, etc]
        for m in mounts:
            cmd += ["--bind" if m.writable else "--ro-bind", str(m.host), m.target]
        for target in hide:
            cmd += ["--tmpfs", target]
        cmd += [
            "--chdir",
            cwd,
            "--unshare-all",
            *(["--share-net"] if network else []),
            "--die-with-parent",
            "--new-session",
            "--uid",
            str(self.uid),
            "--gid",
            str(self.gid),
            "--hostname",
            "sandbox",
            "--clearenv",
        ]
        for key, value in env.items():
            cmd += ["--setenv", key, value]
        return [*cmd, "--", *argv]

    def run(
        self,
        argv: list[str],
        *,
        mounts: list[Mount],
        cwd: str = "/work",
        env: dict[str, str] | None = None,
        limits: Limits | None = None,
        network: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        hide: list[str] | None = None,
    ) -> CommandResult:
        limits = limits or Limits.from_settings(self.settings)
        base_env = {
            "PATH": "/env/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "CI": "1",
        }
        base_env.update(env or {})
        if self.backend == "bubblewrap":
            full = self._bwrap_argv(argv, mounts, cwd, base_env, network, limits, hide or [])
            run_env: dict[str, str] = {"PATH": "/usr/bin:/bin"}
            run_cwd = "/"
        else:
            # Unsandboxed: map sandbox mount targets onto host paths for cwd only.
            full = argv
            run_env = base_env
            run_cwd = next((str(m.host) for m in mounts if m.target == cwd), cwd)

        cgroup = _CGroup(limits.memory_mb, limits.max_processes)
        uid, gid = self.uid, self.gid
        drop = os.geteuid() == 0

        def preexec() -> None:
            os.setsid()
            if cgroup.enforced:
                cgroup.attach_self()
            mem = limits.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            fsize = limits.max_file_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            resource.setrlimit(resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            if drop:
                os.setgroups([])
                os.setgid(gid)
                os.setuid(uid)
            resource.setrlimit(resource.RLIMIT_NPROC, (limits.max_processes, limits.max_processes))

        started = time.monotonic()
        timed_out = cancelled = False
        try:
            proc = subprocess.Popen(
                full,
                cwd=run_cwd,
                env=run_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=preexec,
                close_fds=True,
            )
        except OSError as exc:
            cgroup.cleanup()
            return CommandResult(argv, None, 0, "", f"failed to start sandbox: {exc}", isolation=self.backend)

        limit_bytes = limits.output_limit_kb * 1024
        out_reader = _BoundedReader(proc.stdout, limit_bytes)
        err_reader = _BoundedReader(proc.stderr, limit_bytes)
        out_reader.start()
        err_reader.start()
        deadline = started + limits.timeout_s
        while True:
            try:
                proc.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() > deadline:
                    timed_out = True
                elif cancel_check is not None and cancel_check():
                    cancelled = True
                if timed_out or cancelled:
                    self._kill_tree(proc)
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        proc.wait(timeout=10)
                    break
        out_reader.join(timeout=5)
        err_reader.join(timeout=5)
        cgroup_enforced = cgroup.enforced
        cgroup.cleanup()
        stdout, out_trunc = out_reader.text()
        stderr, err_trunc = err_reader.text()
        return CommandResult(
            argv=argv,
            exit_code=proc.returncode,
            duration_ms=int((time.monotonic() - started) * 1000),
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            cancelled=cancelled,
            stdout_truncated=out_trunc,
            stderr_truncated=err_trunc,
            isolation=self.backend,
            cgroup_enforced=cgroup_enforced,
            limits={
                "timeout_s": limits.timeout_s,
                "memory_mb": limits.memory_mb,
                "max_processes": limits.max_processes,
                "max_file_mb": limits.max_file_mb,
            },
        )

    @staticmethod
    def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(ProcessLookupError):
                proc.kill()


def prepare_writable_dir(path: Path, settings: Settings | None = None) -> Path:
    """Create ``path`` owned by the sandbox uid so sandboxed processes can write to it."""
    settings = settings or get_settings()
    path.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        for root, dirs, files in os.walk(path):
            if "/.git" in root or root.endswith("/.git"):
                continue
            os.chown(root, settings.sandbox_uid, settings.sandbox_gid)
            for name in files:
                p = os.path.join(root, name)
                if not os.path.islink(p):
                    os.chown(p, settings.sandbox_uid, settings.sandbox_gid)
            dirs[:] = [d for d in dirs if d != ".git"]
    return path
