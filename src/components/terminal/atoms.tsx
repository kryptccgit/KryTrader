import { ReactNode } from 'react';
import { HelpCircle } from 'lucide-react';
import type { DataSource, MarketSummary, SourcedField } from '@shared/market';
import { cls } from '../../utils/format';

const SOURCE_LABEL: Record<DataSource, string> = {
  'kalshi-ws': 'our own websocket feed, timestamped when this machine received it',
  'kalshi-rest': 'a REST read from Kalshi, made for this view',
  'kalshi-cache': 'a recent REST read, served from cache',
  'local-db': 'our own recorded history',
  derived: 'computed here from the other numbers on this row',
};

const SOURCE_SHORT: Record<DataSource, string> = {
  'kalshi-ws': 'WS',
  'kalshi-rest': 'REST',
  'kalshi-cache': 'CACHE',
  'local-db': 'LOCAL',
  derived: 'CALC',
};

export function Unknown({ why, className }: { why?: string; className?: string }) {
  return (
    <span
      className={cls('cursor-help text-krypt-dim', className)}
      title={why || 'Nobody could produce this value, so nothing is shown. It is not zero.'}
    >
      —
    </span>
  );
}

export function Cents({
  value, why, className, sign,
}: {
  value: number | null | undefined;
  why?: string;
  className?: string;
  sign?: boolean;
}) {
  if (value === null || value === undefined) return <Unknown why={why} className={className} />;
  const s = sign && value > 0 ? '+' : '';
  const txt = Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1);
  return <span className={cls('font-mono tabular-nums', className)}>{s}{txt}¢</span>;
}

export function Count({
  value, why, className,
}: { value: number | null | undefined; why?: string; className?: string }) {
  if (value === null || value === undefined) return <Unknown why={why} className={className} />;
  return (
    <span className={cls('font-mono tabular-nums', className)}>
      {value.toLocaleString()}
    </span>
  );
}

export function Usd({
  value, why, className, sign, dp = 2,
}: {
  value: number | null | undefined;
  why?: string;
  className?: string;
  sign?: boolean;
  dp?: number;
}) {
  if (value === null || value === undefined) return <Unknown why={why} className={className} />;
  const s = sign && value > 0 ? '+' : value < 0 ? '−' : '';
  return (
    <span className={cls('font-mono tabular-nums', className)}>
      {s}${Math.abs(value).toLocaleString(undefined, {
        minimumFractionDigits: dp, maximumFractionDigits: dp,
      })}
    </span>
  );
}

export function Pnl({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined) {
    return <Unknown why="No reconciled cost basis, so the P&L on this row is unknown — not zero." />;
  }
  return (
    <Usd
      value={value}
      sign
      className={cls(value > 0 ? 'text-krypt-win' : value < 0 ? 'text-krypt-loss' : 'text-white', className)}
    />
  );
}

export function Provenance({
  row, field, className,
}: { row: MarketSummary; field: SourcedField; className?: string }) {
  const src = row.sources?.[field];
  if (!src) return null;
  return (
    <span
      className={cls(
        'ml-1 cursor-help rounded px-1 text-[9px] font-medium uppercase tracking-wider',
        src === 'kalshi-ws'
          ? 'bg-krypt-purple/20 text-krypt-purple'
          : 'bg-white/5 text-krypt-dim',
        className,
      )}
      title={`${field}: ${SOURCE_LABEL[src]} · observed ${row.observedAt}`}
    >
      {SOURCE_SHORT[src]}
    </span>
  );
}

export function Caveat({ children, className }: { children: ReactNode; className?: string }) {
  if (!children) return null;
  return (
    <div
      className={cls(
        'flex items-start gap-2 rounded-lg border border-krypt-border bg-krypt-surface2/60 px-3 py-2 text-[11px] leading-relaxed text-krypt-muted',
        className,
      )}
    >
      <HelpCircle className="mt-px h-3.5 w-3.5 shrink-0 text-krypt-dim" />
      <div>{children}</div>
    </div>
  );
}

export function SidePill({
  side, className,
}: { side: 'yes' | 'no' | null; className?: string }) {
  if (side === null) return <Unknown why="Kalshi did not say which side this order is on." className={className} />;
  return (
    <span
      className={cls(
        'rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
        side === 'yes'
          ? 'bg-krypt-win/15 text-krypt-win'
          : 'bg-krypt-loss/15 text-krypt-loss',
        className,
      )}
    >
      {side}
    </span>
  );
}

export function TimeToClose({ minutes }: { minutes: number | null | undefined }) {
  if (minutes === null || minutes === undefined) {
    return <Unknown why="Kalshi did not report a close time for this market." />;
  }
  if (minutes <= 0) return <span className="text-krypt-dim">closed</span>;
  const urgent = minutes <= 60;
  const txt =
    minutes < 90 ? `${Math.round(minutes)}m`
      : minutes < 60 * 48 ? `${(minutes / 60).toFixed(minutes < 60 * 10 ? 1 : 0)}h`
        : `${Math.round(minutes / 1440)}d`;
  return (
    <span className={cls('font-mono tabular-nums', urgent ? 'text-krypt-warn' : 'text-krypt-muted')}>
      {txt}
    </span>
  );
}

export function ProbBar({
  value, className,
}: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined) {
    return <div className={cls('h-1 rounded-full bg-white/5', className)} title="No two-sided quote, so there is no implied probability." />;
  }
  return (
    <div className={cls('h-1 overflow-hidden rounded-full bg-white/5', className)}>
      <div
        className="h-full rounded-full bg-gradient-to-r from-krypt-indigo to-krypt-purple"
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}
