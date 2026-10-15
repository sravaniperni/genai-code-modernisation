import importlib.metadata
from datetime import datetime, timezone

import pytest
import urllib3
from urllib3.exceptions import MaxRetryError, NewConnectionError
from urllib3.response import HTTPResponse

from webhookrelay.clock import FixedClock
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher
from webhookrelay.payloads import Event
from webhookrelay.transports import TransportError, Urllib3Transport, build_pool_retry


class FakePool:
    def __init__(self, *responses, error=None):
        self.responses = list(responses)
        self.error = error
        self.calls = []

    def urlopen(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def backoff_after(retry, failures):
    for _ in range(failures):
        retry = retry.increment(method="POST", url="/in")
    return retry.get_backoff_time()


def test_urllib3_version_is_pinned():
    assert importlib.metadata.version("urllib3") == "2.5.0"


def test_pooled_transport_sends_through_the_pool():
    response = HTTPResponse(body=b'{"accepted": true}', headers={"Content-Type": "application/json",
                                                                   "X-Request-Id": "req-7"}, status=202)
    pool = FakePool(response)
    transport = Urllib3Transport(pool=pool, retries=5, backoff_factor=1, timeout=4)
    result = transport.send("POST", "https://bulk.example/in?x=1", body=b"{}", headers={"X-Relay-Delivery": "d-1"})
    assert (result.status, result.ok, result.body) == (202, True, '{"accepted": true}')
    assert result.headers == {"content-type": "application/json", "x-request-id": "req-7"}
    method, url, kwargs = pool.calls[0]
    assert (method, url, kwargs["body"]) == ("POST", "https://bulk.example/in?x=1", b"{}")
    assert kwargs["headers"]["X-Relay-Delivery"] == "d-1"
    assert kwargs["headers"]["User-Agent"].startswith("webhookrelay/")
    assert kwargs.get("redirect") is False
    retry = kwargs.get("retries", transport.retry)
    assert isinstance(retry, urllib3.util.Retry)
    assert retry.total == 5
    timeout = kwargs.get("timeout", transport.timeout)
    assert timeout.connect_timeout == 4 and timeout.read_timeout == 4


def test_default_pool_is_a_real_pool_manager():
    transport = Urllib3Transport()
    assert isinstance(transport.pool, urllib3.PoolManager)
    transport.close()


def test_pool_retry_methods_and_statuses():
    retry = build_pool_retry(total=3)
    for method in ("POST", "PUT", "GET", "DELETE"):
        for status in (429, 502, 503, 504):
            assert retry.is_retry(method, status), (method, status)
        assert not retry.is_retry(method, 400)
        assert not retry.is_retry(method, 500)
    assert not retry.is_retry("PATCH", 503)
    assert retry.raise_on_status is False
    assert retry.total == 3


def test_pool_retry_backoff_is_exponential_and_capped_at_30s():
    retry = build_pool_retry(total=20, backoff_factor=1)
    assert [backoff_after(retry, n) for n in range(2, 6)] == [2, 4, 8, 16]
    assert backoff_after(retry, 6) == 30
    assert backoff_after(retry, 12) == 30
    assert backoff_after(build_pool_retry(total=20, backoff_factor=0.5), 4) == 4


def test_retries_run_out():
    retry = build_pool_retry(total=2)
    retry = retry.increment(method="POST", url="/in")
    retry = retry.increment(method="POST", url="/in")
    with pytest.raises(MaxRetryError):
        retry.increment(method="POST", url="/in")


def test_connection_failures_become_transport_errors():
    reason = NewConnectionError(None, "Failed to establish a new connection")
    pool = FakePool(error=MaxRetryError(None, "/in", reason))
    with pytest.raises(TransportError, match="MaxRetryError"):
        Urllib3Transport(pool=pool).send("POST", "https://bulk.example/in", body=b"", headers={})


def test_dispatcher_with_pooled_transport():
    pool = FakePool(HTTPResponse(body=b"busy", headers={"Retry-After": "7"}, status=503))
    config = load_config({"targets": {"bulk": {"url": "https://bulk.example/in", "transport": "pool"}},
                          "rules": [{"targets": ["bulk"]}]})
    t0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    dispatcher = Dispatcher(config, transport=Urllib3Transport(pool=pool), clock=FixedClock(t0))
    [record] = dispatcher.dispatch(Event("shop", "order.created", "o-1", {}, t0, {}))
    assert record.status == 503
    assert record.to_dict()["next_retry_at"] == "2026-01-01T12:00:07Z"
