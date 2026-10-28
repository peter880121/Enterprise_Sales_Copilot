import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import * as api from './api';
import { ApiError, type SessionData } from './api';
import { moneyLabel, opportunitySchema, salesError, SalesWorkspace } from './sales';

const session: SessionData = { user: { id: '10000000-0000-4000-8000-000000000001',
  name: 'Synthetic Rep', email: 'rep@example.test', role: 'SALES_REP', is_active: true }, csrf_token: 'synthetic' };

describe('sales contracts', () => {
  it('keeps unknown distinct from known zero', () => {
    expect(moneyLabel(null, 'CNY')).toBe('金额待确认');
    expect(moneyLabel('0.00', 'CNY')).toBe('CNY 0.00');
  });
  it.each(['1e3', '-1', '1.001', '10000000000000000.00'])('rejects invalid amount %s', amount => {
    expect(opportunitySchema.safeParse({ name: 'Synthetic', account_id: session.user.id,
      amount, currency: 'CNY', priority: 'MEDIUM', expected_close_date: '' }).success).toBe(false);
  });
  it('handles self review as reviewer conflict rather than expired session', () => {
    expect(salesError(new ApiError(403, 'EVIDENCE_REVIEWER_CONFLICT', 'synthetic'))).toContain('更换另一位');
    expect(salesError(new ApiError(403, 'FORBIDDEN', 'synthetic'))).toContain('没有该操作权限');
    expect(salesError(new ApiError(403, 'CSRF_INVALID', 'synthetic'))).toContain('安全校验失败');
  });
  it('renders a read-only board with separate currencies and unknown amount', async () => {
    vi.spyOn(api, 'request').mockImplementation(async path => path.includes('pipeline')
      ? { currency_groups: [ { currency: 'CNY', pipeline_value: null, weighted_forecast: null,
        unknown_amount_count: 1, closed_won_actual_amount: '0.00', stages: [] },
      { currency: 'USD', pipeline_value: '23.00', weighted_forecast: '4.60', unknown_amount_count: 0,
        closed_won_actual_amount: '0.00', stages: [] } ] }
      : { data: [], page: { number: 1, size: 20, total: 0 } });
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/opportunities']}><SalesWorkspace session={{ ...session,
        user: { ...session.user, role: 'READ_ONLY' } }} /></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('CNY Pipeline')).toBeInTheDocument();
    expect(await screen.findByText('USD Pipeline')).toBeInTheDocument();
    expect(screen.getByText('另 1 笔金额待确认')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '创建商机' })).not.toBeInTheDocument();
  });
});
