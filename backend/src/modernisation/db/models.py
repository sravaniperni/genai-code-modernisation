"""Relational schema.

PostgreSQL is the single source of truth for repositories, the commit-aware code index, task state,
the append-only task event log, model-call accounting, external side effects (for idempotency) and
evaluation results. Workspaces on disk are a cache that can always be rebuilt from these rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JsonType, list[Any]: JsonType}


def _now() -> Any:
    return func.now()


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    source_kind: Mapped[str] = mapped_column(String(20))  # local | github
    source: Mapped[str] = mapped_column(Text)  # filesystem path or owner/repo
    clone_url: Mapped[str] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    github_full_name: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())

    snapshots: Mapped[list[IndexSnapshot]] = relationship(back_populates="repository")


class IndexSnapshot(Base):
    """One indexing run of a repository at an exact commit."""

    __tablename__ = "index_snapshots"
    __table_args__ = (UniqueConstraint("repository_id", "commit_sha"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    commit_sha: Mapped[str] = mapped_column(String(64))
    ref: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|ready|failed
    error: Mapped[str | None] = mapped_column(Text)
    files_total: Mapped[int] = mapped_column(Integer, default=0)
    blobs_parsed: Mapped[int] = mapped_column(Integer, default=0)
    blobs_reused: Mapped[int] = mapped_column(Integer, default=0)
    symbols_total: Mapped[int] = mapped_column(Integer, default=0)
    languages: Mapped[dict[str, Any]] = mapped_column(default=dict)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repository: Mapped[Repository] = relationship(back_populates="snapshots")


class Blob(Base):
    """Content-addressed parse cache keyed by git blob SHA (enables incremental indexing)."""

    __tablename__ = "blobs"

    sha: Mapped[str] = mapped_column(String(64), primary_key=True)
    language: Mapped[str | None] = mapped_column(String(40))
    size: Mapped[int] = mapped_column(Integer)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    is_binary: Mapped[bool] = mapped_column(Boolean, default=False)
    content: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(20), default="skipped")  # parsed|skipped|error
    parse_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class BlobSymbol(Base):
    __tablename__ = "blob_symbols"
    __table_args__ = (Index("ix_blob_symbols_blob", "blob_sha"), Index("ix_blob_symbols_name", "name"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    blob_sha: Mapped[str] = mapped_column(ForeignKey("blobs.sha", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300))
    qualified_name: Mapped[str] = mapped_column(String(600))
    kind: Mapped[str] = mapped_column(String(20))  # function|class|method|variable
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str | None] = mapped_column(Text)
    docstring: Mapped[str | None] = mapped_column(Text)
    parent: Mapped[str | None] = mapped_column(String(600))


class BlobImport(Base):
    __tablename__ = "blob_imports"
    __table_args__ = (Index("ix_blob_imports_blob", "blob_sha"), Index("ix_blob_imports_module", "module"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    blob_sha: Mapped[str] = mapped_column(ForeignKey("blobs.sha", ondelete="CASCADE"))
    module: Mapped[str] = mapped_column(String(400))  # absolute or dotted-relative module text
    name: Mapped[str | None] = mapped_column(String(300))  # imported name for "from x import name"
    alias: Mapped[str | None] = mapped_column(String(300))
    level: Mapped[int] = mapped_column(Integer, default=0)  # leading dots of a relative import
    line: Mapped[int] = mapped_column(Integer)


class BlobReference(Base):
    __tablename__ = "blob_references"
    __table_args__ = (Index("ix_blob_refs_blob", "blob_sha"), Index("ix_blob_refs_name", "name"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    blob_sha: Mapped[str] = mapped_column(ForeignKey("blobs.sha", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300))
    qualifier: Mapped[str | None] = mapped_column(String(300))  # receiver text, e.g. "yaml" in yaml.load()
    kind: Mapped[str] = mapped_column(String(20))  # call|attribute
    line: Mapped[int] = mapped_column(Integer)
    column: Mapped[int] = mapped_column(Integer)


class SnapshotFile(Base):
    __tablename__ = "snapshot_files"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "path"),
        Index("ix_snapshot_files_blob", "blob_sha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("index_snapshots.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    blob_sha: Mapped[str] = mapped_column(ForeignKey("blobs.sha"))
    language: Mapped[str | None] = mapped_column(String(40))
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    is_config: Mapped[bool] = mapped_column(Boolean, default=False)
    size: Mapped[int] = mapped_column(Integer, default=0)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_state_lease", "state", "lease_expires_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    title: Mapped[str] = mapped_column(String(300))
    request: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))
    base_ref: Mapped[str | None] = mapped_column(String(300))
    base_commit: Mapped[str] = mapped_column(String(64))
    allowed_paths: Mapped[list[Any]] = mapped_column(default=list)
    forbidden_paths: Mapped[list[Any]] = mapped_column(default=list)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    origin: Mapped[str] = mapped_column(String(20), default="api")  # api|evaluation|webhook
    evaluation_run_id: Mapped[int | None] = mapped_column(ForeignKey("evaluation_runs.id"))

    state: Mapped[str] = mapped_column(String(30), default="QUEUED")
    state_reason: Mapped[str | None] = mapped_column(Text)
    approval_stage: Mapped[str | None] = mapped_column(String(20))  # plan|publish while AWAITING_APPROVAL
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=0)

    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resume_count: Mapped[int] = mapped_column(Integer, default=0)

    analysis: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    result: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    final_diff: Mapped[str | None] = mapped_column(Text)

    publish_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    branch_name: Mapped[str | None] = mapped_column(String(300))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now(), onupdate=_now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repository: Mapped[Repository] = relationship()


class TaskEvent(Base):
    """Append-only execution log rendered by the execution monitor."""

    __tablename__ = "task_events"
    __table_args__ = (Index("ix_task_events_task", "task_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    kind: Mapped[str] = mapped_column(String(40))  # state|tool|model|check|log|error|approval|external
    state: Mapped[str | None] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)


class TaskCheckpoint(Base):
    """Durable output of a completed workflow step, used to resume without repeating work."""

    __tablename__ = "task_checkpoints"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    step: Mapped[str] = mapped_column(String(60), primary_key=True)
    output: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class PatchAttempt(Base):
    __tablename__ = "patch_attempts"
    __table_args__ = (UniqueConstraint("task_id", "attempt_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # initial|repair
    raw_output: Mapped[str | None] = mapped_column(Text)
    edits: Mapped[list[Any]] = mapped_column(default=list)
    apply_status: Mapped[str] = mapped_column(String(20))  # applied|rejected|empty
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    diff: Mapped[str | None] = mapped_column(Text)
    files_changed: Mapped[list[Any]] = mapped_column(default=list)
    checks_passed: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class CheckRun(Base):
    __tablename__ = "check_runs"
    __table_args__ = (Index("ix_check_runs_task", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    phase: Mapped[str] = mapped_column(String(20))  # baseline|attempt|verification|acceptance
    name: Mapped[str] = mapped_column(String(60))
    command: Mapped[list[Any]] = mapped_column(default=list)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (Index("ix_model_calls_task", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    evaluation_run_id: Mapped[int | None] = mapped_column(ForeignKey("evaluation_runs.id"))
    purpose: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))  # ok|error|invalid_output
    error: Mapped[str | None] = mapped_column(Text)
    retry_index: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(20))  # plan|publish
    decision: Mapped[str] = mapped_column(String(20))  # approved|rejected
    reviewer: Mapped[str] = mapped_column(String(200))
    comment: Mapped[str | None] = mapped_column(Text)
    task_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class ExternalAction(Base):
    """Ledger of side effects on external systems; the idempotency key makes retries safe."""

    __tablename__ = "external_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))  # create_branch|push_branch|create_pull_request
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|succeeded|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    request: Mapped[dict[str, Any]] = mapped_column(default=dict)
    response: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    external_ref: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now(), onupdate=_now())


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(100), unique=True)
    event: Mapped[str] = mapped_column(String(60))
    action: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))  # processed|ignored|error
    detail: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(100), unique=True)
    mode: Mapped[str] = mapped_column(String(20))  # platform|baseline
    taskset_version: Mapped[str] = mapped_column(String(100))
    split: Mapped[str] = mapped_column(String(20))
    model_provider: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (UniqueConstraint("run_id", "benchmark_task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"))
    benchmark_task_id: Mapped[str] = mapped_column(String(100))
    repo: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(20))  # success|failure|timeout|error
    failure_category: Mapped[str | None] = mapped_column(String(60))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
