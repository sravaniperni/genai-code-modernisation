import tarfile
from datetime import date

import pytest

from ledgerkit.backup import create_backup, restore_backup
from ledgerkit.errors import BackupError


def test_backup_round_trip(ledger, tmp_path):
    ledger.locked_through = date(2024, 1, 3)
    archive = create_backup(ledger, tmp_path / "books.tar.gz", label="month end")
    with tarfile.open(archive) as tar:
        assert sorted(tar.getnames()) == ["ledger.json", "manifest.json"]
    restored = restore_backup(archive)
    assert restored.to_dict() == ledger.to_dict()


def test_restore_rejects_broken_archives(tmp_path):
    bogus = tmp_path / "bogus.tar.gz"
    bogus.write_bytes(b"not a tar file")
    with pytest.raises(BackupError):
        restore_backup(bogus)
    empty = tmp_path / "empty.tar.gz"
    with tarfile.open(empty, "w:gz"):
        pass
    with pytest.raises(BackupError, match="does not contain"):
        restore_backup(empty)
