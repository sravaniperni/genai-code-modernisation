import importlib.metadata
import json

import pytest
from click.testing import CliRunner

from releasebot.cli import cli
from releasebot.config import parse_config
from releasebot.errors import ConfigError, InvalidVersionError
from releasebot.tags import Tag, latest_release, version_from_tag
from releasebot.versioning import BumpLevel, bump_version, describe_version, is_valid, next_prerelease, parse_version, sort_versions


def test_semver_is_pinned_to_3_0_4():
    assert importlib.metadata.version("semver") == "3.0.4"


def test_validation():
    for good in ["0.0.0", "1.2.3", "10.20.30-rc.1+build.7", "1.0.0-alpha-beta"]:
        assert is_valid(good), good
    for bad in ["1.2", "v1.2.3", "01.2.3", "1.2.3-", "", None, 123]:
        assert not is_valid(bad), bad
    with pytest.raises(InvalidVersionError):
        parse_version("1.2")


def test_tags_and_configuration_use_validation():
    assert version_from_tag("v2.0.0-rc.1") == "2.0.0-rc.1"
    assert version_from_tag("v2.0") is None
    tags = [Tag("v1.9.0", "a" * 40), Tag("v1.10.0", "b" * 40), Tag("vnext", "c" * 40)]
    assert latest_release(tags).version == "1.10.0"
    assert parse_config("project: x\nversion: 3.1.4\n").version == "3.1.4"
    with pytest.raises(ConfigError):
        parse_config("project: x\nversion: 3.1\n")


def test_version_arithmetic():
    assert sort_versions(["1.10.0", "1.2.0", "1.2.0-rc.1"]) == ["1.2.0-rc.1", "1.2.0", "1.10.0"]
    assert bump_version("1.4.2", BumpLevel.MAJOR) == "2.0.0"
    assert bump_version("1.5.0-rc.3", BumpLevel.MINOR) == "1.5.0"
    assert next_prerelease("1.5.0", "rc", ["1.5.0-rc.1", "1.5.0-rc.2+build.9"]) == "1.5.0-rc.3"


def test_describe_version():
    assert describe_version("2.1.0-beta.2+exp.sha.5114f85") == {
        "major": 2, "minor": 1, "patch": 0, "prerelease": "beta.2", "build": "exp.sha.5114f85",
        "version": "2.1.0-beta.2+exp.sha.5114f85", "is_prerelease": True,
    }
    assert json.loads(json.dumps(describe_version("1.0.0")))["is_prerelease"] is False


def test_next_json_output(project):
    argv = ["--config", str(project / ".releasebot.yml"), "--json", "next",
            "--log", str(project / "log.json"), "--tags", str(project / "tags.json")]
    result = CliRunner().invoke(cli, argv, prog_name="releasebot")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["version"] == "1.5.0"
    assert data["semver"] == {"major": 1, "minor": 5, "patch": 0, "prerelease": None, "build": None,
                              "version": "1.5.0", "is_prerelease": False}
