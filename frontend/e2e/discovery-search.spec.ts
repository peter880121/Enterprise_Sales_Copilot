import { test, expect } from '@playwright/test';
import { writeFileSync } from 'node:fs';
const users = JSON.parse(process.env.M2_BROWSER_USERS || '{}') as Record<string, { id: string; email: string }>;

test('explicit public query reaches Tavily once and the same accepted task survives a lost response', async ({ page }, testInfo) => {
  test.skip(process.env.E2E_TAVILY_SEARCH !== 'true' || !users.ADMIN, 'Explicit isolated D2 environment with search quota and real Tavily credentials required');
  test.setTimeout(180000);
  await page.goto('/login');
  await page.getByLabel('邮箱', { exact: true }).fill(users.ADMIN.email);
  await page.getByLabel('密码', { exact: true }).fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await expect(page.getByRole('heading', { name: '工作空间概览' })).toBeVisible();
  await page.getByRole('button', { name: /商机发现 D[12]/ }).click();
  const form = page.getByRole('form', { name: '新建销售画像' });
  await form.getByLabel('画像名称', { exact: true }).fill(`Synthetic search profile ${crypto.randomUUID().slice(0, 8)}`);
  await form.getByLabel('产品或解决方案').fill('Synthetic medical devices');
  await form.getByLabel('匹配关键词').fill('PRIVATE_NOT_FOR_SEARCH');
  await form.getByRole('button', { name: '创建画像', exact: true }).click();
  const search = page.getByRole('region', { name: '公开搜索查询预览', exact: true });
  await expect(search.getByLabel('允许外发的公开查询')).toHaveValue('');
  await search.getByLabel('允许外发的公开查询').fill('超声 医疗器械 采购意向');
  await search.getByRole('button', { name: '预览公开查询', exact: true }).click();
  await expect(search.getByRole('button', { name: '确认并开始搜索' })).toBeDisabled();
  await search.getByLabel('我确认仅发送以上公开查询，并了解搜索可能计费').check();
  const bodies: string[] = [], ids: string[] = [];
  let lost = false;
  await page.route('**/api/v1/discovery/profiles/*/search-runs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    bodies.push(route.request().postData()!);
    if (!lost) {
      lost = true;
      const response = await route.fetch();
      expect(response.status()).toBe(202);
      ids.push((await response.json()).data.id);
      await route.abort('failed');
    } else {
      const response = await route.fetch();
      ids.push((await response.json()).data.id);
      await route.fulfill({ response });
    }
  });
  await search.getByRole('button', { name: '确认并开始搜索' }).click();
  await expect(search.getByRole('alert')).toContainText('保留原请求');
  expect(bodies).toHaveLength(1);
  await search.getByRole('button', { name: '按原请求重试受理' }).click();
  await expect(search.getByRole('button', { name: '搜索任务已受理' })).toBeDisabled();
  const detail = search.getByRole('region', { name: '公开搜索任务详情' });
  await expect(detail.getByRole('status')).toContainText('SUCCEEDED', { timeout: 140000 });
  await expect(search.getByRole('button', { name: '超声 医疗器械 采购意向 · SUCCEEDED', exact: true }).first()).toBeVisible();
  expect(bodies).toHaveLength(2);
  expect(bodies[0]).toBe(bodies[1]);
  expect(ids[0]).toBe(ids[1]);
  expect(bodies[0]).not.toContain('PRIVATE_NOT_FOR_SEARCH');
  await expect(detail.getByText(/以下仅为搜索服务摘要/)).toBeVisible();
  const acceptedUrl = page.request;
  const current = await acceptedUrl.get(`/api/v1/discovery/search-runs/${ids[0]}`);
  expect(current.status()).toBe(200);
  writeFileSync(testInfo.outputPath('search-receipt.json'), JSON.stringify({ id: ids[0], body: JSON.parse(bodies[0]), result: (await current.json()).data }));
  await page.screenshot({ path: testInfo.outputPath('tavily-public-search-once.png'), fullPage: true });
});
