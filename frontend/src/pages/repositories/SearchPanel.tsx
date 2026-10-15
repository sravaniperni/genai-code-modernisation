import { useQuery } from '@tanstack/react-query';
import { useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { EmptyState, ErrorNotice, Loading } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { shortSha } from '../../lib/format';
import type { SearchHit, SearchMode } from '../../lib/types';
import { fileHref, useExplorerParams } from './useExplorerParams';

const MODE_HELP: Record<SearchMode, string> = {
  text: 'Case-insensitive substring match on each line.',
  regex: 'Python regular expression matched against each line.',
  symbol: 'Definitions (functions, classes, methods) by name or qualified name.',
  references: 'Call sites and uses of a name; qualify with a dot, e.g. datetime.utcnow.',
};

function matchText(hit: SearchHit): string {
  if (hit.signature) return hit.signature;
  if (hit.text) return hit.text.trim();
  if (hit.expression) return hit.expression;
  return '';
}

export function SearchPanel({ repoId, gitRef }: { repoId: number; gitRef: string }) {
  const id = useId();
  const params = useExplorerParams();
  const [q, setQ] = useState(params.q);
  const [mode, setMode] = useState<SearchMode>(params.mode);

  const search = useQuery({
    queryKey: ['search', repoId, gitRef, params.mode, params.q],
    queryFn: () => api.repositories.search(repoId, params.q, params.mode, gitRef),
    enabled: params.q.length > 0,
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    params.update({ q: q.trim(), mode });
  };

  return (
    <div className="search-panel">
      <form onSubmit={onSubmit} className="inline-form" role="search" aria-label="Code search">
        <div className="field grow">
          <label htmlFor={`${id}-q`}>Query</label>
          <input
            id={`${id}-q`}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            spellCheck={false}
            maxLength={300}
          />
        </div>
        <div className="field">
          <label htmlFor={`${id}-mode`}>Mode</label>
          <select
            id={`${id}-mode`}
            value={mode}
            onChange={(e) => setMode(e.target.value as SearchMode)}
            aria-describedby={`${id}-mode-help`}
          >
            <option value="text">Text</option>
            <option value="regex">Regex</option>
            <option value="symbol">Symbol</option>
            <option value="references">References</option>
          </select>
        </div>
        <button type="submit" className="primary" disabled={!q.trim()}>
          Search
        </button>
      </form>
      <p id={`${id}-mode-help`} className="hint">
        {MODE_HELP[mode]}
      </p>

      {params.q && search.isPending ? <Loading label="Searching…" /> : null}
      <ErrorNotice error={search.error} />
      {search.data ? (
        <>
          <p className="muted small" role="status">
            {search.data.results.length} result{search.data.results.length === 1 ? '' : 's'} for{' '}
            <code>{params.q}</code> ({search.data.mode}) at{' '}
            <code>{shortSha(search.data.commit_sha)}</code>
          </p>
          {search.data.results.length === 0 ? (
            <EmptyState>No matches.</EmptyState>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">Search results</caption>
                <thead>
                  <tr>
                    <th scope="col">Location</th>
                    <th scope="col">Symbol</th>
                    <th scope="col">Match</th>
                    <th scope="col">Method</th>
                  </tr>
                </thead>
                <tbody>
                  {search.data.results.map((hit, i) => (
                    <tr key={`${hit.path}:${hit.start_line}:${i}`}>
                      <td>
                        <Link to={fileHref(params.href, hit.path, hit.start_line, hit.end_line)}>
                          {hit.path}:{hit.start_line}
                          {hit.end_line !== hit.start_line ? `–${hit.end_line}` : ''}
                        </Link>
                      </td>
                      <td>
                        {hit.kind ? <span className="badge badge-small">{hit.kind}</span> : null}{' '}
                        {hit.symbol ? <code>{hit.symbol}</code> : <span className="muted">—</span>}
                      </td>
                      <td>
                        <code className="match-text">{matchText(hit)}</code>
                      </td>
                      <td>{hit.retrieval_method}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
