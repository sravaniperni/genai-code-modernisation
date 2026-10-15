"""Chart-of-accounts templates bundled as JSON files in the ``ledgerkit.charts`` package."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from ledgerkit import __version__, versioning
from ledgerkit.accounts import ChartOfAccounts
from ledgerkit.errors import TemplateNotFoundError

PACKAGE = "ledgerkit.charts"


def available_templates() -> list[str]:
    """Names of all bundled templates, sorted."""
    return sorted(name[:-5] for name in resources.contents(PACKAGE) if name.endswith(".json"))


def _read(name: str) -> dict[str, Any]:
    if not resources.is_resource(PACKAGE, f"{name}.json"):
        raise TemplateNotFoundError(f"no chart template named {name!r}")
    return json.loads(resources.read_text(PACKAGE, f"{name}.json", encoding="utf-8"))


def template_info(name: str) -> dict[str, Any]:
    data = _read(name)
    return {**{k: data.get(k, "") for k in ("name", "title", "version", "requires", "description")},
            "accounts": len(data["accounts"])}


def load_template(name: str) -> ChartOfAccounts:
    return ChartOfAccounts.from_list(_read(name)["accounts"])


def is_supported(name: str, ledgerkit_version: str = __version__) -> bool:
    """Whether template ``name`` declares support for the given ledgerkit release."""
    return versioning.satisfies(ledgerkit_version, template_info(name)["requires"] or ">=0")
