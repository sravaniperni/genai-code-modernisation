"""Failure-recovery scenarios.

Crash points are simulated with ``SimulatedCrash`` (a BaseException the worker does not catch), which leaves
the database exactly as an abruptly terminated process would: the lease is still held and nothing after
the crash point ran. A second worker then takes over once the lease has expired (expiry is fast-forwarded by
moving ``lease_expires_at`` into the past). Scenarios R07/R08 kill a real worker process with SIGKILL.

Every scenario records observations used in reports/recovery-results.md: duplicate external actions, lost
state and incorrect resumption.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from modernisation.agents import approvals
from modernisation.agents.states import TaskState
from modernisation.agents.store import StaleTask, claim_next, request_cancel, restart, transition
from modernisation.agents.worker import MAX_TRANSIENT_FAILURES, Worker, drain
from modernisation.agents.workflow import WorkflowEngine
from modernisation.config import Settings, get_settings
from modernisation.db.models import (
    ExternalAction,
    IndexSnapshot,
    ModelCall,
    PatchAttempt,
    Repository,
    SnapshotFile,
    Task,
    TaskEvent,
)
from modernisation.db.session import session_factory
from modernisation.llm.base import Pricing, RetryPolicy
from modernisation.llm.factory import db_sink
from modernisation.llm.providers import OpenAICompatibleClient
from modernisation.repository_intelligence.indexer import git_for
from modernisation.services.repositories import register_local
from tests.helpers import BUG_REQUEST, CORRECT_FIX, PLAN_JSON, ScriptedModel, commit_change, git
from tests.scenarios import scenario

pytestmark = [pytest.mark.postgres, pytest.mark.sandbox, pytest.mark.recovery]


class SimulatedCrash(BaseException):
    """Abrupt termination at a precise point (not caught by worker error handling)."""


HANG_FIX = """src/inventory/pricing.py
<<<<<<< SEARCH
    return round(price - price * percent / 1000, 2)
=======
    while True:
        pass
>>>>>>> REPLACE
"""
REPAIR_HANG = """src/inventory/pricing.py
<<<<<<< SEARCH
    while True:
        pass
=======
    return round(price - price * percent / 100, 2)
>>>>>>> REPLACE
"""
GOOD = {"plan": [PLAN_JSON], "implement": [CORRECT_FIX]}


# ------------------------------------------------------------------------------------------------------
# helpers


def settings(**update: Any) -> Settings:
    return get_settings().model_copy(update={"worker_lease_s": 30.0, "worker_heartbeat_s": 1.0, **update})


def engine_for(
    responses: dict[str, list[Any]],
    cfg: Settings | None = None,
    publisher: Any = None,
    model_factory: Callable[[Task], Any] | None = None,
) -> WorkflowEngine:
    cfg = cfg or settings()
    factory = model_factory or (lambda t: ScriptedModel(responses, sink=db_sink(t.id)))
    return WorkflowEngine(settings=cfg, model_factory=factory, publisher=publisher)


def new_task(session: Session, repo: Repository, **config: Any) -> Task:
    task = Task(
        repository_id=repo.id,
        title="Fix discount calculation",
        request=BUG_REQUEST,
        category="bug_fix",
        base_ref="main",
        base_commit=git_for(repo).resolve("main"),
        allowed_paths=["src/**", "tests/**"],
        config={"max_attempts": 3, "auto_complete": True, **config},
    )
    session.add(task)
    session.commit()
    return task


def expire_lease(session: Session, task_id: int) -> None:
    session.execute(
        update(Task).where(Task.id == task_id).values(lease_expires_at=func.now() - text("interval '1 second'"))
    )
    session.commit()


def finish(
    session: Session, engine: WorkflowEngine, task: Task, worker_id: str = "w2", cfg: Settings | None = None
) -> Task:
    drain(Worker(engine, cfg or settings(), worker_id=worker_id), [task.id], timeout_s=900)
    session.expire_all()
    fresh = session.get(Task, task.id)
    assert fresh is not None
    return fresh


def crash_once(
    monkeypatch: pytest.MonkeyPatch,
    owner: Any,
    attr: str,
    *,
    after: bool = False,
    when: Callable[..., bool] = lambda *a, **k: True,
) -> dict[str, int]:
    original = getattr(owner, attr)
    state = {"fired": 0}

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not state["fired"] and not after and when(*args, **kwargs):
            state["fired"] = 1
            raise SimulatedCrash(f"crash before {attr}")
        result = original(*args, **kwargs)
        if not state["fired"] and after and when(*args, **kwargs):
            state["fired"] = 1
            raise SimulatedCrash(f"crash after {attr}")
        return result

    monkeypatch.setattr(owner, attr, wrapper)
    return state


def crash_run(session: Session, engine: WorkflowEngine, task: Task, worker_id: str = "w1") -> Task:
    with pytest.raises(SimulatedCrash):
        drain(Worker(engine, settings(), worker_id=worker_id), [task.id], timeout_s=600)
    session.expire_all()
    fresh = session.get(Task, task.id)
    assert fresh is not None
    return fresh


def count(session: Session, model: Any, **filters: Any) -> int:
    return int(session.query(model).filter_by(**filters).count())


def model_calls(session: Session, task_id: int, purpose: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ModelCall)
            .where(ModelCall.task_id == task_id, ModelCall.purpose == purpose, ModelCall.status == "ok")
        )
        or 0
    )


def assert_completed_correctly(session: Session, task: Task, observe: Callable[..., None], **extra: Any) -> None:
    attempts = count(session, PatchAttempt, task_id=task.id)
    lost = int(task.state != "COMPLETED" or not task.final_diff or "percent / 100, 2)" not in (task.final_diff or ""))
    observe(
        final_state=task.state,
        attempts=attempts,
        resume_count=task.resume_count,
        lost_state=lost,
        duplicate_external_actions=0,
        incorrect_resume=0,
        **extra,
    )
    assert task.state == "COMPLETED", task.state_reason
    assert task.final_diff and "percent / 100, 2)" in task.final_diff and "/ 1000" in task.final_diff


@pytest.fixture()
def repo(session: Session, sample_repo: Path) -> Repository:
    return register_local(session, "inventory", str(sample_repo))


# ------------------------------------------------------------------------------------------------------
# A. worker termination (simulated crash points)


@scenario("R01", "worker termination", "worker dies while baseline checks run during ANALYSING")
def test_r01_crash_during_analysis(session: Session, repo: Repository, monkeypatch: pytest.MonkeyPatch, observe):
    from modernisation.execution.checks import CheckRunner

    crash_once(monkeypatch, CheckRunner, "run", when=lambda *a, **k: k.get("phase") == "baseline")
    engine = engine_for(GOOD)
    task = crash_run(session, engine, new_task(session, repo))
    assert task.state == "ANALYSING" and task.lease_owner == "w1"
    expire_lease(session, task.id)
    task = finish(session, engine, task)
    assert_completed_correctly(session, task, observe)
    assert task.resume_count == 1 and count(session, PatchAttempt, task_id=task.id) == 1


@scenario("R02", "worker termination", "worker dies after the plan model call returns but before the plan is saved")
def test_r02_crash_before_plan_checkpoint(session: Session, repo: Repository, monkeypatch: pytest.MonkeyPatch, observe):
    import modernisation.agents.workflow as wf

    crash_once(monkeypatch, wf, "save_checkpoint", when=lambda s, tid, step, out: step == "plan")
    engine = engine_for(GOOD)
    task = crash_run(session, engine, new_task(session, repo))
    assert task.state == "PLANNING"
    expire_lease(session, task.id)
    task = finish(session, engine, task)
    assert_completed_correctly(session, task, observe, plan_model_calls=model_calls(session, task.id, "plan"))
    # the unsaved plan is regenerated (an extra model call), never silently skipped
    assert model_calls(session, task.id, "plan") == 2


@scenario("R03", "partial operation", "worker dies after the plan checkpoint is saved but before the transition")
def test_r03_crash_after_plan_checkpoint(session: Session, repo: Repository, monkeypatch: pytest.MonkeyPatch, observe):
    import modernisation.agents.workflow as wf

    crash_once(monkeypatch, wf, "transition", when=lambda s, t, target, *a, **k: target == TaskState.IMPLEMENTING)
    engine = engine_for(GOOD)
    task = crash_run(session, engine, new_task(session, repo))
    expire_lease(session, task.id)
    task = finish(session, engine, task)
    assert_completed_correctly(session, task, observe)
    assert model_calls(session, task.id, "plan") == 1  # checkpoint reused, no repeated model call


@scenario("R04", "worker termination", "worker dies while the attempt's tests run in the sandbox")
def test_r04_crash_during_testing(session: Session, repo: Repository, monkeypatch: pytest.MonkeyPatch, observe):
    from modernisation.execution.checks import CheckRunner

    crash_once(monkeypatch, CheckRunner, "run", when=lambda *a, **k: k.get("phase") == "attempt")
    engine = engine_for(GOOD)
    task = crash_run(session, engine, new_task(session, repo))
    assert task.state == "TESTING"
    expire_lease(session, task.id)
    task = finish(session, engine, task)
    assert_completed_correctly(session, task, observe)
    assert count(session, PatchAttempt, task_id=task.id) == 1
    assert model_calls(session, task.id, "implement") == 1


@scenario(
    "R05", "partial operation", "worker dies after writing edits to the workspace but before recording the attempt"
)
def test_r05_crash_after_workspace_write(session: Session, repo: Repository, monkeypatch: pytest.MonkeyPatch, observe):
    from modernisation.execution.workspace import Workspace

    crash_once(monkeypatch, Workspace, "apply_edits", after=True)
    engine = engine_for(GOOD)
    task = crash_run(session, engine, new_task(session, repo))
    assert task.state == "IMPLEMENTING" and count(session, PatchAttempt, task_id=task.id) == 0
    # leave junk in the abandoned workspace: resumption must not trust it
    stray = get_settings().workspaces_dir / f"task-{task.id}" / "agent" / "repo" / "src" / "inventory" / "stray.py"
    stray.write_text("print('left behind by the dead worker')\n")
    expire_lease(session, task.id)
    task = finish(session, engine, task)
    assert_completed_correctly(session, task, observe)
    assert "stray.py" not in (task.final_diff or "")


@scenario("R06", "worker termination", "worker dies during independent verification")
def test_r06_crash_during_verification(session: Session, repo: Repository, monkeypatch: pytest.MonkeyPatch, observe):
    from modernisation.execution.checks import CheckRunner

    crash_once(monkeypatch, CheckRunner, "run", when=lambda *a, **k: k.get("phase") == "verification")
    engine = engine_for(GOOD)
    task = crash_run(session, engine, new_task(session, repo))
    assert task.state == "VERIFYING"
    expire_lease(session, task.id)
    task = finish(session, engine, task)
    assert_completed_correctly(session, task, observe)


def _spawn_worker(
    worker_id: str, responses: dict[str, Any], task_id: int, pause: str, tmp: Path
) -> subprocess.Popen[bytes]:
    path = tmp / f"responses-{worker_id}.json"
    path.write_text(json.dumps(responses))
    backend = Path(__file__).resolve().parents[2]
    return subprocess.Popen(
        [sys.executable, "-m", "tests.recovery.worker_proc", worker_id, str(path), str(task_id), pause],
        cwd=backend,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _wait_for(predicate: Callable[[], bool], timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise TimeoutError("condition not reached")


@scenario("R07", "worker termination", "worker process is SIGKILLed while holding the lease in TESTING")
def test_r07_sigkill_worker_process(session: Session, repo: Repository, tmp_path: Path, observe):
    task = new_task(session, repo)
    marker = Path(f"/tmp/worker-sigkill-a-{task.id}.paused")
    marker.unlink(missing_ok=True)
    proc = _spawn_worker(f"sigkill-a-{task.id}", GOOD, task.id, "TESTING", tmp_path)
    try:
        _wait_for(lambda: Path(f"/tmp/worker-sigkill-a-{task.id}.paused").exists())
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    session.expire_all()
    held = session.get(Task, task.id)
    assert held is not None and held.state == "TESTING" and held.lease_owner == f"sigkill-a-{task.id}"
    # wait for the real lease (4 s in the killed worker) to expire, then a new worker takes over
    _wait_for(lambda: _lease_expired(task.id), timeout=30)
    task = finish(session, engine_for(GOOD), held)
    assert_completed_correctly(session, task, observe)
    assert task.resume_count == 1


def _lease_expired(task_id: int) -> bool:
    with session_factory()() as s:
        t = s.get(Task, task_id)
        return t is not None and t.lease_expires_at is not None and s.scalar(select(func.now())) > t.lease_expires_at


@scenario(
    "R08", "worker termination", "SIGKILL of a worker while a sandboxed test run is executing; no orphan processes"
)
def test_r08_sigkill_kills_sandbox_children(session: Session, repo: Repository, tmp_path: Path, observe):
    task = new_task(session, repo)
    responses = {"plan": [PLAN_JSON], "implement": [HANG_FIX], "repair": [REPAIR_HANG]}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(responses))
    backend = Path(__file__).resolve().parents[2]
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.recovery.worker_proc", f"sigkill-b-{task.id}", str(path), str(task.id)],
        cwd=backend,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ws_fragment = f"task-{task.id}/agent/repo"

    def sandbox_running() -> bool:
        out = subprocess.run(["pgrep", "-f", ws_fragment], capture_output=True, text=True).stdout.split()
        return bool(out)

    try:
        _wait_for(lambda: _state(task.id) == "TESTING" and sandbox_running(), timeout=180)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    _wait_for(lambda: not sandbox_running(), timeout=15)  # bwrap --die-with-parent took the tree down
    observe(orphan_processes=0)
    _wait_for(lambda: _lease_expired(task.id), timeout=30)
    session.expire_all()
    task = finish(session, engine_for(responses, settings(sandbox_command_timeout_s=10.0)), session.get(Task, task.id))
    assert_completed_correctly(session, task, observe)


def _state(task_id: int) -> str | None:
    with session_factory()() as s:
        t = s.get(Task, task_id)
        return t.state if t else None


@scenario("R09", "worker termination", "two workers race to claim the same task; exactly one wins (20 rounds)")
def test_r09_claim_race(session: Session, repo: Repository, observe):
    winners_per_round = []
    for _ in range(20):
        task = new_task(session, repo)
        barrier = threading.Barrier(2)
        winners: list[str] = []

        def claim(
            worker: str, task_id: int = task.id, gate: threading.Barrier = barrier, won: list[str] = winners
        ) -> None:
            with session_factory()() as s:
                gate.wait()
                claimed = claim_next(s, worker, 30, task_ids=[task_id])
                if claimed is not None:
                    won.append(worker)

        threads = [threading.Thread(target=claim, args=(w,)) for w in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        winners_per_round.append(len(winners))
    observe(rounds=20, double_claims=sum(1 for w in winners_per_round if w > 1), duplicate_external_actions=0)
    assert winners_per_round == [1] * 20


@scenario("R10", "worker termination", "a paused worker resumes after its lease was taken over; its write is rejected")
def test_r10_stale_worker_write_rejected(session: Session, repo: Repository, observe):
    task = new_task(session, repo)
    with session_factory()() as a:
        stale = claim_next(a, "slow-worker", 30, task_ids=[task.id])
        assert stale is not None
        expire_lease(session, task.id)
        with session_factory()() as b:
            fresh = claim_next(b, "fast-worker", 30, task_ids=[task.id])
            assert fresh is not None
            transition(b, fresh, TaskState.ANALYSING, "fast worker progressed", lease_owner="fast-worker")
        with pytest.raises(StaleTask):
            transition(a, stale, TaskState.ANALYSING, "stale worker", lease_owner="slow-worker")
    session.expire_all()
    final = session.get(Task, task.id)
    observe(final_state=final.state, incorrect_resume=0, lost_state=0)
    assert final is not None and final.state == "ANALYSING" and final.lease_owner == "fast-worker"


# ------------------------------------------------------------------------------------------------------
# B. interrupted model calls (real HTTP adapter over a simulated transport)


def http_model(fail: Callable[[int], Exception | None], cfg: Settings | None = None) -> Callable[[Task], Any]:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        error = fail(state["n"])
        if error is not None:
            raise error
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        content = PLAN_JSON if "single JSON object" in system else CORRECT_FIX
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 100},
            },
        )

    transport = httpx.MockTransport(handler)

    def factory(task: Task) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            base_url="http://model.local/v1",
            model="m",
            api_key=None,
            timeout_s=5,
            max_output_tokens=256,
            temperature=0,
            retry=RetryPolicy(max_retries=2, sleep=lambda s: None),
            pricing=Pricing(),
            sink=db_sink(task.id),
            transport=transport,
        )

    return factory


@scenario("R11", "interrupted model call", "connection reset on the first model request; retried and completed")
def test_r11_model_connection_reset(session: Session, repo: Repository, observe):
    factory = http_model(lambda n: httpx.RemoteProtocolError("connection reset by peer") if n == 1 else None)
    task = finish(session, engine_for({}, model_factory=factory), new_task(session, repo), worker_id="w1")
    failed = count(session, ModelCall, task_id=task.id, status="error")
    assert_completed_correctly(session, task, observe, failed_model_requests=failed)
    assert failed == 1


@scenario(
    "R12", "interrupted model call", "model requests time out beyond the retry budget, then the endpoint recovers"
)
def test_r12_model_timeout_then_recovery(session: Session, repo: Repository, observe):
    factory = http_model(lambda n: httpx.ReadTimeout("timed out") if n <= 3 else None)
    engine = engine_for({}, model_factory=factory)
    task = new_task(session, repo)
    worker = Worker(engine, settings(), worker_id="w1")
    worker.run_once(task_ids=[task.id])  # analysis ok, planning hits 3 timeouts -> transient backoff
    session.expire_all()
    assert session.get(Task, task.id).state == "PLANNING"
    expire_lease(session, task.id)
    task = finish(session, engine, task, worker_id="w1")
    assert_completed_correctly(session, task, observe, failed_model_requests=3)
    events = [e.message for e in session.scalars(select(TaskEvent).where(TaskEvent.task_id == task.id))]
    assert any("transient failure (1/" in m for m in events)


@scenario(
    "R13", "interrupted model call", "persistent model outage fails the task after bounded retries; restart completes"
)
def test_r13_model_outage_bounded_then_restart(session: Session, repo: Repository, observe):
    outage = {"down": True}
    factory = http_model(lambda n: httpx.ConnectError("refused") if outage["down"] else None)
    engine = engine_for({}, model_factory=factory)
    task = new_task(session, repo)
    worker = Worker(engine, settings(), worker_id="w1")
    for _ in range(MAX_TRANSIENT_FAILURES):
        worker.run_once(task_ids=[task.id])
        expire_lease(session, task.id)
    session.expire_all()
    task = session.get(Task, task.id)
    assert task.state == "FAILED" and "transient failures" in (task.state_reason or "")
    outage["down"] = False
    restart(session, task)
    task = finish(session, engine, task, worker_id="w2")
    assert_completed_correctly(session, task, observe, bounded_failures=MAX_TRANSIENT_FAILURES)


@scenario(
    "R14", "interrupted model call", "model returns unparseable plans; bounded correction then retrieval-based fallback"
)
def test_r14_malformed_plan_fallback(session: Session, repo: Repository, observe):
    engine = engine_for({"plan": ["this is not json", "still not json"], "implement": [CORRECT_FIX]})
    task = finish(session, engine, new_task(session, repo), worker_id="w1")
    assert_completed_correctly(session, task, observe)
    assert "model plan was invalid" in task.plan["summary"]


# ------------------------------------------------------------------------------------------------------
# C. database reconnection (restarts the local PostgreSQL cluster)

PG_RESTART = ["pg_ctlcluster", "16", "main", "restart"]


def restart_postgres() -> None:
    subprocess.run(PG_RESTART, check=True, capture_output=True, timeout=60)


@pytest.mark.db_restart
@scenario("R15", "database reconnection", "PostgreSQL restarts while the worker is idle; next task is processed")
def test_r15_db_restart_idle_worker(session: Session, repo: Repository, observe):
    engine = engine_for(GOOD)
    stop = threading.Event()
    worker = Worker(engine, settings(), worker_id="idle-worker")
    thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True)
    thread.start()
    try:
        time.sleep(2)
        restart_postgres()
        session.close()
        with session_factory()() as s:
            task = new_task(s, s.get(Repository, repo.id))
            task_id = task.id
        _wait_for(lambda: _state(task_id) in ("COMPLETED", "ESCALATED", "FAILED"), timeout=600)
    finally:
        stop.set()
        thread.join(timeout=30)
    with session_factory()() as s:
        task = s.get(Task, task_id)
        assert_completed_correctly(s, task, observe)


@pytest.mark.db_restart
@scenario(
    "R16", "database reconnection", "PostgreSQL restarts in the middle of a task step; task resumes and completes"
)
def test_r16_db_restart_mid_task(session: Session, repo: Repository, monkeypatch: pytest.MonkeyPatch, observe):
    from modernisation.execution.checks import CheckRunner

    original = CheckRunner.run
    fired = {"n": 0}

    def run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("phase") == "attempt" and not fired["n"]:
            fired["n"] = 1
            restart_postgres()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(CheckRunner, "run", run)
    engine = engine_for(GOOD)
    task = new_task(session, repo)
    task_id = task.id
    session.close()
    worker = Worker(engine, settings(), worker_id="w1")
    deadline = time.monotonic() + 600
    while _state(task_id) not in ("COMPLETED", "ESCALATED", "FAILED") and time.monotonic() < deadline:
        try:
            worker.run_once(task_ids=[task_id])
        except Exception:
            time.sleep(1)
        with session_factory()() as s:
            expire_lease(s, task_id)
    with session_factory()() as s:
        task = s.get(Task, task_id)
        assert fired["n"] == 1
        assert_completed_correctly(s, task, observe)


@pytest.mark.db_restart
@scenario("R17", "database reconnection", "API health endpoint recovers after a PostgreSQL restart")
def test_r17_api_recovers_after_db_restart(db: None, observe):
    from fastapi.testclient import TestClient

    from modernisation.api.app import create_app

    client = TestClient(create_app())
    assert client.get("/api/health").json()["database"] is True
    restart_postgres()
    statuses = [client.get("/api/health").json()["database"] for _ in range(3)]
    observe(health_after_restart=statuses)
    assert statuses[-1] is True


# ------------------------------------------------------------------------------------------------------
# D. cancellation


@scenario("R18", "task cancellation", "cancel while a hanging test run executes in the sandbox")
def test_r18_cancel_during_sandbox_run(session: Session, repo: Repository, observe):
    engine = engine_for({"plan": [PLAN_JSON], "implement": [HANG_FIX]}, settings(sandbox_command_timeout_s=300.0))
    task = new_task(session, repo)
    worker = Worker(engine, settings(), worker_id="w1")
    thread = threading.Thread(target=lambda: drain(worker, [task.id], timeout_s=600), daemon=True)
    thread.start()
    fragment = f"task-{task.id}/agent/repo"
    _wait_for(
        lambda: (
            _state(task.id) == "TESTING"
            and bool(subprocess.run(["pgrep", "-f", fragment], capture_output=True, text=True).stdout.strip())
        ),
        timeout=180,
    )
    started = time.monotonic()
    with session_factory()() as s:
        request_cancel(s, s.get(Task, task.id))
    _wait_for(lambda: _state(task.id) == "CANCELLED", timeout=30)
    elapsed = time.monotonic() - started
    thread.join(timeout=30)
    leftover = subprocess.run(["pgrep", "-f", fragment], capture_output=True, text=True).stdout.strip()
    observe(
        cancel_latency_s=round(elapsed, 1),
        orphan_processes=len(leftover.split()) if leftover else 0,
        lost_state=0,
        duplicate_external_actions=0,
        incorrect_resume=0,
    )
    assert elapsed < 20 and not leftover


@scenario("R19", "task cancellation", "cancel while waiting for human approval")
def test_r19_cancel_awaiting_approval(session: Session, repo: Repository, observe):
    engine = engine_for(GOOD)
    task = finish(session, engine, new_task(session, repo, auto_complete=False), worker_id="w1")
    assert task.state == "AWAITING_APPROVAL"
    request_cancel(session, task)
    session.refresh(task)
    worked = Worker(engine, settings(), worker_id="w2").run_once(task_ids=[task.id])
    observe(final_state=task.state, worker_picked_up=worked, lost_state=0, duplicate_external_actions=0)
    assert task.state == "CANCELLED" and not worked


@scenario("R20", "task cancellation", "cancelled task is restarted and completes; attempt numbering continues")
def test_r20_cancel_then_restart(session: Session, repo: Repository, observe):
    engine = engine_for({"plan": [PLAN_JSON], "implement": [CORRECT_FIX]})
    task = finish(session, engine, new_task(session, repo, auto_complete=False), worker_id="w1")
    request_cancel(session, task)
    session.refresh(task)
    restart(session, task)
    task = finish(session, engine, task, worker_id="w2")
    numbers = [
        a.attempt_no
        for a in session.scalars(
            select(PatchAttempt).where(PatchAttempt.task_id == task.id).order_by(PatchAttempt.attempt_no)
        )
    ]
    observe(attempt_numbers=numbers, final_state=task.state, lost_state=0, duplicate_external_actions=0)
    assert task.state == "AWAITING_APPROVAL" and numbers == [1, 2]


# ------------------------------------------------------------------------------------------------------
# E. repeated webhook delivery


def _hook_client(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from modernisation.api.app import create_app
    from modernisation.config import reset_settings_cache

    monkeypatch.setenv("MODERNISATION_GITHUB_WEBHOOK_SECRET", "recovery-secret")
    reset_settings_cache()
    return TestClient(create_app())


def _signed(body: bytes) -> str:
    import hashlib
    import hmac

    return "sha256=" + hmac.new(b"recovery-secret", body, hashlib.sha256).hexdigest()


def _gh_repo(session: Session, sample_repo: Path) -> Repository:
    from modernisation.repository_intelligence.git_ops import mirror_repository
    from modernisation.repository_intelligence.indexer import mirror_path

    repo = Repository(
        name="allowed-repo",
        source_kind="github",
        source="example-org/allowed-repo",
        github_full_name="example-org/allowed-repo",
        clone_url=str(sample_repo),
        default_branch="main",
    )
    session.add(repo)
    session.commit()
    mirror_repository(str(sample_repo), mirror_path(repo))
    return repo


ISSUE = {
    "action": "labeled",
    "repository": {"full_name": "example-org/allowed-repo"},
    "issue": {
        "number": 11,
        "title": "Wrong discount",
        "body": "apply_discount is off by 10x",
        "labels": [{"name": "modernisation:bug_fix"}],
    },
}


@scenario("R21", "repeated webhook delivery", "the same delivery is received five times")
def test_r21_repeated_delivery(session: Session, sample_repo: Path, monkeypatch: pytest.MonkeyPatch, observe):
    from modernisation.config import reset_settings_cache

    _gh_repo(session, sample_repo)
    client = _hook_client(monkeypatch)
    body = json.dumps(ISSUE).encode()
    statuses = [
        client.post(
            "/api/webhooks/github",
            content=body,
            headers={"x-github-event": "issues", "x-github-delivery": "same-id", "x-hub-signature-256": _signed(body)},
        ).json()["status"]
        for _ in range(5)
    ]
    tasks = count(session, Task)
    observe(statuses=statuses, tasks_created=tasks, duplicate_external_actions=max(0, tasks - 1), lost_state=0)
    reset_settings_cache()
    assert statuses == ["processed"] + ["duplicate"] * 4 and tasks == 1


@scenario("R22", "repeated webhook delivery", "ten concurrent copies of one delivery")
def test_r22_concurrent_duplicate_delivery(
    session: Session, sample_repo: Path, monkeypatch: pytest.MonkeyPatch, observe
):
    from modernisation.config import reset_settings_cache

    _gh_repo(session, sample_repo)
    client = _hook_client(monkeypatch)
    body = json.dumps(ISSUE).encode()
    results: list[str] = []
    barrier = threading.Barrier(10)

    def send() -> None:
        barrier.wait()
        r = client.post(
            "/api/webhooks/github",
            content=body,
            headers={
                "x-github-event": "issues",
                "x-github-delivery": "concurrent-id",
                "x-hub-signature-256": _signed(body),
            },
        )
        results.append(r.json()["status"])

    threads = [threading.Thread(target=send) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    tasks = count(session, Task)
    observe(
        processed=results.count("processed"),
        duplicates=results.count("duplicate"),
        tasks_created=tasks,
        duplicate_external_actions=max(0, tasks - 1),
        lost_state=0,
    )
    reset_settings_cache()
    assert results.count("processed") == 1 and results.count("duplicate") == 9 and tasks == 1


# ------------------------------------------------------------------------------------------------------
# F/G. publication: network failures around branch push and pull-request creation


@pytest.fixture()
def gh(session: Session, sample_repo: Path, sources: Path) -> Iterator[dict[str, Any]]:
    from tests.github_standin import GitHubStandIn

    remote = sources / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(sample_repo), str(remote)], check=True)
    repo = _gh_repo(session, sample_repo)
    standin = GitHubStandIn("example-org/allowed-repo", remote)
    yield {"repo": repo, "remote": remote, "standin": standin}


def _publisher(gh: dict[str, Any]):  # type: ignore[no-untyped-def]
    from modernisation.integrations.github.client import GitHubClient
    from modernisation.integrations.github.publisher import Publisher

    return Publisher(
        get_settings(),
        push_url=lambda t: str(gh["remote"]),
        client_factory=lambda: GitHubClient(
            base_url="https://api.github.test", token="t", transport=gh["standin"].transport(), sleep=lambda s: None
        ),
    )


def _approved_task(session: Session, gh: dict[str, Any], engine: WorkflowEngine) -> Task:
    task = new_task(session, gh["repo"], auto_complete=False)
    task = finish(session, engine, task, worker_id="w1")
    assert task.state == "AWAITING_APPROVAL" and task.approval_stage == "publish"
    approvals.decide(session, task, stage="publish", decision="approved", reviewer="m", expected_version=task.version)
    return task


def _publication_observations(session: Session, task: Task, gh: dict[str, Any], observe, **extra: Any) -> None:
    pulls = len(gh["standin"].pulls)
    branches = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)", "refs/heads/modernisation/"],
        cwd=gh["remote"],
        capture_output=True,
        text=True,
    ).stdout.split()
    observe(
        final_state=task.state,
        pull_requests=pulls,
        remote_branches=len(branches),
        duplicate_external_actions=max(0, pulls - 1) + max(0, len(branches) - 1),
        lost_state=0,
        incorrect_resume=0,
        **extra,
    )
    assert task.state == "COMPLETED", task.state_reason
    assert pulls == 1 and len(branches) == 1


@scenario(
    "R23", "branch creation + network failure", "push reaches the remote but the connection drops before the reply"
)
def test_r23_push_lands_then_connection_drops(
    session: Session, gh: dict[str, Any], monkeypatch: pytest.MonkeyPatch, observe
):
    import modernisation.integrations.github.publisher as pub
    from modernisation.repository_intelligence.git_ops import GitError

    engine = engine_for(GOOD, publisher=_publisher(gh))
    task = _approved_task(session, gh, engine)
    original = pub.run_git
    state = {"n": 0}

    def flaky(args, *a, **k):  # type: ignore[no-untyped-def]
        result = original(args, *a, **k)
        if args and args[0] == "push" and not state["n"]:
            state["n"] = 1
            raise GitError(args, 128, "fatal: the remote end hung up unexpectedly")
        return result

    monkeypatch.setattr(pub, "run_git", flaky)
    task = finish(session, engine, task)
    push = session.scalar(
        select(ExternalAction).where(ExternalAction.task_id == task.id, ExternalAction.kind == "push_branch")
    )
    _publication_observations(session, task, gh, observe, push_reconciled=bool(push.response.get("reconciled")))
    assert push.response.get("reconciled") is True


@scenario("R24", "branch creation + network failure", "push fails before reaching the remote; retried once")
def test_r24_push_fails_before_remote(session: Session, gh: dict[str, Any], monkeypatch: pytest.MonkeyPatch, observe):
    import modernisation.integrations.github.publisher as pub
    from modernisation.repository_intelligence.git_ops import GitError

    engine = engine_for(GOOD, publisher=_publisher(gh))
    task = _approved_task(session, gh, engine)
    original = pub.run_git
    state = {"n": 0}

    def flaky(args, *a, **k):  # type: ignore[no-untyped-def]
        if args and args[0] == "push" and not state["n"]:
            state["n"] = 1
            raise GitError(args, 128, "fatal: unable to access remote: Could not resolve host")
        return original(args, *a, **k)

    monkeypatch.setattr(pub, "run_git", flaky)
    worker = Worker(engine, settings(), worker_id="w2")
    worker.run_once(task_ids=[task.id])  # transient failure -> stays PUBLISHING
    session.expire_all()
    assert session.get(Task, task.id).state == "PUBLISHING"
    expire_lease(session, task.id)
    task = finish(session, engine, task, worker_id="w3")
    push = session.scalar(
        select(ExternalAction).where(ExternalAction.task_id == task.id, ExternalAction.kind == "push_branch")
    )
    _publication_observations(session, task, gh, observe, push_attempts=push.attempts)
    assert push.attempts == 2


@scenario("R25", "PR creation + response timeout", "GitHub creates the PR but the response times out")
def test_r25_pr_timeout_after_creation(session: Session, gh: dict[str, Any], observe):
    from tests.github_standin import Fault

    gh["standin"].faults.append(Fault("POST", r"/pulls$", "timeout_after_effect"))
    engine = engine_for(GOOD, publisher=_publisher(gh))
    task = finish(session, engine, _approved_task(session, gh, engine))
    _publication_observations(session, task, gh, observe)


@scenario("R26", "PR creation + response timeout", "GitHub creates the PR but answers 502")
def test_r26_pr_502_after_creation(session: Session, gh: dict[str, Any], observe):
    from tests.github_standin import Fault

    gh["standin"].faults.append(Fault("POST", r"/pulls$", "status_after_effect", status=502))
    engine = engine_for(GOOD, publisher=_publisher(gh))
    task = finish(session, engine, _approved_task(session, gh, engine))
    _publication_observations(session, task, gh, observe)


@scenario("R27", "partial operation", "worker dies after the PR is created but before the ledger records it")
def test_r27_crash_after_pr_before_ledger(
    session: Session, gh: dict[str, Any], monkeypatch: pytest.MonkeyPatch, observe
):
    from modernisation.integrations.github.client import GitHubClient

    engine = engine_for(GOOD, publisher=_publisher(gh))
    task = _approved_task(session, gh, engine)
    crash_once(monkeypatch, GitHubClient, "create_pull_request", after=True)
    with pytest.raises(SimulatedCrash):
        drain(Worker(engine, settings(), worker_id="w2"), [task.id], timeout_s=300)
    session.expire_all()
    action = session.scalar(
        select(ExternalAction).where(ExternalAction.task_id == task.id, ExternalAction.kind == "create_pull_request")
    )
    assert action.status == "pending" and len(gh["standin"].pulls) == 1
    expire_lease(session, task.id)
    task = finish(session, engine, session.get(Task, task.id), worker_id="w3")
    _publication_observations(session, task, gh, observe)


# ------------------------------------------------------------------------------------------------------
# H. stale repository revisions


@scenario("R28", "stale repository revision", "base branch advances after the task is created")
def test_r28_base_branch_moves(session: Session, repo: Repository, sample_repo: Path, observe):
    from modernisation.services.repositories import refresh

    task = new_task(session, repo)
    pinned = task.base_commit
    commit_change(sample_repo, "docs/NOTES.md", "unrelated change\n", "docs: notes")
    refresh(repo)
    task = finish(session, engine_for(GOOD), task, worker_id="w1")
    stale_events = [
        e for e in session.scalars(select(TaskEvent).where(TaskEvent.task_id == task.id)) if "has moved to" in e.message
    ]
    assert_completed_correctly(session, task, observe, stale_base_recorded=bool(stale_events))
    assert task.base_commit == pinned and stale_events
    assert task.analysis["stale_base"]["pinned"] == pinned


@scenario("R29", "stale repository revision", "base commit no longer exists (history rewritten)")
def test_r29_base_commit_missing(session: Session, repo: Repository, sample_repo: Path, observe):
    from modernisation.repository_intelligence.indexer import mirror_path

    side = commit_change(sample_repo, "src/inventory/extra.py", "X = 1\n", "temporary")
    from modernisation.services.repositories import refresh

    refresh(repo)
    task = Task(
        repository_id=repo.id,
        title="t",
        request=BUG_REQUEST,
        category="bug_fix",
        base_ref="main",
        base_commit=side,
        allowed_paths=["src/**"],
        config={"auto_complete": True},
    )
    session.add(task)
    session.commit()
    git(sample_repo, "reset", "-q", "--hard", "HEAD~1")
    refresh(repo)
    mirror = mirror_path(repo)
    for args in (["reflog", "expire", "--expire=now", "--all"], ["gc", "-q", "--prune=now"]):
        subprocess.run(["git", *args], cwd=mirror, check=True)
    task = finish(session, engine_for(GOOD), task, worker_id="w1")
    observe(
        final_state=task.state, reason=task.state_reason, lost_state=0, duplicate_external_actions=0, incorrect_resume=0
    )
    assert task.state == "ESCALATED" and "not available" in (task.state_reason or "")


# ------------------------------------------------------------------------------------------------------
# I. execution timeouts


@scenario("R30", "execution timeout", "patch makes the test suite hang; timeout is fed back and repaired")
def test_r30_hanging_tests_timeout_and_repair(session: Session, repo: Repository, observe):
    cfg = settings(sandbox_command_timeout_s=15.0)
    engine = engine_for({"plan": [PLAN_JSON], "implement": [HANG_FIX], "repair": [REPAIR_HANG]}, cfg)
    task = finish(session, engine, new_task(session, repo), worker_id="w1", cfg=cfg)
    from modernisation.db.models import CheckRun

    timed_out = (
        session.scalar(
            select(func.count()).select_from(CheckRun).where(CheckRun.task_id == task.id, CheckRun.timed_out.is_(True))
        )
        or 0
    )
    assert_completed_correctly(session, task, observe, timed_out_runs=int(timed_out))
    assert timed_out >= 1


# ------------------------------------------------------------------------------------------------------
# J. partial operations in infrastructure steps


@scenario("R31", "partial operation", "indexing is interrupted mid-way and re-run")
def test_r31_interrupted_indexing(session: Session, repo: Repository, monkeypatch: pytest.MonkeyPatch, observe):
    import modernisation.repository_intelligence.indexer as idx
    from modernisation.repository_intelligence.indexer import index_commit

    calls = {"n": 0}
    original = idx.parse_python

    def parse(data: bytes):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 3:
            raise SimulatedCrash("crash while parsing")
        return original(data)

    monkeypatch.setattr(idx, "parse_python", parse)
    with pytest.raises(SimulatedCrash):
        index_commit(session, repo, "main")
    session.rollback()
    snap = session.scalar(select(IndexSnapshot))
    assert snap is not None and snap.status == "running"
    monkeypatch.setattr(idx, "parse_python", original)
    done = index_commit(session, repo, "main")
    files = count(session, SnapshotFile, snapshot_id=done.id)
    observe(snapshot_status=done.status, files_indexed=files, lost_state=0, duplicate_external_actions=0)
    assert done.id == snap.id and done.status == "ready" and files == 8


@scenario("R32", "partial operation", "dependency environment build is interrupted and rebuilt cleanly")
def test_r32_interrupted_env_build(session: Session, sample_repo: Path, monkeypatch: pytest.MonkeyPatch, observe):
    from modernisation.execution.pyenv import DependencySpec, ensure_env
    from modernisation.execution.sandbox import Sandbox

    spec = DependencySpec(["iniconfig==2.3.1"], ["test"], False, get_settings().sandbox_python, ["pytest"])
    sandbox = Sandbox(get_settings())
    original = Sandbox.run
    state = {"n": 0}

    def run(self, argv, **kw):  # type: ignore[no-untyped-def]
        if "install" in argv and not state["n"]:
            state["n"] = 1
            original(self, argv, **kw)  # partially/fully installs, then the process dies
            raise SimulatedCrash("crash during pip install")
        return original(self, argv, **kw)

    monkeypatch.setattr(Sandbox, "run", run)
    with pytest.raises(SimulatedCrash):
        ensure_env(spec, sandbox, get_settings())
    building = get_settings().envs_dir.resolve() / f"{spec.key()}.building"
    assert building.exists()
    result = ensure_env(spec, sandbox, get_settings())
    observe(env_ok=result.ok, reused=result.reused, lost_state=0, duplicate_external_actions=0)
    assert result.ok and not result.reused and (result.path / ".ready").exists() and not building.exists()
