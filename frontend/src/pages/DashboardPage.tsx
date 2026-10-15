import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { BarChart } from '../components/BarChart';
import { EmptyState, ErrorNotice, Loading } from '../components/ErrorNotice';
import { KeyValueList } from '../components/KeyValue';
import { PageHeader } from '../components/PageHeader';
import { StatGrid, StatTile } from '../components/StatTile';
import { TaskTable } from '../components/TaskTable';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { api } from '../lib/api';
import { OVERVIEW_REFRESH_MS } from '../lib/config';
import { formatInt, formatTime, humanize } from '../lib/format';
import { isTerminal } from '../lib/states';

export function DashboardPage() {
  useDocumentTitle('Dashboard');
  const dashboard = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard,
    refetchInterval: OVERVIEW_REFRESH_MS,
  });
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity });

  const header = (
    <PageHeader
      title="Dashboard"
      description={
        dashboard.dataUpdatedAt
          ? `Live figures from the platform database · updated ${formatTime(new Date(dashboard.dataUpdatedAt).toISOString())}`
          : 'Live figures from the platform database'
      }
      actions={
        <button
          type="button"
          onClick={() => void dashboard.refetch()}
          disabled={dashboard.isFetching}
        >
          {dashboard.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      }
    />
  );

  if (dashboard.isPending) {
    return (
      <>
        {header}
        <Loading label="Loading dashboard…" />
      </>
    );
  }
  if (dashboard.isError) {
    return (
      <>
        {header}
        <ErrorNotice error={dashboard.error} />
      </>
    );
  }

  const d = dashboard.data;
  const counts = Object.entries(d.tasks_by_state);
  const total = counts.reduce((sum, [, n]) => sum + n, 0);
  const active = counts.filter(([s]) => !isTerminal(s)).reduce((sum, [, n]) => sum + n, 0);
  const order = meta.data?.states ?? [];
  const states = [
    ...order.filter((s) => (d.tasks_by_state[s] ?? 0) > 0),
    ...counts.map(([s]) => s).filter((s) => !order.includes(s)),
  ];
  const usage = d.model_usage;

  return (
    <>
      {header}
      <StatGrid label="Summary">
        <StatTile label="Repositories" value={formatInt(d.repositories)} />
        <StatTile label="Tasks" value={formatInt(total)} />
        <StatTile
          label="Active tasks"
          value={formatInt(active)}
          hint="not yet in a terminal state"
        />
        <StatTile label="Completed" value={formatInt(d.completed)} />
        <StatTile label="Failed or escalated" value={formatInt(d.failed)} />
        <StatTile label="Model calls" value={formatInt(usage.calls)} />
      </StatGrid>

      <div className="grid-2">
        <section className="panel" aria-labelledby="by-state-heading">
          <h2 id="by-state-heading">Tasks by state</h2>
          {total === 0 ? (
            <EmptyState>
              No tasks have been created yet. <Link to="/tasks/new">Create a task</Link>.
            </EmptyState>
          ) : (
            <BarChart
              title="Number of tasks in each state"
              categories={states}
              series={[{ name: 'Tasks', values: states.map((s) => d.tasks_by_state[s] ?? 0) }]}
              format={formatInt}
              formatCategory={humanize}
            />
          )}
        </section>
        <section className="panel" aria-labelledby="usage-heading">
          <h2 id="usage-heading">Model usage</h2>
          {usage.calls === 0 ? <EmptyState>No model calls have been recorded.</EmptyState> : null}
          <KeyValueList
            items={[
              ['Model calls', formatInt(usage.calls)],
              ['Prompt tokens', formatInt(usage.prompt_tokens)],
              ['Completion tokens', formatInt(usage.completion_tokens)],
              ['Total tokens', formatInt(usage.prompt_tokens + usage.completion_tokens)],
            ]}
          />
        </section>
      </div>

      <section className="panel" aria-labelledby="active-heading">
        <h2 id="active-heading">Active tasks</h2>
        {d.active.length === 0 ? (
          <EmptyState>No active tasks.</EmptyState>
        ) : (
          <TaskTable tasks={d.active} caption="Active tasks" />
        )}
      </section>

      <section className="panel" aria-labelledby="recent-heading">
        <h2 id="recent-heading">Recent history</h2>
        {d.recent.length === 0 ? (
          <EmptyState>No tasks have finished yet.</EmptyState>
        ) : (
          <TaskTable tasks={d.recent} caption="Recently finished tasks" timeColumn="finished" />
        )}
      </section>
    </>
  );
}
