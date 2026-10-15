import { useMemo, useState } from 'react';
import type { TaskEventStream } from '../hooks/useTaskEvents';
import { POLL_INTERVAL_MS } from '../lib/config';
import { formatTime, humanize } from '../lib/format';
import { ErrorNotice } from './ErrorNotice';

const KIND_TONE: Record<string, string> = {
  state: 'info',
  error: 'danger',
  check: 'neutral',
  tool: 'neutral',
  model: 'progress',
  approval: 'attention',
  external: 'neutral',
  log: 'neutral',
};

/** The task's event log. New entries are announced politely to assistive technology. */
export function EventLog({ stream }: { stream: TaskEventStream }) {
  const { events, error, live, lastFetchedAt } = stream;
  const [kind, setKind] = useState('all');
  const kinds = useMemo(() => Array.from(new Set(events.map((e) => e.kind))).sort(), [events]);
  const shown = kind === 'all' ? events : events.filter((e) => e.kind === kind);

  return (
    <div className="event-log">
      <div className="toolbar">
        <p className="muted" role="status">
          {live ? (
            <>
              <span className="dot dot-live" aria-hidden="true" /> Live: polling every{' '}
              {POLL_INTERVAL_MS / 1000} s
            </>
          ) : (
            'Polling stopped: the task is in a terminal state.'
          )}
          {lastFetchedAt ? ` · last checked ${formatTime(lastFetchedAt.toISOString())}` : ''}
        </p>
        <label className="inline-field">
          <span>Show</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="all">All events ({events.length})</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {humanize(k)} ({events.filter((e) => e.kind === k).length})
              </option>
            ))}
          </select>
        </label>
      </div>
      <ErrorNotice error={error} title="Could not load events" />
      <ol
        className="log"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Event log"
      >
        {shown.length === 0 ? (
          <li className="log-empty">No events recorded{kind === 'all' ? '' : ' of this kind'}.</li>
        ) : (
          shown.map((event) => (
            <li key={event.id} className={`log-entry kind-${event.kind}`}>
              <time dateTime={event.ts} className="log-time">
                {formatTime(event.ts)}
              </time>
              <span className={`badge tone-${KIND_TONE[event.kind] ?? 'neutral'}`}>
                {event.kind}
              </span>
              {event.state ? <span className="log-state">{humanize(event.state)}</span> : null}
              <span className="log-message">{event.message}</span>
              {event.payload && Object.keys(event.payload).length > 0 ? (
                <details className="log-payload">
                  <summary>payload</summary>
                  <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                </details>
              ) : null}
            </li>
          ))
        )}
      </ol>
    </div>
  );
}
