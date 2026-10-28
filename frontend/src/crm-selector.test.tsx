import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from './api';
import { OpportunityForm } from './sales';

const id = (i: number) => `00000000-0000-4000-8000-${String(i).padStart(12, '0')}`;
const accounts = Array.from({ length: 125 }, (_, i) => ({ id: id(i + 1), name: `Synthetic client ${String(i + 1).padStart(3, '0')}` }));
const contacts = Array.from({ length: 125 }, (_, i) => ({ id: id(201 + i), name: `Synthetic contact ${String(i + 1).padStart(3, '0')}`, account_id: id(125) }));
let writes: { path: string; body: Record<string, unknown> }[];
beforeEach(() => {
  writes = [];
  vi.spyOn(api, 'request').mockImplementation(async (path, options = {}) => {
    if (options.method === 'POST' || options.method === 'PATCH') {
      writes.push({ path, body: JSON.parse(String(options.body)) }); return { id: id(900) };
    }
    const url = new URL(path, 'http://synthetic.test');
    const match = url.pathname.match(/^\/api\/v1\/(accounts|contacts)\/([^/]+)$/);
    if (match) return [...accounts, ...contacts].find(item => item.id === match[2]);
    const isContact = url.pathname.endsWith('/contacts');
    const q = url.searchParams.get('q') || '';
    if (q === 'fail') throw new api.ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Synthetic unavailable');
    const rows = (isContact ? (url.pathname.includes(id(125)) ? contacts : []) : accounts).filter(item => item.name.includes(q));
    const page = Number(url.searchParams.get('page') || 1), size = Number(url.searchParams.get('page_size') || 25);
    return { data: rows.slice((page - 1) * size, page * size), page: { number: page, size, total: rows.length } };
  });
});
function setup(initial?: Parameters<typeof OpportunityForm>[0]['initial']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><OpportunityForm initial={initial} onDone={vi.fn()} /></QueryClientProvider>);
  return { client, ...view };
}
async function fifthPage(kind: string) {
  for (let i = 0; i < 4; i++) {
    await waitFor(() => expect(screen.getByRole('button', { name: `${kind}下一页` })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: `${kind}下一页` }));
    await screen.findByText(new RegExp(`${kind}第 ${i + 2} 页`));
  }
}
describe('complete CRM selectors', () => {
  it('selects and submits objects after the first 100 accounts and associated contacts', async () => {
    setup(); await userEvent.type(screen.getByLabelText('商机名称'), 'Synthetic later deal');
    await fifthPage('客户');
    await userEvent.selectOptions(screen.getByLabelText('客户企业'), id(125));
    await fifthPage('联系人');
    await userEvent.selectOptions(screen.getByLabelText('主要联系人'), id(325));
    await userEvent.click(screen.getByRole('button', { name: '保存商机' }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body).toMatchObject({ account_id: id(125), primary_contact_id: id(325) });
  });
  it('keeps selected details outside results, original edit version and unsaved input through search/refetch', async () => {
    const initial = { id: id(900), name: 'Initial', account_id: id(125), owner_id: id(1), stage: 'PROPOSAL_SUBMITTED', amount: null, currency: 'CNY', weighted_amount: null, actual_amount: null, actual_currency: null, probability: 20, priority: 'MEDIUM', source: 'UNKNOWN', primary_contact_id: id(325), expected_close_date: null, version: 7, is_archived: false, account: { name: accounts[124].name }, owner: { name: 'Synthetic' } };
    const { client, rerender } = setup(initial);
    await screen.findByRole('option', { name: contacts[124].name });
    expect(screen.getByLabelText('主要联系人')).toHaveValue(id(325));
    await userEvent.clear(screen.getByLabelText('商机名称')); await userEvent.type(screen.getByLabelText('商机名称'), 'Unsaved input');
    await userEvent.type(screen.getByLabelText('搜索联系人'), '001');
    await screen.findByRole('option', { name: contacts[0].name });
    expect(screen.getByLabelText('主要联系人')).toHaveValue(id(325));
    await act(async () => { await client.invalidateQueries({ queryKey: ['crm-selector'] }); });
    rerender(<QueryClientProvider client={client}><OpportunityForm initial={{ ...initial, version: 8, name: 'Server changed' }} onDone={vi.fn()} /></QueryClientProvider>);
    expect(screen.getByLabelText('商机名称')).toHaveValue('Unsaved input');
    await userEvent.click(screen.getByRole('button', { name: '保存商机' }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body).toMatchObject({ expected_version: 7, name: 'Unsaved input', primary_contact_id: id(325) });
  });
  it('searches on the server, clears the contact when the account changes, and distinguishes errors from empty results', async () => {
    setup(); await userEvent.type(screen.getByLabelText('搜索客户'), '125');
    await screen.findByRole('option', { name: accounts[124].name });
    await userEvent.selectOptions(screen.getByLabelText('客户企业'), id(125));
    await screen.findByRole('option', { name: contacts[0].name });
    await userEvent.selectOptions(screen.getByLabelText('主要联系人'), id(201));
    await userEvent.clear(screen.getByLabelText('搜索客户')); await userEvent.type(screen.getByLabelText('搜索客户'), '124');
    await screen.findByRole('option', { name: accounts[123].name });
    await userEvent.selectOptions(screen.getByLabelText('客户企业'), id(124));
    expect(screen.getByLabelText('主要联系人')).toHaveValue('');
    await screen.findByText('没有匹配的联系人。');
    await userEvent.clear(screen.getByLabelText('搜索客户')); await userEvent.type(screen.getByLabelText('搜索客户'), 'fail');
    expect(await screen.findByRole('alert')).toHaveTextContent('客户查询失败');
    expect(screen.queryByText('没有匹配的客户。')).not.toBeInTheDocument();
    expect(writes).toHaveLength(0);
  });
});
