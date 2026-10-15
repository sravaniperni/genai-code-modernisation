"""Relay configuration: inbound sources, delivery targets, routing rules and retry settings."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .routing import Rule
from .scheduler import RetryPolicy

log = logging.getLogger(__name__)

KNOWN_KEYS = frozenset({"sources", "targets", "rules", "retry", "proxy", "plugins", "admin_token", "base_url"})
AUTH_MODES = ("hmac", "jwt", "none")
TRANSPORTS = ("httpx", "pool")


class ConfigError(ValueError):
    """The relay configuration is invalid."""


@dataclass(frozen=True)
class Source:
    """An inbound webhook source and how its requests are authenticated."""

    name: str
    secret: str | None = None
    jwt_issuers: Mapping[str, str] = field(default_factory=dict)
    audience: str | None = None
    tolerance: int = 300


@dataclass(frozen=True)
class Target:
    """A downstream URL that receives deliveries."""

    name: str
    url: str
    secret: str | None = None
    auth: str = "none"
    template: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    max_attempts: int | None = None
    transport: str = "httpx"


@dataclass
class RelayConfig:
    sources: dict[str, Source]
    targets: dict[str, Target]
    rules: list[Rule]
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    proxy: str | None = None
    plugins: list[str] | None = None
    admin_token: str | None = None
    base_url: str = ""

    def retry_policy_for(self, target: Target) -> RetryPolicy:
        if target.max_attempts is None:
            return self.retry
        return dataclasses.replace(self.retry, max_attempts=target.max_attempts)


def _target(name: str, spec: Mapping[str, Any]) -> Target:
    if not spec.get("url"):
        raise ConfigError(f"target {name!r} has no url")
    auth = spec.get("auth", "hmac" if spec.get("secret") else "none")
    if auth not in AUTH_MODES:
        raise ConfigError(f"target {name!r}: unknown auth mode {auth!r}")
    if auth != "none" and not spec.get("secret"):
        raise ConfigError(f"target {name!r}: {auth} auth needs a secret")
    transport = spec.get("transport", "httpx")
    if transport not in TRANSPORTS:
        raise ConfigError(f"target {name!r}: unknown transport {transport!r}")
    return Target(name, spec["url"], spec.get("secret"), auth, spec.get("template"), dict(spec.get("params") or {}),
                  spec.get("max_attempts"), transport)


def load_config(raw: Mapping[str, Any]) -> RelayConfig:
    """Build a :class:`RelayConfig` from a parsed JSON or YAML document."""
    for key in sorted(set(raw) - KNOWN_KEYS):
        log.warning("ignoring unknown configuration key %r", key)
    sources = {
        name: Source(name, spec.get("secret"), dict(spec.get("jwt_issuers") or {}), spec.get("audience"),
                     int(spec.get("tolerance", 300)))
        for name, spec in (raw.get("sources") or {}).items()
    }
    targets = {name: _target(name, spec) for name, spec in (raw.get("targets") or {}).items()}
    rules: list[Rule] = []
    for index, spec in enumerate(raw.get("rules") or []):
        try:
            rule = Rule.from_dict(spec, index)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        unknown = [name for name in rule.targets if name not in targets]
        if unknown:
            raise ConfigError(f"rule {rule.name!r} references unknown target(s): {', '.join(unknown)}")
        rules.append(rule)
    retry_spec = dict(raw.get("retry") or {})
    allowed = {f.name for f in dataclasses.fields(RetryPolicy)}
    if set(retry_spec) - allowed:
        raise ConfigError(f"unknown retry setting(s): {', '.join(sorted(set(retry_spec) - allowed))}")
    plugins = list(raw["plugins"]) if raw.get("plugins") is not None else None
    return RelayConfig(sources, targets, rules, RetryPolicy(**retry_spec), raw.get("proxy"), plugins,
                       raw.get("admin_token"), str(raw.get("base_url") or ""))
