import type { ReactNode } from 'react';
import { humanize } from '../lib/format';
import { stateTone, type Tone } from '../lib/states';

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge tone-${tone}`}>{children}</span>;
}

export function StateBadge({ state }: { state: string }) {
  return (
    <span className={`badge tone-${stateTone(state)}`} data-state={state}>
      {humanize(state)}
    </span>
  );
}

/** Pass/fail is never colour alone: icon and word travel with the tone. */
export function PassFail({ passed, label }: { passed: boolean | null; label?: string }) {
  if (passed === null) return <Badge tone="neutral">{label ?? 'not run'}</Badge>;
  return (
    <Badge tone={passed ? 'success' : 'danger'}>
      <span aria-hidden="true">{passed ? '✓' : '✗'}</span> {label ?? (passed ? 'passed' : 'failed')}
    </Badge>
  );
}
