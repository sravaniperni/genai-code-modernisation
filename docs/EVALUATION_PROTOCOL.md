# Evaluation protocol

## Task set

* Five fixture repositories written for this benchmark (MIT): `ledgerkit`, `webhookrelay`, `sensorpipe`,
  `releasebot`, `jobqueue`. They are original code, so they are legally usable and not present in any model's training
  data verbatim. They are small (hundreds to low thousands of lines), which is a limitation (see below).
* 100 tasks: 40 dependency upgrades, 30 deprecated API migrations, 30 bug fixes (8/6/6 per repository).
* Splits: 20 **dev** tasks (used while developing prompts and heuristics) and 80 **held-out** tasks. Headline numbers
  are reported on the held-out split; dev results are reported separately.
* Format and authoring rules: `evaluation/AUTHORING.md`.

## Integrity controls

1. **Validation** (`python -m modernisation.evaluation validate`): every task is materialised in the real sandbox and
   must satisfy: environment builds; repository tests pass at the task start; protected acceptance tests **fail** at the
   task start; the reference solution passes acceptance with no regressions; the solution stays within
   `allowed_paths`; the request contains no solution code. The report is stored in
   `evaluation/validation-report.json`.
2. **Freezing**: `python -m modernisation.evaluation lock` writes `evaluation/TASKSET.lock` with a content hash of all
   tasks and fixtures. `run --final` refuses to run if the hash differs. Results record the task-set version.
3. **Isolation of acceptance criteria**: acceptance tests and reference solutions live under `evaluation/tasks/` and
   are never part of the repository the agent sees (each task is materialised as its own single-commit repository).
   They are copied into a read-only mount only after the agent finished, by a separate evaluation step.
4. **No re-rolling**: a run is identified by its run key; re-invoking a run resumes it and never re-executes a task
   that already has a result.
5. **Denominator**: every task in the run counts, including errors, timeouts and escalations.

## Success definition

A task is successful only if all hold:

* the platform (or baseline) produced a patch: for the **platform**, the task reached `COMPLETED` after its own
  independent verification (an escalated task is a failure even if a partial diff exists);
* the patch applies to the task base and passes the change policy (no prohibited paths, no test weakening);
* the dependency environment builds from the patched manifests (offline wheelhouse);
* the protected acceptance tests pass;
* the repository's own test suite has no new failures relative to the task base;
* it was produced within the attempt budget and without human code changes (the runner never edits patches).

## Compared systems

| | Platform | Baseline |
| --- | --- | --- |
| Model | same model, same server, temperature 0 | same |
| Retrieval | hybrid (keyword + structural); excerpts of retrieved code as context | the same retrieval picks the top 3 in-scope implementation files; no additional context |
| Plan | structured plan (validated JSON) | none |
| Feedback | sandboxed checks vs baseline, failure report | none |
| Repair | up to 3 attempts in total | 1 attempt |
| Verification gate | must self-verify to deliver a patch | patch delivered regardless of its own checks |
| Sandbox limits | identical | identical |

The asymmetry in the verification gate favours the baseline: a platform patch that would have passed acceptance but
failed the platform's own checks is counted as a platform failure.

## Frozen configuration of the reported runs

| Item | Value |
| --- | --- |
| Task-set version | `29159cc0f4ce5d5a` (`evaluation/TASKSET.lock`, frozen 2026-10-15) |
| Validation | 100/100 valid (`evaluation/validation-report.json`) |
| Wheelhouse | 90 wheels rebuilt from the pinned lists only; listing SHA-256 `968959ca1e377d2a4ac65d9b1aabc50e614457d4605cda39c206f7a1fb8e3689` |
| Model | `qwen2.5-coder-1.5b-instruct-q4_k_m` via llama-cpp-python 0.3.16, 4 CPU threads, context 16,384 |
| Generation | temperature 0, max 1,024 output tokens, grammar-constrained JSON for plans |
| Context budgets | 10,000 characters of retrieved excerpts, 16,000 characters of editable file content |
| Attempt budget | platform 3, baseline 1 |
| Sandbox | 300 s per command, 2,048 MB memory, 256 processes, no network |
| Isolation of runs | dedicated PostgreSQL database and data directory, separate from development runs |

## Oracle check (harness ceiling)

Before the model runs, the complete platform workflow is executed with an *oracle* model that answers with the
reference solution as minimal SEARCH/REPLACE hunks (`mode=oracle`). It measures false negatives of the pipeline itself
(environments, verification, policy, acceptance plumbing): every oracle failure is a platform or harness defect, not a
model failure. Oracle results are reported separately and never as model performance.

The first oracle run (`oracle-all-final`) was stopped after 75 tasks because `sensorpipe-dep-01` (a **dev**-split task)
escalated with the reference solution available: repair prompts never showed a planned file that did not fit the
editable-content budget (defect 15 in `docs/FAILURE_ANALYSIS.md`). The platform was fixed and every reported run
(oracle, platform, baseline; run tag `final2`) uses the fixed revision. The task set was not changed. The aborted run is
kept in the evaluation database with status `aborted`, and its 75 rows are archived outside `reports/`.

## Commands

```bash
cd backend
export MODERNISATION_DATA_DIR=$PWD/../.data MODERNISATION_WHEELHOUSE_DIR=$PWD/../.data/wheelhouse
export MODERNISATION_MODEL_PROVIDER=openai_compatible MODERNISATION_MODEL_BASE_URL=http://127.0.0.1:8081/v1 \
       MODERNISATION_MODEL_NAME=qwen2.5-coder-1.5b-instruct-q4_k_m MODERNISATION_MODEL_STRUCTURED_OUTPUT=json_object_schema \
       MODERNISATION_MODEL_MAX_OUTPUT_TOKENS=1024
../scripts/build_wheelhouse.sh
../scripts/local_model_server.sh start 1.5b
.venv/bin/python -m modernisation.evaluation validate --out ../evaluation/validation-report.json
.venv/bin/python -m modernisation.evaluation lock
.venv/bin/python -m modernisation.evaluation run --final --mode platform --run-key <platform-key> --split all
.venv/bin/python -m modernisation.evaluation run --final --mode baseline --run-key <baseline-key> --split all
.venv/bin/python -m modernisation.evaluation report --run-keys <platform-key>,<baseline-key>
```

Per-task evidence (state, reason, attempts, tokens, latency, diff, acceptance and regression details) is appended to
`reports/runs/<run-key>.jsonl` as each task finishes; aggregate reports are regenerated from the database.

## Statistics

Completion rates are reported with Wilson 95% intervals. Platform and baseline are compared on identical tasks
(paired); the report lists tasks only one system solved. With 80 held-out tasks the interval half-width is roughly
±10 percentage points, so small differences are not meaningful.

## Known limitations

* Fixture repositories are small and authored for the benchmark; real repositories are larger and messier.
* The measured model is a 1.5B-parameter quantised model on CPU; results do not transfer to larger models.
* Acceptance tests are written by the benchmark authors and may admit or reject unusual but valid solutions.
* Dependency upgrades are limited to packages with binary or pure-Python wheels for CPython 3.12.
