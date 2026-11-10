import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import * as api from './api';
import { AccountLinkPanel, DiscoveryWorkspace, profileSchema } from './discovery';

const lead = { id: 'lead', buyer_name: 'Synthetic hospital', project_name: 'Synthetic project', notice_type: 'INTENT', status: 'QUALIFIED', version: 3, account_id: null, summary_only: false };
const accepted = { account_id: 'account', result_version: 4 };
function wrap(child: React.ReactNode, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return <QueryClientProvider client={client}><MemoryRouter>{child}</MemoryRouter></QueryClientProvider>;
}
async function preview() {
  await userEvent.click(screen.getByRole('button', { name: '预览客户关联' }));
  await screen.findByText(/确认客户/);
  await userEvent.click(screen.getByLabelText('我确认将审核后的客户基础字段加入全企业CRM'));
}

describe('discovery intake', () => {
  it('validates a usable sales profile without inventing terms', () => {
    expect(profileSchema.safeParse({ name: 'Synthetic', product: 'Ultrasound', keywords: '超声，设备', regions: '', visibility: 'PRIVATE' }).success).toBe(true);
    expect(profileSchema.safeParse({ name: ' ', product: 'Synthetic', keywords: '', regions: '', visibility: 'PRIVATE' }).success).toBe(false);
  });
  it('READ_ONLY reads only shared leads and offers no upload, profile or paid-search action', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue({ data: [], page: { total: 0 } });
    render(wrap(<DiscoveryWorkspace session={{ user: { id: 'reader', name: 'Reader', email: 'reader@example.test', role: 'READ_ONLY', is_active: true }, csrf_token: 'synthetic' }} />));
    await screen.findByText(/暂无可见线索/);
    expect(screen.queryByRole('button', { name: '创建画像' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('资料正文')).not.toBeInTheDocument();
    expect(request.mock.calls.every(([path]) => path.startsWith('/api/v1/discovery/leads?'))).toBe(true);
  });
  it('separates user/role caches when the signed-in identity changes', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue({ data: [lead], page: { total: 1 } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const session: api.SessionData = { user: { id: 'reader-one', name: 'Reader', email: 'reader@example.test', role: 'READ_ONLY', is_active: true }, csrf_token: 'synthetic' };
    const { rerender } = render(wrap(<DiscoveryWorkspace session={session} />, client));
    await screen.findByRole('button', { name: /Synthetic hospital/ });
    request.mockResolvedValue({ data: [], page: { total: 0 } });
    rerender(wrap(<DiscoveryWorkspace session={{ ...session, user: { ...session.user, id: 'reader-two' } }} />, client));
    expect(screen.queryByRole('button', { name: /Synthetic hospital/ })).not.toBeInTheDocument();
    await screen.findByText(/暂无可见线索/);
  });
  it('keeps the same preview, key and payload after a lost account-link response', async () => {
    let posts = 0;
    const request = vi.spyOn(api, 'request').mockImplementation(async (path, options) => {
      if (path.includes('account-preview')) return { preview_hash: 'a'.repeat(64), account_name: 'Synthetic hospital', notice: 'Shared CRM' };
      if (options?.method === 'POST') { if (++posts === 1) throw new api.ApiError(0, 'NETWORK_ERROR', 'Synthetic response lost'); return accepted; }
      return { data: [], page: { total: 0 } };
    });
    const saved = vi.fn(); render(wrap(<AccountLinkPanel lead={lead} onSaved={saved} />));
    expect(screen.queryByRole('button', { name: '确认建立客户关联' })).not.toBeInTheDocument();
    await preview();
    await userEvent.click(screen.getByRole('button', { name: '确认建立客户关联' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic response lost');
    await userEvent.click(screen.getByRole('button', { name: '确认建立客户关联' }));
    expect(await screen.findByRole('status')).toHaveTextContent('客户关联已成功');
    const calls = request.mock.calls.filter(([path]) => path.endsWith('/link-account'));
    expect(calls).toHaveLength(2); expect(calls[0][1]).toEqual(calls[1][1]); expect(saved).toHaveBeenCalledTimes(1);
  });
  it('does not repeat a committed account link when subsequent UI refresh fails', async () => {
    const request = vi.spyOn(api, 'request').mockImplementation(async (path, options) => path.includes('account-preview') ? { preview_hash: 'b'.repeat(64), account_name: 'Synthetic hospital', notice: 'Shared CRM' } : options?.method === 'POST' ? accepted : { data: [], page: { total: 0 } });
    render(wrap(<AccountLinkPanel lead={lead} onSaved={() => { throw new Error('Synthetic refresh failure'); }} />));
    await preview(); await userEvent.click(screen.getByRole('button', { name: '确认建立客户关联' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('客户已关联');
    expect(screen.getByRole('button', { name: '确认建立客户关联' })).toBeDisabled();
    expect(request.mock.calls.filter(([path]) => path.endsWith('/link-account'))).toHaveLength(1);
  });
  it('keeps user input after a stale preview conflict and never silently adopts a new version', async () => {
    vi.spyOn(api, 'request').mockImplementation(async path => {
      if (path.includes('account-preview')) throw new api.ApiError(409, 'VERSION_CONFLICT', 'Synthetic lead changed');
      return { data: [], page: { total: 0 } };
    });
    render(wrap(<AccountLinkPanel lead={lead} onSaved={vi.fn()} />));
    await userEvent.clear(screen.getByLabelText('新建客户名称'));
    await userEvent.type(screen.getByLabelText('新建客户名称'), 'Synthetic unsaved hospital');
    await userEvent.click(screen.getByRole('button', { name: '预览客户关联' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic lead changed');
    expect(screen.getByLabelText('新建客户名称')).toHaveValue('Synthetic unsaved hospital');
    expect(screen.queryByRole('button', { name: '确认建立客户关联' })).not.toBeInTheDocument();
  });
});
