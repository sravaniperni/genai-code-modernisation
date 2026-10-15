"""Build model clients from settings and persist every model request for cost/latency accounting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from modernisation.config import Settings, get_settings
from modernisation.db.models import ModelCall, Task
from modernisation.db.session import session_scope
from modernisation.llm.base import CallRecord, CallSink, ModelClient, Pricing, RetryPolicy
from modernisation.llm.providers import AnthropicClient, OpenAICompatibleClient


def build_client(settings: Settings, sink: CallSink | None = None) -> ModelClient | None:
    if settings.model_provider == "none" or not settings.model_name:
        return None
    common: dict[str, Any] = dict(
        model=settings.model_name,
        api_key=settings.model_api_key.get_secret_value() if settings.model_api_key else None,
        timeout_s=settings.model_timeout_s,
        max_output_tokens=settings.model_max_output_tokens,
        temperature=settings.model_temperature,
        retry=RetryPolicy(max_retries=settings.model_max_retries),
        pricing=Pricing(settings.model_price_input_per_mtok, settings.model_price_output_per_mtok),
        sink=sink,
    )
    if settings.model_provider == "openai_compatible":
        if not settings.model_base_url:
            raise ValueError("MODERNISATION_MODEL_BASE_URL is required for openai_compatible")
        return OpenAICompatibleClient(
            base_url=settings.model_base_url, structured_mode=settings.model_structured_output, **common
        )
    if settings.model_provider == "anthropic":
        return AnthropicClient(base_url=settings.model_base_url or "https://api.anthropic.com", **common)
    raise ValueError(f"unknown model provider {settings.model_provider}")


def db_sink(task_id: int | None, evaluation_run_id: int | None = None) -> CallSink:
    def sink(record: CallRecord) -> None:
        with session_scope() as session:
            session.add(
                ModelCall(
                    task_id=task_id,
                    evaluation_run_id=evaluation_run_id,
                    purpose=record.purpose,
                    provider=record.provider,
                    model=record.model,
                    status=record.status,
                    error=record.error,
                    retry_index=record.retry_index,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    latency_ms=record.latency_ms,
                    cost_usd=record.cost_usd,
                )
            )
            if task_id is not None:
                from modernisation.agents.store import add_event

                add_event(
                    session,
                    task_id,
                    "model",
                    f"model {record.purpose}: {record.status} in {record.latency_ms} ms"
                    + (
                        f" ({record.prompt_tokens}+{record.completion_tokens} tokens)"
                        if record.prompt_tokens is not None
                        else ""
                    ),
                    payload={
                        "purpose": record.purpose,
                        "status": record.status,
                        "model": record.model,
                        "retry_index": record.retry_index,
                        "error": record.error,
                    },
                )

    return sink


def task_model_factory(settings: Settings | None = None) -> Callable[[Task], ModelClient | None]:
    settings = settings or get_settings()

    def factory(task: Task) -> ModelClient | None:
        return build_client(settings, db_sink(task.id, task.evaluation_run_id))

    return factory
