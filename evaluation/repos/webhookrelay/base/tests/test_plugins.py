import sys

import pytest
from conftest import T0

from webhookrelay.payloads import Event
from webhookrelay.plugins import PluginError, PluginRegistry, default_registry

PLUGIN_MODULE = '''
class Tagger:
    name = "tagger"

    def transform(self, event):
        event.data["tagged"] = True
        return event


class Shouter:
    name = "shouter"

    def transform(self, event):
        event.type = event.type.upper()
        return event
'''


@pytest.fixture
def plugin_dist(tmp_path, monkeypatch):
    """A fake installed distribution advertising two plugins through entry points."""
    (tmp_path / "relay_test_plugins.py").write_text(PLUGIN_MODULE)
    info = tmp_path / "relay_test_plugins-1.2.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: relay-test-plugins\nVersion: 1.2.0\n")
    (info / "entry_points.txt").write_text(
        "[webhookrelay.plugins]\ntagger = relay_test_plugins:Tagger\nshouter = relay_test_plugins:Shouter\n"
    )
    monkeypatch.delitem(sys.modules, "relay_test_plugins", raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def make_event(type_="push", **data):
    return Event("git", type_, "e1", data, T0, {})


def test_builtin_plugins():
    registry = default_registry()
    assert registry.names() == ["drop-pings", "redact-secrets"]
    assert registry.apply(make_event("ping")) is None
    event = registry.apply(make_event(user={"name": "ann", "api_key": "k"}, items=[{"password": "p"}]))
    assert event.data == {"user": {"name": "ann", "api_key": "***"}, "items": [{"password": "***"}]}


def test_entry_point_discovery(plugin_dist):
    registry = PluginRegistry()
    assert registry.discover(enabled=["tagger"]) == ["tagger"]
    assert registry.discover() == ["shouter"]
    assert registry.describe() == [
        {"name": "tagger", "origin": "relay-test-plugins 1.2.0"},
        {"name": "shouter", "origin": "relay-test-plugins 1.2.0"},
    ]
    event = registry.apply(make_event())
    assert event.type == "PUSH" and event.data == {"tagged": True}


def test_load_single_plugin(plugin_dist):
    registry = default_registry()
    plugin = registry.load("shouter")
    assert plugin.name == "shouter" and registry.names()[-1] == "shouter"
    with pytest.raises(PluginError, match="no entry point"):
        registry.load("missing")


def test_registration_errors():
    registry = PluginRegistry()
    registry.register(default_registry().get("drop-pings"))
    with pytest.raises(PluginError, match="already registered"):
        registry.register(default_registry().get("drop-pings"))
    with pytest.raises(PluginError, match="not a plugin"):
        registry.register(object())
    with pytest.raises(PluginError, match="no plugin"):
        registry.get("nope")
