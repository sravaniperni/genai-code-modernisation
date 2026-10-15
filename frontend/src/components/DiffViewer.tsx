import { useMemo, useState } from 'react';
import {
  diffStats,
  displayPath,
  parseUnifiedDiff,
  toSplitRows,
  type DiffFile,
  type DiffLine,
} from '../lib/diff';
import { Badge } from './Badge';
import { EmptyState } from './ErrorNotice';

type Layout = 'unified' | 'split';

const STATUS_TONE = {
  added: 'success',
  deleted: 'danger',
  renamed: 'info',
  modified: 'neutral',
} as const;

function Marker({ line }: { line: DiffLine | null }) {
  if (!line || line.type === 'context' || line.type === 'note') return null;
  return (
    <>
      <span aria-hidden="true">{line.type === 'add' ? '+' : '−'}</span>
      <span className="visually-hidden">{line.type === 'add' ? 'added' : 'removed'}</span>
    </>
  );
}

function UnifiedRows({ file }: { file: DiffFile }) {
  return (
    <>
      {file.hunks.map((hunk, hi) => (
        <tbody key={hi}>
          <tr className="diff-hunk-header">
            <td colSpan={4}>{hunk.header}</td>
          </tr>
          {hunk.lines.map((line, li) =>
            line.type === 'note' ? (
              <tr key={li} className="diff-note">
                <td colSpan={4}>{line.content}</td>
              </tr>
            ) : (
              <tr key={li} className={`diff-line diff-${line.type}`}>
                <td className="ln">{line.oldNumber ?? ''}</td>
                <td className="ln">{line.newNumber ?? ''}</td>
                <td className="marker">
                  <Marker line={line} />
                </td>
                <td className="code">{line.content}</td>
              </tr>
            ),
          )}
        </tbody>
      ))}
    </>
  );
}

function SplitRows({ file }: { file: DiffFile }) {
  return (
    <>
      {file.hunks.map((hunk, hi) => (
        <tbody key={hi}>
          <tr className="diff-hunk-header">
            <td colSpan={4}>{hunk.header}</td>
          </tr>
          {toSplitRows(hunk).map((row, ri) =>
            row.kind === 'note' ? (
              <tr key={ri} className="diff-note">
                <td colSpan={4}>{row.left?.content}</td>
              </tr>
            ) : (
              <tr key={ri} className="diff-line">
                <td className="ln">{row.left?.oldNumber ?? ''}</td>
                <td className={`code side ${row.left ? `diff-${row.left.type}` : 'diff-empty'}`}>
                  {row.left && row.left.type === 'del' ? <Marker line={row.left} /> : null}
                  {row.left?.content ?? ''}
                </td>
                <td className="ln">{row.right?.newNumber ?? ''}</td>
                <td className={`code side ${row.right ? `diff-${row.right.type}` : 'diff-empty'}`}>
                  {row.right && row.right.type === 'add' ? <Marker line={row.right} /> : null}
                  {row.right?.content ?? ''}
                </td>
              </tr>
            ),
          )}
        </tbody>
      ))}
    </>
  );
}

function DiffFileView({ file, layout }: { file: DiffFile; layout: Layout }) {
  const path = displayPath(file);
  return (
    <section className="diff-file" aria-label={`Changes to ${path}`}>
      <header className="diff-file-header">
        <Badge tone={STATUS_TONE[file.status]}>{file.status}</Badge>
        <code className="diff-path">{path}</code>
        <span className="diff-counts">
          <span className="add-count">+{file.additions}</span>{' '}
          <span className="del-count">−{file.deletions}</span>
        </span>
      </header>
      {file.isBinary ? (
        <p className="muted pad">Binary file changed; no text diff.</p>
      ) : file.hunks.length === 0 ? (
        <p className="muted pad">No content changes (metadata only).</p>
      ) : (
        <div className="diff-scroll" tabIndex={0} role="region" aria-label={`Diff of ${path}`}>
          <table className={`diff-table diff-${layout}`}>
            <thead className="visually-hidden">
              {layout === 'unified' ? (
                <tr>
                  <th scope="col">Old line</th>
                  <th scope="col">New line</th>
                  <th scope="col">Change</th>
                  <th scope="col">Content</th>
                </tr>
              ) : (
                <tr>
                  <th scope="col">Old line</th>
                  <th scope="col">Before</th>
                  <th scope="col">New line</th>
                  <th scope="col">After</th>
                </tr>
              )}
            </thead>
            {layout === 'unified' ? <UnifiedRows file={file} /> : <SplitRows file={file} />}
          </table>
        </div>
      )}
    </section>
  );
}

/** Renders a unified diff as per-file tables, in unified or before/after (split) layout. */
export function DiffViewer({
  diff,
  emptyText = 'No diff recorded.',
}: {
  diff: string | null | undefined;
  emptyText?: string;
}) {
  const files = useMemo(() => parseUnifiedDiff(diff), [diff]);
  const [layout, setLayout] = useState<Layout>('unified');

  if (!diff || !diff.trim()) return <EmptyState>{emptyText}</EmptyState>;
  if (files.length === 0) {
    return (
      <div>
        <p className="muted">This diff could not be parsed; the raw text is shown.</p>
        <pre className="code-block">{diff}</pre>
      </div>
    );
  }
  const stats = diffStats(files);
  return (
    <div className="diff-viewer">
      <div className="toolbar">
        <p className="diff-summary">
          {stats.files} file{stats.files === 1 ? '' : 's'} changed,{' '}
          <span className="add-count">+{stats.additions}</span>{' '}
          <span className="del-count">−{stats.deletions}</span>
        </p>
        <div role="group" aria-label="Diff layout" className="segmented">
          <button
            type="button"
            aria-pressed={layout === 'unified'}
            onClick={() => setLayout('unified')}
          >
            Unified
          </button>
          <button
            type="button"
            aria-pressed={layout === 'split'}
            onClick={() => setLayout('split')}
          >
            Before / after
          </button>
        </div>
      </div>
      {files.map((file, i) => (
        <DiffFileView key={`${i}-${displayPath(file)}`} file={file} layout={layout} />
      ))}
    </div>
  );
}
