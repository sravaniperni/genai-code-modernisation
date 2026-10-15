"""Notification bodies rendered from Jinja2 templates.

Targets with a ``template`` receive a rendered notification instead of the raw event JSON. Templates get
``event``, ``data`` (the event payload) and ``base_url`` (the relay's public URL). Templates whose name
ends in ``.html`` are autoescaped.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jinja2 import DictLoader, Environment, StrictUndefined, pass_context, pass_eval_context, select_autoescape
from markupsafe import Markup, escape

from .payloads import Event
from .rendering import render_markdown

BUILTIN_TEMPLATES = {
    "chat.txt": (
        "[{{ event.source }}] {{ event.type }}{% if data.title is defined %}: {{ data.title }}{% endif %}\n"
        "{{ event.id | event_link }}"
    ),
    "email.html": (
        "<h1>{{ event.type | title }} from {{ event.source }}</h1>\n"
        "{% if data.message is defined %}<p>{{ data.message | nl2br }}</p>\n{% endif %}"
        "{% if data.body is defined %}<div class=\"body\">{{ data.body | markdown }}</div>\n{% endif %}"
        "<p>Event {{ event.id | event_link }}</p>"
    ),
}


def nl2br(eval_ctx: Any, value: Any) -> Any:
    """Line breaks become ``<br>`` tags in autoescaped templates; the text itself is escaped first."""
    lines = str(value).splitlines()
    if not eval_ctx.autoescape:
        return "\n".join(lines)
    return Markup("<br>\n").join(escape(line) for line in lines)


def event_link(context: Any, event_id: str) -> Any:
    """Link to an event on the relay's admin pages (uses ``base_url`` from the template context)."""
    url = f"{context.get('base_url') or ''}/admin/events/{event_id}"
    if not context.eval_ctx.autoescape:
        return url
    return Markup('<a href="{0}">{1}</a>').format(url, event_id)


def build_environment(templates: Mapping[str, str] | None = None) -> Environment:
    env = Environment(
        loader=DictLoader({**BUILTIN_TEMPLATES, **(templates or {})}),
        autoescape=select_autoescape(enabled_extensions=("html", "htm", "xml"), default_for_string=False),
        undefined=StrictUndefined,
    )
    env.filters["nl2br"] = pass_eval_context(nl2br)
    env.filters["event_link"] = pass_context(event_link)
    env.filters["markdown"] = render_markdown
    return env


class TemplateRenderer:
    """Renders notification templates (built-in ones plus any supplied by the deployment)."""

    def __init__(self, templates: Mapping[str, str] | None = None, *, base_url: str = ""):
        self.env = build_environment(templates)
        self.base_url = base_url.rstrip("/")

    def render(self, name: str, event: Event, **extra: Any) -> str:
        template = self.env.get_template(name)
        return template.render(event=event, data=event.data, base_url=self.base_url, **extra)
