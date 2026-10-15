import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { vi } from 'vitest';

export interface MockRoute {
  method?: string;
  /** Matched against the request path (and query) with startsWith unless it is a RegExp. */
  path: string | RegExp;
  status?: number;
  /** Fixed JSON body, or a function computing it from the request. */
  body?: unknown;
  respond?: (request: { url: string; method: string; body: unknown }) => unknown;
}

export interface RecordedRequest {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

/**
 * Replace fetch with a router over canned responses. Only for unit tests: the E2E suite always talks
 * to the real backend.
 */
export function mockFetch(routes: MockRoute[]) {
  const requests: RecordedRequest[] = [];
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? 'GET').toUpperCase();
    const body: unknown = typeof init?.body === 'string' ? JSON.parse(init.body) : null;
    requests.push({ url, method, headers: (init?.headers ?? {}) as Record<string, string>, body });
    const route = routes.find(
      (r) =>
        (r.method ?? 'GET').toUpperCase() === method &&
        (typeof r.path === 'string' ? url.startsWith(r.path) : r.path.test(url)),
    );
    if (!route) {
      return Promise.resolve(
        new Response(JSON.stringify({ detail: `no mock for ${method} ${url}` }), { status: 404 }),
      );
    }
    const payload = route.respond ? route.respond({ url, method, body }) : route.body;
    return Promise.resolve(
      new Response(JSON.stringify(payload), {
        status: route.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  });
  vi.stubGlobal('fetch', fn);
  return { fetch: fn, requests };
}

export function renderWithProviders(
  ui: ReactElement,
  { route = '/', path = '*' }: { route?: string; path?: string } = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
