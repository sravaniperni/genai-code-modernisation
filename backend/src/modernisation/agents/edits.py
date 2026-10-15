"""SEARCH/REPLACE edit protocol.

Models express changes as blocks::

    path/to/file.py
    <<<<<<< SEARCH
    exact existing lines
    =======
    replacement lines
    >>>>>>> REPLACE

An empty SEARCH section creates a new file. Each SEARCH section must match the current file exactly once
(trailing-whitespace and uniform-indentation differences are tolerated). This format is easier for models
to produce reliably than unified diffs and every edit is validated before it touches the workspace.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

BLOCK_RE = re.compile(
    r"(?P<path>[^\n`]*?)\s*\n(?:```[^\n]*\n)?<<<<<<<\s*SEARCH\s*\n(?P<search>.*?)^=======\s*\n"
    r"(?P<replace>.*?)^>>>>>>>\s*REPLACE",
    re.DOTALL | re.MULTILINE,
)


@dataclass
class Edit:
    path: str
    search: str
    replace: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EditError(ValueError):
    def __init__(self, code: str, message: str, path: str | None = None):
        super().__init__(message)
        self.code = code
        self.path = path


FILE_TAG_RE = re.compile(r'<file\s+path="([^"]+)"\s*/?>')


def _clean_path(raw: str) -> str:
    tag = FILE_TAG_RE.search(raw)
    if tag:
        return tag.group(1).strip()
    path = raw.strip().strip("`*:# ").strip()
    if path.lower().startswith(("file:", "path:")):
        path = path.split(":", 1)[1].strip()
    return path


def parse_edits(text: str) -> list[Edit]:
    edits = []
    for m in BLOCK_RE.finditer(text):
        path = _clean_path(m.group("path").splitlines()[-1] if m.group("path").strip() else "")
        if not path:
            # path may be on the line preceding a code fence
            prefix = text[: m.start()].rstrip().splitlines()
            path = _clean_path(prefix[-1]) if prefix else ""
        edits.append(Edit(path=path, search=m.group("search"), replace=m.group("replace")))
    return edits


def _find_unique(haystack: str, needle: str) -> tuple[int, int] | None:
    first = haystack.find(needle)
    if first == -1:
        return None
    if haystack.find(needle, first + 1) != -1:
        raise EditError("ambiguous_match", "SEARCH text matches more than one location")
    return first, first + len(needle)


def _rstrip_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines()]


def _lead(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _uniform_shift(window: list[str], needle: list[str]) -> str | None:
    """Return the indentation prefix that turns every ``needle`` line into its ``window`` line."""
    shift: str | None = None
    for w, n in zip(window, needle, strict=True):
        if not w.strip():
            continue
        lw, ln = _lead(w), _lead(n)
        if not lw.endswith(ln):
            return None
        candidate = lw[: len(lw) - len(ln)]
        if shift is None:
            shift = candidate
        elif candidate != shift:
            return None
    return shift


def apply_edit(content: str, edit: Edit) -> str:
    if edit.search == "":
        raise EditError("empty_search", "empty SEARCH is only valid for new files", edit.path)
    span = _find_unique(content, edit.search)
    if span is not None:
        return content[: span[0]] + edit.replace + content[span[1] :]

    # Tolerate trailing whitespace differences, line by line.
    lines = content.splitlines(keepends=True)
    stripped = [line.rstrip() for line in lines]
    needle = _rstrip_lines(edit.search)
    while needle and needle[-1] == "":
        needle.pop()
    if not needle:
        raise EditError("empty_search", "SEARCH section is blank", edit.path)
    matches = [i for i in range(len(stripped) - len(needle) + 1) if stripped[i : i + len(needle)] == needle]
    indent_shift = ""
    if not matches:
        # Tolerate a uniform indentation difference (common when models drop leading spaces).
        dedented = [line.lstrip() for line in needle]
        for i in range(len(stripped) - len(needle) + 1):
            window = stripped[i : i + len(needle)]
            if [w.lstrip() for w in window] != dedented:
                continue
            shift = _uniform_shift(window, needle)
            if shift is not None:
                matches.append(i)
                indent_shift = shift
    if not matches:
        raise EditError("no_match", "SEARCH text was not found in the file", edit.path)
    if len(matches) > 1:
        raise EditError("ambiguous_match", "SEARCH text matches more than one location", edit.path)
    i = matches[0]
    replacement = edit.replace
    if indent_shift:
        replacement = "".join(
            indent_shift + line if line.strip() else line for line in replacement.splitlines(keepends=True)
        )
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    return "".join(lines[:i]) + replacement + "".join(lines[i + len(needle) :])


def apply_edits(files: dict[str, str | None], edits: list[Edit]) -> dict[str, str | None]:
    """Apply edits to an in-memory view; ``None`` content means the file does not exist."""
    result = dict(files)
    for edit in edits:
        current = result.get(edit.path)
        if current is None:
            if edit.search.strip():
                raise EditError("missing_file", f"{edit.path} does not exist", edit.path)
            result[edit.path] = edit.replace
        else:
            if edit.search.strip() == "" and edit.replace.strip() == "":
                continue
            if edit.search.strip() == "":
                raise EditError("file_exists", f"{edit.path} already exists; use a SEARCH section", edit.path)
            result[edit.path] = apply_edit(current, edit)
    return result
