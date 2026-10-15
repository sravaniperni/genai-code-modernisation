import type { ReactNode } from 'react';

export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="stat-tile">
      <dt>{label}</dt>
      <dd>
        <span className="stat-value">{value}</span>
        {hint ? <span className="stat-hint">{hint}</span> : null}
      </dd>
    </div>
  );
}

export function StatGrid({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <dl className="stat-grid" aria-label={label}>
      {children}
    </dl>
  );
}
