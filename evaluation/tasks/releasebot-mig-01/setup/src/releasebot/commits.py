"""Parsing of Conventional Commits 1.0 messages (``type(scope)!: description``, body, footers)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

HEADER_RE = re.compile(
    r"^(?P<type>[A-Za-z][A-Za-z0-9_-]*)(?:\((?P<scope>[^()\r\n]+)\))?(?P<bang>!)?: (?P<description>\S.*)$"
)
# "Token: value" or "Token #value"; BREAKING CHANGE is the only token allowed to contain a space.
FOOTER_RE = re.compile(r"^(?P<token>BREAKING CHANGE|[A-Za-z][A-Za-z0-9-]*)(?::[ \t]+|[ \t]+(?=#))(?P<value>.*)$")
BREAKING_TOKENS = ("BREAKING CHANGE", "BREAKING-CHANGE")
REFERENCE_TOKENS = frozenset({"refs", "references", "closes", "fixes", "resolves"})


@dataclass(frozen=True)
class Commit:
    """A raw commit as exported from the repository log."""

    sha: str
    message: str
    timestamp: int = 0
    author: str = ""

    @property
    def date(self) -> datetime:
        """Commit time in UTC."""
        return datetime.utcfromtimestamp(self.timestamp)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Commit:
        return cls(str(data["sha"]), str(data["message"]), int(data.get("timestamp", 0)), str(data.get("author", "")))


@dataclass(frozen=True)
class Footer:
    token: str
    value: str


@dataclass(frozen=True)
class ConventionalCommit:
    commit: Commit
    type: str
    scope: str | None
    description: str
    body: str = ""
    footers: tuple[Footer, ...] = ()
    breaking: bool = False
    breaking_description: str | None = None

    @property
    def sha(self) -> str:
        return self.commit.sha

    @property
    def references(self) -> tuple[str, ...]:
        """Issue numbers referenced from ``Refs``/``Closes``/``Fixes`` footers, in order."""
        found = [n for f in self.footers if f.token.lower() in REFERENCE_TOKENS for n in re.findall(r"#(\d+)", f.value)]
        return tuple(dict.fromkeys(found))


def _parse_footers(block: str) -> tuple[Footer, ...]:
    footers: list[list[str]] = []
    for line in block.splitlines():
        match = FOOTER_RE.match(line)
        if match:
            footers.append([match["token"], match["value"].strip()])
        elif footers:  # continuation line of a multi-line footer value
            footers[-1][1] = f"{footers[-1][1]}\n{line.strip()}".strip()
    return tuple(Footer(token, value) for token, value in footers)


def parse_commit(commit: Commit) -> ConventionalCommit | None:
    """Parse ``commit``; return ``None`` when the message is not a conventional commit."""
    lines = commit.message.strip("\n").splitlines()
    header = HEADER_RE.match(lines[0].strip()) if lines else None
    if header is None:
        return None
    rest = "\n".join(lines[1:]).strip("\n")
    paragraphs = [p for p in re.split(r"\n[ \t]*\n", rest) if p.strip()]
    footers: tuple[Footer, ...] = ()
    if paragraphs and FOOTER_RE.match(paragraphs[-1].splitlines()[0]):
        footers = _parse_footers(paragraphs.pop())
    breaking_footer = next((f for f in footers if f.token in BREAKING_TOKENS), None)
    bang = header["bang"] is not None
    description = header["description"].strip()
    return ConventionalCommit(
        commit=commit,
        type=header["type"].lower(),
        scope=header["scope"].strip() if header["scope"] else None,
        description=description,
        body="\n\n".join(p.strip() for p in paragraphs),
        footers=footers,
        breaking=bang or breaking_footer is not None,
        breaking_description=breaking_footer.value if breaking_footer else (description if bang else None),
    )


def parse_log(commits: Iterable[Commit]) -> list[ConventionalCommit]:
    """Parse every conventional commit in ``commits``, preserving order and skipping the rest."""
    parsed = (parse_commit(commit) for commit in commits)
    return [commit for commit in parsed if commit is not None]
