"""Release planning: from the commit log and existing tags to the next release."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from releasebot.bumping import determine_bump, next_version
from releasebot.changelog import ChangelogSection, group_commits
from releasebot.commits import Commit, ConventionalCommit, parse_log
from releasebot.config import ProjectConfig
from releasebot.tags import Tag, commits_since, latest_release, release_tags, tag_name
from releasebot.versioning import BumpLevel


def utc_now() -> datetime:
    """The current time as an aware UTC datetime."""
    return datetime.now(UTC)


def format_timestamp(value: datetime) -> str:
    """Timestamps in release manifests look like ``2026-01-31T09:15:00Z``."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ReleasePlan:
    project: str
    version: str
    tag: str
    level: BumpLevel
    previous_version: str | None
    previous_tag: Tag | None
    commits: list[ConventionalCommit] = field(default_factory=list)
    sections: list[ChangelogSection] = field(default_factory=list)
    breaking: list[ConventionalCommit] = field(default_factory=list)
    prerelease: bool = False
    created_at: datetime = field(default_factory=utc_now)

    @property
    def release_date(self) -> date:
        return self.created_at.date()

    @property
    def days_since_previous(self) -> int | None:
        return (self.created_at - self.previous_tag.date).days if self.previous_tag else None

    def variables(self) -> dict[str, str]:
        """Placeholders available to hook commands."""
        return {"project": self.project, "version": self.version, "tag": self.tag,
                "previous_version": self.previous_version or "", "date": self.release_date.isoformat()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project, "version": self.version, "tag": self.tag, "level": self.level.name.lower(),
            "previous_version": self.previous_version, "previous_tag": getattr(self.previous_tag, "name", None),
            "prerelease": self.prerelease, "created_at": format_timestamp(self.created_at),
            "days_since_previous": self.days_since_previous, "commits": [commit.sha for commit in self.commits],
            "breaking": [commit.breaking_description for commit in self.breaking],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def plan_release(
    config: ProjectConfig, log: Sequence[Commit], tags: Sequence[Tag], *, prerelease: bool = False,
    now: datetime | None = None,
) -> ReleasePlan | None:
    """Plan the next release, or return ``None`` when no commit since the last release needs one.

    Without any release tag the configured ``version`` is taken as the last released version.
    """
    latest = latest_release(tags, config.tag_prefix)
    current = latest.version if latest else config.version
    commits = parse_log(commits_since(log, latest.tag if latest else None))
    existing = [release.version for release in release_tags(tags, config.tag_prefix)]
    version = next_version(current, commits, config.bump, prerelease=prerelease, existing=existing)
    if version is None:
        return None
    return ReleasePlan(
        config.project, version, tag_name(version, config.tag_prefix), determine_bump(commits, config.bump),
        previous_version=current, previous_tag=latest.tag if latest else None, commits=commits,
        sections=group_commits(commits, config.changelog.sections), breaking=[c for c in commits if c.breaking],
        prerelease=prerelease, created_at=now or utc_now(),
    )
