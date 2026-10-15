"""Live model integration: runs only when a real endpoint is configured.

    MODERNISATION_TEST_MODEL_BASE_URL=http://127.0.0.1:8081/v1 \
    MODERNISATION_TEST_MODEL_NAME=qwen2.5-coder-1.5b-instruct-q4_k_m \
    MODERNISATION_TEST_MODEL_STRUCTURED=json_object_schema pytest tests/live -m live_llm

A pass shows the platform can drive a real model end to end. Whether the *model* fixes the bug is
recorded, not asserted: capability is measured by the evaluation benchmark, not by unit tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from modernisation.agents.worker import Worker, drain
from modernisation.agents.workflow import WorkflowEngine
from modernisation.config import Settings, get_settings
from modernisation.db.models import ModelCall, Task
from modernisation.llm.base import ChatMessage
from modernisation.llm.factory import build_client, db_sink
from modernisation.repository_intelligence.indexer import git_for
from modernisation.services.repositories import register_local
from tests.helpers import BUG_REQUEST

BASE_URL = os.environ.get("MODERNISATION_TEST_MODEL_BASE_URL")
pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(not BASE_URL, reason="MODERNISATION_TEST_MODEL_BASE_URL not set; live model tests blocked"),
]


def live_settings() -> Settings:
    return get_settings().model_copy(
        update={
            "model_provider": "openai_compatible",
            "model_base_url": BASE_URL,
            "model_name": os.environ.get("MODERNISATION_TEST_MODEL_NAME", "local"),
            "model_structured_output": os.environ.get("MODERNISATION_TEST_MODEL_STRUCTURED", "json_object_schema"),
            "model_timeout_s": 900.0,
            "model_max_output_tokens": 1024,
        }
    )


def test_live_endpoint_round_trip():
    client = build_client(live_settings())
    assert client is not None
    out = client.complete([ChatMessage("user", "Reply with the word ready.")], purpose="health", max_tokens=8)
    assert out.text.strip() and out.prompt_tokens and out.completion_tokens


@pytest.mark.postgres
@pytest.mark.sandbox
def test_live_agent_on_sample_bug(session: Session, sample_repo: Path, capsys: pytest.CaptureFixture[str]):
    settings = live_settings()
    repo = register_local(session, "inventory", str(sample_repo))
    task = Task(
        repository_id=repo.id,
        title="Fix discount calculation",
        request=BUG_REQUEST,
        category="bug_fix",
        base_ref="main",
        base_commit=git_for(repo).resolve("main"),
        allowed_paths=["src/**", "tests/**"],
        config={"max_attempts": 3, "auto_complete": True},
    )
    session.add(task)
    session.commit()
    engine = WorkflowEngine(settings=settings, model_factory=lambda t: build_client(settings, db_sink(t.id)))
    drain(Worker(engine, settings, worker_id="live"), [task.id], timeout_s=3600)
    session.expire_all()
    task = session.get(Task, task.id)
    assert task is not None
    calls = list(session.scalars(select(ModelCall).where(ModelCall.task_id == task.id)))
    assert calls and all(c.provider == "openai_compatible" for c in calls)
    assert any(c.status == "ok" and c.prompt_tokens for c in calls)
    assert task.state in {"COMPLETED", "ESCALATED"}, task.state_reason  # terminal, no crash
    with capsys.disabled():
        print(
            f"\nlive outcome: {task.state} ({task.state_reason}); attempts={task.attempt_count}; "
            f"model calls={len(calls)}; tokens={sum(c.prompt_tokens or 0 for c in calls)}+"
            f"{sum(c.completion_tokens or 0 for c in calls)}"
        )
        if task.final_diff:
            print(task.final_diff)
