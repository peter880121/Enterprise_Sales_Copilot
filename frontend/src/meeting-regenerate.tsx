import { useRef, useState } from 'react';
import { request } from './api';
import { ErrorState } from './components';

type Accepted = { resource_id: string; job_id: string };
export function RegeneratePanel({ suggestionId, version, opportunityId, enabled, replacementAnalysisId, onSaved, onOpen }: {
  suggestionId: string; version: number; opportunityId: string; enabled: boolean; replacementAnalysisId?: string | null;
  onSaved: () => Promise<void>; onOpen: (analysisId: string) => void;
}) {
  const [baseline, setBaseline] = useState<{ opportunity: number; suggestion: number } | null>(null);
  const [confirmed, setConfirmed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [accepted, setAccepted] = useState<Accepted | null>(null);
  const intent = useRef({ body: '', token: '' }), committed = useRef(false);
  const childId = accepted?.resource_id || replacementAnalysisId;
  async function readBaseline() {
    if (busy || committed.current || !enabled || childId) return;
    setBusy(true); setError(''); setConfirmed(false);
    try {
      const current = await request<{ version: number }>(`/api/v1/opportunities/${opportunityId}`);
      setBaseline({ opportunity: current.version, suggestion: version });
    } catch (err) { setError(err instanceof Error ? err.message : '读取基准失败。'); }
    finally { setBusy(false); }
  }
  async function regenerate() {
    if (!baseline || !confirmed || busy || committed.current || !enabled || childId) return;
    setBusy(true); setError('');
    const body = JSON.stringify({ expected_version: baseline.suggestion, expected_opportunity_version: baseline.opportunity });
    if (intent.current.body !== body) intent.current = { body, token: crypto.randomUUID() };
    let result: Accepted;
    try {
      result = await request<Accepted>(`/api/v1/suggestions/${suggestionId}/regenerate`, {
        method: 'POST', body: JSON.stringify({ ...JSON.parse(body), request_token: intent.current.token }),
      });
    } catch (err) { setError(err instanceof Error ? err.message : '请求失败，可使用同一请求重试。'); setBusy(false); return; }
    committed.current = true; setAccepted(result);
    try { await onSaved(); }
    catch { setError('重新生成已受理，但状态刷新失败。请查看新草稿，不要重复生成。'); }
    finally { setBusy(false); }
  }
  return <section aria-label="重新生成草稿"><h3>重新生成草稿</h3>
    <p>复制此分析的原始合成纪要、会议日期及时区，使用当前商机上下文创建新任务；旧草稿将被替代，不能再执行。新草稿不会自动执行。</p>
    {childId ? <><p role="status">已创建替代草稿；请查看真实任务状态。</p><button onClick={() => onOpen(childId)}>查看新草稿</button></> : <>
      <button disabled={!enabled || busy} onClick={() => void readBaseline()}>读取重新生成基准</button>
      {baseline && <p>商机基准版本 {baseline.opportunity}；草稿基准版本 {baseline.suggestion}。后台刷新不会自动提高基准。</p>}
      <label><input type="checkbox" checked={confirmed} disabled={!enabled || !baseline || busy} onChange={event => setConfirmed(event.target.checked)} />我确认复制原始合成纪要，并替换当前未执行草稿</label>
      <button disabled={!enabled || !baseline || !confirmed || busy} onClick={() => void regenerate()}>确认重新生成</button>
    </>}
    {error && <ErrorState message={error} />}
  </section>;
}
