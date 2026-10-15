"""Shared fixtures for the protected acceptance tests (independent of the repository's own tests)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

BASE_TS = 1767225600  # 2026-01-01T00:00:00Z

CONFIG_YAML = """\
# releasebot configuration (acceptance)
project: demo
version: 1.4.2  # last released version
tag_prefix: v
publishers: [changelog]
changelog:
  scope_aliases:
    api: API
hosting:
  api_url: https://git.example.com/api/v1
  web_url: https://git.example.com/acme/demo
  repo: acme/demo
"""


def sha(n: int) -> str:
    return f"{n:07x}" + "b" * 33


def make_log(*messages: str, start: int = 100):
    """Commits newest first; the oldest one gets sha(start)."""
    from releasebot.commits import Commit

    count = len(messages)
    return [Commit(sha(start + count - 1 - i), m, BASE_TS + 3600 * (count - i), "dev") for i, m in enumerate(messages)]


@pytest.fixture
def now():
    return datetime(2026, 3, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def config():
    from releasebot.config import parse_config

    return parse_config(CONFIG_YAML)


@pytest.fixture
def log():
    return make_log(
        "feat(api): add pagination to the export endpoint\n\nCloses #42",
        "feat: support --dry-run for every publisher",
        "fix: do not crash on an empty changelog\n\nRefs: #40",
        "docs: explain the configuration file",
        "chore: release 1.4.2",
    )


@pytest.fixture
def tags(log):
    from releasebot.tags import Tag

    return [Tag("v1.4.0", sha(1), BASE_TS - 7200), Tag("v1.4.2", log[-1].sha, BASE_TS + 3600)]


@pytest.fixture
def project(tmp_path, log, tags):
    (tmp_path / ".releasebot.yml").write_text(CONFIG_YAML)
    (tmp_path / "log.json").write_text(json.dumps([vars(c) for c in log]))
    (tmp_path / "tags.json").write_text(json.dumps([vars(t) for t in tags]))
    return tmp_path
