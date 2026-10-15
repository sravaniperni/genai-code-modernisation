"""Build reports/claims_evidence.json from recorded evidence only.

Every quantitative claim is derived from a report file produced by an executed run; anything that was not measured is
listed with status UNMEASURED and must not appear in resume bullets.

    python scripts/build_claims.py --platform-run <key> --baseline-run <key>
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def rate_claim(cid: str, definition: str, metrics: dict[str, Any], run: dict[str, Any], split: str,
               lock: dict[str, Any], limitations: list[str]) -> dict[str, Any]:
    m = metrics[split]
    return {
        "id": cid,
        "status": "MEASURED",
        "definition": definition,
        "numerator": m["successful"],
        "denominator": m["evaluated"],
        "value": m["completion_rate"],
        "value_display": f"{m['successful']}/{m['evaluated']} ({m['completion_rate'] * 100:.1f}%)"
        if m["completion_rate"] is not None else "n/a",
        "evaluation_run": run["run_key"],
        "taskset_version": run["taskset_version"],
        "taskset_frozen": lock.get("taskset_version") == run["taskset_version"],
        "model": f"{run['model_provider']}:{run['model_name']}",
        "configuration": run["config"],
        "executed": {"started": run["started_at"], "finished": run["finished_at"]},
        "supporting_output": [f"reports/runs/{run['run_key']}.jsonl", "reports/metrics.json", "reports/evaluation.md"],
        "calculation": "successful tasks / all evaluated tasks in the split (errors, timeouts and escalations count as "
                       "failures)",
        "limitations": limitations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-run", required=True)
    parser.add_argument("--baseline-run", required=True)
    args = parser.parse_args()

    metrics = load(ROOT / "reports" / "metrics.json")
    lock = load(ROOT / "evaluation" / "TASKSET.lock")
    security = load(ROOT / "reports" / "security-results.json")
    recovery = load(ROOT / "reports" / "recovery-results.json")
    p = metrics["runs"][args.platform_run]
    b = metrics["runs"][args.baseline_run]
    comparison = metrics["comparisons"][f"{args.platform_run} vs {args.baseline_run}"]
    common_limits = [
        "five small fixture repositories authored for this benchmark (600-1500 lines of source each)",
        "Qwen2.5-Coder-1.5B-Instruct Q4_K_M on 4 CPU cores; results do not transfer to larger models",
        "acceptance tests written by the benchmark authors",
    ]
    claims: list[dict[str, Any]] = []
    for split, label in (("heldout", "held-out"), ("all", "all")):
        if split in p["metrics"]:
            claims.append(rate_claim(f"platform_completion_{split}",
                                     f"Verified completion rate of the full platform on the {label} task split",
                                     p["metrics"], p["run"], split, lock, common_limits))
        if split in b["metrics"]:
            claims.append(rate_claim(f"baseline_completion_{split}",
                                     f"Completion rate of the single-shot baseline on the {label} task split",
                                     b["metrics"], b["run"], split, lock, common_limits))
        comp = comparison.get(split)
        if comp and comp["tasks_compared"]:
            claims.append({
                "id": f"improvement_points_{split}",
                "status": "MEASURED",
                "definition": f"Platform completion rate minus baseline completion rate on identical {label} tasks",
                "numerator": comp["platform_successes"] - comp["baseline_successes"],
                "denominator": comp["tasks_compared"],
                "value": comp["improvement_points"],
                "value_display": f"{comp['improvement_points']:+.1f} percentage points "
                                 f"({comp['platform_successes']} vs {comp['baseline_successes']} of "
                                 f"{comp['tasks_compared']})",
                "evaluation_run": f"{args.platform_run} vs {args.baseline_run}",
                "taskset_version": p["run"]["taskset_version"],
                "model": f"{p['run']['model_provider']}:{p['run']['model_name']}",
                "configuration": {"platform": p["run"]["config"], "baseline": b["run"]["config"]},
                "executed": {"platform": p["run"]["finished_at"], "baseline": b["run"]["finished_at"]},
                "supporting_output": ["reports/metrics.json", "reports/evaluation.md"],
                "calculation": "(platform successes - baseline successes) / paired tasks * 100",
                "confidence_intervals_95": {"platform": comp["platform_rate_95ci"],
                                            "baseline": comp["baseline_rate_95ci"]},
                "limitations": common_limits + ["paired difference on a modest sample; see Wilson intervals"],
            })
    pm = p["metrics"]["all"]
    claims.append({
        "id": "cost_per_accepted_patch_usd",
        "status": "UNMEASURED" if pm["cost_per_accepted_patch_usd"] is None else "MEASURED",
        "definition": "Total inference expenditure (including failed attempts) / accepted patches",
        "value": pm["cost_per_accepted_patch_usd"],
        "reason": "local CPU inference has no per-token price" if pm["cost_per_accepted_patch_usd"] is None else None,
        "supporting_output": ["reports/metrics.json"],
    })
    if pm["successful"]:
        claims.append({
            "id": "model_inference_seconds_per_accepted_patch",
            "status": "MEASURED",
            "definition": "Model inference wall time over all tasks of the platform run (including failed tasks and "
                          "failed requests) divided by accepted patches",
            "numerator": p["model_inference_seconds"],
            "denominator": pm["successful"],
            "value": round(p["model_inference_seconds"] / pm["successful"], 1),
            "evaluation_run": args.platform_run,
            "supporting_output": ["reports/metrics.json"],
            "calculation": "sum(model_calls.latency_ms)/1000 / successful tasks",
            "limitations": ["CPU-only local inference; not comparable to hosted APIs"],
        })
    claims.append({
        "id": "recovery_scenarios",
        "status": "MEASURED",
        "definition": "Failure-recovery scenarios passing (worker termination, interrupted model calls, database "
                      "restarts, cancellation, duplicate webhooks, push/PR failures, stale revisions, timeouts, "
                      "partial operations)",
        "numerator": recovery["passed"], "denominator": recovery["scenarios"],
        "value_display": f"{recovery['passed']}/{recovery['scenarios']}; duplicate external actions "
                         f"{recovery['duplicate_external_actions']}; lost state {recovery['lost_task_state']}",
        "executed": recovery["generated_at"],
        "supporting_output": ["reports/recovery-results.json", "reports/recovery-results.md",
                              "backend/tests/recovery/test_recovery_scenarios.py"],
        "limitations": ["GitHub failures are injected against an in-process stand-in, not live GitHub",
                        "crash points are simulated in-process except two real SIGKILL scenarios"],
    })
    claims.append({
        "id": "security_scenarios",
        "status": "MEASURED",
        "definition": "Workflow-level security test executions passing in the real sandbox",
        "numerator": security["passed"], "denominator": security["scenarios"],
        "executed": security["generated_at"],
        "supporting_output": ["reports/security-results.json", "reports/security-results.md"],
        "limitations": ["tests cover the listed attack classes only; the sandbox shares the host kernel"],
    })
    for cid, reason in (
        ("developer_productivity_savings", "no timed human developer sessions were run"),
        ("infrastructure_cost_savings", "total infrastructure costs were not measured"),
        ("production_deployments_or_users", "the platform has not been deployed; independent project"),
        ("live_github_pull_requests", "no authorised test repository/token was provided"),
        ("hosted_model_performance", "no hosted model credentials were provided"),
    ):
        claims.append({"id": cid, "status": "UNMEASURED", "reason": reason})
    out = {"generated_at": datetime.now(UTC).isoformat(), "claims": claims}
    (ROOT / "reports" / "claims_evidence.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"wrote {len(claims)} claims")


if __name__ == "__main__":
    main()
