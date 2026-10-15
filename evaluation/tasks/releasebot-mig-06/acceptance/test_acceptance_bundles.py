import io
import os
import re
import tarfile
from pathlib import Path

import pytest

from releasebot.errors import BundleError
from releasebot.staging import build_bundle, unpack_bundle


def make_archive(path, members):
    """members: list of (TarInfo, bytes | None)."""
    with tarfile.open(path, "w:gz") as tar:
        for info, data in members:
            if data is not None:
                info.size = len(data)
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return path


def regular(name, data=b"x"):
    return tarfile.TarInfo(name), data


def link(name, target, kind=tarfile.SYMTYPE):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, target
    return info, None


def test_round_trip(tmp_path):
    files = {"CHANGELOG.md": "## 1.5.0 — März\n", "notes/RELEASE_NOTES.md": "* fixed #12\n", "release.json": "{}\n"}
    archive = build_bundle(files, tmp_path / "dist" / "demo-1.5.0.tar.gz", "demo-1.5.0")
    names = unpack_bundle(archive, tmp_path / "out")
    assert names == ["demo-1.5.0/CHANGELOG.md", "demo-1.5.0/notes/RELEASE_NOTES.md", "demo-1.5.0/release.json"]
    root = tmp_path / "out" / "demo-1.5.0"
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == "## 1.5.0 — März\n"
    assert (root / "notes" / "RELEASE_NOTES.md").read_text() == "* fixed #12\n"


def test_links_inside_the_bundle_are_kept(tmp_path):
    archive = make_archive(tmp_path / "ok.tar.gz", [regular("demo/CHANGELOG.md", b"log"), link("demo/LATEST.md", "CHANGELOG.md")])
    assert unpack_bundle(archive, tmp_path / "out") == ["demo/CHANGELOG.md"]
    latest = tmp_path / "out" / "demo" / "LATEST.md"
    assert latest.is_symlink() and latest.read_text() == "log"


@pytest.mark.parametrize(
    "members",
    [
        [regular("demo/ok.txt"), regular("../escaped.txt")],
        [regular("demo/../../escaped.txt")],
        [link("demo/passwd", "/etc/passwd")],
        [link("demo/up", "../../escaped.txt")],
        [link("demo/hard", "../escaped.txt", tarfile.LNKTYPE)],
    ],
)
def test_members_escaping_the_destination_are_refused(tmp_path, members):
    archive = make_archive(tmp_path / "evil.tar.gz", members)
    destination = tmp_path / "a" / "b"
    with pytest.raises(BundleError):
        unpack_bundle(archive, destination)
    assert not (tmp_path / "a" / "escaped.txt").exists() and not (tmp_path / "escaped.txt").exists()
    assert not (destination / "demo" / "passwd").exists() and not (destination / "demo" / "up").exists()


def test_special_files_are_refused(tmp_path):
    fifo = tarfile.TarInfo("demo/pipe")
    fifo.type = tarfile.FIFOTYPE
    archive = make_archive(tmp_path / "fifo.tar.gz", [(fifo, None)])
    with pytest.raises(BundleError):
        unpack_bundle(archive, tmp_path / "out")
    assert not (tmp_path / "out" / "demo" / "pipe").exists()


def test_corrupt_archives(tmp_path):
    broken = tmp_path / "broken.tar.gz"
    broken.write_bytes(b"\x1f\x8b\x08\x00 definitely not a tarball")
    with pytest.raises(BundleError):
        unpack_bundle(broken, tmp_path / "out")


def test_extraction_is_explicitly_filtered():
    root = Path(os.environ.get("REPO_ROOT", ".")) / "src"
    for path in root.rglob("*.py"):
        for call in re.findall(r"\.extractall\((.*?)\)", path.read_text(), re.DOTALL):
            assert "filter" in call, f"{path}: extractall({call})"
