# Progress

Status vocabulary: **VERIFIED** = implemented and exercised by tests or commands whose output was inspected;
**COMPLETED** = implemented, not independently verified; **IN PROGRESS**; **BLOCKED** (with the missing
requirement); **NOT STARTED**.

Last updated: 2026-10-15

## Milestones

| Milestone | Status | Evidence / notes |
| --- | --- | --- |
| M1 Audit & environment | VERIFIED | `docs/IMPLEMENTATION_PLAN.md`; `backend/uv.lock`, `frontend/package-lock.json` |
| M2 Backend API, DB, migrations | VERIFIED | Alembic `0001` upgrade/downgrade/upgrade + `alembic check` on PostgreSQL 16; `tests/integration/test_api.py` (14 tests) |
| M3 Repository intelligence | VERIFIED | `tests/integration/test_repository_intelligence.py`: incremental re-index (1 parsed / 7 reused), retrieval acceptance test, foreign-owner and stat-cache regressions |
| M4 Planning & durable workflow | VERIFIED | `tests/integration/test_workflow.py` (13 tests, scripted model); recovery suite |
| M5 Isolated patch execution | VERIFIED | `tests/security/test_sandbox_boundaries.py` (15 tests) |
| M6 Test, verify, repair | VERIFIED | workflow tests; live-model test |
| Real model inference | VERIFIED | local Qwen2.5-Coder-1.5B (llama.cpp, CPU) via `tests/live/test_live_model.py`; benchmark runs below |
| M7 GitHub integration | VERIFIED against stand-in; live **BLOCKED** | 16 tests + 6 recovery scenarios against a fault-injecting in-process GitHub stand-in backed by a real bare git remote. Live verification needs an authorised test repository and a fine-grained token from the owner. |
| M8 Frontend | VERIFIED | typecheck, lint, prettier, 24 Vitest tests, build, 5 Playwright E2E tests against the real backend (re-run independently) |
| M9 Security & recovery | VERIFIED | `reports/security-results.md` (29/29 executions, 27 scenarios), `reports/recovery-results.md` (32/32 incl. PostgreSQL restarts and SIGKILL) |
| M10 Evaluation benchmark | IN PROGRESS | 5 fixture repositories, 100 tasks authored; per-repository validation reported 20/20 by each author; full re-validation against a rebuilt wheelhouse, freeze and measured runs pending |
| M11 CI & documentation | IN PROGRESS | `.github/workflows/ci.yml` passes `actionlint`; every CI step was run locally and passed except jobs that only exist on GitHub runners. **Not yet executed on GitHub** (requires push). Docs written; README final numbers pending evaluation. |
| M12 Release | NOT STARTED | push requires owner approval |

## Container verification

* `backend/Dockerfile` and `frontend/Dockerfile` build (verified locally through the host network with the proxy CA
  supplied as a build secret, because this environment intercepts TLS).
* `docker compose up` verified: migrations ran, API healthy, dashboard served through nginx with `/api` proxied, and the
  containerised worker indexed a repository, built the environment from the wheelhouse and ran baseline tests inside
  bubblewrap (worker container needs relaxed seccomp/AppArmor/systempaths; documented in `docs/SECURITY.md`).

## Blocked / needs owner input

1. **Live GitHub publication**: needs a test repository and a fine-grained token
   (`MODERNISATION_GITHUB_TOKEN`, `MODERNISATION_ALLOWED_GITHUB_REPOSITORIES`).
2. **Hosted model evaluation**: no API credentials were provided; only the local 1.5B model was measured.
3. **CI on GitHub**: requires pushing the branch (awaiting approval).
4. **Git author identity**: commits use the platform-configured identity; the requested "Sravani Perni" identity was
   not configured because no verified email address was available.

## Next actions

1. Rebuild the wheelhouse from the pinned lists, re-validate all 100 tasks, commit the validation report, freeze
   `TASKSET.lock`.
2. Run platform and baseline evaluations on all 100 tasks; generate reports; complete `docs/FAILURE_ANALYSIS.md`.
3. Write resume evidence files from measured results only.
