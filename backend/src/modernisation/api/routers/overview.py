"""Dashboard, evaluation, settings and health endpoints."""

from __future__ import annotations

import shutil
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from modernisation.agents.states import TaskCategory, TaskState
from modernisation.api.deps import get_session, require_token
from modernisation.api.routers.tasks import task_summary
from modernisation.config import get_settings
from modernisation.db.models import EvaluationRun, ModelCall, Repository, Task
from modernisation.evaluation.metrics import run_summary
from modernisation.llm.base import ChatMessage, ModelError
from modernisation.llm.factory import build_client

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, Any]:
    settings = get_settings()
    db_ok = True
    try:
        session.execute(text("select 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "sandbox": {"backend": settings.sandbox_backend, "bubblewrap_installed": shutil.which("bwrap") is not None},
        "model_configured": settings.model_provider != "none" and bool(settings.model_name),
        # Workers currently holding an unexpired lease (idle workers hold none, so this is a lower bound).
        "active_workers": sorted(
            set(
                session.scalars(
                    select(Task.lease_owner).where(Task.lease_owner.is_not(None), Task.lease_expires_at > func.now())
                )
            )
        )
        if db_ok
        else [],
        "github_configured": settings.github_token is not None,
    }


@router.get("/meta")
def meta() -> dict[str, list[str]]:
    from modernisation.agents.states import RUNNABLE, TERMINAL

    return {
        "states": [s.value for s in TaskState],
        "categories": [c.value for c in TaskCategory],
        "terminal_states": sorted(s.value for s in TERMINAL),
        "restartable_states": ["CANCELLED", "ESCALATED", "FAILED"],
        "runnable_states": sorted(s.value for s in RUNNABLE),
    }


@router.get("/dashboard")
def dashboard(session: Session = Depends(get_session)) -> dict[str, Any]:
    by_state = dict(session.execute(select(Task.state, func.count()).group_by(Task.state)).all())
    active_states = [
        s.value
        for s in TaskState
        if s not in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.ESCALATED}
    ]
    active = session.scalars(
        select(Task).where(Task.state.in_(active_states)).order_by(Task.updated_at.desc()).limit(20)
    )
    recent = session.scalars(
        select(Task).where(Task.finished_at.is_not(None)).order_by(Task.finished_at.desc()).limit(15)
    )
    calls = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(ModelCall.prompt_tokens), 0),
            func.coalesce(func.sum(ModelCall.completion_tokens), 0),
        )
    ).one()
    return {
        "repositories": session.scalar(select(func.count()).select_from(Repository)) or 0,
        "tasks_by_state": by_state,
        "completed": by_state.get("COMPLETED", 0),
        "failed": by_state.get("FAILED", 0) + by_state.get("ESCALATED", 0),
        "active": [task_summary(t) for t in active],
        "recent": [task_summary(t) for t in recent],
        "model_usage": {"calls": calls[0], "prompt_tokens": calls[1], "completion_tokens": calls[2]},
    }


@router.get("/evaluation/runs")
def evaluation_runs(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    runs = session.scalars(select(EvaluationRun).order_by(EvaluationRun.id.desc()))
    return [run_summary(session, r) | {"results": None} for r in runs]


@router.get("/evaluation/runs/{run_id}")
def evaluation_run(run_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(404, "evaluation run not found")
    return run_summary(session, run)


@router.get("/settings")
def settings_view() -> dict[str, Any]:
    s = get_settings()
    return {
        "model": {
            "provider": s.model_provider,
            "base_url": s.model_base_url,
            "name": s.model_name,
            "api_key_configured": s.model_api_key is not None,
            "timeout_s": s.model_timeout_s,
            "max_retries": s.model_max_retries,
            "structured_output": s.model_structured_output,
            "price_input_per_mtok": s.model_price_input_per_mtok,
            "price_output_per_mtok": s.model_price_output_per_mtok,
        },
        "github": {
            "api_url": s.github_api_url,
            "token_configured": s.github_token is not None,
            "webhook_secret_configured": s.github_webhook_secret is not None,
            "allowed_repositories": s.allowed_github_repositories,
        },
        "repositories": {"allowed_local_roots": [str(p) for p in s.allowed_local_roots]},
        "execution": {
            "sandbox_backend": s.sandbox_backend,
            "sandbox_uid": s.sandbox_uid,
            "command_timeout_s": s.sandbox_command_timeout_s,
            "memory_mb": s.sandbox_memory_mb,
            "max_processes": s.sandbox_max_processes,
            "max_file_mb": s.sandbox_max_file_mb,
            "wheelhouse": str(s.wheelhouse_dir) if s.wheelhouse_dir else None,
            "network_in_sandbox": False,
        },
        "workflow": {
            "default_max_attempts": s.default_max_attempts,
            "require_plan_approval": s.require_plan_approval,
            "publish_requires_approval": True,
            "worker_lease_s": s.worker_lease_s,
        },
        "security": {
            "api_token_required": s.api_token is not None,
            "notes": "Settings are read from MODERNISATION_* environment variables; secrets are never "
            "returned by the API.",
        },
    }


@router.post("/settings/model/test", dependencies=[Depends(require_token)])
def test_model() -> dict[str, Any]:
    client = build_client(get_settings())
    if client is None:
        raise HTTPException(400, "no model endpoint configured")
    started = time.monotonic()
    try:
        completion = client.complete(
            [ChatMessage("user", "Reply with the single word: ready")], purpose="health", max_tokens=5
        )
    except ModelError as exc:
        return {"ok": False, "error": str(exc), "latency_ms": int((time.monotonic() - started) * 1000)}
    return {
        "ok": True,
        "provider": completion.provider,
        "model": completion.model,
        "reply": completion.text[:50],
        "latency_ms": completion.latency_ms,
        "prompt_tokens": completion.prompt_tokens,
        "completion_tokens": completion.completion_tokens,
    }
