import { useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ApiError, request, type SessionData } from './api';
import { EmptyState, ErrorState, Loading } from './components';
import './crm.css';

interface Entity { id: string; name: string; version: number; is_active: boolean }
export interface Account extends Entity {
  owner_id: string; owner: { id: string; name: string }; industry: string | null;
  website: string | null; company_size: string | null; description: string | null;
}
export interface Contact extends Entity {
  account_id: string; title: string | null; email: string | null; phone: string | null;
  decision_role: string;
}
interface PageData<T> { data: T[]; page: { number: number; size: number; total: number } }
const managers = (session: SessionData) => ['ADMIN', 'SALES_MANAGER'].includes(session.user.role);
const writable = (session: SessionData, account: Account) => managers(session)
  || (session.user.role === 'SALES_REP' && session.user.id === account.owner_id);
const errorMessage = (error: unknown) => error instanceof ApiError && error.status === 409
  ? '数据已被其他用户更新。请重新加载并确认，当前输入不会自动覆盖新版本。'
  : error instanceof Error ? error.message : '操作失败，请重试。';
const nullable = (value: string) => value.trim() || null;

// Match backend/app/crm/schemas.py; shared fixtures cover this input profile.
const emailPattern = /^(?:[A-Za-z0-9_'+\-]+\.)*[A-Za-z0-9_'+\-]*[A-Za-z0-9_+-]@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;
const websitePattern = /^https?:\/\/(\[[0-9a-f:]+\]|[a-z0-9][a-z0-9.\-]*)(?::([0-9]{1,5}))?(?:[/?#][^\s\\]*)?$/i;
const hostLabel = /^[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?$/;
function validWebsite(value: string): boolean {
  if (/[\s\\\u0000-\u001f\u007f]/u.test(value)) return false;
  const match = websitePattern.exec(value);
  if (!match || (match[2] !== undefined && Number(match[2]) > 65535)) return false;
  const host = match[1];
  if (host.startsWith('[')) {
    try { new URL(`http://${host}`); return true; } catch { return false; }
  }
  const domain = host.endsWith('.') ? host.slice(0, -1) : host;
  const labels = domain.split('.');
  if (domain.length > 253 || !labels.every(label => hostLabel.test(label))) return false;
  if (/^[0-9]+$/.test(labels[labels.length - 1])) {
    return labels.length === 4 && labels.every(label => /^[0-9]+$/.test(label)
      && String(Number(label)) === label && Number(label) <= 255);
  }
  return true;
}

export const accountSchema = z.object({
  name: z.string().trim().min(1, '请输入客户名称。').max(200),
  industry: z.string().trim().max(100),
  website: z.string().trim().max(2048).refine(value => !value || validWebsite(value),
    '请输入主机及端口有效、不含凭据的 HTTP 或 HTTPS 地址（国际域名请使用 Punycode）。'),
  company_size: z.string(), description: z.string().trim().max(10000),
  owner_id: z.string().trim().refine(value => !value || z.uuid().safeParse(value).success,
    '负责人 ID 必须是 UUID。'),
});

export function AccountForm({ session, initial, onSaved, onCancel }: {
  session: SessionData; initial?: Account; onSaved: (account: Account) => Promise<void> | void;
  onCancel: () => void;
}) {
  const [error, setError] = useState('');
  const [baseVersion] = useState(initial?.version);
  const form = useForm({ resolver: zodResolver(accountSchema), defaultValues: {
    name: initial?.name || '', industry: initial?.industry || '', website: initial?.website || '',
    company_size: initial?.company_size || '', description: initial?.description || '',
    owner_id: initial?.owner_id || '',
  } });
  const { register, handleSubmit, formState: { errors, isSubmitting } } = form;
  return <form className="crm-form" noValidate onSubmit={handleSubmit(async values => {
    setError('');
    const body = { name: values.name, industry: nullable(values.industry),
      website: nullable(values.website), company_size: nullable(values.company_size),
      description: nullable(values.description),
      ...(managers(session) && values.owner_id ? { owner_id: values.owner_id } : {}),
      ...(initial ? { expected_version: baseVersion } : {}) };
    try {
      const saved = await request<Account>(`/api/v1/accounts${initial ? `/${initial.id}` : ''}`,
        { method: initial ? 'PATCH' : 'POST', body: JSON.stringify(body) });
      await onSaved(saved);
    } catch (err) { setError(errorMessage(err)); }
  })}>
    <h2>{initial ? '编辑客户' : '创建客户'}</h2>
    <label>客户名称<input {...register('name')} aria-invalid={!!errors.name} /></label>
    <label>行业<input {...register('industry')} /></label>
    <label>网站<input {...register('website')} /></label>
    <label>企业规模<select {...register('company_size')}><option value="">未知</option>
      {['SOLO', 'SMALL', 'MEDIUM', 'LARGE', 'ENTERPRISE'].map(value =>
        <option key={value}>{value}</option>)}</select></label>
    <label>客户说明<textarea {...register('description')} /></label>
    {managers(session) && <label>负责人 UUID（创建时留空归自己）<input {...register('owner_id')} /></label>}
    {Object.entries(errors).map(([key, value]) => <p key={key} role="alert">{value.message}</p>)}
    {error && <ErrorState message={error} />}
    <div className="crm-actions"><button className="primary" disabled={isSubmitting} type="submit">
      {isSubmitting ? '正在保存…' : '保存客户'}</button>
      <button type="button" disabled={isSubmitting} onClick={onCancel}>取消</button></div>
  </form>;
}

export const contactSchema = z.object({
  name: z.string().trim().min(1, '请输入联系人姓名。').max(100),
  title: z.string().trim().max(100),
  email: z.string().trim().refine(value => !value || emailPattern.test(value),
    '请输入有效联系人邮箱。').max(254),
  phone: z.string().trim().max(40), decision_role: z.string(),
});
export function ContactForm({ accountId, initial, onSaved, onCancel }: {
  accountId: string; initial?: Contact; onSaved: () => Promise<void> | void; onCancel: () => void;
}) {
  const [error, setError] = useState('');
  const committed = useRef(false);
  const [writeSucceeded, setWriteSucceeded] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm({
    resolver: zodResolver(contactSchema), defaultValues: { name: initial?.name || '',
      title: initial?.title || '', email: initial?.email || '', phone: initial?.phone || '',
      decision_role: initial?.decision_role || 'UNKNOWN' },
  });
  return <form className="crm-form" noValidate onSubmit={handleSubmit(async values => {
    if (committed.current) return;
    setError('');
    const body = { name: values.name, title: nullable(values.title), email: nullable(values.email),
      phone: nullable(values.phone), decision_role: values.decision_role,
      ...(initial ? { expected_version: initial.version } : { account_id: accountId }) };
    try {
      await request<Contact>(`/api/v1/contacts${initial ? `/${initial.id}` : ''}`,
        { method: initial ? 'PATCH' : 'POST', body: JSON.stringify(body) });
    } catch (err) { setError(errorMessage(err)); return; }
    // A successful write must never be repeated just because subsequent reads fail.
    committed.current = true;
    setWriteSucceeded(true);
    try { await onSaved(); }
    catch { setRefreshFailed(true); }
  })}>
    <h2>{initial ? '编辑联系人' : '创建联系人'}</h2>
    <label>联系人姓名<input {...register('name')} aria-invalid={!!errors.name} /></label>
    <label>职位<input {...register('title')} /></label>
    <label>联系人邮箱<input {...register('email')} /></label>
    <label>电话<input {...register('phone')} /></label>
    <label>决策角色<select {...register('decision_role')}>
      {['UNKNOWN', 'DECISION_MAKER', 'CHAMPION', 'INFLUENCER', 'USER', 'PROCUREMENT'].map(value =>
        <option key={value}>{value}</option>)}</select></label>
    {Object.entries(errors).map(([key, value]) => <p key={key} role="alert">{value.message}</p>)}
    {error && <ErrorState message={error} />}
    {writeSucceeded && <p role="status">联系人已保存，请勿重复提交。</p>}
    {refreshFailed && <p role="alert">联系人已保存，但后续刷新失败。请关闭表单后重新加载列表。</p>}
    <div className="crm-actions"><button type="submit" className="primary" disabled={isSubmitting || writeSucceeded}>
      {isSubmitting ? '正在保存…' : '保存联系人'}</button>
      <button type="button" disabled={isSubmitting} onClick={onCancel}>取消</button></div>
  </form>;
}

function Pager({ page, total, onPage }: { page: number; total: number; onPage: (page: number) => void }) {
  return <div className="crm-actions"><button disabled={page <= 1} onClick={() => onPage(page - 1)}>
    上一页</button><span>第 {page} 页 · 共 {total} 条</span>
    <button disabled={page * 20 >= total} onClick={() => onPage(page + 1)}>下一页</button></div>;
}

function Directory({ contacts = false, session }: { contacts?: boolean; session: SessionData }) {
  const [page, setPage] = useState(1), [q, setQ] = useState(''), [active, setActive] = useState('');
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate(), cache = useQueryClient();
  const resource = contacts ? 'contacts' : 'accounts';
  const query = useQuery({ queryKey: ['crm', resource, page, q, active], retry: false,
    queryFn: () => request<PageData<Account | Contact>>(`/api/v1/${resource}?${new URLSearchParams({
      page: String(page), page_size: '20', q, ...(active ? { is_active: active } : {}),
    })}`, {}, true) });
  return <section className="panel crm-panel"><div className="panel-title">
    <h1>{contacts ? '联系人目录' : '客户企业'}</h1><Link to={contacts ? '/accounts' : '/contacts'}>
      {contacts ? '客户企业' : '跨客户联系人搜索'}</Link></div>
    <div className="crm-actions"><label>搜索<input maxLength={100} value={q}
      onChange={event => { setQ(event.target.value); setPage(1); }} /></label>
      <label>状态<select value={active} onChange={event => { setActive(event.target.value); setPage(1); }}>
        <option value="">全部</option><option value="true">有效</option><option value="false">已停用</option>
      </select></label>
      {!contacts && session.user.role !== 'READ_ONLY' && <button className="primary"
        onClick={() => setCreating(true)}>创建客户</button>}</div>
    {creating && <AccountForm session={session} onCancel={() => setCreating(false)}
      onSaved={async account => { await cache.invalidateQueries({ queryKey: ['crm'] });
        navigate(`/accounts/${account.id}`); }} />}
    {query.isPending ? <Loading text="正在读取客户资料…" /> : query.error
      ? <ErrorState message={query.error.message} onRetry={() => void query.refetch()} />
      : <>{!query.data.data.length ? <EmptyState title="没有匹配资料" description="调整搜索条件，或创建客户。" />
        : <div className="crm-table"><table><thead><tr><th>名称</th><th>{contacts ? '邮箱' : '负责人'}</th>
          <th>状态</th><th>操作</th></tr></thead><tbody>{query.data.data.map(row =>
          <tr key={row.id}><td>{row.name}</td><td>{'owner' in row ? row.owner.name : row.email || '—'}</td>
            <td>{row.is_active ? '有效' : '已停用'}</td><td><Link to={contacts
              ? `/accounts/${(row as Contact).account_id}` : `/accounts/${row.id}`}>
              {contacts ? '所属客户 / 联系人' : '查看详情'}</Link></td></tr>)}</tbody></table></div>}
        <Pager page={page} total={query.data.page.total} onPage={setPage} /></>}
  </section>;
}

function AccountDetail({ session }: { session: SessionData }) {
  const { id } = useParams();
  const cache = useQueryClient();
  const [edit, setEdit] = useState(false), [contact, setContact] = useState<Contact | 'new' | null>(null);
  const [page, setPage] = useState(1), [saved, setSaved] = useState('');
  const [refreshWarning, setRefreshWarning] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const account = useQuery({ queryKey: ['crm', 'account', id], retry: false,
    queryFn: () => request<Account>(`/api/v1/accounts/${id}`) });
  const contacts = useQuery({ queryKey: ['crm', 'accountContacts', id, page], retry: false,
    queryFn: () => request<PageData<Contact>>(`/api/v1/accounts/${id}/contacts?page=${page}`, {}, true) });
  const refresh = async () => {
    await cache.invalidateQueries({ queryKey: ['crm'] }, { throwOnError: true });
  };
  if (account.isPending) return <Loading />;
  if (account.error && (!account.data || !saved || (account.error instanceof ApiError
    && [401, 403].includes(account.error.status)))) return <>
    {saved && <p role="status">{saved}</p>}
    <ErrorState message={account.error.message} onRetry={() => void account.refetch()} /></>;
  const data = account.data!, canEdit = writable(session, data);
  return <section className="panel crm-panel"><Link to="/accounts">← 客户列表</Link>
    <h1>{data.name}</h1><p>负责人：{data.owner.name} · {data.is_active ? '有效' : '已停用'} · 版本 {data.version}</p>
    <p>行业：{data.industry || '未知'} · 规模：{data.company_size || '未知'}</p>
    {data.website && <a href={data.website} target="_blank" rel="noreferrer">{data.website}</a>}
    <p className="crm-description">{data.description || '尚无客户说明'}</p>
    {saved && <p role="status">{saved}</p>}
    {refreshWarning && <div role="alert"><p>{refreshWarning}</p>
      <button type="button" disabled={refreshing} onClick={async () => {
        setRefreshing(true);
        try { await refresh(); setRefreshWarning(''); setSaved('联系人已保存并从服务端刷新。'); }
        catch { /* Keep the confirmed write and warning; retry only GET requests. */ }
        finally { setRefreshing(false); }
      }}>{refreshing ? '正在刷新…' : '重试刷新'}</button></div>}
    {account.error && <ErrorState message={account.error.message} onRetry={() => void account.refetch()} />}
    {canEdit && !edit && <button onClick={() => { setSaved(''); setEdit(true); }}>编辑客户</button>}
    {edit && canEdit && <AccountForm key={data.id} session={session} initial={data}
      onCancel={() => setEdit(false)} onSaved={async () => {
        await refresh(); setEdit(false); setSaved('客户已保存并从服务端刷新。');
      }} />}
    <h2>联系人</h2>
    {canEdit && data.is_active && <button onClick={() => { setSaved(''); setContact('new'); }}>创建联系人</button>}
    {contact && canEdit && <ContactForm key={contact === 'new' ? 'new' : contact.id}
      accountId={data.id} initial={contact === 'new' ? undefined : contact}
      onCancel={() => setContact(null)} onSaved={async () => {
        // Close the committed form before refreshing, including if queries temporarily fail.
        setContact(null); setSaved('联系人已保存。'); setRefreshWarning('');
        try { await refresh(); setSaved('联系人已保存并从服务端刷新。'); }
        catch { setRefreshWarning('联系人已保存，但列表刷新失败。请仅重试刷新，不要重复创建。'); }
      }} />}
    {contacts.isPending ? <Loading /> : contacts.error
      ? <ErrorState message={contacts.error.message} onRetry={() => void contacts.refetch()} />
      : <>{!contacts.data.data.length ? <EmptyState title="暂无联系人" description="可为有效客户创建联系人。" />
        : <div className="crm-table"><table><thead><tr><th>姓名</th><th>职位</th><th>邮箱 / 电话</th>
          <th>决策角色</th><th>状态</th><th>操作</th></tr></thead><tbody>{contacts.data.data.map(row =>
          <tr key={row.id}><td>{row.name}</td><td>{row.title || '—'}</td><td>{row.email || '—'} / {row.phone || '—'}</td>
            <td>{row.decision_role}</td><td>{row.is_active ? '有效' : '已停用'}</td><td>
              {canEdit && <button onClick={() => setContact(row)}>编辑联系人</button>}</td></tr>)}</tbody></table></div>}
        <Pager page={page} total={contacts.data.page.total} onPage={setPage} /></>}
  </section>;
}

export function CRMWorkspace({ session }: { session: SessionData }) {
  return <Routes><Route path="/accounts" element={<Directory session={session} />} />
    <Route path="/accounts/:id" element={<AccountDetail session={session} />} />
    <Route path="/contacts" element={<Directory session={session} contacts />} /></Routes>;
}
