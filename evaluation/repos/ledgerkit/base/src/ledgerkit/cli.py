"""Command line interface: ``ledgerkit --ledger books.json <command>``. Subcommands return a message
or a ``(headers, rows)`` table that the group's result callback renders."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import click

from ledgerkit import formats, reports
from ledgerkit.errors import LedgerError
from ledgerkit.importers import read_csv
from ledgerkit.journal import Ledger

DATE = click.DateTime(formats=["%Y-%m-%d"])


class LedgerGroup(click.Group):
    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except LedgerError as exc:
            raise click.ClickException(str(exc)) from exc


def _path(ctx: click.Context) -> Path:
    path = ctx.find_root().params.get("ledger_path")
    if not path:
        raise click.UsageError("no ledger file given (use --ledger or LEDGERKIT_FILE)")
    return Path(path)


def _load(ctx: click.Context) -> tuple[Ledger, dict[str, Any]]:
    return formats.load_ledger(_path(ctx).read_text(encoding="utf-8"))


def complete_account(ctx: click.Context, args: list[str], incomplete: str) -> list[tuple[str, str]]:
    """Shell completion for account codes (with account names as help) from the ledger in use."""
    try:
        ledger = _load(ctx)[0]
    except (click.UsageError, OSError, LedgerError):
        return []
    return [(a.code, a.name) for a in ledger.chart if a.code.startswith(incomplete)]


@click.group(cls=LedgerGroup)
@click.option("--ledger", "ledger_path", type=click.Path(dir_okay=False), envvar="LEDGERKIT_FILE",
              help="Ledger JSON document to operate on.")
@click.option("--format", "output", type=click.Choice(["table", "json", "csv"]), default="table", show_default=True)
def cli(ledger_path: str | None, output: str) -> None:
    """Inspect and update ledgerkit ledger documents."""


@cli.resultcallback()
def render(result: Any, ledger_path: str | None, output: str) -> None:
    if result is None or isinstance(result, str):
        if result:
            click.echo(result)
        return
    headers, rows = result
    if output == "json":
        click.echo(json.dumps([dict(zip(headers, map(str, row))) for row in rows], indent=2))
    elif output == "csv":
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerows([headers, *rows])
        click.echo(buffer.getvalue(), nl=False)
    else:
        click.echo(reports.render_table(headers, rows, width=click.get_terminal_size()[0]))


@cli.command()
@click.argument("account", autocompletion=complete_account)
@click.option("--as-of", type=DATE, help="Only include entries up to this date.")
@click.pass_context
def balance(ctx: click.Context, account: str, as_of: Any) -> str:
    """Show the balance of one account."""
    ledger = _load(ctx)[0]
    amount = ledger.balance(account, end=as_of.date() if as_of else None)
    return f"{account} {ledger.chart.get(account).name}: {amount}"


@cli.command("trial-balance")
@click.option("--as-of", type=DATE)
@click.pass_context
def trial_balance_cmd(ctx: click.Context, as_of: Any) -> tuple[list[str], list[tuple]]:
    """Print the trial balance."""
    report = reports.trial_balance(_load(ctx)[0], as_of=as_of.date() if as_of else None)
    rows = [(line.code, line.name, line.debit, line.credit) for line in report.lines]
    return ["code", "account", "debit", "credit"], [*rows, ("", "Total", report.total_debit, report.total_credit)]


@cli.command("import-csv")
@click.argument("csv_file", type=click.File("r", encoding="utf-8"))
@click.option("--decimal", "decimal_sep", default=".", show_default=True, help="Decimal separator.")
@click.option("--thousands", "thousands_sep", default=",", show_default=True, help="Thousands separator.")
@click.pass_context
def import_csv(ctx: click.Context, csv_file: Any, decimal_sep: str, thousands_sep: str) -> str:
    """Post the entries of a CSV file to the ledger."""
    ledger, meta = _load(ctx)
    entries = ledger.post_many(read_csv(csv_file, decimal_sep=decimal_sep, thousands_sep=thousands_sep))
    _path(ctx).write_text(formats.dump_ledger(ledger, meta=meta), encoding="utf-8")
    return f"imported {len(entries)} entries"


def main() -> None:  # console-script entry point
    cli(prog_name="ledgerkit")
