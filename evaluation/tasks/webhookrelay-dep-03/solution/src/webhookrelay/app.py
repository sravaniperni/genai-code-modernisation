"""Flask application: the webhook intake endpoint and the admin status page."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote

from flask import Flask, abort, jsonify, render_template_string, request
from flask.json.provider import DefaultJSONProvider
from markupsafe import Markup, escape

from . import __version__
from .clock import isoformat_z
from .config import RelayConfig, load_config
from .delivery import AttemptRecord, Dispatcher
from .payloads import Event, PayloadError, normalise
from .plugins import PluginRegistry, default_registry
from .signatures import SignatureError, authenticate

STATUS_TEMPLATE = """<!doctype html><title>webhookrelay status</title><h1>webhookrelay {{ version }}</h1>
<p>Serving since {{ started_at or "-" }}; {{ received }} event(s) received; retry queue {{ scheduler.pending }}</p>
<table class="targets"><tr><th>Target</th><th>State</th><th>Delivered</th><th>Failed</th><th>Last attempt</th></tr>
{% for row in rows %}<tr><td><a href="{{ row.link }}">{{ row.name }}</a></td><td>{{ row.badge }}</td>
<td>{{ row.delivered }}</td><td>{{ row.failed }}</td><td>{{ row.last_attempt_at or "-" }}</td></tr>
{% endfor %}</table><h2>Recent attempts{% if selected %} for {{ selected }}{% endif %}</h2><ul class="attempts">
{% for a in recent %}<li>{{ a.attempted_at }} {{ a.target }} #{{ a.attempt }}: {{ a.status or a.error }}</li>
{% endfor %}</ul>
<h2>Plugins</h2><ul class="plugins">{% for p in plugins %}<li>{{ p.name }} ({{ p.origin }})</li>{% endfor %}</ul>
"""


class RelayJSONProvider(DefaultJSONProvider):
    """JSON for relay types: UTC datetimes as ``...Z`` strings, records and events through ``to_dict()``."""

    @staticmethod
    def default(o: Any) -> Any:
        if isinstance(o, datetime):
            return isoformat_z(o)
        if hasattr(o, "to_dict"):
            return o.to_dict()
        if isinstance(o, (set, frozenset)):
            return sorted(o)
        return DefaultJSONProvider.default(o)


class Relay:
    """Everything one running relay needs: configuration, plugins and the dispatcher."""

    def __init__(self, config: RelayConfig, *, transport: Any = None, clock: Any = None, registry: Any = None):
        self.config = config
        self.dispatcher = Dispatcher(config, transport=transport, clock=clock)
        self.clock = self.dispatcher.clock
        self.registry: PluginRegistry = registry if registry is not None else default_registry(config.plugins)
        self.started_at: datetime | None = None
        self.received = 0

    def handle(self, event: Event) -> list[AttemptRecord]:
        self.received += 1
        transformed = self.registry.apply(event)
        return [] if transformed is None else self.dispatcher.dispatch(transformed)

    def status(self) -> dict[str, Any]:
        return {
            "version": __version__, "started_at": self.started_at, "now": self.clock.now(),
            "received": self.received, "targets": self.dispatcher.stats(),
            "scheduler": self.dispatcher.scheduler.describe(), "plugins": self.registry.describe(),
            "recent": list(self.dispatcher.attempts)[-20:],
        }


def status_badge(row: Mapping[str, Any]) -> Markup:
    """Small HTML badge summarising a target's last attempt."""
    if row["last_status"] is None and row["last_error"] is None:
        return Markup('<span class="badge idle">idle</span>')
    ok = row["last_error"] is None and 200 <= row["last_status"] < 300
    detail = escape(row["last_error"] or f"HTTP {row['last_status']}")
    state = "ok" if ok else "failing"
    return Markup(f'<span class="badge {state}" title="{detail}">{state}</span>')


def create_app(config: RelayConfig | Mapping[str, Any], *, transport: Any = None, clock: Any = None,
               registry: Any = None, start_scheduler: bool = True) -> Flask:
    """Create the relay's WSGI application. The retry scheduler starts when the first request arrives."""
    relay_config = config if isinstance(config, RelayConfig) else load_config(config)
    relay = Relay(relay_config, transport=transport, clock=clock, registry=registry)
    app = Flask(__name__)
    app.json = RelayJSONProvider(app)
    app.extensions["webhookrelay"] = relay
    first_request = threading.Lock()

    @app.before_request
    def _start_relay() -> None:
        if relay.started_at is not None:
            return
        with first_request:
            if relay.started_at is None:
                relay.started_at = relay.clock.now()
                if start_scheduler:
                    relay.dispatcher.scheduler.start()

    def _require_admin() -> None:
        token = relay.config.admin_token
        if token and token not in (request.headers.get("X-Admin-Token"), request.args.get("token")):
            abort(403)

    @app.post("/hooks/<source>")
    def receive(source: str):
        src = relay.config.sources.get(source)
        if src is None:
            abort(404)
        body = request.get_data()
        try:
            authenticate(src, request.headers, body, clock=relay.clock)
        except SignatureError as exc:
            return jsonify(error=str(exc)), 401
        try:
            event = normalise(source, dict(request.headers), body, relay.clock.now())
        except PayloadError as exc:
            return jsonify(error=str(exc)), 400
        records = relay.handle(event)
        return jsonify(event=event.id, type=event.type, deliveries=records), 202

    @app.get("/admin/status")
    def status_page():
        _require_admin()
        status = relay.status()
        selected = request.args.get("target")
        rows = [
            {**row, "badge": status_badge(row), "link": "/admin/status?target=" + quote(row["name"]),
             "last_attempt_at": isoformat_z(row["last_attempt_at"])}
            for row in status["targets"]
        ]
        recent = [r.to_dict() for r in status["recent"] if selected in (None, r.target)]
        return render_template_string(
            STATUS_TEMPLATE, version=status["version"], started_at=isoformat_z(status["started_at"]),
            received=status["received"], scheduler=status["scheduler"], rows=rows, recent=recent,
            selected=selected, plugins=status["plugins"],
        )

    @app.get("/admin/status.json")
    def status_json():
        _require_admin()
        return jsonify(relay.status())

    return app
