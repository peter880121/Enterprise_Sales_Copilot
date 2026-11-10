import { createContext, useContext, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Link } from 'react-router-dom';
import { ApiError, request, type SessionData } from './api';
import { ErrorState, Loading } from './components';
import { PublicSearchPreview } from './discovery-search-preview';
import './crm.css';

type Reviewer = { id: string; name: string; role: string };
type ProfileData = { id: string; owner_id: string; name: string; product: string; keywords: string[]; regions: string[]; visibility: 'PRIVATE' | 'TEAM'; reviewer_ids: string[]; reviewers: Reviewer[]; version: number };
type Material = { id: string; title: string; purpose: string; sha256: string; content?: string; text_sha256?: string };
type Lead = { id: string; buyer_name: string; project_name: string; notice_type: string; status: string; version: number; account_id: string | null; summary_only: boolean; can_share_summary?: boolean; material_id?: string; review_note?: string; analysis?: { mode: string; profile_version: number; facts: Record<string, { value: string; evidence: { quote: string } }>; matched_keywords: string[]; qualification: string; limitations: string[]; budget: { value: string; currency: string | null } | null } };
type Paged<T> = { data: T[]; page: { total: number } };
const split = (value: string) => value.split(/[,，\n]/).map(term => term.trim()).filter(Boolean);
export const profileSchema = z.object({ name: z.string().trim().min(1).max(200), product: z.string().trim().min(1).max(200), keywords: z.string().refine(value => split(value).length >= 1 && split(value).length <= 20 && split(value).every(term => term.length <= 50), '填写1—20个关键词，每项最多50字符'), regions: z.string().refine(value => split(value).length <= 20 && split(value).every(term => term.length <= 50), '地区最多20项，每项最多50字符'), visibility: z.enum(['PRIVATE', 'TEAM']) });
type ProfileFormData = z.infer<typeof profileSchema>;
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试。';
const AccessScope = createContext('isolated-component');
const factLabels: Record<string, string> = { buyer: '采购人', agency: '采购代理', project: '采购项目', category: '品类', need: '需求', notice_type: '公告类型', budget: '来源预算', deadline: '截止时间原文', region: '地区' };

function Pager({ page, total, busy, onPage, label }: { page: number; total: number; busy: boolean; onPage: (page: number) => void; label: string }) {
  return <div className="crm-actions"><button disabled={page <= 1 || busy} onClick={() => onPage(page - 1)}>{label}上一页</button><span>{label}第 {page} 页 · {total} 条</span><button disabled={busy || page * 20 >= total} onClick={() => onPage(page + 1)}>{label}下一页</button></div>;
}

function ProfileForm({ initial, onSaved }: { initial?: ProfileData; onSaved: (row: ProfileData) => void }) {
  const scope = useContext(AccessScope);
  const [error, setError] = useState(''), [reviewers, setReviewers] = useState<Reviewer[]>(initial?.reviewers || []), [q, setQ] = useState(''), [page, setPage] = useState(1);
  const choices = useQuery({ queryKey: ['discovery-reviewers', q, page, scope], queryFn: () => request<Paged<Reviewer>>(`/api/v1/discovery/reviewers?q=${encodeURIComponent(q)}&page=${page}`, {}, true) });
  const form = useForm<ProfileFormData>({ resolver: zodResolver(profileSchema), defaultValues: { name: initial?.name || '', product: initial?.product || '', keywords: initial?.keywords.join('，') || '', regions: initial?.regions.join('，') || '', visibility: initial?.visibility || 'PRIVATE' } });
  return <form className="crm-form" aria-label={initial ? '编辑销售画像' : '新建销售画像'} onSubmit={form.handleSubmit(async values => {
    setError('');
    try {
      const saved = await request<ProfileData>(initial ? `/api/v1/discovery/profiles/${initial.id}` : '/api/v1/discovery/profiles', { method: initial ? 'PATCH' : 'POST', body: JSON.stringify({ ...values, keywords: split(values.keywords), regions: split(values.regions), reviewer_ids: reviewers.map(row => row.id), ...(initial ? { expected_version: initial.version } : {}) }) });
      onSaved(saved); // Server acknowledgement precedes all refresh/navigation; no automatic POST retry.
      if (!initial) { form.reset(); setReviewers([]); }
    } catch (err) { setError(errorMessage(err)); }
  })}><h2>{initial ? '编辑销售画像' : '新建销售画像'}</h2>
    <label>画像名称<input {...form.register('name')} maxLength={200} /></label>
    <label>产品或解决方案<input {...form.register('product')} maxLength={200} placeholder="例如：医院超声设备方案" /></label>
    <label>匹配关键词<input {...form.register('keywords')} placeholder="超声，彩色多普勒" /></label>
    <label>目标地区<input {...form.register('regions')} placeholder="仅作为画像条件，尚不自动判定地域资格" /></label>
    <label>空间可见性<select {...form.register('visibility')} disabled={!!initial}><option value="PRIVATE">PRIVATE · 本人及明确授权评审者</option><option value="TEAM">TEAM · 销售团队资料共享</option></select></label>
    <p>可见性创建后固定。经理或管理员不会自动获得私有空间权限；只读用户仅可见明确发布的已认可摘要。</p>
    <label>搜索授权评审者<input value={q} onChange={event => { setQ(event.target.value); setPage(1); }} /></label>
    <p>已选评审者：{reviewers.map(row => row.name).join('、') || '无'}。仅创建者可修改授权。</p>
    {reviewers.map(row => <button type="button" key={row.id} disabled={!!initial && initial.owner_id !== scope.split(':')[0]} onClick={() => setReviewers(current => current.filter(item => item.id !== row.id))}>移除评审者：{row.name}</button>)}
    {choices.isPending ? <Loading /> : choices.error ? <ErrorState message={choices.error.message} onRetry={() => void choices.refetch()} /> : choices.data.data.map(row => <label key={row.id}><input type="checkbox" checked={reviewers.some(item => item.id === row.id)} disabled={reviewers.length >= 10 && !reviewers.some(item => item.id === row.id)} onChange={event => setReviewers(current => event.target.checked ? [...current, row] : current.filter(item => item.id !== row.id))} />{row.name} · {row.role}</label>)}
    <Pager label="评审者" page={page} total={choices.data?.page.total || 0} busy={choices.isFetching} onPage={setPage} />
    {Object.values(form.formState.errors).map((entry, index) => <p role="alert" key={index}>{entry.message}</p>)}
    {error && <ErrorState message={error} />}<button className="primary" disabled={form.formState.isSubmitting}>{initial ? '保存画像修改' : '创建画像'}</button>
  </form>;
}

function Materials({ profile }: { profile: ProfileData }) {
  const scope = useContext(AccessScope);
  const cache = useQueryClient(), [page, setPage] = useState(1), [title, setTitle] = useState(''), [content, setContent] = useState(''), [purpose, setPurpose] = useState('BUYER_DEMAND');
  const [noPatient, setNoPatient] = useState(false);
  const [shared, setShared] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [selected, setSelected] = useState<string[]>([]), [runId, setRunId] = useState(''), [opened, setOpened] = useState<Material | null>(null);
  const intent = useRef({ body: '', token: '' }), committed = useRef(false);
  const materials = useQuery({ queryKey: ['discovery-materials', profile.id, page, scope], queryFn: () => request<Paged<Material>>(`/api/v1/discovery/profiles/${profile.id}/materials?page=${page}`, {}, true) });
  const run = useQuery({ queryKey: ['discovery-run', runId, scope], enabled: !!runId, queryFn: () => request<{ id: string; status: string; result_count: number; error_code: string | null; mode: string }>(`/api/v1/discovery/runs/${runId}`), refetchInterval: query => ['QUEUED', 'RUNNING'].includes(query.state.data?.status || '') ? 1000 : false });
  const refresh = () => { void cache.invalidateQueries({ queryKey: ['discovery-materials', profile.id] }); };
  async function paste() {
    if (busy) return; setBusy(true); setError('');
    try { await request(`/api/v1/discovery/profiles/${profile.id}/materials`, { method: 'POST', body: JSON.stringify({ title, content, purpose, confirm_team_visibility: shared, confirm_no_patient_data: noPatient }) }); setTitle(''); setContent(''); refresh(); }
    catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }
  if (materials.error instanceof ApiError && [401, 403].includes(materials.error.status)) return <ErrorState message={materials.error.message} onRetry={() => void materials.refetch()} />;
  return <section aria-label="发现资料与任务"><h2>资料与本地发现</h2>
    <p>RULES · D1仅提取带标签文本，不调用互联网或真实模型。UTF-8 TXT/Markdown上限64 KiB；PDF和通用知识库尚未接入。原始文本及字节保存在独立MySQL资料表，不复用成交附件。</p>
    <label>资料用途<select value={purpose} onChange={event => setPurpose(event.target.value)}><option value="BUYER_DEMAND">采购需求 · 谁可能买</option><option value="SELLER_CAPABILITY">我方能力 · 我们能卖什么</option></select></label>
    <label>资料标题<input value={title} maxLength={200} onChange={event => setTitle(event.target.value)} /></label>
    <label>资料正文<textarea rows={7} maxLength={50000} value={content} onChange={event => setContent(event.target.value)} placeholder={'采购人：示例A医院（合成）\n项目：超声设备采购\n品类：超声\n公告类型：采购意向\n预算：120万元 人民币\n采购代理：示例B机构（合成）'} /></label>
    <label><input type="checkbox" checked={noPatient} onChange={event => setNoPatient(event.target.checked)} />我确认不包含患者身份、病例或检查影像资料</label>
    {profile.visibility === 'TEAM' && <label><input type="checkbox" checked={shared} onChange={event => setShared(event.target.checked)} />我确认本资料在TEAM销售空间共享</label>}
    <button disabled={busy || !noPatient || !title.trim() || !content.trim() || (profile.visibility === 'TEAM' && !shared)} onClick={() => void paste()}>保存文本资料</button>
    <label>上传TXT或Markdown<input type="file" accept=".txt,.md" disabled={busy || !noPatient || (profile.visibility === 'TEAM' && !shared)} onChange={async event => {
      const file = event.target.files?.[0]; if (!file || busy) return;
      if (file.size > 65536) { setError('D1文本资料上限64 KiB。'); return; }
      setBusy(true); setError(''); const form = new FormData(); form.append('file', file); form.append('purpose', purpose); form.append('confirm_team_visibility', String(shared)); form.append('confirm_no_patient_data', String(noPatient));
      try { await request(`/api/v1/discovery/profiles/${profile.id}/material-files`, { method: 'POST', body: form }); refresh(); }
      catch (err) { setError(errorMessage(err)); } finally { setBusy(false); event.target.value = ''; }
    }} /></label>
    {materials.isPending ? <Loading /> : materials.error ? <ErrorState message={materials.error.message} onRetry={() => void materials.refetch()} /> : !materials.data.data.length ? <p>暂无资料。</p> : materials.data.data.map(row => <div key={row.id} className="crm-actions">
      <label><input type="checkbox" disabled={row.purpose !== 'BUYER_DEMAND' || busy || (!!runId && ['QUEUED', 'RUNNING'].includes(run.data?.status || 'QUEUED')) || (selected.length >= 10 && !selected.includes(row.id))} checked={selected.includes(row.id)} onChange={event => { committed.current = false; setSelected(current => event.target.checked ? [...current, row.id] : current.filter(id => id !== row.id)); }} />{row.title} · {row.purpose === 'BUYER_DEMAND' ? '采购需求' : '我方能力'}</label>
      <button onClick={async () => { try { setOpened(await request<Material>(`/api/v1/discovery/materials/${row.id}`)); } catch (err) { if (err instanceof ApiError && [401, 403].includes(err.status)) setOpened(null); setError(errorMessage(err)); } }}>查看资料：{row.title}</button>
    </div>)}
    <Pager label="资料" page={page} total={materials.data?.page.total || 0} busy={materials.isFetching} onPage={setPage} />
    {opened && <details open><summary>原始授权资料：{opened.title}</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{opened.content}</pre><p>文本hash：{opened.text_sha256}</p></details>}
    <button className="primary" disabled={!selected.length || busy || committed.current} onClick={async () => {
      if (busy || !selected.length || committed.current) return; setBusy(true); setError('');
      const body = JSON.stringify({ expected_profile_version: profile.version, material_ids: [...selected].sort() });
      if (intent.current.body !== body) intent.current = { body, token: crypto.randomUUID() };
      try { const accepted = await request<{ id: string }>(`/api/v1/discovery/profiles/${profile.id}/runs`, { method: 'POST', body: JSON.stringify({ ...JSON.parse(body), request_token: intent.current.token }) }); committed.current = true; setRunId(accepted.id); }
      catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
    }}>从所选需求资料发现线索</button>
    {run.isFetching && !run.data && <Loading text="正在读取发现任务…" />}{run.error && <ErrorState message={run.error.message} onRetry={() => void run.refetch()} />}
    {run.data && <p role="status">RULES任务：{run.data.status} · 线索条目（含已有复用）：{run.data.result_count}{run.data.error_code ? ` · ${run.data.error_code}` : ''}</p>}
    {run.data?.status === 'SUCCEEDED' && <button onClick={() => void cache.invalidateQueries({ queryKey: ['discovery-leads'] })}>读取服务端线索结果</button>}
    <p>相同原件再次运行会复用已有冻结线索；画像修改不会自动重算已有分析。重新分析与跨资料项目合并尚未交付。</p>
    {error && <ErrorState message={error} />}
  </section>;
}

function LeadDetail({ id, readonly }: { id: string; readonly: boolean }) {
  const scope = useContext(AccessScope);
  const cache = useQueryClient(), [reason, setReason] = useState(''), [publish, setPublish] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const lead = useQuery({ queryKey: ['discovery-lead', id, scope], queryFn: () => request<Lead>(`/api/v1/discovery/leads/${id}`) });
  const [source, setSource] = useState<Material | null>(null);
  if (lead.isPending) return <Loading />;
  if (lead.error) return <ErrorState message={lead.error.message} onRetry={() => void lead.refetch()} />;
  const row = lead.data;
  return <section className="panel crm-panel" aria-label="线索详情"><h2>{row.buyer_name} · {row.project_name}</h2><p>线索状态 {row.status} · 版本 {row.version} · {row.notice_type}</p>
    {readonly || row.summary_only ? <p>仅共享的已认可摘要，不开放原始资料或触发任务。</p> : <>
      <p>RULES规则结果，不是联网搜索或真实模型判断。分析画像版本 {row.analysis?.profile_version}，后续画像修改不会覆盖此结果。资格状态：{row.analysis?.qualification}；匹配词：{row.analysis?.matched_keywords.join('、') || '未匹配'}。</p>
      {row.analysis?.budget && <p>来源预算：{row.analysis.budget.value} {row.analysis.budget.currency || '币种未知'}；不是预计成交或实际成交金额。</p>}
      {Object.entries(row.analysis?.facts || {}).map(([key, fact]) => <article key={key}><strong>{factLabels[key] || key} · 原文记载</strong><p>{fact.value}</p><blockquote>{fact.evidence.quote}</blockquote></article>)}
      {row.analysis?.limitations.map(text => <p key={text}>{text}</p>)}
      <button onClick={async () => { try { setSource(await request<Material>(`/api/v1/discovery/materials/${row.material_id}`)); } catch (err) { setError(errorMessage(err)); } }}>核对原始资料</button>
      {source && <pre style={{ whiteSpace: 'pre-wrap' }}>{source.content}</pre>}
      <form className="crm-form" onSubmit={event => event.preventDefault()}><label>人工评审说明<textarea value={reason} maxLength={1000} onChange={event => setReason(event.target.value)} /></label>
        <label><input type="checkbox" checked={publish} disabled={!row.can_share_summary || busy} onChange={event => setPublish(event.target.checked)} />认可时明确发布TEAM共享摘要（私有空间不可选）</label>
        {(['IN_REVIEW', 'QUALIFIED', 'DISQUALIFIED'] as const).filter(status => ({ NEW: ['IN_REVIEW', 'DISQUALIFIED'], IN_REVIEW: ['QUALIFIED', 'DISQUALIFIED'], QUALIFIED: ['DISQUALIFIED'], DISQUALIFIED: ['IN_REVIEW'] }[row.status] || []).includes(status)).map(status => <button key={status} disabled={readonly || busy || !reason.trim()} onClick={async () => {
          setBusy(true); setError('');
          try { const saved = await request<Lead>(`/api/v1/discovery/leads/${id}`, { method: 'PATCH', body: JSON.stringify({ expected_version: row.version, status, reason, publish_summary: status === 'QUALIFIED' && publish }) }); cache.setQueryData(['discovery-lead', id, scope], saved); void cache.invalidateQueries({ queryKey: ['discovery-leads'] }); }
          catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
        }}>{status === 'IN_REVIEW' ? '进入人工评审' : status === 'QUALIFIED' ? '认可此线索' : '暂不跟进'}</button>)}
      </form>{row.review_note && <p>最近评审说明：{row.review_note}</p>}
      {row.status === 'QUALIFIED' && !row.account_id && <AccountLinkPanel lead={row} onSaved={saved => { cache.setQueryData(['discovery-lead', id, scope], { ...row, account_id: saved.account_id, version: saved.result_version }); void cache.invalidateQueries({ queryKey: ['discovery-leads'] }); }} />}
      <p>尚未提交方案的项目保留在线索池。D1不自动创建商机，不改变阶段、概率或Pipeline。</p>
    </>}
    {row.account_id && <Link to={`/accounts/${row.account_id}`}>查看关联客户</Link>}{error && <ErrorState message={error} />}
  </section>;
}

export function AccountLinkPanel({ lead, onSaved }: { lead: Lead; onSaved: (result: { account_id: string; result_version: number }) => void }) {
  const scope = useContext(AccessScope);
  const [name, setName] = useState(lead.buyer_name), [existing, setExisting] = useState(''), [q, setQ] = useState(''), [page, setPage] = useState(1), [plan, setPlan] = useState<{ preview_hash: string; account_name: string; owner_name: string; notice: string } | null>(null);
  const [confirmed, setConfirmed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [saved, setSaved] = useState(false);
  const frozen = useRef({ target: {} as Record<string, unknown>, key: '' });
  const accounts = useQuery({ queryKey: ['discovery-account-choices', q, page, scope], queryFn: () => request<Paged<{ id: string; name: string }>>(`/api/v1/accounts?q=${encodeURIComponent(q)}&page=${page}`, {}, true) });
  function reset() { setPlan(null); setConfirmed(false); }
  return <section aria-label="人工客户关联"><h3>建立或关联客户</h3><p>新建基础客户会对全企业CRM用户开放。原文、内部预算、能力资料不会复制到客户。</p>
    <label>新建客户名称<input value={name} disabled={!!existing || saved || busy} maxLength={200} onChange={event => { setName(event.target.value); reset(); }} /></label>
    <label>搜索已有客户<input value={q} maxLength={100} onChange={event => { setQ(event.target.value); setPage(1); }} /></label>
    {accounts.isPending ? <Loading /> : accounts.error ? <ErrorState message={accounts.error.message} onRetry={() => void accounts.refetch()} /> : accounts.data.data.map(row => <button key={row.id} disabled={saved || busy} onClick={() => { setExisting(row.id); reset(); }}>关联已有客户：{row.name}</button>)}
    <Pager label="已有客户" page={page} total={accounts.data?.page.total || 0} busy={accounts.isFetching} onPage={setPage} />
    {existing && <button disabled={saved || busy} onClick={() => { setExisting(''); reset(); }}>改为新建客户</button>}
    <button disabled={busy || saved || (!existing && !name.trim())} onClick={async () => {
      setBusy(true); setError(''); setConfirmed(false);
      const target = { expected_version: lead.version, existing_account_id: existing || null, new_account_name: existing ? null : name };
      try { setPlan(await request(`/api/v1/discovery/leads/${lead.id}/account-preview`, { method: 'POST', body: JSON.stringify(target) })); frozen.current = { target, key: crypto.randomUUID() }; }
      catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
    }}>预览客户关联</button>
    {plan && <><p>确认客户：{plan.account_name}。负责人：{plan.owner_name}。已有客户保持原负责人，新建客户由当前操作者负责。{plan.notice}</p><label><input type="checkbox" checked={confirmed} disabled={busy || saved} onChange={event => setConfirmed(event.target.checked)} />我确认将审核后的客户基础字段加入全企业CRM</label>
      <button disabled={!confirmed || busy || saved} onClick={async () => {
        if (saved || busy || !confirmed) return; setBusy(true); setError('');
        let result: { account_id: string; result_version: number };
        try { result = await request(`/api/v1/discovery/leads/${lead.id}/link-account`, { method: 'POST', headers: { 'Idempotency-Key': frozen.current.key }, body: JSON.stringify({ ...frozen.current.target, preview_hash: plan.preview_hash, confirmed_shared_crm: true }) }); }
        catch (err) { setError(errorMessage(err)); setBusy(false); return; }
        setSaved(true);
        try { onSaved(result); } catch { setError('客户已关联，页面刷新失败。请重新读取，不要重复创建。'); } finally { setBusy(false); }
      }}>确认建立客户关联</button></>}{saved && <p role="status">客户关联已成功。</p>}{error && <ErrorState message={error} />}
  </section>;
}

function Leads({ readonly }: { readonly: boolean }) {
  const scope = useContext(AccessScope);
  const [page, setPage] = useState(1), [q, setQ] = useState(''), [id, setId] = useState('');
  const leads = useQuery({ queryKey: ['discovery-leads', page, q, scope], queryFn: () => request<Paged<Lead>>(`/api/v1/discovery/leads?page=${page}&q=${encodeURIComponent(q)}`, {}, true) });
  return <section><h2>候选线索池</h2><label>搜索线索<input value={q} maxLength={100} onChange={event => { setQ(event.target.value); setPage(1); }} /></label>
    <button disabled={leads.isFetching} onClick={() => void leads.refetch()}>刷新线索池</button>
    {leads.isPending ? <Loading /> : leads.error ? <ErrorState message={leads.error.message} onRetry={() => void leads.refetch()} /> : !leads.data.data.length ? <p>暂无可见线索。任务完成后请读取服务端结果；只读账号仅可见已发布摘要。</p> : leads.data.data.map(row => <button key={row.id} onClick={() => setId(row.id)}>{row.buyer_name} · {row.project_name} · {row.status}</button>)}
    <Pager label="线索" page={page} total={leads.data?.page.total || 0} busy={leads.isFetching} onPage={setPage} />
    {id && <LeadDetail key={id} id={id} readonly={readonly} />}
  </section>;
}

export function DiscoveryWorkspace({ session }: { session: SessionData }) {
  const scope = `${session.user.id}:${session.user.role}`;
  return <AccessScope.Provider value={scope}><DiscoveryContent key={scope} session={session} /></AccessScope.Provider>;
}

function DiscoveryContent({ session }: { session: SessionData }) {
  const scope = useContext(AccessScope);
  const cache = useQueryClient(), [page, setPage] = useState(1), [selected, setSelected] = useState<ProfileData | null>(null), [editing, setEditing] = useState(false), [error, setError] = useState('');
  const readonly = session.user.role === 'READ_ONLY';
  const profiles = useQuery({ queryKey: ['discovery-profiles', page, scope], enabled: !readonly, queryFn: () => request<Paged<ProfileData>>(`/api/v1/discovery/profiles?page=${page}`, {}, true) });
  function saved(row: ProfileData) { setSelected(row); setEditing(false); void cache.invalidateQueries({ queryKey: ['discovery-profiles'] }); }
  return <section className="panel crm-panel"><h1>商机发现中心</h1><p role="status">D2 · 医疗器械示例 · 本地RULES与确认后的Tavily公开搜索，未接入RAG或真实LLM。</p><p>先发现并人工核验线索，再关联客户。不会自动建商机、改变概率、发邮件或投标。</p>
    {!readonly && <><ProfileForm key="new" onSaved={saved} /><h2>可访问销售画像</h2>
      {profiles.isPending ? <Loading /> : profiles.error ? <ErrorState message={profiles.error.message} onRetry={() => void profiles.refetch()} /> : profiles.data.data.map(row => <button key={row.id} onClick={async () => { try { setSelected(await request<ProfileData>(`/api/v1/discovery/profiles/${row.id}`)); setEditing(false); } catch (err) { setError(errorMessage(err)); } }}>{row.name} · {row.visibility}</button>)}
      <Pager label="画像" page={page} total={profiles.data?.page.total || 0} busy={profiles.isFetching} onPage={setPage} />
      {selected && <><h2>当前画像：{selected.name} · 基准版本 {selected.version}</h2><button onClick={() => setEditing(value => !value)}>编辑当前画像</button>
        {editing && <ProfileForm key={`${selected.id}:${selected.version}`} initial={selected} onSaved={saved} />}
        <PublicSearchPreview key={`search:${selected.id}`} profile={selected} scope={scope} />
        <Materials key={selected.id} profile={selected} /></>}
    </>}
    <Leads readonly={readonly} />{error && <ErrorState message={error} />}
  </section>;
}
