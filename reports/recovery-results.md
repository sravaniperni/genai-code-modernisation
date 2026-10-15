# Failure-recovery test results

Generated 2026-10-15T17:22:25.431867+00:00 from `recovery-results.json` (pytest outcomes of the executed scenarios).

- scenarios executed: **32**; passed: **32**; failed: **0**; skipped: **0**
- duplicate external actions observed: **0**
- tasks with lost state: **0**
- incorrectly resumed tasks: **0**

Observation counters are only as complete as the assertions in each scenario; see the test source for exactly what is checked.

## worker termination

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R01 | worker dies while baseline checks run during ANALYSING | PASSED | final_state="COMPLETED"; attempts=1; resume_count=1; duplicate_external_actions=0 |
| R02 | worker dies after the plan model call returns but before the plan is saved | PASSED | final_state="COMPLETED"; attempts=1; resume_count=1; duplicate_external_actions=0; plan_model_calls=2 |
| R04 | worker dies while the attempt's tests run in the sandbox | PASSED | final_state="COMPLETED"; attempts=1; resume_count=1; duplicate_external_actions=0 |
| R06 | worker dies during independent verification | PASSED | final_state="COMPLETED"; attempts=1; resume_count=1; duplicate_external_actions=0 |
| R07 | worker process is SIGKILLed while holding the lease in TESTING | PASSED | final_state="COMPLETED"; attempts=1; resume_count=1; duplicate_external_actions=0 |
| R08 | SIGKILL of a worker while a sandboxed test run is executing; no orphan processes | PASSED | orphan_processes=0; final_state="COMPLETED"; attempts=2; resume_count=1; duplicate_external_actions=0 |
| R09 | two workers race to claim the same task; exactly one wins (20 rounds) | PASSED | rounds=20; double_claims=0; duplicate_external_actions=0 |
| R10 | a paused worker resumes after its lease was taken over; its write is rejected | PASSED | final_state="ANALYSING" |

## partial operation

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R03 | worker dies after the plan checkpoint is saved but before the transition | PASSED | final_state="COMPLETED"; attempts=1; resume_count=1; duplicate_external_actions=0 |
| R05 | worker dies after writing edits to the workspace but before recording the attempt | PASSED | final_state="COMPLETED"; attempts=1; resume_count=1; duplicate_external_actions=0 |
| R27 | worker dies after the PR is created but before the ledger records it | PASSED | final_state="COMPLETED"; pull_requests=1; remote_branches=1; duplicate_external_actions=0 |
| R31 | indexing is interrupted mid-way and re-run | PASSED | snapshot_status="ready"; files_indexed=8; duplicate_external_actions=0 |
| R32 | dependency environment build is interrupted and rebuilt cleanly | PASSED | env_ok=true; reused=false; duplicate_external_actions=0 |

## interrupted model call

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R11 | connection reset on the first model request; retried and completed | PASSED | final_state="COMPLETED"; attempts=1; resume_count=0; duplicate_external_actions=0; failed_model_requests=1 |
| R12 | model requests time out beyond the retry budget, then the endpoint recovers | PASSED | final_state="COMPLETED"; attempts=1; resume_count=0; duplicate_external_actions=0; failed_model_requests=3 |
| R13 | persistent model outage fails the task after bounded retries; restart completes | PASSED | final_state="COMPLETED"; attempts=1; resume_count=0; duplicate_external_actions=0; bounded_failures=5 |
| R14 | model returns unparseable plans; bounded correction then retrieval-based fallback | PASSED | final_state="COMPLETED"; attempts=1; resume_count=0; duplicate_external_actions=0 |

## database reconnection

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R15 | PostgreSQL restarts while the worker is idle; next task is processed | PASSED | final_state="COMPLETED"; attempts=1; resume_count=0; duplicate_external_actions=0 |
| R16 | PostgreSQL restarts in the middle of a task step; task resumes and completes | PASSED | final_state="COMPLETED"; attempts=1; resume_count=0; duplicate_external_actions=0 |
| R17 | API health endpoint recovers after a PostgreSQL restart | PASSED | health_after_restart=[true, true, true] |

## task cancellation

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R18 | cancel while a hanging test run executes in the sandbox | PASSED | cancel_latency_s=1.3; orphan_processes=0; duplicate_external_actions=0 |
| R19 | cancel while waiting for human approval | PASSED | final_state="CANCELLED"; worker_picked_up=false; duplicate_external_actions=0 |
| R20 | cancelled task is restarted and completes; attempt numbering continues | PASSED | attempt_numbers=[1, 2]; final_state="AWAITING_APPROVAL"; duplicate_external_actions=0 |

## repeated webhook delivery

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R21 | the same delivery is received five times | PASSED | statuses=["processed", "duplicate", "duplicate", "duplicate", "duplicate"]; tasks_created=1; duplicate_external_actions=0 |
| R22 | ten concurrent copies of one delivery | PASSED | processed=1; duplicates=9; tasks_created=1; duplicate_external_actions=0 |

## branch creation + network failure

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R23 | push reaches the remote but the connection drops before the reply | PASSED | final_state="COMPLETED"; pull_requests=1; remote_branches=1; duplicate_external_actions=0; push_reconciled=true |
| R24 | push fails before reaching the remote; retried once | PASSED | final_state="COMPLETED"; pull_requests=1; remote_branches=1; duplicate_external_actions=0; push_attempts=2 |

## PR creation + response timeout

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R25 | GitHub creates the PR but the response times out | PASSED | final_state="COMPLETED"; pull_requests=1; remote_branches=1; duplicate_external_actions=0 |
| R26 | GitHub creates the PR but answers 502 | PASSED | final_state="COMPLETED"; pull_requests=1; remote_branches=1; duplicate_external_actions=0 |

## stale repository revision

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R28 | base branch advances after the task is created | PASSED | final_state="COMPLETED"; attempts=1; resume_count=0; duplicate_external_actions=0; stale_base_recorded=true |
| R29 | base commit no longer exists (history rewritten) | PASSED | final_state="ESCALATED"; reason="base commit 2f97f652abd87708ae064a6f898462d79f142b12 is not available in the re; duplicate_external_actions=0 |

## execution timeout

| ID | Scenario | Outcome | Key observations |
| --- | --- | --- | --- |
| R30 | patch makes the test suite hang; timeout is fed back and repaired | PASSED | final_state="COMPLETED"; attempts=2; resume_count=0; duplicate_external_actions=0; timed_out_runs=1 |

