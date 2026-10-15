"""HTTP model providers: OpenAI-compatible chat completions and the Anthropic Messages API.

Both share one retry loop: transport errors, timeouts, HTTP 408/409/429 and 5xx are retried with
exponential backoff (honouring ``Retry-After``); every physical request, failed or not, is reported to the
call sink so that model expenditure includes unsuccessful attempts.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from opentelemetry import trace

from modernisation.llm.base import (
    CallRecord,
    CallSink,
    ChatMessage,
    Completion,
    ModelError,
    Pricing,
    RetryPolicy,
)
from modernisation.log import redact

tracer = trace.get_tracer("modernisation.llm")

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class _HttpProvider:
    provider = "http"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_s: float,
        max_output_tokens: int,
        temperature: float,
        retry: RetryPolicy,
        pricing: Pricing,
        sink: CallSink | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.retry = retry
        self.pricing = pricing
        self.sink = sink
        self._client = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=15.0), transport=transport)

    # provider-specific -----------------------------------------------------------------------------
    def _request(
        self, messages: list[ChatMessage], max_tokens: int, json_schema: dict[str, Any] | None, schema_name: str
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        raise NotImplementedError

    def _parse(self, body: dict[str, Any]) -> tuple[str, int | None, int | None, str | None, dict[str, Any] | None]:
        raise NotImplementedError

    # shared ----------------------------------------------------------------------------------------
    def _emit(self, record: CallRecord) -> None:
        if self.sink is not None:
            self.sink(record)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        purpose: str,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "output",
    ) -> Completion:
        url, headers, payload = self._request(messages, max_tokens or self.max_output_tokens, json_schema, schema_name)
        last_error: ModelError | None = None
        for attempt in range(self.retry.max_retries + 1):
            started = time.monotonic()
            with tracer.start_as_current_span("model.complete") as span:
                span.set_attribute("gen_ai.system", self.provider)
                span.set_attribute("gen_ai.request.model", self.model)
                span.set_attribute("modernisation.purpose", purpose)
                span.set_attribute("modernisation.retry_index", attempt)
                retry_after: float | None = None
                try:
                    response = self._client.post(url, headers=headers, json=payload)
                    latency = int((time.monotonic() - started) * 1000)
                    if response.status_code >= 400:
                        retryable = response.status_code in RETRYABLE_STATUS
                        ra = response.headers.get("retry-after")
                        retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
                        raise ModelError(
                            f"HTTP {response.status_code}: {redact(response.text[:500])}",
                            retryable=retryable,
                            status=response.status_code,
                        )
                    text, pt, ct, finish, structured = self._parse(response.json())
                    cost = self.pricing.cost(pt, ct)
                    span.set_attribute("gen_ai.usage.input_tokens", pt or 0)
                    span.set_attribute("gen_ai.usage.output_tokens", ct or 0)
                    self._emit(
                        CallRecord(self.provider, self.model, purpose, "ok", attempt, latency, pt, ct, cost_usd=cost)
                    )
                    return Completion(text, self.provider, self.model, pt, ct, latency, finish, structured)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    latency = int((time.monotonic() - started) * 1000)
                    last_error = ModelError(f"{type(exc).__name__}: {exc}", retryable=True)
                except ModelError as exc:
                    latency = int((time.monotonic() - started) * 1000)
                    last_error = exc
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    latency = int((time.monotonic() - started) * 1000)
                    last_error = ModelError(f"malformed provider response: {exc}", retryable=True)
                span.set_attribute("error", True)
                self._emit(
                    CallRecord(
                        self.provider, self.model, purpose, "error", attempt, latency, error=str(last_error)[:1000]
                    )
                )
                if not last_error.retryable or attempt >= self.retry.max_retries:
                    break
                self.retry.sleep(self.retry.delay(attempt, retry_after))
        assert last_error is not None
        raise last_error

    def close(self) -> None:
        self._client.close()


class OpenAICompatibleClient(_HttpProvider):
    """Chat Completions API as served by OpenAI, vLLM, llama.cpp, Ollama, LM Studio and others."""

    provider = "openai_compatible"

    def __init__(self, *, structured_mode: str = "json_schema", **kwargs: Any):
        super().__init__(**kwargs)
        self.structured_mode = structured_mode

    def _request(
        self, messages: list[ChatMessage], max_tokens: int, json_schema: dict[str, Any] | None, schema_name: str
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": self.temperature,
        }
        if json_schema is not None:
            if self.structured_mode == "json_schema":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": json_schema, "strict": False},
                }
            elif self.structured_mode == "json_object_schema":
                payload["response_format"] = {"type": "json_object", "schema": json_schema}
        return f"{self.base_url}/chat/completions", headers, payload

    def _parse(self, body: dict[str, Any]) -> tuple[str, int | None, int | None, str | None, dict[str, Any] | None]:
        choice = body["choices"][0]
        text = choice["message"].get("content") or ""
        usage = body.get("usage") or {}
        return text, usage.get("prompt_tokens"), usage.get("completion_tokens"), choice.get("finish_reason"), None


class AnthropicClient(_HttpProvider):
    """Anthropic Messages API. Structured output is obtained through a forced tool call."""

    provider = "anthropic"

    def _request(
        self, messages: list[ChatMessage], max_tokens: int, json_schema: dict[str, Any] | None, schema_name: str
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self.api_key or "",
        }
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages if m.role != "system"],
        }
        if system:
            payload["system"] = system
        if json_schema is not None:
            payload["tools"] = [{"name": schema_name, "description": "Return the result.", "input_schema": json_schema}]
            payload["tool_choice"] = {"type": "tool", "name": schema_name}
        base = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        return f"{base}/v1/messages", headers, payload

    def _parse(self, body: dict[str, Any]) -> tuple[str, int | None, int | None, str | None, dict[str, Any] | None]:
        text_parts: list[str] = []
        structured: dict[str, Any] | None = None
        for block in body.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                structured = block.get("input")
        usage = body.get("usage") or {}
        return (
            "".join(text_parts),
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            body.get("stop_reason"),
            structured,
        )
