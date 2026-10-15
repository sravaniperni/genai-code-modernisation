import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from webhookrelay.clock import FixedClock
from webhookrelay.scheduler import RetryScheduler

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def workers():
    return [t for t in threading.enumerate() if t.name == "webhookrelay-retry"]


def make_scheduler(seen, fired):
    def callback(item):
        seen.append(item)
        fired.set()

    return RetryScheduler(callback, clock=FixedClock(T0), poll_interval=0.01)


def test_worker_lifecycle():
    seen, fired = [], threading.Event()
    scheduler = make_scheduler(seen, fired)
    assert not scheduler.running
    assert scheduler.describe() == {"running": False, "worker": None, "pending": 0, "next_due": None}
    scheduler.start()
    try:
        assert scheduler.running
        [worker] = workers()
        assert worker.daemon is True
        scheduler.start()
        assert workers() == [worker]
        described = scheduler.describe()
        assert described["running"] is True and described["worker"] == "webhookrelay-retry"
        scheduler.schedule("due", T0 - timedelta(seconds=5))
        scheduler.schedule("later", T0 + timedelta(hours=1))
        assert fired.wait(10)
        assert seen == ["due"]
        assert scheduler.describe()["next_due"] == "2026-01-01T13:00:00Z"
    finally:
        scheduler.stop()
    assert not scheduler.running
    assert workers() == []
    assert scheduler.describe()["worker"] is None


def test_restart_after_stop():
    seen, fired = [], threading.Event()
    scheduler = make_scheduler(seen, fired)
    scheduler.start()
    scheduler.stop()
    assert not scheduler.running
    scheduler.schedule("again", T0)
    scheduler.start()
    try:
        assert scheduler.running and len(workers()) == 1 and workers()[0].daemon
        assert fired.wait(10)
        assert seen == ["again"]
    finally:
        scheduler.stop()
    assert workers() == []


def test_callback_errors_do_not_kill_the_worker():
    calls, bad_seen, good_seen = [], threading.Event(), threading.Event()

    def callback(item):
        calls.append(item)
        if item == "bad":
            bad_seen.set()
            raise RuntimeError("downstream exploded")
        good_seen.set()

    scheduler = RetryScheduler(callback, clock=FixedClock(T0), poll_interval=0.01)
    scheduler.schedule("bad", T0 - timedelta(seconds=2))
    scheduler.start()
    try:
        assert bad_seen.wait(10)
        scheduler.schedule("good", T0 - timedelta(seconds=1))
        assert good_seen.wait(10)
        assert scheduler.running
    finally:
        scheduler.stop()
    assert calls == ["bad", "good"]


def test_deprecated_threading_aliases_are_gone():
    src = Path(os.environ["REPO_ROOT"]) / "src"
    pattern = re.compile(r"\.(setDaemon|isSet|getName|setName|isDaemon)\(|currentThread\(|activeCount\(")
    offenders = [
        f"{path.name}:{lineno}"
        for path in src.rglob("*.py")
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []
