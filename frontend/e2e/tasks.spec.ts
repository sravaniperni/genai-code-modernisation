import { expect, test } from '@playwright/test';
import { BUG_REQUEST, headerState, registerSampleRepo, uniqueName } from './support';

let repoName = '';

test.beforeAll(async ({ request }) => {
  repoName = uniqueName('tasks-repo');
  await registerSampleRepo(request, repoName);
});

test('the task form shows validation errors returned by the API', async ({ page }) => {
  await page.goto('/tasks/new');
  await page.getByRole('button', { name: 'Create task' }).click();
  await expect(page.getByRole('alert')).toContainText('The API rejected the task (422)');
  await expect(page.getByLabel('Repository')).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByLabel('Title')).toHaveAttribute('aria-invalid', 'true');

  await page.getByLabel('Repository').selectOption({ label: `${repoName} (local)` });
  await page.getByLabel('Title').fill('Escape the scope');
  await page.getByLabel('Request').fill(BUG_REQUEST);
  await page.getByLabel('Category').selectOption('bug_fix');
  await page.getByLabel('Allowed paths').fill('../secrets');
  await page.getByRole('button', { name: 'Create task' }).click();
  // Errors from the first submission stay rendered until the resubmission re-renders, so wait for the
  // new error itself (retrying) instead of asserting on whichever error elements exist right after the click.
  await expect(
    page.locator('.field-error', { hasText: 'scope patterns must be repository-relative' }),
  ).toBeVisible();
  await expect(page.locator('.field-error')).toHaveCount(1);
  await expect(page.getByLabel('Allowed paths')).toHaveAttribute('aria-invalid', 'true');
  await expect(page).toHaveURL(/\/tasks\/new$/);
});

test('create a task, follow it in the monitor, cancel and restart it', async ({ page }) => {
  const title = uniqueName('Fix discount percentage');
  await page.goto('/tasks/new');
  await page.getByLabel('Repository').selectOption({ label: `${repoName} (local)` });
  await page.getByLabel('Title').fill(title);
  await page.getByLabel('Request').fill(BUG_REQUEST);
  await page.getByLabel('Category').selectOption('bug_fix');
  await page.getByLabel(/Base ref/).fill('main');
  await page.getByLabel('Allowed paths').fill('src/**\ntests/**');
  await page.getByLabel('Max attempts').fill('2');
  await page.getByRole('button', { name: 'Create task' }).click();

  await expect(page).toHaveURL(/\/tasks\/\d+$/);
  const log = page.getByRole('log', { name: 'Event log' });

  await test.step('the monitor shows the queued task and its event log', async () => {
    await expect(page.getByRole('heading', { level: 1 })).toContainText(title);
    await expect(headerState(page)).toHaveText('QUEUED');
    await expect(log).toContainText('task created at');
    await expect(log).toContainText('(main)');
    // No worker or model runs in E2E; the page says so instead of pretending progress.
    await expect(page.getByText('Queued: waiting for a worker')).toBeVisible();
    await expect(page.getByText(/No model endpoint is configured/)).toBeVisible();
    await expect(page.getByText(/Live: polling every 2 s/)).toBeVisible();
    await expect(page.getByText('0 of 2')).toBeVisible();
    await expect(page.getByText('No model calls recorded for this task.')).toBeVisible();
    await expect(page.getByText('No checks have run for this task.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Restart task' })).toBeDisabled();
  });

  await test.step('cancel', async () => {
    await page.getByRole('button', { name: 'Cancel task' }).click();
    await expect(headerState(page)).toHaveText('CANCELLED');
    await expect(log).toContainText('cancellation requested');
    await expect(log).toContainText('QUEUED -> CANCELLED: cancelled by user');
    await expect(page.getByText('Polling stopped: the task is in a terminal state.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Cancel task' })).toBeDisabled();
    await expect(
      page.getByRole('list', { name: 'State timeline' }).locator('[data-state="CANCELLED"]'),
    ).toBeVisible();
  });

  await test.step('restart', async () => {
    await page.getByRole('button', { name: 'Restart task' }).click();
    await expect(headerState(page)).toHaveText('QUEUED');
    await expect(log).toContainText('CANCELLED -> QUEUED: restarted by user');
    await expect(page.getByText(/Live: polling every 2 s/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Restart task' })).toBeDisabled();
  });

  await test.step('code review shows what exists and nothing more', async () => {
    await page.getByRole('link', { name: 'Code review' }).click();
    await expect(
      page.getByText(/Approval is only possible while the task is awaiting/),
    ).toBeVisible();
    await expect(page.getByText('No plan has been recorded for this task yet.')).toBeVisible();
    await expect(
      page.getByText('No final diff: the task has not produced a verified change.'),
    ).toBeVisible();
    await expect(page.getByText('No patch attempts yet.')).toBeVisible();
  });

  await test.step('the task appears in the task list and on the dashboard', async () => {
    const nav = page.getByRole('navigation', { name: 'Primary' });
    await nav.getByRole('link', { name: 'Tasks', exact: true }).click();
    await expect(page.getByRole('link', { name: title })).toBeVisible();
    await nav.getByRole('link', { name: 'Dashboard' }).click();
    const active = page.getByRole('region', { name: 'Active tasks' });
    await expect(active.getByRole('link', { name: title })).toBeVisible();
    await expect(page.getByRole('img', { name: /Number of tasks in each state/ })).toBeVisible();
  });
});
