import base64
import importlib.metadata
import json
from datetime import datetime, timezone

import httpx

from webhookrelay.app import create_app
from webhookrelay.batch import BatchRequest, BatchSender
from webhookrelay.clock import FixedClock
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher
from webhookrelay.replay import load_archive, replay
from webhookrelay.transports import HttpxTransport, TransportError

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
PROXY = "http://proxy.internal:3128"


def test_httpx_version_is_pinned():
    assert importlib.metadata.version("httpx") == "0.28.1"


def test_default_transport_delivers():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.content, request.headers["x-relay-delivery"]))
        return httpx.Response(201, headers={"X-Trace": "t-1"}, text="created")

    transport = HttpxTransport(transport=httpx.MockTransport(handler), timeout=3)
    response = transport.send("POST", "https://t.example/in?a=1", body=b'{"x": 1}', headers={"X-Relay-Delivery": "d"})
    assert (response.status, response.body, response.headers["x-trace"]) == (201, "created", "t-1")
    assert seen == [("POST", "https://t.example/in?a=1", b'{"x": 1}', "d")]


def test_transport_errors_are_wrapped():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    transport = HttpxTransport(transport=httpx.MockTransport(handler))
    try:
        transport.send("POST", "https://t.example/in", body=b"", headers={})
    except TransportError as exc:
        assert "ConnectTimeout" in str(exc)
    else:
        raise AssertionError("expected TransportError")


def test_outbound_proxy_is_used_for_deliveries():
    transport = HttpxTransport(proxy=PROXY)
    client = transport.client
    for url in ("https://downstream.example/hook", "http://downstream.example/hook"):
        routed = client._transport_for_url(httpx.URL(url))
        assert routed is not client._transport
        assert "Proxy" in type(getattr(routed, "_pool", routed)).__name__
    transport.close()
    direct = HttpxTransport()
    assert direct.client._transport_for_url(httpx.URL("https://downstream.example/hook")) is direct.client._transport
    direct.close()


def test_dispatcher_builds_proxied_transport_from_config():
    config = load_config({"proxy": PROXY, "targets": {"a": {"url": "https://a.example/in"}}, "rules": [{"targets": ["a"]}]})
    dispatcher = Dispatcher(config, clock=FixedClock(T0))
    transport = dispatcher.transport_for(config.targets["a"])
    assert isinstance(transport, HttpxTransport)
    assert transport.client._transport_for_url(httpx.URL("https://a.example/in")) is not transport.client._transport


def test_batch_sender():
    async def handler(request):
        return httpx.Response(200 if request.url.path != "/2" else 502)

    sender = BatchSender(concurrency=2, transport=httpx.MockTransport(handler))
    results = sender.send_all([BatchRequest(f"https://t.example/{i}", b"{}") for i in range(4)])
    assert [r.status for r in results] == [200, 200, 502, 200]
    assert BatchSender(proxy=PROXY).send_all([]) == []


def test_replay_into_relay_app():
    delivered = []

    def handler(request):
        request.read()
        delivered.append(json.loads(request.content))
        return httpx.Response(200)

    config = {"sources": {"shop": {}}, "targets": {"audit": {"url": "https://audit.example/in"}},
              "rules": [{"targets": ["audit"]}]}
    app = create_app(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)),
                     clock=FixedClock(T0), start_scheduler=False)
    archive = [
        json.dumps({"source": "shop", "headers": {"Content-Type": "application/json", "Host": "old.example",
                                                   "X-Event-Type": "order.created"}, "body": '{"id": "o-1"}'}),
        json.dumps({"source": "shop", "headers": {"Content-Type": "text/plain"},
                    "body_b64": base64.b64encode("grüße".encode()).decode()}),
        json.dumps({"source": "unknown", "headers": {}, "body": "{}"}),
    ]
    results = replay(app, load_archive(archive))
    assert [(r.source, r.status, r.deliveries) for r in results] == [("shop", 202, 1), ("shop", 202, 1),
                                                                      ("unknown", 404, 0)]
    assert results[0].event_id == "o-1"
    assert delivered[0]["type"] == "order.created"
    assert delivered[1]["data"] == {"text": "grüße"}
