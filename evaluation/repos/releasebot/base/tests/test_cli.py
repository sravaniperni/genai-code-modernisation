import json

from click.testing import CliRunner

from releasebot.cli import cli
from releasebot.config import load_config


def invoke(project, *args):
    history = ["--log", str(project / "log.json"), "--tags", str(project / "tags.json")]
    command, *rest = args
    argv = ["--config", str(project / ".releasebot.yml"), *[a for a in rest if a == "--json"], command]
    return CliRunner().invoke(cli, [*argv, *history, *[a for a in rest if a != "--json"]], prog_name="releasebot")


def test_next(project):
    result = invoke(project, "next")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "1.5.0"


def test_json_output(project):
    result = invoke(project, "next", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["release"] is True and data["version"] == "1.5.0" and data["semver"]["minor"] == 5


def test_changelog_command(project):
    result = invoke(project, "changelog")
    assert result.exit_code == 0, result.output
    assert "### Features" in result.output


def test_publish_records_the_new_version(project):
    result = invoke(project, "publish", "--publisher", "changelog", "--workdir", str(project))
    assert result.exit_code == 0, result.output
    assert "changelog:" in result.output
    assert "## [1.5.0]" in (project / "CHANGELOG.md").read_text()
    assert load_config(project / ".releasebot.yml").version == "1.5.0"


def test_check_index(project):
    (project / "published.json").write_text(json.dumps(["1.4.2", "1.5.0"]))
    result = invoke(project, "check-index", "--published", str(project / "published.json"))
    assert result.exit_code == 1
    assert "already published" in result.output


def test_publishers_command(project):
    result = CliRunner().invoke(cli, ["publishers"])
    assert result.exit_code == 0, result.output
    assert "changelog" in result.output and "built-in" in result.output


def test_missing_configuration_is_reported(tmp_path):
    (tmp_path / "log.json").write_text("[]")
    result = CliRunner().invoke(cli, ["--config", str(tmp_path / "nope.yml"), "next", "--log", str(tmp_path / "log.json")])
    assert result.exit_code == 1
    assert "not found" in result.output
