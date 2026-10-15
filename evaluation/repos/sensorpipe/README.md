# sensorpipe (benchmark fixture)

`sensorpipe` is a small industrial sensor data pipeline library written from scratch for this benchmark:

* CSV/JSON ingestion of readings with epoch, ISO 8601 and custom timestamp formats (`ingest`, `readings`)
* time-zone aware timestamps; naive values are local to the device's site (`timeutil`)
* engineering unit conversion for temperature, pressure, flow, voltage and current (`units`)
* calibration curves, gain chains, JSON calibration files with semantic format versions and bundled RTD /
  thermocouple / thermistor tables (`calibration`, `tables/`)
* numpy-based resampling, windowed statistics and flow integration (`resample`)
* anomaly detection: z-score, rolling bounds and device fault codes, extensible through entry-point plugins
  (`anomaly`, `plugins`)
* device registry with firmware version gating (`devices`)
* YAML pipeline configuration validated with pydantic, runtime settings from `SENSORPIPE_*` variables (`config`)
* SQLite store-and-forward buffer, background uplink forwarder and tarball archiving of batches (`buffer`,
  `uplink`, `archive`)
* report export (CSV/JSON), pipeline orchestration and a click CLI (`report`, `pipeline`, `cli`)

The baseline deliberately pins old releases of its dependencies (numpy 1.26.4, packaging 21.3,
ruamel.yaml 0.17.40, arrow 0.17.0, pydantic 1.10.21, click 7.1.2, semver 2.13.0, importlib-metadata 4.13.0) and
uses APIs that later releases removed or deprecated; the maintenance tasks in `evaluation/tasks/sensorpipe-*`
build on that.

`wheelhouse.txt` lists every pin needed by the baseline and by all task solutions, including transitive
dependencies. It contains two versions of several packages, so pip cannot resolve the file in a single
`pip download -r` call; download it one requirement at a time (e.g. `--no-deps` per line) or as the two sections
(baseline / upgrade targets) separately.

## Licence

All code and data in this fixture are original work released under the MIT licence.

Copyright (c) 2026 the benchmark authors

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of
the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
