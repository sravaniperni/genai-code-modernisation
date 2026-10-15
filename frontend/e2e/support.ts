import type { APIRequestContext, Page } from '@playwright/test';
import { expect } from '@playwright/test';

/** Working directory of scripts/e2e-backend.sh (same E2E_ROOT default). */
export const E2E_ROOT = process.env.E2E_ROOT ?? '/var/tmp/modernisation-e2e';
/** Created by scripts/e2e-backend.sh before the API starts. */
export const SAMPLE_REPO = `${E2E_ROOT}/sources/inventory`;

export const BUG_REQUEST =
  'apply_discount returns the wrong amount: apply_discount(200.0, 10) should return 180.0 but ' +
  'returns 198.0. Fix the percentage calculation in the pricing module.';

/** Names must be unique per backend database; suffix them so specs never collide. */
export function uniqueName(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
}

/** Register and index the sample repository through the real API (used as setup by task specs). */
export async function registerSampleRepo(
  request: APIRequestContext,
  name: string,
): Promise<number> {
  const created = await request.post('/api/repositories', {
    data: { kind: 'local', source: SAMPLE_REPO, name },
  });
  expect(created.status(), await created.text()).toBe(201);
  const repo = (await created.json()) as { id: number };
  const indexed = await request.post(`/api/repositories/${repo.id}/index`, { data: {} });
  expect(indexed.status(), await indexed.text()).toBe(200);
  return repo.id;
}

/** The state badge in the page header of a task screen. */
export function headerState(page: Page) {
  return page.locator('.page-header [data-state]');
}
