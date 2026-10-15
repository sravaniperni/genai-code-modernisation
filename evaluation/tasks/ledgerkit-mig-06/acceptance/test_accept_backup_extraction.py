import io
import json
import logging
import os
import re
import tarfile
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.backup import create_backup, remove_tree, restore_backup
from ledgerkit.errors import BackupError
from ledgerkit.journal import JournalEntry, Ledger, Posting


def _ledger() -> Ledger:
    ledger = Ledger(ChartOfAccounts([Account("1000", "Cash", AccountType.ASSET), Account("3000", "Capital", AccountType.EQUITY),
                                     Account("6100", "Rent", AccountType.EXPENSE)]))
    ledger.post(JournalEntry(date(2024, 1, 2), "Capital", (Posting.debit("1000", "5000"), Posting.credit("3000", "5000")),
                             entry_id="cap", created_at=datetime(2024, 1, 2, 9, 0)))
    ledger.post(JournalEntry(date(2024, 1, 20), "Rent", (Posting.debit("6100", "750.25"), Posting.credit("1000", "750.25")),
                             reference="R1", entry_id="rent", created_at=datetime(2024, 1, 20, 9, 0)))
    ledger.locked_through = date(2024, 1, 5)
    return ledger


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """Private temp root for the library's temporary directories; tmp_path itself plays 'outside'."""
    root = tmp_path / "scratch"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def _archive(path, members):
    with tarfile.open(path, "w:gz") as tar:
        for info, payload in members:
            tar.addfile(info, io.BytesIO(payload) if payload is not None else None)
    return path


def _file(name, payload: bytes):
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    return info, payload


def _valid_members():
    ledger_json = json.dumps(_ledger().to_dict()).encode()
    return [_file("manifest.json", b'{"format": 1}'), _file("ledger.json", ledger_json)]


def test_round_trip_and_cleanup(scratch, tmp_path):
    archive = create_backup(_ledger(), tmp_path / "books.tar.gz", label="jan")
    assert os.listdir(scratch) == []
    restored = restore_backup(archive)
    assert restored.to_dict() == _ledger().to_dict()
    assert os.listdir(scratch) == []
    with tarfile.open(archive) as tar:
        manifest = json.load(tar.extractfile("manifest.json"))
    assert manifest == {"format": 1, "label": "jan", "accounts": 3, "entries": 2}


def test_path_traversal_members_are_rejected(scratch, tmp_path):
    archive = _archive(tmp_path / "evil.tar.gz", [*_valid_members(), _file("../escaped.json", b"{}"),
                                                  _file("nested/../../escaped2.json", b"{}")])
    with pytest.raises(BackupError):
        restore_backup(archive)
    assert not (tmp_path / "escaped.json").exists() and not (tmp_path / "escaped2.json").exists()
    assert os.listdir(scratch) == []


def test_links_pointing_outside_are_rejected(scratch, tmp_path):
    (tmp_path / "secret.txt").write_text("do not touch")
    symlink = tarfile.TarInfo("ledger.json")
    symlink.type, symlink.linkname = tarfile.SYMTYPE, "../secret.txt"
    with pytest.raises(BackupError):
        restore_backup(_archive(tmp_path / "symlink.tar.gz", [_file("manifest.json", b"{}"), (symlink, None)]))
    absolute = tarfile.TarInfo("ledger.json")
    absolute.type, absolute.linkname = tarfile.SYMTYPE, str(tmp_path / "secret.txt")
    with pytest.raises(BackupError):
        restore_backup(_archive(tmp_path / "abs.tar.gz", [_file("manifest.json", b"{}"), (absolute, None)]))
    hardlink = tarfile.TarInfo("copy.txt")
    hardlink.type, hardlink.linkname = tarfile.LNKTYPE, "../secret.txt"
    with pytest.raises(BackupError):
        restore_backup(_archive(tmp_path / "hard.tar.gz", [*_valid_members(), (hardlink, None)]))
    assert (tmp_path / "secret.txt").read_text() == "do not touch"
    assert os.listdir(scratch) == []


def test_corrupt_archives_still_raise_backup_error(scratch, tmp_path):
    (tmp_path / "junk.tar.gz").write_bytes(b"\x1f\x8b not really gzip")
    with pytest.raises(BackupError):
        restore_backup(tmp_path / "junk.tar.gz")
    with pytest.raises(BackupError):
        restore_backup(_archive(tmp_path / "partial.tar.gz", [_file("manifest.json", b"{}")]))
    assert os.listdir(scratch) == []


def test_remove_tree_is_best_effort(tmp_path, monkeypatch, caplog):
    target = tmp_path / "tree"
    (target / "sub").mkdir(parents=True)
    for name in ("a.txt", "locked.txt", "sub/b.txt"):
        (target / name).write_text("x")
    real_unlink = os.unlink

    def unlink(path, *args, **kwargs):
        if os.path.basename(path) == "locked.txt":
            raise PermissionError(13, "Permission denied")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    caplog.set_level(logging.WARNING)
    remove_tree(target)
    monkeypatch.undo()
    assert sorted(os.listdir(target)) == ["locked.txt"]
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("locked.txt" in m and "Permission denied" in m for m in messages)
    remove_tree(target)
    assert not target.exists()
    remove_tree(tmp_path / "does-not-exist")


def test_rmtree_onerror_is_no_longer_used():
    source = Path(os.environ["REPO_ROOT"], "src", "ledgerkit")
    assert [str(p) for p in source.rglob("*.py") if re.search(r"\bonerror\s*=", p.read_text(encoding="utf-8"))] == []
