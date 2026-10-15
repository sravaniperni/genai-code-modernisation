import os
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from conftest import BASE_TS

from releasebot.commits import Commit
from releasebot.release import plan_release
from releasebot.tags import Tag

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def is_utc(value):
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


def test_commit_and_tag_dates_are_aware_utc():
    commit = Commit("a" * 40, "feat: x", BASE_TS + 90)
    assert is_utc(commit.date)
    assert commit.date == datetime(2026, 1, 1, 0, 1, 30, tzinfo=UTC)
    tag = Tag("v1.0.0", "a" * 40, BASE_TS - 1)
    assert is_utc(tag.date)
    assert tag.date == datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)


def test_plan_timestamps_default_to_now_in_utc(config, log, tags):
    before = datetime.now(UTC)
    plan = plan_release(config, log, tags)
    after = datetime.now(UTC)
    assert is_utc(plan.created_at)
    assert before - timedelta(seconds=1) <= plan.created_at <= after + timedelta(seconds=1)
    manifest = plan.to_dict()
    assert STAMP.match(manifest["created_at"]), manifest["created_at"]
    assert manifest["days_since_previous"] == (plan.created_at - tags[-1].date).days


def test_manifest_format_is_unchanged(config, log, tags, now):
    plan = plan_release(config, log, tags, now=now)
    manifest = plan.to_dict()
    assert manifest["created_at"] == "2026-03-05T12:00:00Z"
    assert manifest["days_since_previous"] == 63
    assert plan.release_date.isoformat() == "2026-03-05"
    assert '"created_at": "2026-03-05T12:00:00Z"' in plan.to_json()


def test_non_utc_input_is_normalised(config, log, tags):
    cest = timezone(timedelta(hours=2))
    plan = plan_release(config, log, tags, now=datetime(2026, 6, 1, 1, 30, tzinfo=cest))
    assert plan.to_dict()["created_at"] == "2026-05-31T23:30:00Z"


def test_no_naive_utc_helpers_left():
    root = Path(os.environ.get("REPO_ROOT", ".")) / "src"
    source = "\n".join(p.read_text() for p in root.rglob("*.py"))
    assert "utcnow(" not in source and "utcfromtimestamp(" not in source
