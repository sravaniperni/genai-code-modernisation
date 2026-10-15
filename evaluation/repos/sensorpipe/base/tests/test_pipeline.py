import csv

from sensorpipe.pipeline import Pipeline

CONFIG = """\
name: boiler
source:
  path: readings.csv
  device_id: TT-101
  channel: temp
  unit: degF
target_unit: degC
stages:
  - kind: convert
  - kind: resample
    options: {interval: 60}
  - kind: detect
    options: {detector: zscore, threshold: 2.5}
  - kind: export
    options: {format: csv, dir: out}
"""


def test_pipeline_end_to_end(tmp_path):
    values = [68.0 + (i % 3) * 0.2 for i in range(20)]
    values[12] = 120.0
    rows = "".join(f"2024-01-15T08:{i:02d}:10Z,{v}\n" for i, v in enumerate(values))
    (tmp_path / "readings.csv").write_text("timestamp,value\n" + rows)
    (tmp_path / "pipeline.yaml").write_text(CONFIG)
    result = Pipeline.from_file(tmp_path / "pipeline.yaml").run()
    batch = result.batches[("TT-101", "temp")]
    assert len(batch) == 20 and batch.unit == "degC"
    assert round(batch[0].value, 3) == 20.0
    assert [a.index for a in result.anomalies[("TT-101", "temp")]] == [12]
    (report,) = result.outputs
    assert report.name == "sensorpipe-report-1705305600.csv"
    with open(report, newline="") as handle:
        (row,) = list(csv.DictReader(handle))
    assert row["count"] == "20" and row["anomalies"] == "1"
