import io
import tarfile

import pytest

from releasebot.errors import BundleError
from releasebot.staging import build_bundle, unpack_bundle


def test_bundle_round_trip(tmp_path):
    archive = build_bundle({"CHANGELOG.md": "# 1.0.0\n", "docs/notes.md": "notes"}, tmp_path / "dist" / "demo-1.0.0.tar.gz", "demo-1.0.0")
    names = unpack_bundle(archive, tmp_path / "out")
    assert names == ["demo-1.0.0/CHANGELOG.md", "demo-1.0.0/docs/notes.md"]
    assert (tmp_path / "out" / "demo-1.0.0" / "docs" / "notes.md").read_text() == "notes"


def test_unsafe_members_are_refused(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../escaped.txt")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"evil"))
    with pytest.raises(BundleError):
        unpack_bundle(archive, tmp_path / "out")
    assert not (tmp_path / "escaped.txt").exists()
    with pytest.raises(BundleError):
        build_bundle({"../x": ""}, tmp_path / "b.tar.gz", "demo")
