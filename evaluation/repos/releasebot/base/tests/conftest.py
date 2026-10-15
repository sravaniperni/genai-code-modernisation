from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from releasebot.commits import Commit
from releasebot.config import parse_config
from releasebot.tags import Tag

BASE_TS = 1767225600  # 2026-01-01T00:00:00Z

CONFIG_YAML = """\
# releasebot configuration used by the test-suite
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
  per_page: 2
"""


def sha(n: int) -> str:
    return f"{n:07x}" + "a" * 33


@pytest.fixture
def config():
    return parse_config(CONFIG_YAML)


@pytest.fixture
def now():
    return datetime(2026, 3, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def log():
    """Newest first, like ``git log``; v1.4.2 points at sha(1)."""
    messages = [
        "feat(api): add pagination to the export endpoint\n\nCloses #42",
        "feat: support --dry-run for every publisher",
        "fix: do not crash on an empty changelog\n\nRefs: #40",
        "docs: explain the configuration file",
        "Merge branch 'feature/export'",
        "chore: release 1.4.2",
    ]
    return [Commit(sha(len(messages) - i), msg, BASE_TS + 3600 * (len(messages) - i), "dev") for i, msg in enumerate(messages)]


@pytest.fixture
def tags():
    return [Tag("v1.4.0", sha(100), BASE_TS - 7200), Tag("v1.4.2", sha(1), BASE_TS + 3600), Tag("v1.4.1", sha(101), BASE_TS - 3600)]


@pytest.fixture
def project(tmp_path, log, tags):
    """A project directory with a configuration file and JSON exports of log and tags."""
    (tmp_path / ".releasebot.yml").write_text(CONFIG_YAML)
    (tmp_path / "log.json").write_text(json.dumps([c.__dict__ for c in log]))
    (tmp_path / "tags.json").write_text(json.dumps([t.__dict__ for t in tags]))
    return tmp_path
