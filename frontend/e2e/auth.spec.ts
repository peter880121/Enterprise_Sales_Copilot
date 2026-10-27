import { test, expect } from '@playwright/test';

test('real browser login, dependency status and logout via same origin', async ({ page }) => {
  test.skip(!process.env.E2E_EMAIL || !process.env.E2E_PASSWORD, 'Use tools.proxy_validation --browser');
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '登录工作空间' })).toBeVisible();
  await page.getByLabel('邮箱').fill(process.env.E2E_EMAIL!);
  await page.getByLabel('密码').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await expect(page.getByRole('heading', { name: '工作空间概览' })).toBeVisible();
  await expect(page.getByText('MOCK · 仅适配骨架')).toBeVisible();
  await expect(page.getByRole('heading', { name: '业务模块尚未交付' })).toBeVisible();
  await expect(page.getByRole('button', { name: '销售商机 M2' })).toBeDisabled();
  await page.screenshot({ path: '../.local/m1-workspace.png', fullPage: true });
  await page.reload();
  await expect(page.getByRole('heading', { name: '工作空间概览' })).toBeVisible();
  await page.getByRole('button', { name: '退出登录' }).click();
  await expect(page.getByRole('heading', { name: '登录工作空间' })).toBeVisible();
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '登录工作空间' })).toBeVisible();
});
