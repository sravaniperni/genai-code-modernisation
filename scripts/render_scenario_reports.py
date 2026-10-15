"""Render reports/{security,recovery}-results.md from the JSON produced by the test suites.

    cd backend
    sudo -E MODERNISATION_SCENARIO_REPORT_DIR=../reports .venv/bin/pytest tests/security tests/recovery -p no:cacheprovider
    python ../scripts/render_scenario_reports.py ../reports
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

TITLES = {"security": "Security test results", "recovery": "Failure-recovery test results"}


def render(path: Path) -> str:
    data = json.loads(path.read_text())
    suite = data["suite"]
    lines = [
        f"# {TITLES.get(suite, suite)}",
        "",
        f"Generated {data['generated_at']} from `{path.name}` (pytest outcomes of the executed scenarios).",
        "",
        f"- scenarios executed: **{data['scenarios']}**; passed: **{data['passed']}**; failed: **{data['failed']}**; "
        f"skipped: **{data['skipped']}**",
    ]
    if suite == "recovery":
        lines += [
            f"- duplicate external actions observed: **{data['duplicate_external_actions']}**",
            f"- tasks with lost state: **{data['lost_task_state']}**",
            f"- incorrectly resumed tasks: **{data['incorrectly_resumed']}**",
        ]
    lines += ["", "Observation counters are only as complete as the assertions in each scenario; see the test source "
              "for exactly what is checked.", ""]
    by_area: dict[str, list[dict]] = defaultdict(list)
    for r in data["results"]:
        by_area[r["area"]].append(r)
    for area, rows in by_area.items():
        lines += [f"## {area}", "", "| ID | Scenario | Outcome | Key observations |", "| --- | --- | --- | --- |"]
        for r in rows:
            obs = r.get("observations") or {}
            shown = {k: v for k, v in obs.items() if k not in {"lost_state", "incorrect_resume"}}
            text = "; ".join(f"{k}={json.dumps(v)[:80]}" for k, v in list(shown.items())[:5])
            lines.append(f"| {r['id']} | {r['description']} | {r['outcome'].upper()} | {text.replace('|', '/')} |")
        lines.append("")
    failed = [r for r in data["results"] if r["outcome"] == "failed"]
    if failed:
        lines += ["## Failures", ""]
        for r in failed:
            lines += [f"### {r['id']} {r['description']}", "", "```", (r.get("detail") or "")[-1200:], "```", ""]
    return "\n".join(lines) + "\n"


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "reports")
    for suite in ("security", "recovery"):
        src = out / f"{suite}-results.json"
        if src.is_file():
            (out / f"{suite}-results.md").write_text(render(src))
            print(f"wrote {out / f'{suite}-results.md'}")


if __name__ == "__main__":
    main()
