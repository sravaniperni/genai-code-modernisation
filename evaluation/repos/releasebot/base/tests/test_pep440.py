import pytest

from releasebot.errors import InvalidVersionError, PublishError
from releasebot.pep440 import check_publishable, published_versions, to_pep440


def test_to_pep440():
    cases = {"1.2.0": "1.2.0", "1.2.0-rc.1": "1.2.0rc1", "1.2.0-alpha.3": "1.2.0a3", "2.0.0-beta": "2.0.0b0",
             "1.2.0-dev.4": "1.2.0.dev4", "1.2.0+build.7": "1.2.0+build.7"}
    assert {semver: to_pep440(semver) for semver in cases} == cases
    with pytest.raises(InvalidVersionError):
        to_pep440("1.2.0-preview.1")


def test_published_versions_are_parsed_and_sorted():
    versions = published_versions(["1.10.0", "1.2.0", "1.2.0rc1", "1.2", "0.9"])
    assert [str(v) for v in versions] == ["0.9", "1.2.0rc1", "1.2.0", "1.10.0"]


def test_check_publishable():
    assert check_publishable("1.5.0-rc.1", ["1.4.2", "1.5.0rc0"]) == "1.5.0rc1"
    with pytest.raises(PublishError, match="already published"):
        check_publishable("1.4.0", ["1.4", "1.3.9"])
    with pytest.raises(PublishError, match="older"):
        check_publishable("1.3.0", ["1.4.2"])
