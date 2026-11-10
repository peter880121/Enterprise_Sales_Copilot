import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ApiError, request, type SessionData } from './api';
import { ErrorState, Loading } from './components';
import './crm.css';
import { ApplyPanel, type FrozenChange } from './meeting-execution';
import { RegeneratePanel } from './meeting-regenerate';

type Opportunity = { id: string; name: string; version: number; stage: string };
type Paged<T> = { data: T[]; page: { total: number } };
type Fact = { topic: string; kind: 'FACT' | 'INFERENCE' | 'UNKNOWN'; value: string | null;
  evidence: { start: number; end: number; quote: string }[] };
type Suggestion = { id: string; version: number; status: string; effective_status: string; reason: string | null; expires_at: null;
  proposed_changes?: FrozenChange[]; execution_enabled?: boolean; result_version?: number | null; execution_id?: string | null; replacement_analysis_id?: string | null };
type Analysis = { id: string; source_job_id: string; status: string; mode: string; input_text: string;
  base_opportunity_version: number; opportunity_id: string; result: { facts: Fact[]; proposed_changes: []; limitations?: string[] } | null; suggestion: Suggestion };
const labels: Record<string, string> = { needs: '客户需求', budget: '预算', contacts: '联系人', decision_maker: '决策人', close_date: '预计成交时间', tasks: '待办事项', risks: '风险' };
const message = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试。';

export function Meetings({ session }: { session: SessionData }) {
  if (session.user.role === 'READ_ONLY') return <ErrorState message="只读账号不能访问会议纪要与 AI 草稿。" />;
  return <MeetingWorkspace session={session} />;
}

function MeetingWorkspace({ session }: { session: SessionData }) {
  const cache = useQueryClient();
  const [q, setQ] = useState(''), [page, setPage] = useState(1), [selected, setSelected] = useState<Opportunity | null>(null);
  const [text, setText] = useState(''), [synthetic, setSynthetic] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [analysisId, setAnalysisId] = useState('');
  const [meetingDate, setMeetingDate] = useState(''), [timezone, setTimezone] = useState('Asia/Hong_Kong');
  const [readingBaseline, setReadingBaseline] = useState(false);
  const intent = useRef({ content: '', token: '' });
  const params = new URLSearchParams({ q, page: String(page), ...(session.user.role === 'SALES_REP' ? { owner_id: session.user.id } : {}) });
  const opportunities = useQuery({ queryKey: ['meeting-opportunities', q, page, session.user.id], queryFn: () =>
    request<Paged<Opportunity>>(`/api/v1/opportunities?${params}`, {}, true) });
  return <section className="panel crm-panel"><h1>会议纪要与草稿审核</h1>
    <p role="status">MOCK 合成演示：不调用真实模型。Q07 更新须逐项人工确认；不允许 AI 转换阶段或修改负责人、概率、成交证据。</p>
    <p>原始纪要和草稿独立鉴权，不随全企业 CRM 可读权限开放。请勿输入真实客户资料。</p>
    <label>搜索待分析商机<input maxLength={100} value={q} onChange={event => { setQ(event.target.value); setPage(1); }} /></label>
    {opportunities.isPending ? <Loading /> : opportunities.error ? <ErrorState message={opportunities.error.message} onRetry={() => void opportunities.refetch()} />
      : !opportunities.data.data.length ? <p>没有匹配商机。</p> : <div className="crm-actions">{opportunities.data.data.filter(row => !['WON', 'LOST'].includes(row.stage)).map(row =>
        <button key={row.id} disabled={busy || readingBaseline} onClick={() => { setSelected(row); setAnalysisId(''); setError(''); }}>选择商机：{row.name}</button>)}</div>}
    <div className="crm-actions"><button disabled={page === 1 || opportunities.isFetching} onClick={() => setPage(page - 1)}>商机上一页</button><span>商机第 {page} 页</span>
      <button disabled={!opportunities.data || opportunities.isFetching || page * 20 >= opportunities.data.page.total} onClick={() => setPage(page + 1)}>商机下一页</button></div>
    {selected && <><h2>当前商机：{selected.name}</h2><p>基础版本 {selected.version}，后台刷新不会提高提交版本。<Link to={`/opportunities/${selected.id}`}>查看商机</Link></p>
      <button disabled={busy || readingBaseline} onClick={async () => {
        if (busy || readingBaseline) return; setReadingBaseline(true); setError('');
        try {
          const latest = await request<Opportunity>(`/api/v1/opportunities/${selected.id}`);
          setSelected(latest); void cache.invalidateQueries({ queryKey: ['meeting-opportunities'] });
        } catch (err) { setError(message(err)); } finally { setReadingBaseline(false); }
      }}>读取当前商机版本</button>
      <p>执行后生成下一份草稿，或遇到版本冲突时，请先核对商机并主动读取当前版本；现有纪要输入会保留，旧草稿仍按原基准校验。</p>
      <form className="crm-form" onSubmit={async event => {
        event.preventDefault(); if (busy || readingBaseline || !text.trim() || !synthetic) return; setBusy(true); setError('');
        const content = JSON.stringify({ expected_opportunity_version: selected.version, meeting_text: text, timezone, meeting_date: meetingDate || null });
        if (intent.current.content !== content) intent.current = { content, token: crypto.randomUUID() };
        try { const accepted = await request<{ resource_id: string }>(`/api/v1/opportunities/${selected.id}/meeting-analyses`, {
          method: 'POST', body: JSON.stringify({ ...JSON.parse(content), request_token: intent.current.token }) });
          setAnalysisId(accepted.resource_id); void cache.invalidateQueries({ queryKey: ['meeting-history', selected.id] });
        } catch (err) { setError(message(err)); } finally { setBusy(false); }
      }}><label>会议日期（相对日期换算必需）<input type="date" value={meetingDate} onChange={event => setMeetingDate(event.target.value)} /></label>
        <label>会议时区<input maxLength={64} required value={timezone} onChange={event => setTimezone(event.target.value)} /></label>
        <label>合成会议纪要<textarea required maxLength={50000} rows={8} value={text} onChange={event => setText(event.target.value)} /></label>
        <p>抽取标签：需求：、预算：、联系人：、决策人：、成交时间：、待办：、风险：。可执行演示标签：预计金额：1500.00、币种：CNY、预计成交日期：2026-12-01、优先级：HIGH、来源：EVENT、主要联系人ID：、备注：、任务：、任务截止：（带时区 ISO 时间）、任务负责人ID：。预算不等同预计金额。</p>
        <label><input type="checkbox" checked={synthetic} onChange={event => setSynthetic(event.target.checked)} />我确认这里只使用合成演示资料</label>
        <button className="primary" disabled={busy || readingBaseline || !synthetic || !text.trim()}>提交 Mock 解析</button>{error && <ErrorState message={error} />}
      </form>
      <AnalysisHistory key={selected.id} opportunityId={selected.id} onSelect={setAnalysisId} />
    </>}
    {analysisId && <AnalysisDetail key={analysisId} id={analysisId} onOpenAnalysis={setAnalysisId} />}
  </section>;
}

export function AnalysisHistory({ opportunityId, onSelect }: { opportunityId: string; onSelect: (id: string) => void }) {
  const [page, setPage] = useState(1);
  const history = useQuery({ queryKey: ['meeting-history', opportunityId, page], queryFn: () =>
    request<Paged<{ id: string; status: string; mode: string; created_at: string }>>(`/api/v1/opportunities/${opportunityId}/meeting-analyses?page=${page}&page_size=20`, {}, true) });
  return <section aria-label="会议分析历史"><h2>已有分析</h2><button disabled={history.isFetching} onClick={() => void history.refetch()}>刷新分析历史</button>
    {history.isPending ? <Loading /> : history.error ? <ErrorState message={history.error.message} onRetry={() => void history.refetch()} />
      : !history.data.data.length ? <p>暂无分析。</p> : history.data.data.map(row => <button key={row.id} onClick={() => onSelect(row.id)}>{row.created_at} · {row.mode} · {row.status}</button>)}
    <div className="crm-actions"><button disabled={page === 1 || history.isFetching} onClick={() => setPage(page - 1)}>分析上一页</button>
      <span>分析第 {page} 页 · 共 {history.data?.page.total ?? '—'} 条</span>
      <button disabled={!history.data || !!history.error || history.isFetching || page * 20 >= history.data.page.total} onClick={() => setPage(page + 1)}>分析下一页</button></div>
  </section>;
}

export function AnalysisDetail({ id, onOpenAnalysis }: { id: string; onOpenAnalysis?: (id: string) => void }) {
  const cache = useQueryClient(), [reason, setReason] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const intent = useRef({ body: '', key: '' });
  const analysis = useQuery({ queryKey: ['meeting-analysis', id], queryFn: () => request<Analysis>(`/api/v1/meeting-analyses/${id}`),
    refetchInterval: query => ['QUEUED', 'RUNNING'].includes(query.state.data?.status || '') ? 1000 : false });
  const job = useQuery({ queryKey: ['meeting-job', analysis.data?.source_job_id], enabled: !!analysis.data, queryFn: () => request<{ status: string; error_code: string | null; attempts: number }>(`/api/v1/jobs/${analysis.data!.source_job_id}`),
    refetchInterval: query => ['QUEUED', 'RUNNING'].includes(query.state.data?.status || '') ? 1000 : false });
  if (analysis.isPending) return <Loading />;
  if (analysis.error && (!analysis.data || (analysis.error instanceof ApiError && [401, 403].includes(analysis.error.status)))) return <ErrorState message={analysis.error.message} onRetry={() => void analysis.refetch()} />;
  const data = analysis.data!, suggestion = data.suggestion;
  async function review(action: 'reject' | 'abandon') {
    if (!reason.trim() || busy) return; setBusy(true); setError('');
    const body = JSON.stringify({ expected_version: suggestion.version, reason });
    if (intent.current.body !== `${action}:${body}`) intent.current = { body: `${action}:${body}`, key: crypto.randomUUID() };
    try { await request(`/api/v1/suggestions/${suggestion.id}/${action}`, { method: 'POST', headers: { 'Idempotency-Key': intent.current.key }, body });
      await cache.invalidateQueries({ queryKey: ['meeting-analysis', id] });
    } catch (err) { setError(message(err)); } finally { setBusy(false); }
  }
  return <section aria-label="解析草稿"><h2>解析草稿 · {data.mode}</h2><p role="status">任务：{data.status} · 草稿：{suggestion.effective_status}</p>
    {['QUEUED', 'RUNNING'].includes(data.status) && <p>任务已持久化，等待 Worker 完成；尚未解析成功。</p>}
    {job.error && <ErrorState message={job.error.message} onRetry={() => void job.refetch()} />}
    {data.status === 'FAILED' && <ErrorState message={`解析失败：${job.data?.error_code || '请查询任务状态'}；未生成可用草稿。`} />}
    <details><summary>查看原始合成纪要</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{data.input_text}</pre></details>
    {data.result?.facts.map(fact => <article key={fact.topic}><h3>{labels[fact.topic]} · {fact.kind === 'FACT' ? '原文记载' : fact.kind === 'INFERENCE' ? '模型推断' : '未知'}</h3>
      <p>{fact.value ?? '原文没有可确认信息。'}</p>{fact.evidence.map((evidence, index) => <blockquote key={index}>{evidence.quote}<small>原文字符位置 {evidence.start}—{evidence.end}（Unicode 码点）</small></blockquote>)}</article>)}
    <p>原文记载不代表独立核验。Mock 结果不能作为真实模型质量结论；只有下方冻结的获批字段及活动可人工确认执行。</p>
    {data.result?.limitations?.map((limitation, index) => <p key={index}>{limitation}</p>)}
    {analysis.error && <ErrorState message={`最新资料刷新失败：${analysis.error.message}`} onRetry={() => void analysis.refetch()} />}
    {!!suggestion.proposed_changes?.length && suggestion.status === 'DRAFT' && <ApplyPanel suggestionId={suggestion.id} version={suggestion.version}
      opportunityVersion={data.base_opportunity_version} changes={suggestion.proposed_changes} enabled={!!suggestion.execution_enabled}
      onSaved={async () => { await cache.invalidateQueries({ queryKey: ['meeting-analysis', id] });
        void cache.invalidateQueries({ queryKey: ['opportunity', data.opportunity_id] }); void cache.invalidateQueries({ queryKey: ['opportunities'] }); void cache.invalidateQueries({ queryKey: ['pipeline'] }); }} />}
    {suggestion.status === 'EXECUTED' && <p role="status">草稿已执行，商机版本 {suggestion.result_version}。未选项需生成新草稿，不能补执行。</p>}
    {onOpenAnalysis && ['DRAFT', 'SUPERSEDED'].includes(suggestion.status) && <RegeneratePanel suggestionId={suggestion.id} version={suggestion.version}
      opportunityId={data.opportunity_id} enabled={suggestion.status === 'DRAFT'} replacementAnalysisId={suggestion.replacement_analysis_id}
      onOpen={onOpenAnalysis} onSaved={async () => {
        await Promise.all([cache.invalidateQueries({ queryKey: ['meeting-analysis', id] }, { throwOnError: true }),
          cache.invalidateQueries({ queryKey: ['meeting-history', data.opportunity_id] }, { throwOnError: true })]);
      }} />}
    {suggestion.status === 'DRAFT' && <div className="crm-form"><label>草稿审核原因<textarea maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <button disabled={busy || !reason.trim()} onClick={() => void review('reject')}>拒绝草稿</button><button disabled={busy || !reason.trim()} onClick={() => void review('abandon')}>标记已阅并放弃</button></div>}
    {suggestion.reason && <p>审核说明：{suggestion.reason}</p>}{error && <ErrorState message={error} />}
  </section>;
}
