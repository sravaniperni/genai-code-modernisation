"""Aggregate evaluation metrics, computed only from recorded per-task results.

Every task in a run stays in the denominator, including errors and timeouts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from modernisation.db.models import EvaluationResult, EvaluationRun, ModelCall


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


def aggregate(results: list[EvaluationResult], run_costs: dict[str, Any] | None = None) -> dict[str, Any]:
    total = len(results)
    outcomes = Counter(r.outcome for r in results)
    successes = outcomes.get("success", 0)
    by_cat: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0})
    for r in results:
        by_cat[r.category]["total"] += 1
        by_cat[r.category]["success"] += int(r.outcome == "success")
    durations = [r.duration_ms / 1000 for r in results]
    costs_known = all(r.cost_usd is not None for r in results) and total > 0
    total_cost = sum(r.cost_usd or 0.0 for r in results) if costs_known else None
    return {
        "evaluated": total,
        "successful": successes,
        "failed": outcomes.get("failure", 0),
        "timeouts": outcomes.get("timeout", 0),
        "errors": outcomes.get("error", 0),
        "completion_rate": round(successes / total, 4) if total else None,
        "by_category": {
            cat: {**v, "rate": round(v["success"] / v["total"], 4) if v["total"] else None}
            for cat, v in sorted(by_cat.items())
        },
        "failure_categories": dict(
            Counter(r.failure_category for r in results if r.outcome != "success" and r.failure_category).most_common()
        ),
        "latency_s": {
            "p50": _percentile(durations, 0.5),
            "p90": _percentile(durations, 0.9),
            "max": max(durations) if durations else None,
            "mean": round(sum(durations) / total, 1) if total else None,
        },
        "model_calls": sum(r.model_calls for r in results),
        "prompt_tokens": sum(r.prompt_tokens for r in results),
        "completion_tokens": sum(r.completion_tokens for r in results),
        "inference_cost_usd": total_cost,
        "cost_per_accepted_patch_usd": (
            round(total_cost / successes, 6) if total_cost is not None and successes else None
        ),
        **(run_costs or {}),
    }


def run_summary(session: Session, run: EvaluationRun) -> dict[str, Any]:
    results = list(
        session.scalars(
            select(EvaluationResult)
            .where(EvaluationResult.run_id == run.id)
            .order_by(EvaluationResult.benchmark_task_id)
        )
    )
    calls = list(session.scalars(select(ModelCall).where(ModelCall.evaluation_run_id == run.id)))
    model_seconds = sum(c.latency_ms for c in calls) / 1000
    return {
        "run": {
            "id": run.id,
            "run_key": run.run_key,
            "mode": run.mode,
            "taskset_version": run.taskset_version,
            "split": run.split,
            "model_provider": run.model_provider,
            "model_name": run.model_name,
            "config": run.config,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        },
        "metrics": aggregate(
            results,
            {
                "model_inference_seconds": round(model_seconds, 1),
                "failed_model_requests": sum(1 for c in calls if c.status != "ok"),
            },
        ),
        "results": [
            {
                "benchmark_task_id": r.benchmark_task_id,
                "repo": r.repo,
                "category": r.category,
                "outcome": r.outcome,
                "failure_category": r.failure_category,
                "attempts": r.attempts,
                "duration_ms": r.duration_ms,
                "model_calls": r.model_calls,
                "task_id": r.task_id,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
            }
            for r in results
        ],
    }
