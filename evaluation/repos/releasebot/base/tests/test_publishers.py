import json
import subprocess
import tarfile

import httpx

from releasebot.hosting import HostingClient
from releasebot.plugins import PublishContext
from releasebot.publishers import BundlePublisher, ChangelogPublisher, HooksPublisher, HostingPublisher
from releasebot.release import plan_release


def test_changelog_publisher(config, log, tags, now, tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 1.4.2 (January 1, 2026)\n")
    plan = plan_release(config, log, tags, now=now)
    ChangelogPublisher(config).publish(plan, PublishContext(tmp_path))
    text = (tmp_path / "CHANGELOG.md").read_text()
    assert text.index("## [1.5.0]") < text.index("## 1.4.2")


def test_hosting_publisher(config, log, tags, now, tmp_path):
    created = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(404)
        created.append(json.loads(request.content))
        return httpx.Response(201, json={"id": 1, **created[-1]})

    client = HostingClient.from_config(config.hosting, transport=httpx.MockTransport(handler))
    plan = plan_release(config, log, tags, now=now)
    result = HostingPublisher(config).publish(plan, PublishContext(tmp_path, hosting_client=client))
    assert result == "created release v1.5.0"
    assert created[0]["name"] == "demo 1.5.0" and "### Features" in created[0]["body"]


def test_hooks_publisher(config, log, tags, tmp_path):
    config.hooks = ["tag {tag}", "announce {project} {version}"]
    ran = []
    runner = lambda command, cwd: ran.append(command) or subprocess.CompletedProcess(command, 0, "")  # noqa: E731
    HooksPublisher(config).publish(plan_release(config, log, tags), PublishContext(tmp_path, runner=runner))
    assert ran == ["tag v1.5.0", "announce demo 1.5.0"]


def test_bundle_publisher(config, log, tmp_path):
    plan = plan_release(config, log, [])
    BundlePublisher(config).publish(plan, PublishContext(tmp_path))
    with tarfile.open(tmp_path / "dist" / "demo-1.5.0.tar.gz") as archive:
        names = sorted(archive.getnames())
        manifest = json.load(archive.extractfile("demo-1.5.0/release.json"))
    assert names == ["demo-1.5.0/CHANGELOG.md", "demo-1.5.0/RELEASE_NOTES.md", "demo-1.5.0/release.json"]
    assert manifest["version"] == "1.5.0" and manifest["previous_tag"] is None
