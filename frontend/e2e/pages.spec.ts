import { expect, test } from '@playwright/test';
import { E2E_ROOT } from './support';

test('evaluation page reports that no runs exist', async ({ page }) => {
  await page.goto('/evaluation');
  await expect(page.getByRole('heading', { name: 'Evaluation', level: 1 })).toBeVisible();
  await expect(page.getByText('No evaluation results available.', { exact: true })).toBeVisible();
  await expect(page.getByRole('table')).toHaveCount(0);
});

test('settings page shows the real backend configuration and model test result', async ({
  page,
}) => {
  await page.goto('/settings');

  const model = page.getByRole('region', { name: 'Model endpoint' });
  await expect(model).toContainText('not configured');
  const github = page.getByRole('region', { name: 'GitHub integration' });
  await expect(github).toContainText('https://api.github.com');
  await expect(github).toContainText(`${E2E_ROOT}/sources`);
  await expect(page.getByRole('region', { name: 'Execution limits' })).toContainText('bubblewrap');
  await expect(page.getByRole('region', { name: 'Security' })).toContainText('API token required');

  const health = page.getByRole('list', { name: 'Backend status' });
  await expect(health).toContainText('Database reachable');
  await expect(health).toContainText('Model not configured');

  await test.step('test model connection shows the real answer', async () => {
    await page.getByRole('button', { name: 'Test model connection' }).click();
    const alert = model.getByRole('alert');
    await expect(alert).toContainText('Request rejected (400)');
    await expect(alert).toContainText('no model endpoint configured');
  });

  await test.step('API token is kept in this browser', async () => {
    await page.getByLabel('Token', { exact: true }).fill('e2e-token');
    await page.getByRole('button', { name: 'Save token' }).click();
    await expect(page.getByText('A token is stored in this browser.')).toBeVisible();
    await page.reload();
    await expect(page.getByText('A token is stored in this browser.')).toBeVisible();
    await page.getByRole('button', { name: 'Clear token' }).click();
    await expect(page.getByText('No token stored.')).toBeVisible();
  });
});
