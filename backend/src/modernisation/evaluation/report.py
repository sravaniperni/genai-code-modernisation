"""Generate machine- and human-readable evaluation reports from stored results.

Nothing here is hand-entered: every figure is computed from ``evaluation_results`` rows (one per task per
run). Comparisons between a platform run and a baseline run are paired: only tasks present in both runs are
compared, and the task count is printed next to every rate.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from modernisation.db.models import EvaluationResult, EvaluationRun, ModelCall
from modernisation.db.session import session_scope
from modernisation.evaluation.metrics import aggregate
from modernisation.evaluation.taskset import load_tasks


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def collect(run_keys: list[str], eval_dir: Path) -> dict[str, Any]:
    split_of = {t.id: t.split for t in load_tasks(eval_dir)}
    runs: dict[str, Any] = {}
    with session_scope() as session:
        for key in run_keys:
            run = session.scalar(select(EvaluationRun).where(EvaluationRun.run_key == key))
            if run is None:
                raise SystemExit(f"run {key!r} not found")
            results = list(session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)))
            calls = list(session.scalars(select(ModelCall).where(ModelCall.evaluation_run_id == run.id)))
            by_split: dict[str, list[EvaluationResult]] = defaultdict(list)
            for r in results:
                by_split[split_of.get(r.benchmark_task_id, "unknown")].append(r)
            session.expunge_all()
            runs[key] = {
                "run": {
                    "run_key": run.run_key,
                    "mode": run.mode,
                    "taskset_version": run.taskset_version,
                    "split": run.split,
                    "model_provider": run.model_provider,
                    "model_name": run.model_name,
                    "config": run.config,
                    "status": run.status,
                    "started_at": str(run.started_at),
                    "finished_at": str(run.finished_at),
                },
                "results": results,
                "metrics": {"all": aggregate(results), **{s: aggregate(rs) for s, rs in sorted(by_split.items())}},
                "model_requests": len(calls),
                "failed_model_requests": sum(1 for c in calls if c.status != "ok"),
                "model_inference_seconds": round(sum(c.latency_ms for c in calls) / 1000, 1),
            }
    return runs


def paired(platform: list[EvaluationResult], baseline: list[EvaluationResult]) -> dict[str, Any]:
    p = {r.benchmark_task_id: r for r in platform}
    b = {r.benchmark_task_id: r for r in baseline}
    common = sorted(set(p) & set(b))
    ps = sum(p[t].outcome == "success" for t in common)
    bs = sum(b[t].outcome == "success" for t in common)
    only_p = sum(p[t].outcome == "success" and b[t].outcome != "success" for t in common)
    only_b = sum(b[t].outcome == "success" and p[t].outcome != "success" for t in common)
    n = len(common)
    return {
        "tasks_compared": n,
        "platform_successes": ps,
        "baseline_successes": bs,
        "platform_rate": round(ps / n, 4) if n else None,
        "baseline_rate": round(bs / n, 4) if n else None,
        "improvement_points": round((ps - bs) / n * 100, 1) if n else None,
        "platform_only_successes": only_p,
        "baseline_only_successes": only_b,
        "platform_rate_95ci": _wilson(ps, n),
        "baseline_rate_95ci": _wilson(bs, n),
    }


def write_reports(run_keys: list[str], out_dir: Path, eval_dir: Path) -> dict[str, Any]:
    runs = collect(run_keys, eval_dir)
    platform_keys = [k for k, v in runs.items() if v["run"]["mode"] == "platform"]
    baseline_keys = [k for k, v in runs.items() if v["run"]["mode"] == "baseline"]
    comparisons = {}
    split_of = {t.id: t.split for t in load_tasks(eval_dir)}
    for pk in platform_keys:
        for bk in baseline_keys:
            pr, br = runs[pk]["results"], runs[bk]["results"]
            comparisons[f"{pk} vs {bk}"] = {
                "all": paired(pr, br),
                **{
                    s: paired(
                        [r for r in pr if split_of.get(r.benchmark_task_id) == s],
                        [r for r in br if split_of.get(r.benchmark_task_id) == s],
                    )
                    for s in ("dev", "heldout")
                },
            }
    generated = datetime.now(UTC).isoformat()
    metrics = {
        "generated_at": generated,
        "source": "evaluation_results table; per-task evidence in reports/runs/<run_key>.jsonl",
        "runs": {k: {kk: vv for kk, vv in v.items() if kk != "results"} for k, v in runs.items()},
        "comparisons": comparisons,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")

    with (out_dir / "failures.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "run_key",
                "mode",
                "benchmark_task_id",
                "repo",
                "category",
                "split",
                "outcome",
                "failure_category",
                "attempts",
                "model_calls",
                "duration_s",
                "state_reason",
            ]
        )
        for key, v in runs.items():
            for r in sorted(v["results"], key=lambda r: r.benchmark_task_id):
                if r.outcome == "success":
                    continue
                writer.writerow(
                    [
                        key,
                        v["run"]["mode"],
                        r.benchmark_task_id,
                        r.repo,
                        r.category,
                        split_of.get(r.benchmark_task_id, ""),
                        r.outcome,
                        r.failure_category,
                        r.attempts,
                        r.model_calls,
                        round(r.duration_ms / 1000, 1),
                        str((r.details or {}).get("state_reason") or "")[:200],
                    ]
                )

    lines = [
        "# Evaluation results",
        "",
        f"Generated {generated} from stored per-task results. Every evaluated "
        "task is in the denominator (failures, errors and timeouts included).",
        "",
    ]
    for key, v in runs.items():
        run = v["run"]
        lines += [
            f"## Run `{key}` ({run['mode']})",
            "",
            f"- task set version: `{run['taskset_version']}`; split: {run['split']}",
            f"- model: {run['model_provider']} / `{run['model_name']}`; strategy: "
            f"{run['config'].get('strategy')}; temperature {run['config'].get('temperature')}",
            f"- platform revision: `{run['config'].get('platform_revision')}`; started {run['started_at']}, "
            f"finished {run['finished_at']}",
            f"- model requests: {v['model_requests']} ({v['failed_model_requests']} failed); "
            f"model inference time: {v['model_inference_seconds']} s",
            "",
            "| Split | Evaluated | Successful | Failed | Timeouts | Errors | Completion | 95% CI |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for split, m in v["metrics"].items():
            ci = _wilson(m["successful"], m["evaluated"])
            lines.append(
                f"| {split} | {m['evaluated']} | {m['successful']} | {m['failed']} | {m['timeouts']} | "
                f"{m['errors']} | {_pct(m['completion_rate'])} | "
                f"{'n/a' if ci is None else f'{ci[0] * 100:.1f}-{ci[1] * 100:.1f}%'} |"
            )
        m = v["metrics"]["all"]
        lines += ["", "| Category | Evaluated | Successful | Rate |", "| --- | ---: | ---: | ---: |"]
        for cat, c in m["by_category"].items():
            lines.append(f"| {cat} | {c['total']} | {c['success']} | {_pct(c['rate'])} |")
        lines += [
            "",
            "Failure categories: " + (", ".join(f"{k}: {n}" for k, n in m["failure_categories"].items()) or "none"),
            "",
            f"Latency per task (s): p50 {m['latency_s']['p50']}, p90 {m['latency_s']['p90']}, "
            f"max {m['latency_s']['max']}",
            "",
            f"Tokens: {m['prompt_tokens']} prompt + {m['completion_tokens']} completion over "
            f"{m['model_calls']} recorded model calls.",
            "",
            "Inference cost: "
            + (
                "not applicable - local CPU inference has no per-token price; compute time is reported instead"
                if m["inference_cost_usd"] is None
                else f"${m['inference_cost_usd']:.4f} total, ${m['cost_per_accepted_patch_usd']} per accepted patch"
            ),
            "",
        ]
    if comparisons:
        lines += [
            "## Platform vs baseline (paired on identical tasks)",
            "",
            "| Comparison | Split | Tasks | Platform | Baseline | Difference (points) | Platform-only wins | "
            "Baseline-only wins |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for name, comp in comparisons.items():
            for split, c in comp.items():
                if not c["tasks_compared"]:
                    continue
                lines.append(
                    f"| {name} | {split} | {c['tasks_compared']} | {_pct(c['platform_rate'])} | "
                    f"{_pct(c['baseline_rate'])} | {c['improvement_points']:+.1f} | "
                    f"{c['platform_only_successes']} | {c['baseline_only_successes']} |"
                )
        lines.append("")
    (out_dir / "evaluation.md").write_text("\n".join(lines) + "\n")
    return metrics
