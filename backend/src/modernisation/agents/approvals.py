"""Human approval gates.

Approvals are bound to the task version the reviewer saw: if the task changed after the page was loaded
(new attempt, different diff) the approval is refused, so a reviewer can never approve something they
did not review.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from modernisation.agents.states import IllegalTransition, TaskState
from modernisation.agents.store import add_event, transition
from modernisation.db.models import Approval, Task


class ApprovalError(IllegalTransition):
    pass


def decide(
    session: Session,
    task: Task,
    *,
    stage: str,
    decision: str,
    reviewer: str,
    expected_version: int,
    comment: str | None = None,
) -> Task:
    if decision not in {"approved", "rejected"}:
        raise ApprovalError("decision must be 'approved' or 'rejected'")
    if not reviewer.strip():
        raise ApprovalError("reviewer identity is required")
    if task.state != TaskState.AWAITING_APPROVAL.value or task.approval_stage != stage:
        raise ApprovalError(
            f"task {task.id} is not awaiting {stage} approval (state={task.state}, stage={task.approval_stage})"
        )
    if task.version != expected_version:
        raise ApprovalError(
            f"task {task.id} changed since it was reviewed (version {task.version} != "
            f"{expected_version}); reload and review again"
        )
    session.add(
        Approval(
            task_id=task.id,
            stage=stage,
            decision=decision,
            reviewer=reviewer[:200],
            comment=comment,
            task_version=task.version,
        )
    )
    add_event(
        session,
        task.id,
        "approval",
        f"{stage} {decision} by {reviewer}",
        state=task.state,
        payload={"stage": stage, "decision": decision, "comment": comment},
    )
    session.commit()
    if stage == "plan":
        target = TaskState.IMPLEMENTING if decision == "approved" else TaskState.CANCELLED
        return transition(session, task, target, f"plan {decision} by {reviewer}")
    if decision == "approved":
        return transition(session, task, TaskState.PUBLISHING, f"publication approved by {reviewer}")
    return transition(session, task, TaskState.COMPLETED, f"verified change kept unpublished ({reviewer})")
