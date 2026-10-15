import logging

import pytest

from releasebot.config import DEFAULT_SECTIONS, load_config, parse_config, update_version
from releasebot.errors import ConfigError


def test_parse_full_configuration(config):
    assert (config.project, config.version, config.tag_prefix) == ("demo", "1.4.2", "v")
    assert config.changelog.sections == DEFAULT_SECTIONS
    assert config.changelog.scope_aliases == {"api": "API"}
    assert config.hosting.per_page == 2
    assert config.hosting.issue_url.format(7) == "https://git.example.com/acme/demo/issues/7"
    assert config.hosting.user_url.format("alice") == "https://git.example.com/alice"
    assert config.bump.minor_types == ("feat",)


def test_defaults_and_custom_sections():
    config = parse_config(
        "project: x\nhooks: make dist\nbump:\n  patch: [fix, deps]\nchangelog:\n  sections:\n    - {type: fix, title: Fixes}\n"
    )
    assert config.version == "0.1.0"
    assert config.publishers == ["changelog"]
    assert config.hooks == ["make dist"]
    assert config.bump.patch_types == ("fix", "deps")
    assert [(s.type, s.title) for s in config.changelog.sections] == [("fix", "Fixes")]


def test_invalid_configurations(tmp_path):
    invalid = ["version: 1.0.0\n", "project: x\nversion: 1.0\n", "project: x\nhosting:\n  per_page: 0\n", "- a\n", "project: [x\n"]
    for text in invalid:
        with pytest.raises(ConfigError):
            parse_config(text)
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yml")


def test_unknown_keys_are_reported(caplog):
    with caplog.at_level(logging.WARNING, logger="releasebot.config"):
        parse_config("project: x\nchangelog:\n  colour: red\n")
    assert "changelog.colour" in caplog.text


def test_update_version_keeps_comments(project):
    path = project / ".releasebot.yml"
    update_version(path, "1.5.0")
    text = path.read_text()
    assert text.startswith("# releasebot configuration used by the test-suite\n")
    assert "tag_prefix: v" in text
    assert load_config(path).version == "1.5.0"
    with pytest.raises(ConfigError):
        update_version(path, "1.5")
