# Skills evidence

Each row points to code and tests in this repository. Quantitative outcomes are in `reports/claims_evidence.json`;
only entries with status `MEASURED` there may be quoted as numbers.

| Skill area | What was built | Code | Verification |
| --- | --- | --- | --- |
| System architecture | API, workers, PostgreSQL as source of truth, sandboxed execution, evaluation harness, dashboard | `docs/ARCHITECTURE.md`, `backend/src/modernisation/` | integration and E2E tests |
| Repository intelligence | tree-sitter parsing, content-addressed incremental index, hybrid keyword + structural retrieval with line-precise references, import-graph impact analysis | `repository_intelligence/` | `tests/integration/test_repository_intelligence.py` |
| LLM integration | provider-independent adapters (OpenAI-compatible, Anthropic tool use), retries with backoff and `Retry-After`, schema-constrained output with bounded correction, per-request token/latency/cost accounting | `llm/` | `tests/unit/test_core_units.py`, `tests/live/test_live_model.py` |
| Agent orchestration | durable state machine with leases, optimistic transitions, checkpoints, bounded repair, independent verification, approval gates | `agents/` | `tests/integration/test_workflow.py`, `tests/recovery/` |
| Code modification | SEARCH/REPLACE protocol with tolerant matching, whole-file fallback guarded against dropped definitions, git-based diffs | `agents/edits.py`, `execution/workspace.py` | unit + workspace regression tests |
| Sandboxing | bubblewrap namespaces, unprivileged uid, cgroup/rlimit limits, offline wheelhouse, process-tree termination | `execution/sandbox.py`, `execution/pyenv.py` | `tests/security/test_sandbox_boundaries.py` |
| Security engineering | deterministic change policy, credential redaction and isolation, prompt-injection containment, webhook signature verification, sensitive-file exclusion | `execution/policy.py`, `log.py`, `api/routers/webhooks.py` | `tests/security/test_security_suite.py`, `reports/security-results.md` |
| Reliability | crash-safe resumption, idempotent external side effects, database reconnection, cancellation | `agents/store.py`, `agents/worker.py`, `integrations/github/publisher.py` | `reports/recovery-results.md` |
| GitHub integration | permission checks, primary/secondary rate limits, draft PRs, commit statuses, webhooks | `integrations/github/` | `tests/integration/test_github_integration.py` (stand-in; live verification blocked) |
| Evaluation design | 100-task benchmark with protected acceptance tests, validator, frozen task set, paired platform vs baseline comparison with confidence intervals | `evaluation/`, `backend/src/modernisation/evaluation/` | `evaluation/validation-report.json`, `reports/evaluation.md` |
| Observability | JSON logs, task event stream, OpenTelemetry spans, model-call ledger | `log.py`, `telemetry.py`, `db/models.py` | API tests, dashboard |
| Frontend | React/TypeScript dashboard on real data, diff viewer, approval workflow, evaluation views | `frontend/src/` | 24 Vitest tests, 5 Playwright E2E tests |
| Delivery | Dockerfiles, Compose stack, GitHub Actions (lint, types, tests, E2E, audits, integrity, image builds) | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` | local builds and compose verification; CI not yet executed on GitHub |
