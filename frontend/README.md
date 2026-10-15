# Frontend

Web UI for the codebase modernisation platform. It is a client of the FastAPI backend in `../backend`
and nothing else: every number, file, event and result on screen comes from the API. When the API has
nothing to report the UI says so (for example, the evaluation screen shows
"No evaluation results available." when there are no runs).

Stack: Vite, React 18, TypeScript (strict), react-router, @tanstack/react-query, plain CSS (light and dark
via `prefers-color-scheme`), hand-written SVG charts. Tests use Vitest + Testing Library (unit and
component) and Playwright (end-to-end against the real backend).

## Running it

```bash
cd frontend
npm ci
npm run dev            # http://localhost:5173, proxies /api to http://127.0.0.1:8000
```

Start the backend separately (see `../backend`), e.g.
`cd backend && .venv/bin/python -m modernisation.cli api --port 8000`. Point the proxy elsewhere with
`VITE_API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev`. The UI only uses relative `/api/...` URLs; in
production serve `dist/` behind the same origin as the API (or a reverse proxy that forwards `/api`).

If the backend sets `MODERNISATION_API_TOKEN`, enter the token under **Settings → API token**. It is kept
in this browser's `localStorage` and sent as `Authorization: Bearer <token>` on mutating requests only.

## Scripts

| Script                 | What it does                                               |
| ---------------------- | ---------------------------------------------------------- |
| `npm run dev`          | Vite dev server with the `/api` proxy                      |
| `npm run build`        | type-check, then production build into `dist/`             |
| `npm run preview`      | serve `dist/` (port 4173, same `/api` proxy)               |
| `npm run typecheck`    | `tsc --noEmit` for the app and for the config/E2E code     |
| `npm run lint`         | ESLint (typescript-eslint type-checked rules, react-hooks) |
| `npm run format:check` | Prettier check (`npm run format` rewrites)                 |
| `npm run test`         | Vitest unit and component tests (jsdom, `fetch` mocked)    |
| `npm run e2e`          | Playwright end-to-end tests against the real backend       |

## Screens and the endpoints they use

| Screen               | Route                 | Endpoints                                                                                                                                                                                                                                                                   |
| -------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Header (all screens) | –                     | `GET /api/health`                                                                                                                                                                                                                                                           |
| Dashboard            | `/`                   | `GET /api/dashboard`, `GET /api/meta`                                                                                                                                                                                                                                       |
| Repository explorer  | `/repositories[/:id]` | `GET/POST /api/repositories`, `GET /{id}`, `POST /{id}/index`, `POST /{id}/refresh`, `GET /{id}/snapshots`, `/branches`, `/commits`, `/tree`, `/file`, `/search`, `POST /{id}/retrieve` (review findings), `POST /{id}/impact`, `GET /api/settings` (authorised roots hint) |
| Task list            | `/tasks`              | `GET /api/tasks?state=&repository_id=`, `GET /api/meta`, `GET /api/repositories`                                                                                                                                                                                            |
| Task creation        | `/tasks/new`          | `POST /api/tasks`, `GET /api/repositories`, `GET /{id}/branches`, `GET /api/meta`, `GET /api/settings` (defaults)                                                                                                                                                           |
| Execution monitor    | `/tasks/:id`          | `GET /api/tasks/{id}` (polled while not terminal), `GET /{id}/events?after_id=` (every 2 s while not terminal), `GET /{id}/checks`, `GET /{id}/model-calls`, `POST /{id}/cancel`, `POST /{id}/restart`, `GET /api/health`                                                   |
| Code review          | `/tasks/:id/review`   | `GET /api/tasks/{id}`, `GET /{id}/attempts/{n}`, `GET /{id}/checks`, `POST /{id}/approval` (with `expected_version`)                                                                                                                                                        |
| Evaluation           | `/evaluation`         | `GET /api/evaluation/runs`, `GET /api/evaluation/runs/{id}`                                                                                                                                                                                                                 |
| Settings             | `/settings`           | `GET /api/settings`, `POST /api/settings/model/test`, `GET /api/health`                                                                                                                                                                                                     |

Behaviour worth knowing:

- **Event log**: the monitor keeps the highest event id it has seen and asks only for newer events. It polls
  every 2 s while the task is not `COMPLETED`, `FAILED`, `CANCELLED` or `ESCALATED`, fetches once more when
  the task becomes terminal, then stops. Restarting resumes polling. The log is an ARIA `log` region
  (`aria-live="polite"`).
- **Approvals** send `expected_version = task.version` as displayed. If the task changed meanwhile the API
  answers 409; the form explains this and offers to reload.
- **Validation** is the API's: the task form does not pre-validate, and 422 details are shown next to the
  offending fields (and summarised in an alert).
- **Diffs** are parsed in `src/lib/diff.ts` (hunk-count aware, handles added/deleted/renamed/binary files
  and "\ No newline" markers) and shown unified or before/after.
- **Unknown cost** (no model price configured) is shown as "not applicable", never as $0.

## Tests

```bash
npm run test           # 7 files, 24 tests
npm run e2e            # 5 scenarios, real backend + PostgreSQL
```

Unit/component tests mock `fetch` at the boundary (`src/test/utils.tsx`); they cover the diff parser, the
dashboard, the evaluation empty state, the approval form (`expected_version`, 409), the monitor's event
polling stopping on a terminal state and the cancel/restart rules, task-form 422 handling, and the API
client (token header, error parsing).

### End-to-end tests (real backend)

`npm run e2e` starts two servers through Playwright's `webServer` and stops them afterwards:

1. `scripts/e2e-backend.sh`, which
   - creates the dedicated database `modernisation_e2e` if needed (`su postgres -c "psql -c 'CREATE DATABASE …'"`,
     only when run as root; otherwise create it yourself or set `E2E_DATABASE_URL`),
   - runs `alembic downgrade base && alembic upgrade head` on it, so each run starts empty,
   - recreates `/var/tmp/modernisation-e2e/{data,sources}` (mode 755) and a two-commit sample git repository
     (`sources/inventory`, a small Python package with tests),
   - execs `python -m modernisation.cli api --port 8000` with `MODERNISATION_ALLOWED_LOCAL_ROOTS` set to the
     sources directory, CORS for `localhost:5173`/`127.0.0.1:5173`, and **no** model endpoint, GitHub token
     or API token (all other `MODERNISATION_*` variables are cleared).
2. `vite --host 127.0.0.1 --port 5173`, proxying `/api` to that backend.

No worker runs, so created tasks stay `QUEUED`; the UI says exactly that. Scenarios:

- register a repository (including the 403 for unauthorised paths) → index → browse a file, outline and
  impact → text/symbol/references/invalid-regex search → commits/snapshots → review findings;
- task form 422 errors; create a task → monitor shows `QUEUED` and the event log → cancel → restart →
  review page, task list and dashboard;
- evaluation page shows "No evaluation results available.";
- settings page shows real settings, the real model-test response (400, no model configured) and stores the
  API token.

Prerequisites: PostgreSQL on 127.0.0.1:5432 with the `modernisation` role (as for the backend tests) and the
backend virtualenv at `backend/.venv`. `@playwright/test` is pinned to 1.56.1 because its Chromium build
(1194) is the one installed under `PLAYWRIGHT_BROWSERS_PATH`; do not run `playwright install`. To use another
Chromium binary set `E2E_CHROMIUM_PATH`.

Useful variables: `E2E_BACKEND_PORT` (8000), `E2E_FRONTEND_PORT` (5173), `E2E_ROOT`
(`/var/tmp/modernisation-e2e`), `E2E_DB_NAME`, `E2E_DATABASE_URL`, `E2E_LOG_LEVEL`, and
`E2E_REUSE_SERVERS=1` to run against servers you started yourself (for example
`bash scripts/e2e-backend.sh` in one terminal and `npm run dev -- --host 127.0.0.1` in another).

## Layout

```
src/
  main.tsx, App.tsx          entry point, query client, routes
  lib/                       api client + types, diff parser, file tree, formatting, task-state rules, token
  hooks/                     event-log polling, document title, element width
  components/                layout, badges, notices, stat tiles, key/value, SVG bar chart, diff/code viewers, event log, timeline
  pages/                     Dashboard, repositories/*, tasks/*, evaluation/*, Settings
  styles/global.css          design tokens (light/dark) and all styles
  test/                      Vitest setup, fetch mock, fixtures
e2e/                         Playwright specs and helpers
scripts/e2e-backend.sh       real-backend startup for E2E
```

## Backend contract notes

Resolved in the backend since the first version of this UI: `GET /api/meta` now also returns
`terminal_states`, `restartable_states` and `runnable_states`; check runs include a `passed` field;
`/api/tasks/{id}/model-calls` returns 404 for unknown tasks; `/api/health` lists workers holding active leases
(`active_workers`, a lower bound because idle workers hold none); and read endpoints (`/tree`, `/file`,
`/search`) no longer index implicitly but return 409 until the repository is indexed.

Still open:

- No push channel (SSE/WebSocket) for events; the UI polls `?after_id=` every 2 s.
- No read endpoint for webhook deliveries; GitHub-originated activity is visible only through task events.
- `GET /api/tasks` has no pagination cursor or total count (only `limit`, default 100).
- The UI still mirrors the terminal/restart rules in `src/lib/states.ts` rather than reading them from `/api/meta`.
