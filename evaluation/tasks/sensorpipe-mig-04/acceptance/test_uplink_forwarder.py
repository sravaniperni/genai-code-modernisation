import os
import re
import threading
from pathlib import Path

import pytest

from sensorpipe.uplink import Forwarder


class Uplink:
    def __init__(self, accept=True):
        self.accept = accept
        self.batches = []

    def send(self, batch):
        self.batches.append(list(batch))
        if isinstance(self.accept, Exception):
            raise self.accept
        return self.accept


@pytest.fixture
def forwarders():
    created = []

    def make(fetch, send, name):
        forwarder = Forwarder(fetch, send, interval=3600, name=name)
        created.append(forwarder)
        return forwarder

    yield make
    for forwarder in created:
        forwarder.stop()


def test_runs_in_named_daemon_thread(forwarders):
    forwarder = forwarders(lambda: [], Uplink().send, "acc-uplink-daemon").start()
    threads = [t for t in threading.enumerate() if t.name == "acc-uplink-daemon"]
    assert len(threads) == 1 and threads[0].daemon
    assert forwarder.running
    forwarder.stop()
    assert not forwarder.running
    assert not any(t.name == "acc-uplink-daemon" for t in threading.enumerate())


def test_flush_delivers_batches_in_order(forwarders):
    pending = [["a", "b"], [], ["c"]]
    uplink = Uplink()
    forwarder = forwarders(lambda: pending.pop(0) if pending else [], uplink.send, "acc-uplink-flush").start()
    for _ in range(4):
        assert forwarder.flush(timeout=10)
    assert uplink.batches == [["a", "b"], ["c"]]
    assert forwarder.delivered == 3 and forwarder.failures == 0


def test_failures_are_counted_and_retried(forwarders):
    uplink = Uplink(accept=False)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("buffer locked")
        return ["r1", "r2"]

    forwarder = forwarders(fetch, uplink.send, "acc-uplink-retry").start()
    assert forwarder.flush(timeout=10)          # rejected by the uplink
    assert forwarder.flush(timeout=10)          # fetch raises
    uplink.accept = ConnectionError("uplink down")
    assert forwarder.flush(timeout=10)          # send raises
    assert forwarder.failures == 3 and forwarder.delivered == 0 and forwarder.running
    uplink.accept = True
    assert forwarder.flush(timeout=10)
    assert forwarder.delivered == 2 and forwarder.failures == 3


def test_not_running_before_start():
    forwarder = Forwarder(lambda: [], lambda batch: True, name="acc-uplink-idle")
    assert not forwarder.running


def test_deprecated_threading_aliases_are_gone():
    src = Path(os.environ.get("REPO_ROOT", ".")) / "src"
    pattern = re.compile(r"\.(?:setDaemon|isDaemon|isSet|getName|setName)\(|\b(?:currentThread|activeCount)\(")
    offenders = [f"{p.name}: {m.group(0)}" for p in src.rglob("*.py") for m in pattern.finditer(p.read_text())]
    assert offenders == []
