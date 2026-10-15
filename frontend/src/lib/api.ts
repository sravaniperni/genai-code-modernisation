import { getApiToken } from './token';
import type {
  ApprovalInput,
  AttemptDetail,
  Branches,
  CheckRun,
  Commit,
  Dashboard,
  EvaluationRunSummary,
  FileResponse,
  Health,
  ImpactResponse,
  Meta,
  ModelCall,
  ModelTestResult,
  Repository,
  RepositoryCreate,
  RetrieveRequest,
  RetrieveResponse,
  SearchMode,
  SearchResponse,
  SettingsView,
  Snapshot,
  TaskCreate,
  TaskDetail,
  TaskEvent,
  TaskSummary,
  TreeResponse,
} from './types';

/** All requests go to relative /api URLs; Vite proxies them to the backend in dev and preview. */
export const API_BASE = '/api';

export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type?: string;
}

/** An error response from the API, or (status 0) a failure to reach it at all. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly fieldErrors: FieldError[];

  constructor(status: number, message: string, detail: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.fieldErrors = Array.isArray(detail) ? detail.filter(isFieldError) : [];
  }
}

function isFieldError(value: unknown): value is FieldError {
  return (
    typeof value === 'object' &&
    value !== null &&
    Array.isArray((value as FieldError).loc) &&
    typeof (value as FieldError).msg === 'string'
  );
}

/** "body.config.max_attempts" -> "config.max_attempts" (FastAPI prefixes request-body errors with "body"). */
export function fieldPath(loc: (string | number)[]): string {
  const parts = loc[0] === 'body' || loc[0] === 'query' ? loc.slice(1) : loc;
  return parts.join('.');
}

function messageFor(status: number, detail: unknown): string {
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail)) {
    const items = detail.filter(isFieldError);
    if (items.length) {
      return items
        .map((e) => (fieldPath(e.loc) ? `${fieldPath(e.loc)}: ${e.msg}` : e.msg))
        .join('; ');
    }
  }
  return `HTTP ${status}`;
}

type QueryValue = string | number | boolean | null | undefined;

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`;
}

interface RequestOptions {
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiRequest<T>(
  method: 'GET' | 'POST',
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') {
    // Only mutating endpoints are protected; reads stay open, so the token is not sent with them.
    const token = getApiToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'The API server could not be reached.');
  }
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) {
    const detail =
      typeof data === 'object' && data !== null && 'detail' in data ? data.detail : data;
    throw new ApiError(response.status, messageFor(response.status, detail), detail);
  }
  return data as T;
}

const get = <T>(path: string, query?: Record<string, QueryValue>, signal?: AbortSignal) =>
  apiRequest<T>('GET', path, { query, signal });
const post = <T>(path: string, body?: unknown) => apiRequest<T>('POST', path, { body: body ?? {} });

export const api = {
  health: () => get<Health>('/health'),
  meta: () => get<Meta>('/meta'),
  dashboard: () => get<Dashboard>('/dashboard'),

  repositories: {
    list: () => get<Repository[]>('/repositories'),
    get: (id: number) => get<Repository>(`/repositories/${id}`),
    create: (body: RepositoryCreate) => post<Repository>('/repositories', body),
    refresh: (id: number) => post<{ branches: Branches }>(`/repositories/${id}/refresh`),
    index: (id: number, ref?: string) =>
      post<Snapshot>(`/repositories/${id}/index`, ref ? { ref } : {}),
    snapshots: (id: number) => get<Snapshot[]>(`/repositories/${id}/snapshots`),
    branches: (id: number) => get<Branches>(`/repositories/${id}/branches`),
    commits: (id: number, ref?: string, limit = 50) =>
      get<Commit[]>(`/repositories/${id}/commits`, { ref, limit }),
    tree: (id: number, ref?: string) => get<TreeResponse>(`/repositories/${id}/tree`, { ref }),
    file: (id: number, path: string, ref?: string) =>
      get<FileResponse>(`/repositories/${id}/file`, { path, ref }),
    search: (id: number, q: string, mode: SearchMode, ref?: string, limit = 200) =>
      get<SearchResponse>(`/repositories/${id}/search`, { q, mode, ref, limit }),
    retrieve: (id: number, body: RetrieveRequest) =>
      post<RetrieveResponse>(`/repositories/${id}/retrieve`, body),
    impact: (id: number, body: { paths: string[]; symbols?: string[]; ref?: string }) =>
      post<ImpactResponse>(`/repositories/${id}/impact`, body),
  },

  tasks: {
    list: (filters: { state?: string; repository_id?: number; limit?: number } = {}) =>
      get<TaskSummary[]>('/tasks', filters),
    create: (body: TaskCreate) => post<TaskSummary>('/tasks', body),
    get: (id: number) => get<TaskDetail>(`/tasks/${id}`),
    events: (id: number, afterId: number, signal?: AbortSignal) =>
      get<TaskEvent[]>(`/tasks/${id}/events`, { after_id: afterId }, signal),
    attempt: (id: number, attemptNo: number) =>
      get<AttemptDetail>(`/tasks/${id}/attempts/${attemptNo}`),
    checks: (id: number) => get<CheckRun[]>(`/tasks/${id}/checks`),
    modelCalls: (id: number) => get<ModelCall[]>(`/tasks/${id}/model-calls`),
    cancel: (id: number) => post<TaskSummary>(`/tasks/${id}/cancel`),
    restart: (id: number) => post<TaskSummary>(`/tasks/${id}/restart`),
    approve: (id: number, body: ApprovalInput) => post<TaskSummary>(`/tasks/${id}/approval`, body),
  },

  evaluation: {
    runs: () => get<EvaluationRunSummary[]>('/evaluation/runs'),
    run: (id: number) => get<EvaluationRunSummary>(`/evaluation/runs/${id}`),
  },

  settings: {
    get: () => get<SettingsView>('/settings'),
    testModel: () => post<ModelTestResult>('/settings/model/test'),
  },
};
