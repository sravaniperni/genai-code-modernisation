import importlib.metadata
import json

from click.testing import CliRunner

from jobqueue.cli import AdminContext, cli
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.sqlstore import SQLJobStore


def run(args, admin=None, **kwargs):
    kwargs.setdefault("env", {"COLUMNS": "200"})
    return CliRunner().invoke(cli, args, obj=admin, prog_name="jobqueue", **kwargs)


def test_click_version_is_pinned():
    assert importlib.metadata.version("click") == "8.1.7"


def test_commands_against_a_database_file(tmp_path):
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    created = run(["--db", url, "enqueue", "thumbnail", "--payload", '{"src": "a.png"}', "--queue", "media",
                   "--priority", "9"])
    assert created.exit_code == 0, created.output
    job_id = created.output.strip()
    listing = run(["list"], env={"JOBQUEUE_DB": url, "COLUMNS": "200"})
    assert listing.exit_code == 0 and job_id[:12] in listing.output and "thumbnail" in listing.output
    exported = run(["--db", url, "export"])
    assert json.loads(exported.output)["jobs"][0]["payload"] == {"src": "a.png"}
    assert SQLJobStore(url).get(job_id).priority == 9


def test_store_is_closed_after_each_command():
    admin = AdminContext(store=SQLJobStore("sqlite://"))
    assert run(["list"], admin).exit_code == 0
    assert admin.closed
    owned = AdminContext("sqlite://")
    assert run(["enqueue", "thumbnail"], owned).exit_code == 0
    assert owned.closed


def test_list_fits_the_terminal_and_filters():
    store = SQLJobStore("sqlite://")
    queue = JobQueue(store)
    keep = queue.enqueue("generate-quarterly-report-for-every-region-and-every-product-line", queue="reports")
    other = queue.enqueue("cleanup", queue="maintenance")
    other.state = JobState.FAILED
    store.update(other)
    narrow = run(["list"], AdminContext(store=store), env={"COLUMNS": "48"})
    lines = narrow.output.splitlines()
    assert narrow.exit_code == 0 and len(lines) == 3 and all(len(line) <= 48 for line in lines)
    assert lines[1].startswith(keep.id[:12]) and lines[1].endswith("...")
    wide = run(["list", "--state", "failed"], AdminContext(store=store), env={"COLUMNS": "300"})
    assert [line[:12] for line in wide.output.splitlines()[1:]] == [other.id[:12]]
    assert run(["list", "--queue", "nothing"], AdminContext(store=store)).output.strip() == "no jobs found"


def test_bad_options_are_usage_errors():
    admin = AdminContext(store=SQLJobStore("sqlite://"))
    assert run(["enqueue", "x", "--payload", "{nope"], admin).exit_code == 2
    assert run(["enqueue", "x", "--priority", "12"], admin).exit_code == 2
    assert run(["list", "--state", "sleeping"], admin).exit_code == 2
    assert admin.store.list() == []


def test_queue_names_are_completed():
    store = SQLJobStore("sqlite://")
    queue = JobQueue(store)
    for name in ("emails", "email-digests", "media"):
        queue.enqueue("noop", queue=name)
    env = {"_JOBQUEUE_COMPLETE": "bash_complete", "COMP_WORDS": "jobqueue list --queue em", "COMP_CWORD": "3"}
    result = CliRunner().invoke(cli, [], obj=AdminContext(store=store), prog_name="jobqueue", env=env)
    values = sorted(line.split(",", 1)[1] for line in result.output.splitlines() if "," in line)
    assert values == ["email-digests", "emails"]
