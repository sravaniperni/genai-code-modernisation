import importlib.metadata
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from releasebot import __version__
from releasebot.config import HostingConfig
from releasebot.errors import HostingError
from releasebot.hosting import HostingClient
from releasebot.plugins import PublishContext
from releasebot.publishers import HostingPublisher
from releasebot.release import plan_release

API = "https://git.example.com/api/v1"


def release(n):
    return {"id": n, "tag_name": f"v0.{n}.0", "name": f"demo 0.{n}.0", "body": f"notes {n}", "prerelease": n % 2 == 1}


class FakeApi:
    """In-memory hosting API with Link-header pagination."""

    def __init__(self, releases):
        self.releases = list(releases)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/repos/acme/demo/releases":
            payload = json.loads(request.content)
            created = {"id": 100 + len(self.releases), **payload}
            self.releases.append(created)
            return httpx.Response(201, json=created)
        if path.startswith("/api/v1/repos/acme/demo/releases/tags/"):
            tag = path.rsplit("/", 1)[1]
            match = [r for r in self.releases if r["tag_name"] == tag]
            return httpx.Response(200, json=match[0]) if match else httpx.Response(404, json={"message": "Not Found"})
        if path == "/api/v1/repos/acme/demo/releases":
            size = int(request.url.params["per_page"])
            page = int(request.url.params.get("page", "1"))
            headers = {}
            if page * size < len(self.releases):
                headers["Link"] = f'<{API}/repos/acme/demo/releases?per_page={size}&page={page + 1}>; rel="next"'
            return httpx.Response(200, json=self.releases[(page - 1) * size : page * size], headers=headers)
        return httpx.Response(500, text="unexpected request")


def client_for(api, **kwargs):
    return HostingClient(API, "acme/demo", transport=httpx.MockTransport(api), **kwargs)


def test_httpx_is_pinned_to_0_28_1():
    assert importlib.metadata.version("httpx") == "0.28.1"


def test_paginated_listing():
    api = FakeApi([release(n) for n in range(7)])
    releases = client_for(api, per_page=3).list_releases()
    assert [r.tag_name for r in releases] == [f"v0.{n}.0" for n in range(7)]
    assert [r.prerelease for r in releases[:2]] == [False, True]
    assert len(api.requests) == 3
    assert api.requests[0].url.params["per_page"] == "3"
    assert api.requests[0].headers["user-agent"] == f"releasebot/{__version__}"


def test_create_and_get_release():
    api = FakeApi([release(1)])
    client = client_for(api, token="t0ken")
    assert client.get_release("v0.1.0").name == "demo 0.1.0"
    assert client.get_release("v9.9.9") is None
    created = client.create_release("v1.0.0", "demo 1.0.0", "First!", prerelease=False)
    assert (created.id, created.tag_name, created.body) == (101, "v1.0.0", "First!")
    post = api.requests[-1]
    assert post.method == "POST" and post.headers["authorization"] == "token t0ken"
    assert json.loads(post.content) == {"tag_name": "v1.0.0", "name": "demo 1.0.0", "body": "First!", "prerelease": False, "draft": False}


def test_errors_become_hosting_errors():
    def failing(request):
        if request.url.path.endswith("/boom"):
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(503, text="maintenance")

    client = client_for(failing)
    with pytest.raises(HostingError) as excinfo:
        client.list_releases()
    assert excinfo.value.status_code == 503
    with pytest.raises(HostingError):
        client.get_release("boom")


def test_hosting_publisher(config, log, tags, now, tmp_path):
    api = FakeApi([])
    client = HostingClient.from_config(config.hosting, token="x", transport=httpx.MockTransport(api))
    plan = plan_release(config, log, tags, now=now)
    assert HostingPublisher(config).publish(plan, PublishContext(tmp_path, hosting_client=client)) == "created release v1.5.0"
    assert api.releases[0]["tag_name"] == "v1.5.0" and "### Features" in api.releases[0]["body"]


class ForwardProxy(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):  # noqa: N802
        ForwardProxy.seen.append(self.path)
        body = json.dumps([release(5)]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_requests_go_through_the_configured_proxy():
    server = ThreadingHTTPServer(("127.0.0.1", 0), ForwardProxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        hosting = HostingConfig(api_url="http://git.internal.test/api/v1", repo="acme/demo", per_page=20,
                                proxy=f"http://127.0.0.1:{server.server_address[1]}")
        client = HostingClient.from_config(hosting)
        assert [r.tag_name for r in client.list_releases()] == ["v0.5.0"]
        client.close()
    finally:
        server.shutdown()
        server.server_close()
    assert ForwardProxy.seen == ["http://git.internal.test/api/v1/repos/acme/demo/releases?per_page=20"]
