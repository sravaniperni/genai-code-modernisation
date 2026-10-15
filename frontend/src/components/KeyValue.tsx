import type { ReactNode } from 'react';

export type KeyValueItem = [label: string, value: ReactNode];

export function KeyValueList({ items, className }: { items: KeyValueItem[]; className?: string }) {
  return (
    <dl className={`kv ${className ?? ''}`}>
      {items.map(([label, value]) => (
        <div key={label} className="kv-row">
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function JsonDetails({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined) return null;
  return (
    <details className="json-details">
      <summary>{label}</summary>
      <pre className="code-block">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
