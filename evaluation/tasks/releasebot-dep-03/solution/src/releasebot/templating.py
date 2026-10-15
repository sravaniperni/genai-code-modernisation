"""Templates (``changelog.template_dirs`` first, then the bundled ones) and the Jinja2 environment."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any

from jinja2 import Environment, FunctionLoader, StrictUndefined, pass_context, pass_environment

from releasebot.dates import format_release_date
from releasebot.errors import TemplateNotFoundError

BUNDLE_PACKAGE = "releasebot.templates"


def _check_name(name: str) -> None:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise TemplateNotFoundError(f"invalid template name {name!r}")


def list_bundled_templates() -> list[str]:
    """Names of the templates shipped with releasebot."""
    root = resources.files(BUNDLE_PACKAGE)
    return sorted(entry.name for entry in root.iterdir() if entry.name.endswith(".j2"))


def load_template_source(name: str, search_paths: Iterable[str | Path] = ()) -> str:
    """Return the source of template ``name`` (user directories win over bundled templates)."""
    _check_name(name)
    for directory in search_paths:
        candidate = Path(directory) / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    resource = resources.files(BUNDLE_PACKAGE).joinpath(name)
    if not resource.is_file():
        raise TemplateNotFoundError(f"template {name!r} not found")
    return resource.read_text(encoding="utf-8")


@pass_context
def _commit_link(context: Any, sha: str) -> str:
    """``{{ commit.sha | commit_link }}``: a Markdown link when the template knows ``commit_url``."""
    template = context.get("commit_url")
    return f"[{sha[:7]}]({template.format(sha=sha)})" if template else sha[:7]


@pass_environment
def _scope_label(environment: Environment, scope: str | None) -> str:
    """``{{ commit.scope | scope_label }}``: apply ``changelog.scope_aliases``."""
    return environment.globals.get("scope_aliases", {}).get(scope, scope) if scope else ""


def build_environment(
    search_paths: Iterable[str | Path] = (), *, autoescape: bool = False,
    scope_aliases: Mapping[str, str] | None = None, language: str | None = None,
) -> Environment:
    paths = [Path(p) for p in search_paths]

    def load(name: str) -> str | None:
        try:
            return load_template_source(name, paths)
        except TemplateNotFoundError:
            return None  # Jinja2 raises its own TemplateNotFound

    env = Environment(loader=FunctionLoader(load), autoescape=autoescape, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.globals["scope_aliases"] = dict(scope_aliases or {})
    env.filters["commit_link"] = _commit_link
    env.filters["scope_label"] = _scope_label
    env.filters["release_date"] = lambda value: format_release_date(value, language=language)
    return env
