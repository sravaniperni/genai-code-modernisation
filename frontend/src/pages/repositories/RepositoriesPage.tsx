import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { Badge } from '../../components/Badge';
import { EmptyState, ErrorNotice, Loading } from '../../components/ErrorNotice';
import { PageHeader } from '../../components/PageHeader';
import { useDocumentTitle } from '../../hooks/useDocumentTitle';
import { api } from '../../lib/api';
import { RegisterRepositoryForm } from './RegisterRepositoryForm';
import { RepositoryDetail } from './RepositoryDetail';

export function RepositoriesPage() {
  useDocumentTitle('Repositories');
  const params = useParams();
  const selectedId = params.repoId ? Number(params.repoId) : null;
  const repos = useQuery({ queryKey: ['repositories'], queryFn: api.repositories.list });

  return (
    <>
      <PageHeader
        title="Repository explorer"
        description="Register repositories, index them, browse files and symbols, and search code."
      />
      <div className="explorer-layout">
        <aside className="explorer-sidebar">
          <section className="panel" aria-labelledby="repo-list-heading">
            <h2 id="repo-list-heading">Repositories</h2>
            {repos.isPending ? <Loading /> : null}
            <ErrorNotice error={repos.error} />
            {repos.data && repos.data.length === 0 ? (
              <EmptyState>No repositories registered yet.</EmptyState>
            ) : null}
            {repos.data && repos.data.length > 0 ? (
              <ul className="repo-list">
                {repos.data.map((repo) => (
                  <li key={repo.id}>
                    <Link
                      to={`/repositories/${repo.id}`}
                      aria-current={repo.id === selectedId ? 'page' : undefined}
                      className={repo.id === selectedId ? 'active' : undefined}
                    >
                      <span className="repo-name">{repo.name}</span>
                      <span className="repo-meta">
                        <Badge>{repo.source_kind}</Badge>{' '}
                        {repo.latest_snapshot ? (
                          <Badge
                            tone={repo.latest_snapshot.status === 'ready' ? 'success' : 'attention'}
                          >
                            index {repo.latest_snapshot.status}
                          </Badge>
                        ) : (
                          <Badge tone="attention">not indexed</Badge>
                        )}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
          <section className="panel">
            <RegisterRepositoryForm />
          </section>
        </aside>
        <div className="explorer-main">
          {selectedId !== null && Number.isFinite(selectedId) ? (
            <RepositoryDetail key={selectedId} repoId={selectedId} />
          ) : (
            <section className="panel">
              <EmptyState>Select a repository to explore it, or register a new one.</EmptyState>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
