# Benchmark authoring specification

This document defines how fixture repositories and maintenance tasks are written. The benchmark measures
whether an agent can complete realistic maintenance work; it is only meaningful if every task is correct,
independent, reproducible and free of answer leakage. **Every task must pass the validator** before it is
used for evaluation.

## Layout

```
evaluation/
  repos/<repo>/base/                 the fixture project at its clean baseline
  repos/<repo>/wheelhouse.txt        exact pins (with transitive dependencies) for base and all tasks
  repos/<repo>/README.md             what the project is; licence statement
  tasks/<repo>-<cat>-<nn>/task.yaml
  tasks/<repo>-<cat>-<nn>/setup/...       overlay files: turn the baseline into the task's starting state
  tasks/<repo>-<cat>-<nn>/solution/...    reference solution overlay (applied on top of the task start)
  tasks/<repo>-<cat>-<nn>/acceptance/test_*.py   protected acceptance tests
```

`<cat>` is `dep` (dependency_upgrade), `mig` (deprecated_api_migration) or `bug` (bug_fix); `<nn>` is
`01`..`08`. The task directory name must equal the `id` in `task.yaml`.

Overlays contain **complete files** (not patches). `setup_delete:` in task.yaml lists baseline files to delete
at the task start (rarely needed).

## Fixture repository requirements

* Original code written for this benchmark, MIT licensed (state this in `repos/<repo>/README.md`). Do not copy
  third-party projects.
* A realistic small library or service: 600–1500 lines of Python source in `base/src/<package>/` across at
  least 6 modules with real interdependencies (imports between modules), plus docstrings where natural.
* `base/pyproject.toml` with `[project]` name/version/`requires-python = ">=3.12"` and
  `[tool.pytest.ini_options] testpaths = ["tests"]`.
* `base/requirements.txt`: exact runtime pins (`name==version`) of every direct dependency.
* `base/requirements-dev.txt`: `pytest==8.3.5` (and nothing that requires network).
* `base/tests/`: 30–70 fast, deterministic tests (no network, no wall-clock or timezone dependence, seeded
  randomness, no sleeps). The full suite must pass at the baseline and finish in under 20 seconds.
* Target Python is **3.12** (the sandbox interpreter is `/usr/bin/python3.12`).

## Dependencies and the offline wheelhouse

The sandbox has **no network**. Every package (old and new versions, including transitive dependencies) must
be available as a wheel in the shared wheelhouse `/home/user/genai-code-modernisation/.data/wheelhouse`.

* Only use packages with **cp312 or pure-Python (`py3-none-any` / `py2.py3-none-any`) wheels on PyPI** for every
  version you pin. Do not rely on sdists.
* List every pin you need (base pins, every task's target pins, and their transitive dependencies) in
  `repos/<repo>/wheelhouse.txt`, one `name==version` per line.
* `wheelhouse.txt` normally pins two versions of the same package (old and upgrade target), so it cannot be
  resolved as one requirements file. Download it line by line with `--no-deps` using
  `scripts/build_wheelhouse.sh` (which is also how the wheelhouse is rebuilt from scratch before evaluation). Because
  `--no-deps` is used, the list must name every transitive dependency explicitly; environments resolve only against
  the wheels listed, which keeps them reproducible.
* pytest 8.3.5 and 9.1.1 are already in the wheelhouse. Note pytest 9 needs `packaging>=22`; that is why
  `requirements-dev.txt` pins `pytest==8.3.5`.

## Task counts per repository (exactly 20)

| Category | Total | dev split | heldout split |
| --- | ---: | ---: | ---: |
| dependency_upgrade (`dep-01`..`dep-08`) | 8 | 2 (`dep-01`, `dep-02`) | 6 |
| deprecated_api_migration (`mig-01`..`mig-06`) | 6 | 1 (`mig-01`) | 5 |
| bug_fix (`bug-01`..`bug-06`) | 6 | 1 (`bug-01`) | 5 |

## task.yaml

```yaml
id: ledgerkit-dep-03
repo: ledgerkit
category: dependency_upgrade        # dependency_upgrade | deprecated_api_migration | bug_fix
split: heldout                      # dev | heldout
title: Upgrade pydantic to 2.x
request: |
  Issue text written as a maintainer would file it. State the requirement and observable symptoms.
  Never paste solution code. For upgrades, name the exact target version and say it must be pinned
  exactly in requirements.txt.
allowed_paths: ["src/**", "tests/**", "requirements.txt", "pyproject.toml"]
acceptance:
  pytest_args: ["-W", "error::DeprecationWarning"]   # optional extra args for the acceptance run
max_attempts: 3                     # optional, default 3
notes: |
  Optional author notes (not shown to the agent): what changed and why the acceptance tests detect it.
```

Only `title` and `request` are shown to the agent.

Note: `shutil.rmtree(onerror=...)` is documented as deprecated in 3.12 but CPython 3.12.3 emits no runtime
warning for it (verified by fixture authors), so it cannot drive a warning-based acceptance test.

## Category rules

### dependency_upgrade
* Starting state: an old pinned version of a library whose newer release has **breaking API changes** that the
  repository's code actually uses (removed functions, changed signatures or return types, renamed options).
  The baseline may already pin the old version, or the setup overlay may pin it.
* Request: "Upgrade <dist> from <old> to <new> and pin it exactly in requirements.txt. ..." plus context such as
  a security advisory or a downstream requirement. Do not describe which call sites break.
* Reference solution: bump the pin (and any co-required pins) and adapt all affected code.
* Acceptance tests must check (a) `importlib.metadata.version("<dist>")` equals the new version and (b) the
  behaviour of every affected code path under the new version. They must fail at the starting state.
* Each upgrade task must target a different library within a repository.

### deprecated_api_migration
* Starting state: code using an API that emits a `DeprecationWarning` (or subclass) on Python 3.12 or in a pinned
  library version, e.g. `datetime.utcnow()`, `datetime.utcfromtimestamp()`, `logging.warn`, `Thread.setDaemon`,
  `Event.isSet`, `asyncio.get_event_loop()` with no running loop, `locale.getdefaultlocale()`,
  `importlib.resources.read_text/open_text`, `pkgutil.find_loader`, `tarfile.extractall` without `filter`,
  the sqlite3 default datetime adapter, truth-testing an
  `xml.etree.ElementTree.Element`, `ast.Num`/`ast.Str`, deprecated stdlib modules (`cgi`, `pipes`, `imghdr`, ...),
  numpy `np.product`/`np.cumproduct`/`np.alltrue`, etc.
* Request: names the deprecated API (as a real deprecation report would) and the behaviour that must be kept.
* Acceptance tests run with `pytest_args: ["-W", "error::DeprecationWarning"]` (or the specific warning class),
  exercise the migrated code paths, and assert behaviour is preserved (types, time zones, ordering, errors).
  They may also read source files under `os.environ["REPO_ROOT"]` (`/work`) to assert the deprecated call is gone.

### bug_fix
* Starting state: the setup overlay injects a realistic defect (boundary condition, wrong operator, mutable
  default, timezone handling, wrong sort key, state not reset, encoding, rounding, swapped arguments ...).
* The repository's visible tests must still pass at the starting state (the bug is untested), as in real life.
* Request: a bug report describing symptoms and expected behaviour with a concrete example. Do not name the
  faulty line or the fix.
* Acceptance tests reproduce the report and check closely related behaviour.

## Quality rules

* Tasks in the same repository must be independent (each starts from baseline + its own setup overlay).
* Acceptance tests must be deterministic, test behaviour rather than one exact implementation, and accept any
  reasonable correct fix. Do not assert on exact source text except to verify that a deprecated call is gone.
* Requests must not contain solution code (the validator rejects requests containing any added solution line of
  30+ characters).
* `allowed_paths` must include every file the reference solution changes; prefer
  `["src/**", "tests/**", "requirements.txt", "requirements-dev.txt", "pyproject.toml"]`.
* Never modify files outside `evaluation/repos/<your repo>/` and `evaluation/tasks/<your repo>-*`.

## Validation

```
cd backend
export MODERNISATION_DATA_DIR=/home/user/genai-code-modernisation/.data \
       MODERNISATION_WHEELHOUSE_DIR=/home/user/genai-code-modernisation/.data/wheelhouse \
       MODERNISATION_LOG_LEVEL=WARNING
.venv/bin/python -m modernisation.evaluation validate --tasks <id1>,<id2>,...
```

The validator materialises each task in the real sandbox and checks: environment builds; repository tests
pass at the task start; acceptance fails at the task start; the reference solution passes acceptance with no
regressions; the solution stays within `allowed_paths`; the request does not leak solution code.
