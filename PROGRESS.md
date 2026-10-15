# Progress

Status vocabulary: **VERIFIED** = implemented and exercised by tests or commands whose output was inspected;
**COMPLETED** = implemented, not yet independently verified; **IN PROGRESS**; **BLOCKED** (with the missing
requirement); **NOT STARTED**.

Last updated: 2026-10-15

## Milestones

| Milestone | Status | Evidence / notes |
| --- | --- | --- |
| M1 Audit & environment | VERIFIED | `docs/IMPLEMENTATION_PLAN.md`; `uv.lock` committed |
| M2 Backend API, DB, migrations | IN PROGRESS | Alembic `0001` upgrade → downgrade → upgrade and `alembic check` (no drift) run on PostgreSQL 16. API endpoints written; API tests not yet written. |
| M3 Repository intelligence | VERIFIED | `tests/integration/test_repository_intelligence.py` (6 tests, real git + PostgreSQL): incremental re-index parses 1 changed blob and reuses 7; retrieval acceptance test for a Python bug report. |
| M4 Planning & durable workflow | VERIFIED (scripted model) | `tests/integration/test_workflow.py` (13 tests): plan → implement → test → repair → verify → approval → publish, budget exhaustion, policy escalation, plan approval gate, cancellation, restart, clarification. Crash/lease recovery tests pending (M9). |
| M5 Isolated patch execution | VERIFIED | `tests/security/test_sandbox_boundaries.py` (14 tests): no network, unprivileged uid, hidden host paths, cross-job isolation, process-tree kill on timeout, fork bomb, memory, file size, output flood. |
| M6 Test, verify, repair | VERIFIED (scripted model) | baseline/attempt/verification check runs recorded; repair receives failing test output. |
| Real model inference | VERIFIED (single sample) | `tests/live/test_live_model.py` with local Qwen2.5-Coder-1.5B (llama.cpp, CPU): sample bug fixed and independently verified in 2 attempts / 3 model calls. One sample is not a capability measurement. |
| M7 GitHub integration | IN PROGRESS | client, idempotent publisher ledger, webhook receiver written; tests pending. Live GitHub test BLOCKED: needs an authorised test repository and a token supplied by the owner. |
| M8 Frontend | NOT STARTED | |
| M9 Security & recovery suites | IN PROGRESS | sandbox boundary suite done; recovery scenarios not started. |
| M10 Evaluation benchmark | NOT STARTED | |
| M11 CI & documentation | NOT STARTED | |
| M12 Release | NOT STARTED | push requires owner approval |

## Known issues / decisions pending owner input

- Git author identity: commits in this session use the platform-configured identity. The requested
  "Sravani Perni" identity was **not** configured because no verified email address was available.
- Live GitHub publication needs an authorised test repository and token (`MODERNISATION_GITHUB_TOKEN`).

## Next actions

1. API tests (M2), GitHub publisher/webhook tests with a fault-injecting stand-in (M7).
2. Frontend (M8).
3. Recovery scenarios (M9), benchmark (M10), CI/docs (M11).
