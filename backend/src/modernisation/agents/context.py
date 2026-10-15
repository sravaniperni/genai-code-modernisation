"""Packing retrieved code into bounded prompt context."""

from __future__ import annotations

from typing import Any

from modernisation.agents.prompts import render_file
from modernisation.execution.policy import ChangePolicy, PolicyViolation, is_sensitive_path
from modernisation.execution.workspace import Workspace


def excerpt_blocks(
    workspace: Workspace,
    references: list[dict[str, Any]],
    budget_chars: int,
    skip_paths: set[str] | None = None,
    pad: int = 3,
) -> list[str]:
    """Line-numbered excerpts for retrieved references, merged per file, within ``budget_chars``."""
    skip_paths = skip_paths or set()
    spans: dict[str, list[tuple[int, int]]] = {}
    order: list[str] = []
    for ref in references:
        path = ref["path"]
        if path in skip_paths or is_sensitive_path(path):
            continue
        if path not in spans:
            spans[path] = []
            order.append(path)
        spans[path].append((max(1, ref["start_line"] - pad), ref["end_line"] + pad))
    blocks: list[str] = []
    used = 0
    for path in order:
        content = workspace.read(path)
        if content is None:
            continue
        lines = content.splitlines()
        merged: list[list[int]] = []
        for start, end in sorted(spans[path]):
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        for start, end in merged:
            end = min(end, len(lines))
            if end < start:
                continue
            block = render_file(path, "\n".join(lines[start - 1 : end]), start=start, numbered=True)
            if used + len(block) > budget_chars:
                return blocks
            blocks.append(block)
            used += len(block)
    return blocks


def editable_file_blocks(
    workspace: Workspace, paths: list[str], policy: ChangePolicy, budget_chars: int
) -> tuple[list[str], list[str]]:
    """Full current contents of editable files. Returns (blocks, paths_included)."""
    blocks: list[str] = []
    included: list[str] = []
    used = 0
    for raw in paths:
        try:
            path = policy.check_path(raw)
        except PolicyViolation:
            continue
        content = workspace.read(path)
        if content is None:
            block = f'<file path="{path}">\n(new file - does not exist yet)\n</file>'
        else:
            block = render_file(path, content)
        if used + len(block) > budget_chars and blocks:
            break
        blocks.append(block)
        included.append(path)
        used += len(block)
    return blocks, included
