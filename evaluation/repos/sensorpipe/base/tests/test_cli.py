from click.testing import CliRunner

from sensorpipe.cli import cli


def invoke(*args):
    return CliRunner().invoke(cli, list(args), obj={})


def test_convert_command():
    result = invoke("convert", "1", "bar", "kPa")
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["1 bar = 100.0000 kPa", "-- 1 command(s) completed"]


def test_chained_commands():
    result = invoke("convert", "0", "degC", "K", "calibrate", "--table", "pt100", "119.40")
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["0 degC = 273.1500 K", "119.4 -> 50.000 degC", "-- 2 command(s) completed"]


def test_errors_are_reported():
    result = invoke("convert", "1", "bar", "degC")
    assert result.exit_code == 1
    assert "cannot convert pressure" in result.output


def test_summary_and_check_config(tmp_path):
    data = tmp_path / "readings.csv"
    data.write_text("timestamp,device_id,channel,value,unit\n2024-01-15T08:00:00Z,TT-101,temp,20,degC\n"
                    "2024-01-15T08:01:00Z,TT-101,temp,22,degC\n")
    config = tmp_path / "pipeline.yaml"
    config.write_text("name: demo\nsource: {path: readings.csv}\nstages: [{kind: export}]\n")
    result = invoke("--tz", "Europe/Berlin", "summary", str(data), "check-config", str(config))
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "TT-101/temp: n=2 mean=21.000 min=20.000 max=22.000 degC", "demo: 1 stage(s) OK", "-- 2 command(s) completed",
    ]
