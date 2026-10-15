/** Canned API responses for unit tests only (the E2E suite uses the real backend). */
import type { Health, Meta, TaskDetail, TaskSummary } from '../lib/types';

export const META: Meta = {
  states: [
    'QUEUED',
    'ANALYSING',
    'PLANNING',
    'AWAITING_APPROVAL',
    'IMPLEMENTING',
    'TESTING',
    'REPAIRING',
    'VERIFYING',
    'PUBLISHING',
    'COMPLETED',
    'FAILED',
    'CANCELLED',
    'ESCALATED',
  ],
  categories: ['dependency_upgrade', 'deprecated_api_migration', 'bug_fix'],
};

export const HEALTH: Health = {
  status: 'ok',
  database: true,
  sandbox: { backend: 'bubblewrap', bubblewrap_installed: true },
  model_configured: false,
  github_configured: false,
};

export function taskSummary(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    id: 1,
    repository_id: 1,
    repository: 'inventory',
    title: 'Fix discount',
    category: 'bug_fix',
    state: 'QUEUED',
    state_reason: null,
    approval_stage: null,
    attempt_count: 0,
    created_at: '2026-10-15T10:00:00+00:00',
    updated_at: '2026-10-15T10:00:00+00:00',
    started_at: null,
    finished_at: null,
    origin: 'api',
    pr_url: null,
    version: 1,
    cancel_requested: false,
    resume_count: 0,
    ...overrides,
  };
}

export function taskDetail(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    ...taskSummary(),
    request: 'apply_discount divides by 1000 instead of 100.',
    base_ref: 'main',
    base_commit: 'a'.repeat(40),
    allowed_paths: ['src/**'],
    forbidden_paths: [],
    config: { max_attempts: 3 },
    analysis: null,
    plan: null,
    result: null,
    final_diff: null,
    branch_name: null,
    pr_number: null,
    attempts: [],
    approvals: [],
    usage: {
      model_calls: 0,
      failed_calls: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      model_latency_ms: 0,
      cost_usd: null,
    },
    ...overrides,
  };
}
