"""Provider-independent model interface."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass
class ChatMessage:
    role: Role
    content: str


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    finish_reason: str | None = None
    structured: dict[str, Any] | None = None  # provider-native structured output (e.g. tool input)


class ModelError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass
class CallRecord:
    """One physical request to a provider (including failed and retried ones)."""

    provider: str
    model: str
    purpose: str
    status: str  # ok|error|invalid_output
    retry_index: int
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    cost_usd: float | None = None


CallSink = Callable[[CallRecord], None]


class ModelClient(Protocol):
    provider: str
    model: str

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "output",
    ) -> Completion: ...


@dataclass
class Pricing:
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None

    def cost(self, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
        if self.input_per_mtok is None or self.output_per_mtok is None:
            return None
        if prompt_tokens is None or completion_tokens is None:
            return None
        return prompt_tokens / 1e6 * self.input_per_mtok + completion_tokens / 1e6 * self.output_per_mtok


@dataclass
class RetryPolicy:
    max_retries: int = 2
    base_delay_s: float = 1.0
    max_delay_s: float = 20.0
    sleep: Callable[[float], None] = field(default=time.sleep)

    def delay(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay_s)
        return min(self.base_delay_s * (2**attempt), self.max_delay_s)
