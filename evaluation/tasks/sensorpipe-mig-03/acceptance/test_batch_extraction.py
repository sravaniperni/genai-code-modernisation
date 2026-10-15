import io
import tarfile

import pytest

from sensorpipe.archive import archive_batch, extract_batch
from sensorpipe.errors import ArchiveError


def make_batch(tmp_path):
    src = tmp_path / "export"
    (src / "2024" / "01").mkdir(parents=True)
    (src / "2024" / "01" / "TT-101.csv").write_text("timestamp,value\n2024-01-15T08:00:00Z,20.5\n")
    (src / "2024" / "PT-201.csv").write_text("timestamp,value\n2024-01-15T08:00:00Z,1.02\n")
    (src / "manifest.json").write_text('{"files": 2}')
    files = [src / "2024" / "01" / "TT-101.csv", src / "2024" / "PT-201.csv", src / "manifest.json"]
    return archive_batch(files, tmp_path / "batch.tar.gz", base_dir=src)


def test_round_trip(tmp_path):
    archive = make_batch(tmp_path)
    dest = tmp_path / "restored"
    files = extract_batch(archive, dest)
    assert [p.relative_to(dest).as_posix() for p in files] == ["2024/01/TT-101.csv", "2024/PT-201.csv", "manifest.json"]
    assert (dest / "2024" / "01" / "TT-101.csv").read_text().endswith("20.5\n")
    assert all(p.is_file() for p in files)


def test_extract_into_existing_directory(tmp_path):
    archive = make_batch(tmp_path)
    dest = tmp_path / "restored"
    (dest / "keep").mkdir(parents=True)
    extract_batch(archive, dest)
    assert (dest / "keep").is_dir() and (dest / "manifest.json").is_file()


def unsafe_archive(tmp_path, build):
    path = tmp_path / "unsafe.tar"
    with tarfile.open(path, "w") as tar:
        good = tarfile.TarInfo("ok.csv")
        good.size = 2
        tar.addfile(good, io.BytesIO(b"ok"))
        build(tar)
    return path


def add_file(name):
    def build(tar):
        info = tarfile.TarInfo(name)
        info.size = 4
        tar.addfile(info, io.BytesIO(b"evil"))
    return build


def add_link(kind):
    def build(tar):
        info = tarfile.TarInfo("link.csv")
        info.type = kind
        info.linkname = "ok.csv" if kind == tarfile.LNKTYPE else "/etc/passwd"
        tar.addfile(info)
    return build


def add_device(tar):
    info = tarfile.TarInfo("dev-null")
    info.type = tarfile.CHRTYPE
    info.devmajor, info.devminor = 1, 3
    tar.addfile(info)


@pytest.mark.parametrize("build", [
    add_file("../escape.csv"), add_file("nested/../../escape.csv"), add_file("/tmp/absolute.csv"),
    add_link(tarfile.SYMTYPE), add_link(tarfile.LNKTYPE), add_device,
], ids=["parent", "nested-parent", "absolute", "symlink", "hardlink", "device"])
def test_unsafe_members_are_rejected(tmp_path, build):
    archive = unsafe_archive(tmp_path, build)
    dest = tmp_path / "work" / "dest"
    with pytest.raises(ArchiveError):
        extract_batch(archive, dest)
    assert not (tmp_path / "work" / "escape.csv").exists() and not (tmp_path / "escape.csv").exists()
    assert not (dest / "ok.csv").exists()


def test_unreadable_archive(tmp_path):
    bogus = tmp_path / "bogus.tar.gz"
    bogus.write_bytes(b"this is not a tarball")
    with pytest.raises(ArchiveError):
        extract_batch(bogus, tmp_path / "dest")
    with pytest.raises(ArchiveError):
        extract_batch(tmp_path / "missing.tar.gz", tmp_path / "dest")
