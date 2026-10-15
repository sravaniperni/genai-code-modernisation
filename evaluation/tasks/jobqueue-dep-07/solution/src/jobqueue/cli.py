"""The ``jobqueue`` administration command line."""

from __future__ import annotations

import json
import shutil
from typing import Any

import click

from jobqueue.errors import JobQueueError
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.serialization import dump_jobs
from jobqueue.sqlstore import SQLJobStore
from jobqueue.store import JobStore


class AdminContext:
    """State shared by the commands of one invocation; the store is opened on first use."""

    def __init__(self, db_url: str = "sqlite://", *, store: JobStore | None = None):
        self.db_url, self._store, self._owns_store, self.closed = db_url, store, store is None, False

    @property
    def store(self) -> JobStore:
        if self._store is None:
            self._store = SQLJobStore(self.db_url)
        return self._store

    def close(self) -> None:
        if self._owns_store and self._store is not None:
            self._store.close()
            self._store = None
        self.closed = True


def _complete_queue(ctx: click.Context, param: click.Parameter, incomplete: str) -> list[str]:
    admin = ctx.find_object(AdminContext)
    return [name for name in admin.store.queues() if name.startswith(incomplete)] if admin else []


def _fit(line: str, width: int) -> str:
    return line if len(line) <= width else line[: max(width - 3, 0)] + "..."


@click.group()
@click.option("--db", "db_url", envvar="JOBQUEUE_DB", default="sqlite:///jobqueue.db", show_default=True,
              help="SQLAlchemy URL of the job database.")
@click.pass_context
def cli(ctx: click.Context, db_url: str) -> None:
    """Inspect and administer a jobqueue database."""
    if ctx.obj is None:
        ctx.obj = AdminContext(db_url)


@cli.result_callback()
def _close_store(result: Any, **params: Any) -> None:
    click.get_current_context().find_object(AdminContext).close()


@cli.command("list")
@click.option("--state", type=click.Choice([s.value for s in JobState], case_sensitive=False))
@click.option("--queue", shell_complete=_complete_queue, help="Only jobs from this queue.")
@click.option("--limit", type=click.IntRange(1, 10_000), default=50, show_default=True)
@click.pass_obj
def list_jobs(admin: AdminContext, state: str | None, queue: str | None, limit: int) -> None:
    """List jobs, oldest first; lines are cut to the terminal width."""
    jobs = admin.store.list(state=JobState(state.lower()) if state else None, queue=queue, limit=limit)
    if not jobs:
        click.echo("no jobs found")
        return
    width = shutil.get_terminal_size().columns
    click.echo(_fit(f"{'ID':<12} {'STATE':<10} {'PRI':>3} {'TRIES':>5}  {'QUEUE':<12} NAME", width))
    for job in jobs:
        tries = f"{job.attempts}/{job.max_attempts}"
        click.echo(_fit(f"{job.id[:12]:<12} {job.state.value:<10} {job.priority:>3} {tries:>5}  "
                        f"{job.queue[:12]:<12} {job.name}", width))


@cli.command()
@click.argument("name")
@click.option("--payload", default="{}", show_default=True, help="JSON object passed to the handler.")
@click.option("--queue", default="default", show_default=True)
@click.option("--priority", type=click.IntRange(0, 9), default=5, show_default=True)
@click.option("--delay", type=click.FloatRange(0), default=0.0, help="Seconds before the job becomes due.")
@click.pass_obj
def enqueue(admin: AdminContext, name: str, payload: str, queue: str, priority: int, delay: float) -> None:
    """Submit a job and print its id."""
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise click.BadParameter(f"not valid JSON ({exc})", param_hint="--payload") from exc
    if not isinstance(data, dict):
        raise click.BadParameter("must be a JSON object", param_hint="--payload")
    try:
        click.echo(JobQueue(admin.store).enqueue(name, data, queue=queue, priority=priority, delay=delay).id)
    except JobQueueError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command("export")
@click.option("--redact", is_flag=True, help="Mask payload values.")
@click.pass_obj
def export_jobs(admin: AdminContext, redact: bool) -> None:
    """Write all jobs as JSON to standard output."""
    click.echo(dump_jobs(admin.store.list(), redact_payload=redact))


def main() -> None:
    cli(prog_name="jobqueue")
