import json

import httpx
import pytest

from releasebot.config import HostingConfig
from releasebot.errors import ConfigError, HostingError
from releasebot.hosting import HostingClient

API = "https://git.example.com/api/v1"


def paged_server(items, page_size, requests):
    def handler(request):
        requests.append(request)
        page = int(request.url.params.get("page", "1"))
        chunk = items[(page - 1) * page_size : page * page_size]
        headers = {}
        if page * page_size < len(items):
            headers["Link"] = f'<{API}/repos/acme/demo/releases?per_page={page_size}&page={page + 1}>; rel="next"'
        return httpx.Response(200, json=chunk, headers=headers)

    return handler


def release(n):
    return {"id": n, "tag_name": f"v1.{n}.0", "name": f"demo 1.{n}.0", "body": "", "prerelease": False}


def test_list_releases_follows_pagination():
    requests = []
    transport = httpx.MockTransport(paged_server([release(n) for n in range(5)], 2, requests))
    client = HostingClient(API, "acme/demo", per_page=2, transport=transport)
    assert [r.tag_name for r in client.list_releases()] == [f"v1.{n}.0" for n in range(5)]
    assert len(requests) == 3
    assert requests[0].url.params["per_page"] == "2"
    assert requests[0].url.path == "/api/v1/repos/acme/demo/releases"


def test_create_release_sends_payload_and_token():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 9, **seen["payload"]})

    client = HostingClient(API, "acme/demo", token="s3cret", transport=httpx.MockTransport(handler))
    created = client.create_release("v1.5.0", "demo 1.5.0", "notes", prerelease=True)
    assert (created.id, created.tag_name, created.prerelease) == (9, "v1.5.0", True)
    assert seen["auth"] == "token s3cret"
    assert seen["payload"] == {"tag_name": "v1.5.0", "name": "demo 1.5.0", "body": "notes", "prerelease": True, "draft": False}


def test_missing_release_and_errors():
    def handler(request):
        if request.url.path.endswith("/v1.0.0"):
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(500, text="boom")

    client = HostingClient(API, "acme/demo", transport=httpx.MockTransport(handler))
    assert client.get_release("v1.0.0") is None
    with pytest.raises(HostingError) as excinfo:
        client.get_release("v2.0.0")
    assert excinfo.value.status_code == 500


def test_from_config_requires_api_settings():
    with pytest.raises(ConfigError):
        HostingClient.from_config(HostingConfig())
    client = HostingClient.from_config(HostingConfig(api_url=API, repo="acme/demo", per_page=7))
    assert client.per_page == 7
    client.close()
