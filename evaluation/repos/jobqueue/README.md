# jobqueue fixture repository

`jobqueue` is a small, self-contained Python library written for this benchmark: a lightweight persistent
job queue and scheduler. It contains

* job definitions and payload schemas validated with pydantic (`spec.py`), priorities and job records
  (`job.py`), canonical payload encoding with a byte-size limit (`payload.py`);
* an in-memory store and a SQLAlchemy-backed store (`store.py`, `sqlstore.py`; tests use in-memory SQLite);
* retries with capped exponential backoff (`retry.py`), an executor (`executor.py`) and a thread-based
  worker pool with graceful shutdown (`workers.py`), plus support for `async def` handlers (`aio.py`);
* cron-style recurring schedules evaluated with arrow (`cron.py`, `scheduler.py`);
* handler plugin discovery through importlib-metadata entry points (`registry.py`);
* signed per-job tokens with PyJWT (`tokens.py`), completion webhooks over urllib3 (`webhooks.py`; tests use
  a fake pool manager, never the network), an SQLite execution history (`history.py`);
* JSON export/import with marshmallow (`serialization.py`) and a click admin CLI (`cli.py`).

The baseline pins deliberately old versions of SQLAlchemy, pydantic, marshmallow, arrow, urllib3, PyJWT,
click and importlib-metadata and uses the APIs that changed in their next major releases; the
`jobqueue-dep-*` tasks upgrade one library each. The `jobqueue-mig-*` and `jobqueue-bug-*` tasks inject a
deprecated API or a defect through their setup overlays, so the baseline itself is warning-clean on
Python 3.12 apart from deprecations raised inside the pinned old libraries.

`wheelhouse.txt` lists every wheel needed by the baseline and all tasks (old and new versions and their
transitive dependencies). Because it contains two versions of several packages, pip cannot resolve the file
in one invocation; download it one requirement at a time, e.g.

```
while read -r pin; do
  printf '%s\n' "$pin" > /tmp/pin.txt
  python3.12 -m pip download --only-binary=:all: --python-version 3.12 --platform manylinux2014_x86_64 \
    --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 --platform any \
    -d .data/wheelhouse -r /tmp/pin.txt
done < evaluation/repos/jobqueue/wheelhouse.txt
```

## Licence

The fixture code, tests and task material are original work written for this benchmark and are released
under the MIT licence (see `base/LICENSE`).
