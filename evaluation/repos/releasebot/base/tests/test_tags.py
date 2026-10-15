import pytest

from releasebot.commits import Commit
from releasebot.errors import InvalidVersionError, ReleasebotError
from releasebot.tags import Tag, commits_since, latest_release, release_tags, tag_name, version_from_tag


def test_version_from_tag():
    assert version_from_tag("v1.2.3") == "1.2.3"
    assert version_from_tag("v2.0.0-rc.1") == "2.0.0-rc.1"
    assert version_from_tag("1.2.3") is None
    assert version_from_tag("latest") is None
    assert version_from_tag("v1.2") is None


def test_custom_prefixes():
    assert version_from_tag("api/v1.2.0", "api/v") == "1.2.0"
    assert version_from_tag("1.2.0", "") == "1.2.0"
    assert tag_name("1.2.0", "api/v") == "api/v1.2.0"
    with pytest.raises(InvalidVersionError):
        tag_name("1.2", "v")


def test_release_tags_are_sorted_and_deduplicated(tags):
    found = release_tags([*tags, Tag("nightly", "f" * 40), Tag("v1.4.1", "e" * 40)])
    assert [rt.version for rt in found] == ["1.4.0", "1.4.1", "1.4.2"]
    assert found[1].tag.sha != "e" * 40
    assert latest_release(tags).tag.name == "v1.4.2"
    assert latest_release([]) is None


def test_commits_since(log, tags):
    newer = commits_since(log, Tag("v1.4.2", log[-1].sha))
    assert newer == log[:-1]
    assert commits_since(log, None) == log
    with pytest.raises(ReleasebotError):
        commits_since([Commit("a" * 40, "feat: x")], Tag("v9.9.9", "b" * 40))
