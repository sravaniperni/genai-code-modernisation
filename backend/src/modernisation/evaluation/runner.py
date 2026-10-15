"""Benchmark execution.

Modes (same task set, same model, same sandbox limits):

* ``platform``  full agentic workflow: retrieval, structured plan, edits, sandboxed checks, bounded repair
                (attempt budget from the task, default 3), independent verification.
* ``baseline``  single-shot: keyword-retrieved files, one edit generation, no plan, no test feedback, no
                repair. Its patch is evaluated whether or not its own checks passed.

A platform patch is evaluated only if the platform itself reached COMPLETED (verified); an escalated task is a
failure even if a partial diff exists. Runs are resumable: tasks that already have a result for the run key
are skipped, never re-rolled.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from modernisation.agents.states import TaskState
from modernisation.agents.store import add_event, request_cancel
from modernisation.agents.worker import Worker, drain
from modernisation.agents.workflow import WorkflowEngine
from modernisation.config import Settings, get_settings
from modernisation.db.models import EvaluationResult, EvaluationRun, ModelCall, PatchAttempt, Repository, Task
from modernisation.db.session import session_scope
from modernisation.evaluation.acceptance import AcceptanceRunner
from modernisation.evaluation.taskset import BenchmarkTask, materialise, taskset_hash
from modernisation.llm.factory import build_client, db_sink
from modernisation.repository_intelligence.indexer import git_for
from modernisation.services.repositories import register_local

log = logging.getLogger(__name__)


def classify_escalation(reason: str | None) -> str:
    r = (reason or "").lower()
    if "no applicable change" in r or "edits rejected" in r:
        return "no_valid_patch"
    if "policy" in r:
        return "policy_violation"
    if "checks still failing" in r or "attempt budget" in r or "did not pass checks" in r:
        return "checks_failed"
    if "clarification" in r:
        return "clarification_requested"
    if "environment" in r:
        return "environment_failure"
    if "no in-scope files" in r:
        return "no_target_identified"
    return "escalated_other"


def platform_revision(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


class EvaluationRunner:
    def __init__(
        self,
        eval_dir: Path,
        *,
        mode: str,
        run_key: str,
        split: str,
        settings: Settings | None = None,
        task_timeout_s: float = 2400.0,
        evidence_dir: Path | None = None,
    ):
        if mode not in ("platform", "baseline"):
            raise ValueError("mode must be 'platform' or 'baseline'")
        self.eval_dir = eval_dir.resolve()
        self.mode = mode
        self.run_key = run_key
        self.split = split
        self.settings = settings or get_settings()
        self.task_timeout_s = task_timeout_s
        self.acceptance = AcceptanceRunner(self.eval_dir, self.settings)
        self.sources = (self.settings.data_dir / "benchmark" / "sources").resolve()
        self.version = taskset_hash(self.eval_dir)
        self.evidence = (evidence_dir or self.eval_dir.parent / "reports" / "runs") / f"{run_key}.jsonl"
        if self.sources not in [p.resolve() for p in self.settings.allowed_local_roots]:
            self.settings = self.settings.model_copy(
                update={"allowed_local_roots": [*self.settings.allowed_local_roots, self.sources]}
            )

    # ------------------------------------------------------------------------------------------------
    def _run_row(self) -> int:
        with session_scope() as session:
            run = session.scalar(select(EvaluationRun).where(EvaluationRun.run_key == self.run_key))
            if run is not None:
                if run.taskset_version != self.version or run.mode != self.mode:
                    raise RuntimeError(
                        f"run {self.run_key} exists with a different task set or mode; use a new run key"
                    )
                return run.id
            s = self.settings
            run = EvaluationRun(
                run_key=self.run_key,
                mode=self.mode,
                taskset_version=self.version,
                split=self.split,
                model_provider=s.model_provider,
                model_name=s.model_name or "none",
                config={
                    "temperature": s.model_temperature,
                    "max_output_tokens": s.model_max_output_tokens,
                    "structured_output": s.model_structured_output,
                    "model_base_url": s.model_base_url,
                    "strategy": "agentic" if self.mode == "platform" else "single_shot",
                    "sandbox": {
                        "timeout_s": s.sandbox_command_timeout_s,
                        "memory_mb": s.sandbox_memory_mb,
                        "max_processes": s.sandbox_max_processes,
                    },
                    "task_timeout_s": self.task_timeout_s,
                    "context_chars": s.eval_context_chars,
                    "edit_context_chars": s.eval_edit_context_chars,
                    "platform_revision": platform_revision(self.eval_dir.parent),
                },
            )
            session.add(run)
            session.flush()
            return run.id

    def _repository(self, task: BenchmarkTask) -> tuple[int, str]:
        dest = self.sources / task.id
        sha = materialise(task, self.eval_dir, dest)
        for p in [self.sources, dest]:
            p.chmod(0o755)
        with session_scope() as session:
            name = f"bench-{task.id}"
            repo = session.scalar(select(Repository).where(Repository.name == name))
            if repo is None:
                repo = register_local(session, name, str(dest), self.settings)
            else:
                from modernisation.services.repositories import refresh

                refresh(repo, self.settings)
            if git_for(repo).resolve("main") != sha:
                raise RuntimeError(f"fixture for {task.id} is not deterministic")
            return repo.id, sha

    def _engine(self) -> WorkflowEngine:
        settings = self.settings

        def factory(task: Task):  # type: ignore[no-untyped-def]
            return build_client(settings, db_sink(task.id, task.evaluation_run_id))

        return WorkflowEngine(settings=settings, model_factory=factory)

    # ------------------------------------------------------------------------------------------------
    def run(self, tasks: list[BenchmarkTask]) -> int:
        run_id = self._run_row()
        with session_scope() as session:
            done = set(
                session.scalars(select(EvaluationResult.benchmark_task_id).where(EvaluationResult.run_id == run_id))
            )
        engine = self._engine()
        self.evidence.parent.mkdir(parents=True, exist_ok=True)
        for index, task in enumerate(tasks, start=1):
            if task.id in done:
                continue
            log.info("evaluating", extra={"run": self.run_key, "task": task.id, "n": index, "of": len(tasks)})
            started = time.monotonic()
            try:
                record = self.run_one(task, run_id, engine)
            except Exception as exc:  # infrastructure error: recorded, never dropped from the denominator
                log.exception("evaluation error", extra={"task": task.id})
                record = {
                    "outcome": "error",
                    "failure_category": "infrastructure_error",
                    "details": {"error": f"{type(exc).__name__}: {exc}"[:2000]},
                    "task_id": None,
                }
            record["wall_ms"] = int((time.monotonic() - started) * 1000)
            self._store(run_id, task, record)
        with session_scope() as session:
            run = session.get(EvaluationRun, run_id)
            assert run is not None
            run.status = "finished"
            run.finished_at = datetime.now(UTC)
        return run_id

    def run_one(self, task: BenchmarkTask, run_id: int, engine: WorkflowEngine) -> dict[str, Any]:
        repo_id, sha = self._repository(task)
        with session_scope() as session:
            row = Task(
                repository_id=repo_id,
                title=task.title,
                request=task.request,
                category=task.category,
                base_ref="main",
                base_commit=sha,
                allowed_paths=task.allowed_paths,
                origin="evaluation",
                evaluation_run_id=run_id,
                config={
                    "max_attempts": task.max_attempts if self.mode == "platform" else 1,
                    "auto_complete": True,
                    "strategy": "agentic" if self.mode == "platform" else "single_shot",
                    "context_chars": self.settings.eval_context_chars,
                    "edit_context_chars": self.settings.eval_edit_context_chars,
                },
            )
            session.add(row)
            session.flush()
            add_event(session, row.id, "state", f"evaluation task {task.id} ({self.run_key})", state="QUEUED")
            task_id = row.id
        worker = Worker(engine, self.settings, worker_id=f"eval-{self.run_key}")
        started = time.monotonic()
        timed_out = False
        try:
            drain(worker, [task_id], timeout_s=self.task_timeout_s)
        except TimeoutError:
            timed_out = True
            with session_scope() as session:
                t = session.get(Task, task_id)
                if t is not None and TaskState(t.state) not in (
                    TaskState.COMPLETED,
                    TaskState.ESCALATED,
                    TaskState.FAILED,
                    TaskState.CANCELLED,
                ):
                    request_cancel(session, t)
        duration_ms = int((time.monotonic() - started) * 1000)

        with session_scope() as session:
            t = session.get(Task, task_id)
            assert t is not None
            state, reason, final_diff = t.state, t.state_reason, t.final_diff
            attempts = session.query(PatchAttempt).filter_by(task_id=task_id).count()
            calls = list(session.scalars(select(ModelCall).where(ModelCall.task_id == task_id)))
        usage = {
            "model_calls": len(calls),
            "failed_model_calls": sum(1 for c in calls if c.status != "ok"),
            "prompt_tokens": sum(c.prompt_tokens or 0 for c in calls),
            "completion_tokens": sum(c.completion_tokens or 0 for c in calls),
            "model_latency_ms": sum(c.latency_ms for c in calls),
            "cost_usd": (
                sum(c.cost_usd or 0.0 for c in calls)
                if calls and all(c.cost_usd is not None for c in calls if c.status == "ok")
                else None
            ),
        }
        base = {
            "task_id": task_id,
            "state": state,
            "state_reason": reason,
            "attempts": attempts,
            "duration_ms": duration_ms,
            **usage,
        }

        if timed_out:
            return {**base, "outcome": "timeout", "failure_category": "timeout", "details": {}}
        if state == TaskState.FAILED.value:
            return {
                **base,
                "outcome": "error",
                "failure_category": "infrastructure_error",
                "details": {"reason": reason},
            }
        candidate: str | None = None
        if self.mode == "platform":
            if state != TaskState.COMPLETED.value:
                return {
                    **base,
                    "outcome": "failure",
                    "failure_category": classify_escalation(reason),
                    "details": {"reason": reason},
                }
            candidate = final_diff
        else:
            candidate = final_diff
            if not candidate:
                return {
                    **base,
                    "outcome": "failure",
                    "failure_category": classify_escalation(reason),
                    "details": {"reason": reason},
                }
        outcome = self.acceptance.evaluate(task, candidate, self.version)
        return {
            **base,
            "outcome": "success" if outcome.passed else "failure",
            "failure_category": outcome.failure_category,
            "diff": candidate,
            "details": {
                "acceptance": {k: v for k, v in outcome.acceptance.items() if k != "output_tail"},
                "acceptance_output_tail": outcome.acceptance.get("output_tail", "")[-1500:],
                "regression": outcome.regression,
                "policy_violations": outcome.policy_violations,
                "evaluation_error": outcome.details,
            },
        }

    def _store(self, run_id: int, task: BenchmarkTask, record: dict[str, Any]) -> None:
        with session_scope() as session:
            session.add(
                EvaluationResult(
                    run_id=run_id,
                    benchmark_task_id=task.id,
                    repo=task.repo,
                    category=task.category,
                    outcome=record["outcome"],
                    failure_category=record.get("failure_category"),
                    task_id=record.get("task_id"),
                    attempts=record.get("attempts", 0),
                    duration_ms=record.get("duration_ms", record.get("wall_ms", 0)),
                    model_calls=record.get("model_calls", 0),
                    prompt_tokens=record.get("prompt_tokens", 0),
                    completion_tokens=record.get("completion_tokens", 0),
                    cost_usd=record.get("cost_usd"),
                    details={
                        k: v
                        for k, v in record.items()
                        if k
                        in ("details", "state", "state_reason", "wall_ms", "model_latency_ms", "failed_model_calls")
                    },
                )
            )
        line = {
            "run_key": self.run_key,
            "mode": self.mode,
            "taskset_version": self.version,
            "benchmark_task_id": task.id,
            "repo": task.repo,
            "category": task.category,
            "split": task.split,
            "recorded_at": datetime.now(UTC).isoformat(),
            **record,
        }
        with self.evidence.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, default=str) + "\n")
