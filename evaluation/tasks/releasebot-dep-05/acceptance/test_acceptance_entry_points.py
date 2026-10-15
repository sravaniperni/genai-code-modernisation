import importlib.metadata
import logging

import pytest
from click.testing import CliRunner

from releasebot.cli import cli
from releasebot.errors import PluginError
from releasebot.plugins import BUILTIN_ORIGIN, Publisher, available_publishers, get_publisher, publisher_origins

PLUGIN_MODULE = '''
from releasebot.plugins import Publisher


class MatrixPublisher(Publisher):
    name = "matrix"
    description = "Announce releases in a Matrix room"
    requires = ("json",)

    def publish(self, plan, context):
        return f"announced {plan.version}"


NOT_A_PUBLISHER = object()
'''


def install_distribution(root, name, entry_points):
    info = root / f"{name.replace('-', '_')}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text(entry_points)


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    (tmp_path / "rb_matrix_plugin.py").write_text(PLUGIN_MODULE)
    install_distribution(
        tmp_path,
        "releasebot-matrix",
        "[releasebot.publishers]\n"
        "matrix = rb_matrix_plugin:MatrixPublisher\n"
        "bogus = rb_matrix_plugin:NOT_A_PUBLISHER\n"
        "ghost = rb_no_such_module:Publisher\n"
        "hosting = rb_matrix_plugin:MatrixPublisher\n"
        "\n[console_scripts]\nmatrix-notify = rb_matrix_plugin:main\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def test_importlib_metadata_is_pinned_to_7_2_1():
    assert importlib.metadata.version("importlib-metadata") == "7.2.1"


def test_builtin_publishers_without_plugins():
    origins = publisher_origins()
    assert {"bundle", "changelog", "hooks", "hosting", "notes"} <= set(origins)
    assert {origins[name] for name in ("bundle", "changelog", "hooks", "hosting", "notes")} == {BUILTIN_ORIGIN}
    assert "matrix" not in origins


def test_plugins_are_discovered_from_entry_points(plugins, caplog):
    with caplog.at_level(logging.WARNING, logger="releasebot.plugins"):
        publishers = available_publishers()
    matrix = publishers["matrix"]
    assert issubclass(matrix, Publisher) and matrix.description == "Announce releases in a Matrix room"
    assert get_publisher("matrix") is matrix
    assert publisher_origins()["matrix"] == "releasebot-matrix"
    assert "matrix-notify" not in publishers
    for name in ("bogus", "ghost"):
        assert name not in publishers
        with pytest.raises(PluginError):
            get_publisher(name)
    assert "rb_no_such_module" in caplog.text and "bogus" in caplog.text


def test_plugins_cannot_replace_builtin_publishers(plugins, caplog):
    with caplog.at_level(logging.WARNING, logger="releasebot.plugins"):
        hosting = get_publisher("hosting")
    assert hosting.__module__ == "releasebot.publishers"
    assert publisher_origins()["hosting"] == BUILTIN_ORIGIN
    assert "hosting" in caplog.text


def test_plugin_publisher_runs_from_the_cli(plugins, project):
    argv = ["--config", str(project / ".releasebot.yml"), "publish", "--publisher", "matrix",
            "--log", str(project / "log.json"), "--tags", str(project / "tags.json"), "--dry-run"]
    result = CliRunner().invoke(cli, argv, prog_name="releasebot")
    assert result.exit_code == 0, result.output
    assert "matrix: announced 1.5.0" in result.output

    listing = CliRunner().invoke(cli, ["publishers"], env={"COLUMNS": "200"})
    assert listing.exit_code == 0, listing.output
    assert any(line.startswith("matrix") and "releasebot-matrix" in line for line in listing.output.splitlines())
