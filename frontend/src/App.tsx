import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Navigate, Route, Routes, useNavigate, useLocation, Link } from 'react-router-dom';
import { BookOpen, ChevronRight, Command, LayoutDashboard, LogOut, ShieldCheck,
  Target, Users, Activity, PanelLeftClose } from 'lucide-react';
import { ApiError, authApi, request, type Capabilities, type SessionData } from './api';
import { EmptyState, ErrorState, Loading } from './components';
import { CRMWorkspace } from './crm';
import { SalesWorkspace } from './sales';
import { Profile, Register, UsersWorkspace } from './users';
import { userEmail } from './user-validation';

const loginSchema = z.object({
  email: userEmail,
  password: z.string().min(1, '请输入密码。').max(128, '密码过长。'),
});

export function Login() {
  const location = useLocation();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [error, setError] = useState('');
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm({
    resolver: zodResolver(loginSchema), defaultValues: { email: '', password: '' },
  });
  return <main className="login-page"><section className="login-story">
    <Link className="brand" to="/"><Command /> SALES COPILOT</Link>
    <div><span className="eyebrow">ENTERPRISE WORKSPACE</span><h1>让每一次跟进，<br />都有清晰的依据。</h1>
      <p>连接销售流程与 AI 辅助能力。以可信数据、明确权限和人工审核，构建企业销售工作空间。</p></div>
    <small>Enterprise Sales Copilot · M2 CRM 工作空间</small>
  </section><section className="login-panel"><form noValidate onSubmit={handleSubmit(async (values) => {
    setError('');
    try {
      const session = await authApi.login(values.email, values.password);
      cache.setQueryData(['session'], session);
      navigate('/', { replace: true });
    } catch (err) { setError(err instanceof Error ? err.message : '登录失败，请重试。'); }
  })}>
    <span className="eyebrow">安全访问</span><h2>登录工作空间</h2><p className="muted">使用已批准的企业账号。</p>
    {location.state?.notice && <p role="status">{String(location.state.notice)}</p>}
    <label htmlFor="email">邮箱</label><input id="email" type="email" autoComplete="username"
      aria-invalid={!!errors.email} {...register('email')} />
    {errors.email && <p className="field-error" role="alert">{errors.email.message}</p>}
    <label htmlFor="password">密码</label><input id="password" type="password" autoComplete="current-password"
      aria-invalid={!!errors.password} {...register('password')} />
    {errors.password && <p className="field-error" role="alert">{errors.password.message}</p>}
    {error && <ErrorState message={error} />}
    <button className="primary" type="submit" disabled={isSubmitting}>
      {isSubmitting ? '正在登录…' : '进入工作空间'}<ChevronRight size={16} /></button>
    <p className="login-note"><ShieldCheck size={16} />受保护的会话 · 注册后需管理员批准</p>
    <Link to="/register">注册账号</Link><p>忘记密码？请联系管理员重置。</p>
  </form></section></main>;
}

function StatusPanel() {
  const query = useQuery({ queryKey: ['capabilities'], queryFn: () => request<Capabilities>(
    '/api/v1/capabilities'), retry: false, refetchInterval: 30000 });
  if (query.isPending) return <Loading text="正在检查服务能力…" />;
  if (query.error) return <ErrorState message={query.error.message} onRetry={() => void query.refetch()} />;
  const data = query.data;
  const services = [
    ['数据库基础', data.crm.available ? '就绪' : '不可用', data.crm.available],
    ['对象存储', data.storage.available ? '可访问' : '不可用', data.storage.available],
    ['AI 适配层', data.ai.mode === 'MOCK' ? 'MOCK · 仅适配骨架' : 'REAL · 尚未启用', false],
    ['知识库', '后续阶段 · 未实现', false],
    ['Worker', '基础进程 · 无业务处理器', false],
  ] as const;
  return <section className="panel"><header className="panel-title"><h2>环境与能力状态</h2>
    <span>每 30 秒检查</span></header><div className="service-list">{services.map(([name, label, ok]) =>
    <div key={name}><span><i className={ok ? 'dot ok' : 'dot'} />{name}</span>
      <span className="service-value">{label}</span></div>)}</div>
    <p className="panel-note">状态来自服务端实际配置与依赖检查。Mock 不代表真实模型生成能力。</p></section>;
}

function Workspace({ session }: { session: SessionData }) {
  const location = useLocation();
  const crmPage = location.pathname.startsWith('/accounts') || location.pathname === '/contacts';
  const salesPage = location.pathname.startsWith('/opportunities') || ['/activities', '/audit-events'].includes(location.pathname);
  const usersPage = location.pathname.startsWith('/users');
  const profilePage = location.pathname === '/profile';
  const cache = useQueryClient();
  const navigate = useNavigate();
  const [logoutError, setLogoutError] = useState('');
  const [loggingOut, setLoggingOut] = useState(false);
  const items = [[LayoutDashboard, '工作空间', 'M2'], [Target, '销售商机', 'M2'],
    [Users, '客户与联系人', 'M2'], [Activity, '销售活动', 'M2'], [BookOpen, '企业知识库', 'M4'],
    [ShieldCheck, '审计日志', 'M2'], [Users, '用户管理', 'M2.1'], [ShieldCheck, '个人账号', 'M2.1']] as const;
  return <div className="workspace"><aside className="sidebar">
    <Link to="/" className="brand"><Command size={23} /><span>SALES COPILOT<small>ENTERPRISE</small></span></Link>
    <div className="workspace-label">销售工作空间 <PanelLeftClose size={14} /></div>
    <nav aria-label="主导航">{items.map(([Icon, name, stage], index) => index === 6 && session.user.role !== 'ADMIN' ? null : <button key={name}
      className={(usersPage ? index === 6 : profilePage ? index === 7 : salesPage ? index === (location.pathname === '/activities' ? 3 : location.pathname === '/audit-events' ? 5 : 1) : crmPage ? index === 2 : index === 0) ? 'nav-item selected' : 'nav-item'}
      disabled={index === 4 || (index === 5 && !['ADMIN', 'SALES_MANAGER'].includes(session.user.role))}
      onClick={() => navigate(index === 6 ? '/users' : index === 7 ? '/profile' : index === 2 ? '/accounts' : index === 1 ? '/opportunities' : index === 3 ? '/activities' : index === 5 ? '/audit-events' : '/')}
      title={index === 4 ? `${stage} 交付，当前不可用` : undefined}>
      <Icon size={17} /><span>{name}</span><small>{stage}</small></button>)}</nav>
    <div className="sidebar-foot"><ShieldCheck size={17} /><span>后端权限校验<small>单企业 · 安全会话</small></span></div>
  </aside><div className="workspace-main"><header className="topbar">
    <div>工作空间 <ChevronRight size={14} /><strong>{usersPage ? '用户与权限' : profilePage ? '个人账号' : salesPage ? '销售商机' : crmPage ? '客户与联系人' : '概览'}</strong></div>
    <span className="phase">{usersPage || profilePage ? 'M2.1 / USERS' : salesPage ? 'M2 / SALES' : crmPage ? 'M2-A / CRM' : 'M2 / WORKSPACE'}</span><div className="identity"><span className="avatar">{session.user.name.slice(0, 1)}</span>
      <span>{session.user.name}<small>{session.user.role}</small></span>
      <button aria-label="退出登录" title="退出登录" disabled={loggingOut} onClick={async () => {
        setLoggingOut(true); setLogoutError('');
        try { await authApi.logout(); cache.clear(); navigate('/login', { replace: true }); }
        catch (err) { setLogoutError(err instanceof Error ? err.message : '退出失败'); }
        finally { setLoggingOut(false); }
      }}><LogOut size={16} /></button></div>
    </header><main className="content">{logoutError && <ErrorState message={logoutError} />}
      {usersPage ? <UsersWorkspace session={session} /> : profilePage ? <Profile /> : salesPage ? <SalesWorkspace session={session} /> : crmPage ? <CRMWorkspace session={session} /> : <>
      <div className="page-heading"><div><span className="eyebrow">WORKSPACE / OVERVIEW</span>
        <h1>工作空间概览</h1><p>CRM 核心流程与用户管理已接入，AI 和知识库仍在后续阶段。</p></div>
        <span className="outline-badge">M2 · CRM 与用户管理</span></div>
      <div className="overview-grid"><section className="panel welcome">
        <span className="eyebrow">WELCOME, {session.user.name}</span><h2>为销售业务建立可靠的起点</h2>
        <p>客户、联系人、商机、成交证据和用户管理已接入真实服务。AI 与知识库仍在后续阶段。</p>
        <div className="milestone"><span>01</span><div><strong>工程基础设施</strong><small>会话 / MySQL / 对象存储 / 服务状态</small></div>
          <span className="outline-badge">已验收</span></div>
        <div className="milestone future"><span>02</span><div><strong>CRM 核心业务</strong><small>客户 / 商机 / 状态机 / 审计</small></div>
          <span>当前阶段</span></div>
      </section><StatusPanel /></div>
      <section className="panel"><header className="panel-title"><h2>销售业务区域</h2><span>M2 起交付</span></header>
        <EmptyState title="进入销售商机查看 Pipeline" description="客户与联系人、商机和成交证据已接入真实 API。知识库与 AI 仍待后续阶段交付。" /></section>
      <footer>Enterprise Sales Copilot · 单企业工作空间<span>会话身份由后端验证</span></footer>
      </>}
    </main></div></div>;
}

export function ProtectedWorkspace() {
  const session = useQuery({ queryKey: ['session'], queryFn: authApi.me, retry: false,
    refetchOnWindowFocus: true, staleTime: 0 });
  if (session.isPending) return <Loading />;
  if (session.error instanceof ApiError && session.error.status === 401) return <Navigate to="/login" replace />;
  if (session.error) return <ErrorState message={session.error.message} onRetry={() => void session.refetch()} />;
  return <Workspace session={session.data!} />;
}

export default function App() {
  return <Routes><Route path="/login" element={<Login />} />
    <Route path="/register" element={<Register />} />
    <Route path="/*" element={<ProtectedWorkspace />} /></Routes>;
}
