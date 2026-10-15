import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from webhookrelay.clock import FixedClock
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher
from webhookrelay.payloads import Event
from webhookrelay.transports import HttpxTransport

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def records(caplog, level):
    return [r.getMessage() for r in caplog.records if r.levelno == level]


def make_dispatcher(handler, **config):
    raw = {"targets": {"crm": {"url": "https://crm.example/in"}},
           "rules": [{"events": ["order.*"], "targets": ["crm"]}], **config}
    return Dispatcher(load_config(raw), transport=HttpxTransport(transport=httpx.MockTransport(handler)),
                      clock=FixedClock(T0))


def event(type_):
    return Event("shop", type_, "evt-1", {}, T0, {})


def test_unknown_configuration_keys(caplog):
    with caplog.at_level(logging.DEBUG):
        load_config({"targets": {}, "retries": 3, "Colour": "blue"})
    assert records(caplog, logging.WARNING) == [
        "ignoring unknown configuration key 'Colour'",
        "ignoring unknown configuration key 'retries'",
    ]


def test_unrouted_events(caplog):
    dispatcher = make_dispatcher(lambda request: httpx.Response(200))
    with caplog.at_level(logging.DEBUG):
        assert dispatcher.dispatch(event("user.created")) == []
    assert records(caplog, logging.WARNING) == ["no route for user.created event evt-1 from shop"]


def test_failed_attempts_and_giving_up(caplog):
    dispatcher = make_dispatcher(lambda request: httpx.Response(503), retry={"max_attempts": 2})
    with caplog.at_level(logging.DEBUG):
        [first] = dispatcher.dispatch(event("order.created"))
        dispatcher.deliver(dispatcher.scheduler.pending()[0].payload)
    warnings = records(caplog, logging.WARNING)
    assert warnings == [
        f"delivery {first.delivery_id} to crm failed (attempt 1): HTTP 503",
        f"delivery {first.delivery_id} to crm failed (attempt 2): HTTP 503",
    ]
    assert records(caplog, logging.ERROR) == [f"giving up on delivery {first.delivery_id} to crm after 2 attempt(s)"]


def test_transport_errors_are_logged_as_warnings(caplog):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    dispatcher = make_dispatcher(refuse)
    with caplog.at_level(logging.DEBUG):
        [record] = dispatcher.dispatch(event("order.paid"))
    [message] = records(caplog, logging.WARNING)
    assert message == f"delivery {record.delivery_id} to crm failed (attempt 1): ConnectError: connection refused"


def test_no_deprecated_warn_calls_remain():
    src = Path(os.environ["REPO_ROOT"]) / "src"
    offenders = [
        f"{path.name}:{lineno}"
        for path in src.rglob("*.py")
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"(?<!warnings)\.warn\(", line)
    ]
    assert offenders == []
