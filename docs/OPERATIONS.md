# Operations

## Processes

| Process | Command | Notes |
| --- | --- | --- |
| API | `python -m modernisation.cli api --host 127.0.0.1 --port 8000` | stateless; run several behind a proxy if needed |
| Worker | `python -m modernisation.cli worker` | must start as root to drop to the sandbox uid; run several for parallelism |
| Migrations | `alembic upgrade head` (in `backend/`) | run before starting API/workers |
| Local model | `scripts/local_model_server.sh start 1.5b` | optional OpenAI-compatible endpoint on 127.0.0.1:8081 |

Workers are safe to run concurrently: tasks are claimed with `SKIP LOCKED` and leases. Stopping a worker (SIGTERM)
finishes the current step boundary; killing it (SIGKILL) is also safe: its lease expires after
`MODERNISATION_WORKER_LEASE_S` (default 120 s) and another worker resumes the task.

## Host preparation (bare metal / VM)

```bash
sudo apt-get install -y bubblewrap git postgresql
sudo groupadd --system --gid 9100 modsandbox
sudo useradd --system --uid 9100 --gid 9100 --no-create-home --shell /usr/sbin/nologin modsandbox
# Ubuntu 24.04+: allow unprivileged user namespaces for bubblewrap
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
scripts/build_wheelhouse.sh            # offline package mirror for sandboxed installs
```

The data directory (`MODERNISATION_DATA_DIR`) and all its parents must be traversable (`o+x`) by uid 9100, because the
sandbox user bind-mounts workspaces from it.

## Configuration

All settings are environment variables with the `MODERNISATION_` prefix; see `.env.example` and
`backend/src/modernisation/config.py`. Important ones:

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | local dev database | SQLAlchemy URL (`postgresql+psycopg://...`) |
| `DATA_DIR` | `.data` | mirrors, workspaces, environments, traces |
| `ALLOWED_LOCAL_ROOTS` | `[]` | JSON list of directories local repositories may live under |
| `ALLOWED_GITHUB_REPOSITORIES` | `[]` | JSON list of `owner` or `owner/repo` |
| `MODEL_PROVIDER` | `none` | `openai_compatible`, `anthropic` or `none` |
| `MODEL_BASE_URL`, `MODEL_NAME`, `MODEL_API_KEY` | | model endpoint |
| `MODEL_STRUCTURED_OUTPUT` | `json_schema` | `json_object_schema` for llama.cpp |
| `MODEL_PRICE_INPUT_PER_MTOK`, `MODEL_PRICE_OUTPUT_PER_MTOK` | unset | enables cost accounting |
| `WHEELHOUSE_DIR` | unset | offline wheels mounted read-only into the sandbox |
| `SANDBOX_COMMAND_TIMEOUT_S` | 300 | per-command wall clock |
| `SANDBOX_MEMORY_MB`, `SANDBOX_MAX_PROCESSES`, `SANDBOX_MAX_FILE_MB` | 2048, 256, 256 | per-command limits |
| `DEFAULT_MAX_ATTEMPTS` | 3 | patch attempt budget |
| `REQUIRE_PLAN_APPROVAL` | false | require human approval of plans |
| `API_TOKEN` | unset | bearer token for mutating endpoints |
| `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET` | unset | GitHub integration |
| `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL` | platform identity | author of commits the platform creates for PRs |
| `OTEL_EXPORTER` | `none` | `console` or `jsonl` (`<data_dir>/traces.jsonl`) |

## Observability

* Logs: one JSON object per line on stderr (`ts`, `level`, `logger`, `msg`, extra fields), with secrets redacted.
* Task event log: `GET /api/tasks/{id}/events` (state changes, tool executions, model calls, checks, errors,
  approvals, external actions).
* Model accounting: `model_calls` table (purpose, status, retry index, tokens, latency, cost) and
  `GET /api/tasks/{id}/model-calls`.
* Tracing: OpenTelemetry spans `model.complete` with `gen_ai.*` attributes.

## Recovery runbook

| Symptom | Action |
| --- | --- |
| Task stuck in a running state | Check `lease_expires_at`; if a worker died the lease expires and another worker resumes it. |
| Task `FAILED` after transient errors (model or GitHub outage) | Fix the dependency, then `POST /api/tasks/{id}/restart`. |
| Task `ESCALATED` | Read `state_reason` and the event log; adjust scope or request, then restart. |
| Duplicate pull request suspected | Inspect `external_actions` for the task; keys are unique per task/branch, so a second PR row cannot exist. |
| Database restarted | API and workers reconnect automatically (`pool_pre_ping`); in-flight steps are retried. |
| Disk usage | Remove `data_dir/workspaces/task-*` for finished tasks and unused `data_dir/envs/*` (rebuilt on demand). |

## Backups

Back up PostgreSQL. The data directory is reconstructible: mirrors can be re-fetched, workspaces are rebuilt from
`base_commit + diff`, environments from the wheelhouse.
