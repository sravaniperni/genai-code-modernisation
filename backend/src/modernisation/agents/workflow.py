"""Durable maintenance workflow.

``WorkflowEngine.run_step`` executes the handler for the task's current state and performs at most one
state transition. Handlers are written to be safely re-executed after a crash: completed work is read
from checkpoints, patch attempts and check runs are durable rows, and the workspace is rebuilt from the
base commit plus the recorded diff rather than trusted from disk.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modernisation.agents import prompts
from modernisation.agents.context import editable_file_blocks, excerpt_blocks
from modernisation.agents.edits import EditError, parse_edits
from modernisation.agents.states import TaskState
from modernisation.agents.store import add_event, load_checkpoint, save_checkpoint, transition
from modernisation.config import Settings, get_settings
from modernisation.db.models import Approval, CheckRun, PatchAttempt, Repository, Task
from modernisation.execution.checks import CheckOutcome, CheckRunner, compare_to_baseline, summarise
from modernisation.execution.policy import ChangePolicy, PolicyViolation
from modernisation.execution.pyenv import DependencySpec, EnvResult, ensure_env, read_dependency_spec
from modernisation.execution.sandbox import Sandbox
from modernisation.execution.workspace import Workspace, WorkspaceError
from modernisation.llm.base import ModelClient, ModelError
from modernisation.llm.structured import StructuredOutputError, complete_structured
from modernisation.repository_intelligence.git_ops import GitError
from modernisation.repository_intelligence.indexer import git_for, index_commit
from modernisation.repository_intelligence.languages import is_dependency_manifest
from modernisation.repository_intelligence.retrieval import impact_analysis, load_snapshot, retrieve

log = logging.getLogger(__name__)
S = TaskState


class TransientError(RuntimeError):
    """A failure that should be retried later without changing task state."""


class Publisher(Protocol):
    def publish(self, session: Session, task: Task) -> dict[str, Any]: ...


@dataclass
class TaskConfig:
    max_attempts: int
    strategy: str  # agentic | single_shot
    require_plan_approval: bool
    auto_complete: bool
    allow_test_changes: bool
    context_chars: int
    edit_context_chars: int
    max_output_tokens: int | None

    @classmethod
    def from_task(cls, task: Task, settings: Settings) -> TaskConfig:
        c = task.config or {}
        return cls(
            max_attempts=int(c.get("max_attempts", settings.default_max_attempts)),
            strategy=str(c.get("strategy", "agentic")),
            require_plan_approval=bool(c.get("require_plan_approval", settings.require_plan_approval)),
            auto_complete=bool(c.get("auto_complete", False)),
            allow_test_changes=bool(c.get("allow_test_changes", True)),
            context_chars=int(c.get("context_chars", 14000)),
            edit_context_chars=int(c.get("edit_context_chars", 22000)),
            max_output_tokens=c.get("max_output_tokens"),
        )


@dataclass
class StepContext:
    worker_id: str
    should_stop: Callable[[], bool]  # cancellation requested or lease lost


ModelFactory = Callable[[Task], ModelClient | None]


def policy_for(task: Task, cfg: TaskConfig) -> ChangePolicy:
    return ChangePolicy(
        allowed_paths=list(task.allowed_paths or []),
        forbidden_paths=list(task.forbidden_paths or []),
        allow_test_changes=cfg.allow_test_changes,
    )


class WorkflowEngine:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        sandbox: Sandbox | None = None,
        model_factory: ModelFactory,
        publisher: Publisher | None = None,
    ):
        self.settings = settings or get_settings()
        self.sandbox = sandbox or Sandbox(self.settings)
        self.model_factory = model_factory
        self.publisher = publisher
        self.checks = CheckRunner(self.sandbox, self.settings)

    # ------------------------------------------------------------------------------------------------
    def run_step(self, session: Session, task: Task, ctx: StepContext) -> None:
        handler = {
            S.QUEUED: self._start,
            S.ANALYSING: self._analyse,
            S.PLANNING: self._plan,
            S.IMPLEMENTING: self._implement,
            S.TESTING: self._test,
            S.REPAIRING: self._repair,
            S.VERIFYING: self._verify,
            S.PUBLISHING: self._publish,
        }.get(TaskState(task.state))
        if handler is None:
            return
        handler(session, task, ctx)

    # helpers ------------------------------------------------------------------------------------------
    def _cfg(self, task: Task) -> TaskConfig:
        return TaskConfig.from_task(task, self.settings)

    def _workspace(self, task: Task, label: str = "agent") -> Workspace:
        repo = task.repository
        return Workspace(f"task-{task.id}", git_for(repo), task.base_commit, self.settings, label=label)

    def _model(self, task: Task) -> ModelClient:
        client = self.model_factory(task)
        if client is None:
            raise TransientError("no model endpoint is configured (MODERNISATION_MODEL_PROVIDER=none)")
        return client

    def _env(
        self, session: Session, task: Task, workspace: Workspace, purpose: str
    ) -> tuple[DependencySpec, EnvResult]:
        spec = read_dependency_spec(workspace.repo_dir, self.settings.sandbox_python)
        env = ensure_env(spec, self.sandbox, self.settings)
        add_event(
            session,
            task.id,
            "tool",
            f"python environment {'reused' if env.reused else 'built'} for {purpose}",
            state=task.state,
            payload={"tool": "ensure_env", **env.summary()},
        )
        session.commit()
        return spec, env

    def _record_checks(
        self, session: Session, task: Task, outcomes: list[CheckOutcome], phase: str, attempt_no: int
    ) -> None:
        for o in outcomes:
            session.add(
                CheckRun(
                    task_id=task.id,
                    attempt_no=attempt_no,
                    phase=phase,
                    name=o.name,
                    command=o.result.argv,
                    exit_code=o.result.exit_code,
                    timed_out=o.result.timed_out,
                    duration_ms=o.result.duration_ms,
                    stdout=o.result.stdout[-60000:],
                    stderr=o.result.stderr[-30000:],
                    summary={k: v for k, v in o.summary.items() if k != "passed_ids"},
                )
            )
            add_event(
                session,
                task.id,
                "check",
                f"{phase} {o.name}: {'passed' if o.passed else 'FAILED'} ({o.result.duration_ms} ms)",
                state=task.state,
                payload={
                    "check": o.name,
                    "phase": phase,
                    "attempt": attempt_no,
                    "passed": o.passed,
                    "exit_code": o.result.exit_code,
                    "timed_out": o.result.timed_out,
                },
            )
        session.commit()

    def _attempts_this_run(self, session: Session, task: Task) -> list[PatchAttempt]:
        start = int((task.config or {}).get("attempt_offset", 0))
        return list(
            session.scalars(
                select(PatchAttempt)
                .where(PatchAttempt.task_id == task.id, PatchAttempt.attempt_no > start)
                .order_by(PatchAttempt.attempt_no)
            )
        )

    def _next_attempt_no(self, session: Session, task: Task) -> int:
        current = session.scalar(select(func.max(PatchAttempt.attempt_no)).where(PatchAttempt.task_id == task.id))
        return int(current or 0) + 1

    def _last_applied(self, session: Session, task: Task) -> PatchAttempt | None:
        applied = [a for a in self._attempts_this_run(session, task) if a.apply_status == "applied"]
        return applied[-1] if applied else None

    def _escalate(self, session: Session, task: Task, reason: str, payload: dict[str, Any] | None = None) -> None:
        transition(session, task, S.ESCALATED, reason, payload=payload)

    def _model_call(self, session: Session, task: Task, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except StructuredOutputError as exc:
            add_event(
                session,
                task.id,
                "model",
                "model returned invalid structured output",
                state=task.state,
                payload={"error": str(exc)[:1000], "raw": exc.raw[:2000]},
            )
            session.commit()
            raise
        except ModelError as exc:
            add_event(
                session,
                task.id,
                "error",
                f"model call failed: {exc}",
                state=task.state,
                payload={"retryable": exc.retryable, "status": exc.status},
            )
            session.commit()
            raise TransientError(f"model call failed: {exc}") from exc

    # QUEUED -------------------------------------------------------------------------------------------
    def _start(self, session: Session, task: Task, ctx: StepContext) -> None:
        transition(session, task, S.ANALYSING, "worker picked up task", lease_owner=ctx.worker_id)

    # ANALYSING ----------------------------------------------------------------------------------------
    def _analyse(self, session: Session, task: Task, ctx: StepContext) -> None:
        cfg = self._cfg(task)
        if load_checkpoint(session, task.id, "analysis") is not None:
            transition(session, task, S.PLANNING, "analysis checkpoint found", lease_owner=ctx.worker_id)
            return
        repo: Repository = task.repository
        mirror = git_for(repo)
        stale: dict[str, Any] | None = None
        if task.base_ref:
            try:
                current = mirror.resolve(task.base_ref)
                if current != task.base_commit:
                    stale = {"ref": task.base_ref, "pinned": task.base_commit, "current": current}
                    add_event(
                        session,
                        task.id,
                        "log",
                        f"{task.base_ref} has moved to {current[:12]}; work stays pinned to {task.base_commit[:12]}",
                        state=task.state,
                        payload=stale,
                    )
            except GitError:
                pass
        if not mirror.has_commit(task.base_commit):
            self._escalate(session, task, f"base commit {task.base_commit} is not available in the repository")
            return

        snapshot = index_commit(session, repo, task.base_commit)
        add_event(
            session,
            task.id,
            "tool",
            f"indexed {snapshot.files_total} files at {snapshot.commit_sha[:12]} "
            f"({snapshot.blobs_parsed} parsed, {snapshot.blobs_reused} reused)",
            state=task.state,
            payload={"tool": "index_repository", "snapshot_id": snapshot.id, "duration_ms": snapshot.duration_ms},
        )
        data = load_snapshot(session, snapshot)
        refs = retrieve(data, task.request, category=task.category, limit=30)
        policy = policy_for(task, cfg)
        ref_dicts = []
        for r in refs:
            d = r.to_dict()
            try:
                policy.check_path(r.path)
                d["in_scope"] = True
            except PolicyViolation:
                d["in_scope"] = False
            ref_dicts.append(d)
        impl_paths = list(
            dict.fromkeys(r["path"] for r in ref_dicts if r["in_scope"] and not r["is_test"] and not r["is_config"])
        )[:6]
        impact = impact_analysis(data, impl_paths, [r["symbol"] for r in ref_dicts if r.get("symbol")][:10])
        add_event(
            session,
            task.id,
            "tool",
            f"retrieved {len(ref_dicts)} code references",
            state=task.state,
            payload={
                "tool": "retrieve_context",
                "methods": sorted({m for r in ref_dicts for m in r["methods"]}),
                "top": [f"{r['path']}:{r['start_line']}-{r['end_line']}" for r in ref_dicts[:8]],
            },
        )
        session.commit()

        workspace = self._workspace(task)
        try:
            workspace.create()
        except (WorkspaceError, GitError) as exc:
            self._escalate(session, task, f"could not prepare workspace: {exc}")
            return
        spec, env = self._env(session, task, workspace, "baseline")
        if not env.ok:
            self._escalate(
                session,
                task,
                "dependency environment could not be built at the base commit",
                payload={"env": env.summary()},
            )
            return
        if ctx.should_stop():
            return
        outcomes = self.checks.run(
            workspace, env.path, spec, phase="baseline", cancel_check=ctx.should_stop, label="baseline"
        )
        if any(o.result.cancelled for o in outcomes):
            return
        self._record_checks(session, task, outcomes, "baseline", 0)
        baseline = summarise(outcomes)
        analysis = {
            "snapshot_id": snapshot.id,
            "commit_sha": snapshot.commit_sha,
            "references": ref_dicts,
            "impact": impact,
            "baseline": baseline,
            "env_key": env.key,
            "stale_base": stale,
            "dependency_sources": spec.sources,
        }
        task.analysis = {k: v for k, v in analysis.items() if k != "baseline"} | {
            "baseline_tests": baseline.get("pytest", {}).get("tests"),
            "baseline_failing": len(baseline.get("pytest", {}).get("failing", [])),
        }
        session.commit()
        save_checkpoint(session, task.id, "analysis", analysis)
        transition(session, task, S.PLANNING, "repository analysed", lease_owner=ctx.worker_id)

    # PLANNING -----------------------------------------------------------------------------------------
    def _plan(self, session: Session, task: Task, ctx: StepContext) -> None:
        cfg = self._cfg(task)
        analysis = load_checkpoint(session, task.id, "analysis") or {}
        policy = policy_for(task, cfg)
        plan = load_checkpoint(session, task.id, "plan")
        if plan is None and cfg.strategy == "single_shot":
            plan = {"strategy": "single_shot", "target_files": self._single_shot_targets(analysis)}
        if plan is None:
            workspace = self._workspace(task)
            workspace.create()
            refs = analysis.get("references", [])
            blocks = excerpt_blocks(workspace, refs, cfg.context_chars)
            messages = prompts.planning_messages(
                task.request,
                task.category,
                prompts.scope_text(task.allowed_paths, task.forbidden_paths),
                blocks,
                analysis.get("impact"),
            )
            client = self._model(task)
            try:
                result, _raw = self._model_call(
                    session,
                    task,
                    lambda: complete_structured(
                        client,
                        messages,
                        prompts.Plan,
                        purpose="plan",
                        max_tokens=cfg.max_output_tokens or 1200,
                        sink=getattr(client, "sink", None),
                    ),
                )
            except StructuredOutputError:
                # Fall back to a retrieval-derived plan rather than failing the task outright.
                result = prompts.Plan(
                    summary="Plan derived from retrieval (model plan was invalid).",
                    target_files=self._single_shot_targets(analysis) or ["."],
                    steps=[prompts.PlanStep(description=task.request[:500])],
                )
            plan = result.model_dump()
            kept, dropped = [], []
            for path in plan["target_files"]:
                try:
                    kept.append(policy.check_path(path))
                except PolicyViolation as exc:
                    dropped.append({"path": path, "reason": str(exc)})
            existing = {r["path"] for r in refs}
            plan["target_files"] = kept
            plan["dropped_targets"] = dropped
            plan["unknown_targets"] = [p for p in kept if p not in existing and workspace.read(p) is None]
            if dropped:
                add_event(
                    session,
                    task.id,
                    "log",
                    f"plan proposed {len(dropped)} out-of-scope file(s); removed",
                    state=task.state,
                    payload={"dropped": dropped},
                )
            if not kept:
                kept = self._single_shot_targets(analysis)
                plan["target_files"] = kept
            if plan.get("needs_clarification") and plan.get("clarification_questions"):
                task.plan = plan
                session.commit()
                self._escalate(session, task, "clarification required: " + "; ".join(plan["clarification_questions"]))
                return
            if not kept:
                task.plan = plan
                session.commit()
                self._escalate(session, task, "no in-scope files could be identified for this request")
                return
            save_checkpoint(session, task.id, "plan", plan)
        task.plan = plan
        session.commit()
        if cfg.require_plan_approval and cfg.strategy != "single_shot":
            transition(
                session,
                task,
                S.AWAITING_APPROVAL,
                "plan awaiting human approval",
                lease_owner=ctx.worker_id,
                approval_stage="plan",
            )
        else:
            transition(session, task, S.IMPLEMENTING, "plan ready", lease_owner=ctx.worker_id)

    @staticmethod
    def _single_shot_targets(analysis: dict[str, Any]) -> list[str]:
        paths: list[str] = []
        for ref in analysis.get("references", []):
            if ref.get("in_scope") and not ref.get("is_test") and ref["path"] not in paths:
                paths.append(ref["path"])
            if len(paths) >= 3:
                break
        return paths

    # IMPLEMENTING -------------------------------------------------------------------------------------
    def _implement(self, session: Session, task: Task, ctx: StepContext) -> None:
        cfg = self._cfg(task)
        attempts = self._attempts_this_run(session, task)
        if attempts and attempts[-1].apply_status == "applied" and attempts[-1].checks_passed is None:
            transition(session, task, S.TESTING, "resuming with recorded attempt", lease_owner=ctx.worker_id)
            return
        if len(attempts) >= cfg.max_attempts:
            self._escalate(session, task, f"attempt budget of {cfg.max_attempts} exhausted")
            return
        analysis = load_checkpoint(session, task.id, "analysis") or {}
        plan = task.plan or {}
        policy = policy_for(task, cfg)
        workspace = self._workspace(task)
        workspace.create()
        workspace.reset()
        targets = list(plan.get("target_files") or self._single_shot_targets(analysis))
        if any(is_dependency_manifest(t) for t in targets) is False and task.category == "dependency_upgrade":
            targets += [
                r["path"]
                for r in analysis.get("references", [])
                if r.get("is_config") and is_dependency_manifest(r["path"]) and r.get("in_scope")
            ][:2]
        file_blocks, included = editable_file_blocks(workspace, targets, policy, cfg.edit_context_chars)
        context = (
            excerpt_blocks(
                workspace,
                analysis.get("references", []),
                max(0, cfg.context_chars - sum(len(b) for b in file_blocks) // 2),
                skip_paths=set(included),
            )
            if cfg.strategy != "single_shot"
            else []
        )
        messages = prompts.implementation_messages(
            task.request,
            task.category,
            prompts.scope_text(task.allowed_paths, task.forbidden_paths),
            plan if cfg.strategy != "single_shot" else None,
            file_blocks,
            context,
        )
        client = self._model(task)
        completion = self._model_call(
            session,
            task,
            lambda: client.complete(
                messages, purpose="implement", max_tokens=cfg.max_output_tokens or self.settings.model_max_output_tokens
            ),
        )
        self._apply_and_record(session, task, ctx, workspace, policy, completion.text, kind="initial", base_diff=None)

    def _apply_and_record(
        self,
        session: Session,
        task: Task,
        ctx: StepContext,
        workspace: Workspace,
        policy: ChangePolicy,
        raw: str,
        *,
        kind: str,
        base_diff: str | None,
    ) -> None:
        cfg = self._cfg(task)
        attempt_no = self._next_attempt_no(session, task)
        edits = parse_edits(raw)
        attempt = PatchAttempt(
            task_id=task.id,
            attempt_no=attempt_no,
            kind=kind,
            raw_output=raw[:60000],
            edits=[e.to_dict() for e in edits],
            apply_status="rejected",
        )
        try:
            change = workspace.apply_edits(edits, policy)
            if not change.diff.strip():
                raise EditError("empty_change", "the edits produced no change to the repository")
            attempt.apply_status = "applied"
            attempt.diff = change.diff
            attempt.files_changed = change.files_changed
        except (EditError, PolicyViolation) as exc:
            code = getattr(exc, "code", "rejected")
            attempt.rejection_reason = f"{code}: {exc}"
            save_checkpoint(
                session,
                task.id,
                "last_failure",
                {
                    "kind": "policy_violation" if isinstance(exc, PolicyViolation) else "edit_rejected",
                    "code": code,
                    "report": f"Your edits were rejected: {exc}\n"
                    "Valid paths are the ones in the <file path=...> tags; authorised scope: "
                    f"{policy.allowed_paths or 'whole repository'}.",
                    "attempt_no": attempt_no,
                    "base_diff": base_diff,
                },
            )
        session.add(attempt)
        task.attempt_count = task.attempt_count + 1
        session.commit()
        add_event(
            session,
            task.id,
            "tool",
            f"attempt {attempt_no} ({kind}): {attempt.apply_status}"
            + (
                f" - {attempt.rejection_reason}"
                if attempt.rejection_reason
                else f" - {len(attempt.files_changed)} file(s) changed"
            ),
            state=task.state,
            payload={
                "tool": "apply_edits",
                "attempt": attempt_no,
                "edits": len(edits),
                "files": attempt.files_changed,
                "status": attempt.apply_status,
            },
        )
        session.commit()
        exhausted = len(self._attempts_this_run(session, task)) >= cfg.max_attempts
        if attempt.apply_status == "applied":
            transition(session, task, S.TESTING, f"attempt {attempt_no} applied", lease_owner=ctx.worker_id)
        elif cfg.strategy == "single_shot" or exhausted:
            self._escalate(session, task, f"no applicable change produced ({attempt.rejection_reason})")
        elif TaskState(task.state) != S.REPAIRING:
            transition(session, task, S.REPAIRING, "edits rejected; repairing", lease_owner=ctx.worker_id)
        # in REPAIRING the handler simply runs again for the next attempt

    # TESTING ------------------------------------------------------------------------------------------
    def _test(self, session: Session, task: Task, ctx: StepContext) -> None:
        cfg = self._cfg(task)
        attempt = self._last_applied(session, task)
        if attempt is None or attempt.diff is None:
            transition(session, task, S.REPAIRING, "no applied attempt to test", lease_owner=ctx.worker_id)
            return
        policy = policy_for(task, cfg)
        workspace = self._workspace(task)
        workspace.create()
        workspace.reset()
        workspace.apply_diff(attempt.diff, policy)
        spec, env = self._env(session, task, workspace, f"attempt {attempt.attempt_no}")
        analysis = load_checkpoint(session, task.id, "analysis") or {}
        if not env.ok:
            attempt.checks_passed = False
            session.commit()
            self._after_failed_checks(
                session,
                task,
                ctx,
                attempt,
                {
                    "kind": "dependency_resolution",
                    "report": f"Installing the changed dependencies failed:\n{(env.error or '')[-1500:]}",
                },
            )
            return
        outcomes = self.checks.run(
            workspace,
            env.path,
            spec,
            phase="attempt",
            changed_files=attempt.files_changed,
            cancel_check=ctx.should_stop,
            label=f"attempt-{attempt.attempt_no}",
        )
        if any(o.result.cancelled for o in outcomes):
            return
        self._record_checks(session, task, outcomes, "attempt", attempt.attempt_no)
        current = summarise(outcomes)
        verdict = compare_to_baseline(analysis.get("baseline", {}), current)
        attempt.checks_passed = verdict["acceptable"]
        session.commit()
        add_event(
            session,
            task.id,
            "check",
            "checks " + ("acceptable" if verdict["acceptable"] else "failed: " + "; ".join(verdict["reasons"])),
            state=task.state,
            payload={"verdict": verdict, "attempt": attempt.attempt_no},
        )
        session.commit()
        if verdict["acceptable"]:
            transition(
                session, task, S.VERIFYING, f"attempt {attempt.attempt_no} passed checks", lease_owner=ctx.worker_id
            )
            return
        self._after_failed_checks(
            session,
            task,
            ctx,
            attempt,
            {"kind": "check_failure", "report": self._failure_report(outcomes, verdict, workspace)},
        )

    def _after_failed_checks(
        self, session: Session, task: Task, ctx: StepContext, attempt: PatchAttempt, failure: dict[str, Any]
    ) -> None:
        cfg = self._cfg(task)
        failure["attempt_no"] = attempt.attempt_no
        save_checkpoint(session, task.id, "last_failure", failure)
        if cfg.strategy == "single_shot":
            # Baseline strategy: no feedback loop; the unverified patch is kept for evaluation.
            task.final_diff = attempt.diff
            task.result = {"verified": False, "strategy": "single_shot", "reason": failure["kind"]}
            session.commit()
            self._escalate(session, task, "single-shot patch did not pass checks (no repair in this strategy)")
            return
        if len(self._attempts_this_run(session, task)) >= cfg.max_attempts:
            self._escalate(
                session,
                task,
                f"checks still failing after {cfg.max_attempts} attempt(s)",
                payload={"failure": failure["kind"]},
            )
            return
        transition(session, task, S.REPAIRING, f"checks failed ({failure['kind']})", lease_owner=ctx.worker_id)

    @staticmethod
    def _failure_report(outcomes: list[CheckOutcome], verdict: dict[str, Any], workspace: Workspace) -> str:
        lines = ["Problems: " + "; ".join(verdict["reasons"])]
        for o in outcomes:
            if o.name == "syntax" and not o.passed:
                lines.append("Syntax errors:\n" + o.result.stdout[-1500:])
            if o.name == "pytest":
                new = set(verdict.get("new_failures", []))
                for f in o.summary.get("failing", []):
                    if f["id"] in new:
                        lines.append(f"FAILED {f['id']}: {f['message']}\n{f['detail'][-1200:]}")
                if o.summary.get("collection_error") or not o.summary.get("junit"):
                    lines.append("pytest output:\n" + (o.result.stdout[-2000:] + o.result.stderr[-1000:]))
                if o.result.timed_out:
                    lines.append("The test run exceeded its time limit (possible infinite loop or hang).")
            if o.name in ("ruff", "mypy") and o.summary.get("count"):
                lines.append(
                    f"{o.name}:\n" + "\n".join((o.summary.get("diagnostics") or o.summary.get("errors") or [])[:20])
                )
        return "\n\n".join(lines)[:7000]

    # REPAIRING ----------------------------------------------------------------------------------------
    def _repair(self, session: Session, task: Task, ctx: StepContext) -> None:
        cfg = self._cfg(task)
        attempts = self._attempts_this_run(session, task)
        if attempts and attempts[-1].apply_status == "applied" and attempts[-1].checks_passed is None:
            transition(session, task, S.TESTING, "resuming with recorded attempt", lease_owner=ctx.worker_id)
            return
        if len(attempts) >= cfg.max_attempts:
            self._escalate(session, task, f"attempt budget of {cfg.max_attempts} exhausted")
            return
        failure = load_checkpoint(session, task.id, "last_failure") or {"kind": "unknown", "report": "unknown failure"}
        recent = [a.rejection_reason or "" for a in attempts[-2:]]
        if len(recent) == 2 and all(
            r.startswith(
                ("forbidden_path", "path_traversal", "absolute_path", "test_removed", "test_weakened", "test_deleted")
            )
            for r in recent
        ):
            self._escalate(session, task, "repeated policy violations; the change appears to need out-of-scope edits")
            return
        policy = policy_for(task, cfg)
        workspace = self._workspace(task)
        workspace.create()
        workspace.reset()
        base = self._last_applied(session, task)
        if base is not None and base.diff:
            workspace.apply_diff(base.diff, policy)
        plan = task.plan or {}
        analysis = load_checkpoint(session, task.id, "analysis") or {}
        targets = list(
            dict.fromkeys([*(plan.get("target_files") or []), *((base.files_changed if base else []) or [])])
        )
        failing_tests = self._failing_test_paths(failure.get("report", ""))
        targets += [t for t in failing_tests if t not in targets]
        if not targets:
            targets = self._single_shot_targets(analysis)
        blocks, _ = editable_file_blocks(workspace, targets, policy, cfg.edit_context_chars)
        messages = prompts.repair_messages(
            task.request,
            task.category,
            prompts.scope_text(task.allowed_paths, task.forbidden_paths),
            plan,
            blocks,
            failure.get("report", ""),
            base.diff if base else None,
        )
        client = self._model(task)
        completion = self._model_call(
            session,
            task,
            lambda: client.complete(
                messages, purpose="repair", max_tokens=cfg.max_output_tokens or self.settings.model_max_output_tokens
            ),
        )
        self._apply_and_record(
            session, task, ctx, workspace, policy, completion.text, kind="repair", base_diff=base.diff if base else None
        )

    @staticmethod
    def _failing_test_paths(report: str) -> list[str]:
        paths = []
        for line in report.splitlines():
            if line.startswith("FAILED "):
                ident = line[len("FAILED ") :].split("::")[0]
                # junit classname is dotted (tests.test_mod.TestX) -> map to a path guess
                parts = ident.split(".")
                for cut in range(len(parts), 0, -1):
                    candidate = "/".join(parts[:cut]) + ".py"
                    if candidate not in paths:
                        paths.append(candidate)
                        break
        return paths[:3]

    # VERIFYING ----------------------------------------------------------------------------------------
    def _verify(self, session: Session, task: Task, ctx: StepContext) -> None:
        """Re-check the candidate in a fresh, independent workspace and audit the final diff."""
        cfg = self._cfg(task)
        attempt = self._last_applied(session, task)
        if attempt is None or not attempt.checks_passed or not attempt.diff:
            transition(session, task, S.REPAIRING, "no passing attempt to verify", lease_owner=ctx.worker_id)
            return
        policy = policy_for(task, cfg)
        audit: list[str] = []
        verify_ws = self._workspace(task, label="verify")
        verify_ws.destroy()
        verify_ws.create()
        for path in Workspace.paths_in_diff(attempt.diff):
            try:
                policy.check_path(path)
            except PolicyViolation as exc:
                audit.append(f"{exc.code}: {exc}")
        if audit:  # never apply a diff that touches disallowed paths, even in the verification workspace
            self._escalate(session, task, "final diff violates change policy", payload={"audit": audit})
            return
        originals = {p: verify_ws.read(p) for p in Workspace.paths_in_diff(attempt.diff)}
        verify_ws.apply_diff(attempt.diff, policy)
        for path, old in originals.items():
            try:
                policy.check_content(path, old, verify_ws.read(path))
            except PolicyViolation as exc:
                audit.append(f"{exc.code}: {exc}")
        if audit:
            self._escalate(session, task, "final diff violates change policy", payload={"audit": audit})
            return
        spec, env = self._env(session, task, verify_ws, "verification")
        if not env.ok:
            self._escalate(session, task, "verification environment could not be built")
            return
        outcomes = self.checks.run(
            verify_ws,
            env.path,
            spec,
            phase="verification",
            changed_files=attempt.files_changed,
            cancel_check=ctx.should_stop,
            label="verification",
        )
        if any(o.result.cancelled for o in outcomes):
            return
        self._record_checks(session, task, outcomes, "verification", attempt.attempt_no)
        analysis = load_checkpoint(session, task.id, "analysis") or {}
        verdict = compare_to_baseline(analysis.get("baseline", {}), summarise(outcomes))
        plan_targets = set((task.plan or {}).get("target_files") or [])
        unplanned = [p for p in attempt.files_changed if plan_targets and p not in plan_targets]
        if self.settings.workspace_retention == "delete":
            verify_ws.destroy()
        if not verdict["acceptable"]:
            # Testing passed in the agent workspace but not in a clean one: possible flakiness or
            # dependence on workspace state. Surface it instead of retrying until it passes.
            add_event(
                session,
                task.id,
                "error",
                "independent verification disagreed with agent-workspace checks",
                state=task.state,
                payload={"verdict": verdict, "attempt": attempt.attempt_no},
            )
            attempt.checks_passed = False
            session.commit()
            self._after_failed_checks(
                session,
                task,
                ctx,
                attempt,
                {
                    "kind": "verification_failure",
                    "report": "Independent verification failed: " + "; ".join(verdict["reasons"]),
                },
            )
            return
        task.final_diff = attempt.diff
        task.result = {
            "verified": True,
            "attempt_no": attempt.attempt_no,
            "files_changed": attempt.files_changed,
            "fixed_tests": verdict["fixed"],
            "still_failing_from_baseline": verdict["still_failing"],
            "unplanned_files": unplanned,
            "verification": {o.name: o.passed for o in outcomes},
        }
        session.commit()
        if cfg.auto_complete:
            transition(session, task, S.COMPLETED, "verified (auto-complete)", lease_owner=ctx.worker_id)
        else:
            transition(
                session,
                task,
                S.AWAITING_APPROVAL,
                "verified; awaiting review",
                lease_owner=ctx.worker_id,
                approval_stage="publish",
            )

    # PUBLISHING ---------------------------------------------------------------------------------------
    def _publish(self, session: Session, task: Task, ctx: StepContext) -> None:
        approval = session.scalar(
            select(Approval)
            .where(Approval.task_id == task.id, Approval.stage == "publish")
            .order_by(Approval.id.desc())
            .limit(1)
        )
        if approval is None or approval.decision != "approved":
            self._escalate(session, task, "publishing requires a recorded human approval")
            return
        if not task.final_diff:
            self._escalate(session, task, "no verified diff to publish")
            return
        if self.publisher is None:
            raise TransientError("no publisher configured")
        from modernisation.integrations.github.publisher import PublishError

        try:
            result = self.publisher.publish(session, task)
        except PublishError as exc:
            if exc.retryable:
                raise TransientError(f"publication failed: {exc}") from exc
            session.rollback()
            self._escalate(session, task, f"publication failed: {exc}")
            return
        task.result = {**(task.result or {}), "publication": result}
        session.commit()
        transition(session, task, S.COMPLETED, "published for review", lease_owner=ctx.worker_id)
