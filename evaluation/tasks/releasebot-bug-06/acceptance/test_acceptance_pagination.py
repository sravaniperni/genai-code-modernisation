import httpx
import pytest

from releasebot.config import HostingConfig
from releasebot.errors import HostingError
from releasebot.hosting import HostingClient

API = "https://git.example.com/api/v1"


class CappedServer:
    """Paginated API that never returns more than ``cap`` items per page (like Gitea's MAX_RESPONSE_ITEMS)."""

    def __init__(self, total, cap):
        self.items = [{"id": n, "tag_name": f"v1.{n}.0", "name": f"1.{n}.0"} for n in range(total)]
        self.cap = cap
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if not request.url.path.endswith("/repos/acme/demo/releases"):
            return httpx.Response(404)
        size = min(int(request.url.params["per_page"]), self.cap)
        page = int(request.url.params.get("page", "1"))
        headers = {}
        if page * size < len(self.items):
            headers["Link"] = (
                f'<{API}/repos/acme/demo/releases?per_page={size}&page={page + 1}>; rel="next", '
                f'<{API}/repos/acme/demo/releases?per_page={size}&page={-(-len(self.items) // size)}>; rel="last"'
            )
        return httpx.Response(200, json=self.items[(page - 1) * size : page * size], headers=headers)


def client(server, per_page):
    return HostingClient(API, "acme/demo", per_page=per_page, transport=httpx.MockTransport(server))


def test_all_pages_are_fetched_when_the_server_caps_page_size():
    server = CappedServer(total=130, cap=50)
    releases = client(server, per_page=100).list_releases()
    assert [r.id for r in releases] == list(range(130))
    assert len(server.requests) == 3
    assert [r.url.params.get("page", "1") for r in server.requests] == ["1", "2", "3"]


def test_short_pages_in_the_middle_do_not_stop_pagination():
    server = CappedServer(total=7, cap=2)
    assert len(client(server, per_page=5).list_releases()) == 7
    assert len(server.requests) == 4


def test_pagination_stops_when_there_is_no_next_link():
    server = CappedServer(total=6, cap=3)
    assert len(client(server, per_page=3).list_releases()) == 6
    assert len(server.requests) == 2
    empty = CappedServer(total=0, cap=3)
    assert client(empty, per_page=3).list_releases() == []
    assert len(empty.requests) == 1


def test_per_page_from_configuration():
    server = CappedServer(total=12, cap=100)
    hosting = HostingConfig(api_url=API, repo="acme/demo", per_page=5)
    releases = HostingClient.from_config(hosting, transport=httpx.MockTransport(server)).list_releases()
    assert len(releases) == 12 and server.requests[0].url.params["per_page"] == "5"


def test_errors_on_later_pages_are_reported():
    server = CappedServer(total=10, cap=4)

    def flaky(request):
        if request.url.params.get("page") == "3":
            return httpx.Response(502, text="bad gateway")
        return server(request)

    with pytest.raises(HostingError) as excinfo:
        client(flaky, per_page=10).list_releases()
    assert excinfo.value.status_code == 502
