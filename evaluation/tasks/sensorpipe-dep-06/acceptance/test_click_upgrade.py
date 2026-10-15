import importlib.metadata

import click
from click.testing import CliRunner

from sensorpipe.cli import cli


def invoke(args, **kwargs):
    return CliRunner().invoke(cli, args, obj={}, **kwargs)


def test_click_is_pinned_to_8_1_8():
    assert importlib.metadata.version("click") == "8.1.8"


def test_single_and_chained_commands():
    result = invoke(["convert", "1", "bar", "kPa"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["1 bar = 100.0000 kPa", "-- 1 command(s) completed"]
    result = invoke(["convert", "0", "degC", "K", "calibrate", "--table", "pt100", "119.40", "convert", "2", "bar", "kPa"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "0 degC = 273.1500 K", "119.4 -> 50.000 degC", "2 bar = 200.0000 kPa", "-- 3 command(s) completed",
    ]


def test_errors_exit_with_code_1():
    result = invoke(["convert", "1", "bar", "degC"])
    assert result.exit_code == 1
    assert "cannot convert pressure" in result.output
    result = invoke(["calibrate", "--table", "pt9999", "100"])
    assert result.exit_code == 1 and "pt9999" in result.output


def test_summary_lines_fit_the_terminal(tmp_path):
    data = tmp_path / "readings.csv"
    data.write_text("timestamp,device_id,channel,value,unit\n"
                    "2024-01-15T08:00:00Z,BOILER-HOUSE-NORTH-SUPPLY-TT-101,temperature,20,degC\n")
    wide = invoke(["summary", str(data)], env={"COLUMNS": "200"})
    assert wide.exit_code == 0, wide.output
    line = "BOILER-HOUSE-NORTH-SUPPLY-TT-101/temperature: n=1 mean=20.000 min=20.000 max=20.000 degC"
    assert wide.output.splitlines()[0] == line
    narrow = invoke(["summary", str(data)], env={"COLUMNS": "40"})
    first = narrow.output.splitlines()[0]
    assert len(first) <= 40 and first.endswith("...") and line.startswith(first[:-3])


def test_check_config_and_tz_option(tmp_path):
    config = tmp_path / "pipeline.yaml"
    config.write_text("name: demo\nsource: {path: readings.csv}\nstages: [{kind: resample}, {kind: export}]\n")
    result = invoke(["--tz", "Europe/Berlin", "check-config", str(config)])
    assert result.output.splitlines() == ["demo: 2 stage(s) OK", "-- 1 command(s) completed"]
    config.write_text("name: demo\nsource: {path: readings.csv}\nstages: []\n")
    assert invoke(["check-config", str(config)]).exit_code == 1


def test_table_option_completes_bundled_tables():
    command = cli.commands["calibrate"]
    option = next(p for p in command.params if p.name == "table")
    ctx = click.Context(command, info_name="calibrate")
    assert [item.value for item in option.shell_complete(ctx, "pt")] == ["pt100"]
    assert sorted(item.value for item in option.shell_complete(ctx, "")) == ["ntc10k", "pt100", "type_k"]
