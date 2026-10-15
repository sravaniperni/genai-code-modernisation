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
    entries = resources.files(PACKAGE).iterdir()
    return sorted(entry.name[:-5] for entry in entries if entry.name.endswith(".json") and entry.is_file())


def _read(name: str) -> dict[str, Any]:
    resource = resources.files(PACKAGE).joinpath(f"{name}.json")
    if "/" in name or not resource.is_file():
        raise TemplateNotFoundError(f"no chart template named {name!r}")
    return json.loads(resource.read_text(encoding="utf-8"))


def template_info(name: str) -> dict[str, Any]:
    data = _read(name)
    return {**{k: data.get(k, "") for k in ("name", "title", "version", "requires", "description")},
            "accounts": len(data["accounts"])}


def load_template(name: str) -> ChartOfAccounts:
    return ChartOfAccounts.from_list(_read(name)["accounts"])


def is_supported(name: str, ledgerkit_version: str = __version__) -> bool:
    """Whether template ``name`` declares support for the given ledgerkit release."""
    return versioning.satisfies(ledgerkit_version, template_info(name)["requires"] or ">=0")
