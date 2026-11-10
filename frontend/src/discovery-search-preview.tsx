import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { request } from './api';
import { ErrorState, Loading } from './components';

type Preview = { provider: string; public_query: string; profile_version: number; max_results: number; search_depth: string; configured: boolean; external_request_sent: false; web_execution_available: boolean; preview_token: string | null; quota: { user_used: number; user_limit: number; global_used: number; global_limit: number; timezone: string }; notice: string };
type Run = { id: string; public_query: string; status: string; error_code: string | null; may_have_been_charged: boolean; result?: { results: { title: string; url: string; snippet: string }[] } | null };
type History = { data: Run[]; page: { total: number } };

export function PublicSearchPreview({ profile, scope = 'isolated-test' }: { profile: { id: string; version: number }; scope?: string }) {
  const cache = useQueryClient();
  const [query, setQuery] = useState(''), [preview, setPreview] = useState<Preview | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false), [confirmed, setConfirmed] = useState(false), [runId, setRunId] = useState(''), [page, setPage] = useState(1);
  const revision = useRef(0), intent = useRef<{ body: string } | null>(null), accepted = useRef(false);
  const historyKey = ['discovery-search-history', profile.id, scope];
  const history = useQuery({ queryKey: [...historyKey, page], queryFn: () => request<History>(`/api/v1/discovery/profiles/${profile.id}/search-runs?page=${page}`, {}, true) });
  const run = useQuery({ queryKey: ['discovery-search-run', runId, scope], enabled: !!runId, queryFn: () => request<Run>(`/api/v1/discovery/search-runs/${runId}`), refetchInterval: current => ['QUEUED', 'RUNNING'].includes(current.state.data?.status || '') ? 1000 : false });
  useEffect(() => {
    if (!run.error && run.data && ['SUCCEEDED', 'FAILED', 'OUTCOME_UNKNOWN'].includes(run.data.status)) {
      void cache.invalidateQueries({ queryKey: ['discovery-search-history', profile.id, scope] }).catch(() => setError('任务已受理，历史刷新失败；请读取已有任务，不要重复搜索。'));
    }
  }, [cache, profile.id, scope, run.data?.id, run.data?.status, run.error]);
  function changed(value: string) { revision.current += 1; setQuery(value); setPreview(null); setConfirmed(false); setError(''); }
  async function submit() {
    if (busy || accepted.current || (!intent.current && (!confirmed || !preview?.web_execution_available || !preview.preview_token))) return;
    if (!intent.current) intent.current = { body: JSON.stringify({ expected_profile_version: preview!.profile_version, public_query: preview!.public_query, preview_token: preview!.preview_token, request_token: crypto.randomUUID(), confirmed_public: true }) };
    setBusy(true); setError('');
    try {
      const data = await request<Run>(`/api/v1/discovery/profiles/${profile.id}/search-runs`, { method: 'POST', body: intent.current.body });
      accepted.current = true; setRunId(data.id);
      cache.setQueryData(['discovery-search-run', data.id, scope], data);
      void cache.invalidateQueries({ queryKey: historyKey }).catch(() => setError('任务已受理，历史刷新失败；请读取已有任务，不要重复搜索。'));
    } catch (err) { setError(`${err instanceof Error ? err.message : '搜索受理响应未确认。'} 保留原请求，手动重试只确认同一任务。`); }
    finally { setBusy(false); }
  }
  return <section aria-label="公开搜索查询预览"><h2>公开搜索 · Tavily</h2>
    <p>单独填写允许发送给搜索服务的公开词语。请勿填写内部报价、客户名单、患者信息或私有资料；不会自动复制画像或上传原文。</p>
    <form onSubmit={async event => {
      event.preventDefault(); if (busy || intent.current) return;
      const current = revision.current;
      setBusy(true); setError(''); setPreview(null); setConfirmed(false);
      try {
        const data = await request<Preview>(`/api/v1/discovery/profiles/${profile.id}/search-preview`, { method: 'POST', body: JSON.stringify({ expected_profile_version: profile.version, public_query: query.trim() }) });
        if (current === revision.current) setPreview(data);
      } catch (err) {
        if (current === revision.current) setError(err instanceof Error ? err.message : '查询预览失败，请重试。');
      } finally { setBusy(false); }
    }}>
      <label>允许外发的公开查询<input value={query} disabled={!!intent.current} minLength={3} maxLength={200} required onChange={event => changed(event.target.value)} placeholder="例如：超声 医疗器械 采购意向" /></label>
      <button disabled={busy || !!intent.current || query.trim().length < 3}>{busy ? '请求处理中…' : '预览公开查询'}</button>
    </form>
    {error && <ErrorState message={error} />}
    {preview && <div role="status"><p>将外发的完整查询：{preview.public_query}</p><p>服务：{preview.provider} · 最多{preview.max_results}条 · {preview.search_depth} · 画像版本{preview.profile_version}</p><p>{preview.configured ? '搜索凭据已配置' : '搜索服务尚未配置'}</p><p>{preview.notice}</p>
      {preview.quota && <p>预览时受理统计：本人{preview.quota.user_used}/{preview.quota.user_limit}，全局{preview.quota.global_used}/{preview.quota.global_limit}（{preview.quota.timezone}）。不是实时货币费用账单。</p>}
      <p>本次预览未发送外部请求，不产生搜索结果。</p>
      {preview.web_execution_available && <label><input type="checkbox" checked={confirmed} disabled={!!intent.current} onChange={event => setConfirmed(event.target.checked)} />我确认仅发送以上公开查询，并了解搜索可能计费</label>}
    </div>}
    <button disabled={busy || accepted.current || (!intent.current && (!confirmed || !preview?.web_execution_available))} onClick={() => void submit()}>{accepted.current ? '搜索任务已受理' : intent.current ? '按原请求重试受理' : preview?.web_execution_available ? '确认并开始搜索' : '网页搜索执行尚未开放'}</button>
    {intent.current && <button disabled={busy} onClick={() => { intent.current = null; accepted.current = false; changed(query); }}>编辑下一次查询（需重新预览）</button>}
    <h3>搜索任务历史</h3><button onClick={() => void history.refetch()}>刷新搜索历史</button>
    {history.isPending ? <Loading /> : history.error ? <ErrorState message={history.error.message} onRetry={() => void history.refetch()} /> : !history.data.data.length ? <p>暂无已受理搜索。</p> : history.data.data.map(row => <button key={row.id} onClick={() => setRunId(row.id)}>{row.public_query} · {row.status}</button>)}
    <div className="crm-actions"><button disabled={page <= 1 || history.isFetching} onClick={() => setPage(value => value - 1)}>搜索历史上一页</button><span>第{page}页 · {history.data?.page.total || 0}条</span><button disabled={history.isFetching || page * 20 >= (history.data?.page.total || 0)} onClick={() => setPage(value => value + 1)}>搜索历史下一页</button></div>
    {runId && <section aria-label="公开搜索任务详情"><h3>搜索任务详情</h3><button onClick={() => void run.refetch()}>刷新当前搜索任务</button>
      {run.isPending ? <Loading /> : run.error ? <ErrorState message={run.error.message} onRetry={() => void run.refetch()} /> : run.data && <><p role="status">{run.data.status} · {run.data.public_query}</p>
        {run.data.error_code && <p role="alert">{run.data.error_code}；{run.data.may_have_been_charged ? '可能已经计费，不会自动重放搜索。' : '未确认派发搜索。'}</p>}
        {run.data.status === 'SUCCEEDED' && <><p>以下仅为搜索服务摘要，尚未核验采购主体、公告有效期、预算或资格；不会自动写入CRM。</p>{!run.data.result?.results.length ? <p>搜索成功，但本次没有返回可展示的结果。</p> : run.data.result.results.map(row => <article key={row.url}><h4><a href={row.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">{row.title || row.url}</a></h4><p>{row.snippet}</p><small>{row.url}</small></article>)}</>}
      </>}
    </section>}
  </section>;
}
