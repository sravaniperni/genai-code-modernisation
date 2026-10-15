import { Link } from 'react-router';
import { KeyValueList, type KeyValueItem } from '../../components/KeyValue';
import { formatDateTime, humanize, shortSha } from '../../lib/format';
import type { TaskDetail } from '../../lib/types';

export function TaskFacts({ task }: { task: TaskDetail }) {
  const maxAttempts =
    typeof task.config?.max_attempts === 'number' ? task.config.max_attempts : null;
  return (
    <KeyValueList
      className="kv-compact kv-columns"
      items={[
        [
          'Repository',
          <Link key="r" to={`/repositories/${task.repository_id}`}>
            {task.repository}
          </Link>,
        ],
        ['Category', humanize(task.category)],
        ['State reason', task.state_reason ?? '—'],
        ['Approval stage', task.approval_stage ?? '—'],
        [
          'Attempts',
          maxAttempts ? `${task.attempt_count} of ${maxAttempts}` : String(task.attempt_count),
        ],
        ['Version', String(task.version)],
        ['Cancel requested', task.cancel_requested ? 'yes' : 'no'],
        ['Resumed after lost lease', String(task.resume_count)],
        ['Origin', task.origin],
        [
          'Base',
          <span key="b">
            {task.base_ref} @ <code title={task.base_commit}>{shortSha(task.base_commit)}</code>
          </span>,
        ],
        ['Created', formatDateTime(task.created_at)],
        ['Started', formatDateTime(task.started_at)],
        ['Finished', formatDateTime(task.finished_at)],
        ['Updated', formatDateTime(task.updated_at)],
        ...(task.branch_name
          ? [['Branch', <code key="br">{task.branch_name}</code>] as KeyValueItem]
          : []),
        ...(task.pr_url
          ? [
              [
                'Pull request',
                <a key="pr" href={task.pr_url} target="_blank" rel="noreferrer">
                  #{task.pr_number ?? ''} (opens GitHub)
                </a>,
              ] as KeyValueItem,
            ]
          : []),
      ]}
    />
  );
}

export function TaskScope({ task }: { task: TaskDetail }) {
  return (
    <div className="scope">
      <div>
        <h4>Allowed paths</h4>
        {task.allowed_paths.length ? (
          <ul className="plain-list">
            {task.allowed_paths.map((p) => (
              <li key={p}>
                <code>{p}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">Not restricted.</p>
        )}
      </div>
      <div>
        <h4>Forbidden paths</h4>
        {task.forbidden_paths.length ? (
          <ul className="plain-list">
            {task.forbidden_paths.map((p) => (
              <li key={p}>
                <code>{p}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">None.</p>
        )}
      </div>
    </div>
  );
}
