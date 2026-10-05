import { useMemo, useState } from 'react';
import type { SignalRow } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { Empty, Page } from '../components/common';
import { cls, fmtRelative, fmtUsd } from '../utils/format';

export function SignalsPage() {
  const { signals } = useApp();
  const [src, setSrc] = useState<'all' | 'whale' | 'momentum'>('all');
  const [minConf, setMinConf] = useState(0);

  const filtered = useMemo(() => {
    return signals.filter((s) => {
      if (src !== 'all' && s.source !== src) return false;
      if (s.confidence < minConf) return false;
      return true;
    });
  }, [signals, src, minConf]);

  return (
    <Page
      title="Signals"
      subtitle="Live whale + momentum signals as the scanners produce them."
    >
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-krypt-border bg-krypt-surface p-3">
        <div className="inline-flex rounded-md border border-krypt-border bg-krypt-surface2 p-0.5">
          {(['all', 'whale', 'momentum'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSrc(s)}
              className={cls(
                'rounded-[6px] px-3 py-1.5 text-xs uppercase tracking-wider',
                src === s ? 'bg-white/10 text-white' : 'text-krypt-muted hover:text-white',
              )}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <label className="text-xs text-krypt-muted">Min confidence</label>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={minConf}
            onChange={(e) => setMinConf(parseInt(e.target.value))}
            className="accent-krypt-purple"
          />
          <span className="font-mono text-xs text-white">{minConf}%</span>
        </div>
      </div>

      {filtered.length === 0 ? (
        <Empty title="No signals" description="Loosen the filter or wait for the next scan cycle." />
      ) : (
        <div className="overflow-hidden rounded-xl border border-krypt-border">
          <table className="krypt-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Source</th>
                <th>Ticker</th>
                <th>Title</th>
                <th>Cat</th>
                <th>Side</th>
                <th>Price</th>
                <th>Conf</th>
                <th>Edge</th>
                <th>$</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => <SignalRowView key={`${s.source}:${s.id}`} s={s} />)}
            </tbody>
          </table>
        </div>
      )}
    </Page>
  );
}

function SignalRowView({ s }: { s: SignalRow }) {
  return (
    <tr>
      <td className="text-xs text-krypt-muted">{fmtRelative(s.createdAt)}</td>
      <td>
        <span className={cls(
          'inline-flex rounded-md px-1.5 py-0.5 text-[10px] uppercase',
          s.source === 'whale'
            ? 'bg-krypt-purple/15 text-krypt-purple'
            : 'bg-krypt-pink/15 text-krypt-pink',
        )}>
          {s.source}
        </span>
      </td>
      <td className="font-mono text-xs">{s.ticker}</td>
      <td className="max-w-[260px] truncate text-xs text-krypt-muted">{s.title}</td>
      <td className="text-xs text-krypt-muted">{s.category || '—'}</td>
      <td>
        <span className={cls(
          'rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase',
          s.direction === 'yes' ? 'bg-krypt-win/10 text-krypt-win' : 'bg-krypt-loss/10 text-krypt-loss',
        )}>
          {s.direction}
        </span>
      </td>
      <td className="font-mono text-xs">{s.priceCents}¢</td>
      <td className="font-mono text-xs">{s.confidence.toFixed(1)}%</td>
      <td className="font-mono text-xs text-krypt-purple">+{s.edgePts.toFixed(1)}</td>
      <td className="font-mono text-xs text-krypt-muted">
        {s.dollarValue ? fmtUsd(s.dollarValue) : '—'}
      </td>
      <td>
        {s.resolved ? (
          <span className={cls(
            'rounded-md px-1.5 py-0.5 text-[10px] uppercase',
            s.outcomeCorrect === 1 ? 'bg-krypt-win/10 text-krypt-win' : 'bg-krypt-loss/10 text-krypt-loss',
          )}>
            {s.outcomeCorrect === 1 ? 'won' : 'lost'}
          </span>
        ) : s.traded ? (
          <span className="rounded-md bg-krypt-indigo/10 px-1.5 py-0.5 text-[10px] uppercase text-krypt-indigo">
            traded
          </span>
        ) : (
          <span className="text-[10px] text-krypt-dim">open</span>
        )}
      </td>
    </tr>
  );
}
