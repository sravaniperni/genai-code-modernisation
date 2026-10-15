"""Command line interface (``sensorpipe``). Commands can be chained: ``sensorpipe convert ... summary ...``."""

from __future__ import annotations

from typing import Any

import click

from sensorpipe.calibration import list_bundled_tables, load_bundled_table
from sensorpipe.config import load_pipeline_config
from sensorpipe.errors import SensorPipeError
from sensorpipe.ingest import group_batches, load_file
from sensorpipe.report import summarise
from sensorpipe.units import convert


def _complete_tables(ctx: Any, args: list[str], incomplete: str) -> list[str]:
    return [name for name in list_bundled_tables() if name.startswith(incomplete)]


def _fit(line: str) -> str:
    """Truncate a line to the terminal width."""
    width = click.get_terminal_size()[0]
    return line if len(line) <= width else line[: max(width - 3, 20)] + "..."


@click.group(chain=True)
@click.option("--tz", default="UTC", show_default=True, help="Time zone of naive timestamps in input files.")
@click.pass_context
def cli(ctx: click.Context, tz: str) -> None:
    """Industrial sensor data pipeline tools."""
    ctx.ensure_object(dict)["tz"] = tz


@cli.resultcallback()
def _report_completion(results: list[Any], tz: str) -> None:
    click.echo(f"-- {len(results)} command(s) completed")


@cli.command("convert")
@click.argument("value", type=float)
@click.argument("from_unit")
@click.argument("to_unit")
def convert_cmd(value: float, from_unit: str, to_unit: str) -> float:
    """Convert VALUE from FROM_UNIT to TO_UNIT."""
    try:
        result = convert(value, from_unit, to_unit)
    except SensorPipeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{value:g} {from_unit} = {result:.4f} {to_unit}")
    return result


@cli.command("calibrate")
@click.argument("raw", type=float)
@click.option("--table", required=True, autocompletion=_complete_tables, help="Bundled calibration table.")
def calibrate_cmd(raw: float, table: str) -> float:
    """Calibrate a RAW sensor value with a bundled table."""
    try:
        curve = load_bundled_table(table)
        value = curve.apply(raw)
    except SensorPipeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{raw:g} -> {value:.3f} {curve.unit}")
    return value


@cli.command("summary")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def summary_cmd(ctx: click.Context, path: str) -> int:
    """Print per-channel statistics of a CSV or JSON reading file."""
    try:
        batches = group_batches(load_file(path, tz=ctx.obj["tz"]))
    except SensorPipeError as exc:
        raise click.ClickException(str(exc)) from exc
    for (device, channel), batch in batches.items():
        s = summarise(batch)
        click.echo(_fit(f"{device}/{channel}: n={s.count} mean={s.mean:.3f} min={s.minimum:.3f} "
                        f"max={s.maximum:.3f} {s.unit}"))
    return len(batches)


@cli.command("check-config")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def check_config_cmd(path: str) -> str:
    """Validate a pipeline configuration file."""
    try:
        config = load_pipeline_config(path)
    except SensorPipeError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{config.name}: {len(config.stages)} stage(s) OK")
    return config.name


def main() -> None:
    cli(obj={})
