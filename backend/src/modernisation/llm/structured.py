"""Validated structured outputs with a single bounded correction round."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from modernisation.llm.base import CallRecord, ChatMessage, ModelClient, ModelError

T = TypeVar("T", bound=BaseModel)

FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class StructuredOutputError(ModelError):
    def __init__(self, message: str, raw: str):
        super().__init__(message, retryable=False)
        self.raw = raw


def extract_json(text: str) -> Any:
    candidates = [m.group(1) for m in FENCE_RE.finditer(text)] + [text]
    for candidate in candidates:
        candidate = candidate.strip()
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            continue
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object found in model output")


def complete_structured[T: BaseModel](
    client: ModelClient,
    messages: list[ChatMessage],
    model_cls: type[T],
    *,
    purpose: str,
    max_tokens: int | None = None,
    correction_rounds: int = 1,
    sink: Any = None,
) -> tuple[T, str]:
    """Request ``model_cls`` as JSON, validate it, and ask once for a correction if it is invalid."""
    schema = model_cls.model_json_schema()
    convo = list(messages)
    raw = ""
    for round_no in range(correction_rounds + 1):
        completion = client.complete(
            convo, purpose=purpose, max_tokens=max_tokens, json_schema=schema, schema_name=model_cls.__name__
        )
        raw = completion.text
        try:
            data = completion.structured if completion.structured is not None else extract_json(raw)
            return model_cls.model_validate(data), raw
        except (ValueError, ValidationError) as exc:
            if sink is not None:
                sink(
                    CallRecord(
                        client.provider, client.model, purpose, "invalid_output", round_no, 0, error=str(exc)[:1000]
                    )
                )
            if round_no >= correction_rounds:
                raise StructuredOutputError(f"invalid structured output for {model_cls.__name__}: {exc}", raw) from exc
            convo = [
                *convo,
                ChatMessage("assistant", raw[:6000]),
                ChatMessage(
                    "user",
                    "That response was not valid. Errors:\n"
                    f"{str(exc)[:1500]}\n"
                    "Reply with only a JSON object that satisfies this JSON schema:\n"
                    f"{json.dumps(schema)[:4000]}",
                ),
            ]
    raise AssertionError("unreachable")
