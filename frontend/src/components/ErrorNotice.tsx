import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { ApiError, fieldPath } from '../lib/api';

function heading(status: number | null): string {
  if (status === null) return 'Something went wrong';
  if (status === 0) return 'API unreachable';
  if (status === 400) return 'Request rejected (400)';
  if (status === 401) return 'Authentication required (401)';
  if (status === 403) return 'Not authorised (403)';
  if (status === 404) return 'Not found (404)';
  if (status === 409) return 'Conflict (409)';
  if (status === 422) return 'Validation failed (422)';
  if (status >= 500) return `Server error (${status})`;
  return `Request failed (${status})`;
}

/** Renders an API (or unexpected) error. 422 responses list each invalid field. */
export function ErrorNotice({ error, title }: { error: unknown; title?: string }) {
  if (!error) return null;
  const apiError = error instanceof ApiError ? error : null;
  const message =
    error instanceof Error
      ? error.message
      : typeof error === 'string'
        ? error
        : 'Unexpected error.';
  return (
    <div className="notice notice-error" role="alert">
      <p className="notice-title">{title ?? heading(apiError ? apiError.status : null)}</p>
      {apiError && apiError.fieldErrors.length > 0 ? (
        <ul className="field-errors">
          {apiError.fieldErrors.map((e, i) => (
            <li key={i}>
              {fieldPath(e.loc) ? <code>{fieldPath(e.loc)}</code> : null} {e.msg}
            </li>
          ))}
        </ul>
      ) : (
        <p>{message}</p>
      )}
      {apiError?.status === 401 ? (
        <p>
          This backend requires an API token for changes. Enter it in{' '}
          <Link to="/settings#api-token">Settings</Link>.
        </p>
      ) : null}
      {apiError?.status === 0 ? (
        <p>Check that the backend is running and that the dev server proxies /api to it.</p>
      ) : null}
    </div>
  );
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <p className="muted loading" role="status">
      {label}
    </p>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
