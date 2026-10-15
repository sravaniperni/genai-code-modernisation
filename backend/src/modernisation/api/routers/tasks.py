from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from modernisation.agents import approvals
from modernisation.agents.states import IllegalTransition
from modernisation.agents.store import add_event, request_cancel, restart
from modernisation.api.deps import get_session, require_token
from modernisation.api.schemas import ApprovalIn, TaskCreate
from modernisation.db.models import Approval, CheckRun, ModelCall, PatchAttempt, Repository, Task, TaskEvent
from modernisation.repository_intelligence.git_ops import GitError
from modernisation.repository_intelligence.indexer import git_for

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task(session: Session, task_id: int) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return task


def task_summary(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "repository_id": task.repository_id,
        "repository": task.repository.name,
        "title": task.title,
        "category": task.category,
        "state": task.state,
        "state_reason": task.state_reason,
        "approval_stage": task.approval_stage,
        "attempt_count": task.attempt_count,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "origin": task.origin,
        "pr_url": task.pr_url,
        "version": task.version,
        "cancel_requested": task.cancel_requested,
        "resume_count": task.resume_count,
    }


@router.get("")
def list_tasks(
    state: str | None = None,
    repository_id: int | None = None,
    origin: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(Task).order_by(Task.id.desc()).limit(limit)
    if state:
        stmt = stmt.where(Task.state == state.upper())
    if repository_id:
        stmt = stmt.where(Task.repository_id == repository_id)
    if origin:
        stmt = stmt.where(Task.origin == origin)
    return [task_summary(t) for t in session.scalars(stmt)]


@router.post("", dependencies=[Depends(require_token)], status_code=201)
def create_task(body: TaskCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    repo = session.get(Repository, body.repository_id)
    if repo is None:
        raise HTTPException(404, "repository not found")
    ref = body.base_ref or repo.default_branch
    try:
        base_commit = git_for(repo).resolve(ref)
    except (GitError, ValueError) as exc:
        raise HTTPException(400, f"cannot resolve base ref {ref!r}: {exc}") from exc
    task = Task(
        repository_id=repo.id,
        title=body.title,
        request=body.request,
        category=body.category.value,
        base_ref=ref,
        base_commit=base_commit,
        allowed_paths=body.allowed_paths,
        forbidden_paths=body.forbidden_paths,
        config=body.config.model_dump(),
        origin="api",
        publish_requested=repo.source_kind == "github",
    )
    session.add(task)
    session.flush()
    add_event(
        session,
        task.id,
        "state",
        f"task created at {base_commit[:12]} ({ref})",
        state="QUEUED",
        payload={"base_commit": base_commit, "base_ref": ref},
    )
    session.commit()
    return task_summary(task)


@router.get("/{task_id}")
def get_task(task_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    task = _task(session, task_id)
    attempts = session.scalars(
        select(PatchAttempt).where(PatchAttempt.task_id == task_id).order_by(PatchAttempt.attempt_no)
    )
    approvals_rows = session.scalars(select(Approval).where(Approval.task_id == task_id).order_by(Approval.id))
    calls = list(session.scalars(select(ModelCall).where(ModelCall.task_id == task_id)))
    return {
        **task_summary(task),
        "request": task.request,
        "base_ref": task.base_ref,
        "base_commit": task.base_commit,
        "allowed_paths": task.allowed_paths,
        "forbidden_paths": task.forbidden_paths,
        "config": task.config,
        "analysis": task.analysis,
        "plan": task.plan,
        "result": task.result,
        "final_diff": task.final_diff,
        "branch_name": task.branch_name,
        "pr_number": task.pr_number,
        "attempts": [
            {
                "attempt_no": a.attempt_no,
                "kind": a.kind,
                "apply_status": a.apply_status,
                "rejection_reason": a.rejection_reason,
                "files_changed": a.files_changed,
                "checks_passed": a.checks_passed,
                "created_at": a.created_at,
            }
            for a in attempts
        ],
        "approvals": [
            {
                "stage": a.stage,
                "decision": a.decision,
                "reviewer": a.reviewer,
                "comment": a.comment,
                "created_at": a.created_at,
            }
            for a in approvals_rows
        ],
        "usage": {
            "model_calls": len(calls),
            "failed_calls": sum(1 for c in calls if c.status != "ok"),
            "prompt_tokens": sum(c.prompt_tokens or 0 for c in calls),
            "completion_tokens": sum(c.completion_tokens or 0 for c in calls),
            "model_latency_ms": sum(c.latency_ms for c in calls),
            "cost_usd": (
                sum(c.cost_usd for c in calls if c.cost_usd is not None)
                if calls and all(c.cost_usd is not None for c in calls if c.status == "ok")
                else None
            ),
        },
    }


@router.get("/{task_id}/events")
def events(
    task_id: int, after_id: int = 0, limit: int = Query(500, ge=1, le=2000), session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    _task(session, task_id)
    rows = session.scalars(
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id, TaskEvent.id > after_id)
        .order_by(TaskEvent.id)
        .limit(limit)
    )
    return [
        {"id": e.id, "ts": e.ts, "kind": e.kind, "state": e.state, "message": e.message, "payload": e.payload}
        for e in rows
    ]


@router.get("/{task_id}/attempts/{attempt_no}")
def attempt_detail(task_id: int, attempt_no: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    a = session.scalar(
        select(PatchAttempt).where(PatchAttempt.task_id == task_id, PatchAttempt.attempt_no == attempt_no)
    )
    if a is None:
        raise HTTPException(404, "attempt not found")
    return {
        "attempt_no": a.attempt_no,
        "kind": a.kind,
        "apply_status": a.apply_status,
        "rejection_reason": a.rejection_reason,
        "diff": a.diff,
        "edits": a.edits,
        "raw_output": a.raw_output,
        "files_changed": a.files_changed,
        "checks_passed": a.checks_passed,
    }


@router.get("/{task_id}/checks")
def checks(task_id: int, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _task(session, task_id)
    rows = session.scalars(select(CheckRun).where(CheckRun.task_id == task_id).order_by(CheckRun.id))
    return [
        {
            "id": c.id,
            "attempt_no": c.attempt_no,
            "phase": c.phase,
            "name": c.name,
            "command": c.command,
            "exit_code": c.exit_code,
            "timed_out": c.timed_out,
            "duration_ms": c.duration_ms,
            "summary": c.summary,
            "stdout_tail": c.stdout[-4000:],
            "stderr_tail": c.stderr[-2000:],
        }
        for c in rows
    ]


@router.post("/{task_id}/cancel", dependencies=[Depends(require_token)])
def cancel(task_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    task = _task(session, task_id)
    try:
        request_cancel(session, task)
    except IllegalTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    session.refresh(task)
    return task_summary(task)


@router.post("/{task_id}/restart", dependencies=[Depends(require_token)])
def restart_task(task_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    task = _task(session, task_id)
    try:
        restart(session, task)
    except IllegalTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    return task_summary(task)


@router.post("/{task_id}/approval", dependencies=[Depends(require_token)])
def approve(task_id: int, body: ApprovalIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    task = _task(session, task_id)
    try:
        approvals.decide(
            session,
            task,
            stage=body.stage,
            decision=body.decision,
            reviewer=body.reviewer,
            expected_version=body.expected_version,
            comment=body.comment,
        )
    except IllegalTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    session.refresh(task)
    return task_summary(task)


@router.get("/{task_id}/model-calls")
def model_calls(task_id: int, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.scalars(select(ModelCall).where(ModelCall.task_id == task_id).order_by(ModelCall.id))
    return [
        {
            "id": c.id,
            "purpose": c.purpose,
            "provider": c.provider,
            "model": c.model,
            "status": c.status,
            "retry_index": c.retry_index,
            "prompt_tokens": c.prompt_tokens,
            "completion_tokens": c.completion_tokens,
            "latency_ms": c.latency_ms,
            "cost_usd": c.cost_usd,
            "error": c.error,
            "created_at": c.created_at,
        }
        for c in rows
    ]
