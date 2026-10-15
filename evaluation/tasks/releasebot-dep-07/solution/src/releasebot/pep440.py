"""PEP 440 versions for Python projects that publish their releases to a package index."""

from __future__ import annotations

import re
from collections.abc import Iterable

from packaging.version import InvalidVersion, Version

from releasebot.errors import InvalidVersionError, PublishError
from releasebot.versioning import parse_version

PRERELEASE_LABELS = {"alpha": "a", "a": "a", "beta": "b", "b": "b", "rc": "rc", "c": "rc", "dev": ".dev"}


def to_pep440(semver_text: str) -> str:
    """Convert a SemVer version to normalised PEP 440 (``1.2.0-rc.1`` becomes ``1.2.0rc1``)."""
    info = parse_version(semver_text)
    result = f"{info.major}.{info.minor}.{info.patch}"
    if info.prerelease:
        label, _, number = info.prerelease.partition(".")
        number = number or "0"
        if label.lower() not in PRERELEASE_LABELS or not number.isdigit():
            raise InvalidVersionError(f"pre-release {info.prerelease!r} has no PEP 440 equivalent")
        result += f"{PRERELEASE_LABELS[label.lower()]}{int(number)}"
    if info.build:
        result += "+" + re.sub(r"[^A-Za-z0-9.]", ".", info.build)
    return str(Version(result))


def published_versions(raw: Iterable[str]) -> list[Version]:
    """Versions listed by the package index, sorted ascending; non-PEP 440 entries are skipped."""
    versions: set[Version] = set()
    for text in raw:
        try:
            versions.add(Version(str(text).strip()))
        except InvalidVersion:
            continue
    return sorted(versions)


def check_publishable(semver_text: str, published: Iterable[str]) -> str:
    """Return the PEP 440 version to upload, or raise :class:`PublishError` if it cannot be published.

    A version cannot be published if an equivalent version (``1.2`` equals ``1.2.0``) is already on
    the index, or if a final release would be older than the newest final release on the index.
    """
    candidate, versions = Version(to_pep440(semver_text)), published_versions(published)
    if candidate in versions:
        raise PublishError(f"{candidate} is already published")
    newest = max((v for v in versions if not v.is_prerelease), default=None)
    if newest is not None and not candidate.is_prerelease and candidate < newest:
        raise PublishError(f"{candidate} is older than the latest published release {newest}")
    return str(candidate)
