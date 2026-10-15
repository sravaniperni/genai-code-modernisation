import importlib.metadata
import sys
from datetime import datetime, timezone

import httpx
import pytest

from webhookrelay.app import create_app
from webhookrelay.clock import FixedClock
from webhookrelay.payloads import Event
from webhookrelay.plugins import PluginError, PluginRegistry, default_registry
from webhookrelay.transports import HttpxTransport

MODULE_A = '''
class Stamp:
    name = "stamp"

    def transform(self, event):
        event.data["stamped"] = True
        return event


class Upper:
    name = "upper"

    def transform(self, event):
        event.type = event.type.upper()
        return event


class DropAll:
    name = "drop-all"

    def transform(self, event):
        return None
'''

MODULE_B = '''
class _Counter:
    name = "counter"

    def __init__(self):
        self.seen = 0

    def transform(self, event):
        self.seen += 1
        event.data["count"] = self.seen
        return event


counter = _Counter()
'''


def add_dist(root, dist, version, module, source, entry_points):
    (root / f"{module}.py").write_text(source)
    info = root / f"{dist.replace('-', '_')}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist}\nVersion: {version}\n")
    lines = "".join(f"{name} = {target}\n" for name, target in entry_points)
    (info / "entry_points.txt").write_text(f"[webhookrelay.plugins]\n{lines}\n[console_scripts]\nnoise = {module}:main\n")


@pytest.fixture
def dists(tmp_path, monkeypatch):
    add_dist(tmp_path, "acme-relay-plugins", "2.3.0", "acme_relay_plugins_t", MODULE_A,
             [("upper", "acme_relay_plugins_t:Upper"), ("stamp", "acme_relay_plugins_t:Stamp"),
              ("drop-all", "acme_relay_plugins_t:DropAll"), ("broken", "acme_relay_missing_module:Thing")])
    add_dist(tmp_path, "counter-plugin", "0.4.1", "counter_plugin_t", MODULE_B,
             [("counter", "counter_plugin_t:counter")])
    for name in ("acme_relay_plugins_t", "counter_plugin_t"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def event():
    return Event("git", "push", "e1", {}, datetime(2026, 1, 1, tzinfo=timezone.utc), {})


def test_importlib_metadata_version_is_pinned():
    assert importlib.metadata.version("importlib-metadata") == "7.2.1"


def test_discover_enabled_plugins_in_name_order(dists):
    registry = PluginRegistry()
    assert registry.discover(enabled=["upper", "counter", "stamp"]) == ["counter", "stamp", "upper"]
    assert registry.describe() == [
        {"name": "counter", "origin": "counter-plugin 0.4.1"},
        {"name": "stamp", "origin": "acme-relay-plugins 2.3.0"},
        {"name": "upper", "origin": "acme-relay-plugins 2.3.0"},
    ]
    result = registry.apply(event())
    assert result.type == "PUSH" and result.data == {"count": 1, "stamped": True}
    assert registry.discover(enabled=["upper"]) == []


def test_discover_everything_reports_broken_plugins(dists):
    registry = PluginRegistry()
    with pytest.raises(PluginError, match="cannot load plugin 'broken'"):
        registry.discover()
    assert registry.discover(enabled=["drop-all", "nonexistent"]) == ["drop-all"]


def test_load_single_plugin_by_name(dists):
    registry = default_registry()
    plugin = registry.load("counter")
    assert plugin.name == "counter"
    assert registry.names() == ["drop-pings", "redact-secrets", "counter"]
    assert registry.describe()[-1] == {"name": "counter", "origin": "counter-plugin 0.4.1"}
    with pytest.raises(PluginError, match="no entry point 'missing'"):
        registry.load("missing")
    with pytest.raises(PluginError, match="already registered"):
        registry.load("counter")
    with pytest.raises(PluginError, match="cannot load plugin 'broken'"):
        registry.load("broken")


def test_default_registry_enables_configured_plugins(dists):
    registry = default_registry(["stamp"])
    assert registry.names() == ["drop-pings", "redact-secrets", "stamp"]
    assert default_registry().names() == ["drop-pings", "redact-secrets"]


def test_configured_plugins_are_active_in_the_app(dists):
    delivered = []

    def handler(request):
        request.read()
        delivered.append(request.content)
        return httpx.Response(200)

    config = {"sources": {"git": {}}, "targets": {"ci": {"url": "https://ci.example/in"}},
              "rules": [{"targets": ["ci"]}], "plugins": ["upper", "stamp"]}
    app = create_app(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)),
                     clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)), start_scheduler=False)
    client = app.test_client()
    response = client.post("/hooks/git", data=b'{"type": "push"}', headers={"Content-Type": "application/json"})
    assert response.status_code == 202 and response.get_json()["type"] == "PUSH"
    assert b'"stamped": true' in delivered[0]
    plugins = client.get("/admin/status.json").get_json()["plugins"]
    assert plugins[-2:] == [{"name": "stamp", "origin": "acme-relay-plugins 2.3.0"},
                            {"name": "upper", "origin": "acme-relay-plugins 2.3.0"}]
