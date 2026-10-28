import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { AccountForm, ContactForm, CRMWorkspace, accountSchema, contactSchema, type Account } from './crm';
import { ApiError, type SessionData } from './api';
import * as api from './api';
import App from './App';

const session: SessionData = { user: { id: '10000000-0000-4000-8000-000000000001',
  name: 'Synthetic Rep', email: 'rep@example.test', role: 'SALES_REP', is_active: true }, csrf_token: 'test' };
const account: Account = { id: '20000000-0000-4000-8000-000000000001', name: 'Synthetic Account',
  owner_id: session.user.id, owner: { id: session.user.id, name: session.user.name },
  version: 1, is_active: true, industry: null, website: null, company_size: null, description: null };

interface ValidationCase { value: string | null; valid: boolean }
const cases = JSON.parse(readFileSync(resolve(process.cwd(), '../tests/fixtures/crm-validation.json'), 'utf8')) as {
  websites: ValidationCase[]; emails: ValidationCase[];
};

describe('shared CRM validation profile', () => {
  it.each(cases.websites)('website $value => $valid', ({ value, valid }) => {
    expect(accountSchema.safeParse({ name: 'Synthetic', website: value ?? '', industry: '',
      company_size: '', description: '', owner_id: '' }).success).toBe(valid);
  });
  it.each(cases.emails)('email $value => $valid', ({ value, valid }) => {
    expect(contactSchema.safeParse({ name: 'Synthetic', email: value ?? '', title: '',
      phone: '', decision_role: 'UNKNOWN' }).success).toBe(valid);
  });
});

describe('M2-A CRM forms', () => {
  it('opens account details through the authenticated application router', async () => {
    vi.spyOn(api.authApi, 'me').mockResolvedValue(session);
    vi.spyOn(api, 'request').mockImplementation(async path => path.includes('/contacts?')
      ? { data: [], page: { number: 1, size: 20, total: 0 } } : account);
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter
      initialEntries={[`/accounts/${account.id}`]}><App /></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByRole('heading', { name: account.name })).toBeInTheDocument();
    expect(screen.getByText('M2-A / CRM')).toBeInTheDocument();
  });
  it('rejects blank account name without a write', async () => {
    const request = vi.spyOn(api, 'request');
    render(<AccountForm session={session} onCancel={vi.fn()} onSaved={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '保存客户' }));
    expect(await screen.findByText('请输入客户名称。')).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });
  it('posts a real account request and only reports server success', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue(account);
    const saved = vi.fn();
    render(<AccountForm session={session} onCancel={vi.fn()} onSaved={saved} />);
    await userEvent.type(screen.getByLabelText('客户名称'), 'Synthetic Account');
    await userEvent.click(screen.getByRole('button', { name: '保存客户' }));
    expect(request).toHaveBeenCalledWith('/api/v1/accounts', expect.objectContaining({ method: 'POST' }));
    expect(saved).toHaveBeenCalledWith(account);
    const body = JSON.parse(request.mock.calls[0][1]?.body as string);
    expect(body.owner_id).toBeUndefined();
  });
  it('preserves input and original version on conflict, including background refresh', async () => {
    const request = vi.spyOn(api, 'request').mockRejectedValue(new ApiError(409, 'VERSION_CONFLICT', 'conflict'));
    const saved = vi.fn();
    const view = render(<AccountForm session={session} initial={account} onCancel={vi.fn()} onSaved={saved} />);
    await userEvent.clear(screen.getByLabelText('客户名称'));
    await userEvent.type(screen.getByLabelText('客户名称'), 'Unsaved input');
    view.rerender(<AccountForm session={session} initial={{ ...account, version: 2 }}
      onCancel={vi.fn()} onSaved={saved} />);
    await userEvent.click(screen.getByRole('button', { name: '保存客户' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('数据已被其他用户更新');
    expect(screen.getByLabelText('客户名称')).toHaveValue('Unsaved input');
    expect(JSON.parse(request.mock.calls[0][1]?.body as string).expected_version).toBe(1);
    expect(request).toHaveBeenCalledTimes(1);
    expect(saved).not.toHaveBeenCalled();
  });
  it('validates contact email and displays rejected server permissions', async () => {
    const request = vi.spyOn(api, 'request').mockRejectedValue(new ApiError(403, 'FORBIDDEN', '没有写入权限'));
    const saved = vi.fn();
    render(<ContactForm accountId={account.id} onCancel={vi.fn()} onSaved={saved} />);
    await userEvent.type(screen.getByLabelText('联系人姓名'), 'Synthetic Contact');
    await userEvent.type(screen.getByLabelText('联系人邮箱'), 'invalid');
    await userEvent.click(screen.getByRole('button', { name: '保存联系人' }));
    expect(await screen.findByText('请输入有效联系人邮箱。')).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
    await userEvent.clear(screen.getByLabelText('联系人邮箱'));
    await userEvent.click(screen.getByRole('button', { name: '保存联系人' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('没有写入权限');
    expect(saved).not.toHaveBeenCalled();
    expect(request).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '保存联系人' })).toBeEnabled();
  });
  it('refreshes account contacts from the server after a successful create', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const request = vi.spyOn(api, 'request').mockImplementation(async path => {
      if (path.endsWith('/contacts?page=1')) return { data: [], page: { number: 1, size: 20, total: 0 } };
      if (path === '/api/v1/contacts') return { id: 'new-contact' };
      return account;
    });
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[`/accounts/${account.id}`]}>
      <CRMWorkspace session={session} /></MemoryRouter></QueryClientProvider>);
    await screen.findByRole('heading', { name: account.name });
    await userEvent.click(screen.getByRole('button', { name: '创建联系人' }));
    await userEvent.type(screen.getByLabelText('联系人姓名'), 'Synthetic Contact');
    await userEvent.click(screen.getByRole('button', { name: '保存联系人' }));
    expect(await screen.findByText('联系人已保存并从服务端刷新。')).toBeInTheDocument();
    expect(request.mock.calls.filter(([path]) => path.endsWith('/contacts?page=1')).length).toBeGreaterThan(1);
  });
  it('keeps a committed contact locked when its refresh callback fails', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue({ id: 'created-contact' });
    const onSaved = vi.fn().mockRejectedValue(new Error('Synthetic read failure'));
    render(<ContactForm accountId={account.id} onSaved={onSaved} onCancel={vi.fn()} />);
    await userEvent.type(screen.getByLabelText('联系人姓名'), 'Synthetic Contact');
    await userEvent.click(screen.getByRole('button', { name: '保存联系人' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('联系人已保存，但后续刷新失败');
    const save = screen.getByRole('button', { name: '保存联系人' });
    expect(save).toBeDisabled();
    await userEvent.click(save);
    // Even a second submit event must not issue a second write.
    await act(async () => { fireEvent.submit(save.closest('form')!); });
    expect(request).toHaveBeenCalledTimes(1);
    expect(onSaved).toHaveBeenCalledTimes(1);
  });
  it('lets a user clear a legacy invalid website before saving the account', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue(account);
    render(<AccountForm session={session} initial={{ ...account, website: 'https://example.test:bogus' }}
      onSaved={vi.fn()} onCancel={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '保存客户' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('端口有效');
    expect(request).not.toHaveBeenCalled();
    await userEvent.clear(screen.getByLabelText('网站'));
    await userEvent.click(screen.getByRole('button', { name: '保存客户' }));
    expect(request).toHaveBeenCalledTimes(1);
    expect(JSON.parse(request.mock.calls[0][1]?.body as string).website).toBeNull();
  });
  it('lets a user correct a legacy invalid contact email before saving', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue({ id: 'existing-contact' });
    render(<ContactForm accountId={account.id} initial={{ id: 'existing-contact', account_id: account.id,
      name: 'Synthetic', email: 'person@a..example.test', phone: null, title: null,
      decision_role: 'UNKNOWN', is_active: true, version: 1 }} onSaved={vi.fn()} onCancel={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '保存联系人' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('有效联系人邮箱');
    expect(request).not.toHaveBeenCalled();
    await userEvent.clear(screen.getByLabelText('联系人邮箱'));
    await userEvent.type(screen.getByLabelText('联系人邮箱'), 'corrected@example.test');
    await userEvent.click(screen.getByRole('button', { name: '保存联系人' }));
    expect(request).toHaveBeenCalledTimes(1);
    expect(JSON.parse(request.mock.calls[0][1]?.body as string).email).toBe('corrected@example.test');
  });
  it.each(['contacts', 'account'])('reports POST success and retries only reads after %s refresh failure', async failedResource => {
    let created = false, failReads = true;
    const request = vi.spyOn(api, 'request').mockImplementation(async (path, options) => {
      if (path === '/api/v1/contacts' && options?.method === 'POST') {
        created = true;
        return { id: 'created-contact' };
      }
      if (path.endsWith('/contacts?page=1')) {
        if (created && failReads && failedResource === 'contacts') {
          throw new ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Synthetic read failure');
        }
        return { data: [], page: { number: 1, size: 20, total: 0 } };
      }
      if (created && failReads && failedResource === 'account') {
        throw new ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Synthetic read failure');
      }
      return account;
    });
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[`/accounts/${account.id}`]}><CRMWorkspace session={session} /></MemoryRouter>
    </QueryClientProvider>);
    await screen.findByRole('heading', { name: account.name });
    await userEvent.click(screen.getByRole('button', { name: '创建联系人' }));
    await userEvent.type(screen.getByLabelText('联系人姓名'), 'Synthetic Contact');
    await userEvent.click(screen.getByRole('button', { name: '保存联系人' }));
    expect(await screen.findByText('联系人已保存，但列表刷新失败。请仅重试刷新，不要重复创建。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '保存联系人' })).not.toBeInTheDocument();
    const postCount = () => request.mock.calls.filter(([, options]) => options?.method === 'POST').length;
    expect(postCount()).toBe(1);
    await userEvent.click(screen.getByRole('button', { name: '重试刷新' }));
    expect(postCount()).toBe(1);
    failReads = false;
    await userEvent.click(screen.getByRole('button', { name: '重试刷新' }));
    expect(await screen.findByText('联系人已保存并从服务端刷新。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重试刷新' })).not.toBeInTheDocument();
    expect(postCount()).toBe(1);
  });
  it('shows a read-only account to non-owners without edit controls', async () => {
    vi.spyOn(api, 'request').mockImplementation(async path => path.includes('/contacts?')
      ? { data: [], page: { number: 1, size: 20, total: 0 } } : account);
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter
      initialEntries={[`/accounts/${account.id}`]}><CRMWorkspace session={{ ...session,
        user: { ...session.user, id: 'other-rep' } }} /></MemoryRouter></QueryClientProvider>);
    await screen.findByRole('heading', { name: account.name });
    expect(screen.queryByRole('button', { name: '编辑客户' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '创建联系人' })).not.toBeInTheDocument();
  });
});
