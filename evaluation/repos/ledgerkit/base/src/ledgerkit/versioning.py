"""Version handling: semantic ``formatVersion`` of ledger documents, PEP 440 versions of chart templates.

Templates shipped in 2019 used free-form versions such as ``"2019.4-CH"``; those are still accepted and
always sort before every PEP 440 version.
"""

from __future__ import annotations

from typing import Any, Iterable

import semver
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import LegacyVersion, Version, parse

from ledgerkit.errors import FormatError

FORMAT_VERSION = "1.4.0"


def check_format_version(value: str) -> None:
    """Raise :class:`FormatError` unless documents in format ``value`` can be read by this release."""
    if not isinstance(value, str) or not semver.VersionInfo.isvalid(value):
        raise FormatError(f"invalid format version {value!r}")
    if semver.parse_version_info(value).major != semver.parse_version_info(FORMAT_VERSION).major:
        raise FormatError(f"unsupported format version {value}; this release reads {FORMAT_VERSION[0]}.x")
    if semver.compare(value, FORMAT_VERSION) > 0:
        raise FormatError(f"format version {value} is newer than the supported {FORMAT_VERSION}")


def needs_upgrade(value: str) -> bool:
    """True when a document written in format ``value`` predates the current format."""
    return semver.match(value, "<" + FORMAT_VERSION)


def format_version_info(value: str) -> dict[str, Any]:
    return dict(semver.VersionInfo.parse(value)._asdict())


def is_legacy_version(value: str) -> bool:
    """True for free-form (non PEP 440) template versions such as ``"2019.4-CH"``."""
    return isinstance(parse(value), LegacyVersion)


def latest_template_version(values: Iterable[str]) -> str:
    """Highest template version; legacy versions sort before all PEP 440 versions."""
    keyed: list[tuple[Version | LegacyVersion, str]] = [(parse(v), v) for v in values]
    return max(keyed, key=lambda pair: pair[0])[1]


def satisfies(version: str, requirement: str) -> bool:
    """Whether ``version`` matches a PEP 440 specifier such as ``">=0.8,<2"`` (pre-releases included).

    Legacy versions never satisfy a requirement; an invalid requirement raises :class:`FormatError`.
    """
    try:
        spec = SpecifierSet(requirement)
    except InvalidSpecifier:
        raise FormatError(f"invalid version requirement {requirement!r}") from None
    parsed = parse(version)
    return not isinstance(parsed, LegacyVersion) and spec.contains(parsed, prereleases=True)
