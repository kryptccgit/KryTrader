import { useEffect, useRef, useState } from 'react';
import type { TradingStatus } from '@shared/types';
import { cls } from '../utils/format';
import { publishActivity } from '../state/activity';

export function WhyNotTrading() {
  const [st, setSt] = useState<TradingStatus | null>(null);
  const halted = useRef<{ daily: boolean; c15: boolean } | null>(null);

  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const s = await window.krypt.trading.status();
        if (alive) setSt(s);
        publishActivity(() => {
          if (!s) return null;
          const gate = s.main.find((g) => g.id === 'dailyRisk');
          const now = { daily: gate?.state === 'blocked', c15: !!s.c15?.takeProfitHalted };
          const was = halted.current;
          halted.current = now;
          if (!was) return null;
          if (now.daily && !was.daily) return { kind: 'halt', scope: 'daily', reason: gate?.reason || 'daily stop/take-profit' };
          if (now.c15 && !was.c15) return { kind: 'halt', scope: 'c15TakeProfit', reason: '15m session take-profit reached' };
          return null;
        });
      } catch {}
    };
    void pull();
    const t = setInterval(pull, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!st) return null;

  const filters = Object.entries(st.mainFilterCounts || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);
  const c15Blocks = Object.entries(st.c15?.blockReasons || {});

  return (
    <div className="rounded-xl border border-krypt-border bg-krypt-surface2/40 p-3">
      <div className="mb-2 text-sm font-semibold text-white">Why isn&apos;t it trading?</div>

      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-krypt-dim">Main engine</div>
      <ul className="space-y-1">
        {st.main.map((g) => (
          <li key={g.id} className="flex items-start gap-2 text-xs">
            <span className={cls(
              'mt-0.5 inline-block h-2 w-2 flex-none rounded-full',
              g.state === 'ok' ? 'bg-krypt-win' : g.state === 'off' ? 'bg-krypt-dim/50' : 'bg-krypt-loss',
            )} />
            <span className={g.state === 'blocked' ? 'text-white' : 'text-krypt-dim'}>
              {g.label}
              {g.reason && <span className="ml-1 text-krypt-loss">— {g.reason}</span>}
            </span>
          </li>
        ))}
      </ul>
      {filters.length > 0 && (
        <p className="mt-1.5 text-[11px] text-krypt-dim">
          Last scan: {st.mainCandidates} candidates, {st.mainPlaced} placed. Top skip reasons:{' '}
          {filters.map(([why, n]) => `${why} (×${n})`).join(' · ')}
        </p>
      )}

      <div className="mb-1 mt-3 text-[11px] font-semibold uppercase tracking-wide text-krypt-dim">15-minute crypto</div>
      {!st.c15.enabled ? (
        <p className="text-xs text-krypt-dim">Feature is off (open positions are still managed).</p>
      ) : (
        <>
          <p className="text-xs text-krypt-dim">
            {st.c15.live
              ? 'LIVE — entries armed.'
              : st.c15.env === 'paper'
                ? 'Paper mode: every runner trades the paper simulation.'
                : `Monitor-only: ${!st.c15.authed ? 'not authenticated' : 'live switch is off'}.`}
            {st.c15.takeProfitHalted && ' Session take-profit reached — no new entries.'}
          </p>
          {c15Blocks.length > 0 && (
            <ul className="mt-1 space-y-0.5">
              {c15Blocks.map(([asset, why]) => (
                <li key={asset} className="text-[11px] text-krypt-dim">
                  <span className="font-mono text-white">{asset}</span> — {why}
                </li>
              ))}
            </ul>
          )}
          {c15Blocks.length === 0 && st.c15.live && (
            <p className="mt-1 text-[11px] text-krypt-dim">No blocked assets this tick — waiting for a signal to qualify.</p>
          )}
        </>
      )}
    </div>
  );
}
