import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { Badge } from '../../components/Badge';
import { ErrorNotice, Loading } from '../../components/ErrorNotice';
import { KeyValueList } from '../../components/KeyValue';
import { api } from '../../lib/api';
import { formatDateTime, formatDurationMs, formatInt, shortSha } from '../../lib/format';
import type { Repository, Snapshot } from '../../lib/types';
import { CommitsPanel } from './CommitsPanel';
import { FileBrowser } from './FileBrowser';
import { FindingsPanel } from './FindingsPanel';
import { SearchPanel } from './SearchPanel';
import { SnapshotsPanel } from './SnapshotsPanel';
import { EXPLORER_TABS, useExplorerParams, type ExplorerTab } from './useExplorerParams';

const TAB_LABELS: Record<ExplorerTab, string> = {
  files: 'Files',
  search: 'Search',
  findings: 'Review findings',
  commits: 'Commits',
  snapshots: 'Index snapshots',
};

/** Tabs that read the code index; they wait until the repository has been indexed. */
const NEEDS_INDEX: ReadonlySet<ExplorerTab> = new Set(['files', 'search', 'findings']);

function SnapshotSummary({ snapshot }: { snapshot: Snapshot }) {
  const languages = Object.entries(snapshot.languages ?? {})
    .map(([lang, n]) => `${lang} (${n})`)
    .join(', ');
  return (
    <KeyValueList
      className="kv-compact"
      items={[
        [
          'Status',
          <Badge
            key="s"
            tone={
              snapshot.status === 'ready'
                ? 'success'
                : snapshot.status === 'failed'
                  ? 'danger'
                  : 'attention'
            }
          >
            {snapshot.status}
          </Badge>,
        ],
        [
          'Commit',
          <code key="c" title={snapshot.commit_sha}>
            {shortSha(snapshot.commit_sha)}
          </code>,
        ],
        ['Ref', snapshot.ref ?? '—'],
        ['Files', formatInt(snapshot.files_total)],
        ['Symbols', formatInt(snapshot.symbols_total)],
        [
          'Blobs parsed / reused',
          `${formatInt(snapshot.blobs_parsed)} / ${formatInt(snapshot.blobs_reused)}`,
        ],
        ['Languages', languages || '—'],
        ['Index time', formatDurationMs(snapshot.duration_ms)],
        ['Finished', formatDateTime(snapshot.finished_at)],
        ...(snapshot.error ? [['Error', snapshot.error] as [string, string]] : []),
      ]}
    />
  );
}

function IndexControls({ repo, selectedRef }: { repo: Repository; selectedRef: string }) {
  const id = useId();
  const queryClient = useQueryClient();
  const [ref, setRef] = useState(selectedRef);
  const index = useMutation({
    mutationFn: (r: string) => api.repositories.index(repo.id, r || undefined),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['repositories'] });
      void queryClient.invalidateQueries({ queryKey: ['repository', repo.id] });
      void queryClient.invalidateQueries({ queryKey: ['snapshots', repo.id] });
      void queryClient.invalidateQueries({ queryKey: ['tree', repo.id] });
    },
  });
  const refresh = useMutation({
    mutationFn: () => api.repositories.refresh(repo.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['branches', repo.id] });
      void queryClient.invalidateQueries({ queryKey: ['commits', repo.id] });
    },
  });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    index.mutate(ref.trim());
  };
  return (
    <div className="index-controls">
      <form onSubmit={onSubmit} className="inline-form">
        <div className="field">
          <label htmlFor={`${id}-ref`}>Ref to index</label>
          <input
            id={`${id}-ref`}
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            placeholder={repo.default_branch}
            spellCheck={false}
          />
        </div>
        <button type="submit" className="primary" disabled={index.isPending}>
          {index.isPending ? 'Indexing…' : 'Index now'}
        </button>
        <button type="button" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          {refresh.isPending ? 'Fetching…' : 'Fetch from source'}
        </button>
      </form>
      {index.isSuccess ? (
        <p className="notice notice-success" role="status">
          Indexed {formatInt(index.data.files_total)} files at{' '}
          <code>{shortSha(index.data.commit_sha)}</code> ({formatInt(index.data.blobs_parsed)}{' '}
          parsed, {formatInt(index.data.blobs_reused)} reused) in{' '}
          {formatDurationMs(index.data.duration_ms)}.
        </p>
      ) : null}
      {refresh.isSuccess ? (
        <p className="notice notice-success" role="status">
          Fetched from source: {Object.keys(refresh.data.branches).length} branch(es).
        </p>
      ) : null}
      <ErrorNotice error={index.error} title="Indexing failed" />
      <ErrorNotice error={refresh.error} title="Fetch failed" />
    </div>
  );
}

export function RepositoryDetail({ repoId }: { repoId: number }) {
  const params = useExplorerParams();
  const repo = useQuery({
    queryKey: ['repository', repoId],
    queryFn: () => api.repositories.get(repoId),
  });
  const branches = useQuery({
    queryKey: ['branches', repoId],
    queryFn: () => api.repositories.branches(repoId),
    enabled: repo.isSuccess,
  });

  if (repo.isPending) return <Loading label="Loading repository…" />;
  if (repo.isError) return <ErrorNotice error={repo.error} />;

  const r = repo.data;
  const ref = params.ref || r.default_branch;
  const snapshot = r.latest_snapshot;
  const indexed = snapshot?.status === 'ready';
  const branchNames = Object.keys(branches.data ?? {});

  return (
    <div className="repo-detail">
      <section className="panel" aria-labelledby="repo-heading">
        <div className="panel-header">
          <h2 id="repo-heading">{r.name}</h2>
          <div className="badges">
            <Badge>{r.source_kind}</Badge>
            {Object.entries(r.task_counts).map(([state, n]) => (
              <Badge key={state}>
                {n} {state.toLowerCase()}
              </Badge>
            ))}
          </div>
        </div>
        <KeyValueList
          className="kv-compact"
          items={[
            ['Source', <code key="s">{r.source}</code>],
            ['Default branch', r.default_branch],
            ['Registered', formatDateTime(r.created_at)],
            [
              'Tasks',
              <Link key="t" to={`/tasks?repository_id=${r.id}`}>
                View tasks
              </Link>,
            ],
            [
              'New task',
              <Link key="n" to={`/tasks/new?repository_id=${r.id}`}>
                Create a task for this repository
              </Link>,
            ],
          ]}
        />
        <h3>Index status</h3>
        {snapshot ? (
          <SnapshotSummary snapshot={snapshot} />
        ) : (
          <p className="notice notice-info">
            Not indexed yet. Index the repository to browse files, search and review findings.
          </p>
        )}
        <IndexControls repo={r} selectedRef={params.ref} />
      </section>

      <section className="panel" aria-label="Explore repository">
        <div className="toolbar">
          <nav aria-label="Repository views" className="tabs">
            {EXPLORER_TABS.map((t) => (
              <Link
                key={t}
                to={params.href({ tab: t })}
                aria-current={params.tab === t ? 'page' : undefined}
                className={params.tab === t ? 'tab active' : 'tab'}
              >
                {TAB_LABELS[t]}
              </Link>
            ))}
          </nav>
          <label className="inline-field">
            <span>Ref</span>
            <select
              value={ref}
              onChange={(e) =>
                params.update({
                  ref: e.target.value === r.default_branch ? null : e.target.value,
                  line: null,
                  end: null,
                })
              }
            >
              {(branchNames.includes(ref) ? branchNames : [ref, ...branchNames]).map((b) => (
                <option key={b} value={b}>
                  {b}
                  {b === r.default_branch ? ' (default)' : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
        {NEEDS_INDEX.has(params.tab) && !indexed ? (
          <p className="notice notice-info">
            {snapshot?.status === 'failed'
              ? 'The last index attempt failed. Re-run indexing above.'
              : 'This view reads the code index. Index the repository first (“Index now” above).'}
          </p>
        ) : (
          <>
            {params.tab === 'files' ? <FileBrowser repoId={r.id} gitRef={ref} /> : null}
            {params.tab === 'search' ? <SearchPanel repoId={r.id} gitRef={ref} /> : null}
            {params.tab === 'findings' ? <FindingsPanel repoId={r.id} gitRef={ref} /> : null}
            {params.tab === 'commits' ? <CommitsPanel repoId={r.id} gitRef={ref} /> : null}
            {params.tab === 'snapshots' ? <SnapshotsPanel repoId={r.id} /> : null}
          </>
        )}
      </section>
    </div>
  );
}
