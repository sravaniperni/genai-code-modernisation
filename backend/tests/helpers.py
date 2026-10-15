"""Shared test utilities.

``ScriptedModel`` is a *test double*: it returns pre-written responses so workflow mechanics (state
transitions, patch validation, repair loops, recovery) can be tested deterministically. It says nothing
about model quality; results produced with it are never reported as evaluation results.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from modernisation.llm.base import CallRecord, CallSink, ChatMessage, Completion, ModelError

SAMPLE_FILES: dict[str, str] = {
    "pyproject.toml": """[project]
name = "inventory"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
test = ["pytest"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
    "README.md": "# inventory\n\nSmall inventory and pricing library used as a test fixture.\n",
    "src/inventory/__init__.py": '"""Inventory management helpers."""\n\nfrom inventory.pricing import apply_discount, order_total\n\n__all__ = ["apply_discount", "order_total"]\n',
    "src/inventory/pricing.py": '''"""Pricing rules."""

from __future__ import annotations

from inventory.models import LineItem

BULK_THRESHOLD = 10


def apply_discount(price: float, percent: float) -> float:
    """Return ``price`` reduced by ``percent`` percent, never below zero."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return round(price - price * percent / 1000, 2)


def order_total(items: list[LineItem], discount_percent: float = 0.0) -> float:
    """Total of all line items after an order-level discount."""
    subtotal = sum(item.unit_price * item.quantity for item in items)
    return apply_discount(subtotal, discount_percent)


def is_bulk(item: LineItem) -> bool:
    return item.quantity >= BULK_THRESHOLD
''',
    "src/inventory/models.py": '''"""Domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineItem:
    sku: str
    unit_price: float
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError("quantity must be non-negative")
''',
    "src/inventory/report.py": '''"""Reporting helpers."""

from __future__ import annotations

from inventory.models import LineItem
from inventory.pricing import is_bulk, order_total


def summary(items: list[LineItem]) -> dict[str, float]:
    return {"total": order_total(items), "bulk_lines": float(sum(1 for i in items if is_bulk(i)))}
''',
    "tests/test_pricing.py": """from inventory.models import LineItem
from inventory.pricing import apply_discount, order_total


def test_zero_discount_keeps_price():
    assert apply_discount(50.0, 0) == 50.0


def test_invalid_percent_rejected():
    import pytest

    with pytest.raises(ValueError):
        apply_discount(10.0, 120)


def test_order_total_without_discount():
    items = [LineItem("a", 2.5, 4), LineItem("b", 1.0, 3)]
    assert order_total(items) == 13.0
""",
    "tests/test_report.py": """from inventory.models import LineItem
from inventory.report import summary


def test_summary_counts_bulk_lines():
    items = [LineItem("a", 1.0, 12), LineItem("b", 2.0, 1)]
    assert summary(items)["bulk_lines"] == 1.0
""",
}

BUG_REQUEST = (
    "apply_discount returns the wrong amount: apply_discount(200.0, 10) should return 180.0 but returns 198.0. "
    "Fix the percentage calculation in the pricing module."
)

CORRECT_FIX = """src/inventory/pricing.py
<<<<<<< SEARCH
    return round(price - price * percent / 1000, 2)
=======
    return round(price - price * percent / 100, 2)
>>>>>>> REPLACE
"""


def git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout


def make_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    for rel, content in (files or SAMPLE_FILES).items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "initial import")
    return path


def commit_change(path: Path, rel: str, content: str, message: str = "update") -> str:
    target = path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD").strip()


PLAN_JSON = json.dumps(
    {
        "summary": "Fix percentage arithmetic in apply_discount.",
        "target_files": ["src/inventory/pricing.py"],
        "steps": [{"description": "Divide by 100 instead of 1000", "files": ["src/inventory/pricing.py"]}],
        "risks": ["order_total depends on apply_discount"],
        "validation": ["tests/test_pricing.py"],
        "needs_clarification": False,
        "clarification_questions": [],
    }
)


class ScriptedModel:
    """Deterministic model double. ``responses`` maps purpose -> list of outputs (or callables)."""

    provider = "scripted"
    model = "scripted-test-double"

    def __init__(
        self,
        responses: dict[str, list[str | Callable[[list[ChatMessage]], str] | Exception]],
        sink: CallSink | None = None,
    ):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.sink = sink
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "output",
    ) -> Completion:
        self.calls.append((purpose, messages))
        queue = self.responses.get(purpose) or []
        if not queue:
            raise ModelError(f"scripted model has no response left for {purpose}", retryable=False)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            if self.sink:
                self.sink(CallRecord(self.provider, self.model, purpose, "error", 0, 1, error=str(item)))
            raise item
        text = item(messages) if callable(item) else item
        if self.sink:
            self.sink(CallRecord(self.provider, self.model, purpose, "ok", 0, 1, 100, 50, cost_usd=None))
        return Completion(text, self.provider, self.model, 100, 50, 1)
