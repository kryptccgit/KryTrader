import { useMemo, useState } from 'react';
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import type { CandleInterval, CandleSeries, MarketSummary } from '@shared/market';
import { usePoll } from '../../state/TerminalProvider';
import { cls } from '../../utils/format';
import { Caveat } from './atoms';


const RANGES: { label: string; intervalMin: CandleInterval; lookbackMin: number }[] = [
  { label: '1H', intervalMin: 1, lookbackMin: 60 },
  { label: '4H', intervalMin: 1, lookbackMin: 240 },
  { label: '1D', intervalMin: 60, lookbackMin: 60 * 24 },
  { label: '1W', intervalMin: 60, lookbackMin: 60 * 24 * 7 },
  { label: '1M', intervalMin: 1440, lookbackMin: 60 * 24 * 30 },
  { label: '3M', intervalMin: 1440, lookbackMin: 60 * 24 * 90 },
];

function fmtTs(ts: number, intervalMin: number): string {
  const d = new Date(ts * 1000);
  if (intervalMin >= 1440) return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  if (intervalMin >= 60) return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric' });
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export function ProbabilityChart({
  ticker, market,
}: { ticker: string; market: MarketSummary }) {
  const [rangeIdx, setRangeIdx] = useState(1);
  const range = RANGES[rangeIdx];

  const { data, error, loading } = usePoll<CandleSeries>(
    () => window.krypt.terminal.candles({
      ticker, intervalMin: range.intervalMin, lookbackMin: range.lookbackMin,
    }),
    range.intervalMin === 1 ? 15_000 : 60_000,
    [ticker, range.intervalMin, range.lookbackMin],
  );

  const points = useMemo(
    () => (data?.candles ?? []).map((c) => ({
      ts: c.ts,
      close: c.close,
      bid: c.yesBidClose,
      ask: c.yesAskClose,
      volume: c.volume,
    })),
    [data],
  );

  const traded = points.filter((p) => p.close !== null).length;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {RANGES.map((r, i) => (
            <button
              key={r.label}
              onClick={() => setRangeIdx(i)}
              className={cls(
                'rounded px-2 py-1 text-[11px] font-medium transition-colors',
                i === rangeIdx
                  ? 'bg-krypt-purple/15 text-white'
                  : 'text-krypt-dim hover:bg-white/5 hover:text-white',
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3 text-[10px] text-krypt-dim">
          <span className="flex items-center gap-1">
            <span className="h-0.5 w-4 rounded bg-krypt-purple" /> traded
          </span>
          <span className="flex items-center gap-1">
            <span className="h-0.5 w-4 rounded bg-krypt-win/60" /> bid
          </span>
          <span className="flex items-center gap-1">
            <span className="h-0.5 w-4 rounded bg-krypt-loss/60" /> ask
          </span>
        </div>
      </div>

      <div className="h-64 w-full">
        {loading && !data ? (
          <div className="grid h-full place-items-center text-sm text-krypt-muted">
            Loading history…
          </div>
        ) : error && !data ? (
          <div className="grid h-full place-items-center px-8 text-center text-sm text-krypt-muted">
            {error}
          </div>
        ) : points.length === 0 ? (
          <div className="grid h-full place-items-center px-8 text-center text-sm text-krypt-muted">
            No candles in this window. Nothing is drawn rather than a flat line
            through a period that never traded.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="ts"
                tickFormatter={(v) => fmtTs(Number(v), range.intervalMin)}
                stroke="rgba(255,255,255,0.25)"
                tick={{ fontSize: 10 }}
                minTickGap={44}
              />
              <YAxis
                domain={[0, 100]}
                ticks={[0, 25, 50, 75, 100]}
                tickFormatter={(v) => `${v}`}
                stroke="rgba(255,255,255,0.25)"
                tick={{ fontSize: 10 }}
                width={38}
              />
              <ReferenceLine y={50} stroke="rgba(255,255,255,0.12)" strokeDasharray="3 3" />
              {market.yesBid !== null && market.yesAsk !== null && (
                <ReferenceLine
                  y={(market.yesBid + market.yesAsk) / 2}
                  stroke="rgba(168,85,247,0.35)"
                  strokeDasharray="2 4"
                />
              )}
              <Tooltip content={<ChartTooltip intervalMin={range.intervalMin} />} />
              <Line
                type="linear" dataKey="bid" stroke="#22C55E" strokeOpacity={0.45}
                strokeWidth={1} dot={false} isAnimationActive={false} connectNulls
              />
              <Line
                type="linear" dataKey="ask" stroke="#EF4444" strokeOpacity={0.45}
                strokeWidth={1} dot={false} isAnimationActive={false} connectNulls
              />
              <Line
                type="linear" dataKey="close" stroke="#A855F7" strokeWidth={2}
                dot={false} isAnimationActive={false} connectNulls={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {data && (
        <div className="mt-2 space-y-2">
          <div className="text-[11px] text-krypt-dim">
            {traded} of {points.length} periods traded
            {data.emptyPeriods > 0 && ` · ${data.emptyPeriods} gaps left as gaps`}
            {' · '}prices are YES cents, which is the market’s probability
          </div>
          {data.note && <Caveat>{data.note}</Caveat>}
        </div>
      )}
    </div>
  );
}

function ChartTooltip({ active, payload, label, intervalMin }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-krypt-border bg-krypt-surface/95 px-3 py-2 text-[11px] shadow-krypt-soft backdrop-blur">
      <div className="mb-1 text-krypt-dim">{fmtTs(Number(label), intervalMin)}</div>
      <Row label="Traded" value={p.close} empty="no trades this period" />
      <Row label="Bid" value={p.bid} empty="no bid" />
      <Row label="Ask" value={p.ask} empty="no ask" />
      {p.volume !== null && p.volume !== undefined && (
        <div className="mt-1 text-krypt-dim">{p.volume.toLocaleString()} contracts</div>
      )}
    </div>
  );
}

function Row({ label, value, empty }: { label: string; value: number | null; empty: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-krypt-muted">{label}</span>
      {value === null || value === undefined
        ? <span className="text-krypt-dim">— {empty}</span>
        : <span className="font-mono text-white">{value.toFixed(1)}¢</span>}
    </div>
  );
}
