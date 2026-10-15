"""Routing rules decide which delivery targets receive an event.

Rules are evaluated by descending ``priority``; rules with the same priority are evaluated in the order
they were declared. The first matching rule wins unless it sets ``continue``, in which case evaluation
carries on and the targets of every matching rule are combined (without duplicates, in evaluation order).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from .payloads import Event, header_value

_MISSING = object()


def lookup(data: Mapping[str, Any], path: str) -> Any:
    """Resolve a dotted path such as ``repository.owner.login`` inside nested mappings and lists."""
    current: Any = data
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def _patterns(value: Any) -> tuple[str, ...]:
    if value is None:
        return ("*",)
    return (value,) if isinstance(value, str) else tuple(value)


@dataclass(frozen=True)
class Rule:
    """One routing rule. ``events``/``sources`` are glob patterns, ``headers`` maps header names to glob
    patterns and ``where`` maps dotted payload paths to required values."""

    name: str
    targets: tuple[str, ...]
    events: tuple[str, ...] = ("*",)
    sources: tuple[str, ...] = ("*",)
    headers: tuple[tuple[str, str], ...] = ()
    where: tuple[tuple[str, Any], ...] = ()
    priority: int = 0
    continue_matching: bool = False

    @classmethod
    def from_dict(cls, spec: Mapping[str, Any], index: int = 0) -> Rule:
        targets = spec.get("targets") or ([spec["target"]] if spec.get("target") else [])
        name = str(spec.get("name") or f"rule-{index + 1}")
        if not targets:
            raise ValueError(f"rule {name!r} has no targets")
        headers, where = tuple((spec.get("headers") or {}).items()), tuple((spec.get("where") or {}).items())
        return cls(name, tuple(targets), _patterns(spec.get("events")), _patterns(spec.get("sources")), headers, where,
                   int(spec.get("priority", 0)), bool(spec.get("continue", False)))

    def matches(self, event: Event) -> bool:
        if not any(fnmatchcase(event.type, pattern) for pattern in self.events):
            return False
        if not any(fnmatchcase(event.source, pattern) for pattern in self.sources):
            return False
        for name, pattern in self.headers:
            actual = header_value(event.headers, name)
            if actual is None or not fnmatchcase(actual, pattern):
                return False
        return all(lookup(event.data, path) == expected for path, expected in self.where)


class Router:
    """Evaluates rules in precedence order."""

    def __init__(self, rules: Iterable[Rule]):
        ordered = sorted(enumerate(rules), key=lambda item: (-item[1].priority, item[0]))
        self.rules: list[Rule] = [rule for _, rule in ordered]

    def matching_rules(self, event: Event) -> list[Rule]:
        matched: list[Rule] = []
        for rule in self.rules:
            if rule.matches(event):
                matched.append(rule)
                if not rule.continue_matching:
                    break
        return matched

    def route(self, event: Event) -> list[str]:
        """Names of the targets that should receive ``event``."""
        targets: list[str] = []
        for rule in self.matching_rules(event):
            for name in rule.targets:
                if name not in targets:
                    targets.append(name)
        return targets
