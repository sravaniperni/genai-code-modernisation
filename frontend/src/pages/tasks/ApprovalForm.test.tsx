import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { taskSummary } from '../../test/fixtures';
import { mockFetch, renderWithProviders } from '../../test/utils';
import { ApprovalForm } from './ApprovalForm';

const waiting = { id: 5, version: 7, approval_stage: 'publish', state: 'AWAITING_APPROVAL' };

describe('ApprovalForm', () => {
  it('sends the decision bound to the task version it shows (expected_version)', async () => {
    const { requests } = mockFetch([
      {
        method: 'POST',
        path: '/api/tasks/5/approval',
        body: taskSummary({ id: 5, state: 'PUBLISHING', version: 8 }),
      },
    ]);
    const onDecided = vi.fn();
    renderWithProviders(<ApprovalForm task={waiting} onDecided={onDecided} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Reviewer name'), 'Ada Lovelace');
    await user.type(screen.getByLabelText(/Comment/), 'Diff and checks look right.');
    await user.click(screen.getByRole('button', { name: 'Approve publication' }));

    expect(await screen.findByText(/Decision recorded/)).toHaveTextContent('PUBLISHING');
    const post = requests.find((r) => r.method === 'POST');
    expect(post?.url).toBe('/api/tasks/5/approval');
    expect(post?.body).toEqual({
      stage: 'publish',
      decision: 'approved',
      reviewer: 'Ada Lovelace',
      comment: 'Diff and checks look right.',
      expected_version: 7,
    });
    expect(onDecided).toHaveBeenCalledOnce();
  });

  it('sends a rejection at the plan stage with a null comment when none is given', async () => {
    const { requests } = mockFetch([
      {
        method: 'POST',
        path: '/api/tasks/5/approval',
        body: taskSummary({ id: 5, state: 'CANCELLED' }),
      },
    ]);
    renderWithProviders(<ApprovalForm task={{ ...waiting, approval_stage: 'plan', version: 3 }} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Reviewer name'), 'Grace');
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    await screen.findByText(/Decision recorded/);
    expect(requests[0]?.body).toEqual({
      stage: 'plan',
      decision: 'rejected',
      reviewer: 'Grace',
      comment: null,
      expected_version: 3,
    });
  });

  it('explains a 409 conflict and offers to reload', async () => {
    mockFetch([
      {
        method: 'POST',
        path: '/api/tasks/5/approval',
        status: 409,
        body: {
          detail: 'task 5 changed since it was reviewed (version 8 != 7); reload and review again',
        },
      },
    ]);
    const onReload = vi.fn();
    renderWithProviders(<ApprovalForm task={waiting} onReload={onReload} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Reviewer name'), 'Ada');
    await user.click(screen.getByRole('button', { name: 'Approve publication' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Conflict (409)');
    expect(alert).toHaveTextContent('version 8 != 7');
    await user.click(screen.getByRole('button', { name: 'Reload task and review again' }));
    expect(onReload).toHaveBeenCalledOnce();
  });

  it('offers no approval controls when the task is not waiting for approval', () => {
    mockFetch([]);
    renderWithProviders(
      <ApprovalForm task={{ ...waiting, state: 'TESTING', approval_stage: null }} />,
    );
    expect(screen.getByText(/Approval is only possible/)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
