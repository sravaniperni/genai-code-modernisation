import { describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../test/utils';
import { ApiError, api } from './api';
import { setApiToken } from './token';

describe('api client', () => {
  it('sends the stored bearer token with mutations but not with reads', async () => {
    const { requests } = mockFetch([
      { path: '/api/repositories', body: [] },
      { method: 'POST', path: '/api/tasks/1/cancel', body: {} },
    ]);
    setApiToken('s3cret');
    await api.repositories.list();
    await api.tasks.cancel(1);
    expect(requests[0]!.headers.Authorization).toBeUndefined();
    expect(requests[1]!.headers.Authorization).toBe('Bearer s3cret');
    setApiToken(null);
    await api.tasks.cancel(1);
    expect(requests[2]!.headers.Authorization).toBeUndefined();
  });

  it('turns FastAPI error bodies into ApiError with status, message and field errors', async () => {
    mockFetch([
      {
        method: 'POST',
        path: '/api/repositories',
        status: 403,
        body: { detail: '/etc is not under an authorised local root' },
      },
      {
        method: 'POST',
        path: '/api/tasks',
        status: 422,
        body: {
          detail: [
            {
              loc: ['body', 'config', 'max_attempts'],
              msg: 'Input should be less than or equal to 6',
            },
          ],
        },
      },
    ]);
    const forbidden = await api.repositories
      .create({ kind: 'local', source: '/etc' })
      .catch((e: unknown) => e);
    expect(forbidden).toBeInstanceOf(ApiError);
    expect(forbidden).toMatchObject({
      status: 403,
      message: '/etc is not under an authorised local root',
    });

    const invalid = (await api.tasks
      .create({
        repository_id: 1,
        title: 'xxx',
        request: 'y'.repeat(20),
        category: 'bug_fix',
        allowed_paths: [],
        forbidden_paths: [],
        config: {
          max_attempts: 9,
          require_plan_approval: false,
          allow_test_changes: true,
          strategy: 'agentic',
        },
      })
      .catch((e: unknown) => e)) as ApiError;
    expect(invalid.status).toBe(422);
    expect(invalid.fieldErrors).toHaveLength(1);
    expect(invalid.message).toBe('config.max_attempts: Input should be less than or equal to 6');
  });

  it('reports an unreachable server as status 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    );
    await expect(api.health()).rejects.toMatchObject({ status: 0 });
  });

  it('builds query strings and omits empty parameters', async () => {
    const { requests } = mockFetch([{ path: '/api/', body: [] }]);
    await api.tasks.list({ state: 'QUEUED', repository_id: undefined });
    await api.repositories.search(2, 'percent / 1000', 'text', 'main');
    expect(requests[0]!.url).toBe('/api/tasks?state=QUEUED');
    expect(requests[1]!.url).toBe(
      '/api/repositories/2/search?q=percent+%2F+1000&mode=text&ref=main&limit=200',
    );
  });
});
