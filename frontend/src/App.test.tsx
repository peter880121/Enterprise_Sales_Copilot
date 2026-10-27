import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import App from './App';

function renderAt(path: string) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: {
    queries: { retry: false },
  } })}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
}

describe('authentication UI', () => {
  it('validates the login form without sending credentials', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch');
    renderAt('/login');
    await userEvent.click(screen.getByRole('button', { name: '进入工作空间' }));
    expect(await screen.findByText('请输入有效邮箱地址。')).toBeInTheDocument();
    expect(screen.getByText('请输入密码。')).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('shows a rejected login', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'INVALID_CREDENTIALS', message: '邮箱或密码不正确。' },
    }), { status: 401 }));
    renderAt('/login');
    await userEvent.type(screen.getByLabelText('邮箱'), 'synthetic@example.test');
    await userEvent.type(screen.getByLabelText('密码'), 'synthetic-password');
    await userEvent.click(screen.getByRole('button', { name: '进入工作空间' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('邮箱或密码不正确。');
  });
  it('redirects unauthenticated users', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'SESSION_EXPIRED', message: '请先登录。' },
    }), { status: 401 }));
    renderAt('/');
    expect(await screen.findByRole('heading', { name: '登录工作空间' })).toBeInTheDocument();
  });
  it('reports current-user loading failures instead of claiming logged-out', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('network unavailable'));
    renderAt('/');
    expect(await screen.findByRole('alert')).toHaveTextContent('无法连接服务');
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();
  });
});
