import { test, expect, type Page } from '@playwright/test';

const users = JSON.parse(process.env.M2_BROWSER_USERS || '{}') as Record<string, { id: string; email: string }>;
test.beforeEach(() => {
  test.skip(!process.env.E2E_SALES || !process.env.M2_BROWSER_USERS || !process.env.E2E_PASSWORD,
    'Requires explicitly isolated M2 API/MySQL/MinIO acceptance environment');
});

async function login(page: Page, role = 'SALES_MANAGER') {
  await page.goto('/login');
  await page.getByLabel('邮箱').fill(users[role].email);
  await page.getByLabel('密码').fill(process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await expect(page.getByRole('heading', { name: '工作空间概览' })).toBeVisible();
}

async function write(page: Page, path: string, body: object) {
  const me = await page.request.get('/api/v1/auth/me');
  const csrf = (await me.json()).data.csrf_token;
  const response = await page.request.post('/api/v1' + path, {
    headers: { Origin: process.env.E2E_BASE_URL!, 'X-CSRF-Token': csrf, 'Idempotency-Key': crypto.randomUUID() }, data: body,
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).data;
}

async function create(page: Page) {
  const account = await write(page, '/accounts', { name: `E2E isolated ${Date.now()}` });
  return write(page, '/opportunities', { name: `E2E negative ${Date.now()}`, account_id: account.id, amount: '250000.00' });
}

test('selects and persists customers and associated contacts beyond 100 records', async ({ page }, testInfo) => {
  test.setTimeout(120000);
  await login(page);
  const prefix = `Selector-${crypto.randomUUID().slice(0, 8)}`;
  let account: { id: string; name: string } = { id: '', name: '' };
  for (let index = 1; index <= 125; index++) {
    account = await write(page, '/accounts', { name: `${prefix} account ${String(index).padStart(3, '0')}` });
  }
  let contact: { id: string; name: string } = { id: '', name: '' };
  for (let index = 1; index <= 125; index++) {
    contact = await write(page, '/contacts', { account_id: account.id, name: `${prefix} contact ${String(index).padStart(3, '0')}` });
  }
  await page.goto('/opportunities');
  await page.getByRole('button', { name: '创建商机', exact: true }).click();
  const deal = `${prefix} persisted deal`;
  await page.getByLabel('商机名称').fill(deal);
  await page.getByLabel('搜索客户').fill(prefix);
  for (let index = 2; index <= 5; index++) {
    await page.getByRole('button', { name: '客户下一页', exact: true }).click();
    await expect(page.getByText(`客户第 ${index} 页 · 共 125 条`, { exact: true })).toBeVisible();
  }
  await page.getByLabel('客户企业').selectOption(account.id);
  for (let index = 2; index <= 5; index++) {
    await page.getByRole('button', { name: '联系人下一页', exact: true }).click();
    await expect(page.getByText(`联系人第 ${index} 页 · 共 125 条`, { exact: true })).toBeVisible();
  }
  await page.getByLabel('主要联系人').selectOption(contact.id);
  await page.getByRole('button', { name: '保存商机', exact: true }).click();
  await expect(page.getByRole('heading', { name: deal })).toBeVisible();
  const saved = (await (await page.request.get(`/api/v1/opportunities/${page.url().split('/').pop()}`)).json()).data;
  expect(saved.account_id).toBe(account.id); expect(saved.primary_contact_id).toBe(contact.id);
  await page.getByRole('button', { name: '编辑商机', exact: true }).click();
  await expect(page.getByLabel('客户企业')).toHaveValue(account.id);
  await expect(page.getByLabel('主要联系人')).toHaveValue(contact.id);
  await expect(page.getByLabel('主要联系人').locator('option:checked')).toHaveText(contact.name);
  await page.getByLabel('搜索联系人').fill('not-a-matching-synthetic-name');
  await expect(page.getByText('没有匹配的联系人。', { exact: true })).toBeVisible();
  await expect(page.getByLabel('主要联系人')).toHaveValue(contact.id);
  await page.screenshot({ path: testInfo.outputPath('selector-beyond-100.png'), fullPage: true });
});

test('two real pages reject stale editing and retain unsaved input', async ({ page, context }) => {
  await login(page);
  const opportunity = await create(page);
  await page.goto(`/opportunities/${opportunity.id}`);
  const second = await context.newPage();
  await second.goto(`/opportunities/${opportunity.id}`);
  for (const p of [page, second]) await p.getByRole('button', { name: '编辑商机', exact: true }).click();
  await page.getByLabel('商机名称').fill('E2E first persisted');
  await second.getByLabel('商机名称').fill('E2E second unsaved');
  await page.getByRole('button', { name: '保存商机', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'E2E first persisted' })).toBeVisible();
  const conflict = second.waitForResponse(r => r.request().method() === 'PATCH' && r.url().endsWith(`/opportunities/${opportunity.id}`));
  await second.getByRole('button', { name: '保存商机', exact: true }).click();
  expect((await conflict).status()).toBe(409);
  await expect(second.getByLabel('商机名称')).toHaveValue('E2E second unsaved');
  await expect(second.getByRole('alert')).toContainText('当前输入已保留');
  const saved = (await (await page.request.get(`/api/v1/opportunities/${opportunity.id}`)).json()).data;
  expect(saved.name).toBe('E2E first persisted');
  expect(saved.version).toBe(2);
});

test('real NGINX PDF upload is independently reviewed and selected for WON', async ({ page, browser }) => {
  test.skip(!process.env.M2_BROWSER_PDF, 'Requires synthetic PDF generated by this acceptance run');
  await login(page);
  const opportunity = await create(page);
  await write(page, `/opportunities/${opportunity.id}/transitions`, {
    expected_version: 1, target_stage: 'NEGOTIATION', reason: 'Synthetic browser negotiation',
  });
  await page.goto(`/opportunities/${opportunity.id}`);
  await page.getByLabel('PDF原件（≤20 MiB / ≤100页）').setInputFiles(process.env.M2_BROWSER_PDF!);
  await page.getByLabel('合同/PO编号').fill('SYNTHETIC-E2E');
  await page.getByLabel('客户法律主体').fill('Synthetic legal entity');
  await page.getByLabel('文档日期').fill('2026-10-27');
  await page.getByLabel('实际金额（CNY）').fill('230000.00');
  const upload = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/evidence-files'));
  await page.getByRole('button', { name: '上传并提交待核验证据' }).click();
  expect((await upload).status()).toBe(201);
  await expect(page.getByText('请由另一位有权限的经理或管理员核验。', { exact: true })).toBeVisible();
  const reviewerContext = await browser.newContext({ baseURL: process.env.E2E_BASE_URL });
  try {
    const reviewer = await reviewerContext.newPage();
    await login(reviewer, 'ADMIN');
    await reviewer.goto(`/opportunities/${opportunity.id}`);
    await reviewer.getByLabel('核验说明').fill('Synthetic independent reviewer checked original');
    await reviewer.getByRole('button', { name: '核验通过', exact: true }).click();
    await expect(reviewer.getByText('Synthetic independent reviewer checked original', { exact: true })).toBeVisible();
    await page.reload();
    await page.getByLabel('目标阶段').selectOption('WON');
    await page.getByLabel('选定已核验成交依据').selectOption({ index: 1 });
    await page.getByLabel('操作原因', { exact: true }).fill('Synthetic reviewed close');
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: '确认阶段变更' }).click();
    await expect(page.getByRole('heading', { name: '实际成交 CNY 230000.00' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '预计 CNY 250000.00' })).toBeVisible();
    await expect(page.getByRole('button', { name: '编辑商机', exact: true })).toHaveCount(0);
  } finally { await reviewerContext.close(); }
});

test('lost response retries the same real command without a second mutation', async ({ page }) => {
  await login(page);
  const opportunity = await create(page);
  await page.goto(`/opportunities/${opportunity.id}`);
  await page.getByLabel('目标阶段').selectOption('NEGOTIATION');
  await page.getByLabel('操作原因', { exact: true }).fill('Synthetic lost response retry');
  const keys: string[] = [];
  let first = true;
  await page.route(`**/api/v1/opportunities/${opportunity.id}/transitions`, async route => {
    keys.push(route.request().headers()['idempotency-key']);
    if (first) {
      first = false;
      const response = await route.fetch(); // Real server commits before its response is discarded.
      expect(response.status()).toBe(200);
      await route.abort('failed');
    } else { await route.continue(); }
  });
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '确认阶段变更' }).click();
  await expect(page.getByRole('alert')).toContainText('无法连接服务');
  await page.getByRole('button', { name: '确认阶段变更' }).click();
  await expect(page.getByText('谈判中 · 60%', { exact: true })).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  const saved = (await (await page.request.get(`/api/v1/opportunities/${opportunity.id}`)).json()).data;
  expect(saved.version).toBe(2);
  const history = await (await page.request.get(`/api/v1/opportunities/${opportunity.id}/history`)).json();
  expect(history.page.total).toBe(2);
});
