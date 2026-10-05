import { useEffect, useState } from 'react';
import { Check, Plus, X, Library, AlertTriangle } from 'lucide-react';
import type { TurbineLibrary as TLib, TurbineStrategy } from '@shared/types';

export function TurbineLibrary({ onClose, onAdd }: {
  onClose: () => void; onAdd: (s: TurbineStrategy) => void;
}) {
  const [lib, setLib] = useState<TLib | null>(null);
  const [loading, setLoading] = useState(true);
  const [added, setAdded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let alive = true;
    window.krypt?.turbine?.library()
      .then((l) => { if (alive) { setLib(l); setLoading(false); } })
      .catch(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const addRunner = (s: TurbineStrategy) => {
    onAdd(s);
    setAdded((prev) => new Set(prev).add(s.name));
  };

  const edgeCell = (s: TurbineStrategy) => {
    const b = s.backtest;
    if (!b || b.n == null || b.n === 0) return <span className="text-krypt-dim">— not tested</span>;
    const net = b.netCentsPerContract ?? 0;
    const sig = b.t != null && Math.abs(b.t) >= 2 && (b.n ?? 0) >= 30;
    return (
      <span className="font-mono">
        <span className={net >= 0 ? 'text-krypt-win' : 'text-krypt-loss'}>{net >= 0 ? '+' : ''}{net.toFixed(1)}¢</span>
        <span className="ml-2 text-krypt-dim">t{b.t?.toFixed(1) ?? '—'} · n{b.n} · {b.winRate != null ? `${Math.round(b.winRate * 100)}%` : '—'}</span>
        {sig && <span className="ml-1.5 rounded bg-krypt-win/15 px-1 py-0.5 text-[9px] uppercase text-krypt-win">sig</span>}
      </span>
    );
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-6 backdrop-blur-sm" onClick={onClose}>
      <div className="my-4 w-full max-w-4xl rounded-2xl border border-krypt-border bg-krypt-void shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-krypt-border px-5 py-4">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-krypt-purple/15 text-krypt-purple"><Library className="h-5 w-5" /></span>
          <div className="flex-1">
            <div className="font-pixel text-[11px] uppercase tracking-[0.16em] text-white">Strategy Library</div>
            <div className="text-xs text-krypt-muted">Momentum/VWAP strategies imported from Turbine, ranked by fee-adjusted edge on <em>your</em> recorded data. Add one as a paper runner to test it.</div>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-krypt-muted hover:bg-white/5 hover:text-white"><X className="h-5 w-5" /></button>
        </div>

        <div className="flex items-center gap-2 border-b border-krypt-border bg-krypt-warn/[0.06] px-5 py-2 text-[11px] text-krypt-warn">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          ★ Settlement Edge = the one class with a measured, holdout-robust edge (model prices the contract ≥2¢ over the ask). The rest are ranked <b>in-sample</b>, which flatters overfit momentum — trust the Coin Optimizer's holdout, not this order. Paper-test before going live.
        </div>

        <div className="max-h-[60vh] overflow-y-auto px-2 py-2">
          {loading && <div className="px-4 py-8 text-center text-sm text-krypt-muted">Loading library…</div>}
          {!loading && !lib && <div className="px-4 py-8 text-center text-sm text-krypt-muted">Backend not running — start the app to load the library.</div>}
          {lib?.strategies.map((s, i) => (
            <div key={s.name} className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-white/[0.03]">
              <span className="w-5 text-right text-xs text-krypt-dim">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm text-white">{s.name}</span>
                  <span className="rounded bg-krypt-surface2 px-1.5 py-0.5 text-[10px] font-medium text-krypt-muted">{s.asset ?? 'ALL'}</span>
                  <span className="rounded bg-krypt-surface2 px-1.5 py-0.5 text-[10px] text-krypt-dim">{s.archetype}</span>
                </div>
                <div className="mt-0.5 text-xs">{edgeCell(s)}</div>
              </div>
              {added.has(s.name) ? (
                <span className="flex items-center gap-1 rounded-lg bg-krypt-win/15 px-2.5 py-1.5 text-xs text-krypt-win"><Check className="h-3.5 w-3.5" /> Added</span>
              ) : (
                <button onClick={() => addRunner(s)} className="flex items-center gap-1 rounded-lg border border-krypt-border bg-krypt-surface px-2.5 py-1.5 text-xs text-white hover:border-krypt-purple/50">
                  <Plus className="h-3.5 w-3.5" /> Add runner
                </button>
              )}
            </div>
          ))}
          {lib && lib.skipped.length > 0 && (
            <div className="px-4 py-2 text-[11px] text-krypt-dim">
              Not importable ({lib.skipped.length}): {lib.skipped.join(', ')} — need mechanics the engine can't express (both-side or stateful entries).
            </div>
          )}
        </div>

        <div className="border-t border-krypt-border px-5 py-2 text-[11px] text-krypt-dim">
          Added strategies land in Multi-Run as disabled <b>paper</b> runners on their coin. Open a runner, flip it on, and race them.
        </div>
      </div>
    </div>
  );
}
