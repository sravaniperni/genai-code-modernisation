"""Deciding the next version from the conventional commits made since the last release."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from releasebot.commits import ConventionalCommit
from releasebot.versioning import BumpLevel, bump_version, next_prerelease, parse_version


@dataclass(frozen=True)
class BumpRules:
    """Which commit types trigger which bump (configured under ``bump:``)."""

    minor_types: tuple[str, ...] = ("feat",)
    patch_types: tuple[str, ...] = ("fix", "perf")
    prerelease_token: str = "rc"
    # While the major version is 0, breaking changes only bump the minor version (SemVer item 4).
    initial_development_minor: bool = True


def commit_level(commit: ConventionalCommit, rules: BumpRules) -> BumpLevel:
    if commit.breaking:
        return BumpLevel.MAJOR
    if commit.type in rules.minor_types:
        return BumpLevel.MINOR
    if commit.type in rules.patch_types:
        return BumpLevel.PATCH
    return BumpLevel.NONE


def determine_bump(commits: Iterable[ConventionalCommit], rules: BumpRules | None = None) -> BumpLevel:
    """The highest bump level required by any of ``commits``."""
    rules = rules or BumpRules()
    return max((commit_level(commit, rules) for commit in commits), default=BumpLevel.NONE)


def next_version(
    current: str, commits: Sequence[ConventionalCommit], rules: BumpRules | None = None, *,
    prerelease: bool = False, existing: Iterable[str] = (),
) -> str | None:
    """The version after ``current`` (``None`` if nothing needs releasing); with ``prerelease`` the next
    ``<token>.N`` pre-release of that version, numbered after the ones listed in ``existing``."""
    rules = rules or BumpRules()
    level = determine_bump(commits, rules)
    if level is BumpLevel.NONE:
        return None
    if level is BumpLevel.MAJOR and rules.initial_development_minor and parse_version(current).major == 0:
        level = BumpLevel.MINOR
    target = bump_version(current, level)
    return next_prerelease(target, rules.prerelease_token, existing) if prerelease else target
