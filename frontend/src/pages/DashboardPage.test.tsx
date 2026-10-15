import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { META, taskSummary } from '../test/fixtures';
import { mockFetch, renderWithProviders } from '../test/utils';
import { DashboardPage } from './DashboardPage';

function tileValue(label: string): string | null | undefined {
  return screen.getByText(label, { selector: '.stat-tile dt' }).nextElementSibling?.textContent;
}

describe('DashboardPage', () => {
  it('renders the figures returned by GET /api/dashboard', async () => {
    mockFetch([
      { path: '/api/meta', body: META },
      {
        path: '/api/dashboard',
        body: {
          repositories: 2,
          tasks_by_state: { QUEUED: 1, TESTING: 1, COMPLETED: 3, FAILED: 1, ESCALATED: 1 },
          completed: 3,
          failed: 2,
          active: [
            taskSummary({ id: 9, title: 'Upgrade requests', state: 'TESTING', attempt_count: 2 }),
            taskSummary({ id: 8, title: 'Fix discount', state: 'QUEUED' }),
          ],
          recent: [
            taskSummary({
              id: 4,
              title: 'Migrate utcnow',
              state: 'COMPLETED',
              finished_at: '2026-10-15T11:00:00+00:00',
            }),
          ],
          model_usage: { calls: 12, prompt_tokens: 3400, completion_tokens: 560 },
        },
      },
    ]);
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText('Upgrade requests')).toBeInTheDocument();
    expect(tileValue('Repositories')).toBe('2');
    expect(tileValue('Tasks')).toBe('7');
    expect(tileValue('Active tasks')).toContain('2');
    expect(tileValue('Completed')).toBe('3');
    expect(tileValue('Failed or escalated')).toBe('2');
    expect(tileValue('Model calls')).toBe('12');

    const chart = screen.getByRole('img', { name: /Number of tasks in each state/ });
    expect(chart).toHaveAccessibleName(expect.stringContaining('QUEUED: 1') as string);
    expect(chart).toHaveAccessibleName(expect.stringContaining('COMPLETED: 3') as string);

    const active = screen.getByRole('region', { name: 'Active tasks' });
    expect(within(active).getAllByRole('row')).toHaveLength(3); // header + 2 tasks
    expect(within(active).getByRole('link', { name: 'Upgrade requests' })).toHaveAttribute(
      'href',
      '/tasks/9',
    );
    const recent = screen.getByRole('region', { name: 'Recent history' });
    expect(within(recent).getByText('Migrate utcnow')).toBeInTheDocument();

    const usage = screen.getByRole('region', { name: 'Model usage' });
    expect(within(usage).getByText('3,960')).toBeInTheDocument();
  });

  it('shows explicit empty states when nothing has happened yet', async () => {
    mockFetch([
      { path: '/api/meta', body: META },
      {
        path: '/api/dashboard',
        body: {
          repositories: 0,
          tasks_by_state: {},
          completed: 0,
          failed: 0,
          active: [],
          recent: [],
          model_usage: { calls: 0, prompt_tokens: 0, completion_tokens: 0 },
        },
      },
    ]);
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText(/No tasks have been created yet/)).toBeInTheDocument();
    expect(screen.getByText('No active tasks.')).toBeInTheDocument();
    expect(screen.getByText('No tasks have finished yet.')).toBeInTheDocument();
    expect(screen.getByText('No model calls have been recorded.')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('reports an unreachable API instead of showing numbers', async () => {
    mockFetch([{ path: '/api/dashboard', status: 503, body: { detail: 'database unavailable' } }]);
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('database unavailable');
    expect(
      screen.queryByText('Repositories', { selector: '.stat-tile dt' }),
    ).not.toBeInTheDocument();
  });
});
