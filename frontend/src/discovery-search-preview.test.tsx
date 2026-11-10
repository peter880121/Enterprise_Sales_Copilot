import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import * as api from './api';
import { PublicSearchPreview } from './discovery-search-preview';

const data = { provider: 'TAVILY', public_query: 'Synthetic public procurement', profile_version: 7, max_results: 5, search_depth: 'basic', configured: true, external_request_sent: false, web_execution_available: false, notice: 'Synthetic preview only' };
const empty = { data: [], page: { total: 0 } };
function renderPreview(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(<QueryClientProvider client={client}><PublicSearchPreview profile={{ id: 'profile', version: 7 }} /></QueryClientProvider>);
}

describe('public search preview', () => {
  it('starts empty and submits only explicitly entered public text with the frozen version', async () => {
    const request = vi.spyOn(api, 'request').mockImplementation(async path => path.endsWith('/search-preview') ? data : empty);
    renderPreview();
    expect(screen.getByLabelText('允许外发的公开查询')).toHaveValue('');
    await userEvent.type(screen.getByLabelText('允许外发的公开查询'), data.public_query);
    await userEvent.click(screen.getByRole('button', { name: '预览公开查询' }));
    expect(await screen.findByRole('status')).toHaveTextContent(data.public_query);
    const posts = request.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(JSON.parse(posts[0][1]!.body as string)).toEqual({ expected_profile_version: 7, public_query: data.public_query });
    expect(screen.getByRole('button', { name: '网页搜索执行尚未开放' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText('允许外发的公开查询'), ' changed');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('retains unsaved text on version conflict and does not call a search endpoint', async () => {
    const request = vi.spyOn(api, 'request').mockImplementation(async path => { if (path.endsWith('/search-preview')) throw new api.ApiError(409, 'VERSION_CONFLICT', 'Synthetic profile changed'); return empty; });
    renderPreview();
    await userEvent.type(screen.getByLabelText('允许外发的公开查询'), data.public_query);
    await userEvent.click(screen.getByRole('button', { name: '预览公开查询' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic profile changed');
    expect(screen.getByLabelText('允许外发的公开查询')).toHaveValue(data.public_query);
    expect(request.mock.calls.filter(([, options]) => options?.method === 'POST').every(([path]) => path.endsWith('/search-preview'))).toBe(true);
  });

  it('ignores an older response when the public input changes while the request is in flight', async () => {
    let resolve!: (value: typeof data) => void;
    vi.spyOn(api, 'request').mockImplementation(path => path.endsWith('/search-preview') ? new Promise(done => { resolve = done; }) : Promise.resolve(empty));
    renderPreview();
    await userEvent.type(screen.getByLabelText('允许外发的公开查询'), data.public_query);
    await userEvent.click(screen.getByRole('button', { name: '预览公开查询' }));
    await userEvent.type(screen.getByLabelText('允许外发的公开查询'), ' changed');
    await act(async () => resolve(data));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('retries a lost acceptance response with exactly the same frozen intent and no automatic POST', async () => {
    const available = { ...data, web_execution_available: true, preview_token: 'synthetic-preview' };
    const received = { id: 'run', public_query: data.public_query, status: 'SUCCEEDED', error_code: null, may_have_been_charged: true, result: { results: [] } };
    let posts = 0;
    const request = vi.spyOn(api, 'request').mockImplementation(async (path, options) => {
      if (path.endsWith('/search-preview')) return available;
      if (options?.method === 'POST') { if (++posts === 1) throw new api.ApiError(0, 'NETWORK_ERROR', 'Synthetic response lost'); return received; }
      return path.includes('/search-runs/run') ? received : empty;
    });
    renderPreview();
    await userEvent.type(screen.getByLabelText('允许外发的公开查询'), data.public_query);
    await userEvent.click(screen.getByRole('button', { name: '预览公开查询' }));
    expect(await screen.findByRole('button', { name: '确认并开始搜索' })).toBeDisabled();
    await userEvent.click(screen.getByLabelText('我确认仅发送以上公开查询，并了解搜索可能计费'));
    await userEvent.click(screen.getByRole('button', { name: '确认并开始搜索' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('保留原请求');
    expect(posts).toBe(1);
    expect(screen.getByLabelText('允许外发的公开查询')).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '按原请求重试受理' }));
    expect(await screen.findByRole('button', { name: '搜索任务已受理' })).toBeDisabled();
    const acceptedCalls = request.mock.calls.filter(([path, options]) => path.endsWith('/search-runs') && options?.method === 'POST');
    expect(acceptedCalls).toHaveLength(2);
    expect(acceptedCalls[0][1]).toEqual(acceptedCalls[1][1]);
  });

  it('never repeats an acknowledged search after history refresh fails', async () => {
    const received = { id: 'run', public_query: data.public_query, status: 'SUCCEEDED', error_code: null, may_have_been_charged: true, result: { results: [] } };
    const request = vi.spyOn(api, 'request').mockImplementation(async (path, options) => path.endsWith('/search-preview') ? { ...data, web_execution_available: true, preview_token: 'synthetic-preview' } : options?.method === 'POST' || path.includes('/search-runs/run') ? received : empty);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, 'invalidateQueries').mockRejectedValue(new Error('Synthetic history refresh failed'));
    renderPreview(client);
    await userEvent.type(screen.getByLabelText('允许外发的公开查询'), data.public_query);
    await userEvent.click(screen.getByRole('button', { name: '预览公开查询' }));
    await userEvent.click(await screen.findByLabelText('我确认仅发送以上公开查询，并了解搜索可能计费'));
    await userEvent.click(screen.getByRole('button', { name: '确认并开始搜索' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('任务已受理');
    expect(screen.getByRole('button', { name: '搜索任务已受理' })).toBeDisabled();
    expect(request.mock.calls.filter(([path, options]) => path.endsWith('/search-runs') && options?.method === 'POST')).toHaveLength(1);
  });

  it('refreshes history automatically when polling observes a terminal task, without another search', async () => {
    let histories = 0;
    const received = { id: 'run', public_query: data.public_query, status: 'RUNNING', error_code: null, may_have_been_charged: true };
    const request = vi.spyOn(api, 'request').mockImplementation(async (path, options) => {
      if (path.endsWith('/search-preview')) return { ...data, web_execution_available: true, preview_token: 'synthetic-preview' };
      if (options?.method === 'POST') return received;
      if (path.includes('/search-runs/run')) return { ...received, status: 'SUCCEEDED', result: { results: [] } };
      histories += 1;
      return { data: histories >= 3 ? [{ ...received, status: 'SUCCEEDED' }] : [], page: { total: histories >= 3 ? 1 : 0 } };
    });
    renderPreview();
    await userEvent.type(screen.getByLabelText('允许外发的公开查询'), data.public_query);
    await userEvent.click(screen.getByRole('button', { name: '预览公开查询' }));
    await userEvent.click(await screen.findByLabelText('我确认仅发送以上公开查询，并了解搜索可能计费'));
    await userEvent.click(screen.getByRole('button', { name: '确认并开始搜索' }));
    expect(await screen.findByRole('button', { name: `${data.public_query} · SUCCEEDED` })).toBeVisible();
    expect(request.mock.calls.filter(([path, options]) => path.endsWith('/search-runs') && options?.method === 'POST')).toHaveLength(1);
  });
});
