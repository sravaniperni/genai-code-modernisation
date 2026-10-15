# Failure analysis

This document records observed failures: platform defects found during development (and their fixes), and failure
modes of the measured agent on the benchmark. Benchmark failure counts come from `reports/failures.csv` and
`reports/evaluation.md`; nothing here is estimated.

## Platform defects found and fixed

Found by tests, by the pilot task set (outside the benchmark), or by reviewing development-split runs. Each fix has
a regression test.

| # | Defect | How it was found | Fix |
| --- | --- | --- | --- |
| 1 | Retrieval cache detached every ORM object from the caller's session (`expunge_all`), breaking the workflow | first end-to-end workflow test | cache stores immutable row records instead of ORM instances |
| 2 | `branches()` used `git log` format escapes with `for-each-ref`, returning garbage names | workflow test assertion on published branch | tab-separated `for-each-ref` format |
| 3 | Publication commit was empty (`git apply` does not stage) | workflow test | stage before committing |
| 4 | The model copied the prompt's `path/to/file.py` placeholder and wrapped edits in `<file>` tags | first live run with the 1.5B model | format example uses a real target path; `<file path>` accepted as a path line |
| 5 | Injected `pytest` 9 conflicted with projects pinning `packaging<22` | pilot validation | wheelhouse carries pytest 8.3.5 as well; resolver backtracks |
| 6 | Git stat cache hid same-size, same-mtime overlay changes (reference solution silently dropped a file) | pilot validation | overlays copied without preserving mtimes; content re-hashed (`git add --renormalize`) before diffs |
| 7 | One job's fork bomb could starve concurrent jobs (`RLIMIT_NPROC` is per uid) | writing the security suite | per-job limit from the cgroup pids controller; rlimit becomes a host-wide backstop |
| 8 | Registration validated the name before authorisation (inconsistent 400 vs 403 for unauthorised paths) | security suite | authorise first |
| 9 | A diff touching a disallowed path raised inside verification (task FAILED instead of ESCALATED) | security suite | audit before applying the diff |
| 10 | Repository `.env`/key files could be retrieved into model context | writing the security suite | sensitive-path filter in retrieval and context packing |
| 11 | Mirrors owned by another uid failed git's ownership check (API and worker containers) | Docker Compose verification | platform-owned global git config (`safe.directory`), which reaches `upload-pack` |
| 12 | State-change events recorded the new state as the old one | Compose verification event log | read the old state before the ORM update |
| 13 | Whole-file answers were rejected because the flag was dropped during edit normalisation | development-split review | flag preserved; workspace-level regression test |
| 14 | GET explorer endpoints indexed repositories as a side effect | frontend integration review | read endpoints return 409 until an explicit index |

## Agent failure modes observed on development data

Observed with Qwen2.5-Coder-1.5B-Instruct (Q4_K_M) on the pilot and development tasks:

* **Format drift**: answering with whole files, echoing the context blocks unchanged, or unterminated blocks. The
  platform now accepts whole-file rewrites when they do not drop definitions; echoes produce no change and are
  rejected as `empty_change`.
* **Truncated replacements**: a REPLACE section that keeps the signature and docstring but drops the body, so the
  function returns `None`. The visible tests catch it and the failure report is fed back; the small model often
  repeats the same mistake in repair.
* **No-op edits**: SEARCH and REPLACE identical except for a rewritten docstring.
* **Partial upgrades**: bumping a pin without adapting call sites (caught by tests after the environment rebuild),
  or adapting code without changing the pin (caught by acceptance version checks).

## Benchmark failure categories

Populated from the final evaluation run (see `reports/evaluation.md`).
