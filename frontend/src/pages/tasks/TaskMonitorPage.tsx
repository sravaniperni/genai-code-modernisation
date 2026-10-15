import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { StateBadge } from '../../components/Badge';
import { EmptyState, ErrorNotice, Loading } from '../../components/ErrorNotice';
import { EventLog } from '../../components/EventLog';
import { KeyValueList } from '../../components/KeyValue';
import { PageHeader } from '../../components/PageHeader';
import { StateTimeline } from '../../components/StateTimeline';
import { useDocumentTitle } from '../../hooks/useDocumentTitle';
import { useTaskEvents } from '../../hooks/useTaskEvents';
import { api } from '../../lib/api';
import { POLL_INTERVAL_MS } from '../../lib/config';
import { formatCost, formatDurationMs, formatInt, formatTime } from '../../lib/format';
import { canCancel, canRestart, isTerminal } from '../../lib/states';
import type { TaskDetail, TaskEvent } from '../../lib/types';
import { ChecksTable } from './ChecksTable';
import { ModelCallsTable } from './ModelCallsTable';
import { TaskFacts, TaskScope } from './TaskFacts';
import { useTask, useTaskActions } from './useTask';

function StatusNotice({
  task,
  modelConfigured,
}: {
  task: TaskDetail;
  modelConfigured: boolean | null;
}) {
  if (task.state === 'QUEUED') {
    return (
      <div className="notice notice-info" role="status">
        <p className="notice-title">Queued: waiting for a worker</p>
        <p>
          The task starts when a worker process (<code>modernisation worker</code>) claims it. The
          API does not report whether a worker is running, so this page shows only what has been
          recorded.
        </p>
        {modelConfigured === false ? (
          <p>
            No model endpoint is configured on this backend, so a worker could not analyse, plan or
            implement this task. See <Link to="/settings">Settings</Link>.
          </p>
        ) : null}
      </div>
    );
  }
  if (task.state === 'AWAITING_APPROVAL') {
    return (
      <div className="notice notice-attention" role="status">
        <p className="notice-title">Waiting for {task.approval_stage ?? 'human'} approval</p>
        <p>
          <Link to={`/tasks/${task.id}/review`}>
            Review the {task.approval_stage === 'plan' ? 'plan' : 'change'}
          </Link>{' '}
          to approve or reject it.
        </p>
      </div>
    );
  }
  if (task.cancel_requested && !isTerminal(task.state)) {
    return (
      <p className="notice notice-attention" role="status">
        Cancellation requested; the worker stops at its next checkpoint.
      </p>
    );
  }
  return null;
}

function ToolExecutions({ events }: { events: TaskEvent[] }) {
  const tools = events.filter((e) => e.kind === 'tool');
  if (tools.length === 0) return <EmptyState>No tool executions recorded.</EmptyState>;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">Tool executions</caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Tool</th>
            <th scope="col">State</th>
            <th scope="col">Result</th>
            <th scope="col">Duration</th>
          </tr>
        </thead>
        <tbody>
          {tools.map((e) => (
            <tr key={e.id}>
              <td>{formatTime(e.ts)}</td>
              <td>
                <code>{typeof e.payload?.tool === 'string' ? e.payload.tool : '—'}</code>
              </td>
              <td>{e.state ?? '—'}</td>
              <td>{e.message}</td>
              <td>
                {typeof e.payload?.duration_ms === 'number'
                  ? formatDurationMs(e.payload.duration_ms)
                  : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RetriesAndErrors({ task, events }: { task: TaskDetail; events: TaskEvent[] }) {
  const errors = events.filter((e) => e.kind === 'error');
  const rejected = task.attempts.filter(
    (a) => a.apply_status !== 'applied' || a.checks_passed === false,
  );
  if (errors.length === 0 && rejected.length === 0 && task.usage.failed_calls === 0) {
    return <EmptyState>No errors or retries recorded.</EmptyState>;
  }
  return (
    <div>
      {task.usage.failed_calls > 0 ? (
        <p>
          {task.usage.failed_calls} model call{task.usage.failed_calls === 1 ? '' : 's'} failed (see
          the model calls table).
        </p>
      ) : null}
      {rejected.length > 0 ? (
        <>
          <h4>Attempts that did not pass</h4>
          <ul>
            {rejected.map((a) => (
              <li key={a.attempt_no}>
                Attempt {a.attempt_no} ({a.kind}): {a.apply_status}
                {a.rejection_reason ? ` — ${a.rejection_reason}` : ''}
                {a.checks_passed === false ? ' — checks failed' : ''}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {errors.length > 0 ? (
        <>
          <h4>Error events</h4>
          <ul>
            {errors.map((e) => (
              <li key={e.id}>
                <time dateTime={e.ts}>{formatTime(e.ts)}</time> {e.message}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

export function TaskMonitorPage() {
  const params = useParams();
  const taskId = Number(params.taskId);
  const validId = Number.isInteger(taskId) && taskId > 0;
  useDocumentTitle(`Task ${params.taskId ?? ''}`);
  const task = useTask(taskId, validId);
  const active = task.data ? !isTerminal(task.data.state) : false;
  const stream = useTaskEvents(taskId, active, POLL_INTERVAL_MS, validId);
  const checks = useQuery({
    queryKey: ['task', taskId, 'checks'],
    queryFn: () => api.tasks.checks(taskId),
    enabled: validId,
    refetchInterval: active ? POLL_INTERVAL_MS * 2 : false,
  });
  const calls = useQuery({
    queryKey: ['task', taskId, 'model-calls'],
    queryFn: () => api.tasks.modelCalls(taskId),
    enabled: validId,
    refetchInterval: active ? POLL_INTERVAL_MS * 2 : false,
  });
  const health = useQuery({ queryKey: ['health'], queryFn: api.health });
  const { cancel, restart } = useTaskActions(taskId);

  if (!validId) {
    return <ErrorNotice error={new Error('Invalid task id.')} />;
  }
  if (task.isPending) return <Loading label="Loading task…" />;
  if (task.isError) return <ErrorNotice error={task.error} />;

  const t = task.data;
  const cancellable = canCancel(t.state) && !t.cancel_requested;
  const restartable = canRestart(t.state);

  return (
    <>
      <PageHeader
        title={
          <>
            <span className="muted">Task {t.id}:</span> {t.title}
          </>
        }
        description={
          <span className="header-state">
            <StateBadge state={t.state} />
            {t.state_reason ? <span>{t.state_reason}</span> : null}
          </span>
        }
        actions={
          <>
            <button
              type="button"
              className="danger"
              onClick={() => cancel.mutate()}
              disabled={!cancellable || cancel.isPending}
              aria-describedby="action-help"
            >
              {cancel.isPending ? 'Cancelling…' : 'Cancel task'}
            </button>
            <button
              type="button"
              onClick={() => restart.mutate()}
              disabled={!restartable || restart.isPending}
              aria-describedby="action-help"
            >
              {restart.isPending ? 'Restarting…' : 'Restart task'}
            </button>
            <Link className="button" to={`/tasks/${t.id}/review`}>
              Code review
            </Link>
          </>
        }
      />
      <p id="action-help" className="hint">
        Cancel is available until the task finishes; restart is available for failed, cancelled or
        escalated tasks.
      </p>
      <ErrorNotice error={cancel.error} title="Cancel failed" />
      <ErrorNotice error={restart.error} title="Restart failed" />
      <StatusNotice task={t} modelConfigured={health.data ? health.data.model_configured : null} />

      <section className="panel" aria-labelledby="facts-heading">
        <h2 id="facts-heading">Task</h2>
        <TaskFacts task={t} />
        <details>
          <summary>Maintenance request and scope</summary>
          <pre className="request-text">{t.request}</pre>
          <TaskScope task={t} />
        </details>
      </section>

      <div className="grid-monitor">
        <section className="panel" aria-labelledby="timeline-heading">
          <h2 id="timeline-heading">State timeline</h2>
          <StateTimeline events={stream.events} />
        </section>
        <section className="panel" aria-labelledby="log-heading">
          <h2 id="log-heading">Event log</h2>
          <EventLog stream={stream} />
        </section>
      </div>

      <section className="panel" aria-labelledby="tools-heading">
        <h2 id="tools-heading">Tool executions</h2>
        <ToolExecutions events={stream.events} />
      </section>

      <section className="panel" aria-labelledby="calls-heading">
        <h2 id="calls-heading">Model calls</h2>
        <KeyValueList
          className="kv-compact kv-columns"
          items={[
            ['Calls', formatInt(t.usage.model_calls)],
            ['Failed calls', formatInt(t.usage.failed_calls)],
            ['Prompt tokens', formatInt(t.usage.prompt_tokens)],
            ['Completion tokens', formatInt(t.usage.completion_tokens)],
            ['Model latency (total)', formatDurationMs(t.usage.model_latency_ms)],
            ['Cost', formatCost(t.usage.cost_usd)],
          ]}
        />
        {calls.isPending ? <Loading /> : null}
        <ErrorNotice error={calls.error} />
        {calls.data && calls.data.length === 0 ? (
          <EmptyState>No model calls recorded for this task.</EmptyState>
        ) : null}
        {calls.data && calls.data.length > 0 ? <ModelCallsTable calls={calls.data} /> : null}
      </section>

      <section className="panel" aria-labelledby="checks-heading">
        <h2 id="checks-heading">Check runs</h2>
        {checks.isPending ? <Loading /> : null}
        <ErrorNotice error={checks.error} />
        {checks.data && checks.data.length === 0 ? (
          <EmptyState>No checks have run for this task.</EmptyState>
        ) : null}
        {checks.data && checks.data.length > 0 ? (
          <ChecksTable checks={checks.data} caption="Check runs for this task" />
        ) : null}
      </section>

      <section className="panel" aria-labelledby="attempts-heading">
        <h2 id="attempts-heading">Patch attempts</h2>
        {t.attempts.length === 0 ? (
          <EmptyState>No patch attempts yet.</EmptyState>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Patch attempts</caption>
              <thead>
                <tr>
                  <th scope="col" className="num">
                    Attempt
                  </th>
                  <th scope="col">Kind</th>
                  <th scope="col">Applied</th>
                  <th scope="col">Checks</th>
                  <th scope="col">Files changed</th>
                  <th scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {t.attempts.map((a) => (
                  <tr key={a.attempt_no}>
                    <td className="num">
                      <Link to={`/tasks/${t.id}/review?attempt=${a.attempt_no}`}>
                        {a.attempt_no}
                      </Link>
                    </td>
                    <td>{a.kind}</td>
                    <td>
                      {a.apply_status}
                      {a.rejection_reason ? (
                        <div className="cell-note">{a.rejection_reason}</div>
                      ) : null}
                    </td>
                    <td>
                      {a.checks_passed === null ? 'not run' : a.checks_passed ? 'passed' : 'failed'}
                    </td>
                    <td>{a.files_changed.length ? a.files_changed.join(', ') : '—'}</td>
                    <td>{formatTime(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel" aria-labelledby="errors-heading">
        <h2 id="errors-heading">Retries and errors</h2>
        <RetriesAndErrors task={t} events={stream.events} />
      </section>
    </>
  );
}
