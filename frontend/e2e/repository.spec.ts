import { expect, test } from '@playwright/test';
import { BUG_REQUEST, SAMPLE_REPO, uniqueName } from './support';

test('register a repository, index it, browse a file and search', async ({ page }) => {
  const name = uniqueName('inventory');
  await page.goto('/repositories');
  await expect(page.getByRole('heading', { name: 'Repository explorer' })).toBeVisible();
  const register = page.getByRole('button', { name: 'Register repository' });

  await test.step('the backend refuses unauthorised sources with 403', async () => {
    await page.getByLabel('Path on the server').fill('/etc');
    await register.click();
    const alert = page.getByRole('alert');
    await expect(alert).toContainText('Not authorised (403)');
    await expect(alert).toContainText('/etc is not under an authorised local root');

    await page.getByLabel('GitHub').check();
    await page.getByLabel('Repository (owner/name)').fill('someone-else/private-repo');
    await register.click();
    await expect(page.getByRole('alert')).toContainText('not in the authorised repository list');
    await page.getByLabel('Local git repository').check();
  });

  await test.step('register the sample repository', async () => {
    await page.getByLabel('Path on the server').fill(SAMPLE_REPO);
    await page.getByLabel(/^Name/).fill(name);
    await register.click();
    await expect(page).toHaveURL(/\/repositories\/\d+$/);
    await expect(page.getByRole('heading', { name, level: 2 })).toBeVisible();
    await expect(page.getByText('Not indexed yet.')).toBeVisible();
    await expect(page.getByText(/This view reads the code index/)).toBeVisible();
  });

  await test.step('index it', async () => {
    await page.getByRole('button', { name: 'Index now' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Indexed 8 files' })).toBeVisible();
    await expect(page.locator('.repo-list a.active')).toContainText('index ready');
  });

  const tree = page.getByRole('navigation', { name: 'File tree' });
  await test.step('browse the tree and open a file', async () => {
    await expect(tree.getByRole('link', { name: 'test_pricing.py test' })).toBeVisible();
    await expect(tree.getByRole('link', { name: 'pyproject.toml config' })).toBeVisible();
    await tree.getByRole('link', { name: 'pricing.py', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'src/inventory/pricing.py', level: 3 }),
    ).toBeVisible();
    const code = page.getByRole('region', { name: 'Contents of src/inventory/pricing.py' });
    await expect(code.locator('tr[data-line="14"]')).toContainText('percent / 1000');

    const outline = page.getByRole('navigation', { name: 'Symbol outline' });
    await outline.getByRole('link', { name: /apply_discount/ }).click();
    await expect(page).toHaveURL(/line=10&end=14/);
    await expect(code.locator('tr.highlight')).toHaveCount(5);
    await expect(code.locator('tr.highlight').first()).toHaveAttribute('data-line', '10');
  });

  await test.step('analyse the impact of changing the file', async () => {
    await page.getByRole('button', { name: 'Analyse impact of changing this file' }).click();
    const impact = page.locator('.impact');
    await expect(impact.getByRole('link', { name: 'src/inventory/report.py' })).toBeVisible();
    await expect(impact.getByRole('link', { name: 'tests/test_pricing.py' }).first()).toBeVisible();
  });

  const views = page.getByRole('navigation', { name: 'Repository views' });
  const search = async (query: string, mode: string) => {
    await views.getByRole('link', { name: 'Search' }).click();
    await page.getByLabel('Query').fill(query);
    await page.getByLabel('Mode').selectOption(mode);
    await page.getByRole('button', { name: 'Search', exact: true }).click();
  };

  await test.step('text search links to file and line', async () => {
    await search('percent / 1000', 'text');
    const hit = page.getByRole('link', { name: 'src/inventory/pricing.py:14' });
    await expect(hit).toBeVisible();
    await hit.click();
    await expect(
      page.getByRole('heading', { name: 'src/inventory/pricing.py', level: 3 }),
    ).toBeVisible();
    await expect(page.locator('.code-view tr.highlight')).toHaveAttribute('data-line', '14');
  });

  await test.step('symbol, references and invalid regex searches', async () => {
    await search('LineItem', 'symbol');
    const symbolRow = page.getByRole('row').filter({ hasText: 'src/inventory/models.py:8–16' });
    await expect(symbolRow).toContainText('class');

    await search('is_bulk', 'references');
    await expect(
      page.getByRole('link', { name: /^src\/inventory\/report\.py:\d+$/ }).first(),
    ).toBeVisible();

    await search('(', 'regex');
    await expect(page.getByRole('alert')).toContainText('Request rejected (400)');
    await expect(page.getByRole('alert')).toContainText('invalid pattern');
  });

  await test.step('commits and snapshots', async () => {
    await views.getByRole('link', { name: 'Commits' }).click();
    await expect(page.getByRole('cell', { name: 'add order summary report' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'initial import' })).toBeVisible();
    await views.getByRole('link', { name: 'Index snapshots' }).click();
    await expect(page.getByRole('table').getByText('ready')).toBeVisible();
  });

  await test.step('review findings from the retrieval engine', async () => {
    await views.getByRole('link', { name: 'Review findings' }).click();
    await page.getByLabel('Maintenance request').fill(BUG_REQUEST);
    await page.getByLabel('Category').selectOption('bug_fix');
    await page.getByRole('button', { name: 'Find relevant code' }).click();
    const first = page.locator('.finding').first();
    await expect(first.getByRole('link', { name: 'src/inventory/pricing.py' })).toBeVisible();
    await expect(first).toContainText('lines 10–14');
    await expect(first).toContainText('apply_discount (function)');
    await expect(first).toContainText('keyword');
    await expect(first).toContainText('symbol');
  });
});
