import { useQuery } from '@tanstack/react-query';
import { EmptyState, ErrorNotice, Loading } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { formatDateTime, shortSha } from '../../lib/format';

export function CommitsPanel({ repoId, gitRef }: { repoId: number; gitRef: string }) {
  const commits = useQuery({
    queryKey: ['commits', repoId, gitRef],
    queryFn: () => api.repositories.commits(repoId, gitRef, 50),
  });
  if (commits.isPending) return <Loading label="Loading commits…" />;
  if (commits.isError) return <ErrorNotice error={commits.error} />;
  if (commits.data.length === 0) return <EmptyState>No commits on {gitRef}.</EmptyState>;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">Latest commits on {gitRef}</caption>
        <thead>
          <tr>
            <th scope="col">Commit</th>
            <th scope="col">Subject</th>
            <th scope="col">Author</th>
            <th scope="col">Date</th>
          </tr>
        </thead>
        <tbody>
          {commits.data.map((c) => (
            <tr key={c.sha}>
              <td>
                <code title={c.sha}>{shortSha(c.sha)}</code>
              </td>
              <td>{c.subject}</td>
              <td>{c.author}</td>
              <td>{formatDateTime(c.authored_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {commits.data.length === 50 ? (
        <p className="muted small">Showing the latest 50 commits.</p>
      ) : null}
    </div>
  );
}
