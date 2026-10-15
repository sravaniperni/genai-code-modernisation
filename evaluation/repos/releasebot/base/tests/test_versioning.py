import pytest

from releasebot.errors import InvalidVersionError
from releasebot.versioning import BumpLevel, bump_version, describe_version, is_valid, next_prerelease, parse_version, sort_versions


def test_validation():
    assert is_valid("1.2.3") and is_valid("1.2.3-rc.1+build.5")
    assert not is_valid("1.2") and not is_valid("v1.2.3") and not is_valid(None)
    with pytest.raises(InvalidVersionError):
        parse_version("one.two.three")


def test_sort_versions_is_numeric():
    assert sort_versions(["1.10.0", "1.2.0", "1.9.3", "0.9.0"]) == ["0.9.0", "1.2.0", "1.9.3", "1.10.0"]


def test_bump_version():
    assert bump_version("1.4.2", BumpLevel.MAJOR) == "2.0.0"
    assert bump_version("1.4.2", BumpLevel.MINOR) == "1.5.0"
    assert bump_version("1.4.2", BumpLevel.PATCH) == "1.4.3"
    assert bump_version("1.4.2", BumpLevel.NONE) == "1.4.2"
    assert bump_version("1.5.0-rc.2", BumpLevel.MINOR) == "1.5.0"  # a pre-release of the target is finalised


def test_next_prerelease_numbering():
    assert next_prerelease("1.5.0", "rc", []) == "1.5.0-rc.1"
    assert next_prerelease("1.5.0", "rc", ["1.5.0-rc.1", "1.5.0-rc.2", "1.4.0-rc.7", "1.5.0-beta.4"]) == "1.5.0-rc.3"
    assert next_prerelease("1.5.0", "beta", ["1.5.0-rc.1", "1.5.0-beta.4"]) == "1.5.0-beta.5"


def test_describe_version():
    info = describe_version("2.0.0-rc.1")
    assert info["major"] == 2 and info["prerelease"] == "rc.1"
    assert info["version"] == "2.0.0-rc.1"
    assert info["is_prerelease"] is True
