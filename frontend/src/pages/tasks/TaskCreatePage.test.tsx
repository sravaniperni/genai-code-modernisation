import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { META } from '../../test/fixtures';
import { mockFetch, renderWithProviders } from '../../test/utils';
import { TaskCreatePage } from './TaskCreatePage';

const REPO = {
  id: 4,
  name: 'inventory',
  source_kind: 'local',
  source: '/srv/inventory',
  github_full_name: null,
  default_branch: 'main',
  created_at: '2026-10-15T10:00:00+00:00',
  latest_snapshot: null,
  task_counts: {},
};

describe('TaskCreatePage', () => {
  it('submits the form to POST /api/tasks and shows 422 details next to the fields', async () => {
    const { requests } = mockFetch([
      { path: '/api/repositories/4/branches', body: { main: 'b'.repeat(40) } },
      { path: '/api/repositories', body: [REPO] },
      { path: '/api/meta', body: META },
      { path: '/api/settings', status: 503, body: { detail: 'unavailable' } },
      {
        method: 'POST',
        path: '/api/tasks',
        status: 422,
        body: {
          detail: [
            {
              type: 'string_too_short',
              loc: ['body', 'title'],
              msg: 'String should have at least 3 characters',
            },
            {
              type: 'value_error',
              loc: ['body', 'allowed_paths'],
              msg: "Value error, scope patterns must be repository-relative without '..': '../secrets'",
            },
          ],
        },
      },
    ]);
    renderWithProviders(<TaskCreatePage />, { route: '/tasks/new?repository_id=4' });
    const user = userEvent.setup();

    await screen.findByRole('option', { name: 'inventory (local)' });
    expect(screen.getByLabelText('Repository')).toHaveValue('4');
    await user.type(screen.getByLabelText('Title'), 'Fx');
    await user.type(screen.getByLabelText('Request'), 'apply_discount divides by 1000.');
    await screen.findByRole('option', { name: 'bug fix' });
    await user.selectOptions(screen.getByLabelText('Category'), 'bug_fix');
    await user.type(screen.getByLabelText('Allowed paths'), 'src/**\n../secrets\n');
    await user.type(screen.getByLabelText('Forbidden paths'), 'tests/fixtures/**');
    await user.click(screen.getByLabelText(/Require plan approval/));
    await user.click(screen.getByRole('button', { name: 'Create task' }));

    expect(
      await screen.findByText('String should have at least 3 characters', {
        selector: '.field-error',
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Title')).toHaveAccessibleDescription(
      expect.stringContaining('String should have at least 3 characters') as string,
    );
    expect(screen.getByLabelText('Allowed paths')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('alert')).toHaveTextContent('The API rejected the task (422)');

    const post = requests.find((r) => r.method === 'POST');
    expect(post?.body).toEqual({
      repository_id: 4,
      title: 'Fx',
      request: 'apply_discount divides by 1000.',
      category: 'bug_fix',
      allowed_paths: ['src/**', '../secrets'],
      forbidden_paths: ['tests/fixtures/**'],
      config: {
        max_attempts: 3,
        require_plan_approval: true,
        allow_test_changes: true,
        strategy: 'agentic',
      },
    });
  });
});
