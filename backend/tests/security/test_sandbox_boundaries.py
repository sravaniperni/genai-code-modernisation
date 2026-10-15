"""Sandbox boundary tests: each test runs real hostile code inside the real bubblewrap sandbox."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from modernisation.config import get_settings
from modernisation.execution.sandbox import Limits, Mount, Sandbox, prepare_writable_dir

pytestmark = pytest.mark.sandbox

PY = "/usr/bin/python3.12"


@pytest.fixture()
def sandbox() -> Sandbox:
    return Sandbox(get_settings())


@pytest.fixture()
def job(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = Path(get_settings().data_dir) / "sbx" / os.urandom(4).hex()
    base.mkdir(parents=True)
    for p in [base, base.parent]:
        p.chmod(0o755)
    return prepare_writable_dir(base / "work")


def run(sandbox: Sandbox, job: Path, code: str, **kw):  # type: ignore[no-untyped-def]
    limits = kw.pop("limits", Limits(timeout_s=30))
    return sandbox.run([PY, "-c", code], mounts=[Mount(job, "/work", writable=True)], limits=limits, **kw)


def test_runs_as_unprivileged_user_with_empty_environment(sandbox: Sandbox, job: Path):
    os.environ["MODERNISATION_FAKE_SECRET"] = "should-not-leak"
    try:
        res = run(sandbox, job, "import os, json; print(json.dumps({'uid': os.getuid(), 'env': sorted(os.environ)}))")
    finally:
        del os.environ["MODERNISATION_FAKE_SECRET"]
    assert res.ok, res.stderr
    assert '"uid": 9100' in res.stdout
    assert "MODERNISATION" not in res.stdout and "TOKEN" not in res.stdout and "PROXY" not in res.stdout.upper()


def test_network_is_unreachable(sandbox: Sandbox, job: Path):
    code = (
        "import socket\n"
        "for host in [('1.1.1.1', 443), ('127.0.0.1', 5432)]:\n"
        "    s = socket.socket(); s.settimeout(3)\n"
        "    try:\n"
        "        s.connect(host); print('CONNECTED', host)\n"
        "    except OSError as e:\n"
        "        print('blocked', host, e.errno)\n"
    )
    res = run(sandbox, job, code)
    assert "CONNECTED" not in res.stdout
    assert res.stdout.count("blocked") == 2  # includes the host's PostgreSQL on loopback


def test_host_sensitive_paths_are_not_visible(sandbox: Sandbox, job: Path):
    code = (
        "import os\n"
        "for p in ['/root', '/home', '/etc/shadow', '/etc/passwd', '/var/run/docker.sock', '/run/docker.sock',\n"
        "          '/proc/1/environ', '/opt', '/var/lib/postgresql']:\n"
        "    print(p, os.path.exists(p))\n"
    )
    res = run(sandbox, job, code)
    assert res.ok, res.stderr
    for line in res.stdout.splitlines():
        path, exists = line.rsplit(" ", 1)
        if path == "/proc/1/environ":
            continue  # /proc/1 is the sandbox's own init in its PID namespace
        assert exists == "False", f"{path} visible inside sandbox"


def test_pid_namespace_hides_host_processes(sandbox: Sandbox, job: Path):
    res = run(sandbox, job, "import os; print(len([p for p in os.listdir('/proc') if p.isdigit()]))")
    assert res.ok and int(res.stdout.strip()) <= 3


def test_system_directories_are_read_only(sandbox: Sandbox, job: Path):
    res = run(sandbox, job, "open('/usr/lib/evil.txt', 'w').write('x')")
    assert not res.ok and ("Read-only" in res.stderr or "Permission denied" in res.stderr)


def test_workspace_is_writable_and_owned_by_sandbox_uid(sandbox: Sandbox, job: Path):
    res = run(sandbox, job, "open('/work/out.txt', 'w').write('ok')")
    assert res.ok, res.stderr
    assert (job / "out.txt").stat().st_uid == 9100


def test_other_jobs_workspaces_are_invisible(sandbox: Sandbox, job: Path, tmp_path: Path):
    other = prepare_writable_dir(job.parent / "other-job")
    (other / "secret.txt").write_text("job-b-data")
    code = (
        "import os\n"
        f"print(os.path.exists({str(other)!r}), os.path.exists({str(job.parent)!r}))\n"
        "print(sorted(os.listdir('/')))\n"
    )
    res = run(sandbox, job, code)
    assert res.ok, res.stderr
    assert res.stdout.splitlines()[0] == "False False"


def test_timeout_kills_entire_process_tree(sandbox: Sandbox, job: Path):
    code = (
        "import subprocess, time\n"
        "subprocess.Popen(['/usr/bin/python3.12', '-c', "
        '\'import time; time.sleep(8); open("/work/orphan.txt","w").write("alive")\'])\n'
        "time.sleep(60)\n"
    )
    started = time.monotonic()
    res = run(sandbox, job, code, limits=Limits(timeout_s=2))
    assert res.timed_out and not res.ok
    assert time.monotonic() - started < 15
    time.sleep(9)
    assert not (job / "orphan.txt").exists(), "child process survived the timeout"


def test_cancellation_stops_command(sandbox: Sandbox, job: Path):
    flag = {"n": 0}

    def cancel() -> bool:
        flag["n"] += 1
        return flag["n"] > 4

    res = run(sandbox, job, "import time; time.sleep(60)", cancel_check=cancel)
    assert res.cancelled and not res.ok and res.duration_ms < 10000


def test_fork_bomb_is_contained(sandbox: Sandbox, job: Path):
    code = (
        "import os, time\n"
        "pids = []\n"
        "try:\n"
        "    for _ in range(500):\n"
        "        pid = os.fork()\n"
        "        if pid == 0:\n"
        "            time.sleep(5); os._exit(0)\n"
        "        pids.append(pid)\n"
        "    print('spawned', len(pids))\n"
        "except OSError as e:\n"
        "    print('limited after', len(pids), e.errno)\n"
    )
    res = run(sandbox, job, code, limits=Limits(timeout_s=30, max_processes=40))
    assert "limited after" in res.stdout, res.stdout + res.stderr
    assert int(res.stdout.split()[2]) < 60


def test_memory_limit_enforced(sandbox: Sandbox, job: Path):
    code = "b = bytearray(1500 * 1024 * 1024); print('allocated')"
    res = run(sandbox, job, code, limits=Limits(timeout_s=30, memory_mb=512))
    assert "allocated" not in res.stdout
    assert "MemoryError" in res.stderr or res.exit_code != 0


def test_file_size_limit_enforced(sandbox: Sandbox, job: Path):
    code = "f = open('/work/big.bin', 'wb')\nfor _ in range(64): f.write(b'0' * 1024 * 1024)\nprint('wrote')"
    res = run(sandbox, job, code, limits=Limits(timeout_s=30, max_file_mb=8))
    assert "wrote" not in res.stdout
    assert (job / "big.bin").stat().st_size <= 8 * 1024 * 1024


def test_output_flood_is_truncated(sandbox: Sandbox, job: Path):
    res = run(
        sandbox,
        job,
        "import sys\nfor _ in range(200000): sys.stdout.write('x' * 50 + '\\n')",
        limits=Limits(timeout_s=30, output_limit_kb=64),
    )
    assert res.ok and res.stdout_truncated
    assert len(res.stdout) < 80 * 1024


def test_git_metadata_hidden_from_sandbox(sandbox: Sandbox, job: Path):
    (job / ".git").mkdir()
    (job / ".git" / "config").write_text("[core]\n")
    res = sandbox.run(
        [PY, "-c", "import os; print(os.listdir('/work/.git'))"],
        mounts=[Mount(job, "/work", writable=True)],
        hide=["/work/.git"],
        limits=Limits(timeout_s=20),
    )
    assert res.ok and res.stdout.strip() == "[]"
