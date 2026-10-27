import { describe, it, expect, vi } from 'vitest';
import { request, setCsrfToken } from './api';

describe('same-origin request layer', () => {
  it('uses relative API paths, session cookies and CSRF for writes', async () => {
    const mock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));
    setCsrfToken('synthetic-csrf');
    await request('/api/v1/auth/logout', { method: 'POST' });
    expect(mock).toHaveBeenCalledWith('/api/v1/auth/logout', expect.objectContaining({
      credentials: 'same-origin', method: 'POST',
    }));
    expect(new Headers(mock.mock.calls[0][1]?.headers).get('X-CSRF-Token')).toBe('synthetic-csrf');
    setCsrfToken();
  });
  it('rejects container URLs in browser code', async () => {
    await expect(request('http://api:8000/api/v1/auth/me')).rejects.toThrow('same-origin');
  });
  it('does not disclose non-JSON server responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('private upstream debug', { status: 500 }));
    await expect(request('/api/v1/auth/me')).rejects.toThrow('服务暂不可用');
  });
});
