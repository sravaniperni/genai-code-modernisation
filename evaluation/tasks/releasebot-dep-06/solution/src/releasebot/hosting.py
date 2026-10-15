"""Client for the REST API of the code-hosting service (Gitea/GitHub style ``repos/{owner}/{repo}/...``)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from releasebot import __version__
from releasebot.config import HostingConfig
from releasebot.errors import ConfigError, HostingError


@dataclass(frozen=True)
class Release:
    id: int
    tag_name: str
    name: str
    body: str = ""
    prerelease: bool = False

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Release:
        return cls(int(data["id"]), str(data["tag_name"]), str(data.get("name") or data["tag_name"]),
                   str(data.get("body") or ""), bool(data.get("prerelease", False)))


class HostingClient:
    """Thin synchronous API client; pass ``transport`` to plug in a fake server in tests."""

    def __init__(
        self, api_url: str, repo: str, *, token: str | None = None, proxy: str | None = None,
        per_page: int = 100, timeout: float = 10.0, transport: httpx.BaseTransport | None = None,
    ):
        headers = {"Accept": "application/json", "User-Agent": f"releasebot/{__version__}"}
        if token:
            headers["Authorization"] = f"token {token}"
        self.repo = repo
        self.per_page = per_page
        self.http = httpx.Client(
            base_url=api_url.rstrip("/") + "/",
            headers=headers,
            timeout=timeout,
            transport=transport,
            proxy=proxy,
            trust_env=False,  # the proxy is configured explicitly in releasebot.yml
        )

    @classmethod
    def from_config(cls, hosting: HostingConfig, *, token: str | None = None, **kwargs: Any) -> HostingClient:
        if not hosting.api_url or not hosting.repo:
            raise ConfigError("'hosting.api_url' and 'hosting.repo' are required for the hosting publisher")
        return cls(hosting.api_url, hosting.repo, token=token, proxy=hosting.proxy, per_page=hosting.per_page, **kwargs)

    def close(self) -> None:
        self.http.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise HostingError(f"{method} {url} failed: {exc}") from exc
        if response.status_code >= 400:
            message = f"{method} {url} returned {response.status_code}: {response.text[:200]}"
            raise HostingError(message, response.status_code)
        return response

    def _paginate(self, path: str) -> Iterator[dict[str, Any]]:
        """Yield every item of a paginated collection, following ``Link: <...>; rel="next"``."""
        url: str | None = path
        params: dict[str, Any] | None = {"per_page": self.per_page}
        while url:
            response = self._request("GET", url, params=params)
            batch = response.json()
            if not isinstance(batch, list):
                raise HostingError(f"GET {url} did not return a list")
            yield from batch
            url = response.links.get("next", {}).get("url")
            params = None  # the next link already carries the query string

    def list_releases(self) -> list[Release]:
        return [Release.from_api(item) for item in self._paginate(f"repos/{self.repo}/releases")]

    def get_release(self, tag_name: str) -> Release | None:
        try:
            return Release.from_api(self._request("GET", f"repos/{self.repo}/releases/tags/{tag_name}").json())
        except HostingError as exc:
            if exc.status_code == 404:
                return None
            raise

    def create_release(self, tag_name: str, name: str, body: str, *, prerelease: bool = False) -> Release:
        payload = {"tag_name": tag_name, "name": name, "body": body, "prerelease": prerelease, "draft": False}
        return Release.from_api(self._request("POST", f"repos/{self.repo}/releases", json=payload).json())
