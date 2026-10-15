"""Evaluation command line.

python -m modernisation.evaluation list      [--split dev|heldout|all]
python -m modernisation.evaluation validate  [--split ...] [--tasks id,id] [--out evaluation/validation-report.json]
python -m modernisation.evaluation lock                       # freeze the task-set version
python -m modernisation.evaluation run --mode platform|baseline --run-key KEY [--split ...] [--tasks ...] [--final]
python -m modernisation.evaluation report --run-keys KEY1,KEY2 [--out-dir reports]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from modernisation.config import get_settings
from modernisation.log import configure_logging

DEFAULT_EVAL_DIR = Path(__file__).resolve().parents[4] / "evaluation"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modernisation.evaluation")
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("list", "validate", "run"):
        p = sub.add_parser(name)
        p.add_argument("--split", default="all", choices=["dev", "heldout", "all"])
        p.add_argument("--tasks", default="")
        if name == "validate":
            p.add_argument("--out", type=Path, default=None)
        if name == "run":
            p.add_argument("--mode", required=True, choices=["platform", "baseline"])
            p.add_argument("--run-key", required=True)
            p.add_argument("--final", action="store_true", help="require the frozen task-set version")
            p.add_argument("--task-timeout-s", type=float, default=2400.0)
    sub.add_parser("lock")
    rep = sub.add_parser("report")
    rep.add_argument("--run-keys", required=True)
    rep.add_argument("--out-dir", type=Path, default=DEFAULT_EVAL_DIR.parent / "reports")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    from modernisation.evaluation.taskset import load_tasks, taskset_hash

    eval_dir: Path = args.eval_dir
    ids = [t for t in getattr(args, "tasks", "").split(",") if t]

    if args.cmd == "list":
        tasks = load_tasks(eval_dir, split=args.split, ids=ids or None)
        counts = Counter((t.repo, t.category, t.split) for t in tasks)
        print(
            json.dumps(
                {
                    "version": taskset_hash(eval_dir),
                    "tasks": len(tasks),
                    "by_category": Counter(t.category for t in tasks),
                    "by_split": Counter(t.split for t in tasks),
                    "by_repo": Counter(t.repo for t in tasks),
                    "cells": {"/".join(k): v for k, v in sorted(counts.items())},
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "validate":
        from modernisation.evaluation.validate import validate

        tasks = load_tasks(eval_dir, split=args.split, ids=ids or None)
        report = validate(eval_dir, tasks, settings)
        text = json.dumps(report, indent=2)
        if args.out:
            args.out.write_text(text + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
        for r in report["results"]:
            print(f"{'OK  ' if r['valid'] else 'FAIL'} {r['id']}: {'; '.join(r['problems'])[:400]}")
        return 0 if report["valid"] == report["tasks"] else 1
    if args.cmd == "lock":
        tasks = load_tasks(eval_dir)
        lock = {
            "taskset_version": taskset_hash(eval_dir),
            "tasks": len(tasks),
            "by_category": Counter(t.category for t in tasks),
            "by_split": Counter(t.split for t in tasks),
            "frozen_at": datetime.now(UTC).isoformat(),
        }
        (eval_dir / "TASKSET.lock").write_text(json.dumps(lock, indent=2) + "\n")
        print(json.dumps(lock, indent=2))
        return 0
    if args.cmd == "run":
        from modernisation.evaluation.runner import EvaluationRunner

        if args.final:
            lock = json.loads((eval_dir / "TASKSET.lock").read_text())
            if lock["taskset_version"] != taskset_hash(eval_dir):
                print("task set differs from the frozen TASKSET.lock; refusing a final run", file=sys.stderr)
                return 2
        tasks = load_tasks(eval_dir, split=args.split, ids=ids or None)
        runner = EvaluationRunner(
            eval_dir,
            mode=args.mode,
            run_key=args.run_key,
            split=args.split,
            settings=settings,
            task_timeout_s=args.task_timeout_s,
        )
        run_id = runner.run(tasks)
        print(json.dumps({"run_id": run_id, "run_key": args.run_key}))
        return 0
    if args.cmd == "report":
        from modernisation.evaluation.report import write_reports

        write_reports([k for k in args.run_keys.split(",") if k], args.out_dir, eval_dir)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
