import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ErrorNotice } from '../../components/ErrorNotice';
import { PageHeader } from '../../components/PageHeader';
import { useDocumentTitle } from '../../hooks/useDocumentTitle';
import { ApiError, api, fieldPath } from '../../lib/api';
import { humanize } from '../../lib/format';
import type { TaskCreate } from '../../lib/types';

type Draft = Omit<TaskCreate, 'repository_id'> & { repository_id?: number };

function lines(text: string): string[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
}

/** API (422) messages for one field, matched on the field path ("allowed_paths.0" counts as "allowed_paths"). */
function errorsFor(error: unknown, field: string): string[] {
  if (!(error instanceof ApiError)) return [];
  return error.fieldErrors
    .filter((e) => {
      const p = fieldPath(e.loc);
      return p === field || p.startsWith(`${field}.`);
    })
    .map((e) => e.msg);
}

function Field({
  id,
  label,
  hint,
  errors,
  children,
}: {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  errors: string[];
  children: (describedBy: string | undefined, invalid: boolean) => ReactNode;
}) {
  const ids = [hint ? `${id}-hint` : null, errors.length ? `${id}-error` : null].filter(Boolean);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(ids.length ? ids.join(' ') : undefined, errors.length > 0)}
      {hint ? (
        <p id={`${id}-hint`} className="hint">
          {hint}
        </p>
      ) : null}
      {errors.length ? (
        <p id={`${id}-error`} className="field-error">
          {errors.join(' ')}
        </p>
      ) : null}
    </div>
  );
}

export function TaskCreatePage() {
  useDocumentTitle('New task');
  const id = useId();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search] = useSearchParams();
  const repos = useQuery({ queryKey: ['repositories'], queryFn: api.repositories.list });
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity });
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: api.settings.get,
    staleTime: 60_000,
  });

  const [repositoryId, setRepositoryId] = useState(search.get('repository_id') ?? '');
  const [title, setTitle] = useState('');
  const [request, setRequest] = useState('');
  const [category, setCategory] = useState('');
  const [baseRef, setBaseRef] = useState('');
  const [allowed, setAllowed] = useState('');
  const [forbidden, setForbidden] = useState('');
  const [maxAttempts, setMaxAttempts] = useState<string | null>(null);
  const [requirePlanApproval, setRequirePlanApproval] = useState<boolean | null>(null);
  const [allowTestChanges, setAllowTestChanges] = useState(true);
  const [strategy, setStrategy] = useState<'agentic' | 'single_shot'>('agentic');

  // Until the user edits them, numeric/boolean defaults follow the server's workflow settings.
  const attemptsValue = maxAttempts ?? String(settings.data?.workflow.default_max_attempts ?? 3);
  const planApprovalValue =
    requirePlanApproval ?? settings.data?.workflow.require_plan_approval ?? false;

  const branches = useQuery({
    queryKey: ['branches', Number(repositoryId)],
    queryFn: () => api.repositories.branches(Number(repositoryId)),
    enabled: repositoryId !== '',
  });

  const create = useMutation({
    mutationFn: (body: Draft) => api.tasks.create(body as TaskCreate),
    onSuccess: (task) => {
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      void navigate(`/tasks/${task.id}`);
    },
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    // Validation is the API's job; whatever it rejects is shown next to the field (422 details).
    create.mutate({
      ...(repositoryId ? { repository_id: Number(repositoryId) } : {}),
      title: title.trim(),
      request: request.trim(),
      category,
      ...(baseRef.trim() ? { base_ref: baseRef.trim() } : {}),
      allowed_paths: lines(allowed),
      forbidden_paths: lines(forbidden),
      config: {
        max_attempts: Number.parseInt(attemptsValue, 10),
        require_plan_approval: planApprovalValue,
        allow_test_changes: allowTestChanges,
        strategy,
      },
    });
  };

  const err = (field: string) => errorsFor(create.error, field);
  const selectedRepo = repos.data?.find((r) => String(r.id) === repositoryId);

  return (
    <>
      <PageHeader
        title="New maintenance task"
        description="The task is queued for a worker. Every change is verified and, for GitHub repositories, published only after approval."
      />
      {repos.data && repos.data.length === 0 ? (
        <p className="notice notice-info">
          No repositories are registered. <Link to="/repositories">Register one</Link> first.
        </p>
      ) : null}
      <form className="form panel task-form" onSubmit={onSubmit} noValidate aria-label="New task">
        <Field id={`${id}-repo`} label="Repository" errors={err('repository_id')}>
          {(describedBy, invalid) => (
            <select
              id={`${id}-repo`}
              value={repositoryId}
              onChange={(e) => setRepositoryId(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
            >
              <option value="">Select a repository…</option>
              {(repos.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} ({r.source_kind})
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field id={`${id}-title`} label="Title" errors={err('title')} hint="3–300 characters.">
          {(describedBy, invalid) => (
            <input
              id={`${id}-title`}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
            />
          )}
        </Field>
        <Field
          id={`${id}-request`}
          label="Request"
          errors={err('request')}
          hint="What should change and why (at least 10 characters). Include error messages, versions or API names."
        >
          {(describedBy, invalid) => (
            <textarea
              id={`${id}-request`}
              rows={6}
              value={request}
              onChange={(e) => setRequest(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
            />
          )}
        </Field>
        <div className="form-row">
          <Field id={`${id}-category`} label="Category" errors={err('category')}>
            {(describedBy, invalid) => (
              <select
                id={`${id}-category`}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
              >
                <option value="">Select a category…</option>
                {(meta.data?.categories ?? []).map((c) => (
                  <option key={c} value={c}>
                    {humanize(c)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field
            id={`${id}-base`}
            label={
              <>
                Base ref <span className="optional">(optional)</span>
              </>
            }
            errors={err('base_ref')}
            hint={
              selectedRepo
                ? `Defaults to ${selectedRepo.default_branch}.`
                : 'Defaults to the default branch.'
            }
          >
            {(describedBy, invalid) => (
              <>
                <input
                  id={`${id}-base`}
                  value={baseRef}
                  onChange={(e) => setBaseRef(e.target.value)}
                  list={`${id}-branches`}
                  spellCheck={false}
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                />
                <datalist id={`${id}-branches`}>
                  {Object.keys(branches.data ?? {}).map((b) => (
                    <option key={b} value={b} />
                  ))}
                </datalist>
              </>
            )}
          </Field>
        </div>
        <div className="form-row">
          <Field
            id={`${id}-allowed`}
            label="Allowed paths"
            errors={err('allowed_paths')}
            hint="One repository-relative glob per line, e.g. src/**. Empty means unrestricted."
          >
            {(describedBy, invalid) => (
              <textarea
                id={`${id}-allowed`}
                rows={3}
                value={allowed}
                onChange={(e) => setAllowed(e.target.value)}
                spellCheck={false}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
              />
            )}
          </Field>
          <Field
            id={`${id}-forbidden`}
            label="Forbidden paths"
            errors={err('forbidden_paths')}
            hint="One glob per line; the agent may never modify these."
          >
            {(describedBy, invalid) => (
              <textarea
                id={`${id}-forbidden`}
                rows={3}
                value={forbidden}
                onChange={(e) => setForbidden(e.target.value)}
                spellCheck={false}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
              />
            )}
          </Field>
        </div>
        <div className="form-row">
          <Field
            id={`${id}-attempts`}
            label="Max attempts"
            errors={err('config.max_attempts')}
            hint="1–6 patch attempts (including repairs)."
          >
            {(describedBy, invalid) => (
              <input
                id={`${id}-attempts`}
                type="number"
                min={1}
                max={6}
                value={attemptsValue}
                onChange={(e) => setMaxAttempts(e.target.value)}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
              />
            )}
          </Field>
          <Field id={`${id}-strategy`} label="Strategy" errors={err('config.strategy')}>
            {(describedBy) => (
              <select
                id={`${id}-strategy`}
                value={strategy}
                onChange={(e) => setStrategy(e.target.value as 'agentic' | 'single_shot')}
                aria-describedby={describedBy}
              >
                <option value="agentic">Agentic (plan, implement, test, repair)</option>
                <option value="single_shot">Single shot (one attempt, no repair)</option>
              </select>
            )}
          </Field>
        </div>
        <div className="checkbox-group">
          <label>
            <input
              type="checkbox"
              checked={planApprovalValue}
              onChange={(e) => setRequirePlanApproval(e.target.checked)}
            />
            Require plan approval before implementation
          </label>
          <label>
            <input
              type="checkbox"
              checked={allowTestChanges}
              onChange={(e) => setAllowTestChanges(e.target.checked)}
            />
            Allow the agent to change tests
          </label>
        </div>
        <ErrorNotice
          error={create.error}
          title={
            create.error instanceof ApiError && create.error.status === 422
              ? 'The API rejected the task (422)'
              : undefined
          }
        />
        <div className="button-row">
          <button type="submit" className="primary" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create task'}
          </button>
        </div>
      </form>
    </>
  );
}
