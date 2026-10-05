import { ExternalLink } from 'lucide-react';
import { cls } from '../utils/format';
import { openKalshiMarket } from '../utils/kalshi';

export function TickerLink({
  ticker,
  eventTicker,
  env,
  label,
  className,
}: {
  ticker: string;
  eventTicker?: string;
  env?: string;
  label?: string;
  className?: string;
}) {
  if (!ticker) return <span className="text-krypt-dim">{label ?? '—'}</span>;
  return (
    <button
      type="button"
      onClick={() => void openKalshiMarket({ ticker, eventTicker, env })}
      title="Open this market on Kalshi"
      className={cls(
        'group inline-flex items-center gap-1 font-mono text-xs text-krypt-purple',
        'transition-colors hover:text-krypt-pink hover:underline',
        className,
      )}
    >
      {label ?? ticker}
      <ExternalLink className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-70" />
    </button>
  );
}
