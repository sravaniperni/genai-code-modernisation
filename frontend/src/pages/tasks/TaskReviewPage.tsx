import { useQuery } from '@tanstack/react-query';
import { useId } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { PassFail, StateBadge } from '../../components/Badge';
import { DiffViewer } from '../../components/DiffViewer';
import { EmptyState, ErrorNotice, Loading } from '../../components/ErrorNotice';
import { JsonDetails, KeyValueList } from '../../components/KeyValue';
import { PageHeader } from '../../components/PageHeader';
import { useDocumentTitle } from '../../hooks/useDocumentTitle';
import { api } from '../../lib/api';
import { POLL_INTERVAL_MS } from '../../lib/config';
import { formatDateTime } from '../../lib/format';
import { isTerminal } from '../../lib/states';
import type { TaskDetail } from '../../lib/types';
import { ApprovalForm } from './ApprovalForm';
import { ChecksTable, checkPassed } from './ChecksTable';
import { PlanView } from './PlanView';
import { VerificationSummary } from './VerificationSummary';
import { useInvalidateTask, useTask } from './useTask';

function AttemptPanel({ taskId, attemptNo }: { taskId: number; attemptNo: number }) {
  const attempt = useQuery({
    queryKey: ['task', taskId, 'attempt', attemptNo],
    queryFn: () => api.tasks.attempt(taskId, attemptNo),
  });
  if (attempt.isPending) return <Loading label={`Loading attempt ${attemptNo}…`} />;
  if (attempt.isError) return <ErrorNotice error={attempt.error} />;
  const a = attempt.data;
  return (
    <div className="attempt">
      <KeyValueList
        className="kv-compact kv-columns"
        items={[
          ['Kind', a.kind],
          ['Apply status', a.apply_status],
          ['Rejection reason', a.rejection_reason ?? '—'],
          ['Checks', <PassFail key="c" passed={a.checks_passed} />],
          ['Files changed', a.files_changed.length ? a.files_changed.join(', ') : '—'],
        ]}
      />
      <DiffViewer diff={a.diff} emptyText="This attempt produced no diff." />
      <JsonDetails label="Structured edits proposed by the model" value={a.edits} />
      {a.raw_output ? (
        <details className="json-details">
          <summary>Raw model output</summary>
          <pre className="code-block">{a.raw_output}</pre>
        </details>
      ) : null}
    </div>
  );
}

function Attempts({ task }: { task: TaskDetail }) {
  const id = useId();
  const [params, setParams] = useSearchParams();
  if (task.attempts.length === 0) return <EmptyState>No patch attempts yet.</EmptyState>;
  const requested = Number(params.get('attempt'));
  const selected = task.attempts.some((a) => a.attempt_no === requested)
    ? requested
    : task.attempts[task.attempts.length - 1]!.attempt_no;
  return (
    <div>
      <div className="field inline-field">
        <label htmlFor={`${id}-attempt`}>Attempt</label>
        <select
          id={`${id}-attempt`}
          value={selected}
          onChange={(e) =>
            setParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                next.set('attempt', e.target.value);
                return next;
              },
              { replace: true },
            )
          }
        >
          {task.attempts.map((a) => (
            <option key={a.attempt_no} value={a.attempt_no}>
              Attempt {a.attempt_no} ({a.kind}, {a.apply_status}
              {a.checks_passed === null
                ? ''
                : a.checks_passed
                  ? ', checks passed'
                  : ', checks failed'}
              )
            </option>
          ))}
        </select>
      </div>
      <AttemptPanel key={selected} taskId={task.id} attemptNo={selected} />
    </div>
  );
}

function ChecksSection({ taskId, active }: { taskId: number; active: boolean }) {
  const checks = useQuery({
    queryKey: ['task', taskId, 'checks'],
    queryFn: () => api.tasks.checks(taskId),
    refetchInterval: active ? POLL_INTERVAL_MS * 2 : false,
  });
  if (checks.isPending) return <Loading />;
  if (checks.isError) return <ErrorNotice error={checks.error} />;
  if (checks.data.length === 0) return <EmptyState>No checks have run for this task.</EmptyState>;
  const passed = checks.data.filter(checkPassed).length;
  return (
    <>
      <p className="muted">
        {passed} of {checks.data.length} check runs passed (baseline runs record the state before
        any change).
      </p>
      <ChecksTable checks={checks.data} caption="Checks performed for this task" />
    </>
  );
}

export function TaskReviewPage() {
  const params = useParams();
  const taskId = Number(params.taskId);
  const validId = Number.isInteger(taskId) && taskId > 0;
  useDocumentTitle(`Review task ${params.taskId ?? ''}`);
  const task = useTask(taskId, validId);
  const invalidate = useInvalidateTask(taskId);

  if (!validId) return <ErrorNotice error={new Error('Invalid task id.')} />;
  if (task.isPending) return <Loading label="Loading task…" />;
  if (task.isError) return <ErrorNotice error={task.error} />;
  const t = task.data;
  const active = !isTerminal(t.state);

  return (
    <>
      <PageHeader
        title={
          <>
            <span className="muted">Review task {t.id}:</span> {t.title}
          </>
        }
        description={
          <span className="header-state">
            <StateBadge state={t.state} />
            {t.state_reason ? <span>{t.state_reason}</span> : null}
            <span className="muted">version {t.version}</span>
          </span>
        }
        actions={
          <Link className="button" to={`/tasks/${t.id}`}>
            Execution monitor
          </Link>
        }
      />

      <section className="panel" aria-labelledby="approval-heading">
        <h2 id="approval-heading">Approval</h2>
        <ApprovalForm task={t} onDecided={invalidate} onReload={() => void task.refetch()} />
        {t.approvals.length > 0 ? (
          <>
            <h3>Decisions so far</h3>
            <ul className="plain-list">
              {t.approvals.map((a, i) => (
                <li key={i}>
                  <PassFail passed={a.decision === 'approved'} label={a.decision} /> {a.stage} by{' '}
                  <strong>{a.reviewer}</strong> on {formatDateTime(a.created_at)}
                  {a.comment ? <blockquote>{a.comment}</blockquote> : null}
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </section>

      <div className="grid-2">
        <section className="panel" aria-labelledby="plan-heading">
          <h2 id="plan-heading">Plan</h2>
          <PlanView plan={t.plan} />
        </section>
        <section className="panel" aria-labelledby="verification-heading">
          <h2 id="verification-heading">Verification summary</h2>
          <VerificationSummary result={t.result} />
        </section>
      </div>

      <section className="panel" aria-labelledby="diff-heading">
        <h2 id="diff-heading">Final diff</h2>
        <DiffViewer
          diff={t.final_diff}
          emptyText="No final diff: the task has not produced a verified change."
        />
      </section>

      <section className="panel" aria-labelledby="attempts-heading">
        <h2 id="attempts-heading">Attempt diffs</h2>
        <Attempts task={t} />
      </section>

      <section className="panel" aria-labelledby="checks-heading">
        <h2 id="checks-heading">Checks performed</h2>
        <ChecksSection taskId={t.id} active={active} />
      </section>
    </>
  );
}
