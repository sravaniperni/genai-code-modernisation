# Security model

## Threat model

| Asset | Threat | Primary control |
| --- | --- | --- |
| Host and other jobs | Repository code (install hooks, tests) and model-generated code execute arbitrary instructions | bubblewrap sandbox as an unprivileged uid; no network; no host paths; per-job workspace; resource limits |
| Credentials (model key, GitHub token, webhook secret) | Leakage to sandboxed code, logs, prompts, the database or API responses | `MODERNISATION_*`-only settings; empty sandbox environment; log/event redaction; secrets never serialised by the API; git token passed as an environment-scoped HTTP header |
| Repository integrity | Agent changes CI, hooks, unrelated files, or weakens tests | Deterministic change policy on every edit and again on the final diff |
| Human control | Publication without review; approving something that changed after review | Publish approval gate bound to the task version; recorded approval re-checked before any external side effect |
| External systems | Duplicate branches or pull requests after retries | Idempotent publication ledger with reconciliation |
| Model provider | Repository secrets sent as context | Credential/key files excluded from retrieval and prompts |

Repository content and model output are both treated as untrusted. Prompt-injection text in a repository can influence
what the model proposes, but cannot change what the platform permits: the policy, the sandbox and the approval gates do
not depend on model behaviour. The security suite tests this with a deliberately obedient scripted model.

## Sandbox (bubblewrap backend)

Each command runs as:

* host uid/gid **9100** (`modsandbox`), dropped from root before `bwrap` executes; inside, separate user, PID, IPC, UTS,
  cgroup and **network** namespaces (`--unshare-all`; only the loopback interface exists);
* a root filesystem containing read-only `/usr` (plus `/etc/alternatives`, `ld.so.cache`, `localtime`), a private
  size-limited `/tmp`, `/proc` for its own PID namespace, the job workspace at `/work` (writable), the dependency
  environment at `/env` (**read-only** during checks), an output directory and, for evaluation only, the acceptance
  tests at `/acceptance` (read-only). `/work/.git` is hidden by an empty tmpfs;
* `--clearenv` with a fixed allowlist of variables: no host environment, therefore no credentials or proxy settings;
* `--die-with-parent` and `--new-session`; a wall-clock timeout and cooperative cancellation kill the process group;
* rlimits: address space (memory), file size, open files, core dumps; cgroup memory and **pids** limits per job
  (unified cgroup v2 hierarchy or legacy v1) when the worker runs as root and the host allows it. `RLIMIT_NPROC` counts all processes of the shared sandbox uid, so it is only a host-wide backstop
  when cgroups are enforced; without cgroups it falls back to the per-job value;
* bounded output capture (head and tail kept).

Dependency installation happens inside the same sandbox from an **offline wheelhouse** (`--no-index`). If no
wheelhouse is configured, installation may use the network but only binary wheels (`--only-binary=:all:`), so no package
build script executes.

### Verified by tests

`backend/tests/security/test_sandbox_boundaries.py` and `backend/tests/security/test_security_suite.py` execute real
hostile code in the real sandbox: network connections (internet, PostgreSQL, model server, API) are refused; `/root`,
`/home`, `/etc/shadow`, `/etc/passwd`, `/opt`, the Docker socket and other jobs' workspaces are absent; writing to `/usr` or
the shared environment fails; the uid is 9100; no `MODERNISATION_*`, GitHub, AWS, OpenAI or Anthropic variables are
visible; fork bombs, memory and disk exhaustion are contained; one job's fork bomb does not starve a concurrent job;
a timed-out or cancelled command leaves no surviving process. Results: `reports/security-results.md`.

### Residual risks

* **Shared kernel.** Namespaces are not a VM boundary; a kernel exploit escapes the sandbox. No seccomp filter is applied
  inside bubblewrap.
* **No disk quota.** File size is limited per file, total workspace usage is not.
* **CPU** is limited only by the wall-clock timeout (no CPU quota).
* **Containers.** Running workers inside Docker requires `seccomp=unconfined`, `apparmor=unconfined` and
  `systempaths=unconfined` on the worker container so bubblewrap can create namespaces and mount `/proc`. The container
  stays unprivileged (default capability set, no Docker socket) but these options widen its kernel attack surface, and
  cgroup per-job limits are unavailable inside the container.
* **Unsandboxed mode** (`MODERNISATION_SANDBOX_BACKEND=unsandboxed`) exists for development hosts without bubblewrap and
  must never be used with untrusted repositories.

**Before accepting untrusted third-party repositories**, run workers on dedicated hosts or microVMs (Firecracker,
gVisor/`runsc`, Kata), add a seccomp profile, per-job CPU and disk quotas, and egress policy for any network-enabled
installation step.

## Change policy

Always forbidden: `.git/**`, `.gitmodules`, `.github/workflows/**`, `.env*`, `*.pem`, `*.key`, `id_rsa*`; absolute
paths; `..`; any symlink component; anything outside `allowed_paths`; anything in `forbidden_paths`. Test files may
not be deleted, lose `test_*` functions or gain `skip`/`skipif`/`xfail`/`collect_ignore`/`--deselect`. The policy is
applied to each proposed edit, to recorded diffs before they are re-applied, and to the final diff during independent
verification (a violating diff escalates before it is applied).

## Credentials

* Settings are read only from `MODERNISATION_*` variables; ambient `GITHUB_TOKEN`/`OPENAI_API_KEY` are ignored.
* `SecretStr` values are never returned by the API (`/api/settings` reports only whether they are configured).
* The JSON log formatter and the task event writer redact registered secret values and common token formats
  (`ghp_`, `github_pat_`, `sk-`, bearer/basic headers, credentials in URLs).
* Git authentication uses an `http.extraheader` supplied through environment-scoped git configuration, never a URL or
  command-line argument.
* Recommended GitHub token: fine-grained, limited to the allowed repositories, with contents, pull requests and commit
  statuses read/write and issues read.

## API

The API is single-tenant. When `MODERNISATION_API_TOKEN` is set, every mutating endpoint requires
`Authorization: Bearer <token>`; read endpoints stay open on the bound interface (the compose file binds to
127.0.0.1). There is no role-based access control and the reviewer name on approvals is self-asserted; deployments with
several users need an identity provider in front of the API.

Webhooks require `MODERNISATION_GITHUB_WEBHOOK_SECRET`; without it every delivery is rejected. Signatures use a
constant-time HMAC-SHA256 comparison and delivery ids are de-duplicated.
