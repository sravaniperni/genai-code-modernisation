"""Shell hooks run by the ``hooks`` publisher (``hooks:`` in the configuration).

Hook commands are shell command lines with ``{placeholders}`` (``make dist VERSION={version}``); every
substituted value is quoted so that release data can never inject shell syntax.
"""

from __future__ import annotations

import shlex
import string
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from releasebot.errors import HookError

Runner = Callable[[str, Path | None], subprocess.CompletedProcess]


def quote(value: object) -> str:
    """Quote ``value`` as a single word for a POSIX shell."""
    return shlex.quote(str(value))


def render_command(template: str, variables: Mapping[str, object]) -> str:
    """Substitute ``{name}`` placeholders in ``template`` with shell-quoted values."""
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise HookError(f"malformed hook command {template!r}: {exc}") from exc
    parts: list[str] = []
    for literal, field_name, _spec, _conversion in parsed:
        parts.append(literal)
        if field_name is None:
            continue
        if field_name not in variables:
            raise HookError(f"unknown placeholder {{{field_name}}} in hook command {template!r}")
        parts.append(quote(variables[field_name]))
    return "".join(parts)


@dataclass(frozen=True)
class HookResult:
    command: str
    returncode: int
    output: str = ""


def _run_shell(command: str, cwd: Path | None) -> subprocess.CompletedProcess:
    return subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, check=False)


def run_hooks(commands: Iterable[str], variables: Mapping[str, object], *, cwd: Path | None = None,
              runner: Runner | None = None, dry_run: bool = False) -> list[HookResult]:
    """Render and run ``commands`` in order, stopping at the first failure."""
    results: list[HookResult] = []
    for template in commands:
        command = render_command(template, variables)
        if dry_run:
            results.append(HookResult(command, 0))
            continue
        completed = (runner or _run_shell)(command, cwd)
        results.append(HookResult(command, completed.returncode, completed.stdout or ""))
        if completed.returncode != 0:
            raise HookError(f"hook exited with status {completed.returncode}: {command}")
    return results
