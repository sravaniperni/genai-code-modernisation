"""Durable task persistence: transitions, events, checkpoints and worker leases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from modernisation.agents.states import RUNNABLE, TERMINAL, IllegalTransition, TaskState, check_transition
from modernisation.db.models import Task, TaskCheckpoint, TaskEvent
from modernisation.log import redact, redact_obj


class StaleTask(RuntimeError):
    """The task changed underneath us (another worker or an API call won the race)."""


def now() -> datetime:
    return datetime.now(UTC)


def add_event(
    session: Session,
    task_id: int,
    kind: str,
    message: str,
    *,
    state: str | None = None,
    payload: dict[str, Any] | None = None,
) -> TaskEvent:
    event = TaskEvent(
        task_id=task_id, kind=kind, state=state, message=redact(message)[:4000], payload=redact_obj(payload or {})
    )
    session.add(event)
    return event


def transition(
    session: Session,
    task: Task,
    target: TaskState,
    reason: str | None = None,
    *,
    lease_owner: str | None = None,
    payload: dict[str, Any] | None = None,
    approval_stage: str | None = None,
) -> Task:
    """Move ``task`` to ``target`` atomically; raises StaleTask if the row changed since it was read."""
    check_transition(task.state, target)
    conditions = [Task.id == task.id, Task.version == task.version]
    if lease_owner is not None:
        conditions.append(Task.lease_owner == lease_owner)
    values: dict[str, Any] = {
        "state": target.value,
        "state_reason": reason,
        "version": task.version + 1,
        "updated_at": now(),
    }
    if target in TERMINAL:
        values.update(finished_at=now(), lease_owner=None, lease_expires_at=None)
    if target == TaskState.AWAITING_APPROVAL:
        if approval_stage not in {"plan", "publish"}:
            raise IllegalTransition("AWAITING_APPROVAL requires approval_stage 'plan' or 'publish'")
        values["approval_stage"] = approval_stage
    else:
        values["approval_stage"] = None
    result = session.execute(update(Task).where(and_(*conditions)).values(**values))
    if result.rowcount != 1:  # type: ignore[attr-defined]
        session.rollback()
        raise StaleTask(f"task {task.id} changed concurrently; transition to {target} abandoned")
    previous = task.state
    session.refresh(task)
    add_event(
        session,
        task.id,
        "state",
        f"{previous} -> {target.value}" + (f": {reason}" if reason else ""),
        state=target.value,
        payload={"from": previous, "to": target.value, **(payload or {})},
    )
    session.commit()
    return task


def save_checkpoint(session: Session, task_id: int, step: str, output: dict[str, Any]) -> None:
    existing = session.get(TaskCheckpoint, (task_id, step))
    if existing is None:
        session.add(TaskCheckpoint(task_id=task_id, step=step, output=output))
    else:
        existing.output = output
        existing.updated_at = now()
    session.commit()


def load_checkpoint(session: Session, task_id: int, step: str) -> dict[str, Any] | None:
    cp = session.get(TaskCheckpoint, (task_id, step))
    return dict(cp.output) if cp is not None else None


def claim_next(session: Session, worker_id: str, lease_s: float, *, task_ids: list[int] | None = None) -> Task | None:
    """Claim one runnable task whose lease is free or expired (crash recovery)."""
    t = now()
    stmt = (
        select(Task)
        .where(
            Task.state.in_([s.value for s in RUNNABLE]),
            or_(Task.lease_owner.is_(None), Task.lease_expires_at < t),
        )
        .order_by(Task.updated_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if task_ids is not None:
        stmt = stmt.where(Task.id.in_(task_ids))
    task = session.scalar(stmt)
    if task is None:
        session.rollback()
        return None
    resumed = task.lease_owner is not None and task.lease_owner != worker_id
    previous_owner = task.lease_owner
    task.lease_owner = worker_id
    task.lease_expires_at = t + timedelta(seconds=lease_s)
    task.heartbeat_at = t
    task.version += 1
    if task.started_at is None:
        task.started_at = t
    if resumed:
        task.resume_count += 1
        add_event(
            session,
            task.id,
            "log",
            f"resumed after expired lease held by {previous_owner}",
            state=task.state,
            payload={"previous_owner": previous_owner, "worker": worker_id},
        )
    session.commit()
    return task


def heartbeat(session: Session, task: Task, worker_id: str, lease_s: float) -> bool:
    """Extend the lease. Returns False if the lease was lost (another worker took over)."""
    t = now()
    result = session.execute(
        update(Task)
        .where(Task.id == task.id, Task.lease_owner == worker_id)
        .values(lease_expires_at=t + timedelta(seconds=lease_s), heartbeat_at=t)
    )
    session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


def release(session: Session, task: Task, worker_id: str) -> None:
    session.execute(
        update(Task)
        .where(Task.id == task.id, Task.lease_owner == worker_id)
        .values(lease_owner=None, lease_expires_at=None)
    )
    session.commit()


def request_cancel(session: Session, task: Task) -> Task:
    if TaskState(task.state) in TERMINAL:
        raise IllegalTransition(f"task {task.id} is already {task.state}")
    task.cancel_requested = True
    add_event(session, task.id, "log", "cancellation requested", state=task.state)
    session.commit()
    # Tasks no worker is driving (queued or waiting for a human) are cancelled immediately.
    if task.state in (TaskState.QUEUED.value, TaskState.AWAITING_APPROVAL.value) or task.lease_owner is None:
        session.refresh(task)
        transition(session, task, TaskState.CANCELLED, "cancelled by user")
    return task


def restart(session: Session, task: Task, reason: str = "restarted by user") -> Task:
    if TaskState(task.state) not in {TaskState.FAILED, TaskState.CANCELLED, TaskState.ESCALATED}:
        raise IllegalTransition(f"only failed, cancelled or escalated tasks can be restarted (is {task.state})")
    from sqlalchemy import delete, func

    from modernisation.db.models import PatchAttempt

    last_attempt = session.scalar(select(func.max(PatchAttempt.attempt_no)).where(PatchAttempt.task_id == task.id))
    # Attempt history is kept; the budget restarts after the last recorded attempt.
    task.config = {**(task.config or {}), "attempt_offset": int(last_attempt or 0)}
    session.execute(delete(TaskCheckpoint).where(TaskCheckpoint.task_id == task.id))
    task.cancel_requested = False
    task.attempt_count = 0
    task.finished_at = None
    task.final_diff = None
    task.result = None
    session.commit()
    return transition(session, task, TaskState.QUEUED, reason)
