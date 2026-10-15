import { useMutation } from '@tanstack/react-query';
import { useId, useState } from 'react';
import { ErrorNotice } from '../../components/ErrorNotice';
import { ApiError, api } from '../../lib/api';
import { humanize } from '../../lib/format';
import type { ApprovalInput, TaskSummary } from '../../lib/types';

const REVIEWER_KEY = 'modernisation.reviewer';

function loadReviewer(): string {
  try {
    return window.localStorage.getItem(REVIEWER_KEY) ?? '';
  } catch {
    return '';
  }
}

function saveReviewer(name: string): void {
  try {
    window.localStorage.setItem(REVIEWER_KEY, name);
  } catch {
    // storage unavailable; the name simply is not remembered
  }
}

const CONSEQUENCES: Record<'plan' | 'publish', { approve: string; reject: string }> = {
  plan: {
    approve: 'Approving lets the agent implement this plan.',
    reject: 'Rejecting cancels the task.',
  },
  publish: {
    approve: 'Approving publishes the verified change (branch and pull request).',
    reject: 'Rejecting keeps the verified change unpublished and completes the task.',
  },
};

/**
 * Approve or reject a task waiting at the plan or publish gate. The decision is bound to the task
 * version the reviewer is looking at (expected_version); if the task changed meanwhile the API answers
 * 409 and nothing is recorded.
 */
export function ApprovalForm({
  task,
  onDecided,
  onReload,
}: {
  task: Pick<TaskSummary, 'id' | 'version' | 'approval_stage' | 'state'>;
  onDecided?: (task: TaskSummary) => void;
  onReload?: () => void;
}) {
  const id = useId();
  const [reviewer, setReviewer] = useState(loadReviewer);
  const [comment, setComment] = useState('');
  const stage =
    task.approval_stage === 'plan' || task.approval_stage === 'publish'
      ? task.approval_stage
      : null;

  const decide = useMutation({
    mutationFn: (body: ApprovalInput) => api.tasks.approve(task.id, body),
    onSuccess: (updated) => {
      if (reviewer.trim()) saveReviewer(reviewer.trim());
      onDecided?.(updated);
    },
  });

  if (task.state !== 'AWAITING_APPROVAL' || stage === null) {
    return (
      <p className="notice notice-info">
        Approval is only possible while the task is awaiting plan or publish approval (current
        state: {humanize(task.state)}).
      </p>
    );
  }

  const submit = (decision: 'approved' | 'rejected') => {
    decide.mutate({
      stage,
      decision,
      reviewer: reviewer.trim(),
      comment: comment.trim() ? comment.trim() : null,
      expected_version: task.version,
    });
  };
  const conflict =
    decide.error instanceof ApiError && decide.error.status === 409 ? decide.error : null;

  return (
    <form
      className="form approval-form"
      onSubmit={(e) => e.preventDefault()}
      aria-labelledby={`${id}-title`}
    >
      <h3 id={`${id}-title`}>{stage === 'plan' ? 'Plan approval' : 'Publication approval'}</h3>
      <p className="hint">
        {CONSEQUENCES[stage].approve} {CONSEQUENCES[stage].reject} Your decision applies to version{' '}
        {task.version} of the task.
      </p>
      <div className="field">
        <label htmlFor={`${id}-reviewer`}>Reviewer name</label>
        <input
          id={`${id}-reviewer`}
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          autoComplete="name"
          maxLength={200}
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-comment`}>
          Comment <span className="optional">(optional)</span>
        </label>
        <textarea
          id={`${id}-comment`}
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          maxLength={4000}
        />
      </div>
      {conflict ? (
        <div className="notice notice-error" role="alert">
          <p className="notice-title">Conflict (409): nothing was recorded</p>
          <p>{conflict.message}</p>
          <p>
            The task changed after this page loaded, or it is no longer waiting for this approval.
          </p>
          {onReload ? (
            <button
              type="button"
              onClick={() => {
                decide.reset();
                onReload();
              }}
            >
              Reload task and review again
            </button>
          ) : null}
        </div>
      ) : (
        <ErrorNotice error={decide.error} />
      )}
      {decide.isSuccess ? (
        <p className="notice notice-success" role="status">
          Decision recorded. Task is now {humanize(decide.data.state)}.
        </p>
      ) : null}
      <div className="button-row">
        <button
          type="button"
          className="primary"
          disabled={decide.isPending}
          onClick={() => submit('approved')}
        >
          {stage === 'plan' ? 'Approve plan' : 'Approve publication'}
        </button>
        <button
          type="button"
          className="danger"
          disabled={decide.isPending}
          onClick={() => submit('rejected')}
        >
          Reject
        </button>
      </div>
    </form>
  );
}
