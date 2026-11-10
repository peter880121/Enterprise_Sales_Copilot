import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { request, type SessionData } from './api';
import { ErrorState, Loading } from './components';

type Preview = { mode: 'DRY_RUN'; writes_enabled: false; as_of: string; groups: {
  scope: string; days: number; due_count: number; candidate_count: number; blocked_by_reason: Record<string, number>; sample_ids: string[];
}[]; protected: Record<string, number>; limitations: string[] };
const labels: Record<string, string> = { meeting_source_and_quotes: '纪要原文及引文', job_details: '已结束任务详情（保留身份/状态/引用）',
  ai_run_details: '模型运行详情（保留最小元数据）', idempotency_response_cache: '完整响应缓存（保留永久去重）' };

export function RetentionPreview({ session }: { session: SessionData }) {
  if (session.user.role !== 'ADMIN') return <ErrorState message="仅管理员可查看保留策略预览。" />;
  return <AdminPreview />;
}
function AdminPreview() {
  const [asOf, setAsOf] = useState(''), [submitted, setSubmitted] = useState<string | null>(null);
  const query = useQuery({ queryKey: ['retention-preview', submitted], enabled: submitted !== null, retry: false,
    queryFn: () => request<Preview>(`/api/v1/admin/retention/preview${submitted ? `?${new URLSearchParams({ as_of: submitted })}` : ''}`) });
  return <section className="panel crm-panel"><h1>保留策略预览</h1><p role="status">DRY-RUN：仅查看候选与阻断原因，不删除、不归档、不修改资料。</p>
    <p>候选不表示可删除整行。审计、成交证据、执行记录与永久去重保留；不扫描 .local、报告、备份或对象存储。</p>
    <form className="crm-form" onSubmit={event => { event.preventDefault(); if (submitted === asOf) void query.refetch(); else setSubmitted(asOf); }}>
      <label>预览基准时间（ISO8601，可选）<input value={asOf} onChange={event => setAsOf(event.target.value)} placeholder="留空使用服务端 UTC 时间" /></label>
      <button disabled={query.isFetching}>生成只读预览</button></form>
    {query.isFetching && <Loading />}{query.error && <ErrorState message={query.error.message} onRetry={() => void query.refetch()} />}
    {query.data && !query.error && <><p>预览时间：{query.data.as_of} · 写操作：禁用</p><div className="crm-table"><table><thead><tr><th>范围</th><th>保留日数</th><th>已到期限</th><th>可供评审</th><th>阻断原因</th></tr></thead><tbody>
      {query.data.groups.map(group => <tr key={group.scope}><td>{labels[group.scope] || group.scope}</td><td>{group.days}</td><td>{group.due_count}</td><td>{group.candidate_count}</td><td>{JSON.stringify(group.blocked_by_reason)}</td></tr>)}
    </tbody></table></div><h2>受保护记录</h2>{Object.entries(query.data.protected).map(([name, count]) => <p key={name}>{name}：{count} 条，不纳入删除范围</p>)}
      {query.data.limitations.map((limitation, index) => <p key={index}>{limitation}</p>)}</>}
  </section>;
}
