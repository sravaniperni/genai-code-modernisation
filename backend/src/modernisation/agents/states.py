"""Maintenance-task lifecycle.

The transition table is the single authority on which moves are legal. Every state change goes through
:func:`modernisation.agents.store.transition`, which enforces it with an optimistic version check, so two
workers (or a worker and an API request) can never both move the same task.
"""

from __future__ import annotations

from enum import StrEnum


class TaskState(StrEnum):
    QUEUED = "QUEUED"
    ANALYSING = "ANALYSING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    REPAIRING = "REPAIRING"
    VERIFYING = "VERIFYING"
    PUBLISHING = "PUBLISHING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"


class TaskCategory(StrEnum):
    DEPENDENCY_UPGRADE = "dependency_upgrade"
    DEPRECATED_API_MIGRATION = "deprecated_api_migration"
    BUG_FIX = "bug_fix"
    TYPE_COMPATIBILITY = "type_compatibility"
    RESTRICTED_REFACTOR = "restricted_refactor"
    TEST_REPAIR = "test_repair"


S = TaskState

TERMINAL: frozenset[TaskState] = frozenset({S.COMPLETED, S.FAILED, S.CANCELLED, S.ESCALATED})
# States a worker may pick up and drive forward.
RUNNABLE: frozenset[TaskState] = frozenset(
    {S.QUEUED, S.ANALYSING, S.PLANNING, S.IMPLEMENTING, S.TESTING, S.REPAIRING, S.VERIFYING, S.PUBLISHING}
)

TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    S.QUEUED: frozenset({S.ANALYSING}),
    S.ANALYSING: frozenset({S.PLANNING, S.ESCALATED}),
    S.PLANNING: frozenset({S.AWAITING_APPROVAL, S.IMPLEMENTING, S.ESCALATED}),
    # plan stage -> IMPLEMENTING / CANCELLED; publish stage -> PUBLISHING / COMPLETED (declined publish)
    S.AWAITING_APPROVAL: frozenset({S.IMPLEMENTING, S.PUBLISHING, S.COMPLETED, S.CANCELLED}),
    S.IMPLEMENTING: frozenset({S.TESTING, S.REPAIRING, S.ESCALATED}),
    S.TESTING: frozenset({S.VERIFYING, S.REPAIRING, S.ESCALATED}),
    S.REPAIRING: frozenset({S.TESTING, S.ESCALATED}),
    S.VERIFYING: frozenset({S.AWAITING_APPROVAL, S.COMPLETED, S.REPAIRING, S.ESCALATED}),
    S.PUBLISHING: frozenset({S.COMPLETED, S.ESCALATED}),
    S.COMPLETED: frozenset(),
    S.FAILED: frozenset({S.QUEUED}),  # explicit restart
    S.CANCELLED: frozenset({S.QUEUED}),  # explicit restart
    S.ESCALATED: frozenset({S.QUEUED}),  # explicit restart after human input
}

# Any non-terminal task may be cancelled or fail on an unrecoverable infrastructure error.
for _state in TaskState:
    if _state not in TERMINAL:
        TRANSITIONS[_state] = TRANSITIONS[_state] | {S.CANCELLED, S.FAILED}


class IllegalTransition(RuntimeError):
    pass


def check_transition(current: TaskState | str, target: TaskState | str) -> None:
    cur, tgt = TaskState(current), TaskState(target)
    if tgt not in TRANSITIONS[cur]:
        raise IllegalTransition(f"illegal transition {cur} -> {tgt}")
