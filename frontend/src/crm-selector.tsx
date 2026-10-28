import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { request } from './api';

type Item = { id: string; name: string; account_id?: string };
type Page = { data: Item[]; page: { number: number; size: number; total: number } };

export function CRMSelector({ kind, value, onChange, accountId, initialLabel, disabled = false }: {
  kind: 'accounts' | 'contacts'; value: string; onChange: (id: string) => void;
  accountId?: string; initialLabel?: string; disabled?: boolean;
}) {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const contact = kind === 'contacts';
  const label = contact ? '联系人' : '客户';
  const enabled = !contact || !!accountId;
  const params = new URLSearchParams({ q: search, page: String(page), page_size: '25' });
  const base = contact ? `/api/v1/accounts/${accountId}/contacts` : '/api/v1/accounts';
  const results = useQuery({ queryKey: ['crm-selector', kind, accountId, search, page],
    enabled, retry: false, queryFn: () => request<Page>(`${base}?${params}`, {}, true) });
  const selected = useQuery({ queryKey: ['crm-selector-selected', kind, value],
    enabled: enabled && !!value, retry: false,
    queryFn: () => request<Item>(`/api/v1/${kind}/${value}`) });
  const items = results.data?.data || [];
  const selectedItem = selected.data && (!contact || selected.data.account_id === accountId) ? selected.data : undefined;
  return <fieldset className="crm-selector" disabled={disabled || !enabled}>
    <label>搜索{label}<input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} /></label>
    <label>{contact ? '主要联系人' : '客户企业'}<select value={value} onChange={e => onChange(e.target.value)}>
      <option value="">{contact ? '未指定' : '选择客户'}</option>
      {value && !items.some(item => item.id === value) && <option value={value}>{selectedItem?.name || initialLabel || value}</option>}
      {items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label>
    {!enabled ? <p>请先选择客户。</p> : results.error ? <p role="alert">{label}查询失败：{results.error.message}<button type="button" onClick={() => void results.refetch()}>重试{label}查询</button></p>
      : results.isPending ? <p role="status">正在读取{label}…</p>
      : !items.length ? <p>没有匹配的{label}。</p> : null}
    {selected.error && <p role="alert">当前选中{label}读取失败：{selected.error.message}</p>}
    <div><button type="button" disabled={page === 1 || results.isFetching} onClick={() => setPage(page - 1)}>{label}上一页</button>
      <span>{label}第 {page} 页 · 共 {results.data?.page.total ?? '—'} 条</span>
      <button type="button" disabled={!results.data || !!results.error || results.isFetching || page * 25 >= results.data.page.total} onClick={() => setPage(page + 1)}>{label}下一页</button></div>
  </fieldset>;
}
