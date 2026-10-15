import { useMutation, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { Badge } from '../../components/Badge';
import { CodeView } from '../../components/CodeView';
import { EmptyState, ErrorNotice, Loading } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { shortSha } from '../../lib/format';
import type { ImpactResponse, SymbolInfo } from '../../lib/types';
import { fileHref, useExplorerParams } from './useExplorerParams';

function SymbolOutline({
  path,
  symbols,
  activeLine,
}: {
  path: string;
  symbols: SymbolInfo[];
  activeLine: number | null;
}) {
  const { href } = useExplorerParams();
  if (symbols.length === 0) return <p className="empty small">No symbols indexed for this file.</p>;
  return (
    <ul className="outline">
      {symbols.map((s) => {
        const depth = s.qualified_name.split('.').length - 1;
        const active = activeLine === s.start_line;
        return (
          <li
            key={`${s.qualified_name}-${s.start_line}`}
            style={{ paddingInlineStart: `${depth}rem` }}
          >
            <Link
              to={fileHref(href, path, s.start_line, s.end_line)}
              className={active ? 'selected' : undefined}
              aria-current={active ? 'true' : undefined}
              title={s.signature ?? s.qualified_name}
            >
              <span className="badge badge-small">{s.kind}</span> {s.name}
              <span className="muted small">
                {' '}
                L{s.start_line}–{s.end_line}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function ImpactResult({ impact }: { impact: ImpactResponse }) {
  const { href } = useExplorerParams();
  return (
    <div className="impact">
      <h4>Dependents (import graph, up to 2 levels)</h4>
      {impact.dependents.length === 0 ? (
        <p className="empty small">No other indexed files import this file.</p>
      ) : (
        <ul>
          {impact.dependents.map((d) => (
            <li key={d.path}>
              <Link to={fileHref(href, d.path)}>{d.path}</Link>{' '}
              <span className="muted small">distance {d.distance}</span>{' '}
              {d.is_test ? <span className="badge tone-info badge-small">test</span> : null}
            </li>
          ))}
        </ul>
      )}
      <h4>Tests likely affected</h4>
      {impact.tests.length === 0 ? (
        <p className="empty small">No tests found in the dependency set.</p>
      ) : (
        <ul>
          {impact.tests.map((t) => (
            <li key={t}>
              <Link to={fileHref(href, t)}>{t}</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FileViewer({
  repoId,
  gitRef,
  path,
  line,
  end,
}: {
  repoId: number;
  gitRef: string;
  path: string;
  line: number | null;
  end: number | null;
}) {
  const file = useQuery({
    queryKey: ['file', repoId, gitRef, path],
    queryFn: () => api.repositories.file(repoId, path, gitRef),
  });
  const impact = useMutation({
    mutationKey: ['impact', repoId, gitRef, path],
    mutationFn: () => api.repositories.impact(repoId, { paths: [path], ref: gitRef }),
  });

  if (file.isPending) return <Loading label={`Loading ${path}…`} />;
  if (file.isError) return <ErrorNotice error={file.error} />;
  const f = file.data;

  return (
    <article className="file-viewer" aria-labelledby="file-heading">
      <header className="file-header">
        <h3 id="file-heading">
          <code>{f.path}</code>
        </h3>
        <div className="badges">
          {f.language ? <Badge>{f.language}</Badge> : null}
          {f.is_test ? <Badge tone="info">test</Badge> : null}
          {f.is_config ? <Badge tone="attention">config</Badge> : null}
          {f.module ? <span className="muted small">module {f.module}</span> : null}
          <span className="muted small">
            at <code title={f.commit_sha}>{shortSha(f.commit_sha)}</code>
          </span>
        </div>
      </header>
      <div className="file-columns">
        <div className="file-code">
          {f.binary_or_large || f.content === null ? (
            <EmptyState>This file is binary or too large to display.</EmptyState>
          ) : (
            <CodeView
              content={f.content}
              label={`Contents of ${f.path}`}
              highlight={line ? { start: line, end: end ?? line } : null}
            />
          )}
        </div>
        <aside className="file-aside">
          <nav aria-label="Symbol outline">
            <h4>Symbol outline</h4>
            <SymbolOutline path={f.path} symbols={f.symbols} activeLine={line} />
          </nav>
          {f.imports.length > 0 ? (
            <details>
              <summary>Imports ({f.imports.length})</summary>
              <ul className="small">
                {f.imports.map((imp, i) => (
                  <li key={i}>
                    <code>
                      {imp.level ? '.'.repeat(imp.level) : ''}
                      {imp.module}
                      {imp.name ? ` → ${imp.name}` : ''}
                      {imp.alias ? ` as ${imp.alias}` : ''}
                    </code>{' '}
                    <span className="muted">L{imp.line}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <div className="impact-box">
            <button type="button" onClick={() => impact.mutate()} disabled={impact.isPending}>
              {impact.isPending ? 'Analysing…' : 'Analyse impact of changing this file'}
            </button>
            <ErrorNotice error={impact.error} />
            {impact.data ? <ImpactResult impact={impact.data} /> : null}
          </div>
        </aside>
      </div>
    </article>
  );
}
