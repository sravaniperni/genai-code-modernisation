"""Ledger backups as gzip-compressed tar archives."""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from ledgerkit.errors import BackupError, LedgerError
from ledgerkit.journal import Ledger

log = logging.getLogger(__name__)

MANIFEST, LEDGER = "manifest.json", "ledger.json"


def remove_tree(path: str | Path) -> None:
    """Best-effort recursive delete: whatever cannot be removed is logged as a warning, never raised."""
    def on_error(func: Any, failed: str, exc: BaseException) -> None:
        log.warning("could not remove %s: %s", failed, exc)

    shutil.rmtree(path, onexc=on_error)


def create_backup(ledger: Ledger, path: str | Path, *, label: str = "") -> Path:
    workdir = Path(tempfile.mkdtemp(prefix="ledgerkit-backup-"))
    try:
        manifest = {"format": 1, "label": label, "accounts": len(ledger.chart), "entries": len(ledger.entries)}
        (workdir / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (workdir / LEDGER).write_text(json.dumps(ledger.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        with tarfile.open(path, "w:gz") as tar:
            for name in (MANIFEST, LEDGER):
                tar.add(workdir / name, arcname=name)
    finally:
        remove_tree(workdir)
    return Path(path)


def restore_backup(path: str | Path) -> Ledger:
    """Rebuild a ledger from a backup archive, extracting it into a private temporary directory."""
    workdir = Path(tempfile.mkdtemp(prefix="ledgerkit-restore-"))
    try:
        try:
            with tarfile.open(path, "r:*") as tar:
                tar.extractall(workdir, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise BackupError(f"cannot extract backup {path}: {exc}") from exc
        if not (workdir / LEDGER).is_file():
            raise BackupError(f"{path} does not contain {LEDGER}")
        try:
            return Ledger.from_dict(json.loads((workdir / LEDGER).read_text(encoding="utf-8")))
        except (LedgerError, ValueError, KeyError) as exc:
            raise BackupError(f"corrupt backup {path}: {exc}") from exc
    finally:
        remove_tree(workdir)
