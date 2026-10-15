# Implementation plan

This plan was written after auditing the repository and the execution environment on 2026-10-15.

## Starting point (audit)

| Item | Finding |
| --- | --- |
| Repository | `sravaniperni/genai-code-modernisation`, one commit (`Initial commit`) containing `README.md`, `LICENSE` (MIT), `.gitignore` (Python template). No source code, tests or CI existed. |
| Branch | Development branch `praveen/friendly-archimedes-04rb8u` (session-assigned); `main` untouched. |
| Machine | 4 vCPU, 15 GiB RAM, no GPU, Ubuntu 24.04, Linux 6.18. |
| Python | 3.12.3 and 3.13 available; the platform targets 3.12. |
| Node | 22.22, npm 10.9, pnpm, Playwright Chromium pre-installed. |
| PostgreSQL | 16.15 installed (cluster was stopped; started for development). `pg_trgm` available. |
| Docker | CLI + daemon binaries installed; daemon not running at start (started manually for compose verification). |
| Sandboxing | Unprivileged user namespaces work; bubblewrap 0.9 installed from Ubuntu packages. cgroup v1 hierarchy present. |
| Model endpoint | No model credentials configured for the platform. Outbound HTTPS to Hugging Face and PyPI available. |

## Decisions that follow from the audit

1. **Local, real model inference without credentials**: a llama.cpp server (`llama-cpp-python`, compiled locally)
   serving Apache-2.0 *Qwen2.5-Coder-1.5B-Instruct* (Q4_K_M) on CPU. Measured throughput: ~90 tok/s prompt
   processing, ~10 tok/s generation. The 7B variant was measured at ~28 / ~3.5 tok/s, too slow for a 100-task
   benchmark on this machine. Hosted endpoints (OpenAI-compatible or Anthropic) are supported by configuration.
2. **Sandbox**: bubblewrap namespaces + unprivileged host uid + rlimits + cgroup v1 limits, no network, offline
   wheelhouse for dependency installation (see `docs/SECURITY.md`).
3. **Orchestration**: a PostgreSQL-backed durable state machine with leases instead of LangGraph
   (see `docs/TECHNICAL_DECISIONS.md`).

## Milestones

| # | Milestone | Exit criteria |
| --- | --- | --- |
| M1 | Audit + environment | this document, PROGRESS.md, backend scaffold, lockfile |
| M2 | Backend API, DB, migrations | Alembic upgrade/downgrade/drift check on PostgreSQL; API tests |
| M3 | Repository intelligence | tree-sitter index, incremental re-index, hybrid retrieval acceptance test |
| M4 | Planning + durable workflow | state machine, checkpoints, approvals, cancellation, restart |
| M5 | Isolated patch execution | workspace per job, path policy, sandbox boundary tests |
| M6 | Test/verify/repair | baseline comparison, bounded repair, independent verification |
| M7 | GitHub integration | idempotent publish ledger, webhooks, rate limits; tested against a local fault-injecting GitHub stand-in; live test requires an authorised test repository + token |
| M8 | Frontend | seven screens on the real API; component + Playwright E2E tests |
| M9 | Security + recovery | security suite and ≥30 recovery scenarios with recorded results |
| M10 | Evaluation | 5 fixture repositories, 100 tasks (40/30/30), protected acceptance tests, platform vs single-shot baseline, measured reports |
| M11 | CI + docs | GitHub Actions workflows, README, docs |
| M12 | Release checks | acceptance checklist; push only after explicit approval |
