import type { TaskEvent } from '../lib/types';
import { formatDateTime, humanize } from '../lib/format';
import { StateBadge } from './Badge';

/** Observed state transitions, derived from "state" events in the task's event log. */
export function StateTimeline({ events }: { events: TaskEvent[] }) {
  const transitions = events.filter((e) => e.kind === 'state' && e.state);
  if (transitions.length === 0) return <p className="empty">No state transitions recorded yet.</p>;
  return (
    <ol className="timeline" aria-label="State timeline">
      {transitions.map((e) => {
        const from = typeof e.payload?.from === 'string' ? e.payload.from : null;
        const reason = e.message.includes(': ')
          ? e.message.slice(e.message.indexOf(': ') + 2)
          : null;
        return (
          <li key={e.id}>
            <StateBadge state={e.state!} />
            <span className="timeline-meta">
              <time dateTime={e.ts}>{formatDateTime(e.ts)}</time>
              {from ? <span> from {humanize(from)}</span> : <span> {e.message}</span>}
              {from && reason ? <span className="timeline-reason">{reason}</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
