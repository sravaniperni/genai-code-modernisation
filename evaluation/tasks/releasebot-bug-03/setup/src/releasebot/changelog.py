"""Changelog generation: grouping commits into sections and rendering Markdown entries."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from jinja2 import TemplateNotFound

from releasebot.commits import ConventionalCommit
from releasebot.config import DEFAULT_SECTIONS, ProjectConfig, SectionConfig
from releasebot.errors import TemplateNotFoundError
from releasebot.templating import build_environment

if TYPE_CHECKING:
    from releasebot.release import ReleasePlan

CHANGELOG_HEADER = "# Changelog\n"


@dataclass
class ChangelogSection:
    type: str
    title: str
    commits: list[ConventionalCommit] = field(default_factory=list)


def group_commits(
    commits: Iterable[ConventionalCommit], sections: Sequence[SectionConfig] = DEFAULT_SECTIONS
) -> list[ChangelogSection]:
    """Group commits into the configured sections.

    Sections appear in configuration order and only when they contain commits; commits keep the
    order in which they were given. Commit types without a section are left out.
    """
    titles = {section.type: section.title for section in sections}
    grouped: dict[str, ChangelogSection] = {}
    for commit in commits:
        if commit.type in titles:
            grouped.setdefault(commit.type, ChangelogSection(commit.type, titles[commit.type])).commits.append(commit)
    return list(grouped.values())


def render_template(name: str, plan: ReleasePlan, config: ProjectConfig, *, autoescape: bool = False, **extra: Any):
    """Render template ``name`` with the release data of ``plan``."""
    env = build_environment(config.changelog.template_dirs, autoescape=autoescape,
                            scope_aliases=config.changelog.scope_aliases, language=config.changelog.language)
    try:
        template = env.get_template(name)
    except TemplateNotFound as exc:
        raise TemplateNotFoundError(f"template {name!r} not found") from exc
    previous = plan.previous_tag.name if plan.previous_tag else None
    return template.render(
        project=config.project, version=plan.version, tag=plan.tag, previous_version=plan.previous_version,
        date=plan.release_date, sections=plan.sections, breaking=plan.breaking,
        commit_url=config.hosting.commit_url, compare_url=config.hosting.compare_url(previous, plan.tag), **extra,
    )


def render_entry(plan: ReleasePlan, config: ProjectConfig) -> str:
    """The Markdown changelog entry for ``plan`` (heading, breaking changes, sections)."""
    text = render_template(config.changelog.template, plan, config)
    return text.strip() + "\n"


def prepend_entry(existing: str, entry: str) -> str:
    """Insert ``entry`` below the ``# Changelog`` heading so that the newest release comes first."""
    body = existing
    if body.startswith(CHANGELOG_HEADER):
        body = body[len(CHANGELOG_HEADER) :]
    body = body.strip("\n")
    parts = [CHANGELOG_HEADER, entry.strip("\n") + "\n"]
    if body:
        parts.append(body + "\n")
    return "\n".join(parts)
