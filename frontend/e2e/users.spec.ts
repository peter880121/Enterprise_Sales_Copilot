import { test, expect, type Page } from '@playwright/test';

const users = JSON.parse(process.env.M2_BROWSER_USERS || '{}') as Record<string, { id: string; email: string }>;
test.beforeEach(() => { test.skip(!process.env.E2E_SALES || !users.ADMIN || !process.env.E2E_PASSWORD, 'Requires explicit isolated M2.1 environment'); });

async function login(page: Page, email: string, password = process.env.E2E_PASSWORD!) {
  await page.goto('/login');
  await page.getByLabel('邮箱', { exact: true }).fill(email);
  await page.getByLabel('密码', { exact: true }).fill(password);
  await page.getByRole('button', { name: '进入工作空间' }).click();
  await expect(page.getByRole('heading', { name: '工作空间概览' })).toBeVisible();
}

test('registration approval, roles, password changes and logical deletion retain real history', async ({ page, browser }, testInfo) => {
  test.setTimeout(120000);
  const suffix = crypto.randomUUID().slice(0, 10), email = `browser-user-${suffix}@example.test`;
  const password = process.env.E2E_PASSWORD!, reset = password + '-reset', changed = password + '-changed';
  await page.goto('/login'); await page.getByRole('link', { name: '注册账号', exact: true }).click();
  await page.getByLabel('姓名', { exact: true }).fill(`Browser registrant ${suffix}`);
  await page.getByLabel('注册邮箱', { exact: true }).fill(email);
  await page.getByLabel('注册密码', { exact: true }).fill(password);
  await page.getByLabel('确认注册密码', { exact: true }).fill(password);
  await page.getByRole('button', { name: '提交注册申请' }).click();
  await expect(page.getByRole('heading', { name: '注册申请已提交' })).toBeVisible();
  expect((await page.request.get('/api/v1/accounts')).status()).toBe(401);
  await page.getByRole('link', { name: '前往登录' }).click();
  await page.getByLabel('邮箱', { exact: true }).fill(email); await page.getByLabel('密码', { exact: true }).fill(password);
  const rejected = page.waitForResponse(r => r.url().endsWith('/auth/login') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '进入工作空间' }).click(); expect((await rejected).status()).toBe(401);
  const adminContext = await browser.newContext({ baseURL: process.env.E2E_BASE_URL });
  try {
    const admin = await adminContext.newPage();
    admin.on('dialog', dialog => dialog.accept());
    await login(admin, users.ADMIN.email);
    await admin.getByRole('button', { name: '用户管理 M2.1', exact: true }).click();
    await admin.getByLabel('搜索用户').fill(email);
    await admin.getByLabel('状态筛选').selectOption('PENDING');
    await admin.getByRole('link', { name: '用户详情', exact: true }).click();
    const id = admin.url().split('/').pop()!;
    await expect(admin.getByText(/待批准 · 版本 1/)).toBeVisible();
    await admin.getByRole('button', { name: '批准注册', exact: true }).click();
    await admin.getByLabel('批准后角色').selectOption('SALES_REP');
    await admin.getByLabel('操作原因').fill('Synthetic reviewed registration');
    await admin.getByRole('button', { name: '确认批准注册', exact: true }).click();
    await expect(admin.getByText(/正常 · 版本 2/)).toBeVisible();
    await login(page, email);
    expect((await page.request.get('/api/v1/users')).status()).toBe(403);
    await expect(page.getByRole('button', { name: '用户管理 M2.1', exact: true })).toHaveCount(0);
    const me = (await (await page.request.get('/api/v1/auth/me')).json()).data;
    const owned = await page.request.post('/api/v1/accounts', { headers: { Origin: process.env.E2E_BASE_URL!, 'X-CSRF-Token': me.csrf_token }, data: { name: `Retained browser ownership ${suffix}` } });
    expect(owned.status()).toBe(201); const accountId = (await owned.json()).data.id;
    await admin.getByRole('button', { name: '编辑用户', exact: true }).click();
    await admin.getByLabel('分配角色').selectOption('READ_ONLY');
    await admin.getByLabel('修改原因').fill('Synthetic restrict write access');
    await admin.getByRole('button', { name: '保存用户修改', exact: true }).click();
    await expect(admin.getByText(/只读用户 · 正常 · 版本 3/)).toBeVisible();
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401);
    await login(page, email);
    const readOnlyMe = (await (await page.request.get('/api/v1/auth/me')).json()).data;
    expect((await page.request.post('/api/v1/accounts', { headers: { Origin: process.env.E2E_BASE_URL!, 'X-CSRF-Token': readOnlyMe.csrf_token }, data: { name: 'Must be denied' } })).status()).toBe(403);
    for (const label of ['停用用户', '启用用户']) {
      await admin.getByRole('button', { name: label, exact: true }).click();
      await admin.getByLabel('操作原因').fill('Synthetic lifecycle ' + label);
      await admin.getByRole('button', { name: '确认' + label, exact: true }).click();
      await expect(admin.getByRole('button', { name: label === '停用用户' ? '启用用户' : '停用用户', exact: true })).toBeVisible();
    }
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401);
    await admin.getByRole('button', { name: '重置密码', exact: true }).click();
    await admin.getByLabel('操作原因').fill('Synthetic reset after request loss');
    await admin.getByLabel('新密码', { exact: true }).fill(reset); await admin.getByLabel('确认新密码', { exact: true }).fill(reset);
    let lost = true; const keys: string[] = [];
    await admin.route(`**/api/v1/users/${id}/reset-password`, async route => {
      keys.push(route.request().headers()['idempotency-key']);
      if (lost) { lost = false; expect((await route.fetch()).status()).toBe(200); await route.abort('failed'); }
      else await route.continue();
    });
    await admin.getByRole('button', { name: '确认重置密码', exact: true }).click();
    await expect(admin.getByRole('alert')).toContainText('无法连接服务');
    await admin.getByRole('button', { name: '确认重置密码', exact: true }).click();
    await expect(admin.getByText(/正常 · 版本 6/)).toBeVisible();
    expect(keys).toHaveLength(2); expect(keys[0]).toBe(keys[1]);
    await login(page, email, reset);
    await page.getByRole('button', { name: '个人账号 M2.1', exact: true }).click();
    await page.getByLabel('验证当前密码').fill(reset); await page.getByLabel('个人姓名').fill(`Updated registrant ${suffix}`);
    await page.getByRole('button', { name: '保存个人资料', exact: true }).click();
    await expect(page.getByRole('heading', { name: '登录工作空间' })).toBeVisible();
    await login(page, email, reset);
    await page.getByRole('button', { name: '个人账号 M2.1', exact: true }).click();
    await page.getByLabel('验证当前密码').fill(reset);
    await page.getByLabel('新的登录密码').fill(changed); await page.getByLabel('再次确认新密码').fill(changed);
    await page.getByRole('button', { name: '修改登录密码', exact: true }).click();
    await expect(page.getByRole('heading', { name: '登录工作空间' })).toBeVisible();
    await login(page, email, changed);
    await admin.reload();
    await expect(admin.getByRole('heading', { name: `Updated registrant ${suffix}`, exact: true })).toBeVisible();
    await admin.getByRole('button', { name: '删除用户', exact: true }).click(); await admin.getByLabel('操作原因').fill('Synthetic logical deletion');
    await admin.getByRole('button', { name: '确认删除用户', exact: true }).click();
    await expect(admin.getByRole('button', { name: '恢复用户', exact: true })).toBeVisible();
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401);
    expect((await (await admin.request.get(`/api/v1/accounts/${accountId}`)).json()).data.owner_id).toBe(id);
    await admin.getByRole('button', { name: '恢复用户', exact: true }).click(); await admin.getByLabel('操作原因').fill('Synthetic restoration');
    await admin.getByRole('button', { name: '确认恢复用户', exact: true }).click();
    await expect(admin.getByText(/正常 · 版本 10/)).toBeVisible();
    await login(page, email, changed);
    const history = (await (await admin.request.get(`/api/v1/users/${id}/history`)).json()).data;
    expect(history.filter((event: { action: string }) => event.action === 'USER_RESET_PASSWORD')).toHaveLength(1);
    expect(JSON.stringify(history)).not.toContain(password);
    await admin.screenshot({ path: testInfo.outputPath('user-lifecycle.png'), fullPage: true });
  } finally { await adminContext.close(); }
});

test('administrator creates an active user and views role permissions', async ({ page }, testInfo) => {
  await login(page, users.ADMIN.email);
  await page.getByRole('button', { name: '用户管理 M2.1', exact: true }).click();
  await page.getByText('角色与权限说明', { exact: true }).click();
  await expect(page.getByText('全企业 CRM 只读；不能写入或核验证据', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '创建用户', exact: true }).click();
  const suffix = crypto.randomUUID().slice(0, 8), name = `Created user ${suffix}`;
  await page.getByLabel('姓名', { exact: true }).fill(name); await page.getByLabel('用户邮箱').fill(`created-${suffix}@example.test`);
  await page.getByLabel('初始密码').fill(process.env.E2E_PASSWORD!);
  await page.getByLabel('用户角色').selectOption('SALES_MANAGER');
  await page.getByRole('button', { name: '保存新用户' }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  await expect(page.getByText(/销售经理 · 正常 · 版本 1/)).toBeVisible();
  await expect(page.getByText('USER_CREATED', { exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('admin-created-user.png'), fullPage: true });
});

test('administrator browses user audit beyond the first twenty records', async ({ page }, testInfo) => {
  test.setTimeout(120000);
  await login(page, users.ADMIN.email);
  const csrf = (await (await page.request.get('/api/v1/auth/me')).json()).data.csrf_token;
  const headers = { Origin: process.env.E2E_BASE_URL!, 'X-CSRF-Token': csrf };
  const suffix = crypto.randomUUID().slice(0, 8);
  const created = await page.request.post('/api/v1/users', { headers, data: {
    name: `Audit pages ${suffix}`, email: `audit-pages-${suffix}@example.test`, password: process.env.E2E_PASSWORD!, role: 'SALES_REP',
  } });
  expect(created.status()).toBe(201);
  let user = (await created.json()).data;
  for (let index = 0; index < 21; index++) {
    const response = await page.request.patch(`/api/v1/users/${user.id}`, { headers, data: {
      expected_version: user.version, name: `Audit pages ${suffix} change ${index}`, reason: `Synthetic audit page ${index}`,
    } });
    expect(response.status()).toBe(200); user = (await response.json()).data;
  }
  await page.goto(`/users/${user.id}`);
  const audit = page.getByRole('region', { name: '用户操作审计' });
  await expect(audit.getByText('审计第 1 页 · 共 22 条')).toBeVisible();
  await expect(audit.getByText(/USER_CREATED/)).toHaveCount(0);
  await audit.getByRole('button', { name: '审计下一页' }).click();
  await expect(audit.getByText('审计第 2 页 · 共 22 条')).toBeVisible();
  await expect(audit.getByText(/USER_CREATED/)).toBeVisible();
  await expect(audit.getByRole('button', { name: '审计下一页' })).toBeDisabled();
  await audit.getByText('查看字段变更').first().click();
  await expect(audit.getByRole('cell', { name: 'name', exact: true }).first()).toBeVisible();
  await expect(audit.getByText(users.ADMIN.id, { exact: false }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('user-audit-page-two.png'), fullPage: true });
});
