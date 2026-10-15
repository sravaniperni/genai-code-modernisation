import httpx
import pytest
from urllib3.response import HTTPResponse

from webhookrelay.transports import HttpxTransport, TransportError, Urllib3Transport, build_pool_retry


class FakePool:
    """Stands in for a urllib3 PoolManager; records calls and returns a canned response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def urlopen(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def test_httpx_transport_returns_normalised_response():
    def handler(request):
        assert request.headers["user-agent"].startswith("webhookrelay/")
        assert request.content == b"{}"
        return httpx.Response(201, headers={"X-Request-Id": "r-1"}, text="created")

    transport = HttpxTransport(transport=httpx.MockTransport(handler))
    response = transport.send("POST", "https://t.example/in", body=b"{}", headers={"X-Test": "1"})
    assert (response.status, response.ok, response.body) == (201, True, "created")
    assert response.headers["x-request-id"] == "r-1"


def test_httpx_transport_wraps_errors():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    transport = HttpxTransport(transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError, match="ReadTimeout"):
        transport.send("POST", "https://t.example/in", body=b"", headers={})


def test_urllib3_transport_uses_pool():
    pool = FakePool(HTTPResponse(body=b"accepted", headers={"Content-Type": "text/plain"}, status=202))
    transport = Urllib3Transport(pool=pool, retries=4)
    response = transport.send("POST", "https://t.example/in", body=b"payload", headers={"X-Relay-Delivery": "d1"})
    assert (response.status, response.body, response.headers["content-type"]) == (202, "accepted", "text/plain")
    method, url, kwargs = pool.calls[0]
    assert (method, url, kwargs["body"]) == ("POST", "https://t.example/in", b"payload")
    assert kwargs["headers"]["X-Relay-Delivery"] == "d1"
    assert kwargs["retries"] is transport.retry and kwargs["retries"].total == 4


def test_pool_retry_covers_post_and_transient_statuses():
    retry = build_pool_retry(total=3)
    assert retry.is_retry("POST", 503)
    assert retry.is_retry("GET", 429)
    assert not retry.is_retry("POST", 400)


def test_pool_retry_backoff_is_capped_at_30_seconds():
    retry = build_pool_retry(total=10, backoff_factor=4)
    for _ in range(6):
        retry = retry.increment(method="POST", url="/in")
    assert retry.get_backoff_time() == 30
