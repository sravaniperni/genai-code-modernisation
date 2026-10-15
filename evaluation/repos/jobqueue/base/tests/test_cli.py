import json

import pytest
from click.testing import CliRunner

from jobqueue.cli import AdminContext, cli
from jobqueue.job import JobState
from jobqueue.sqlstore import SQLJobStore


@pytest.fixture
def admin():
    return AdminContext(store=SQLJobStore("sqlite://"))


def invoke(admin, *args, columns=120):
    return CliRunner().invoke(cli, list(args), obj=admin, env={"COLUMNS": str(columns)}, catch_exceptions=False)


def test_enqueue_then_list(admin):
    result = invoke(admin, "enqueue", "resize", "--payload", '{"width": 640}', "--priority", "8", "--queue", "media")
    job_id = result.output.strip()
    assert result.exit_code == 0 and admin.store.get(job_id).payload == {"width": 640}
    listing = invoke(admin, "list")
    assert job_id[:12] in listing.output and "media" in listing.output and "resize" in listing.output


def test_list_filters_and_fits_the_terminal(admin):
    for name in ("first", "second"):
        invoke(admin, "enqueue", name + "-" + "x" * 80)
    first = admin.store.list()[0]
    first.state = JobState.FAILED
    admin.store.update(first)
    lines = invoke(admin, "list", "--state", "FAILED", columns=60).output.splitlines()
    assert len(lines) == 2 and lines[1].startswith(first.id[:12])
    assert all(len(line) <= 60 for line in lines)
    assert invoke(admin, "list", "--queue", "nope").output.strip() == "no jobs found"


def test_bad_payload_is_a_usage_error(admin):
    result = CliRunner().invoke(cli, ["enqueue", "resize", "--payload", "[1, 2]"], obj=admin)
    assert result.exit_code == 2 and admin.store.list() == []


def test_export_writes_json_and_closes_the_context(admin):
    invoke(admin, "enqueue", "resize", "--payload", '{"secret": "abc"}')
    data = json.loads(invoke(admin, "export", "--redact").output)
    assert data["jobs"][0]["payload"] == {"secret": "***"}
    assert admin.closed
