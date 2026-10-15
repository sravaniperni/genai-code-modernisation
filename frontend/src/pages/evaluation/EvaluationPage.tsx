import { useQuery } from '@tanstack/react-query';
import { useId, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Badge } from '../../components/Badge';
import { BarChart } from '../../components/BarChart';
import { EmptyState, ErrorNotice, Loading } from '../../components/ErrorNotice';
import { JsonDetails, KeyValueList } from '../../components/KeyValue';
import { PageHeader } from '../../components/PageHeader';
import { StatGrid, StatTile } from '../../components/StatTile';
import { useDocumentTitle } from '../../hooks/useDocumentTitle';
import { api } from '../../lib/api';
import {
  formatCost,
  formatDateTime,
  formatDurationMs,
  formatInt,
  formatPercent,
  formatSeconds,
  humanize,
} from '../../lib/format';
import type { EvaluationMetrics, EvaluationRunSummary } from '../../lib/types';

export const NO_RESULTS_TEXT = 'No evaluation results available.';

const METRIC_ROWS: [label: string, value: (m: EvaluationMetrics) => string][] = [
  ['Completion rate', (m) => formatPercent(m.completion_rate)],
  ['Tasks evaluated', (m) => formatInt(m.evaluated)],
  ['Successful', (m) => formatInt(m.successful)],
  ['Failed', (m) => formatInt(m.failed)],
  ['Timeouts', (m) => formatInt(m.timeouts)],
  ['Errors', (m) => formatInt(m.errors)],
  ['Latency p50', (m) => formatSeconds(m.latency_s.p50)],
  ['Latency p90', (m) => formatSeconds(m.latency_s.p90)],
  ['Latency mean', (m) => formatSeconds(m.latency_s.mean)],
  ['Latency max', (m) => formatSeconds(m.latency_s.max)],
  ['Model calls', (m) => formatInt(m.model_calls)],
  ['Failed model requests', (m) => formatInt(m.failed_model_requests)],
  ['Model inference time', (m) => formatSeconds(m.model_inference_seconds)],
  ['Prompt tokens', (m) => formatInt(m.prompt_tokens)],
  ['Completion tokens', (m) => formatInt(m.completion_tokens)],
  ['Inference cost', (m) => formatCost(m.inference_cost_usd)],
  ['Cost per accepted patch', (m) => formatCost(m.cost_per_accepted_patch_usd)],
];

function runLabel(run: EvaluationRunSummary['run']): string {
  return `#${run.id} ${run.mode} · ${run.run_key}`;
}

function RunDetail({ runId }: { runId: number }) {
  const id = useId();
  const [outcome, setOutcome] = useState('all');
  const detail = useQuery({
    queryKey: ['evaluation', 'run', runId],
    queryFn: () => api.evaluation.run(runId),
  });
  if (detail.isPending) return <Loading label="Loading run…" />;
  if (detail.isError) return <ErrorNotice error={detail.error} />;
  const { run, metrics, results } = detail.data;
  const rows = results ?? [];
  const outcomes = Array.from(new Set(rows.map((r) => r.outcome))).sort();
  const shown = outcome === 'all' ? rows : rows.filter((r) => r.outcome === outcome);
  const categories = Object.keys(metrics.by_category);
  const failureCats = Object.keys(metrics.failure_categories);

  return (
    <section className="panel" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>
        Run #{run.id}: {run.run_key}
      </h2>
      <KeyValueList
        className="kv-compact kv-columns"
        items={[
          ['Mode', <Badge key="m">{run.mode}</Badge>],
          ['Status', run.status],
          ['Task set', `${run.taskset_version ?? '—'}${run.split ? ` (${run.split})` : ''}`],
          ['Model', `${run.model_provider ?? '—'} / ${run.model_name ?? '—'}`],
          ['Started', formatDateTime(run.started_at)],
          ['Finished', formatDateTime(run.finished_at)],
        ]}
      />
      <JsonDetails label="Run configuration" value={run.config} />

      <StatGrid label="Run metrics">
        <StatTile
          label="Completion rate"
          value={formatPercent(metrics.completion_rate)}
          hint={`${formatInt(metrics.successful)} of ${formatInt(metrics.evaluated)} tasks`}
        />
        <StatTile label="Latency p50" value={formatSeconds(metrics.latency_s.p50)} />
        <StatTile label="Latency p90" value={formatSeconds(metrics.latency_s.p90)} />
        <StatTile
          label="Tokens"
          value={formatInt(metrics.prompt_tokens + metrics.completion_tokens)}
          hint={`${formatInt(metrics.prompt_tokens)} prompt / ${formatInt(metrics.completion_tokens)} completion`}
        />
        <StatTile label="Inference cost" value={formatCost(metrics.inference_cost_usd)} />
        <StatTile
          label="Cost per accepted patch"
          value={formatCost(metrics.cost_per_accepted_patch_usd)}
        />
      </StatGrid>

      <div className="grid-2">
        <div>
          <h3>By category</h3>
          {categories.length === 0 ? (
            <EmptyState>No per-category results.</EmptyState>
          ) : (
            <>
              <BarChart
                title="Completion rate by category"
                categories={categories}
                series={[
                  {
                    name: 'Completion rate',
                    values: categories.map((c) => metrics.by_category[c]?.rate ?? null),
                  },
                ]}
                max={1}
                format={(v) => formatPercent(v, 0)}
                formatCategory={humanize}
              />
              <table className="data-table compact">
                <caption className="visually-hidden">Results by category</caption>
                <thead>
                  <tr>
                    <th scope="col">Category</th>
                    <th scope="col" className="num">
                      Succeeded
                    </th>
                    <th scope="col" className="num">
                      Total
                    </th>
                    <th scope="col" className="num">
                      Rate
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map((c) => (
                    <tr key={c}>
                      <td>{humanize(c)}</td>
                      <td className="num">{metrics.by_category[c]?.success}</td>
                      <td className="num">{metrics.by_category[c]?.total}</td>
                      <td className="num">{formatPercent(metrics.by_category[c]?.rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
        <div>
          <h3>Failure categories</h3>
          {failureCats.length === 0 ? (
            <EmptyState>No failures were categorised in this run.</EmptyState>
          ) : (
            <BarChart
              title="Unsuccessful tasks by failure category"
              categories={failureCats}
              series={[
                {
                  name: 'Tasks',
                  values: failureCats.map((c) => metrics.failure_categories[c] ?? 0),
                },
              ]}
              format={formatInt}
              formatCategory={humanize}
            />
          )}
          <h3>Latency and usage</h3>
          <KeyValueList
            className="kv-compact"
            items={METRIC_ROWS.filter(([label]) =>
              [
                'Latency mean',
                'Latency max',
                'Model calls',
                'Failed model requests',
                'Model inference time',
                'Timeouts',
                'Errors',
              ].includes(label),
            ).map(([label, value]) => [label, value(metrics)])}
          />
        </div>
      </div>

      <h3>Per-task results</h3>
      {rows.length === 0 ? (
        <EmptyState>This run has no recorded task results.</EmptyState>
      ) : (
        <>
          <div className="field inline-field">
            <label htmlFor={`${id}-outcome`}>Outcome</label>
            <select
              id={`${id}-outcome`}
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
            >
              <option value="all">All ({rows.length})</option>
              {outcomes.map((o) => (
                <option key={o} value={o}>
                  {o} ({rows.filter((r) => r.outcome === o).length})
                </option>
              ))}
            </select>
          </div>
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Per-task results of run {run.id}</caption>
              <thead>
                <tr>
                  <th scope="col">Benchmark task</th>
                  <th scope="col">Repository</th>
                  <th scope="col">Category</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Failure category</th>
                  <th scope="col" className="num">
                    Attempts
                  </th>
                  <th scope="col" className="num">
                    Duration
                  </th>
                  <th scope="col" className="num">
                    Model calls
                  </th>
                  <th scope="col" className="num">
                    Tokens
                  </th>
                  <th scope="col">Task</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.benchmark_task_id}>
                    <td>
                      <code>{r.benchmark_task_id}</code>
                    </td>
                    <td>{r.repo}</td>
                    <td>{humanize(r.category)}</td>
                    <td>
                      <Badge tone={r.outcome === 'success' ? 'success' : 'danger'}>
                        <span aria-hidden="true">{r.outcome === 'success' ? '✓' : '✗'}</span>{' '}
                        {r.outcome}
                      </Badge>
                    </td>
                    <td>{r.failure_category ? humanize(r.failure_category) : '—'}</td>
                    <td className="num">{r.attempts}</td>
                    <td className="num">{formatDurationMs(r.duration_ms)}</td>
                    <td className="num">{formatInt(r.model_calls)}</td>
                    <td className="num">{formatInt(r.prompt_tokens + r.completion_tokens)}</td>
                    <td>
                      {r.task_id ? <Link to={`/tasks/${r.task_id}`}>#{r.task_id}</Link> : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function Comparison({ aId, bId }: { aId: number; bId: number }) {
  const a = useQuery({
    queryKey: ['evaluation', 'run', aId],
    queryFn: () => api.evaluation.run(aId),
  });
  const b = useQuery({
    queryKey: ['evaluation', 'run', bId],
    queryFn: () => api.evaluation.run(bId),
  });
  if (a.isPending || b.isPending) return <Loading label="Loading runs…" />;
  if (a.isError) return <ErrorNotice error={a.error} />;
  if (b.isError) return <ErrorNotice error={b.error} />;
  const left = a.data;
  const right = b.data;
  const nameA = `#${left.run.id} (${left.run.mode})`;
  const nameB = `#${right.run.id} (${right.run.mode})`;
  const categories = Array.from(
    new Set([...Object.keys(left.metrics.by_category), ...Object.keys(right.metrics.by_category)]),
  ).sort();

  return (
    <div className="comparison">
      <div className="table-scroll">
        <table className="data-table">
          <caption>Side-by-side metrics</caption>
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col" className="num">
                {nameA}
              </th>
              <th scope="col" className="num">
                {nameB}
              </th>
            </tr>
          </thead>
          <tbody>
            {METRIC_ROWS.map(([label, value]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                <td className="num">{value(left.metrics)}</td>
                <td className="num">{value(right.metrics)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {categories.length > 0 ? (
        <BarChart
          title="Completion rate by category"
          categories={categories}
          series={[
            {
              name: nameA,
              values: categories.map((c) => left.metrics.by_category[c]?.rate ?? null),
            },
            {
              name: nameB,
              values: categories.map((c) => right.metrics.by_category[c]?.rate ?? null),
            },
          ]}
          max={1}
          format={(v) => formatPercent(v, 0)}
          formatCategory={humanize}
        />
      ) : null}
    </div>
  );
}

export function EvaluationPage() {
  useDocumentTitle('Evaluation');
  const id = useId();
  const [params, setParams] = useSearchParams();
  const runs = useQuery({ queryKey: ['evaluation', 'runs'], queryFn: api.evaluation.runs });

  const header = (
    <PageHeader
      title="Evaluation"
      description="Benchmark runs recorded by the evaluation harness. Every figure comes from stored per-task results."
    />
  );
  if (runs.isPending) {
    return (
      <>
        {header}
        <Loading label="Loading evaluation runs…" />
      </>
    );
  }
  if (runs.isError) {
    return (
      <>
        {header}
        <ErrorNotice error={runs.error} />
      </>
    );
  }
  if (runs.data.length === 0) {
    return (
      <>
        {header}
        <section className="panel">
          <p className="empty">{NO_RESULTS_TEXT}</p>
        </section>
      </>
    );
  }

  const list = runs.data;
  const ids = list.map((r) => r.run.id);
  const pick = (key: string, fallback: number): number => {
    const v = Number(params.get(key));
    return ids.includes(v) ? v : fallback;
  };
  const selected = pick('run', list[0]!.run.id);
  const latestPlatform = list.find((r) => r.run.mode === 'platform')?.run.id;
  const latestBaseline = list.find((r) => r.run.mode === 'baseline')?.run.id;
  const defaultA = latestPlatform ?? list[0]!.run.id;
  const defaultB = latestBaseline ?? list.find((r) => r.run.id !== defaultA)?.run.id ?? defaultA;
  const compareA = pick('a', defaultA);
  const compareB = pick('b', defaultB);
  const setParam = (key: string, value: number) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set(key, String(value));
        return next;
      },
      { replace: true },
    );

  return (
    <>
      {header}
      <section className="panel" aria-labelledby={`${id}-runs`}>
        <h2 id={`${id}-runs`}>Runs</h2>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Evaluation runs, newest first</caption>
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Mode</th>
                <th scope="col">Model</th>
                <th scope="col">Task set</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">
                  Evaluated
                </th>
                <th scope="col" className="num">
                  Completion rate
                </th>
                <th scope="col">Finished</th>
              </tr>
            </thead>
            <tbody>
              {list.map(({ run, metrics }) => (
                <tr key={run.id} className={run.id === selected ? 'selected-row' : undefined}>
                  <td>
                    <Link
                      to={`?${new URLSearchParams({ ...Object.fromEntries(params), run: String(run.id) }).toString()}`}
                      aria-current={run.id === selected ? 'true' : undefined}
                    >
                      #{run.id} {run.run_key}
                    </Link>
                  </td>
                  <td>
                    <Badge>{run.mode}</Badge>
                  </td>
                  <td>
                    {run.model_provider ?? '—'} / {run.model_name ?? '—'}
                  </td>
                  <td>
                    {run.taskset_version ?? '—'}
                    {run.split ? ` (${run.split})` : ''}
                  </td>
                  <td>{run.status}</td>
                  <td className="num">{formatInt(metrics.evaluated)}</td>
                  <td className="num">{formatPercent(metrics.completion_rate)}</td>
                  <td>{formatDateTime(run.finished_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {list.length >= 2 ? (
        <section className="panel" aria-labelledby={`${id}-compare`}>
          <h2 id={`${id}-compare`}>Compare runs</h2>
          <p className="hint">
            Defaults to the latest platform run against the latest baseline (single-shot) run.
          </p>
          <div className="inline-form">
            <div className="field">
              <label htmlFor={`${id}-a`}>Run A</label>
              <select
                id={`${id}-a`}
                value={compareA}
                onChange={(e) => setParam('a', Number(e.target.value))}
              >
                {list.map(({ run }) => (
                  <option key={run.id} value={run.id}>
                    {runLabel(run)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor={`${id}-b`}>Run B</label>
              <select
                id={`${id}-b`}
                value={compareB}
                onChange={(e) => setParam('b', Number(e.target.value))}
              >
                {list.map(({ run }) => (
                  <option key={run.id} value={run.id}>
                    {runLabel(run)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {compareA === compareB ? (
            <p className="notice notice-info">Select two different runs to compare.</p>
          ) : (
            <Comparison aId={compareA} bId={compareB} />
          )}
        </section>
      ) : null}

      <RunDetail key={selected} runId={selected} />
    </>
  );
}
