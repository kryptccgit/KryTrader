import { useMemo, useState } from 'react';
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import type { Microstructure } from '@shared/market';
import { usePoll } from '../../state/TerminalProvider';
import { cls } from '../../utils/format';
import { Caveat, Cents, Unknown } from './atoms';

export function MicrostructurePanel({ ticker }: { ticker: string }) {
  const [probe, setProbe] = useState('');
  const probeN = Number(probe);
  const probeValid = Number.isFinite(probeN) && probeN >= 1 && probeN <= 99;

  const { data, error, loading } = usePoll<Microstructure>(
    () => window.krypt.terminal.micro({
      ticker, ...(probeValid ? { probeCents: probeN } : {}),
    }),
    3_000,
    [ticker, probeValid ? probeN : 0],
  );

  const points = useMemo(
    () => (data?.samples ?? []).map((s) => ({
      ts: s.ts,
      spread: s.bid !== null && s.ask !== null ? Math.round((s.ask - s.bid) * 10) / 10 : null,
      bid: s.bid,
      ask: s.ask,
    })),
    [data],
  );

  if (loading && !data) {
    return <div className="py-8 text-center text-sm text-krypt-muted">Reading our tape…</div>;
  }
  if (error && !data) {
    return <div className="py-8 text-center text-sm text-krypt-muted">{error}</div>;
  }
  if (!data) return null;

  return (
    <div>
      <div className="mb-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Stat
          label="Median spread"
          value={<Cents value={data.medianSpreadCents} why="Not enough two-sided samples yet." />}
          hint="what it usually costs to cross"
        />
        <Stat
          label="Worst 10%"
          value={<Cents value={data.p90SpreadCents} why="Not enough two-sided samples yet." />}
          hint="the spread at its 90th percentile"
        />
        <Stat
          label="Two-sided"
          value={data.twoSidedPct === null
            ? <Unknown />
            : <span className="font-mono">{(data.twoSidedPct * 100).toFixed(0)}%</span>}
          hint="of the time both sides were quoted"
        />
        <Stat
          label="Quote lifetime"
          value={data.quoteLifetimeSec === null
            ? <Unknown why="The top of book has not changed yet in the recorded window." />
            : <span className="font-mono">{data.quoteLifetimeSec.toFixed(1)}s</span>}
          hint="how long the top of book survives"
        />
      </div>

      <div className="h-40 w-full">
        {points.length < 2 ? (
          <div className="grid h-full place-items-center px-8 text-center text-sm text-krypt-muted">
            Not enough samples yet — this records while you have the market open.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: -22 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="ts"
                tickFormatter={(v) => new Date(Number(v) * 1000)
                  .toLocaleTimeString(undefined, { minute: '2-digit', second: '2-digit' })}
                stroke="rgba(255,255,255,0.25)"
                tick={{ fontSize: 10 }}
                minTickGap={50}
              />
              <YAxis
                stroke="rgba(255,255,255,0.25)"
                tick={{ fontSize: 10 }}
                width={34}
                allowDecimals={false}
              />
              <Tooltip content={<MicroTooltip />} />
              <Area
                type="stepAfter" dataKey="spread" stroke="#A855F7"
                fill="url(#spreadFill)" strokeWidth={1.5}
                isAnimationActive={false} connectNulls={false}
              />
              <defs>
                <linearGradient id="spreadFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#A855F7" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#A855F7" stopOpacity={0.02} />
                </linearGradient>
              </defs>
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="mt-3 rounded-lg border border-krypt-border bg-krypt-surface2/40 p-3">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-krypt-muted">
          Would this price have filled?
        </div>
        <div className="flex items-center gap-2">
          <input
            value={probe}
            onChange={(e) => setProbe(e.target.value.replace(/[^0-9.]/g, ''))}
            placeholder="buy YES at… ¢"
            inputMode="decimal"
            className="krypt-input w-32 font-mono"
          />
          <div className="text-[11px] text-krypt-muted">
            {!probeValid ? (
              <span className="text-krypt-dim">Enter a price between 1¢ and 99¢.</span>
            ) : data.probeFillablePct === null ? (
              <Unknown why="No asks recorded in the window yet." />
            ) : (
              <>
                Immediately fillable in{' '}
                <span className={cls(
                  'font-mono',
                  data.probeFillablePct > 0.5 ? 'text-krypt-win' : 'text-krypt-warn',
                )}>
                  {(data.probeFillablePct * 100).toFixed(0)}%
                </span>{' '}
                of the {data.sampleCount} samples recorded.
              </>
            )}
          </div>
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-krypt-dim">
          This is a measurement of the window above, not a forecast: it says how
          often the ask was already at or below your price, nothing about what
          happens next.
        </p>
      </div>

      {data.note && <Caveat className="mt-3">{data.note}</Caveat>}
    </div>
  );
}

function Stat({
  label, value, hint,
}: { label: string; value: React.ReactNode; hint: string }) {
  return (
    <div className="rounded-lg border border-krypt-border bg-krypt-surface2/40 px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-wider text-krypt-dim">{label}</div>
      <div className="text-base text-white">{value}</div>
      <div className="text-[9px] leading-tight text-krypt-dim">{hint}</div>
    </div>
  );
}

function MicroTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-krypt-border bg-krypt-surface/95 px-3 py-2 text-[11px] shadow-krypt-soft backdrop-blur">
      <div className="mb-1 text-krypt-dim">
        {new Date(Number(label) * 1000).toLocaleTimeString()}
      </div>
      <div className="flex justify-between gap-4">
        <span className="text-krypt-muted">Spread</span>
        {p.spread === null
          ? <span className="text-krypt-dim">— one-sided</span>
          : <span className="font-mono text-white">{p.spread}¢</span>}
      </div>
      <div className="flex justify-between gap-4">
        <span className="text-krypt-muted">Bid / Ask</span>
        <span className="font-mono text-white">
          {p.bid ?? '—'} / {p.ask ?? '—'}
        </span>
      </div>
    </div>
  );
}
