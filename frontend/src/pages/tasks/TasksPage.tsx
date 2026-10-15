import { useQuery } from '@tanstack/react-query';
import { useId } from 'react';
import { Link, useSearchParams } from 'react-router';
import { EmptyState, ErrorNotice, Loading } from '../../components/ErrorNotice';
import { PageHeader } from '../../components/PageHeader';
import { TaskTable } from '../../components/TaskTable';
import { useDocumentTitle } from '../../hooks/useDocumentTitle';
import { api } from '../../lib/api';
import { OVERVIEW_REFRESH_MS } from '../../lib/config';
import { humanize } from '../../lib/format';

export function TasksPage() {
  useDocumentTitle('Tasks');
  const id = useId();
  const [params, setParams] = useSearchParams();
  const state = params.get('state') ?? '';
  const repositoryId = params.get('repository_id') ?? '';
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity });
  const repos = useQuery({ queryKey: ['repositories'], queryFn: api.repositories.list });
  const tasks = useQuery({
    queryKey: ['tasks', { state, repositoryId }],
    queryFn: () =>
      api.tasks.list({
        state: state || undefined,
        repository_id: repositoryId ? Number(repositoryId) : undefined,
      }),
    refetchInterval: OVERVIEW_REFRESH_MS,
  });

  const setFilter = (key: string, value: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      return next;
    });

  return (
    <>
      <PageHeader
        title="Tasks"
        description="Maintenance tasks, newest first. Open a task to follow its execution."
        actions={
          <Link className="button primary" to="/tasks/new">
            New task
          </Link>
        }
      />
      <section className="panel">
        <form
          className="inline-form"
          aria-label="Filter tasks"
          onSubmit={(e) => e.preventDefault()}
        >
          <div className="field">
            <label htmlFor={`${id}-state`}>State</label>
            <select
              id={`${id}-state`}
              value={state}
              onChange={(e) => setFilter('state', e.target.value)}
            >
              <option value="">All states</option>
              {(meta.data?.states ?? []).map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-repo`}>Repository</label>
            <select
              id={`${id}-repo`}
              value={repositoryId}
              onChange={(e) => setFilter('repository_id', e.target.value)}
            >
              <option value="">All repositories</option>
              {(repos.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </div>
        </form>
        {tasks.isPending ? <Loading label="Loading tasks…" /> : null}
        <ErrorNotice error={tasks.error} />
        {tasks.data && tasks.data.length === 0 ? (
          <EmptyState>
            {state || repositoryId
              ? 'No tasks match these filters.'
              : 'No tasks have been created yet.'}
          </EmptyState>
        ) : null}
        {tasks.data && tasks.data.length > 0 ? (
          <TaskTable tasks={tasks.data} caption="Tasks" />
        ) : null}
      </section>
    </>
  );
}
