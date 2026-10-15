import importlib.metadata
import json

from click.testing import CliRunner

from releasebot.cli import cli


def invoke(project, *args, env=None):
    argv = ["--config", str(project / ".releasebot.yml"), *args]
    return CliRunner().invoke(cli, argv, prog_name="releasebot", env=env)


def history(project):
    return ["--log", str(project / "log.json"), "--tags", str(project / "tags.json")]


def complete(words, cword):
    env = {"_RELEASEBOT_COMPLETE": "bash_complete", "COMP_WORDS": words, "COMP_CWORD": str(cword)}
    result = CliRunner().invoke(cli, [], prog_name="releasebot", env=env)
    return [line.split(",", 1)[1] for line in result.output.splitlines() if "," in line]


def test_click_is_pinned_to_8_1_8():
    assert importlib.metadata.version("click") == "8.1.8"


def test_help_lists_all_commands():
    result = CliRunner().invoke(cli, ["--help"], prog_name="releasebot")
    assert result.exit_code == 0, result.output
    for command in ("next", "changelog", "check-index", "publish", "publishers"):
        assert command in result.output


def test_text_and_json_output(project):
    text = invoke(project, "next", *history(project))
    assert text.exit_code == 0, text.output
    assert text.output.strip() == "1.5.0"

    result = invoke(project, "--json", "next", *history(project))
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["release"] is True and data["version"] == "1.5.0" and data["tag"] == "v1.5.0"

    result = invoke(project, "--json", "changelog", *history(project))
    assert result.exit_code == 0, result.output
    assert "### Features" in json.loads(result.output)["changelog"]


def test_publisher_names_complete_in_the_shell():
    assert complete("releasebot publish --publisher ch", 3) == ["changelog"]
    assert complete("releasebot publish --publisher ho", 3) == ["hooks", "hosting"]
    assert {"bundle", "changelog", "hooks", "hosting", "notes"} <= set(complete("releasebot publish --publisher", 3))


def test_publishers_listing_fits_the_terminal():
    narrow = CliRunner().invoke(cli, ["publishers"], env={"COLUMNS": "30"})
    assert narrow.exit_code == 0, narrow.output
    lines = narrow.output.splitlines()
    assert len(lines) >= 5 and all(len(line) <= 30 for line in lines)
    assert lines[0].startswith("bundle")

    wide = CliRunner().invoke(cli, ["publishers"], env={"COLUMNS": "200"})
    assert "Prepend the release entry to the changelog file" in wide.output


def test_errors_are_reported(project):
    result = CliRunner().invoke(cli, ["--config", str(project / "missing.yml"), "next", *history(project)])
    assert result.exit_code == 1
    assert "not found" in result.output
