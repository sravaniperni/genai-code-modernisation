import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { EvaluationRunSummary } from '../../lib/types';
import { mockFetch, renderWithProviders } from '../../test/utils';
import { EvaluationPage } from './EvaluationPage';

function run(id: number, mode: string, rate: number, cost: number | null): EvaluationRunSummary {
  return {
    run: {
      id,
      run_key: `${mode}-run`,
      mode,
      taskset_version: 'v1',
      split: 'test',
      model_provider: 'openai_compatible',
      model_name: 'qwen2.5-coder-1.5b',
      config: {},
      status: 'finished',
      started_at: '2026-10-15T10:00:00+00:00',
      finished_at: '2026-10-15T12:00:00+00:00',
    },
    metrics: {
      evaluated: 4,
      successful: Math.round(rate * 4),
      failed: 4 - Math.round(rate * 4),
      timeouts: 0,
      errors: 0,
      completion_rate: rate,
      by_category: { bug_fix: { total: 4, success: Math.round(rate * 4), rate } },
      failure_categories: rate < 1 ? { tests_failed: 4 - Math.round(rate * 4) } : {},
      latency_s: { p50: 42.5, p90: 80.1, max: 90, mean: 50 },
      model_calls: 10,
      prompt_tokens: 1000,
      completion_tokens: 200,
      inference_cost_usd: cost,
      cost_per_accepted_patch_usd: cost,
      model_inference_seconds: 120,
      failed_model_requests: 0,
    },
    results: null,
  };
}

describe('EvaluationPage', () => {
  it('shows exactly "No evaluation results available." when the API returns no runs', async () => {
    mockFetch([{ path: '/api/evaluation/runs', body: [] }]);
    renderWithProviders(<EvaluationPage />);
    const empty = await screen.findByText('No evaluation results available.');
    expect(empty.textContent).toBe('No evaluation results available.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not claim emptiness when the request fails', async () => {
    mockFetch([{ path: '/api/evaluation/runs', status: 500, body: { detail: 'boom' } }]);
    renderWithProviders(<EvaluationPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Server error (500)');
    expect(screen.queryByText('No evaluation results available.')).not.toBeInTheDocument();
  });

  it('lists runs, shows the selected run and compares platform with baseline', async () => {
    const platform = run(2, 'platform', 0.75, null);
    const baseline = run(1, 'baseline', 0.25, null);
    mockFetch([
      { path: '/api/evaluation/runs/2', body: { ...platform, results: [] } },
      { path: '/api/evaluation/runs/1', body: { ...baseline, results: [] } },
      { path: '/api/evaluation/runs', body: [platform, baseline] },
    ]);
    renderWithProviders(<EvaluationPage />);

    const compare = await screen.findByRole('table', { name: 'Side-by-side metrics' });
    expect(
      within(compare).getByRole('columnheader', { name: '#2 (platform)' }),
    ).toBeInTheDocument();
    expect(
      within(compare).getByRole('columnheader', { name: '#1 (baseline)' }),
    ).toBeInTheDocument();
    const rateRow = within(compare).getByRole('row', { name: /Completion rate/ });
    expect(rateRow).toHaveTextContent('75.0%');
    expect(rateRow).toHaveTextContent('25.0%');
    // Unknown cost is reported as such, never as $0.
    expect(within(compare).getByRole('row', { name: /^Inference cost/ })).toHaveTextContent(
      'not applicablenot applicable',
    );
    expect(
      await screen.findByRole('heading', { name: 'Run #2: platform-run' }),
    ).toBeInTheDocument();
    expect(screen.getByText('This run has no recorded task results.')).toBeInTheDocument();
  });
});
