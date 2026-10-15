"""Oracle model for harness validation (not a model result).

The oracle answers every implementation request with the task's reference solution expressed as minimal
SEARCH/REPLACE hunks against the files the platform shows it. Running the full platform workflow with the oracle
measures the pipeline's ceiling: any oracle task that does not succeed is a false negative of the platform or the
harness (environment, verification, policy), not a model failure.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

from modernisation.evaluation.taskset import BenchmarkTask
from modernisation.llm.base import CallRecord, CallSink, ChatMessage, Completion

FILE_RE = re.compile(r'<file path="([^"]+)">\n(.*?)\n</file>', re.DOTALL)


def solution_files(task: BenchmarkTask) -> dict[str, str]:
    return {
        str(p.relative_to(task.solution_dir)): p.read_text()
        for p in sorted(task.solution_dir.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def hunks(path: str, current: str, target: str, context: int = 2) -> list[str]:
    """Minimal unique SEARCH/REPLACE blocks turning ``current`` into ``target``."""
    if not current:
        return [f"{path}\n<<<<<<< SEARCH\n=======\n{target}>>>>>>> REPLACE\n"]
    a = current.splitlines(keepends=True)
    b = target.splitlines(keepends=True)
    blocks = []
    for group in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_grouped_opcodes(context):
        i1, i2 = group[0][1], group[-1][2]
        j1, j2 = group[0][3], group[-1][4]
        # widen the context (equal lines on both sides) until the SEARCH text is non-empty and unique
        while (not "".join(a[i1:i2]) or current.count("".join(a[i1:i2])) != 1) and (i1 > 0 or i2 < len(a)):
            if i1 > 0:
                i1, j1 = i1 - 1, j1 - 1
            if i2 < len(a):
                i2, j2 = i2 + 1, j2 + 1
        blocks.append(f"{path}\n<<<<<<< SEARCH\n{''.join(a[i1:i2])}=======\n{''.join(b[j1:j2])}>>>>>>> REPLACE\n")
    return blocks


class OracleModel:
    provider = "oracle"
    model = "reference-solution-oracle"

    def __init__(self, task: BenchmarkTask, sink: CallSink | None = None):
        self.task = task
        self.sink = sink
        self.solution = solution_files(task)

    def _record(self, purpose: str) -> None:
        if self.sink:
            self.sink(CallRecord(self.provider, self.model, purpose, "ok", 0, 0, 0, 0, cost_usd=0.0))

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "output",
    ) -> Completion:
        self._record(purpose)
        if purpose == "plan":
            text = json.dumps(
                {
                    "summary": "Apply the reference change.",
                    "target_files": list(self.solution),
                    "steps": [{"description": "apply reference solution", "files": list(self.solution)}],
                    "risks": [],
                    "validation": [],
                    "needs_clarification": False,
                    "clarification_questions": [],
                }
            )
            return Completion(text, self.provider, self.model, 0, 0, 0)
        shown = {m.group(1): m.group(2) + "\n" for m in FILE_RE.finditer(messages[-1].content)}
        blocks: list[str] = []
        for path, target in self.solution.items():
            if path not in shown:
                continue  # the oracle can only edit files the platform showed it
            current = "" if shown[path].strip() == "(new file - does not exist yet)" else shown[path]
            if current != target:
                blocks.extend(hunks(path, current, target))
        return Completion("\n".join(blocks), self.provider, self.model, 0, 0, 0)


def oracle_factory(tasks: dict[str, BenchmarkTask]):  # type: ignore[no-untyped-def]
    """Model factory for the runner: tasks are looked up by their benchmark repository name."""
    from modernisation.llm.factory import db_sink

    def factory(task_row: Any) -> OracleModel:
        bench = tasks[task_row.repository.name.removeprefix("bench-")]
        return OracleModel(bench, sink=db_sink(task_row.id, task_row.evaluation_run_id))

    return factory
