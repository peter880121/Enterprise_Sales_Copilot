import { LoaderCircle, TriangleAlert } from 'lucide-react';

export function Loading({ text = '正在读取工作空间…' }: { text?: string }) {
  return <div className="state" role="status"><LoaderCircle className="spin" size={20} />{text}</div>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="state error" role="alert"><TriangleAlert size={20} />
    <p>{message}</p>{onRetry && <button onClick={onRetry}>重新加载</button>}</div>;
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return <div className="empty"><span className="empty-mark">◇</span>
    <h2>{title}</h2><p>{description}</p></div>;
}
