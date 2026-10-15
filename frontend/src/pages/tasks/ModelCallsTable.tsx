import { Badge } from '../../components/Badge';
import { formatCost, formatDurationMs, formatInt, formatTime } from '../../lib/format';
import type { ModelCall } from '../../lib/types';

export function ModelCallsTable({ calls }: { calls: ModelCall[] }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">Model calls made for this task</caption>
        <thead>
          <tr>
            <th scope="col" className="num">
              #
            </th>
            <th scope="col">Time</th>
            <th scope="col">Purpose</th>
            <th scope="col">Model</th>
            <th scope="col">Status</th>
            <th scope="col" className="num">
              Retry
            </th>
            <th scope="col" className="num">
              Prompt tokens
            </th>
            <th scope="col" className="num">
              Completion tokens
            </th>
            <th scope="col" className="num">
              Latency
            </th>
            <th scope="col" className="num">
              Cost
            </th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => (
            <tr key={c.id}>
              <td className="num">{c.id}</td>
              <td>{formatTime(c.created_at)}</td>
              <td>{c.purpose}</td>
              <td>
                {c.provider} / <code>{c.model}</code>
              </td>
              <td>
                <Badge tone={c.status === 'ok' ? 'success' : 'danger'}>
                  <span aria-hidden="true">{c.status === 'ok' ? '✓' : '✗'}</span> {c.status}
                </Badge>
                {c.error ? <div className="cell-note">{c.error}</div> : null}
              </td>
              <td className="num">{c.retry_index}</td>
              <td className="num">{formatInt(c.prompt_tokens)}</td>
              <td className="num">{formatInt(c.completion_tokens)}</td>
              <td className="num">{formatDurationMs(c.latency_ms)}</td>
              <td className="num">{formatCost(c.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
