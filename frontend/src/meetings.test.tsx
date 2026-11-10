import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import * as api from './api';
import { AnalysisDetail, AnalysisHistory, Meetings } from './meetings';

const draft = { id: 'analysis', source_job_id: 'job', status: 'SUCCEEDED', mode: 'MOCK', input_text: '需求：合成报表', base_opportunity_version: 1,
  result: { facts: [{ topic: 'needs', kind: 'FACT', value: '合成报表', evidence: [{ start: 3, end: 7, quote: '合成报表' }] },
    { topic: 'budget', kind: 'UNKNOWN', value: null, evidence: [] }], proposed_changes: [] },
  suggestion: { id: 'suggestion', version: 2, status: 'DRAFT', effective_status: 'DRAFT', reason: null, expires_at: null } };
function wrap(content: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{content}</MemoryRouter></QueryClientProvider>;
}

describe('Mock meeting drafts', () => {
  it('only advances the submission baseline on an explicit read, preserving unsaved notes', async () => {
    let serverVersion = 1;
    const request = vi.spyOn(api, 'request').mockImplementation(async (path, options) => {
      if (options?.method === 'POST') return { resource_id: 'analysis' };
      if (path === '/api/v1/opportunities/opportunity') return { id: 'opportunity', name: 'Synthetic deal', version: serverVersion, stage: 'NEGOTIATION' };
      if (path.startsWith('/api/v1/opportunities?')) return { data: [{ id: 'opportunity', name: 'Synthetic deal', version: serverVersion, stage: 'NEGOTIATION' }], page: { total: 1 } };
      if (path.includes('/meeting-analyses?page=')) return { data: [], page: { total: 0 } };
      return path.includes('/jobs/') ? { status: 'SUCCEEDED', attempts: 1 } : draft;
    });
    const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={cache}><MemoryRouter><Meetings session={{ user: { id: 'manager', name: 'Synthetic', email: 'manager@example.test', role: 'SALES_MANAGER', is_active: true }, csrf_token: 'synthetic' }} /></MemoryRouter></QueryClientProvider>);
    await userEvent.click(await screen.findByRole('button', { name: '选择商机：Synthetic deal' }));
    await userEvent.type(screen.getByLabelText('合成会议纪要'), '备注：Synthetic retained input');
    serverVersion = 2;
    await cache.invalidateQueries({ queryKey: ['meeting-opportunities'] });
    expect(screen.getByText(/基础版本 1，/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '读取当前商机版本' }));
    expect(await screen.findByText(/基础版本 2，/)).toBeInTheDocument();
    expect(screen.getByLabelText('合成会议纪要')).toHaveValue('备注：Synthetic retained input');
    await userEvent.click(screen.getByLabelText('我确认这里只使用合成演示资料'));
    await userEvent.click(screen.getByRole('button', { name: '提交 Mock 解析' }));
    const posts = request.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(JSON.parse(String(posts[0][1]?.body)).expected_opportunity_version).toBe(2);
  });
  it('keeps the baseline and input when explicitly reading the latest opportunity fails', async () => {
    const request = vi.spyOn(api, 'request').mockImplementation(async path => {
      if (path === '/api/v1/opportunities/opportunity') throw new api.ApiError(0, 'NETWORK_ERROR', 'Synthetic baseline read failed');
      return path.includes('/meeting-analyses?') ? { data: [], page: { total: 0 } } : { data: [{ id: 'opportunity', name: 'Synthetic deal', version: 1, stage: 'NEGOTIATION' }], page: { total: 1 } };
    });
    render(wrap(<Meetings session={{ user: { id: 'manager', name: 'Synthetic', email: 'manager@example.test', role: 'SALES_MANAGER', is_active: true }, csrf_token: 'synthetic' }} />));
    await userEvent.click(await screen.findByRole('button', { name: '选择商机：Synthetic deal' }));
    await userEvent.type(screen.getByLabelText('合成会议纪要'), 'Synthetic unsaved');
    await userEvent.click(screen.getByRole('button', { name: '读取当前商机版本' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic baseline read failed');
    expect(screen.getByText(/基础版本 1，/)).toBeInTheDocument();
    expect(screen.getByLabelText('合成会议纪要')).toHaveValue('Synthetic unsaved');
    expect(request.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  });
  it('paginates history and opens the selected analysis without submitting a new task', async () => {
    const request = vi.spyOn(api, 'request').mockImplementation(async path => ({
      data: [{ id: path.includes('page=2&') ? 'older' : 'newer', status: 'SUCCEEDED', mode: 'MOCK', created_at: path.includes('page=2&') ? 'older date' : 'newer date' }],
      page: { total: 21 },
    }));
    const select = vi.fn(); render(wrap(<AnalysisHistory opportunityId="opportunity" onSelect={select} />));
    await screen.findByText(/newer date/);
    await userEvent.click(screen.getByRole('button', { name: '分析下一页' }));
    await userEvent.click(await screen.findByRole('button', { name: /older date/ }));
    expect(select).toHaveBeenCalledWith('older');
    expect(screen.getByRole('button', { name: '分析下一页' })).toBeDisabled();
    expect(request).toHaveBeenCalledWith('/api/v1/opportunities/opportunity/meeting-analyses?page=2&page_size=20', {}, true);
    expect(request.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  });
  it('distinguishes failed history loading from empty results and retries the current page', async () => {
    vi.spyOn(api, 'request').mockRejectedValueOnce(new Error('Synthetic history unavailable')).mockResolvedValue({ data: [], page: { total: 0 } });
    render(wrap(<AnalysisHistory opportunityId="opportunity" onSelect={vi.fn()} />));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic history unavailable');
    expect(screen.queryByText('暂无分析。')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(await screen.findByText('暂无分析。')).toBeInTheDocument();
  });
  it('blocks READ_ONLY without reading private notes', () => {
    const request = vi.spyOn(api, 'request');
    render(wrap(<Meetings session={{ user: { id: 'user', name: 'Synthetic', email: 'synthetic@example.test', role: 'READ_ONLY', is_active: true }, csrf_token: 'synthetic' }} />));
    expect(screen.getByRole('alert')).toHaveTextContent('只读账号');
    expect(request).not.toHaveBeenCalled();
  });
  it('shows source evidence, unknowns, and Mock boundaries without an apply action', async () => {
    vi.spyOn(api, 'request').mockImplementation(async path => path.includes('/jobs/') ? { status: 'SUCCEEDED', attempts: 1 } : draft);
    render(wrap(<AnalysisDetail id="analysis" />));
    expect(await screen.findByRole('heading', { name: '解析草稿 · MOCK' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '预算 · 未知' })).toBeInTheDocument();
    expect(screen.getByRole('blockquote')).toHaveTextContent('合成报表');
    expect(screen.queryByRole('button', { name: /接受|应用|执行/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '拒绝草稿' })).toBeDisabled();
  });
  it('does not call a queued task a successful analysis', async () => {
    vi.spyOn(api, 'request').mockImplementation(async path => path.includes('/jobs/') ? { status: 'QUEUED', attempts: 0 } : { ...draft, status: 'QUEUED', result: null, suggestion: { ...draft.suggestion, status: 'GENERATING', effective_status: 'GENERATING' } });
    render(wrap(<AnalysisDetail id="analysis" />));
    expect(await screen.findByText(/尚未解析成功/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '拒绝草稿' })).not.toBeInTheDocument();
  });
  it('preserves review reason after conflict and sends the displayed version', async () => {
    const request = vi.spyOn(api, 'request').mockImplementation(async (path, options) => {
      if (options?.method === 'POST') throw new api.ApiError(409, 'VERSION_CONFLICT', '草稿已变化');
      return path.includes('/jobs/') ? { status: 'SUCCEEDED', attempts: 1 } : draft;
    });
    render(wrap(<AnalysisDetail id="analysis" />));
    await userEvent.type(await screen.findByLabelText('草稿审核原因'), 'Synthetic review');
    await userEvent.click(screen.getByRole('button', { name: '拒绝草稿' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('草稿已变化');
    expect(screen.getByLabelText('草稿审核原因')).toHaveValue('Synthetic review');
    const call = request.mock.calls.find(([, options]) => options?.method === 'POST')!;
    expect(JSON.parse(String(call[1]!.body))).toEqual({ expected_version: 2, reason: 'Synthetic review' });
  });
});
