import { useQuery } from '@tanstack/react-query';
import { Badge } from '../../components/Badge';
import { EmptyState, ErrorNotice, Loading } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { formatDateTime, formatDurationMs, formatInt, shortSha } from '../../lib/format';

export function SnapshotsPanel({ repoId }: { repoId: number }) {
  const snapshots = useQuery({
    queryKey: ['snapshots', repoId],
    queryFn: () => api.repositories.snapshots(repoId),
  });
  if (snapshots.isPending) return <Loading label="Loading snapshots…" />;
  if (snapshots.isError) return <ErrorNotice error={snapshots.error} />;
  if (snapshots.data.length === 0) return <EmptyState>No index snapshots yet.</EmptyState>;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">Index snapshots, newest first</caption>
        <thead>
          <tr>
            <th scope="col">ID</th>
            <th scope="col">Commit</th>
            <th scope="col">Ref</th>
            <th scope="col">Status</th>
            <th scope="col" className="num">
              Files
            </th>
            <th scope="col" className="num">
              Parsed / reused
            </th>
            <th scope="col" className="num">
              Symbols
            </th>
            <th scope="col">Duration</th>
            <th scope="col">Finished</th>
          </tr>
        </thead>
        <tbody>
          {snapshots.data.map((s) => (
            <tr key={s.id}>
              <td className="num">{s.id}</td>
              <td>
                <code title={s.commit_sha}>{shortSha(s.commit_sha)}</code>
              </td>
              <td>{s.ref ?? '—'}</td>
              <td>
                <Badge
                  tone={
                    s.status === 'ready'
                      ? 'success'
                      : s.status === 'failed'
                        ? 'danger'
                        : 'attention'
                  }
                >
                  {s.status}
                </Badge>
                {s.error ? <div className="cell-note">{s.error}</div> : null}
              </td>
              <td className="num">{formatInt(s.files_total)}</td>
              <td className="num">
                {formatInt(s.blobs_parsed)} / {formatInt(s.blobs_reused)}
              </td>
              <td className="num">{formatInt(s.symbols_total)}</td>
              <td>{formatDurationMs(s.duration_ms)}</td>
              <td>{formatDateTime(s.finished_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
