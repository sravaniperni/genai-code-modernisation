"""GitHub webhook receiver.

* Signatures (``X-Hub-Signature-256``) are verified with a constant-time comparison; without a configured
  secret every delivery is rejected.
* ``X-GitHub-Delivery`` is stored under a unique constraint, so redelivered events are acknowledged but
  processed exactly once.
* Issue text is untrusted input. An issue labelled ``modernisation:<category>`` on a registered repository
  creates a queued task; the deterministic change policy and the publication approval gate still apply.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modernisation.agents.states import TaskCategory
from modernisation.agents.store import add_event
from modernisation.api.deps import get_session
from modernisation.config import get_settings
from modernisation.db.models import Repository, Task, WebhookDelivery
from modernisation.repository_intelligence.git_ops import GitError
from modernisation.repository_intelligence.indexer import git_for

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

LABEL_PREFIX = "modernisation:"


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(...),
    x_github_delivery: str = Header(...),
    x_hub_signature_256: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    settings = get_settings()
    if settings.github_webhook_secret is None:
        raise HTTPException(503, "webhook secret not configured; deliveries are rejected")
    body = await request.body()
    if not verify_signature(settings.github_webhook_secret.get_secret_value(), body, x_hub_signature_256):
        raise HTTPException(401, "invalid signature")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "invalid JSON") from exc

    delivery = WebhookDelivery(
        delivery_id=x_github_delivery[:100],
        event=x_github_event[:60],
        action=str(payload.get("action"))[:60] if payload.get("action") else None,
        status="received",
        payload={"repository": (payload.get("repository") or {}).get("full_name")},
    )
    session.add(delivery)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return {"status": "duplicate", "delivery": x_github_delivery}

    try:
        status, detail = _handle(session, x_github_event, payload)
    except Exception as exc:  # recorded, never leaks a stack trace to the caller
        session.rollback()
        status, detail = "error", f"{type(exc).__name__}: {exc}"[:500]
    stored = session.scalar(select(WebhookDelivery).where(WebhookDelivery.delivery_id == x_github_delivery[:100]))
    if stored is not None:
        stored.status = status
        stored.detail = detail
        session.commit()
    return {"status": status, "detail": detail}


def _handle(session: Session, event: str, payload: dict[str, Any]) -> tuple[str, str]:
    if event == "ping":
        return "processed", "pong"
    full_name = (payload.get("repository") or {}).get("full_name")
    repo = session.scalar(select(Repository).where(Repository.github_full_name == full_name)) if full_name else None
    if repo is None:
        return "ignored", f"repository {full_name!r} is not registered"

    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        task = session.scalar(select(Task).where(Task.repository_id == repo.id, Task.pr_number == pr.get("number")))
        if task is None:
            return "ignored", "pull request not created by this platform"
        action = payload.get("action")
        merged = bool(pr.get("merged"))
        add_event(
            session,
            task.id,
            "external",
            f"pull request #{pr.get('number')} {action}" + (" (merged)" if merged else ""),
            state=task.state,
            payload={"action": action, "merged": merged, "url": pr.get("html_url")},
        )
        task.result = {**(task.result or {}), "pull_request_state": pr.get("state"), "merged": merged}
        session.commit()
        return "processed", f"task {task.id} updated"

    if event in ("status", "check_run"):
        sha = payload.get("sha") or (payload.get("check_run") or {}).get("head_sha")
        tasks = session.scalars(select(Task).where(Task.repository_id == repo.id, Task.pr_number.is_not(None)))
        matched = 0
        for task in tasks:
            pub = (task.result or {}).get("publication") or {}
            if pub.get("sha") == sha:
                state = payload.get("state") or (payload.get("check_run") or {}).get("conclusion")
                name = payload.get("context") or (payload.get("check_run") or {}).get("name")
                add_event(
                    session,
                    task.id,
                    "external",
                    f"CI {name}: {state}",
                    state=task.state,
                    payload={"sha": sha, "state": state, "name": name},
                )
                matched += 1
        session.commit()
        return ("processed" if matched else "ignored"), f"{matched} task(s) matched"

    if event == "issues" and payload.get("action") in ("opened", "labeled"):
        issue = payload.get("issue") or {}
        labels = [label.get("name", "") for label in issue.get("labels", [])]
        categories = [lbl[len(LABEL_PREFIX) :] for lbl in labels if lbl.startswith(LABEL_PREFIX)]
        valid = [c for c in categories if c in {c.value for c in TaskCategory}]
        if not valid:
            return "ignored", "issue has no modernisation:<category> label"
        marker = f"github-issue:{full_name}#{issue.get('number')}"
        if session.scalar(select(Task).where(Task.repository_id == repo.id, Task.title.like(f"%[{marker}]%"))):
            return "ignored", "task already exists for this issue"
        try:
            base_commit = git_for(repo).resolve(repo.default_branch)
        except (GitError, ValueError) as exc:
            return "error", f"cannot resolve default branch: {exc}"
        task = Task(
            repository_id=repo.id,
            title=f"{str(issue.get('title', ''))[:200]} [{marker}]",
            request=f"{issue.get('title', '')}\n\n{issue.get('body') or ''}"[:20000],
            category=valid[0],
            base_ref=repo.default_branch,
            base_commit=base_commit,
            origin="webhook",
            config={"max_attempts": settings_attempts()},
            publish_requested=True,
        )
        session.add(task)
        session.flush()
        add_event(session, task.id, "state", f"task created from {marker}", state="QUEUED")
        session.commit()
        return "processed", f"task {task.id} created"

    return "ignored", f"event {event} not handled"


def settings_attempts() -> int:
    return get_settings().default_max_attempts
