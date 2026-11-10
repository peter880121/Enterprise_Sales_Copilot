import { test, expect, type Page } from '@playwright/test';
const users = JSON.parse(process.env.M2_BROWSER_USERS || '{}') as Record<string, { id: string; email: string }>;
test.beforeEach(() => test.skip(!process.env.E2E_SALES || !users.SALES_MANAGER, 'Explicit isolated M3-B environment required'));
async function login(page: Page, role: string) {
  await page.goto('/login'); await page.getByLabel('邮箱', { exact: true }).fill(users[role].email);
  await page.getByLabel('密码', { exact: true }).fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await expect(page.getByRole('heading', { name: '工作空间概览' })).toBeVisible();
}
test('explicit partial selection survives a lost response and applies exactly once', async ({ page }, testInfo) => {
  test.setTimeout(90000); await login(page, 'SALES_MANAGER');
  const csrf = (await (await page.request.get('/api/v1/auth/me')).json()).data.csrf_token;
  const headers = { Origin: process.env.E2E_BASE_URL!, 'X-CSRF-Token': csrf };
  const accountResponse = await page.request.post('/api/v1/accounts', { headers, data: { name: `Synthetic apply ${Date.now()}` } });
  expect(accountResponse.status()).toBe(201); const account = (await accountResponse.json()).data;
  const name = `Apply ${crypto.randomUUID().slice(0, 10)}`;
  const opportunityResponse = await page.request.post('/api/v1/opportunities', { headers, data: { name, account_id: account.id } });
  expect(opportunityResponse.status()).toBe(201); const opportunity = (await opportunityResponse.json()).data;
  await page.getByRole('button', { name: '会议解析 M3-B', exact: true }).click();
  await page.getByLabel('搜索待分析商机').fill(name);
  await page.getByRole('button', { name: `选择商机：${name}`, exact: true }).click();
  await page.getByRole('textbox', { name: '合成会议纪要', exact: true }).fill('需求：Synthetic controlled execution\n预计金额：2500.00\n币种：USD\n优先级：HIGH\n备注：Synthetic accepted follow-up');
  await page.getByLabel('我确认这里只使用合成演示资料').check();
  await page.getByRole('button', { name: '提交 Mock 解析' }).click();
  const apply = page.getByRole('region', { name: '受控执行' });
  await expect(apply.getByRole('button', { name: '确认执行所选变更' })).toBeDisabled();
  await expect(apply.getByRole('checkbox', { name: '字段：amount / currency' })).not.toBeChecked();
  await apply.getByRole('checkbox', { name: '字段：amount / currency' }).check();
  await apply.getByRole('checkbox', { name: '追加备注 NOTE' }).check();
  await apply.getByRole('checkbox', { name: '我已核对所选变更及依据，确认执行' }).check();
  let first = true; const keys: string[] = [];
  await page.route('**/api/v1/suggestions/*/apply', async route => {
    keys.push(route.request().headers()['idempotency-key']);
    if (first) { first = false; expect((await route.fetch()).status()).toBe(200); await route.abort('failed'); }
    else await route.continue();
  });
  await apply.getByRole('button', { name: '确认执行所选变更' }).click();
  await expect(apply.getByRole('alert')).toContainText('无法连接服务');
  await apply.getByRole('button', { name: '确认执行所选变更' }).click();
  await expect(page.getByText(/草稿已执行，商机版本 2/)).toBeVisible();
  expect(keys).toHaveLength(2); expect(keys[0]).toBe(keys[1]);
  const after = (await (await page.request.get(`/api/v1/opportunities/${opportunity.id}`)).json()).data;
  expect(after.amount).toBe('2500.00'); expect(after.currency).toBe('USD'); expect(after.version).toBe(2);
  expect(after.priority).toBe('MEDIUM'); expect(after.stage).toBe('PROPOSAL_SUBMITTED'); expect(after.probability).toBe(20);
  const activities = (await (await page.request.get(`/api/v1/activities?opportunity_id=${opportunity.id}`)).json()).data;
  expect(activities).toHaveLength(1); expect(activities[0].type).toBe('NOTE');
  // A new draft must use an explicitly refreshed server baseline, without losing input
  // or silently advancing the baseline of the already executed draft.
  await page.getByRole('textbox', { name: '合成会议纪要', exact: true }).fill('备注：Synthetic next draft');
  await expect(page.getByText(/基础版本 1，/)).toBeVisible();
  await page.getByRole('button', { name: '读取当前商机版本', exact: true }).click();
  await expect(page.getByText(/基础版本 2，/)).toBeVisible();
  await expect(page.getByRole('textbox', { name: '合成会议纪要', exact: true })).toHaveValue('备注：Synthetic next draft');
  const accepted = page.waitForResponse(response => response.url().endsWith(`/opportunities/${opportunity.id}/meeting-analyses`) && response.request().method() === 'POST');
  await page.getByRole('button', { name: '提交 Mock 解析' }).click();
  const next = await accepted; expect(next.status()).toBe(202);
  await expect(page.getByRole('region', { name: '受控执行' }).getByRole('checkbox', { name: '追加备注 NOTE' })).not.toBeChecked();
  const nextAnalysis = (await (await page.request.get(`/api/v1/meeting-analyses/${(await next.json()).data.resource_id}`)).json()).data;
  expect(nextAnalysis.base_opportunity_version).toBe(2);
  expect((await (await page.request.get(`/api/v1/opportunities/${opportunity.id}`)).json()).data.version).toBe(2);
  expect(keys).toHaveLength(2); // Reading and generating a new draft never automatically applies it.
  await page.screenshot({ path: testInfo.outputPath('controlled-apply-once.png'), fullPage: true });
  const regenerate = page.getByRole('region', { name: '重新生成草稿', exact: true });
  await regenerate.getByRole('button', { name: '读取重新生成基准' }).click();
  await regenerate.getByLabel('我确认复制原始合成纪要，并替换当前未执行草稿').check();
  const regenerateTokens: string[] = []; let firstRegeneration = true;
  await page.route('**/api/v1/suggestions/*/regenerate', async route => {
    regenerateTokens.push(route.request().postDataJSON().request_token);
    if (firstRegeneration) { firstRegeneration = false; expect((await route.fetch()).status()).toBe(202); await route.abort('failed'); }
    else await route.continue();
  });
  await regenerate.getByRole('button', { name: '确认重新生成' }).click();
  await expect(regenerate.getByRole('alert')).toContainText('无法连接服务');
  await regenerate.getByRole('button', { name: '确认重新生成' }).click();
  await expect(regenerate.getByRole('button', { name: '查看新草稿' })).toBeVisible();
  expect(regenerateTokens).toHaveLength(2); expect(regenerateTokens[0]).toBe(regenerateTokens[1]);
  const replaced = (await (await page.request.get(`/api/v1/meeting-analyses/${nextAnalysis.id}`)).json()).data;
  expect(replaced.suggestion.status).toBe('SUPERSEDED');
  expect(replaced.suggestion.replacement_analysis_id).not.toBe(nextAnalysis.id);
  await regenerate.getByRole('button', { name: '查看新草稿' }).click();
  await expect(page.getByRole('region', { name: '受控执行' }).getByRole('checkbox', { name: '追加备注 NOTE' })).not.toBeChecked();
  const history = (await (await page.request.get(`/api/v1/opportunities/${opportunity.id}/meeting-analyses`)).json()).page;
  expect(history.total).toBe(3); // Original, explicitly submitted, and one replacement only.
  expect((await (await page.request.get(`/api/v1/opportunities/${opportunity.id}`)).json()).data.version).toBe(2);
  expect(keys).toHaveLength(2);
  await page.screenshot({ path: testInfo.outputPath('regenerated-draft-once.png'), fullPage: true });
});
test('administrator previews retention without exposing a cleanup action', async ({ page }, testInfo) => {
  await login(page, 'ADMIN');
  await page.getByRole('button', { name: '保留预览 Q10', exact: true }).click();
  await page.getByRole('button', { name: '生成只读预览' }).click();
  await expect(page.getByText(/预览时间：.*写操作：禁用/)).toBeVisible();
  await expect(page.getByRole('cell', { name: '纪要原文及引文', exact: true })).toBeVisible();
  expect(await page.getByRole('button', { name: /执行清理|确认删除|执行归档/ }).count()).toBe(0);
  await page.screenshot({ path: testInfo.outputPath('retention-preview-only.png'), fullPage: true });
});
