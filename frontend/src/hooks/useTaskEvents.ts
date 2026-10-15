import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import type { TaskEvent } from '../lib/types';

/** GET /events returns at most this many rows per request (the backend default limit). */
const PAGE_SIZE = 500;

export interface TaskEventStream {
  events: TaskEvent[];
  error: unknown;
  /** True while the stream keeps polling (task not in a terminal state). */
  live: boolean;
  lastFetchedAt: Date | null;
}

/**
 * Incrementally follow a task's event log with GET /api/tasks/{id}/events?after_id=N.
 *
 * While `active` is true it polls every `intervalMs`. When `active` turns false (the task reached a
 * terminal state) it fetches once more to pick up the final events and then stops; turning `active`
 * back on (e.g. after a restart) resumes from the last event seen.
 */
export function useTaskEvents(
  taskId: number,
  active: boolean,
  intervalMs: number,
  enabled = true,
): TaskEventStream {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);
  const lastId = useRef(0);

  // The monitor route is reused when navigating between tasks: start over for a different task.
  useEffect(() => {
    lastId.current = 0;
    setEvents([]);
    setError(null);
    setLastFetchedAt(null);
  }, [taskId]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const tick = async () => {
      try {
        let batch: TaskEvent[];
        do {
          batch = await api.tasks.events(taskId, lastId.current, controller.signal);
          if (cancelled) return;
          const fresh = batch.filter((e) => e.id > lastId.current);
          if (fresh.length) {
            lastId.current = fresh[fresh.length - 1]!.id;
            setEvents((prev) => [...prev, ...fresh]);
          }
        } while (batch.length >= PAGE_SIZE);
        setError(null);
        setLastFetchedAt(new Date());
      } catch (err) {
        if (cancelled) return;
        setError(err);
      }
      if (!cancelled && active) timer = setTimeout(() => void tick(), intervalMs);
    };

    void tick();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [taskId, active, intervalMs, enabled]);

  return { events, error, live: enabled && active, lastFetchedAt };
}
