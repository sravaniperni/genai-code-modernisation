import importlib.metadata
import logging

import pytest
from click.testing import CliRunner

from releasebot.cli import cli
from releasebot.config import load_config, parse_config, update_version
from releasebot.errors import ConfigError

FULL = """\
# Release configuration for the demo service
project: demo-service   # shown in release titles
version: 2.3.1
tag_prefix: svc/v
publishers:
  - changelog
  - hosting
changelog:
  path: docs/CHANGES.md
  language: de
  sections:
    - {type: feat, title: Neue Funktionen}
    - {type: fix, title: Fehlerbehebungen}
  scope_aliases: &aliases
    api: API
bump:
  patch: [fix, perf, deps]
  prerelease_token: beta
hosting:
  api_url: https://git.example.com/api/v1
  repo: acme/demo-service
  per_page: 50
hooks:
  - make dist VERSION={version}
"""


def test_ruamel_yaml_is_pinned_to_0_18_6():
    assert importlib.metadata.version("ruamel.yaml") == "0.18.6"


def test_configuration_is_parsed(tmp_path):
    path = tmp_path / ".releasebot.yml"
    path.write_text(FULL)
    config = load_config(path)
    assert (config.project, config.version, config.tag_prefix) == ("demo-service", "2.3.1", "svc/v")
    assert config.publishers == ["changelog", "hosting"]
    assert config.changelog.path == "docs/CHANGES.md" and config.changelog.language == "de"
    assert [(s.type, s.title) for s in config.changelog.sections] == [("feat", "Neue Funktionen"), ("fix", "Fehlerbehebungen")]
    assert config.changelog.scope_aliases == {"api": "API"}
    assert config.bump.patch_types == ("fix", "perf", "deps") and config.bump.prerelease_token == "beta"
    assert config.hosting.per_page == 50 and config.hosting.repo == "acme/demo-service"
    assert config.hooks == ["make dist VERSION={version}"]
    assert config.path == path


def test_invalid_configuration_files(tmp_path, caplog):
    for text in ["project: [unterminated\n", "- just\n- a list\n", "project: x\nversion: 1.0\n", ""]:
        with pytest.raises(ConfigError):
            parse_config(text)
    with caplog.at_level(logging.WARNING, logger="releasebot.config"):
        parse_config("project: x\ncolour: blue\n")
    assert "colour" in caplog.text


def test_update_version_keeps_the_file_layout(tmp_path):
    path = tmp_path / ".releasebot.yml"
    path.write_text(FULL)
    update_version(path, "2.4.0")
    text = path.read_text()
    assert text.startswith("# Release configuration for the demo service\n")
    assert "version: 2.4.0\n" in text
    assert "{type: feat, title: Neue Funktionen}" in text  # flow style is kept
    assert "project: demo-service   # shown in release titles" in text
    assert text.index("project:") < text.index("version:") < text.index("tag_prefix:") < text.index("hosting:")
    reloaded = load_config(path)
    assert reloaded.version == "2.4.0"
    assert reloaded.changelog.scope_aliases == {"api": "API"} and reloaded.hosting.per_page == 50
    with pytest.raises(ConfigError):
        update_version(path, "2.4")
    assert load_config(path).version == "2.4.0"


def test_publish_records_the_released_version(project):
    argv = ["--config", str(project / ".releasebot.yml"), "publish", "--publisher", "changelog", "--workdir", str(project),
            "--log", str(project / "log.json"), "--tags", str(project / "tags.json")]
    result = CliRunner().invoke(cli, argv, prog_name="releasebot")
    assert result.exit_code == 0, result.output
    text = (project / ".releasebot.yml").read_text()
    assert "version: 1.5.0" in text and text.startswith("# releasebot configuration (acceptance)\n")
    assert load_config(project / ".releasebot.yml").version == "1.5.0"
