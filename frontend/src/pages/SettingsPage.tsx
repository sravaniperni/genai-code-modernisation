import { useMutation, useQuery } from '@tanstack/react-query';
import { useId, useState, useSyncExternalStore, type FormEvent } from 'react';
import { Badge } from '../components/Badge';
import { ErrorNotice, Loading } from '../components/ErrorNotice';
import { KeyValueList } from '../components/KeyValue';
import { PageHeader } from '../components/PageHeader';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { api } from '../lib/api';
import { formatCost, formatDurationMs, formatInt, yesNo } from '../lib/format';
import { getApiToken, setApiToken, subscribeToToken } from '../lib/token';

/** Unset prices mean costs are recorded as unknown, not as zero. */
function formatPrice(usd: number | null): string {
  return usd === null ? 'not configured (costs recorded as unknown)' : formatCost(usd);
}

function Configured({
  value,
  yes = 'configured',
  no = 'not configured',
}: {
  value: boolean;
  yes?: string;
  no?: string;
}) {
  return <Badge tone={value ? 'success' : 'neutral'}>{value ? yes : no}</Badge>;
}

function ApiTokenForm({ required }: { required: boolean | null }) {
  const id = useId();
  const stored = useSyncExternalStore(subscribeToToken, getApiToken, () => null);
  const [value, setValue] = useState(stored ?? '');
  const [message, setMessage] = useState<string | null>(null);

  const save = (e: FormEvent) => {
    e.preventDefault();
    const ok = setApiToken(value);
    setMessage(
      ok
        ? value.trim()
          ? 'Token saved in this browser. It is sent with every change request.'
          : 'Token removed.'
        : 'This browser does not allow local storage; the token could not be saved.',
    );
  };
  const clear = () => {
    const ok = setApiToken(null);
    setValue('');
    setMessage(ok ? 'Token removed.' : 'This browser does not allow local storage.');
  };

  return (
    <form onSubmit={save} className="form" aria-labelledby={`${id}-title`} id="api-token">
      <h2 id={`${id}-title`}>API token</h2>
      <p className="hint">
        {required === null
          ? 'Whether this backend requires a token is unknown (settings unavailable).'
          : required
            ? 'This backend requires a bearer token (MODERNISATION_API_TOKEN) for every change: registering, indexing, creating, cancelling, restarting, approving and testing the model.'
            : 'This backend does not require a token. A stored token is still sent with change requests.'}{' '}
        The token is kept only in this browser&apos;s local storage.
      </p>
      <div className="field">
        <label htmlFor={`${id}-token`}>Token</label>
        <input
          id={`${id}-token`}
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <p className="muted small">
        {stored ? 'A token is stored in this browser.' : 'No token stored.'}
      </p>
      <div className="button-row">
        <button type="submit" className="primary">
          Save token
        </button>
        <button type="button" onClick={clear} disabled={!stored && !value}>
          Clear token
        </button>
      </div>
      {message ? (
        <p className="notice notice-info" role="status">
          {message}
        </p>
      ) : null}
    </form>
  );
}

function ModelTest() {
  const test = useMutation({ mutationFn: api.settings.testModel });
  return (
    <div className="model-test">
      <button type="button" onClick={() => test.mutate()} disabled={test.isPending}>
        {test.isPending ? 'Testing…' : 'Test model connection'}
      </button>
      <ErrorNotice error={test.error} title={undefined} />
      {test.data ? (
        test.data.ok ? (
          <div className="notice notice-success" role="status">
            <p className="notice-title">Model endpoint answered</p>
            <KeyValueList
              className="kv-compact"
              items={[
                ['Provider', test.data.provider ?? '—'],
                ['Model', test.data.model ?? '—'],
                ['Reply', test.data.reply ?? '—'],
                ['Latency', formatDurationMs(test.data.latency_ms)],
                [
                  'Prompt / completion tokens',
                  `${formatInt(test.data.prompt_tokens)} / ${formatInt(test.data.completion_tokens)}`,
                ],
              ]}
            />
          </div>
        ) : (
          <div className="notice notice-error" role="alert">
            <p className="notice-title">Model request failed</p>
            <p>{test.data.error}</p>
            <p className="small">after {formatDurationMs(test.data.latency_ms)}</p>
          </div>
        )
      ) : null}
    </div>
  );
}

export function SettingsPage() {
  useDocumentTitle('Settings');
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings.get });
  const health = useQuery({ queryKey: ['health'], queryFn: api.health });
  const s = settings.data;

  return (
    <>
      <PageHeader
        title="Settings"
        description="Read-only view of the backend configuration (MODERNISATION_* environment variables). Secrets are never returned by the API."
      />
      {settings.isPending ? <Loading label="Loading settings…" /> : null}
      <ErrorNotice error={settings.error} />
      {s ? (
        <div className="grid-2">
          <section className="panel" aria-labelledby="model-heading">
            <h2 id="model-heading">Model endpoint</h2>
            <KeyValueList
              items={[
                [
                  'Provider',
                  s.model.provider === 'none' ? (
                    <Configured key="p" value={false} />
                  ) : (
                    s.model.provider
                  ),
                ],
                ['Base URL', s.model.base_url ?? '—'],
                ['Model', s.model.name ?? '—'],
                ['API key', <Configured key="k" value={s.model.api_key_configured} />],
                ['Timeout', `${s.model.timeout_s} s`],
                ['Max retries', String(s.model.max_retries)],
                ['Structured output', s.model.structured_output],
                ['Price (input, per 1M tokens)', formatPrice(s.model.price_input_per_mtok)],
                ['Price (output, per 1M tokens)', formatPrice(s.model.price_output_per_mtok)],
              ]}
            />
            <ModelTest />
          </section>
          <section className="panel" aria-labelledby="github-heading">
            <h2 id="github-heading">GitHub integration</h2>
            <KeyValueList
              items={[
                ['API URL', s.github.api_url],
                ['Token', <Configured key="t" value={s.github.token_configured} />],
                [
                  'Webhook secret',
                  <Configured key="w" value={s.github.webhook_secret_configured} />,
                ],
                [
                  'Authorised repositories',
                  s.github.allowed_repositories.length
                    ? s.github.allowed_repositories.join(', ')
                    : 'none',
                ],
              ]}
            />
            <h2>Repositories</h2>
            <KeyValueList
              items={[
                [
                  'Authorised local roots',
                  s.repositories.allowed_local_roots.length ? (
                    <ul key="r" className="plain-list">
                      {s.repositories.allowed_local_roots.map((r) => (
                        <li key={r}>
                          <code>{r}</code>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    'none'
                  ),
                ],
              ]}
            />
          </section>
          <section className="panel" aria-labelledby="exec-heading">
            <h2 id="exec-heading">Execution limits</h2>
            <KeyValueList
              items={[
                ['Sandbox backend', s.execution.sandbox_backend],
                ['Sandbox uid', String(s.execution.sandbox_uid)],
                ['Command timeout', `${s.execution.command_timeout_s} s`],
                ['Memory', `${formatInt(s.execution.memory_mb)} MB`],
                ['Max processes', formatInt(s.execution.max_processes)],
                ['Max file size', `${formatInt(s.execution.max_file_mb)} MB`],
                ['Offline wheelhouse', s.execution.wheelhouse ?? 'none'],
                ['Network in sandbox', yesNo(s.execution.network_in_sandbox)],
                ...(health.data
                  ? ([
                      ['bubblewrap installed', yesNo(health.data.sandbox.bubblewrap_installed)],
                    ] as [string, string][])
                  : []),
              ]}
            />
            <h2>Workflow</h2>
            <KeyValueList
              items={[
                ['Default max attempts', String(s.workflow.default_max_attempts)],
                ['Plan approval required by default', yesNo(s.workflow.require_plan_approval)],
                ['Publication requires approval', yesNo(s.workflow.publish_requires_approval)],
                ['Worker lease', `${s.workflow.worker_lease_s} s`],
              ]}
            />
          </section>
          <section className="panel" aria-labelledby="security-heading">
            <h2 id="security-heading">Security</h2>
            <KeyValueList
              items={[
                ['API token required', yesNo(s.security.api_token_required)],
                ['Notes', s.security.notes],
              ]}
            />
            <ApiTokenForm required={s.security.api_token_required} />
          </section>
        </div>
      ) : null}
      {settings.isError ? (
        <section className="panel">
          <ApiTokenForm required={null} />
        </section>
      ) : null}
    </>
  );
}
