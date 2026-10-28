import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import * as api from './api';
import { CreateUserForm, EditUserForm, Profile, Register, UserHistory, UsersWorkspace, type ManagedUser } from './users';
import { registrationSchema } from './user-validation';

const user: ManagedUser = { id: '00000000-0000-4000-8000-000000000001', name: 'Synthetic user', email: 'synthetic@example.test', role: 'SALES_REP', is_active: true, registration_status: 'APPROVED', deleted_at: null, version: 7, created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z' };
const password = 'Synthetic-password-only-2026';
function wrap(content: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{content}</MemoryRouter></QueryClientProvider>;
}
describe('user registration and management', () => {
  it('validates password confirmation before making a registration request', async () => {
    const request = vi.spyOn(api, 'request');
    render(wrap(<Register />));
    await userEvent.click(screen.getByRole('button', { name: '提交注册申请' }));
    expect(await screen.findAllByRole('alert')).not.toHaveLength(0);
    expect(request).not.toHaveBeenCalled();
    expect(registrationSchema.safeParse({ name: 'Synthetic', email: user.email, password, confirm_password: 'different' }).success).toBe(false);
  });
  it('submits only public registration fields and shows pending approval without auto-login', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue({ message: 'pending' });
    render(wrap(<Register />));
    await userEvent.type(screen.getByLabelText('姓名'), 'Synthetic registrant');
    await userEvent.type(screen.getByLabelText('注册邮箱'), user.email);
    await userEvent.type(screen.getByLabelText('注册密码'), password);
    await userEvent.type(screen.getByLabelText('确认注册密码'), password);
    await userEvent.click(screen.getByRole('button', { name: '提交注册申请' }));
    expect(await screen.findByRole('heading', { name: '注册申请已提交' })).toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(1);
    const body = JSON.parse(String(request.mock.calls[0][1]?.body));
    expect(Object.keys(body).sort()).toEqual(['email', 'name', 'password']);
  });
  it.each(['SALES_MANAGER', 'SALES_REP', 'READ_ONLY'] as const)('blocks the admin workspace for %s', role => {
    const request = vi.spyOn(api, 'request');
    render(wrap(<UsersWorkspace session={{ user: { ...user, role }, csrf_token: 'synthetic' }} />));
    expect(screen.getByRole('alert')).toHaveTextContent('没有用户管理权限');
    expect(request).not.toHaveBeenCalled();
  });
  it('keeps confirmed creation locked when subsequent reading fails', async () => {
    const request = vi.spyOn(api, 'request').mockResolvedValue(user);
    render(wrap(<CreateUserForm onSaved={async () => { throw new Error('Synthetic read failure'); }} onCancel={vi.fn()} />));
    await userEvent.type(screen.getByLabelText('姓名'), user.name);
    await userEvent.type(screen.getByLabelText('用户邮箱'), user.email);
    await userEvent.type(screen.getByLabelText('初始密码'), password);
    const button = screen.getByRole('button', { name: '保存新用户' });
    await userEvent.click(button);
    expect(await screen.findByRole('status')).toHaveTextContent('用户已创建');
    expect(screen.getByRole('alert')).toHaveTextContent('不要重复创建');
    expect(button).toBeDisabled();
    await act(async () => { fireEvent.submit(button.closest('form')!); });
    expect(request).toHaveBeenCalledTimes(1);
  });
  it('preserves the edit version and inputs when refreshed props arrive and PATCH conflicts', async () => {
    const request = vi.spyOn(api, 'request').mockRejectedValue(new api.ApiError(409, 'VERSION_CONFLICT', 'Synthetic conflict'));
    const { rerender } = render(wrap(<EditUserForm user={user} onSaved={vi.fn()} onCancel={vi.fn()} />));
    await userEvent.clear(screen.getByLabelText('编辑姓名')); await userEvent.type(screen.getByLabelText('编辑姓名'), 'Unsaved input');
    await userEvent.type(screen.getByLabelText('修改原因'), 'Synthetic change');
    rerender(wrap(<EditUserForm user={{ ...user, version: 8, name: 'Server changed' }} onSaved={vi.fn()} onCancel={vi.fn()} />));
    await userEvent.click(screen.getByRole('button', { name: '保存用户修改' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('当前输入已保留');
    expect(screen.getByLabelText('编辑姓名')).toHaveValue('Unsaved input');
    expect(JSON.parse(String(request.mock.calls[0][1]?.body))).toMatchObject({ expected_version: 7, name: 'Unsaved input' });
  });
  it('treats incorrect current password as a local validation failure and keeps profile input', async () => {
    const request = vi.spyOn(api, 'request').mockImplementation(async (_path, options) => {
      if (options?.method === 'PATCH') throw new api.ApiError(401, 'WRONG_PASSWORD', '当前密码不正确。');
      return { user };
    });
    render(wrap(<Profile />));
    await screen.findByLabelText('个人姓名');
    await userEvent.type(screen.getByLabelText('验证当前密码'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: '保存个人资料' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('当前密码不正确');
    expect(screen.getByLabelText('个人姓名')).toHaveValue(user.name);
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  });
  it('paginates user audit history and shows actor and field changes', async () => {
    const request = vi.spyOn(api, 'request').mockImplementation(async path => {
      const page = path.includes('page=2&') ? 2 : 1;
      return { data: [{ id: `audit-${page}`, action: `USER_UPDATE_PAGE_${page}`, actor_id: 'synthetic-admin',
        reason: 'Synthetic change', created_at: '2026-10-28T00:00:00Z',
        before_state: { name: 'Before', role: 'SALES_REP' }, after_state: { name: 'After', role: 'SALES_REP' } }],
      page: { number: page, size: 20, total: 21 } };
    });
    render(wrap(<UserHistory userId={user.id} />));
    expect(await screen.findByText(/USER_UPDATE_PAGE_1/)).toHaveTextContent('synthetic-admin');
    await userEvent.click(screen.getByText('查看字段变更'));
    expect(screen.getByRole('cell', { name: '"Before"' })).toBeVisible();
    expect(screen.getByRole('cell', { name: '"After"' })).toBeVisible();
    expect(screen.queryByRole('cell', { name: 'role' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '审计下一页' }));
    expect(await screen.findByText(/USER_UPDATE_PAGE_2/)).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith(`/api/v1/users/${user.id}/history?page=2&page_size=20`, {}, true);
    expect(screen.getByRole('button', { name: '审计下一页' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '审计上一页' }));
    expect(await screen.findByText(/USER_UPDATE_PAGE_1/)).toBeInTheDocument();
  });
  it('shows audit request failures and retries the current page without claiming empty history', async () => {
    const request = vi.spyOn(api, 'request').mockRejectedValueOnce(new Error('Synthetic audit read failure'))
      .mockResolvedValue({ data: [], page: { number: 1, size: 20, total: 0 } });
    render(wrap(<UserHistory userId={user.id} />));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic audit read failure');
    expect(screen.queryByText('暂无用户操作审计。')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(await screen.findByText('暂无用户操作审计。')).toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(2);
  });
});
