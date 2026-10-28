import { test, expect } from '@playwright/test';

test('real M2 browser creates account and unknown-amount opportunity, then moves stage', async ({ page }, testInfo) => {
  test.skip(!process.env.E2E_SALES || !process.env.E2E_EMAIL || !process.env.E2E_PASSWORD,
    'Requires isolated M2 validation environment');
  await page.goto('/login');
  await page.getByLabel('邮箱').fill(process.env.E2E_EMAIL!);
  await page.getByLabel('密码').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await expect(page.getByRole('heading', { name: '工作空间概览' })).toBeVisible();
  await page.getByRole('button', { name: '客户与联系人 M2' }).click();
  await page.getByRole('button', { name: '创建客户', exact: true }).click();
  const suffix = Date.now();
  await page.getByLabel('客户名称').fill(`Browser Synthetic ${suffix}`);
  await page.getByRole('button', { name: '保存客户' }).click();
  await expect(page.getByRole('heading', { name: `Browser Synthetic ${suffix}` })).toBeVisible();
  await page.getByRole('button', { name: '销售商机 M2' }).click();
  await page.getByRole('button', { name: '创建商机', exact: true }).click();
  await page.getByLabel('商机名称').fill(`Browser Opportunity ${suffix}`);
  await page.getByLabel('搜索客户').fill(`Browser Synthetic ${suffix}`);
  await page.getByLabel('客户企业').selectOption({ label: `Browser Synthetic ${suffix}` });
  await page.getByRole('button', { name: '保存商机' }).click();
  await expect(page.getByRole('heading', { name: `Browser Opportunity ${suffix}` })).toBeVisible();
  await expect(page.getByRole('heading', { name: '预计 金额待确认' })).toBeVisible();
  await page.getByLabel('目标阶段').selectOption('NEGOTIATION');
  await page.getByLabel('操作原因', { exact: true }).fill('Synthetic browser stage change');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '确认阶段变更' }).click();
  await expect(page.getByText('谈判中 · 60%')).toBeVisible();
  await page.reload();
  await expect(page.getByText('谈判中 · 60%')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('opportunity-browser.png'), fullPage: true });
  await page.getByRole('button', { name: '退出登录' }).click();
  await expect(page.getByRole('heading', { name: '登录工作空间' })).toBeVisible();
});
