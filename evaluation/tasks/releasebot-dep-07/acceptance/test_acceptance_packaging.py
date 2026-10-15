import importlib.metadata
import json

import pytest
from click.testing import CliRunner

from releasebot.cli import cli
from releasebot.errors import InvalidVersionError, PublishError
from releasebot.pep440 import check_publishable, published_versions, to_pep440

INDEX = ["1.0.0", "2019-snapshot", "1.4.2", "latest", "1.10.0rc1", "nightly-20260101", "1.2", " 1.3.0 ", "1.2.0", "0.9.post1"]


def test_packaging_is_pinned_to_24_2():
    assert importlib.metadata.version("packaging") == "24.2"


def test_non_pep440_entries_are_ignored():
    assert [str(v) for v in published_versions(INDEX)] == ["0.9.post1", "1.0.0", "1.2", "1.3.0", "1.4.2", "1.10.0rc1"]
    assert published_versions(["release-candidate", "final"]) == []


def test_conversion_to_pep440():
    assert to_pep440("1.5.0-rc.2") == "1.5.0rc2"
    assert to_pep440("2.0.0-alpha.1") == "2.0.0a1"
    assert to_pep440("2.0.0-dev.3") == "2.0.0.dev3"
    assert to_pep440("2.0.0+linux.x86-64") == "2.0.0+linux.x86.64"
    with pytest.raises(InvalidVersionError):
        to_pep440("2.0.0-snapshot.1")


def test_publishable_checks():
    assert check_publishable("1.5.0", INDEX) == "1.5.0"
    assert check_publishable("1.10.0-rc.2", INDEX) == "1.10.0rc2"
    assert check_publishable("1.4.3-beta.1", INDEX) == "1.4.3b1"
    with pytest.raises(PublishError, match="already published"):
        check_publishable("1.2.0", INDEX)
    with pytest.raises(PublishError, match="older"):
        check_publishable("1.4.1", INDEX)


def test_check_index_command(project):
    published = project / "published.json"
    base = ["--config", str(project / ".releasebot.yml"), "check-index", "--published", str(published),
            "--log", str(project / "log.json"), "--tags", str(project / "tags.json")]
    published.write_text(json.dumps(INDEX))
    result = CliRunner().invoke(cli, base, prog_name="releasebot")
    assert result.exit_code == 0, result.output
    assert "1.5.0 can be published" in result.output

    published.write_text(json.dumps([*INDEX, "1.5", "unreleased"]))
    result = CliRunner().invoke(cli, base, prog_name="releasebot")
    assert result.exit_code == 1 and "already published" in result.output
