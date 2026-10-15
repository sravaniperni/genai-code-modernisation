import os
import re
import threading
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ledgerkit.rates import Rate, RateRefresher, RateTable

NAME = "ledgerkit-rate-refresher"


def _workers():
    return [t for t in threading.enumerate() if t.name == NAME and t.is_alive()]


def _provider(calls):
    def provide():
        calls.append(len(calls) + 1)
        return [Rate("EUR", "USD", Decimal("1.08") + Decimal(len(calls)) / 100, date(2024, 5, len(calls)))]
    return provide


@pytest.fixture
def refresher():
    calls: list[int] = []
    instance = RateRefresher(RateTable(), _provider(calls), interval=3600)
    instance.calls = calls
    yield instance
    instance.stop()


def test_worker_is_a_named_daemon_thread_that_refreshes_immediately(refresher):
    assert not refresher.running
    refresher.start()
    assert refresher.wait_for_refresh(timeout=10)
    assert refresher.running
    (worker,) = _workers()
    assert worker.daemon
    assert refresher.calls == [1]
    assert refresher.table.rate("EUR", "USD") == Decimal("1.09")
    refresher.stop()
    assert not refresher.running
    assert _workers() == []


def test_double_start_and_restart(refresher):
    refresher.start()
    assert refresher.wait_for_refresh(timeout=10)
    with pytest.raises(RuntimeError):
        refresher.start()
    refresher.stop()
    refresher.start()
    assert refresher.wait_for_refresh(timeout=10)
    assert refresher.running and refresher.refreshes == 2
    assert len(_workers()) == 1


def test_stop_is_prompt_with_long_interval(refresher):
    refresher.start()
    assert refresher.wait_for_refresh(timeout=10)
    started = time.monotonic()
    refresher.stop()
    assert time.monotonic() - started < 3
    assert _workers() == []


def test_provider_errors_are_recorded_and_the_worker_survives():
    calls: list[int] = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("rate feed unavailable")
        return [Rate("GBP", "USD", Decimal("1.27"), date(2024, 5, 2))]

    refresher = RateRefresher(RateTable(), flaky, interval=0.01)
    refresher.start()
    try:
        assert refresher.wait_for_refresh(timeout=10)
        assert isinstance(refresher.last_error, ConnectionError)
        assert str(refresher.last_error) == "rate feed unavailable"
        assert refresher.running
        assert refresher.table.rate("GBP", "USD") == Decimal("1.27")
    finally:
        refresher.stop()
    assert not refresher.running


def test_refresh_once_without_thread():
    refresher = RateRefresher(RateTable(), lambda: [Rate("USD", "JPY", Decimal("151.2"), date(2024, 5, 1))])
    assert refresher.refresh_once() == 1
    assert refresher.refreshes == 1 and _workers() == []


def test_deprecated_aliases_are_gone():
    source = Path(os.environ["REPO_ROOT"], "src", "ledgerkit")
    pattern = re.compile(r"\.(setDaemon|setName|getName|isDaemon|isSet)\(|currentThread\(|activeCount\(")
    assert [str(p) for p in source.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))] == []
