/**
 * Task lifecycle facts mirrored from backend/src/modernisation/agents/states.py. GET /api/meta lists the
 * state names but not which ones are terminal or restartable, so those two sets are kept here.
 */
export const TERMINAL_STATES: ReadonlySet<string> = new Set([
  'COMPLETED',
  'FAILED',
  'CANCELLED',
  'ESCALATED',
]);

/** States POST /api/tasks/{id}/restart accepts. */
export const RESTARTABLE_STATES: ReadonlySet<string> = new Set([
  'FAILED',
  'CANCELLED',
  'ESCALATED',
]);

export function isTerminal(state: string): boolean {
  return TERMINAL_STATES.has(state);
}

/** POST /api/tasks/{id}/cancel accepts any non-terminal task. */
export function canCancel(state: string): boolean {
  return !TERMINAL_STATES.has(state);
}

export function canRestart(state: string): boolean {
  return RESTARTABLE_STATES.has(state);
}

export type Tone = 'neutral' | 'info' | 'progress' | 'attention' | 'success' | 'danger';

export function stateTone(state: string): Tone {
  switch (state) {
    case 'COMPLETED':
      return 'success';
    case 'FAILED':
    case 'ESCALATED':
      return 'danger';
    case 'CANCELLED':
      return 'neutral';
    case 'AWAITING_APPROVAL':
      return 'attention';
    case 'QUEUED':
      return 'info';
    default:
      return 'progress';
  }
}
