import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import * as api from './api';
import { RegeneratePanel } from './meeting-regenerate';

const accepted = { job_id: 'new-job', resource_id: 'new-analysis' };
function panel(onSaved: () => Promise<void> = async () => {}, onOpen = vi.fn()) {
  return <RegeneratePanel suggestionId="old" version={2} opportunityId="opportunity" enabled onSaved={onSaved} onOpen={onOpen} />;
}
async function confirm() {
  await userEvent.click(screen.getByRole('button', { name: '读取重新生成基准' }));
  await userEvent.click(screen.getByLabelText('我确认复制原始合成纪要，并替换当前未执行草稿'));
}
describe('explicit draft regeneration', () => {
  it('requires explicit confirmation and only opens the accepted draft when requested', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValueOnce({ version: 5 }).mockResolvedValue(accepted);
    const open = vi.fn(); render(panel(async () => {}, open));
    expect(screen.getByRole('button', { name: '确认重新生成' })).toBeDisabled();
    await confirm(); await userEvent.click(screen.getByRole('button', { name: '确认重新生成' }));
    expect(await screen.findByRole('status')).toHaveTextContent('已创建替代草稿');
    expect(request.mock.calls[1][0]).toBe('/api/v1/suggestions/old/regenerate');
    expect(JSON.parse(String(request.mock.calls[1][1]?.body))).toEqual({ expected_version: 2, expected_opportunity_version: 5, request_token: expect.any(String) });
    expect(open).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '查看新草稿' })); expect(open).toHaveBeenCalledWith('new-analysis');
  });
  it('retains the same token and frozen versions after response loss and background refresh', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValueOnce({ version: 5 }).mockRejectedValueOnce(new api.ApiError(0, 'NETWORK_ERROR', 'Synthetic lost response')).mockResolvedValue(accepted);
    const { rerender } = render(panel()); await confirm();
    await userEvent.click(screen.getByRole('button', { name: '确认重新生成' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic lost response');
    rerender(<RegeneratePanel suggestionId="old" version={3} opportunityId="opportunity" enabled onSaved={async () => {}} onOpen={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: '确认重新生成' })); await screen.findByRole('status');
    expect(request.mock.calls[1][1]).toEqual(request.mock.calls[2][1]);
    expect(JSON.parse(String(request.mock.calls[2][1]?.body)).expected_version).toBe(2);
  });
  it('does not create another task when acceptance is followed by refresh failure', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValueOnce({ version: 1 }).mockResolvedValue(accepted);
    render(panel(async () => { throw new Error('Synthetic refresh failure'); })); await confirm();
    await userEvent.click(screen.getByRole('button', { name: '确认重新生成' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('重新生成已受理');
    expect(screen.queryByRole('button', { name: '确认重新生成' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查看新草稿' })).toBeEnabled();
    expect(request).toHaveBeenCalledTimes(2);
  });
  it('does not submit when reading the baseline fails', async () => {
    const request = vi.spyOn(api, 'request').mockRejectedValue(new api.ApiError(0, 'NETWORK_ERROR', 'Synthetic baseline unavailable'));
    render(panel()); await userEvent.click(screen.getByRole('button', { name: '读取重新生成基准' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic baseline unavailable');
    expect(screen.getByRole('button', { name: '确认重新生成' })).toBeDisabled();
    expect(request.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  });
  it('restores a superseded draft replacement link without sending a request', async () => {
    const request = vi.spyOn(api, 'request'), open = vi.fn();
    render(<RegeneratePanel suggestionId="old" version={3} opportunityId="opportunity" enabled={false} replacementAnalysisId="restored-child" onSaved={async () => {}} onOpen={open} />);
    await userEvent.click(screen.getByRole('button', { name: '查看新草稿' }));
    expect(open).toHaveBeenCalledWith('restored-child'); expect(request).not.toHaveBeenCalled();
  });
});
