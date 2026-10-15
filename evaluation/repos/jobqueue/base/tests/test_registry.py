import pytest

from jobqueue.errors import HandlerNotFound
from jobqueue.registry import HandlerRegistry

PLUGIN = '''
def resize(payload):
    return ("resized", payload["width"])

def notify(payload):
    return "plugin notify"

resize.payload_schema = dict
'''


def test_register_and_lookup():
    registry = HandlerRegistry()

    @registry.register("hello")
    def hello(payload):
        return "hi " + payload["name"]

    assert registry.get("hello").func({"name": "ada"}) == "hi ada" and registry.get("hello").origin == "local"
    with pytest.raises(ValueError):
        registry.register("hello", hello)
    registry.register("hello", len, replace=True)
    assert registry.get("hello").func is len
    with pytest.raises(HandlerNotFound):
        registry.get("missing")


def test_discovers_plugin_handlers(tmp_path, monkeypatch):
    (tmp_path / "acme_visible_handlers.py").write_text(PLUGIN)
    info = tmp_path / "acme_jobs-1.4.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: acme-jobs\nVersion: 1.4\n")
    (info / "entry_points.txt").write_text(
        "[jobqueue.handlers]\nresize = acme_visible_handlers:resize\nnotify = acme_visible_handlers:notify\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = HandlerRegistry()
    registry.register("notify", lambda payload: "local notify")
    assert registry.discover() == ["resize"]
    resize = registry.get("resize")
    assert resize.func({"width": 3}) == ("resized", 3) and resize.schema is dict
    assert resize.origin == "plugin:acme-jobs==1.4"
    assert registry.get("notify").func({}) == "local notify"
