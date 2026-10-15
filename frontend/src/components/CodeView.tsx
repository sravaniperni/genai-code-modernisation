import { useEffect, useMemo, useRef } from 'react';

interface CodeViewProps {
  content: string;
  label: string;
  /** Lines to highlight and scroll to (1-based, inclusive). */
  highlight?: { start: number; end: number } | null;
}

export function CodeView({ content, label, highlight }: CodeViewProps) {
  const lines = useMemo(() => {
    const split = content.split('\n');
    if (split.length > 1 && split[split.length - 1] === '') split.pop();
    return split;
  }, [content]);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const start = highlight?.start ?? null;

  useEffect(() => {
    if (start === null) return;
    const row = containerRef.current?.querySelector(`[data-line="${start}"]`);
    row?.scrollIntoView({ block: 'center' });
  }, [start, content]);

  return (
    <div className="code-view" ref={containerRef} tabIndex={0} role="region" aria-label={label}>
      <table>
        <tbody>
          {lines.map((text, i) => {
            const n = i + 1;
            const on = highlight ? n >= highlight.start && n <= highlight.end : false;
            return (
              <tr key={n} id={`L${n}`} data-line={n} className={on ? 'highlight' : undefined}>
                <td className="ln">{n}</td>
                <td className="code">{text}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
