import logging

import pytest

from releasebot.errors import PluginError
from releasebot.plugins import BUILTIN_ORIGIN, available_publishers, get_publisher, module_available, publisher_origins

PLUGIN_MODULE = """
from releasebot.plugins import Publisher

class SlackPublisher(Publisher):
    name = "slack"
    description = "Announce the release on Slack"

    def publish(self, plan, context):
        return "posted"
"""


@pytest.fixture
def plugin_dist(tmp_path, monkeypatch):
    """A fake installed distribution registering publishers via entry points."""
    (tmp_path / "rb_slack_plugin.py").write_text(PLUGIN_MODULE)
    info = tmp_path / "rb_slack-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: rb-slack\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text(
        "[releasebot.publishers]\nslack = rb_slack_plugin:SlackPublisher\n"
        "broken = rb_missing_module:Publisher\nchangelog = rb_slack_plugin:SlackPublisher\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def test_builtin_publishers():
    publishers = available_publishers()
    assert {"changelog", "hosting", "notes", "hooks", "bundle"} <= set(publishers)
    assert publisher_origins()["changelog"] == BUILTIN_ORIGIN


def test_entry_point_plugins_are_discovered(plugin_dist, caplog):
    with caplog.at_level(logging.WARNING, logger="releasebot.plugins"):
        publishers = available_publishers()
    assert publishers["slack"].description == "Announce the release on Slack"
    assert publisher_origins()["slack"] == "rb-slack"
    assert "broken" not in publishers
    assert publishers["changelog"].__module__ == "releasebot.publishers"
    assert "rb_missing_module" in caplog.text


def test_unknown_publisher():
    with pytest.raises(PluginError, match="unknown publisher"):
        get_publisher("carrier-pigeon")


def test_module_available():
    assert module_available("json")
    assert not module_available("releasebot_no_such_module")
