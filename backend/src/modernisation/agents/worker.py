"""Task worker: claims runnable tasks via leases and drives them through the workflow.

Crash safety: a worker holds a time-limited lease on the task it is driving and renews it from a
heartbeat thread. If the worker dies, the lease expires and any other worker claims the task and resumes
it from its persisted state. A worker that loses its lease (for example after a long pause) stops
driving the task immediately; optimistic version checks reject any late write it might still attempt.
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy.exc import DBAPIError, OperationalError

from modernisation.agents.states import RUNNABLE, IllegalTransition, TaskState
from modernisation.agents.store import StaleTask, add_event, claim_next, heartbeat, now, release, transition
from modernisation.agents.workflow import StepContext, TransientError, WorkflowEngine
from modernisation.config import Settings, get_settings
from modernisation.db.models import Task
from modernisation.db.session import session_factory
from modernisation.execution.workspace import WorkspaceError

log = logging.getLogger(__name__)

MAX_TRANSIENT_FAILURES = 5


class Worker:
    def __init__(self, engine: WorkflowEngine, settings: Settings | None = None, worker_id: str | None = None):
        self.engine = engine
        self.settings = settings or get_settings()
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.sessions = session_factory()
        self.transient_failures: dict[int, int] = {}

    # ------------------------------------------------------------------------------------------------
    def run_forever(self, stop: threading.Event | None = None, task_ids: list[int] | None = None) -> None:
        stop = stop or threading.Event()
        log.info("worker started", extra={"worker": self.worker_id})
        while not stop.is_set():
            try:
                worked = self.run_once(task_ids=task_ids)
            except (OperationalError, DBAPIError) as exc:
                log.warning("database unavailable; backing off", extra={"error": str(exc)[:300]})
                stop.wait(5)
                continue
            if not worked:
                stop.wait(self.settings.worker_poll_s)

    def run_once(self, task_ids: list[int] | None = None) -> bool:
        with self.sessions() as session:
            task = claim_next(session, self.worker_id, self.settings.worker_lease_s, task_ids=task_ids)
            if task is None:
                return False
            task_id = task.id
        self.drive(task_id)
        return True

    # ------------------------------------------------------------------------------------------------
    def drive(self, task_id: int) -> None:
        lease_lost = threading.Event()
        done = threading.Event()
        cancel_flag = threading.Event()

        def beat() -> None:
            with self.sessions() as hb:
                while not done.wait(self.settings.worker_heartbeat_s):
                    try:
                        task = hb.get(Task, task_id)
                        hb.refresh(task)
                        if task is None or not heartbeat(hb, task, self.worker_id, self.settings.worker_lease_s):
                            lease_lost.set()
                            return
                        if task.cancel_requested:
                            cancel_flag.set()
                    except (OperationalError, DBAPIError):
                        hb.rollback()  # transient; the lease is long enough to survive a brief outage

        hb_thread = threading.Thread(target=beat, daemon=True, name=f"heartbeat-{task_id}")
        hb_thread.start()
        ctx = StepContext(self.worker_id, should_stop=lambda: lease_lost.is_set() or cancel_flag.is_set())
        try:
            self._drive_loop(task_id, ctx, lease_lost, cancel_flag)
        finally:
            done.set()
            hb_thread.join(timeout=5)

    def _drive_loop(
        self, task_id: int, ctx: StepContext, lease_lost: threading.Event, cancel_flag: threading.Event
    ) -> None:
        steps = 0
        while steps < 50:  # hard stop against any logic error causing a transition loop
            steps += 1
            with self.sessions() as session:
                task = session.get(Task, task_id)
                if task is None:
                    return
                if lease_lost.is_set() or task.lease_owner != self.worker_id:
                    log.warning("lease lost; stopping", extra={"task_id": task_id})
                    return
                if task.cancel_requested or cancel_flag.is_set():
                    with contextlib.suppress(IllegalTransition, StaleTask):
                        transition(session, task, TaskState.CANCELLED, "cancelled by user", lease_owner=self.worker_id)
                    return
                if TaskState(task.state) not in RUNNABLE:
                    release(session, task, self.worker_id)
                    return
                before = (task.state, task.version)
                try:
                    self.engine.run_step(session, task, ctx)
                    self.transient_failures.pop(task_id, None)
                except StaleTask:
                    return
                except (TransientError, OperationalError, DBAPIError, WorkspaceError) as exc:
                    session.rollback()
                    self._handle_transient(task_id, exc)
                    return
                except Exception as exc:
                    session.rollback()
                    self._fail(task_id, exc)
                    return
                session.refresh(task)
                if (task.state, task.version) == before and task.state not in (TaskState.REPAIRING.value,):
                    # A handler returned without progress (e.g. cancellation observed mid-step).
                    if ctx.should_stop():
                        continue
                    release(session, task, self.worker_id)
                    return

    def _handle_transient(self, task_id: int, exc: Exception) -> None:
        count = self.transient_failures.get(task_id, 0) + 1
        self.transient_failures[task_id] = count
        backoff = min(300.0, 5.0 * 2 ** (count - 1))
        log.warning("transient failure", extra={"task_id": task_id, "error": str(exc)[:300], "count": count})
        with self.sessions() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            add_event(
                session,
                task_id,
                "error",
                f"transient failure ({count}/{MAX_TRANSIENT_FAILURES}): {exc}",
                state=task.state,
                payload={"retry_in_s": backoff},
            )
            session.commit()
            if count >= MAX_TRANSIENT_FAILURES:
                with contextlib.suppress(IllegalTransition, StaleTask):
                    transition(
                        session,
                        task,
                        TaskState.FAILED,
                        f"giving up after {count} transient failures: {exc}",
                        lease_owner=self.worker_id,
                    )
                return
            # Keep the lease but let it expire after the backoff so the task is retried later.
            if task.lease_owner == self.worker_id:
                task.lease_expires_at = now() + timedelta(seconds=backoff)
                session.commit()

    def _fail(self, task_id: int, exc: Exception) -> None:
        log.exception("task failed", extra={"task_id": task_id})
        with self.sessions() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            add_event(
                session,
                task_id,
                "error",
                f"unexpected error: {type(exc).__name__}: {exc}",
                state=task.state,
                payload={"traceback": traceback.format_exc()[-4000:]},
            )
            session.commit()
            with contextlib.suppress(IllegalTransition, StaleTask):
                transition(
                    session,
                    task,
                    TaskState.FAILED,
                    f"{type(exc).__name__}: {str(exc)[:500]}",
                    lease_owner=self.worker_id,
                )


def drain(
    worker: Worker, task_ids: list[int], timeout_s: float = 3600, on_idle: Callable[[], None] | None = None
) -> None:
    """Drive the given tasks until none is runnable (used by tests and the evaluation runner)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        worked = worker.run_once(task_ids=task_ids)
        if worked:
            continue
        with worker.sessions() as session:
            states = [session.get(Task, t) for t in task_ids]
            if all(t is None or TaskState(t.state) not in RUNNABLE for t in states):
                return
        if on_idle:
            on_idle()
        time.sleep(min(1.0, worker.settings.worker_poll_s))
    raise TimeoutError(f"tasks {task_ids} did not finish within {timeout_s}s")
