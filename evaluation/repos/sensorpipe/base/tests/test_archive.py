import tarfile

import pytest

from sensorpipe.archive import archive_batch, extract_batch
from sensorpipe.errors import ArchiveError


def test_archive_round_trip(tmp_path):
    src = tmp_path / "out"
    (src / "2024").mkdir(parents=True)
    (src / "2024" / "a.csv").write_text("a")
    (src / "b.csv").write_text("b")
    archive = archive_batch([src / "2024" / "a.csv", src / "b.csv"], tmp_path / "batch.tar.gz", base_dir=src)
    files = extract_batch(archive, tmp_path / "restored")
    assert [p.relative_to(tmp_path / "restored").as_posix() for p in files] == ["2024/a.csv", "b.csv"]
    assert files[0].read_text() == "a"


def test_archive_rejects_traversal(tmp_path):
    payload = tmp_path / "evil.csv"
    payload.write_text("x")
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload, arcname="../evil.csv")
    with pytest.raises(ArchiveError):
        extract_batch(archive, tmp_path / "dest")
    with pytest.raises(ArchiveError):
        extract_batch(payload, tmp_path / "dest")
