/**
 * Response shapes of the FastAPI backend (backend/src/modernisation/api). These mirror what the routers
 * return; anything the backend marks optional or nullable is nullable here too.
 */

export type JsonObject = Record<string, unknown>;

export interface Health {
  status: 'ok' | 'degraded';
  database: boolean;
  sandbox: { backend: string; bubblewrap_installed: boolean };
  model_configured: boolean;
  github_configured: boolean;
}

export interface Meta {
  states: string[];
  categories: string[];
}

export interface TaskSummary {
  id: number;
  repository_id: number;
  repository: string;
  title: string;
  category: string;
  state: string;
  state_reason: string | null;
  approval_stage: string | null;
  attempt_count: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  origin: string;
  pr_url: string | null;
  version: number;
  cancel_requested: boolean;
  resume_count: number;
}

export interface Dashboard {
  repositories: number;
  tasks_by_state: Record<string, number>;
  completed: number;
  failed: number;
  active: TaskSummary[];
  recent: TaskSummary[];
  model_usage: { calls: number; prompt_tokens: number; completion_tokens: number };
}

export interface Snapshot {
  id: number;
  commit_sha: string;
  ref: string | null;
  status: string;
  files_total: number | null;
  blobs_parsed: number | null;
  blobs_reused: number | null;
  symbols_total: number | null;
  languages: Record<string, number> | null;
  duration_ms: number | null;
  finished_at: string | null;
  error: string | null;
}

export interface Repository {
  id: number;
  name: string;
  source_kind: 'local' | 'github';
  source: string;
  github_full_name: string | null;
  default_branch: string;
  created_at: string;
  latest_snapshot: Snapshot | null;
  task_counts: Record<string, number>;
}

export interface RepositoryCreate {
  kind: 'local' | 'github';
  source: string;
  name?: string;
}

export interface TreeFile {
  path: string;
  language: string | null;
  is_test: boolean;
  is_config: boolean;
  size: number;
}

export interface TreeResponse {
  snapshot: Snapshot;
  files: TreeFile[];
}

export interface SymbolInfo {
  name: string;
  qualified_name: string;
  kind: string;
  start_line: number;
  end_line: number;
  signature: string | null;
}

export interface ImportInfo {
  module: string;
  name: string | null;
  alias: string | null;
  level: number;
  line: number;
}

export interface FileResponse {
  repository: string;
  commit_sha: string;
  path: string;
  language: string | null;
  is_test: boolean;
  is_config: boolean;
  module: string | null;
  content: string | null;
  binary_or_large: boolean;
  symbols: SymbolInfo[];
  imports: ImportInfo[];
}

export type SearchMode = 'text' | 'regex' | 'symbol' | 'references';

/** One search hit; which optional fields are present depends on the search mode. */
export interface SearchHit {
  repository: string;
  commit_sha: string;
  path: string;
  start_line: number;
  end_line: number;
  retrieval_method: string;
  symbol?: string | null;
  text?: string | null;
  name?: string;
  kind?: string;
  signature?: string | null;
  docstring?: string | null;
  expression?: string;
}

export interface SearchResponse {
  commit_sha: string;
  mode: SearchMode;
  results: SearchHit[];
}

export interface CodeReference {
  repository: string;
  commit_sha: string;
  path: string;
  start_line: number;
  end_line: number;
  retrieval_method: string;
  score: number;
  symbol: string | null;
  symbol_kind: string | null;
  reason: string;
  methods: string[];
  is_test: boolean;
  is_config: boolean;
}

export interface RetrieveRequest {
  request: string;
  category?: string;
  ref?: string;
  limit?: number;
}

export interface RetrieveResponse {
  commit_sha: string;
  references: CodeReference[];
}

export interface ImpactResponse {
  repository: string;
  commit_sha: string;
  changed: string[];
  dependents: { path: string; distance: number; is_test: boolean }[];
  symbol_references: { path: string; lines: number[] }[];
  tests: string[];
}

export interface Commit {
  sha: string;
  author: string;
  authored_at: string;
  subject: string;
}

export type Branches = Record<string, string>;

export interface TaskEvent {
  id: number;
  ts: string;
  kind: string;
  state: string | null;
  message: string;
  payload: JsonObject | null;
}

export interface AttemptSummary {
  attempt_no: number;
  kind: string;
  apply_status: string;
  rejection_reason: string | null;
  files_changed: string[];
  checks_passed: boolean | null;
  created_at: string;
}

export interface ApprovalRecord {
  stage: string;
  decision: string;
  reviewer: string;
  comment: string | null;
  created_at: string;
}

export interface TaskUsage {
  model_calls: number;
  failed_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  model_latency_ms: number;
  cost_usd: number | null;
}

export interface TaskDetail extends TaskSummary {
  request: string;
  base_ref: string;
  base_commit: string;
  allowed_paths: string[];
  forbidden_paths: string[];
  config: JsonObject;
  analysis: JsonObject | null;
  plan: JsonObject | null;
  result: JsonObject | null;
  final_diff: string | null;
  branch_name: string | null;
  pr_number: number | null;
  attempts: AttemptSummary[];
  approvals: ApprovalRecord[];
  usage: TaskUsage;
}

export interface TaskConfigInput {
  max_attempts: number;
  require_plan_approval: boolean;
  allow_test_changes: boolean;
  strategy: 'agentic' | 'single_shot';
}

export interface TaskCreate {
  repository_id: number;
  title: string;
  request: string;
  category: string;
  base_ref?: string;
  allowed_paths: string[];
  forbidden_paths: string[];
  config: TaskConfigInput;
}

export interface AttemptDetail {
  attempt_no: number;
  kind: string;
  apply_status: string;
  rejection_reason: string | null;
  diff: string | null;
  edits: unknown;
  raw_output: string | null;
  files_changed: string[];
  checks_passed: boolean | null;
}

export interface CheckRun {
  id: number;
  attempt_no: number | null;
  phase: string;
  name: string;
  command: string[];
  exit_code: number | null;
  timed_out: boolean;
  duration_ms: number;
  summary: JsonObject;
  stdout_tail: string;
  stderr_tail: string;
}

export interface ModelCall {
  id: number;
  purpose: string;
  provider: string;
  model: string;
  status: string;
  retry_index: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number;
  cost_usd: number | null;
  error: string | null;
  created_at: string;
}

export interface ApprovalInput {
  stage: 'plan' | 'publish';
  decision: 'approved' | 'rejected';
  reviewer: string;
  comment: string | null;
  expected_version: number;
}

export interface EvaluationRunInfo {
  id: number;
  run_key: string;
  mode: string;
  taskset_version: string | null;
  split: string | null;
  model_provider: string | null;
  model_name: string | null;
  config: JsonObject | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface CategoryMetric {
  total: number;
  success: number;
  rate: number | null;
}

export interface EvaluationMetrics {
  evaluated: number;
  successful: number;
  failed: number;
  timeouts: number;
  errors: number;
  completion_rate: number | null;
  by_category: Record<string, CategoryMetric>;
  failure_categories: Record<string, number>;
  latency_s: { p50: number | null; p90: number | null; max: number | null; mean: number | null };
  model_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  inference_cost_usd: number | null;
  cost_per_accepted_patch_usd: number | null;
  model_inference_seconds?: number;
  failed_model_requests?: number;
}

export interface EvaluationResultRow {
  benchmark_task_id: string;
  repo: string;
  category: string;
  outcome: string;
  failure_category: string | null;
  attempts: number;
  duration_ms: number;
  model_calls: number;
  task_id: number | null;
  prompt_tokens: number;
  completion_tokens: number;
}

export interface EvaluationRunSummary {
  run: EvaluationRunInfo;
  metrics: EvaluationMetrics;
  /** null in the list endpoint; populated by GET /api/evaluation/runs/{id}. */
  results: EvaluationResultRow[] | null;
}

export interface SettingsView {
  model: {
    provider: string;
    base_url: string | null;
    name: string | null;
    api_key_configured: boolean;
    timeout_s: number;
    max_retries: number;
    structured_output: string;
    price_input_per_mtok: number | null;
    price_output_per_mtok: number | null;
  };
  github: {
    api_url: string;
    token_configured: boolean;
    webhook_secret_configured: boolean;
    allowed_repositories: string[];
  };
  repositories: { allowed_local_roots: string[] };
  execution: {
    sandbox_backend: string;
    sandbox_uid: number;
    command_timeout_s: number;
    memory_mb: number;
    max_processes: number;
    max_file_mb: number;
    wheelhouse: string | null;
    network_in_sandbox: boolean;
  };
  workflow: {
    default_max_attempts: number;
    require_plan_approval: boolean;
    publish_requires_approval: boolean;
    worker_lease_s: number;
  };
  security: { api_token_required: boolean; notes: string };
}

export interface ModelTestResult {
  ok: boolean;
  error?: string;
  latency_ms: number;
  provider?: string;
  model?: string;
  reply?: string;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
}
