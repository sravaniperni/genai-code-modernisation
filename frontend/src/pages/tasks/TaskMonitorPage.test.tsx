import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { TaskEvent } from '../../lib/types';
import { HEALTH, taskDetail, taskSummary } from '../../test/fixtures';
import { mockFetch, renderWithProviders } from '../../test/utils';
import { TaskMonitorPage } from './TaskMonitorPage';

// Poll fast so the test observes several cycles quickly.
vi.mock('../../lib/config', () => ({
  POLL_INTERVAL_MS: 25,
  OVERVIEW_REFRESH_MS: 60_000,
  HEALTH_REFRESH_MS: 60_000,
}));

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function event(id: number, state: string, message: string, from?: string): TaskEvent {
  return {
    id,
    ts: `2026-10-15T10:00:0${id}+00:00`,
    kind: 'state',
    state,
    message,
    payload: from ? { from, to: state } : {},
  };
}

function afterId(url: string): number {
  return Number(new URL(url, 'http://localhost').searchParams.get('after_id') ?? 0);
}

describe('TaskMonitorPage', () => {
  it('polls the event log with after_id while running and stops once the task is terminal', async () => {
    let state = 'TESTING';
    const events: TaskEvent[] = [
      event(1, 'QUEUED', 'task created at aaaaaaaaaaaa (main)'),
      event(2, 'TESTING', 'IMPLEMENTING -> TESTING', 'IMPLEMENTING'),
    ];
    const { requests } = mockFetch([
      {
        path: '/api/tasks/7/events',
        respond: ({ url }) => events.filter((e) => e.id > afterId(url)),
      },
      { path: '/api/tasks/7/checks', body: [] },
      { path: '/api/tasks/7/model-calls', body: [] },
      { path: /^\/api\/tasks\/7$/, respond: () => taskDetail({ id: 7, state }) },
      { path: '/api/health', body: HEALTH },
    ]);
    const eventCalls = () => requests.filter((r) => r.url.startsWith('/api/tasks/7/events'));

    renderWithProviders(<TaskMonitorPage />, { route: '/tasks/7', path: '/tasks/:taskId' });

    expect(await screen.findByText('IMPLEMENTING -> TESTING')).toBeInTheDocument();
    expect(screen.getByRole('log', { name: 'Event log' })).toHaveAttribute('aria-live', 'polite');
    await waitFor(() => expect(eventCalls().length).toBeGreaterThanOrEqual(4));
    // Incremental: after the first page, requests ask only for events newer than the last one seen.
    expect(eventCalls().slice(-1)[0]!.url).toBe('/api/tasks/7/events?after_id=2');

    // The task finishes: the backend now reports a terminal state and a final event.
    state = 'COMPLETED';
    events.push(event(3, 'COMPLETED', 'VERIFYING -> COMPLETED: verified', 'VERIFYING'));

    expect(await screen.findByText('VERIFYING -> COMPLETED: verified')).toBeInTheDocument();
    expect(await screen.findByText(/Polling stopped/)).toBeInTheDocument();
    await sleep(60);
    const settled = eventCalls().length;
    await sleep(250); // ten polling intervals
    expect(eventCalls().length).toBe(settled);
    // Each event is listed once even though it was polled for many times.
    expect(screen.getAllByText('IMPLEMENTING -> TESTING')).toHaveLength(1);
  });

  it('enables Cancel only for unfinished tasks and Restart only for restartable ones', async () => {
    let state = 'QUEUED';
    const { requests } = mockFetch([
      { path: '/api/tasks/3/events', body: [] },
      { path: '/api/tasks/3/checks', body: [] },
      { path: '/api/tasks/3/model-calls', body: [] },
      {
        method: 'POST',
        path: '/api/tasks/3/cancel',
        respond: () => {
          state = 'CANCELLED';
          return taskSummary({ id: 3, state });
        },
      },
      {
        method: 'POST',
        path: '/api/tasks/3/restart',
        respond: () => {
          state = 'QUEUED';
          return taskSummary({ id: 3, state });
        },
      },
      { path: /^\/api\/tasks\/3$/, respond: () => taskDetail({ id: 3, state }) },
      { path: '/api/health', body: HEALTH },
    ]);
    renderWithProviders(<TaskMonitorPage />, { route: '/tasks/3', path: '/tasks/:taskId' });
    const user = userEvent.setup();

    const cancel = await screen.findByRole('button', { name: 'Cancel task' });
    const restart = screen.getByRole('button', { name: 'Restart task' });
    expect(cancel).toBeEnabled();
    expect(restart).toBeDisabled();
    expect(screen.getByText('Queued: waiting for a worker')).toBeInTheDocument();
    expect(screen.getByText(/No model endpoint is configured/)).toBeInTheDocument();

    await user.click(cancel);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Restart task' })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Cancel task' })).toBeDisabled();
    expect(requests.some((r) => r.method === 'POST' && r.url === '/api/tasks/3/cancel')).toBe(true);

    await user.click(screen.getByRole('button', { name: 'Restart task' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cancel task' })).toBeEnabled());
    expect(requests.some((r) => r.method === 'POST' && r.url === '/api/tasks/3/restart')).toBe(
      true,
    );
  });
});
