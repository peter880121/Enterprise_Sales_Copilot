import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import * as api from './api';
import { ApplyPanel, type ExecutionReceipt, type FrozenChange } from './meeting-execution';
import { RetentionPreview } from './retention';

const change: FrozenChange = { id: '00000000-0000-4000-8000-000000000001', kind: 'FIELD', before: { amount: null, currency: 'CNY' },
  values: { amount: '1500.00', currency: 'USD' }, evidence: [{ quote: '1500.00 USD', start: 0, end: 11 }] };
const receipt = { execution_id: 'execution', suggestion_id: 'suggestion', opportunity_id: 'opportunity', result_version: 2, activity_ids: [], selected_change_ids: [change.id] };
function panel(onSaved: (receipt: ExecutionReceipt) => void | Promise<void> = vi.fn()) {
  return <ApplyPanel suggestionId="suggestion" version={2} opportunityVersion={1} changes={[change]} enabled onSaved={onSaved} />;
}
async function choose() {
  await userEvent.click(screen.getByRole('checkbox', { name: '字段：amount / currency' }));
  await userEvent.click(screen.getByRole('checkbox', { name: '我已核对所选变更及依据，确认执行' }));
}
describe('controlled execution and retention', () => {
  it('defaults to no selection and requires explicit confirmation of the complete money group', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue(receipt);
    render(panel());
    expect(screen.getByRole('button', { name: '确认执行所选变更' })).toBeDisabled();
    expect(screen.getAllByRole('checkbox').every(checkbox => !(checkbox as HTMLInputElement).checked)).toBe(true);
    await choose(); await userEvent.click(screen.getByRole('button', { name: '确认执行所选变更' }));
    expect(await screen.findByRole('status')).toHaveTextContent('执行已完成');
    expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toEqual({ expected_version: 2, expected_opportunity_version: 1, selected_change_ids: [change.id], confirmed: true });
  });
  it('retries a lost response with the identical key and body and preserves selection', async () => {
    const request = vi.spyOn(api, 'request').mockRejectedValueOnce(new api.ApiError(0, 'NETWORK_ERROR', 'Synthetic response lost')).mockResolvedValue(receipt);
    render(panel()); await choose();
    await userEvent.click(screen.getByRole('button', { name: '确认执行所选变更' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic response lost');
    expect(screen.getByRole('checkbox', { name: '字段：amount / currency' })).toBeChecked();
    await userEvent.click(screen.getByRole('button', { name: '确认执行所选变更' }));
    await screen.findByRole('status');
    expect(request.mock.calls[0][1]).toEqual(request.mock.calls[1][1]);
  });
  it('does not repeat a committed execution when the following refresh fails', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue(receipt);
    render(panel(async () => { throw new Error('Synthetic refresh failure'); })); await choose();
    const button = screen.getByRole('button', { name: '确认执行所选变更' }); await userEvent.click(button);
    expect(await screen.findByRole('alert')).toHaveTextContent('执行已成功');
    expect(button).toBeDisabled();
    await act(async () => { fireEvent.click(button); });
    expect(request).toHaveBeenCalledTimes(1);
  });
  it('preserves selected input and its original version when refreshed props conflict', async () => {
    const request = vi.spyOn(api, 'request').mockRejectedValue(new api.ApiError(409, 'SUGGESTION_STALE', '上下文已变化'));
    const { rerender } = render(panel()); await choose();
    rerender(<ApplyPanel suggestionId="suggestion" version={3} opportunityVersion={1} changes={[change]} enabled onSaved={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '确认执行所选变更' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('上下文已变化');
    expect(screen.getByRole('checkbox', { name: '字段：amount / currency' })).toBeChecked();
    expect(JSON.parse(String(request.mock.calls[0][1]?.body)).expected_version).toBe(2);
    expect(request).toHaveBeenCalledTimes(1);
  });
  it.each(['SALES_MANAGER', 'SALES_REP', 'READ_ONLY'] as const)('blocks retention preview for %s without fetching', role => {
    const request = vi.spyOn(api, 'request');
    render(<RetentionPreview session={{ user: { id: 'user', name: 'Synthetic', email: 'synthetic@example.test', is_active: true, role }, csrf_token: 'synthetic' }} />);
    expect(screen.getByRole('alert')).toHaveTextContent('仅管理员'); expect(request).not.toHaveBeenCalled();
  });
  it('requests only a read-only preview and offers no deletion action', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue({ mode: 'DRY_RUN', writes_enabled: false, as_of: '2026-10-28T00:00:00Z', groups: [], protected: { audit_events: 10 }, limitations: ['仅预览'] });
    render(<QueryClientProvider client={new QueryClient()}><RetentionPreview session={{ user: { id: 'admin', name: 'Synthetic', email: 'admin@example.test', is_active: true, role: 'ADMIN' }, csrf_token: 'synthetic' }} /></QueryClientProvider>);
    await userEvent.click(screen.getByRole('button', { name: '生成只读预览' }));
    expect(await screen.findByText(/audit_events：10/)).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/api/v1/admin/retention/preview');
    expect(screen.queryByRole('button', { name: /删除|清理|归档/ })).not.toBeInTheDocument();
  });
});
