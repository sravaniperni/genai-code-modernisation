"""In-process stand-in for the subset of the GitHub REST API the platform uses.

It is backed by a real bare git repository (the push target), so branch state reflects real pushes.
Faults can be injected to test idempotency and recovery. This is NOT evidence that the live GitHub
integration works; it verifies the platform's retry/reconciliation logic against GitHub's documented
semantics.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass
class Fault:
    method: str
    path_re: str
    kind: str  # timeout_after_effect | timeout_before_effect | status | status_after_effect
    status: int = 500
    times: int = 1
    headers: dict[str, str] = field(default_factory=dict)


class GitHubStandIn:
    def __init__(self, full_name: str, remote: Path, *, push: bool = True, default_branch: str = "main"):
        self.full_name = full_name
        self.remote = remote
        self.push = push
        self.default_branch = default_branch
        self.pulls: list[dict[str, Any]] = []
        self.statuses: list[dict[str, Any]] = []
        self.faults: list[Fault] = []
        self.requests: list[tuple[str, str]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def branch_sha(self, branch: str) -> str | None:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
            cwd=self.remote,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout.strip() or None

    def _fault(self, method: str, path: str) -> Fault | None:
        for f in self.faults:
            if f.times > 0 and f.method == method and re.search(f.path_re, path):
                f.times -= 1
                return f
        return None

    def handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.requests.append((method, path))
        fault = self._fault(method, path)
        if fault and fault.kind == "timeout_before_effect":
            raise httpx.ReadTimeout("injected timeout", request=request)
        if fault and fault.kind == "status":
            return httpx.Response(fault.status, headers=fault.headers, json={"message": "injected failure"})
        response = self._route(request, method, path)
        if fault and fault.kind == "timeout_after_effect":
            raise httpx.ReadTimeout("injected timeout after the server applied the change", request=request)
        if fault and fault.kind == "status_after_effect":
            return httpx.Response(fault.status, headers=fault.headers, json={"message": "injected failure"})
        return response

    def _route(self, request: httpx.Request, method: str, path: str) -> httpx.Response:
        repo_prefix = f"/repos/{self.full_name}"
        if path == "/user":
            return httpx.Response(200, headers={"x-oauth-scopes": "repo"}, json={"login": "standin-bot"})
        if path == repo_prefix and method == "GET":
            return httpx.Response(
                200,
                json={
                    "full_name": self.full_name,
                    "default_branch": self.default_branch,
                    "permissions": {"pull": True, "push": self.push, "admin": False},
                },
            )
        m = re.fullmatch(rf"{re.escape(repo_prefix)}/git/ref/heads/(.+)", path)
        if m and method == "GET":
            sha = self.branch_sha(m.group(1))
            if sha is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"ref": f"refs/heads/{m.group(1)}", "object": {"sha": sha}})
        if path == f"{repo_prefix}/pulls" and method == "GET":
            head = request.url.params.get("head", "")
            branch = head.split(":", 1)[-1]
            return httpx.Response(200, json=[p for p in self.pulls if p["head"]["ref"] == branch])
        if path == f"{repo_prefix}/pulls" and method == "POST":
            body = json.loads(request.content)
            if self.branch_sha(body["head"]) is None:
                return httpx.Response(422, json={"message": "Validation Failed", "errors": [{"field": "head"}]})
            if any(p["head"]["ref"] == body["head"] and p["state"] == "open" for p in self.pulls):
                return httpx.Response(422, json={"message": "A pull request already exists"})
            number = len(self.pulls) + 1
            pr = {
                "number": number,
                "html_url": f"https://github.test/{self.full_name}/pull/{number}",
                "state": "open",
                "draft": body.get("draft", False),
                "title": body["title"],
                "body": body["body"],
                "head": {"ref": body["head"], "sha": self.branch_sha(body["head"])},
                "base": {"ref": body["base"]},
            }
            self.pulls.append(pr)
            return httpx.Response(201, json=pr)
        m = re.fullmatch(rf"{re.escape(repo_prefix)}/statuses/([0-9a-f]+)", path)
        if m and method == "POST":
            body = json.loads(request.content)
            self.statuses.append({"sha": m.group(1), **body})
            return httpx.Response(201, json={"id": len(self.statuses), **body})
        m = re.fullmatch(rf"{re.escape(repo_prefix)}/issues/(\d+)", path)
        if m and method == "GET":
            return httpx.Response(200, json={"number": int(m.group(1)), "title": "Issue", "body": "text", "labels": []})
        return httpx.Response(404, json={"message": f"stand-in does not implement {method} {path}"})
