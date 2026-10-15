"""Minimal GitHub REST client with rate-limit handling.

* Primary rate limit: when ``X-RateLimit-Remaining`` is 0 the client waits until ``X-RateLimit-Reset`` if
  that is within ``max_rate_wait_s``, otherwise raises :class:`RateLimited`.
* Secondary rate limits / ``Retry-After``: honoured with bounded waits.
* Transport errors and 5xx responses are retried only for idempotent requests. Non-idempotent requests
  (creating a pull request) are never blindly retried; callers reconcile by looking the resource up.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from modernisation.log import redact


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class RateLimited(GitHubError):
    pass


class GitHubClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        max_rate_wait_s: float = 120.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.max_rate_wait_s = max_rate_wait_s
        self.sleep = sleep
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "codebase-modernisation-platform",
            },
        )

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        idempotent: bool | None = None,
        ok: tuple[int, ...] = (200, 201, 204),
    ) -> httpx.Response:
        idempotent = method in ("GET", "HEAD", "PUT", "DELETE") if idempotent is None else idempotent
        last: GitHubError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.request(method, path, json=json, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = GitHubError(f"{method} {path}: {type(exc).__name__}", retryable=True)
                if not idempotent:
                    raise last from exc
                self.sleep(min(2.0 * 2**attempt, 30.0))
                continue
            if resp.status_code in ok:
                return resp
            if resp.status_code in (403, 429):
                wait = self._rate_wait(resp)
                if wait is not None:
                    if wait > self.max_rate_wait_s:
                        raise RateLimited(
                            f"GitHub rate limit exhausted; resets in {int(wait)}s", resp.status_code, retryable=True
                        )
                    self.sleep(max(wait, 1.0))
                    continue
            if resp.status_code >= 500 and idempotent:
                last = GitHubError(f"{method} {path}: HTTP {resp.status_code}", resp.status_code, retryable=True)
                self.sleep(min(2.0 * 2**attempt, 30.0))
                continue
            raise GitHubError(
                f"{method} {path}: HTTP {resp.status_code}: {redact(resp.text[:300])}",
                resp.status_code,
                retryable=resp.status_code >= 500,
            )
        assert last is not None
        raise last

    @staticmethod
    def _rate_wait(resp: httpx.Response) -> float | None:
        if resp.headers.get("retry-after"):
            try:
                return float(resp.headers["retry-after"])
            except ValueError:
                return 60.0
        if resp.headers.get("x-ratelimit-remaining") == "0" and resp.headers.get("x-ratelimit-reset"):
            return max(0.0, float(resp.headers["x-ratelimit-reset"]) - time.time())
        if "secondary rate limit" in resp.text.lower():
            return 60.0
        return None

    # ------------------------------------------------------------------------------------------------
    def get_authenticated(self) -> dict[str, Any]:
        resp = self.request("GET", "/user", ok=(200,))
        return {
            "login": resp.json().get("login"),
            "scopes": resp.headers.get("x-oauth-scopes"),
            "rate_limit_remaining": resp.headers.get("x-ratelimit-remaining"),
        }

    def get_repo(self, full_name: str) -> dict[str, Any]:
        return dict(self.request("GET", f"/repos/{full_name}", ok=(200,)).json())

    def permissions(self, full_name: str) -> dict[str, bool]:
        return dict(self.get_repo(full_name).get("permissions") or {})

    def list_issues(self, full_name: str, state: str = "open", per_page: int = 30) -> list[dict[str, Any]]:
        items = self.request(
            "GET", f"/repos/{full_name}/issues", params={"state": state, "per_page": per_page}, ok=(200,)
        ).json()
        return [i for i in items if "pull_request" not in i]

    def get_issue(self, full_name: str, number: int) -> dict[str, Any]:
        return dict(self.request("GET", f"/repos/{full_name}/issues/{number}", ok=(200,)).json())

    def get_branch_sha(self, full_name: str, branch: str) -> str | None:
        try:
            resp = self.request("GET", f"/repos/{full_name}/git/ref/heads/{branch}", ok=(200,))
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        return str(resp.json()["object"]["sha"])

    def find_pull_request(self, full_name: str, head: str, base: str | None = None) -> dict[str, Any] | None:
        owner = full_name.split("/")[0]
        params: dict[str, Any] = {"head": f"{owner}:{head}", "state": "all", "per_page": 10}
        if base:
            params["base"] = base
        items = self.request("GET", f"/repos/{full_name}/pulls", params=params, ok=(200,)).json()
        return dict(items[0]) if items else None

    def create_pull_request(
        self, full_name: str, *, title: str, body: str, head: str, base: str, draft: bool = True
    ) -> dict[str, Any]:
        resp = self.request(
            "POST",
            f"/repos/{full_name}/pulls",
            idempotent=False,
            ok=(201,),
            json={"title": title, "body": body, "head": head, "base": base, "draft": draft},
        )
        return dict(resp.json())

    def get_pull_request(self, full_name: str, number: int) -> dict[str, Any]:
        return dict(self.request("GET", f"/repos/{full_name}/pulls/{number}", ok=(200,)).json())

    def create_status(self, full_name: str, sha: str, *, state: str, context: str, description: str) -> dict[str, Any]:
        resp = self.request(
            "POST",
            f"/repos/{full_name}/statuses/{sha}",
            idempotent=True,
            ok=(201,),
            json={"state": state, "context": context, "description": description[:140]},
        )
        return dict(resp.json())

    def combined_status(self, full_name: str, sha: str) -> dict[str, Any]:
        return dict(self.request("GET", f"/repos/{full_name}/commits/{sha}/status", ok=(200,)).json())
