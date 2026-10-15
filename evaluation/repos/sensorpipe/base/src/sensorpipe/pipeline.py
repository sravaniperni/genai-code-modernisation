"""Pipeline orchestration: run the configured stages over ingested readings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sensorpipe.anomaly import Anomaly
from sensorpipe.calibration import load_bundled_table, load_calibration
from sensorpipe.config import PipelineConfig, StageConfig, load_pipeline_config
from sensorpipe.errors import ConfigError
from sensorpipe.ingest import group_batches, read_csv, read_json
from sensorpipe.plugins import create_detector
from sensorpipe.readings import ReadingBatch
from sensorpipe.report import export_csv, export_json, report_filename, summarise
from sensorpipe.resample import batch_series, resample
from sensorpipe.timeutil import UTC
from sensorpipe.units import convert_reading

Key = tuple[str, str]


@dataclass
class PipelineResult:
    batches: dict[Key, ReadingBatch]
    anomalies: dict[Key, list[Anomaly]] = field(default_factory=dict)
    outputs: list[Path] = field(default_factory=list)


class Pipeline:
    def __init__(self, config: PipelineConfig, base_dir: str | Path = "."):
        self.config = config
        self.base_dir = Path(base_dir)

    @classmethod
    def from_file(cls, path: str | Path) -> Pipeline:
        return cls(load_pipeline_config(path), base_dir=Path(path).parent)

    def load(self) -> dict[Key, ReadingBatch]:
        src = self.config.source
        path = self.base_dir / src.path
        if src.format == "json":
            return group_batches(read_json(path, tz=src.timezone))
        return group_batches(read_csv(path, device_id=src.device_id, channel=src.channel, unit=src.unit,
                                      tz=src.timezone, timestamp_format=src.timestamp_format))

    def run(self) -> PipelineResult:
        result = PipelineResult(self.load())
        for stage in self.config.stages:
            if stage.kind == "export":
                self._export(stage, result)
                continue
            handler = getattr(self, f"_{stage.kind}")
            for key, batch in list(result.batches.items()):
                result.batches[key] = handler(key, batch, dict(stage.options), result)
        return result

    def _convert(self, key: Key, batch: ReadingBatch, options: dict[str, Any], result: PipelineResult) -> ReadingBatch:
        unit = options.get("unit") or self.config.target_unit
        if not unit:
            raise ConfigError("the convert stage needs a 'unit' option or a target_unit")
        return ReadingBatch(convert_reading(r, unit) for r in batch)

    def _calibrate(self, key: Key, batch: ReadingBatch, options: dict[str, Any], result: PipelineResult) -> ReadingBatch:
        if "table" in options:
            curve = load_bundled_table(options["table"])
        elif "file" in options:
            curve = load_calibration(self.base_dir / options["file"])
        else:
            raise ConfigError("the calibrate stage needs a 'table' or 'file' option")
        values = curve.apply_array(batch.values())
        return ReadingBatch(r.with_value(v, curve.unit or r.unit) for r, v in zip(batch, values))

    def _resample(self, key: Key, batch: ReadingBatch, options: dict[str, Any], result: PipelineResult) -> ReadingBatch:
        times, values = resample(*batch_series(batch), float(options.get("interval", 60)), options.get("how", "mean"))
        return ReadingBatch.from_arrays(times, values, device_id=key[0], channel=key[1], unit=batch.unit or "")

    def _detect(self, key: Key, batch: ReadingBatch, options: dict[str, Any], result: PipelineResult) -> ReadingBatch:
        detector = create_detector(options.pop("detector", "zscore"), **options)
        result.anomalies[key] = detector.detect(batch.values())
        return batch

    def _export(self, stage: StageConfig, result: PipelineResult) -> None:
        summaries = [summarise(b, len(result.anomalies.get(k, []))) for k, b in result.batches.items() if len(b)]
        if not summaries:
            return
        fmt = stage.options.get("format", "csv")
        out_dir = self.base_dir / stage.options.get("dir", "reports")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / report_filename(min(s.first for s in summaries), fmt)
        text = export_csv(summaries) if fmt == "csv" else export_json(summaries, datetime.now(UTC))
        path.write_text(text, encoding="utf-8")
        result.outputs.append(path)
