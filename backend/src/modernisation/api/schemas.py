from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from modernisation.agents.states import TaskCategory


class RepositoryCreate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    kind: Literal["local", "github"]
    source: str = Field(min_length=1, max_length=1000, description="filesystem path or owner/repo")


class IndexRequest(BaseModel):
    ref: str | None = Field(default=None, max_length=200)


class RetrieveRequest(BaseModel):
    request: str = Field(min_length=3, max_length=8000)
    category: TaskCategory | None = None
    ref: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ImpactRequest(BaseModel):
    paths: list[str] = Field(default_factory=list, max_length=100)
    symbols: list[str] = Field(default_factory=list, max_length=100)
    ref: str | None = None


class TaskConfigIn(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=6)
    require_plan_approval: bool = False
    allow_test_changes: bool = True
    strategy: Literal["agentic", "single_shot"] = "agentic"


class TaskCreate(BaseModel):
    repository_id: int
    title: str = Field(min_length=3, max_length=300)
    request: str = Field(min_length=10, max_length=20000)
    category: TaskCategory
    base_ref: str | None = Field(default=None, max_length=200)
    allowed_paths: list[str] = Field(default_factory=list, max_length=50)
    forbidden_paths: list[str] = Field(default_factory=list, max_length=50)
    config: TaskConfigIn = Field(default_factory=TaskConfigIn)

    @field_validator("allowed_paths", "forbidden_paths")
    @classmethod
    def _no_traversal(cls, value: list[str]) -> list[str]:
        for item in value:
            if ".." in item.split("/") or item.startswith("/"):
                raise ValueError(f"scope patterns must be repository-relative without '..': {item!r}")
        return value


class ApprovalIn(BaseModel):
    stage: Literal["plan", "publish"]
    decision: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=1, max_length=200)
    comment: str | None = Field(default=None, max_length=4000)
    expected_version: int


class TaskSummary(BaseModel):
    id: int
    repository_id: int
    repository: str
    title: str
    category: str
    state: str
    state_reason: str | None
    approval_stage: str | None
    attempt_count: int
    created_at: Any
    updated_at: Any
    finished_at: Any | None
    origin: str
    pr_url: str | None
