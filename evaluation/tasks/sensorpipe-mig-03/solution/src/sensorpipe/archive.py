"""Archiving of exported reading batches as compressed tarballs."""

from __future__ import annotations

import tarfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from sensorpipe.errors import ArchiveError


def archive_batch(files: Iterable[str | Path], dest: str | Path, base_dir: str | Path | None = None) -> Path:
    """Write ``files`` into a ``.tar.gz`` archive (paths stored relative to ``base_dir``)."""
    dest = Path(dest)
    with tarfile.open(dest, "w:gz") as tar:
        for file in sorted(Path(f) for f in files):
            arcname = file.relative_to(base_dir).as_posix() if base_dir else file.name
            tar.add(file, arcname=arcname, recursive=False)
    return dest


def _check_member(member: tarfile.TarInfo) -> None:
    name = PurePosixPath(member.name)
    if name.is_absolute() or ".." in name.parts:
        raise ArchiveError(f"refusing to extract unsafe path {member.name!r}")
    if not (member.isfile() or member.isdir()):
        raise ArchiveError(f"refusing to extract link or special file {member.name!r}")


def extract_batch(archive: str | Path, dest: str | Path) -> list[Path]:
    """Extract a batch archive into ``dest`` and return the extracted files, sorted.

    Archives containing absolute paths, ``..`` components, links or device files are rejected as a whole.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:*") as tar:
            members = tar.getmembers()
            for member in members:
                _check_member(member)
            tar.extractall(dest, filter="data")
    except (OSError, tarfile.TarError) as exc:
        raise ArchiveError(f"cannot extract batch archive {archive}: {exc}") from exc
    return sorted(dest / m.name for m in members if m.isfile())
