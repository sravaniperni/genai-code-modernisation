"""Project configuration stored in ``.releasebot.yml`` (see README for an example)."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import ruamel.yaml
from ruamel.yaml import YAML

from releasebot.bumping import BumpRules
from releasebot.errors import ConfigError
from releasebot.versioning import is_valid

log = logging.getLogger(__name__)

DEFAULT_FILENAME = ".releasebot.yml"


@dataclass(frozen=True)
class SectionConfig:
    type: str
    title: str


DEFAULT_SECTIONS = tuple(SectionConfig(t, title) for t, title in (
    ("feat", "Features"), ("fix", "Bug Fixes"), ("perf", "Performance Improvements"), ("revert", "Reverts")))


@dataclass
class ChangelogConfig:
    path: str = "CHANGELOG.md"
    template: str = "changelog.md.j2"
    template_dirs: list[str] = field(default_factory=list)
    sections: tuple[SectionConfig, ...] = DEFAULT_SECTIONS
    scope_aliases: dict[str, str] = field(default_factory=dict)
    language: str | None = None  # None: follow the user's locale


@dataclass
class HostingConfig:
    api_url: str | None = None
    web_url: str | None = None  # e.g. https://git.example.com/acme/demo
    repo: str | None = None  # owner/name
    token_env: str = "RELEASEBOT_TOKEN"
    proxy: str | None = None
    per_page: int = 100

    def _web(self, suffix: str) -> str | None:
        return f"{self.web_url.rstrip('/')}/{suffix}" if self.web_url else None

    commit_url = property(lambda self: self._web("commit/{sha}"))
    issue_url = property(lambda self: self._web("issues/{}"))

    @property
    def user_url(self) -> str | None:
        parts = urlsplit(self.web_url or "")
        return f"{parts.scheme}://{parts.netloc}/{{}}" if self.web_url else None

    def compare_url(self, previous_tag: str | None, tag: str) -> str | None:
        return self._web(f"compare/{previous_tag}...{tag}") if previous_tag else None


@dataclass
class ProjectConfig:
    project: str
    version: str  # the last released version
    tag_prefix: str = "v"
    changelog: ChangelogConfig = field(default_factory=ChangelogConfig)
    bump: BumpRules = field(default_factory=BumpRules)
    hosting: HostingConfig = field(default_factory=HostingConfig)
    publishers: list[str] = field(default_factory=lambda: ["changelog"])
    hooks: list[str] = field(default_factory=list)  # shell commands run by the "hooks" publisher
    path: Path | None = None


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a mapping")
    return dict(value)


def _strings(value: Any, key: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"'{key}' must be a list of strings")
    return list(value)


def _warn_unknown(data: dict[str, Any], known: set[str], prefix: str = "") -> None:
    for key in sorted(set(map(str, data)) - known):
        log.warning("ignoring unknown configuration key %r", prefix + key)


def _changelog(data: dict[str, Any]) -> ChangelogConfig:
    _warn_unknown(data, {"path", "template", "template_dirs", "sections", "scope_aliases", "language"}, "changelog.")
    sections = DEFAULT_SECTIONS
    if data.get("sections") is not None:
        raw = data["sections"]
        if not isinstance(raw, list) or not all(isinstance(item, dict) and item.get("type") for item in raw):
            raise ConfigError("'changelog.sections' must be a list of {type, title} mappings")
        sections = tuple(SectionConfig(str(item["type"]), str(item.get("title") or item["type"])) for item in raw)
    return ChangelogConfig(
        str(data.get("path", "CHANGELOG.md")), str(data.get("template", "changelog.md.j2")),
        _strings(data.get("template_dirs", []), "changelog.template_dirs"), sections,
        {str(k): str(v) for k, v in _mapping(data, "scope_aliases").items()},
        str(data["language"]) if data.get("language") else None,
    )


def _bump(data: dict[str, Any]) -> BumpRules:
    _warn_unknown(data, {"minor", "patch", "prerelease_token", "initial_development_minor"}, "bump.")
    defaults = BumpRules()
    return BumpRules(
        tuple(_strings(data.get("minor", defaults.minor_types), "bump.minor")),
        tuple(_strings(data.get("patch", defaults.patch_types), "bump.patch")),
        str(data.get("prerelease_token", defaults.prerelease_token)),
        bool(data.get("initial_development_minor", True)),
    )


def _hosting(data: dict[str, Any]) -> HostingConfig:
    _warn_unknown(data, {"api_url", "web_url", "repo", "token_env", "proxy", "per_page"}, "hosting.")
    per_page = data.get("per_page", 100)
    if not isinstance(per_page, int) or isinstance(per_page, bool) or per_page < 1:
        raise ConfigError("'hosting.per_page' must be a positive integer")
    return HostingConfig(data.get("api_url"), data.get("web_url"), data.get("repo"),
                         str(data.get("token_env", "RELEASEBOT_TOKEN")), data.get("proxy"), per_page)


def parse_config(text: str, *, path: Path | None = None) -> ProjectConfig:
    """Build a :class:`ProjectConfig` from YAML text."""
    try:
        data = YAML(typ="safe", pure=True).load(text)
    except ruamel.yaml.YAMLError as exc:
        raise ConfigError(f"{path or 'configuration'} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("the configuration must be a mapping")
    _warn_unknown(data, {"project", "version", "tag_prefix", "changelog", "bump", "hosting", "publishers", "hooks"})
    if not data.get("project"):
        raise ConfigError("'project' is required")
    version = str(data.get("version", "0.1.0"))
    if not is_valid(version):
        raise ConfigError(f"'version' must be a semantic version, got {version!r}")
    return ProjectConfig(
        project=str(data["project"]),
        version=version,
        tag_prefix=str(data.get("tag_prefix", "v")),
        changelog=_changelog(_mapping(data, "changelog")),
        bump=_bump(_mapping(data, "bump")),
        hosting=_hosting(_mapping(data, "hosting")),
        publishers=_strings(data.get("publishers", ["changelog"]), "publishers"),
        hooks=_strings(data.get("hooks") or [], "hooks"),
        path=path,
    )


def load_config(path: str | Path) -> ProjectConfig:
    try:
        return parse_config(Path(path).read_text(encoding="utf-8"), path=Path(path))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {path}") from exc


def update_version(path: str | Path, new_version: str) -> None:
    """Rewrite the ``version`` key of a configuration file, keeping comments and layout."""
    if not is_valid(new_version):
        raise ConfigError(f"not a semantic version: {new_version!r}")
    path = Path(path)
    yaml = YAML()
    data = yaml.load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a configuration mapping")
    data["version"] = new_version
    buffer = io.StringIO()
    yaml.dump(data, buffer)
    path.write_text(buffer.getvalue(), encoding="utf-8")
