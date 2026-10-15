"""Parsing inbound webhook requests into normalised :class:`Event` objects."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import parse_qsl

from .clock import isoformat_z

DEFAULT_CONTENT_TYPE = "application/octet-stream"
EVENT_TYPE_HEADERS = ("X-Event-Type", "X-GitHub-Event", "X-Gitlab-Event")
EVENT_ID_HEADERS = ("X-Event-Id", "X-GitHub-Delivery", "X-Request-Id")


class PayloadError(ValueError):
    """The request body could not be decoded."""


@dataclass
class Event:
    """A webhook after normalisation, independent of the sender's wire format."""

    source: str
    type: str
    id: str
    data: dict[str, Any]
    received_at: datetime
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "received_at": isoformat_z(self.received_at),
            "data": self.data,
        }


def header_value(headers: Mapping[str, str], name: str, default: str | None = None) -> str | None:
    """Look up a header by name. HTTP header names are case-insensitive."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return default


_PARAM_RE = re.compile(r';\s*([^=;\s]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^;]*)')


def parse_content_type(value: str | None) -> tuple[str, dict[str, str]]:
    """Split a Content-Type header into ``(media_type, params)``.

    The media type and parameter names are lower-cased and quoted parameter values are unquoted
    (``text/plain; Charset="latin-1"`` gives ``("text/plain", {"charset": "latin-1"})``). A missing or
    blank header means ``application/octet-stream``.
    """
    if not value or not value.strip():
        return DEFAULT_CONTENT_TYPE, {}
    media_type, _, rest = value.partition(";")
    params: dict[str, str] = {}
    for match in _PARAM_RE.finditer(";" + rest):
        raw = match.group(2).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            raw = raw[1:-1].replace("\\\\", "\\").replace('\\"', '"')
        params[match.group(1).lower()] = raw
    return media_type.strip().lower(), params


def decode_body(body: bytes, content_type: str | None) -> dict[str, Any]:
    """Decode a request body according to its Content-Type into a dict."""
    media_type, params = parse_content_type(content_type)
    charset = params.get("charset", "utf-8")
    try:
        text = body.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise PayloadError(f"cannot decode body as {charset}: {exc}") from exc
    if media_type == "application/json" or media_type.endswith("+json"):
        return _json_object(text)
    if media_type == "application/x-www-form-urlencoded":
        form = dict(parse_qsl(text, keep_blank_values=True))
        if "payload" in form:  # GitHub and Slack style form envelopes
            return _json_object(form["payload"])
        return form
    if media_type in ("application/xml", "text/xml") or media_type.endswith("+xml"):
        return parse_xml(text)
    if media_type.startswith("text/"):
        return {"text": text}
    raise PayloadError(f"unsupported content type {media_type!r}")


def _json_object(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PayloadError(f"invalid JSON: {exc.msg}") from exc
    return value if isinstance(value, dict) else {"items": value}


def parse_xml(text: str) -> dict[str, Any]:
    """Convert an XML envelope into a dict.

    Root attributes become ``_``-prefixed keys (``<event type="push">`` gives ``_type``); the payload is
    the content of ``<data>`` (or of the root when there is none); ``<headers><header name="...">``
    entries are returned under ``_headers``. Elements with children become dicts, repeated tags lists,
    and leaf elements their text.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise PayloadError(f"invalid XML: {exc}") from exc
    result: dict[str, Any] = {f"_{key}": value for key, value in root.attrib.items()}
    headers = root.find("headers")
    if headers is not None:
        result["_headers"] = {h.get("name", ""): (h.text or "").strip() for h in headers.iter("header")}
    data = root.find("data")
    container = data if data is not None else root
    for child in container:
        if child is not headers:
            _merge(result, child.tag, _element_value(child))
    return result


def _element_value(element: ET.Element) -> Any:
    if len(element) == 0:
        return (element.text or "").strip()
    value: dict[str, Any] = {}
    for child in element:
        _merge(value, child.tag, _element_value(child))
    return value


def _merge(target: dict[str, Any], key: str, value: Any) -> None:
    if key not in target:
        target[key] = value
    elif isinstance(target[key], list):
        target[key].append(value)
    else:
        target[key] = [target[key], value]


def _first_header(headers: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = header_value(headers, name)
        if value:
            return value
    return None


def _text(value: Any) -> str | None:
    return str(value) if isinstance(value, (str, int)) and str(value) else None


def normalise(source: str, headers: Mapping[str, str], body: bytes, received_at: datetime) -> Event:
    """Build an :class:`Event` from a raw request.

    The event type comes from the first of :data:`EVENT_TYPE_HEADERS` that is present, then from the
    payload (``type`` or ``event``); the id likewise from :data:`EVENT_ID_HEADERS`, then ``id``, and
    finally a digest of the source and body so that redeliveries get the same id.
    """
    data = decode_body(body, header_value(headers, "Content-Type"))
    merged_headers = {**data.pop("_headers", {}), **headers}
    event_type = (_first_header(headers, EVENT_TYPE_HEADERS) or _text(data.pop("_type", None))
                  or _text(data.get("type")) or _text(data.get("event")) or "unknown")
    event_id = (_first_header(headers, EVENT_ID_HEADERS) or _text(data.pop("_id", None)) or _text(data.get("id"))
                or hashlib.sha256(source.encode() + b"\0" + body).hexdigest()[:16])
    return Event(source, event_type, event_id, data, received_at, merged_headers)
