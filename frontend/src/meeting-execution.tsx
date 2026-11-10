import { useRef, useState } from 'react';
import { request } from './api';
import { ErrorState } from './components';

export type FrozenChange = { id: string; kind: 'FIELD' | 'NOTE' | 'TASK'; before: Record<string, unknown>; values: Record<string, unknown>;
  evidence: { quote: string; start: number; end: number }[]; normalization?: string | null };
export type ExecutionReceipt = { execution_id: string; suggestion_id: string; opportunity_id: string; result_version: number; activity_ids: string[]; selected_change_ids: string[] };

export function ApplyPanel({ suggestionId, version, opportunityVersion, changes, enabled, onSaved }: {
  suggestionId: string; version: number; opportunityVersion: number; changes: FrozenChange[]; enabled: boolean;
  onSaved: (receipt: ExecutionReceipt) => void | Promise<void>;
}) {
  const [chosen, setChosen] = useState<string[]>([]), [confirmed, setConfirmed] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [receipt, setReceipt] = useState<ExecutionReceipt | null>(null);
  const intent = useRef({ body: '', key: '' }), committed = useRef(false), baseVersion = useRef<number | null>(null);
  async function apply() {
    if (busy || committed.current || !enabled || !confirmed || !chosen.length) return;
    setBusy(true); setError('');
    const body = JSON.stringify({ expected_version: baseVersion.current ?? version, expected_opportunity_version: opportunityVersion,
      selected_change_ids: [...chosen].sort(), confirmed: true });
    if (intent.current.body !== body) intent.current = { body, key: crypto.randomUUID() };
    let saved: ExecutionReceipt;
    try { saved = await request<ExecutionReceipt>(`/api/v1/suggestions/${suggestionId}/apply`, { method: 'POST', headers: { 'Idempotency-Key': intent.current.key }, body }); }
    catch (err) { setError(err instanceof Error ? err.message : '执行失败，选择已保留。'); setBusy(false); return; }
    committed.current = true; setReceipt(saved);
    try { await onSaved(saved); } catch { setError('执行已成功，但最新资料刷新失败。请重新加载，不要重复执行。'); }
    finally { setBusy(false); }
  }
  return <section aria-label="受控执行"><h3>逐项确认变更</h3><p>默认不选择。金额与币种是一整组；未选项不会执行，同一草稿不能分批补执行。</p>
    {changes.map(change => <article key={change.id}><label><input type="checkbox" checked={chosen.includes(change.id)} disabled={!enabled || busy || !!receipt}
      onChange={event => { if (baseVersion.current === null) baseVersion.current = version; setConfirmed(false);
        setChosen(current => event.target.checked ? [...current, change.id] : current.filter(id => id !== change.id)); }} />
      {change.kind === 'FIELD' ? `字段：${Object.keys(change.values).join(' / ')}` : change.kind === 'NOTE' ? '追加备注 NOTE' : '追加任务 TASK'}</label>
      <div className="crm-table"><table><thead><tr><th>字段</th><th>变更前</th><th>变更后</th></tr></thead><tbody>{Object.entries(change.values).map(([key, value]) =>
        <tr key={key}><td>{key}</td><td>{JSON.stringify(change.before[key] ?? null)}</td><td>{JSON.stringify(value)}</td></tr>)}</tbody></table></div>
      {change.evidence.map((evidence, index) => <blockquote key={index}>{evidence.quote}</blockquote>)}
      {change.normalization && <p>{change.normalization}</p>}{change.kind === 'NOTE' && <p>备注记录时间为执行时刻，不代表会议发生时间。</p>}
    </article>)}
    <label><input type="checkbox" checked={confirmed} disabled={!enabled || busy || !!receipt || !chosen.length} onChange={event => setConfirmed(event.target.checked)} />我已核对所选变更及依据，确认执行</label>
    <button className="primary" disabled={!enabled || busy || !!receipt || !confirmed || !chosen.length} onClick={() => void apply()}>确认执行所选变更</button>
    {!enabled && <p>当前草稿不可执行；过期上下文需生成新草稿。</p>}
    {receipt && <p role="status">执行已完成，商机版本 {receipt.result_version}；新增活动 {receipt.activity_ids.length} 条。</p>}
    {error && <ErrorState message={error} />}
  </section>;
}
