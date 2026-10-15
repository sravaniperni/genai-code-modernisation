"""Semantic versions (passed around as strings) on top of the ``semver`` package."""

from __future__ import annotations

from collections.abc import Iterable
from enum import IntEnum
from typing import Any

import semver

from releasebot.errors import InvalidVersionError


class BumpLevel(IntEnum):
    NONE, PATCH, MINOR, MAJOR = range(4)


_PARTS = {BumpLevel.MAJOR: "major", BumpLevel.MINOR: "minor", BumpLevel.PATCH: "patch"}


def is_valid(text: object) -> bool:
    """Return True if ``text`` is a valid SemVer 2.0 version string."""
    return isinstance(text, str) and semver.VersionInfo.isvalid(text)


def parse_version(text: str) -> semver.VersionInfo:
    if not is_valid(text):
        raise InvalidVersionError(f"not a semantic version: {text!r}")
    return semver.VersionInfo.parse(text)


def is_prerelease(text: str) -> bool:
    return parse_version(text).prerelease is not None


def compare_versions(left: str, right: str) -> int:
    """Compare by SemVer precedence: negative, zero or positive like ``cmp``."""
    return parse_version(left).compare(parse_version(right))


def _precedence(text: str) -> tuple[int, int, int, str]:
    info = parse_version(text)
    return info.major, info.minor, info.patch, info.prerelease or ""


def sort_versions(versions: Iterable[str]) -> list[str]:
    """Sort version strings by ascending SemVer precedence (build metadata is ignored)."""
    return sorted(versions, key=_precedence)


def bump_version(current: str, level: BumpLevel) -> str:
    """Raise ``current`` by ``level``; a pre-release of the target version is finalised instead."""
    if level is BumpLevel.NONE:
        return current
    return str(parse_version(current).next_version(_PARTS[level]))


def next_prerelease(target: str, token: str, existing: Iterable[str]) -> str:
    """The next ``<token>.N`` pre-release of ``target``: ``("1.3.0", "rc", ["1.3.0-rc.1"])`` gives ``1.3.0-rc.2``."""
    core = parse_version(target).finalize_version()
    infos = {v: parse_version(v) for v in existing if is_valid(v)}
    same_line = [v for v, info in infos.items()
                 if info.finalize_version() == core and str(info.prerelease).startswith(f"{token}.")]
    if not same_line:
        return str(core.replace(prerelease=f"{token}.1"))
    latest = parse_version(sort_versions(same_line)[-1])
    return str(latest.replace(build=None).bump_prerelease(token))


def describe_version(text: str) -> dict[str, Any]:
    """A JSON-serialisable description of ``text`` (used by ``releasebot version --json``)."""
    info = parse_version(text)
    return {**info._asdict(), "version": str(info), "is_prerelease": info.prerelease is not None}
