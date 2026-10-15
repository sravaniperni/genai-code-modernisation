import importlib.metadata
import textwrap

import pytest

from jobqueue.executor import Executor
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry


def install_plugin(root, dist, version, module, source, groups):
    (root / f"{module}.py").write_text(textwrap.dedent(source))
    info = root / f"{dist.replace('-', '_')}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist}\nVersion: {version}\n")
    lines = []
    for group, entries in groups.items():
        lines.append(f"[{group}]")
        lines += [f"{name} = {module}:{attr}" for name, attr in entries.items()]
    (info / "entry_points.txt").write_text("\n".join(lines) + "\n")


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    install_plugin(tmp_path, "imaging-tools", "2.3.0", "acc_imaging_handlers", """
        class ResizePayload(dict):
            pass

        def resize(payload):
            return {"resized": payload["width"]}

        resize.payload_schema = ResizePayload

        def crop(payload):
            return "cropped"
    """, {"jobqueue.handlers": {"resize": "resize", "crop": "crop"}, "console_scripts": {"imgtool": "crop"}})
    install_plugin(tmp_path, "mailer", "0.9", "acc_mail_handlers", """
        def send(payload):
            return "sent to " + payload["to"]

        def audit(payload):
            return "audited"
    """, {"jobqueue.handlers": {"send-mail": "send"}, "acme.audit": {"audit": "audit"}})
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def test_importlib_metadata_version_is_pinned():
    assert importlib.metadata.version("importlib-metadata") == "7.2.1"


def test_discovers_handlers_from_all_distributions(plugins):
    registry = HandlerRegistry()
    assert registry.discover() == ["crop", "resize", "send-mail"]
    resize = registry.get("resize")
    assert resize.func({"width": 10}) == {"resized": 10}
    assert resize.schema.__name__ == "ResizePayload" and registry.get("crop").schema is None
    assert resize.origin == "plugin:imaging-tools==2.3.0"
    assert registry.get("send-mail").origin == "plugin:mailer==0.9"
    assert registry.discover() == []


def test_local_handlers_take_precedence(plugins):
    registry = HandlerRegistry()
    registry.register("crop", lambda payload: "local crop")
    assert registry.discover() == ["resize", "send-mail"]
    assert registry.get("crop").func({}) == "local crop" and registry.get("crop").origin == "local"


def test_custom_and_empty_groups(plugins):
    registry = HandlerRegistry()
    assert registry.discover("acme.audit") == ["audit"]
    assert registry.get("audit").func({}) == "audited"
    assert registry.discover("no.such.group") == []


def test_discovered_handlers_run(plugins):
    registry = HandlerRegistry()
    registry.discover()
    queue = JobQueue(registry=registry)
    job = queue.enqueue("send-mail", {"to": "ops@example.test"})
    Executor(queue.store, registry).execute(queue.store.claim_next(queue.clock.now(), "w"))
    done = queue.get(job.id)
    assert (done.state, done.result) == (JobState.SUCCEEDED, "sent to ops@example.test")
