# Technical decisions

Each entry records the decision, the alternatives considered and why the choice was made.

## TD-1 Durable state machine in PostgreSQL instead of LangGraph

* **Decision**: a small explicit state machine (`agents/states.py`) persisted in PostgreSQL, with leases, optimistic
  versioned transitions, per-step checkpoints and an append-only event log.
* **Alternatives**: LangGraph with a Postgres checkpointer; Celery/RQ with Redis; Temporal.
* **Why**: the workflow is a fixed, auditable pipeline rather than an open-ended graph. Recovery semantics had to be
  testable at precise crash points (32 scenarios), and the same table already holds approvals, the side-effect ledger
  and evaluation results. A single store avoids keeping a framework's checkpoint format consistent with domain state,
  and `FOR UPDATE SKIP LOCKED` gives a queue without Redis. Cost: transitions and resume logic are hand-written and
  must be tested explicitly (they are).

## TD-2 Keyword + structural retrieval, no embeddings

* **Decision**: BM25 over identifier-aware tokens combined with tree-sitter symbols, references, import graph,
  test linkage and manifests.
* **Why**: maintenance requests usually name identifiers, packages or deprecated APIs; exact structure gives
  reproducible, explainable references with line ranges. No vector database is introduced without evidence it helps.
  Embeddings remain a measurable future experiment.

## TD-3 Content-addressed index

* **Decision**: parse results are stored per git blob SHA and snapshots map paths to blobs.
* **Why**: incremental indexing falls out naturally (only new blobs are parsed) and every snapshot stays exact for its
  commit.

## TD-4 SEARCH/REPLACE edits instead of unified diffs

* **Why**: models produce exact-text blocks far more reliably than hunk headers. Each block is validated (unique
  match, policy) before anything touches the workspace. Trailing-whitespace and uniform-indentation differences are
  tolerated; ambiguous matches are rejected. A whole-file fallback was added after observing that the small local model
  frequently answers with complete files; it is accepted only if no existing Python definition is dropped.

## TD-5 Baseline-relative checks and independent verification

* **Why**: real repositories often have failing or flaky tests. Comparing against a baseline run at the base commit
  avoids blaming the change for pre-existing failures and catches removed tests. Verification in a fresh clone guards
  against results that depend on workspace state; a disagreement is surfaced as a failure, never retried until it
  passes.

## TD-6 bubblewrap sandbox with an unprivileged uid and offline wheelhouse

* **Alternatives**: Docker per job (needs the Docker socket or Docker-in-Docker: rejected by the security brief),
  gVisor or Firecracker (stronger, but not available on the development host), plain subprocess (no isolation).
* **Why**: unprivileged namespaces are available without the Docker socket or privileged containers. Dropping to a
  dedicated uid makes `RLIMIT_NPROC` and file ownership meaningful, and cgroup pids/memory limits give per-job resource
  control. An offline wheelhouse removes network access from dependency installation. Residual risks are in
  `docs/SECURITY.md`.

## TD-7 Provider-independent HTTP model adapters

* **Decision**: two adapters (OpenAI-compatible Chat Completions, Anthropic Messages) over `httpx`, with one retry
  loop and one accounting sink. Structured output via JSON schema (OpenAI), grammar-constrained JSON (llama.cpp) or a
  forced tool call (Anthropic), always validated with Pydantic and corrected at most once.
* **Why**: SDKs differ in retry and usage reporting; a thin adapter keeps cost and latency accounting identical across
  providers and records failed requests too.

## TD-8 Local open-weights model for measured evaluation

* **Decision**: Qwen2.5-Coder-1.5B-Instruct (Apache-2.0), Q4_K_M quantisation, served by llama.cpp on 4 CPU cores.
* **Why**: no model credentials were provisioned for this project and no GPU exists. A local model gives real,
  reproducible, credential-free inference. The 7B model measured ~3.5 tokens/s generation, which would make a
  200-run benchmark take days; the 1.5B model (~10 tokens/s) makes it hours. Consequence: absolute completion rates
  reflect a very small model and are not representative of hosted frontier models.

## TD-9 Idempotent publication ledger

* **Why**: GitHub calls can time out after taking effect. Each side effect is recorded under a deterministic key
  before it is attempted; commits are deterministic (fixed dates), pushes never force, and pull requests are looked up
  by head branch before creation and after any ambiguous failure.

## TD-10 Settings namespace

* **Decision**: only `MODERNISATION_*` variables configure the platform.
* **Why**: prevents accidental use of ambient credentials (CI `GITHUB_TOKEN`, developer API keys).

## Dependencies and their purpose

| Dependency | Purpose |
| --- | --- |
| fastapi, uvicorn | HTTP API |
| pydantic, pydantic-settings | request/response validation, structured model output, configuration |
| sqlalchemy, psycopg, alembic | PostgreSQL access and migrations |
| httpx | model provider and GitHub HTTP clients |
| tree-sitter, tree-sitter-python | syntax-tree parsing for repository intelligence |
| pyyaml | benchmark task definitions |
| opentelemetry-api/sdk | tracing spans for model calls |
| pytest, pytest-timeout, ruff, mypy, types-PyYAML | development and CI only |
| bubblewrap (system) | sandbox |
| llama-cpp-python (optional, separate venv) | local model server used for the measured evaluation |
