import { useMutation, useQuery } from '@tanstack/react-query';
import { useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { EmptyState, ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { humanize, shortSha } from '../../lib/format';
import type { RetrieveRequest } from '../../lib/types';
import { fileHref, useExplorerParams } from './useExplorerParams';

/**
 * "Review findings": ask the retrieval engine which code a maintenance request touches
 * (POST /api/repositories/{id}/retrieve), with the evidence behind each reference.
 */
export function FindingsPanel({ repoId, gitRef }: { repoId: number; gitRef: string }) {
  const id = useId();
  const { href } = useExplorerParams();
  const [request, setRequest] = useState('');
  const [category, setCategory] = useState('');
  const [limit, setLimit] = useState(20);
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity });
  const retrieve = useMutation({
    mutationFn: (body: RetrieveRequest) => api.repositories.retrieve(repoId, body),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    retrieve.mutate({
      request,
      ref: gitRef,
      limit,
      ...(category ? { category } : {}),
    });
  };

  return (
    <div className="findings-panel">
      <form onSubmit={onSubmit} className="form" noValidate>
        <div className="field">
          <label htmlFor={`${id}-request`}>Maintenance request</label>
          <textarea
            id={`${id}-request`}
            rows={4}
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            aria-describedby={`${id}-request-hint`}
          />
          <p id={`${id}-request-hint`} className="hint">
            Describe the bug, upgrade or migration. The platform lists the code it would read first.
          </p>
        </div>
        <div className="form-row">
          <div className="field">
            <label htmlFor={`${id}-category`}>Category</label>
            <select
              id={`${id}-category`}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="">Any</option>
              {(meta.data?.categories ?? []).map((c) => (
                <option key={c} value={c}>
                  {humanize(c)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-limit`}>Max references</label>
            <input
              id={`${id}-limit`}
              type="number"
              min={1}
              max={100}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            />
          </div>
        </div>
        <ErrorNotice error={retrieve.error} />
        <button type="submit" className="primary" disabled={retrieve.isPending}>
          {retrieve.isPending ? 'Retrieving…' : 'Find relevant code'}
        </button>
      </form>

      {retrieve.data ? (
        <section aria-labelledby={`${id}-results`} className="findings">
          <h3 id={`${id}-results`}>
            {retrieve.data.references.length} reference
            {retrieve.data.references.length === 1 ? '' : 's'} at{' '}
            <code>{shortSha(retrieve.data.commit_sha)}</code>
          </h3>
          {retrieve.data.references.length === 0 ? (
            <EmptyState>No code references were found for this request.</EmptyState>
          ) : (
            <ol className="finding-list">
              {retrieve.data.references.map((ref, i) => (
                <li key={`${ref.path}:${ref.start_line}:${i}`} className="finding">
                  <div className="finding-head">
                    <Link to={fileHref(href, ref.path, ref.start_line, ref.end_line)}>
                      <code>{ref.path}</code>
                    </Link>
                    <span className="muted">
                      lines {ref.start_line}–{ref.end_line}
                    </span>
                    {ref.is_test ? <span className="badge tone-info badge-small">test</span> : null}
                    {ref.is_config ? (
                      <span className="badge tone-attention badge-small">config</span>
                    ) : null}
                    <span className="muted small">score {ref.score.toFixed(1)}</span>
                  </div>
                  <div className="finding-body">
                    <span>
                      Symbol:{' '}
                      {ref.symbol ? (
                        <code>
                          {ref.symbol}
                          {ref.symbol_kind ? ` (${ref.symbol_kind})` : ''}
                        </code>
                      ) : (
                        <span className="muted">none</span>
                      )}
                    </span>
                    <span>
                      Retrieved by:{' '}
                      {(ref.methods.length ? ref.methods : [ref.retrieval_method]).map((m) => (
                        <span key={m} className="badge badge-small">
                          {humanize(m)}
                        </span>
                      ))}
                    </span>
                  </div>
                  {ref.reason ? <p className="finding-reason">{ref.reason}</p> : null}
                </li>
              ))}
            </ol>
          )}
        </section>
      ) : null}
    </div>
  );
}
