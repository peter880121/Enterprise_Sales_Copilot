import { useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ApiError, request, setCsrfToken, type Role, type SessionData } from './api';
import { EmptyState, ErrorState, Loading } from './components';
import { newPassword, registrationSchema, roles, userEmail } from './user-validation';
import './crm.css';

export type ManagedUser = { id: string; name: string; email: string; role: Role; is_active: boolean;
  registration_status: string; deleted_at: string | null; version: number; created_at: string; updated_at: string };
type Paged<T> = { data: T[]; page: { number: number; size: number; total: number } };
type UserAudit = { id: string; action: string; actor_id: string | null; reason: string | null;
  created_at: string; before_state: Record<string, unknown> | null; after_state: Record<string, unknown> | null };
const roleLabels: Record<Role, string> = { ADMIN: '管理员', SALES_MANAGER: '销售经理', SALES_REP: '销售人员', READ_ONLY: '只读用户' };
const assignedRole = (user: ManagedUser) => user.registration_status === 'PENDING' ? '未分配' : roleLabels[user.role];
export const userStatus = (user: ManagedUser) => user.deleted_at ? '已删除' : user.registration_status === 'PENDING' ? '待批准' : user.is_active ? '正常' : '已停用';
const errorText = (err: unknown) => err instanceof ApiError && err.code === 'VERSION_CONFLICT'
  ? '用户已被更新，当前输入已保留。请取消编辑并重新加载后确认。'
  : err instanceof Error ? err.message : '请求失败，请重试。';

export function Register() {
  const [error, setError] = useState(''), [done, setDone] = useState(false);
  const committed = useRef(false);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm({ resolver: zodResolver(registrationSchema),
    defaultValues: { name: '', email: '', password: '', confirm_password: '' } });
  return <main className="login-page"><section className="panel crm-panel"><Link to="/login">← 返回登录</Link>
    <h1>申请企业账号</h1><p>提交申请后，由管理员批准并分配角色。批准前不能登录或访问企业数据。</p>
    {done ? <div role="status"><h2>注册申请已提交</h2><p>若资料可用，请等待管理员批准；已有账号请直接登录或联系管理员。</p><Link to="/login">前往登录</Link></div>
      : <form className="crm-form" noValidate onSubmit={handleSubmit(async values => {
        if (committed.current) return;
        setError('');
        try { await request('/api/v1/auth/register', { method: 'POST', body: JSON.stringify({ name: values.name, email: values.email, password: values.password }) }); committed.current = true; setDone(true); }
        catch (err) { setError(errorText(err)); }
      })}>
        <label>姓名<input {...register('name')} autoComplete="name" /></label>
        <label>注册邮箱<input {...register('email')} autoComplete="username" /></label>
        <label>注册密码<input type="password" {...register('password')} autoComplete="new-password" /></label>
        <label>确认注册密码<input type="password" {...register('confirm_password')} autoComplete="new-password" /></label>
        <p>密码12—128个字符；请勿使用真实业务系统的密码。</p>
        {Object.entries(errors).map(([key, value]) => <p role="alert" key={key}>{value.message}</p>)}
        {error && <ErrorState message={error} />}<button className="primary" disabled={isSubmitting}>提交注册申请</button>
      </form>}
  </section></main>;
}

function RoleSelect({ value, onChange }: { value: Role; onChange: (role: Role) => void }) {
  return <select value={value} onChange={e => onChange(e.target.value as Role)}>{roles.map(role => <option key={role} value={role}>{roleLabels[role]}</option>)}</select>;
}

function RoleMatrix() {
  const query = useQuery({ queryKey: ['user-roles'], queryFn: () => request<{ role: Role; description: string }[]>('/api/v1/users/roles') });
  return <details><summary>角色与权限说明</summary>{query.isPending ? <Loading /> : query.error ? <ErrorState message={query.error.message} />
    : query.data?.map(role => <p key={role.role}><strong>{roleLabels[role.role]}</strong>：{role.description}</p>)}</details>;
}

const createSchema = z.object({ name: z.string().trim().min(1).max(100), email: userEmail, password: newPassword, role: z.enum(roles), is_active: z.boolean() });
export function CreateUserForm({ onSaved, onCancel }: { onSaved: (user: ManagedUser) => void | Promise<void>; onCancel: () => void }) {
  const [error, setError] = useState(''), [saved, setSaved] = useState(false); const committed = useRef(false);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm({ resolver: zodResolver(createSchema), defaultValues: { name: '', email: '', password: '', role: 'SALES_REP' as Role, is_active: true } });
  return <form className="crm-form" noValidate onSubmit={handleSubmit(async values => {
    if (committed.current) return;
    setError('');
    let user: ManagedUser;
    try { user = await request<ManagedUser>('/api/v1/users', { method: 'POST', body: JSON.stringify(values) }); }
    catch (err) { setError(errorText(err)); return; }
    committed.current = true; setSaved(true);
    try { await onSaved(user); } catch { setError('用户已创建，但后续读取失败。请重新加载，不要重复创建。'); }
  })}><h2>创建用户</h2><label>姓名<input {...register('name')} /></label><label>用户邮箱<input {...register('email')} /></label>
    <label>初始密码<input type="password" autoComplete="new-password" {...register('password')} /></label>
    <label>用户角色<select {...register('role')}>{roles.map(role => <option key={role} value={role}>{roleLabels[role]}</option>)}</select></label>
    <label>立即启用<input type="checkbox" {...register('is_active')} /></label>
    {Object.entries(errors).map(([key, value]) => <p key={key} role="alert">{value.message}</p>)}
    {saved && <p role="status">用户已创建。</p>}{error && <ErrorState message={error} />}<button className="primary" disabled={isSubmitting || saved}>保存新用户</button><button type="button" onClick={onCancel} disabled={isSubmitting}>取消创建</button>
  </form>;
}

function UserDirectory() {
  const [q, setQ] = useState(''), [role, setRole] = useState(''), [status, setStatus] = useState(''), [page, setPage] = useState(1), [creating, setCreating] = useState(false);
  const navigate = useNavigate(), cache = useQueryClient();
  const params = new URLSearchParams({ q, page: String(page), ...(role ? { role } : {}), ...(status ? { status } : {}) });
  const query = useQuery({ queryKey: ['users', q, role, status, page], queryFn: () => request<Paged<ManagedUser>>(`/api/v1/users?${params}`, {}, true) });
  return <section className="panel crm-panel"><h1>用户与角色管理</h1><p>新注册申请须管理员批准。用户停用或删除不会移除历史业务关联。</p><RoleMatrix />
    <div className="crm-actions"><label>搜索用户<input value={q} onChange={e => { setQ(e.target.value); setPage(1); }} /></label>
      <label>角色筛选<select value={role} onChange={e => { setRole(e.target.value); setPage(1); }}><option value="">全部角色</option>{roles.map(r => <option key={r} value={r}>{roleLabels[r]}</option>)}</select></label>
      <label>状态筛选<select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">全部未删除</option>{[['PENDING', '待批准'], ['ACTIVE', '正常'], ['DISABLED', '已停用'], ['DELETED', '已删除']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <button className="primary" onClick={() => setCreating(true)}>创建用户</button></div>
    {creating && <CreateUserForm onCancel={() => setCreating(false)} onSaved={user => { setCreating(false); void cache.invalidateQueries({ queryKey: ['users'] }); navigate(`/users/${user.id}`); }} />}
    {query.isPending ? <Loading /> : query.error ? <ErrorState message={query.error.message} onRetry={() => void query.refetch()} />
      : !query.data.data.length ? <EmptyState title="没有匹配用户" description="调整筛选条件，或创建用户。" /> : <div className="crm-table"><table><thead><tr><th>姓名</th><th>邮箱</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>{query.data.data.map(user => <tr key={user.id}><td>{user.name}</td><td>{user.email}</td><td>{assignedRole(user)}</td><td>{userStatus(user)}</td><td><Link to={`/users/${user.id}`}>用户详情</Link></td></tr>)}</tbody></table></div>}
    <div className="crm-actions"><button disabled={page === 1 || query.isFetching} onClick={() => setPage(page - 1)}>用户上一页</button><span>第 {page} 页 · 共 {query.data?.page.total ?? '—'} 人</span><button disabled={!query.data || query.isFetching || page * 20 >= query.data.page.total} onClick={() => setPage(page + 1)}>用户下一页</button></div>
  </section>;
}

const editSchema = z.object({ name: z.string().trim().min(1).max(100), email: userEmail, role: z.enum(roles), reason: z.string().trim().min(1).max(2000) });
export function EditUserForm({ user, onSaved, onCancel }: { user: ManagedUser; onSaved: (user: ManagedUser) => void; onCancel: () => void }) {
  const [version] = useState(user.version), [error, setError] = useState('');
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm({ resolver: zodResolver(editSchema), defaultValues: { name: user.name, email: user.email, role: user.role, reason: '' } });
  return <form className="crm-form" noValidate onSubmit={handleSubmit(async values => {
    setError(''); try { const saved = await request<ManagedUser>(`/api/v1/users/${user.id}`, { method: 'PATCH', body: JSON.stringify({ ...values, expected_version: version }) }); onSaved(saved); } catch (err) { setError(errorText(err)); }
  })}><h2>编辑用户</h2><label>编辑姓名<input {...register('name')} /></label><label>编辑邮箱<input {...register('email')} /></label>
    <label>分配角色<select {...register('role')}>{roles.map(role => <option key={role} value={role}>{roleLabels[role]}</option>)}</select></label>
    <label>修改原因<textarea {...register('reason')} /></label><p>保存后将撤销该用户现有会话，需重新登录。</p>
    {Object.entries(errors).map(([key, value]) => <p key={key} role="alert">{value.message}</p>)}{error && <ErrorState message={error} />}
    <button disabled={isSubmitting}>保存用户修改</button><button type="button" disabled={isSubmitting} onClick={onCancel}>取消编辑</button></form>;
}

type Action = 'approve' | 'toggle' | 'delete' | 'restore' | 'reset-password';
function UserActionForm({ target, action, onDone, onCancel }: { target: ManagedUser; action: Action; onDone: (user: ManagedUser) => void; onCancel: () => void }) {
  const [reason, setReason] = useState(''), [role, setRole] = useState<Role>('SALES_REP'), [password, setPassword] = useState(''), [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''); const intent = useRef({ body: '', key: '' });
  const labels: Record<Action, string> = { approve: '批准注册', toggle: target.is_active ? '停用用户' : '启用用户', delete: '删除用户', restore: '恢复用户', 'reset-password': '重置密码' };
  return <form className="crm-form" onSubmit={async e => { e.preventDefault(); setError('');
    if (action === 'reset-password' && (!newPassword.safeParse(password).success || password !== confirm)) { setError('新密码须12—128个字符，且两次输入一致。'); return; }
    if (!window.confirm(`确认${labels[action]}“${target.name}”？现有会话将失效，历史业务关联保留。`)) return;
    const body = JSON.stringify({ expected_version: target.version, reason, ...(action === 'approve' ? { role } : {}), ...(action === 'toggle' ? { is_active: !target.is_active } : {}), ...(action === 'reset-password' ? { new_password: password } : {}) });
    if (body !== intent.current.body) intent.current = { body, key: crypto.randomUUID() };
    setBusy(true);
    try { const saved = await request<ManagedUser>(`/api/v1/users/${target.id}${['toggle', 'delete'].includes(action) ? '' : `/${action}`}`, { method: action === 'toggle' ? 'PATCH' : action === 'delete' ? 'DELETE' : 'POST', headers: action === 'reset-password' ? { 'Idempotency-Key': intent.current.key } : {}, body }); onDone(saved); }
    catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }}><h2>{labels[action]}</h2><label>操作原因<textarea required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label>
    {action === 'approve' && <label>批准后角色<RoleSelect value={role} onChange={setRole} /></label>}
    {action === 'reset-password' && <><label>新密码<input type="password" autoComplete="new-password" required value={password} onChange={e => setPassword(e.target.value)} /></label><label>确认新密码<input type="password" autoComplete="new-password" required value={confirm} onChange={e => setConfirm(e.target.value)} /></label></>}
    {error && <ErrorState message={error} />}<button disabled={busy}>确认{labels[action]}</button><button type="button" disabled={busy} onClick={onCancel}>取消操作</button>
  </form>;
}

export function UserHistory({ userId }: { userId: string }) {
  const [page, setPage] = useState(1);
  const history = useQuery({ queryKey: ['user-history', userId, page], queryFn: () =>
    request<Paged<UserAudit>>(`/api/v1/users/${userId}/history?page=${page}&page_size=20`, {}, true) });
  return <section aria-label="用户操作审计"><h2>用户操作审计</h2>
    {history.isPending ? <Loading /> : history.error ? <ErrorState message={history.error.message} onRetry={() => void history.refetch()} />
      : !history.data.data.length ? <p>暂无用户操作审计。</p> : history.data.data.map(event => <article key={event.id}>
        <p>{event.created_at} · {event.action} · 操作者：{event.actor_id || '匿名注册'} · {event.reason || '—'}</p>
        <details><summary>查看字段变更</summary><div className="crm-table"><table><thead><tr><th>字段</th><th>变更前</th><th>变更后</th></tr></thead>
          <tbody>{Object.keys({ ...event.before_state, ...event.after_state }).filter(field =>
            JSON.stringify(event.before_state?.[field]) !== JSON.stringify(event.after_state?.[field])).map(field => <tr key={field}>
              <td>{field}</td><td>{JSON.stringify(event.before_state?.[field] ?? null)}</td><td>{JSON.stringify(event.after_state?.[field] ?? null)}</td>
            </tr>)}</tbody></table></div></details>
      </article>)}
    <div className="crm-actions"><button disabled={page === 1 || history.isFetching} onClick={() => setPage(page - 1)}>审计上一页</button>
      <span>审计第 {page} 页 · 共 {history.data?.page.total ?? '—'} 条</span>
      <button disabled={!history.data || !!history.error || history.isFetching || page * 20 >= history.data.page.total} onClick={() => setPage(page + 1)}>审计下一页</button></div>
  </section>;
}

function UserDetail({ session }: { session: SessionData }) {
  const { id } = useParams(), cache = useQueryClient(), navigate = useNavigate();
  const [editing, setEditing] = useState<ManagedUser | null>(null), [action, setAction] = useState<{ kind: Action; target: ManagedUser } | null>(null), [notice, setNotice] = useState('');
  const query = useQuery({ queryKey: ['user', id], queryFn: () => request<ManagedUser>(`/api/v1/users/${id}`) });
  function saved(user: ManagedUser) {
    setEditing(null); setAction(null); setNotice('操作已保存，目标用户需重新登录。');
    if (user.id === session.user.id) { setCsrfToken(); cache.clear(); navigate('/login', { replace: true, state: { notice: '账号已更新，请重新登录。' } }); return; }
    cache.setQueryData(['user', id], user); void cache.invalidateQueries({ queryKey: ['users'] }); void cache.invalidateQueries({ queryKey: ['user-history', id] });
    void cache.invalidateQueries({ queryKey: ['user', id] });
  }
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorState message={`${notice ? '操作已保存，但最新用户资料读取失败。' : ''}${query.error.message}`} onRetry={() => void query.refetch()} />;
  const user = query.data!;
  return <section className="panel crm-panel"><Link to="/users">← 用户列表</Link><h1>{user.name}</h1><p>{user.email} · {assignedRole(user)} · {userStatus(user)} · 版本 {user.version}</p><p>创建于 {user.created_at}；更新于 {user.updated_at}</p>
    <button onClick={() => void query.refetch()}>重新加载用户</button>{notice && <p role="status">{notice}</p>}
    {!editing && !action && <div className="crm-actions">{!user.deleted_at ? <>
      <button onClick={() => setEditing({ ...user })}>编辑用户</button>
      {user.registration_status === 'PENDING' ? <button onClick={() => setAction({ kind: 'approve', target: { ...user } })}>批准注册</button> : <button onClick={() => setAction({ kind: 'toggle', target: { ...user } })}>{user.is_active ? '停用用户' : '启用用户'}</button>}
      <button onClick={() => setAction({ kind: 'reset-password', target: { ...user } })}>重置密码</button><button onClick={() => setAction({ kind: 'delete', target: { ...user } })}>删除用户</button>
    </> : <button onClick={() => setAction({ kind: 'restore', target: { ...user } })}>恢复用户</button>}</div>}
    {editing && <EditUserForm user={editing} onSaved={saved} onCancel={() => setEditing(null)} />}
    {action && <UserActionForm key={action.kind} target={action.target} action={action.kind} onDone={saved} onCancel={() => setAction(null)} />}
    <p className="muted">删除仅撤销访问并标记删除，负责人、成交核验及审计关联均保留；需要转交业务时由有权限人员另行调整。</p>
    <UserHistory key={user.id} userId={user.id} />
  </section>;
}

export function Profile() {
  const query = useQuery({ queryKey: ['profile'], queryFn: () => request<{ user: ManagedUser }>('/api/v1/auth/me') });
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorState message={query.error.message} onRetry={() => void query.refetch()} />;
  return <ProfileForms user={query.data!.user} />;
}
function ProfileForms({ user }: { user: ManagedUser }) {
  const [name, setName] = useState(user.name), [email, setEmail] = useState(user.email), [current, setCurrent] = useState(''), [password, setPassword] = useState(''), [confirm, setConfirm] = useState('');
  const [version] = useState(user.version), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const navigate = useNavigate(), cache = useQueryClient();
  async function submit(changePassword: boolean) {
    setError('');
    if (changePassword ? !newPassword.safeParse(password).success || password !== confirm : !name.trim() || !userEmail.safeParse(email).success) { setError('请检查姓名、邮箱及密码格式，两次新密码须一致。'); return; }
    setBusy(true);
    try { await request(changePassword ? '/api/v1/auth/change-password' : '/api/v1/auth/profile', { method: changePassword ? 'POST' : 'PATCH', body: JSON.stringify(changePassword ? { current_password: current, new_password: password } : { expected_version: version, name, email, current_password: current }) }); setCsrfToken(); cache.clear(); navigate('/login', { replace: true, state: { notice: '修改已保存，请重新登录。' } }); }
    catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  return <section className="panel crm-panel"><h1>个人账号</h1><p>角色：{roleLabels[user.role]}。角色和账号状态由管理员管理。</p>
    <label>验证当前密码<input type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} /></label>
    <form className="crm-form" onSubmit={e => { e.preventDefault(); void submit(false); }}><h2>个人资料</h2><label>个人姓名<input required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></label><label>个人邮箱<input required value={email} onChange={e => setEmail(e.target.value)} /></label><button disabled={busy || !current}>保存个人资料</button></form>
    <form className="crm-form" onSubmit={e => { e.preventDefault(); void submit(true); }}><h2>修改密码</h2><label>新的登录密码<input type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} /></label><label>再次确认新密码<input type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} /></label><button disabled={busy || !current}>修改登录密码</button></form>
    {error && <ErrorState message={error} />}<p>资料或密码保存后，现有会话将撤销。忘记密码请联系管理员重置。</p>
  </section>;
}

export function UsersWorkspace({ session }: { session: SessionData }) {
  if (session.user.role !== 'ADMIN') return <ErrorState message="当前账号没有用户管理权限。" />;
  return <Routes><Route path="/users" element={<UserDirectory />} /><Route path="/users/:id" element={<UserDetail key={window.location.pathname} session={session} />} /></Routes>;
}
