"""OpenTelemetry tracing setup.

Spans are created around model calls (``model.complete``) and can be exported to the console or to a JSON
Lines file (``<data_dir>/traces.jsonl``) for offline latency analysis. Any OTLP-compatible collector can
be used by installing ``opentelemetry-exporter-otlp`` and configuring the SDK through its standard
environment variables; it is intentionally not a hard dependency.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
    SpanExportResult,
)

from modernisation.config import Settings

_configured = False
_lock = threading.Lock()


class JsonlSpanExporter(SpanExporter):
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self.path.open("a", encoding="utf-8") as fh:
            for span in spans:
                fh.write(
                    json.dumps(
                        {
                            "name": span.name,
                            "trace_id": f"{span.context.trace_id:032x}" if span.context else None,
                            "span_id": f"{span.context.span_id:016x}" if span.context else None,
                            "start_ns": span.start_time,
                            "end_ns": span.end_time,
                            "duration_ms": ((span.end_time or 0) - (span.start_time or 0)) / 1e6,
                            "attributes": dict(span.attributes or {}),
                            "status": span.status.status_code.name,
                        }
                    )
                    + "\n"
                )
        return SpanExportResult.SUCCESS


def configure_tracing(settings: Settings) -> None:
    global _configured
    with _lock:
        if _configured or settings.otel_exporter == "none":
            return
        provider = TracerProvider(resource=Resource.create({"service.name": "modernisation"}))
        if settings.otel_exporter == "console":
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        else:
            provider.add_span_processor(BatchSpanProcessor(JsonlSpanExporter(settings.data_dir / "traces.jsonl")))
        trace.set_tracer_provider(provider)
        _configured = True
