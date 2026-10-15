"""Release tags as plain data (exported from git by the caller) and helpers relating them to versions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from releasebot.commits import Commit
from releasebot.errors import ReleasebotError
from releasebot.versioning import is_prerelease, is_valid, parse_version, sort_versions


@dataclass(frozen=True)
class Tag:
    name: str
    sha: str
    timestamp: int = 0

    @property
    def date(self) -> datetime:
        """Tag creation time in UTC."""
        return datetime.fromtimestamp(self.timestamp, tz=UTC)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Tag:
        return cls(str(data["name"]), str(data["sha"]), int(data.get("timestamp", 0)))


@dataclass(frozen=True)
class ReleaseTag:
    tag: Tag
    version: str


def version_from_tag(name: str, prefix: str = "v") -> str | None:
    """The version encoded in release tag ``name`` (monorepos use prefixes like ``api/v``), else ``None``."""
    if not name.startswith(prefix):
        return None
    candidate = name[len(prefix) :]
    return candidate if is_valid(candidate) else None


def tag_name(version: str, prefix: str = "v") -> str:
    return f"{prefix}{parse_version(version)}"


def release_tags(tags: Iterable[Tag], prefix: str = "v") -> list[ReleaseTag]:
    """Release tags in ascending version order; the first tag wins for duplicate versions."""
    found: dict[str, ReleaseTag] = {}
    for tag in tags:
        version = version_from_tag(tag.name, prefix)
        if version is not None and version not in found:
            found[version] = ReleaseTag(tag, version)
    return [found[version] for version in sort_versions(found)]


def latest_release(tags: Iterable[Tag], prefix: str = "v", *, include_prereleases: bool = True) -> ReleaseTag | None:
    candidates = [rt for rt in release_tags(tags, prefix) if include_prereleases or not is_prerelease(rt.version)]
    return candidates[-1] if candidates else None


def commits_since(log: Sequence[Commit], tag: Tag | None) -> list[Commit]:
    """Commits made after ``tag``; ``log`` is newest-first like ``git log``."""
    if tag is None:
        return list(log)
    newer: list[Commit] = []
    for commit in log:
        if commit.sha == tag.sha:
            return newer
        newer.append(commit)
    raise ReleasebotError(f"tag {tag.name} points to {tag.sha[:7]}, which is not part of the commit log")
