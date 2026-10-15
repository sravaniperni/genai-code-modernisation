"""End-to-end workflow tests: real PostgreSQL, git, sandbox and checks; scripted model responses.

The scripted model makes the agent's *decisions* deterministic so the platform's mechanics can be
verified. These tests do not measure model capability.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from modernisation.agents import approvals
from modernisation.agents.states import IllegalTransition, TaskState
from modernisation.agents.store import add_event, request_cancel, restart
from modernisation.agents.worker import Worker, drain
from modernisation.agents.workflow import WorkflowEngine
from modernisation.config import get_settings
from modernisation.db.models import CheckRun, ModelCall, PatchAttempt, Repository, Task
from modernisation.integrations.github.publisher import Publisher
from modernisation.llm.factory import db_sink
from modernisation.repository_intelligence.indexer import git_for
from modernisation.services.repositories import register_local
from tests.helpers import BUG_REQUEST, CORRECT_FIX, PLAN_JSON, ScriptedModel

pytestmark = [pytest.mark.postgres, pytest.mark.sandbox]

WRONG_FIX = """src/inventory/pricing.py
<<<<<<< SEARCH
    return round(price - price * percent / 1000, 2)
=======
    return round(price * percent / 100, 2)
>>>>>>> REPLACE
"""
REPAIR_AFTER_WRONG = """src/inventory/pricing.py
<<<<<<< SEARCH
    return round(price * percent / 100, 2)
=======
    return round(price - price * percent / 100, 2)
>>>>>>> REPLACE
"""
STILL_WRONG = """src/inventory/pricing.py
<<<<<<< SEARCH
    return round(price * percent / 100, 2)
=======
    return round(price * percent / 10, 2)
>>>>>>> REPLACE
"""
NO_MATCH_FIX = """src/inventory/pricing.py
<<<<<<< SEARCH
    return price * 0.9
=======
    return price
>>>>>>> REPLACE
"""
WORKFLOW_TAMPER = """.github/workflows/ci.yml
<<<<<<< SEARCH
=======
on: push
>>>>>>> REPLACE
"""
SKIP_TESTS = """tests/test_pricing.py
<<<<<<< SEARCH
def test_zero_discount_keeps_price():
=======
import pytest


@pytest.mark.skip
def test_zero_discount_keeps_price():
>>>>>>> REPLACE
"""


def make_task(session: Session, repo: Repository, **config: Any) -> Task:
    base = git_for(repo).resolve("main")
    task = Task(
        repository_id=repo.id,
        title="Fix discount calculation",
        request=BUG_REQUEST,
        category="bug_fix",
        base_ref="main",
        base_commit=base,
        allowed_paths=["src/**", "tests/**", "pyproject.toml"],
        config={"max_attempts": 3, **config},
    )
    session.add(task)
    session.commit()
    return task


def engine_with(responses: dict[str, list[Any]], store: dict[str, ScriptedModel]) -> WorkflowEngine:
    def factory(task: Task) -> ScriptedModel:
        model = ScriptedModel(responses, sink=db_sink(task.id))
        store["model"] = model
        return model

    return WorkflowEngine(settings=get_settings(), model_factory=factory, publisher=Publisher(get_settings()))


def run(session: Session, engine: WorkflowEngine, task: Task) -> Task:
    worker = Worker(engine, get_settings(), worker_id="test-worker")
    drain(worker, [task.id], timeout_s=600)
    session.expire_all()
    refreshed = session.get(Task, task.id)
    assert refreshed is not None
    return refreshed


@pytest.fixture()
def repo(session: Session, sample_repo: Path) -> Repository:
    return register_local(session, "inventory", str(sample_repo))


def test_happy_path_bug_fix_to_review_and_local_publication(session: Session, repo: Repository):
    store: dict[str, ScriptedModel] = {}
    engine = engine_with({"plan": [PLAN_JSON], "implement": [CORRECT_FIX]}, store)
    task = run(session, engine, make_task(session, repo))

    assert task.state == "AWAITING_APPROVAL" and task.approval_stage == "publish", task.state_reason
    assert task.final_diff and "percent / 100, 2)" in task.final_diff and "/ 1000" in task.final_diff
    assert task.result and task.result["verified"] is True
    phases = {c.phase for c in session.scalars(select(CheckRun).where(CheckRun.task_id == task.id))}
    assert phases == {"baseline", "attempt", "verification"}
    assert session.scalar(select(ModelCall).where(ModelCall.task_id == task.id, ModelCall.purpose == "plan"))
    # the model saw repository context retrieved from the index
    plan_prompt = store["model"].calls[0][1][-1].content
    assert "src/inventory/pricing.py" in plan_prompt and "percent / 1000" in plan_prompt

    # approval bound to the reviewed version
    with pytest.raises(IllegalTransition):
        approvals.decide(session, task, stage="publish", decision="approved", reviewer="r", expected_version=0)
    approvals.decide(
        session, task, stage="publish", decision="approved", reviewer="reviewer@example", expected_version=task.version
    )
    task = run(session, engine, task)
    assert task.state == "COMPLETED", task.state_reason
    pub = task.result["publication"]
    assert pub["kind"] == "local" and pub["branch"].startswith("modernisation/task-")
    # the branch exists in the platform mirror (never in the source repository)
    assert pub["branch"] in git_for(repo).branches()
    transitions = [e.message.split(":")[0] for e in task_events(session, task.id) if e.kind == "state"]
    assert transitions[:3] == ["QUEUED -> ANALYSING", "ANALYSING -> PLANNING", "PLANNING -> IMPLEMENTING"]


def test_failed_checks_trigger_bounded_repair_with_test_feedback(session: Session, repo: Repository):
    store: dict[str, ScriptedModel] = {}
    engine = engine_with({"plan": [PLAN_JSON], "implement": [WRONG_FIX], "repair": [REPAIR_AFTER_WRONG]}, store)
    task = run(session, engine, make_task(session, repo))
    assert task.state == "AWAITING_APPROVAL", task.state_reason
    attempts = list(
        session.scalars(select(PatchAttempt).where(PatchAttempt.task_id == task.id).order_by(PatchAttempt.attempt_no))
    )
    assert [(a.kind, a.checks_passed) for a in attempts] == [("initial", False), ("repair", True)]
    repair_prompt = next(m for p, m in store["model"].calls if p == "repair")[-1].content
    assert "test_zero_discount_keeps_price" in repair_prompt  # failing test fed back to the model


def test_rejected_edits_are_repaired(session: Session, repo: Repository):
    store: dict[str, ScriptedModel] = {}
    engine = engine_with({"plan": [PLAN_JSON], "implement": [NO_MATCH_FIX], "repair": [CORRECT_FIX]}, store)
    task = run(session, engine, make_task(session, repo))
    assert task.state == "AWAITING_APPROVAL", task.state_reason
    first = session.scalar(select(PatchAttempt).where(PatchAttempt.task_id == task.id, PatchAttempt.attempt_no == 1))
    assert first and first.apply_status == "rejected" and "no_match" in (first.rejection_reason or "")


def test_attempt_budget_exhaustion_escalates(session: Session, repo: Repository):
    store: dict[str, ScriptedModel] = {}
    engine = engine_with({"plan": [PLAN_JSON], "implement": [WRONG_FIX], "repair": [STILL_WRONG]}, store)
    task = run(session, engine, make_task(session, repo, max_attempts=2))
    assert task.state == "ESCALATED"
    assert "2 attempt" in (task.state_reason or "")
    assert session.query(PatchAttempt).filter_by(task_id=task.id).count() == 2
    assert task.final_diff is None


def test_policy_violations_never_touch_workspace_and_escalate(session: Session, repo: Repository):
    store: dict[str, ScriptedModel] = {}
    engine = engine_with({"plan": [PLAN_JSON], "implement": [WORKFLOW_TAMPER], "repair": [SKIP_TESTS]}, store)
    task = run(session, engine, make_task(session, repo, max_attempts=3))
    assert task.state == "ESCALATED"
    reasons = [
        a.rejection_reason
        for a in session.scalars(
            select(PatchAttempt).where(PatchAttempt.task_id == task.id).order_by(PatchAttempt.attempt_no)
        )
    ]
    assert reasons[0].startswith("forbidden_path") and reasons[1].startswith("test_weakened")
    assert "repeated policy violations" in (task.state_reason or "")


def test_single_shot_strategy_has_no_repair(session: Session, repo: Repository):
    store: dict[str, ScriptedModel] = {}
    engine = engine_with({"implement": [WRONG_FIX]}, store)
    task = run(session, engine, make_task(session, repo, strategy="single_shot"))
    assert task.state == "ESCALATED"
    assert [p for p, _ in store["model"].calls] == ["implement"]  # no plan call, no repair call
    assert task.final_diff and "percent / 100, 2)" in task.final_diff  # kept for evaluation, marked unverified
    assert task.result == {"verified": False, "strategy": "single_shot", "reason": "check_failure"}


def test_plan_approval_gate(session: Session, repo: Repository):
    store: dict[str, ScriptedModel] = {}
    engine = engine_with({"plan": [PLAN_JSON], "implement": [CORRECT_FIX]}, store)
    task = run(session, engine, make_task(session, repo, require_plan_approval=True))
    assert task.state == "AWAITING_APPROVAL" and task.approval_stage == "plan"
    assert [p for p, _ in store["model"].calls] == ["plan"]  # nothing implemented before approval
    with pytest.raises(IllegalTransition):
        approvals.decide(
            session, task, stage="publish", decision="approved", reviewer="r", expected_version=task.version
        )  # wrong stage
    approvals.decide(session, task, stage="plan", decision="approved", reviewer="lead", expected_version=task.version)
    task = run(session, engine, task)
    assert task.state == "AWAITING_APPROVAL" and task.approval_stage == "publish"


def test_rejected_plan_cancels_task(session: Session, repo: Repository):
    engine = engine_with({"plan": [PLAN_JSON]}, {})
    task = run(session, engine, make_task(session, repo, require_plan_approval=True))
    approvals.decide(session, task, stage="plan", decision="rejected", reviewer="lead", expected_version=task.version)
    session.refresh(task)
    assert task.state == "CANCELLED"


def test_cancel_queued_task_and_restart(session: Session, repo: Repository):
    task = make_task(session, repo)
    request_cancel(session, task)
    session.refresh(task)
    assert task.state == "CANCELLED"
    restart(session, task)
    assert task.state == "QUEUED" and not task.cancel_requested


def test_clarification_request_escalates(session: Session, repo: Repository):
    plan = PLAN_JSON.replace('"needs_clarification": false', '"needs_clarification": true').replace(
        '"clarification_questions": []', '"clarification_questions": ["Which currency rounding applies?"]'
    )
    engine = engine_with({"plan": [plan]}, {})
    task = run(session, engine, make_task(session, repo))
    assert task.state == "ESCALATED" and "Which currency rounding" in (task.state_reason or "")


def test_out_of_scope_plan_targets_are_dropped(session: Session, repo: Repository):
    plan = PLAN_JSON.replace(
        '"target_files": ["src/inventory/pricing.py"]',
        '"target_files": ["src/inventory/pricing.py", "../outside.py", ".git/config"]',
    )
    engine = engine_with({"plan": [plan], "implement": [CORRECT_FIX]}, {})
    task = run(session, engine, make_task(session, repo))
    assert task.plan["target_files"] == ["src/inventory/pricing.py"]
    assert len(task.plan["dropped_targets"]) == 2


def test_missing_model_endpoint_is_reported_not_faked(session: Session, repo: Repository):
    engine = WorkflowEngine(settings=get_settings(), model_factory=lambda t: None)
    task = make_task(session, repo)
    worker = Worker(engine, get_settings(), worker_id="w")
    for _ in range(3):
        worker.run_once(task_ids=[task.id])
    session.expire_all()
    task = session.get(Task, task.id)
    assert task is not None and task.state == "PLANNING"
    events = [e.message for e in task_events(session, task.id)]
    assert any("no model endpoint is configured" in m for m in events)


def task_events(session: Session, task_id: int) -> list[Any]:
    from modernisation.db.models import TaskEvent

    return list(session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)))


def test_event_log_redacts_secrets(session: Session, repo: Repository):
    from modernisation.log import register_secret

    fake_token = "ghp" + "_" + "A" * 36  # built at runtime so no token-shaped literal is committed
    register_secret(fake_token)
    task = make_task(session, repo)
    add_event(
        session,
        task.id,
        "log",
        f"pushing with {fake_token}",
        payload={"url": f"https://x:{fake_token}@github.com"},
    )
    session.commit()
    stored = task_events(session, task.id)[-1]
    assert "ghp_" not in stored.message and "ghp_" not in str(stored.payload)
    assert TaskState(task.state) == TaskState.QUEUED
