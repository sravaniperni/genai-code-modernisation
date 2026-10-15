"""Release bundles: release files packed into a ``<project>-<version>.tar.gz`` archive."""

from __future__ import annotations

import io
import tarfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from releasebot.errors import BundleError


def build_bundle(files: Mapping[str, str], destination: str | Path, root: str, *, mtime: int = 0) -> Path:
    """Write ``files`` (relative path -> text) below directory ``root`` of a gzipped tarball."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for relpath in sorted(files):
            pure = PurePosixPath(relpath)
            if pure.is_absolute() or ".." in pure.parts:
                raise BundleError(f"invalid bundle path {relpath!r}")
            data = files[relpath].encode("utf-8")
            info = tarfile.TarInfo(f"{root}/{pure}")
            info.size, info.mode, info.mtime = len(data), 0o644, mtime
            archive.addfile(info, io.BytesIO(data))
    return destination


def unpack_bundle(archive: str | Path, destination: str | Path) -> list[str]:
    """Extract a release bundle into ``destination`` and return the names of the extracted files.

    Bundles are downloaded from CI artifacts, so members that would end up outside ``destination``
    (``..`` components, links pointing elsewhere) and special files such as devices are refused.
    """
    archive, destination = Path(archive), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:*") as bundle:
            members = bundle.getmembers()
            bundle.extractall(destination, filter="data")
    except tarfile.FilterError as exc:
        raise BundleError(f"refusing to unpack {archive.name}: {exc}") from exc
    except (tarfile.TarError, OSError) as exc:
        raise BundleError(f"cannot unpack {archive}: {exc}") from exc
    return sorted(member.name for member in members if member.isfile())
