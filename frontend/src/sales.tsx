import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { ApiError, request, type SessionData } from './api';
import { ErrorState, Loading } from './components';
import { CRMSelector } from './crm-selector';
import './sales.css';

export const stages = ['PROPOSAL_SUBMITTED', 'NEGOTIATION', 'FOLLOW_UP', 'WON', 'LOST'] as const;
const names: Record<string, string> = { PROPOSAL_SUBMITTED: '方案已提交', NEGOTIATION: '谈判中', FOLLOW_UP: '跟进中', WON: '已成交', LOST: '已丢单' };
const openStages = new Set<string>(stages.slice(0, 3));
type Opportunity = {
  id: string; name: string; account_id: string; owner_id: string; stage: string;
  amount: string | null; currency: string; weighted_amount: string | null;
  actual_amount: string | null; actual_currency: string | null; probability: number;
  priority: string; source: string; primary_contact_id: string | null;
  expected_close_date: string | null; version: number; is_archived: boolean;
  account: { name: string }; owner: { name: string };
};
type Page<T> = { data: T[]; page: { number: number; size: number; total: number } };
type Proof = { id: string; type: string; status: string; amount: string; currency: string;
  version: number; submitted_by: string; reviewed_by: string | null; verification_note: string | null };
type Group = { currency: string; pipeline_value: string | null; weighted_forecast: string | null;
  unknown_amount_count: number; closed_won_actual_amount: string; stages: { stage: string; count: number }[] };
const managers = (s: SessionData) => ['ADMIN', 'SALES_MANAGER'].includes(s.user.role);
export const moneyLabel = (value: string | null, currency: string) => value === null ? '金额待确认' : `${currency} ${value}`;
export const salesError = (err: unknown) => err instanceof ApiError
  ? err.code === 'EVIDENCE_REVIEWER_CONFLICT' ? '提交人不能自核验，请更换另一位有权限的经理或管理员。'
    : err.code === 'CSRF_INVALID' ? '请求安全校验失败，请刷新会话后重新确认提交。'
    : err.code === 'FORBIDDEN' ? '当前账号没有该操作权限。'
    : err.status === 409 ? `${err.message} 请重新加载并确认；当前输入已保留。`
    : err.message
  : err instanceof Error ? err.message : '请求失败。';

export const opportunitySchema = z.object({
  name: z.string().trim().min(1).max(200), account_id: z.uuid(),
  amount: z.string().refine(v => v === '' || /^(0|[1-9][0-9]{0,15})(\.[0-9]{1,2})?$/.test(v), '金额最多两位小数，不支持负数或科学计数法。'),
  currency: z.enum(['CNY', 'USD', 'EUR', 'HKD']),
  priority: z.enum(['LOW', 'MEDIUM', 'HIGH']), expected_close_date: z.string(),
  primary_contact_id: z.string().refine(v => !v || z.uuid().safeParse(v).success),
  source: z.enum(['WEBSITE', 'PARTNER', 'REFERRAL', 'CAMPAIGN', 'EVENT', 'COLD_OUTREACH', 'EXISTING_CUSTOMER', 'OTHER', 'UNKNOWN']),
});

export function OpportunityForm({ initial, onDone }: { initial?: Opportunity; onDone: (o: Opportunity) => void }) {
  const [error, setError] = useState('');
  const [version] = useState(initial?.version);
  const { register, handleSubmit, watch, setValue, formState: { errors, isSubmitting } } = useForm({
    resolver: zodResolver(opportunitySchema), defaultValues: {
      name: initial?.name || '', account_id: initial?.account_id || '', amount: initial?.amount ?? '',
      currency: (initial?.currency || 'CNY') as 'CNY' | 'USD' | 'EUR' | 'HKD',
      priority: (initial?.priority || 'MEDIUM') as 'LOW' | 'MEDIUM' | 'HIGH', expected_close_date: initial?.expected_close_date || '',
      primary_contact_id: initial?.primary_contact_id || '',
      source: (initial?.source || 'UNKNOWN') as z.infer<typeof opportunitySchema>['source'],
    },
  });
  const accountId = watch('account_id');
  return <form className="crm-form" onSubmit={handleSubmit(async data => {
    setError('');
    const { account_id, ...fields } = data;
    try {
      const saved = await request<Opportunity>(`/api/v1/opportunities${initial ? `/${initial.id}` : ''}`, {
        method: initial ? 'PATCH' : 'POST', body: JSON.stringify({ ...fields, amount: data.amount || null,
          primary_contact_id: data.primary_contact_id || null,
          expected_close_date: data.expected_close_date || null,
          ...(initial ? { expected_version: version } : { account_id }) }),
      });
      onDone(saved);
    } catch (err) { setError(salesError(err)); }
  })}>
    <h2>{initial ? '编辑商机' : '创建商机'}</h2>
    <label>商机名称<input {...register('name')} /></label>
    <CRMSelector kind="accounts" value={accountId} disabled={!!initial} initialLabel={initial?.account.name}
      onChange={value => { if (value !== accountId) setValue('primary_contact_id', ''); setValue('account_id', value, { shouldValidate: true, shouldDirty: true }); }} />
    <CRMSelector key={accountId} kind="contacts" accountId={accountId} value={watch('primary_contact_id')}
      onChange={value => setValue('primary_contact_id', value, { shouldValidate: true, shouldDirty: true })} />
    <label>来源<select {...register('source')}>{['WEBSITE', 'PARTNER', 'REFERRAL', 'CAMPAIGN', 'EVENT', 'COLD_OUTREACH', 'EXISTING_CUSTOMER', 'OTHER', 'UNKNOWN'].map(s => <option key={s}>{s}</option>)}</select></label>
    <label>预计金额（留空表示未知）<input inputMode="decimal" {...register('amount')} /></label>
    <label>币种<select {...register('currency')}>{['CNY', 'USD', 'EUR', 'HKD'].map(c => <option key={c}>{c}</option>)}</select></label>
    <label>优先级<select {...register('priority')}>{['LOW', 'MEDIUM', 'HIGH'].map(c => <option key={c}>{c}</option>)}</select></label>
    <label>预计成交日期<input type="date" {...register('expected_close_date')} /></label>
    {Object.entries(errors).map(([key, err]) => <p role="alert" key={key}>{err?.message}</p>)}
    {error && <ErrorState message={error} />}<button className="primary" disabled={isSubmitting}>保存商机</button>
  </form>;
}

function Opportunities({ session }: { session: SessionData }) {
  const [q, setQ] = useState(''); const [stage, setStage] = useState('');
  const [currency, setCurrency] = useState(''); const [owner, setOwner] = useState('');
  const [page, setPage] = useState(1); const [board, setBoard] = useState(true);
  const [archived, setArchived] = useState(false);
  const [creating, setCreating] = useState(false); const navigate = useNavigate();
  const cache = useQueryClient();
  const filters = new URLSearchParams({ q, is_archived: String(archived), ...(stage ? { stage } : {}), ...(currency ? { currency } : {}), ...(owner ? { owner_id: owner } : {}) }).toString();
  const list = useQuery({ queryKey: ['opportunities', filters, page], queryFn: () => request<Page<Opportunity>>(`/api/v1/opportunities?${filters}&page=${page}`, {}, true) });
  const summary = useQuery({ queryKey: ['pipeline', filters], queryFn: () => request<{ currency_groups: Group[] }>(`/api/v1/pipeline/summary?${filters}`) });
  return <section className="panel crm-panel sales-panel"><span className="eyebrow">SALES / OPPORTUNITIES</span>
    <h1>销售商机</h1><p className="muted">阶段固定概率是业务配置，尚未经过历史数据校准。</p>
    <div className="crm-actions">
      <label>搜索<input value={q} onChange={e => { setQ(e.target.value); setPage(1); }} /></label>
      <label>阶段<select value={stage} onChange={e => { setStage(e.target.value); setPage(1); }}><option value="">全部</option>{stages.map(s => <option key={s} value={s}>{names[s]}</option>)}</select></label>
      <label>币种<select value={currency} onChange={e => { setCurrency(e.target.value); setPage(1); }}><option value="">全部币种</option>{['CNY', 'USD', 'EUR', 'HKD'].map(c => <option key={c}>{c}</option>)}</select></label>
      <label>负责人ID<input value={owner} onChange={e => { setOwner(e.target.value); setPage(1); }} /></label>
      <button onClick={() => setBoard(!board)}>{board ? '列表视图' : '看板视图'}</button>
      <label>已归档<input type="checkbox" checked={archived} onChange={e => { setArchived(e.target.checked); setPage(1); }} /></label>
      {session.user.role !== 'READ_ONLY' && <button className="primary" onClick={() => setCreating(!creating)}>创建商机</button>}
    </div>
    {creating && <OpportunityForm onDone={o => { void cache.invalidateQueries({ queryKey: ['opportunities'] }); navigate(`/opportunities/${o.id}`); }} />}
    <div className="pipeline-groups">{summary.data?.currency_groups.map(g => <article key={g.currency}>
      <strong>{g.currency} Pipeline</strong><h2>{moneyLabel(g.pipeline_value, g.currency)}</h2>
      <p>加权预计 {moneyLabel(g.weighted_forecast, g.currency)}</p><p>另 {g.unknown_amount_count} 笔金额待确认</p>
      <small>已核验实际成交 {moneyLabel(g.closed_won_actual_amount, g.currency)}</small>
    </article>)}</div>
    {summary.error && <ErrorState message={summary.error.message} />}
    {list.isPending && <Loading />}{list.error && <ErrorState message={list.error.message} />}
    {board ? <><p className="muted">卡片显示当前页；阶段数量为当前筛选范围总数。</p><div className="sales-board">{stages.map(s => <section key={s}>
      <h2>{names[s]} <small>{summary.data?.currency_groups.reduce((n, g) => n + (g.stages.find(x => x.stage === s)?.count || 0), 0) ?? '—'}</small></h2>
      {list.data?.data.filter(o => o.stage === s).map(o => <Link key={o.id} to={`/opportunities/${o.id}`} className="opportunity-card">
        <strong>{o.name}</strong><span>{o.account.name}</span><b>{moneyLabel(o.amount, o.currency)}</b>
        <small>{o.owner.name} · {o.priority}</small><small>预计成交 {o.expected_close_date || '待确认'}</small>
      </Link>)}
    </section>)}</div></> : <div className="crm-table"><table><thead><tr><th>商机</th><th>客户</th><th>阶段</th><th>预计金额</th><th>负责人</th></tr></thead>
      <tbody>{list.data?.data.map(o => <tr key={o.id}><td><Link to={`/opportunities/${o.id}`}>{o.name}</Link></td><td>{o.account.name}</td><td>{names[o.stage]}</td><td>{moneyLabel(o.amount, o.currency)}</td><td>{o.owner.name}</td></tr>)}</tbody></table></div>}
    <div className="crm-actions"><button disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} 页 · 共 {list.data?.page.total ?? 0} 笔</span><button disabled={page * 20 >= (list.data?.page.total || 0)} onClick={() => setPage(page + 1)}>下一页</button></div>
  </section>;
}

function OpportunityDetail({ session }: { session: SessionData }) {
  const { id } = useParams(); const cache = useQueryClient();
  const [editing, setEditing] = useState<Opportunity | null>(null);
  const [target, setTarget] = useState('NEGOTIATION'); const [reason, setReason] = useState('');
  const [proofId, setProofId] = useState(''); const [lossCode, setLossCode] = useState('BUDGET');
  const [reviewNote, setReviewNote] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [owner, setOwner] = useState('');
  const keys = useRef(new Map<string, string>());
  const detail = useQuery({ queryKey: ['opportunity', id], queryFn: () => request<Opportunity>(`/api/v1/opportunities/${id}`) });
  const proofs = useQuery({ queryKey: ['evidence', id], queryFn: () => request<Page<Proof>>(`/api/v1/opportunities/${id}/evidence`, {}, true) });
  const history = useQuery({ queryKey: ['history', id], queryFn: () => request<Page<{ id: string; action: string; created_at: string; reason: string | null }>>(`/api/v1/opportunities/${id}/history`, {}, true) });
  const activities = useQuery({ queryKey: ['activities', id], queryFn: () => request<Page<{ id: string; subject: string; content: string; type: string; status: string; version: number }>>(`/api/v1/opportunities/${id}/activities`, {}, true) });
  async function refresh() { await Promise.all([['opportunity', id], ['opportunities'], ['pipeline'], ['evidence', id], ['history', id], ['activities', id]].map(queryKey => cache.invalidateQueries({ queryKey }))); }
  async function command(path: string, body: object) {
    const intent = JSON.stringify({ path, body });
    if (!keys.current.has(intent)) keys.current.set(intent, crypto.randomUUID());
    setError(''); setBusy(true);
    try {
      await request(path, { method: 'POST', headers: { 'Idempotency-Key': keys.current.get(intent)! }, body: JSON.stringify(body) });
      await refresh();
    } catch (err) { setError(salesError(err)); } finally { setBusy(false); }
  }
  if (detail.isPending) return <Loading />;
  if (detail.error) return <ErrorState message={detail.error.message} />;
  const o = detail.data!; const canWrite = managers(session) || (session.user.role === 'SALES_REP' && session.user.id === o.owner_id);
  const allowed = ({ PROPOSAL_SUBMITTED: ['NEGOTIATION', 'FOLLOW_UP'],
    NEGOTIATION: ['FOLLOW_UP', 'WON', 'LOST'], FOLLOW_UP: ['NEGOTIATION', 'WON', 'LOST'] } as Record<string, string[]>)[o.stage] || [];
  const choices = allowed.filter(s => managers(session) || openStages.has(s));
  const selectedTarget = choices.includes(target) ? target : choices[0];
  return <section className="panel crm-panel sales-panel"><Link to="/opportunities">← 商机列表</Link>
    <h1>{o.name}</h1><div className="crm-actions"><span className="outline-badge">{names[o.stage]} · {o.probability}%</span><span>版本 {o.version}</span><button onClick={() => void refresh()}>重新加载</button></div>
    <p>{o.account.name} · {o.owner.name}</p><h2>预计 {moneyLabel(o.amount, o.currency)}</h2><p>加权预计 {moneyLabel(o.weighted_amount, o.currency)}</p>
    {o.stage === 'WON' && <h2>实际成交 {moneyLabel(o.actual_amount, o.actual_currency || o.currency)}</h2>}
    {error && <ErrorState message={error} />}
    {canWrite && openStages.has(o.stage) && <button onClick={() => setEditing({ ...o })}>编辑商机</button>}
    {editing && <><OpportunityForm initial={editing} onDone={() => { setEditing(null); void refresh(); }} /><button onClick={() => setEditing(null)}>取消编辑</button></>}
    {canWrite && openStages.has(o.stage) && <form className="crm-form" onSubmit={e => {
      e.preventDefault(); if (!window.confirm(`确认将商机变更为“${names[selectedTarget]}”？`)) return;
      void command(`/api/v1/opportunities/${id}/transitions`, { expected_version: o.version, target_stage: selectedTarget, reason,
        ...(selectedTarget === 'WON' ? { evidence_id: proofId || null } : {}),
        ...(selectedTarget === 'LOST' ? { close_reason_code: lossCode, close_reason: reason } : {}) });
    }}><h2>阶段变更</h2><label>目标阶段<select value={selectedTarget} onChange={e => setTarget(e.target.value)}>
      {choices.map(s => <option key={s} value={s}>{names[s]}</option>)}</select></label>
      <label>操作原因<textarea required value={reason} onChange={e => setReason(e.target.value)} /></label>
      {selectedTarget === 'WON' && <label>选定已核验成交依据<select required value={proofId} onChange={e => setProofId(e.target.value)}><option value="">请选择</option>{proofs.data?.data.filter(p => p.status === 'VERIFIED').map(p => <option key={p.id} value={p.id}>{p.type} · {p.currency} {p.amount}</option>)}</select></label>}
      {selectedTarget === 'LOST' && <label>丢单分类<select value={lossCode} onChange={e => setLossCode(e.target.value)}>{['BUDGET', 'COMPETITOR', 'NO_DECISION', 'PRODUCT_FIT', 'TIMING', 'OTHER'].map(s => <option key={s}>{s}</option>)}</select></label>}
      <button disabled={busy}>确认阶段变更</button>
    </form>}
    {managers(session) && o.stage === 'LOST' && !o.is_archived && <form className="crm-form" onSubmit={e => { e.preventDefault(); void command(`/api/v1/opportunities/${id}/reopen`, { expected_version: o.version, reason }); }}><label>重新打开原因<input required value={reason} onChange={e => setReason(e.target.value)} /></label><button disabled={busy}>重新打开丢单商机</button></form>}
    {managers(session) && !openStages.has(o.stage) && <form className="crm-form" onSubmit={e => { e.preventDefault(); void command(`/api/v1/opportunities/${id}/archive`, { expected_version: o.version, reason, is_archived: !o.is_archived }); }}><label>归档操作原因<input required value={reason} onChange={e => setReason(e.target.value)} /></label><button disabled={busy}>{o.is_archived ? '取消归档' : '归档商机'}</button></form>}
    {managers(session) && openStages.has(o.stage) && <form className="crm-form" onSubmit={e => { e.preventDefault(); void command(`/api/v1/opportunities/${id}/assign-owner`, { expected_version: o.version, owner_id: owner, reason }); }}><label>新负责人UUID<input required value={owner} onChange={e => setOwner(e.target.value)} /></label><label>调整原因<input required value={reason} onChange={e => setReason(e.target.value)} /></label><button disabled={busy}>调整负责人</button></form>}
    <h2>成交证据</h2><p className="muted">提交人与核验人必须不同。仅合同/采购订单可核验成交；其他依据的审批责任仍待确认。</p>
    {canWrite && openStages.has(o.stage) && <EvidenceForm opportunity={o} onSaved={refresh} />}
    {proofs.error && <ErrorState message={proofs.error.message} />}
    <label>核验说明<textarea value={reviewNote} onChange={e => setReviewNote(e.target.value)} /></label>
    {proofs.data?.data.map(p => <article className="proof-card" key={p.id}><strong>{p.type} · {p.currency} {p.amount}</strong><p>{p.status} · 提交人 {p.submitted_by}</p>
      <a href={`/api/v1/evidence/${p.id}/download`} download>下载原件（重新鉴权）</a>
      {p.verification_note && <p>{p.verification_note}</p>}
      {managers(session) && p.status === 'PENDING' && p.submitted_by !== session.user.id && <div className="crm-actions">{['VERIFY', 'REJECT'].map(decision => <button key={decision} disabled={busy || !reviewNote.trim() || (p.type === 'OTHER_APPROVED' && decision === 'VERIFY')} onClick={() => void command(`/api/v1/evidence/${p.id}/review`, { expected_version: p.version, decision, note: reviewNote })}>{decision === 'VERIFY' ? '核验通过' : '拒绝证据'}</button>)}</div>}
      {p.status === 'PENDING' && p.submitted_by === session.user.id && <p>请由另一位有权限的经理或管理员核验。</p>}
    </article>)}
    <h2>销售活动</h2>{canWrite && <ActivityForm opportunity={o} onSaved={refresh} />}
    {activities.error && <ErrorState message={activities.error.message} />}
    {activities.data?.data.map(a => <article className="proof-card" key={a.id}><strong>{a.subject}</strong><p>{a.content}</p><small>{a.type} · {a.status}</small>
      {canWrite && a.type === 'TASK' && a.status === 'OPEN' && <p><button disabled={busy} onClick={() => void command(`/api/v1/activities/${a.id}/complete`, { expected_version: a.version })}>完成任务</button></p>}
    </article>)}
    <h2>状态与审计时间线</h2>{history.error && <ErrorState message={history.error.message} />}
    {history.data?.data.map(h => <p key={h.id}>{h.created_at} · {h.action} · {h.reason}</p>)}
  </section>;
}

function EvidenceForm({ opportunity, onSaved }: { opportunity: Opportunity; onSaved: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null); const [amount, setAmount] = useState('');
  const [reference, setReference] = useState(''); const [legal, setLegal] = useState(''); const [date, setDate] = useState('');
  const [type, setType] = useState('SIGNED_CONTRACT'); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const token = useRef(crypto.randomUUID()); const uploaded = useRef<string | null>(null);
  return <form className="crm-form" onSubmit={async e => {
    e.preventDefault(); if (!file || file.size > 20 * 1024 * 1024) { setError('请选择不超过20 MiB的PDF。'); return; }
    setBusy(true); setError('');
    try {
      if (!uploaded.current) {
        const body = new FormData(); body.set('file', file); body.set('request_token', token.current);
        const result = await request<{ stored_object_id: string }>(`/api/v1/opportunities/${opportunity.id}/evidence-files`, { method: 'POST', body });
        uploaded.current = result.stored_object_id;
      }
      await request(`/api/v1/opportunities/${opportunity.id}/evidence`, { method: 'POST', body: JSON.stringify({ stored_object_id: uploaded.current,
        type, reference_number: reference, customer_legal_name: legal, document_date: date, amount, currency: opportunity.currency }) });
      uploaded.current = null; token.current = crypto.randomUUID(); await onSaved();
    } catch (err) { setError(salesError(err)); } finally { setBusy(false); }
  }}><h3>提交成交证据</h3><label>证据类型<select value={type} onChange={e => setType(e.target.value)}><option>SIGNED_CONTRACT</option><option>PURCHASE_ORDER</option></select></label>
    <label>PDF原件（≤20 MiB / ≤100页）<input required type="file" accept="application/pdf" onChange={e => { setFile(e.target.files?.[0] || null); token.current = crypto.randomUUID(); uploaded.current = null; }} /></label>
    <label>合同/PO编号<input required maxLength={100} value={reference} onChange={e => setReference(e.target.value)} /></label>
    <label>客户法律主体<input required maxLength={200} value={legal} onChange={e => setLegal(e.target.value)} /></label>
    <label>文档日期<input required type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
    <label>实际金额（{opportunity.currency}）<input required inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,2})?" value={amount} onChange={e => setAmount(e.target.value)} /></label>
    {error && <ErrorState message={error} />}<button disabled={busy}>上传并提交待核验证据</button>
  </form>;
}

function ActivityForm({ opportunity, onSaved }: { opportunity: Opportunity; onSaved: () => Promise<void> }) {
  const [subject, setSubject] = useState(''); const [content, setContent] = useState('');
  const [type, setType] = useState('NOTE'); const [due, setDue] = useState('');
  const [assignee, setAssignee] = useState(opportunity.owner_id);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  return <form className="crm-form" onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError('');
    try { await request('/api/v1/activities', { method: 'POST', body: JSON.stringify({ account_id: opportunity.account_id,
      opportunity_id: opportunity.id, type, subject, content,
      ...(type === 'TASK' ? { due_at: new Date(due).toISOString(), assignee_id: assignee } : { occurred_at: new Date().toISOString() }) }) });
      setSubject(''); setContent(''); await onSaved();
    } catch (err) { setError(salesError(err)); } finally { setBusy(false); }
  }}><label>活动类型<select value={type} onChange={e => setType(e.target.value)}>{['NOTE', 'CALL', 'MEETING', 'EMAIL', 'TASK'].map(t => <option key={t}>{t}</option>)}</select></label>
    <label>活动主题<input required maxLength={200} value={subject} onChange={e => setSubject(e.target.value)} /></label>
    <label>跟进记录<textarea required maxLength={20000} value={content} onChange={e => setContent(e.target.value)} /></label>
    {type === 'TASK' && <><label>截止时间<input required type="datetime-local" value={due} onChange={e => setDue(e.target.value)} /></label><label>任务负责人UUID<input required value={assignee} onChange={e => setAssignee(e.target.value)} /></label></>}
    {error && <ErrorState message={error} />}<button disabled={busy}>追加跟进记录</button></form>;
}

export function SalesWorkspace({ session }: { session: SessionData }) {
  return <Routes><Route path="/opportunities" element={<Opportunities session={session} />} />
    <Route path="/opportunities/:id" element={<OpportunityDetail key={window.location.pathname} session={session} />} />
    <Route path="/activities" element={<SalesDirectory kind="activities" />} />
    <Route path="/audit-events" element={<SalesDirectory kind="audit-events" />} /></Routes>;
}

function SalesDirectory({ kind }: { kind: 'activities' | 'audit-events' }) {
  const [page, setPage] = useState(1);
  const query = useQuery({ queryKey: [kind, 'directory', page], queryFn: () => request<Page<{
    id: string; subject?: string; content?: string; action?: string; entity_id?: string;
    opportunity_id?: string; status?: string; created_at: string; version?: number;
  }>>(`/api/v1/${kind}?page=${page}`, {}, true) });
  return <section className="panel crm-panel"><h1>{kind === 'activities' ? '销售活动' : '业务审计'}</h1>
    {kind === 'activities' && <p>从商机详情追加跟进记录和任务，所有修改由后端授权并审计。</p>}
    {query.isPending && <Loading />}{query.error && <ErrorState message={salesError(query.error)} />}
    {query.data?.data.map(row => <article className="proof-card" key={row.id}>
      <strong>{row.subject || row.action}</strong><p>{row.content || row.entity_id}</p><small>{row.created_at} · {row.status}</small>
      {row.opportunity_id && <p><Link to={`/opportunities/${row.opportunity_id}`}>查看商机</Link></p>}
    </article>)}<div className="crm-actions"><button disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button>
      <span>第{page}页 · 共{query.data?.page.total ?? 0}条</span><button disabled={page * 20 >= (query.data?.page.total || 0)} onClick={() => setPage(page + 1)}>下一页</button></div>
  </section>;
}
