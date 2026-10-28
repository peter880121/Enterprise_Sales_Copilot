export type Role = 'ADMIN' | 'SALES_MANAGER' | 'SALES_REP' | 'READ_ONLY';
export interface User { id: string; name: string; email: string; role: Role; is_active: boolean }
export interface SessionData { user: User; csrf_token: string; expires_at?: string }
export interface Capability { available: boolean; reason: string | null }
export interface Capabilities {
  crm: Capability;
  storage: Capability;
  ai: Capability & { mode: 'MOCK' | 'REAL' };
  knowledge: Capability & { enabled: boolean };
  worker: Capability;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string) {
    super(message);
  }
}

let csrfToken: string | undefined;
export const setCsrfToken = (value?: string) => { csrfToken = value; };

export async function request<T>(path: string, options: RequestInit = {}, withPage = false): Promise<T> {
  if (!path.startsWith('/api/v1/')) throw new Error('API requests must use the same-origin API path');
  const method = options.method || 'GET';
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD'].includes(method) && csrfToken) headers.set('X-CSRF-Token', csrfToken);
  let response: Response;
  try {
    response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', '无法连接服务，请检查网络后重试。');
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, body?.error?.code || 'HTTP_ERROR',
      body?.error?.message || '服务暂不可用，请稍后重试。', body?.request_id);
  }
  return (withPage ? body : body.data) as T;
}

export const authApi = {
  me: async () => {
    const data = await request<SessionData>('/api/v1/auth/me');
    setCsrfToken(data.csrf_token);
    return data;
  },
  login: async (email: string, password: string) => {
    const data = await request<SessionData>('/api/v1/auth/login', {
      method: 'POST', body: JSON.stringify({ email, password }),
    });
    setCsrfToken(data.csrf_token);
    return data;
  },
  logout: async () => {
    await request<void>('/api/v1/auth/logout', { method: 'POST' });
    setCsrfToken();
  },
};
