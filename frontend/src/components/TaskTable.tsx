import { Link } from 'react-router';
import { formatDateTime, humanize } from '../lib/format';
import type { TaskSummary } from '../lib/types';
import { StateBadge } from './Badge';

export function TaskTable({
  tasks,
  caption,
  timeColumn = 'updated',
}: {
  tasks: TaskSummary[];
  caption: string;
  timeColumn?: 'updated' | 'finished';
}) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">ID</th>
            <th scope="col">Title</th>
            <th scope="col">Repository</th>
            <th scope="col">Category</th>
            <th scope="col">State</th>
            <th scope="col" className="num">
              Attempts
            </th>
            <th scope="col">{timeColumn === 'finished' ? 'Finished' : 'Updated'}</th>
            <th scope="col">
              <span className="visually-hidden">Links</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id}>
              <td className="num">{task.id}</td>
              <td>
                <Link to={`/tasks/${task.id}`}>{task.title}</Link>
                {task.state_reason ? <div className="cell-note">{task.state_reason}</div> : null}
              </td>
              <td>{task.repository}</td>
              <td>{humanize(task.category)}</td>
              <td>
                <StateBadge state={task.state} />
                {task.approval_stage && task.state === 'AWAITING_APPROVAL' ? (
                  <div className="cell-note">{task.approval_stage} approval</div>
                ) : null}
              </td>
              <td className="num">{task.attempt_count}</td>
              <td>
                {formatDateTime(timeColumn === 'finished' ? task.finished_at : task.updated_at)}
              </td>
              <td>
                <Link to={`/tasks/${task.id}/review`} aria-label={`Review task ${task.id}`}>
                  Review
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
