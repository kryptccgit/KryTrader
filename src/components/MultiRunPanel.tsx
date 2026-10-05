import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CalendarClock, Copy, Gem, Library, LayoutGrid, Plus, SlidersHorizontal, Trash2, X } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { cls, fmtUsd } from '../utils/format';
import { Switch } from './common';
import { TurbineLibrary } from './TurbineLibrary';
import { CoinOptimizer } from './CoinOptimizer';
import type {
  Crypto15mRunner, Crypto15mRunnerStatus, Crypto15mStatus, Profile, TraderConfig,
} from '@shared/types';

const C15_ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'HYPE', 'BNB'];

const RUNNER_SLICE_EXCLUDE = new Set([
  'crypto15mEnabled', 'crypto15mLive', 'crypto15mRunners', 'crypto15mAssets',
]);

function crypto15mSlice(cfg: Partial<TraderConfig>): Partial<TraderConfig> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(cfg)) {
    if (k.startsWith('crypto15m') && !RUNNER_SLICE_EXCLUDE.has(k)) out[k] = v;
  }
  return out as Partial<TraderConfig>;
}

function newId(): string {
  try { return crypto.randomUUID().slice(0, 8); } catch { return Math.random().toString(36).slice(2, 10); }
}

export function MultiRunPanel({ onClose }: { onClose: () => void }) {
  const { config, state } = useApp();
  const [runners, setRunners] = useState<Crypto15mRunner[]>(
    () => (config?.crypto15mRunners as Crypto15mRunner[] | null) ?? [],
  );
  const [status, setStatus] = useState<Crypto15mStatus | null>(null);
  const [showLibrary, setShowLibrary] = useState(false);
  const [showOptimizer, setShowOptimizer] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleExpanded = (id: string) => setExpanded((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const c15Profiles: Profile[] = useMemo(
    () => (state?.customProfiles ?? []).filter((p) => p.kind === 'crypto15m'),
    [state?.customProfiles],
  );

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = await window.krypt?.crypto15m?.status();
        if (alive && s) setStatus(s);
      } catch {  }
    };
    tick();
    const iv = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  const statById = useMemo(() => {
    const m = new Map<string, Crypto15mRunnerStatus>();
    for (const r of status?.runners ?? []) m.set(r.id, r);
    return m;
  }, [status]);

  const persist = (next: Crypto15mRunner[]) => {
    setRunners(next);
    void window.krypt?.config?.update({ crypto15mRunners: next.length ? next : null });
  };

  const patch = (id: string, p: Partial<Crypto15mRunner>) =>
    persist(runners.map((r) => (r.id === id ? { ...r, ...p } : r)));

  const addRunner = (seed?: Partial<Crypto15mRunner>) => {
    const id = newId();
    persist([...runners, {
      id, name: seed?.name ?? `Runner ${runners.length + 1}`,
      coins: seed?.coins ?? [], mode: seed?.mode ?? 'paper',
      enabled: false, config: seed?.config ?? {}, profileId: seed?.profileId,
    }]);
  };

  const duplicate = (r: Crypto15mRunner) =>
    persist([...runners, { ...r, id: newId(), name: `${r.name} copy`, enabled: false, coins: [] }]);

  const addFromLibrary = (s: { name: string; asset: string | null; config: Partial<TraderConfig> }) =>
    persist([...runners, {
      id: newId(), name: s.name, coins: s.asset ? [s.asset] : null, mode: 'paper', enabled: false, config: s.config,
    }]);

  const remove = (id: string) => persist(runners.filter((r) => r.id !== id));

  const takenBefore = (idx: number): Set<string> => {
    const taken = new Set<string>();
    runners.forEach((r, i) => {
      if (i < idx && r.enabled) (r.coins ?? C15_ASSETS).forEach((c) => taken.add(c));
    });
    return taken;
  };

  const masterOn = !!config?.crypto15mEnabled;
  const anyLiveEnabled = runners.some((r) => r.enabled && r.mode === 'live');

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-6 backdrop-blur-sm" onClick={onClose}>
      <div
        className="my-4 w-full max-w-4xl rounded-2xl border border-krypt-border bg-krypt-void shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-krypt-border px-5 py-4">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-krypt-purple/15 text-krypt-purple">
            <LayoutGrid className="h-5 w-5" />
          </span>
          <div className="flex-1">
            <div className="font-pixel text-[11px] uppercase tracking-[0.16em] text-white">Multi-Run · 15m Crypto</div>
            <div className="text-xs text-krypt-muted">Run different strategies on different coins at the same time. Paper races cost nothing — promote the winners to live.</div>
          </div>
          <button
            onClick={() => setShowOptimizer(true)}
            className="flex items-center gap-1.5 rounded-lg border border-krypt-border bg-krypt-surface px-2.5 py-1.5 text-xs text-white hover:border-krypt-purple/50"
            title="Sweep strategies per hour-bucket for a coin and assemble the best 24h schedule"
          >
            <Gem className="h-3.5 w-3.5 text-krypt-purple" /> Coin optimizer
          </button>
          <button
            onClick={() => setShowLibrary(true)}
            className="flex items-center gap-1.5 rounded-lg border border-krypt-border bg-krypt-surface px-2.5 py-1.5 text-xs text-white hover:border-krypt-purple/50"
            title="Browse imported strategies ranked on your data"
          >
            <Library className="h-3.5 w-3.5 text-krypt-purple" /> Strategy library
          </button>
          <button onClick={onClose} className="rounded-lg p-1.5 text-krypt-muted hover:bg-white/5 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          {!masterOn && (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-krypt-warn/40 bg-krypt-warn/10 px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-krypt-warn">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                The 15m engine is OFF — no runner will trade until you turn it on.
              </div>
              <button
                onClick={() => void window.krypt?.config?.update({ crypto15mEnabled: true })}
                className="shrink-0 rounded-lg border border-krypt-warn/50 bg-krypt-warn/15 px-3 py-1.5 text-xs font-medium text-krypt-warn hover:bg-krypt-warn/25"
              >
                Turn on 15m engine
              </button>
            </div>
          )}
          {anyLiveEnabled && (
            <div className="flex items-center gap-2 rounded-lg border border-krypt-win/40 bg-krypt-win/10 px-4 py-2.5 text-sm text-krypt-win">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              At least one runner is LIVE — it can place real orders on your {config?.kalshiEnv ?? 'demo'} account.
            </div>
          )}

          {runners.length === 0 && (
            <div className="rounded-xl border border-dashed border-krypt-border bg-krypt-surface/40 px-5 py-8 text-center">
              <div className="text-sm text-white">No runners yet</div>
              <div className="mx-auto mt-1 max-w-md text-xs text-krypt-muted">
                A runner is one strategy trading a set of coins. Add several to race strategies head-to-head — each coin belongs to just one runner.
              </div>
              <div className="mt-4 flex justify-center gap-2">
                <button
                  onClick={() => addRunner({
                    name: 'From current 15m', coins: config?.crypto15mAssets ?? [...C15_ASSETS],
                    mode: config?.crypto15mLive ? 'live' : 'paper', config: {},
                  })}
                  className="rounded-lg border border-krypt-border bg-krypt-surface px-3 py-2 text-xs text-white hover:border-krypt-borderHi"
                >
                  Start from my current 15m strategy
                </button>
                <button
                  onClick={() => addRunner()}
                  className="rounded-lg bg-krypt-purple px-3 py-2 text-xs font-medium text-white hover:bg-krypt-purple/90"
                >
                  Add blank runner
                </button>
              </div>
            </div>
          )}

          {runners.map((r, idx) => {
            const taken = takenBefore(idx);
            const st = statById.get(r.id);
            const coins = r.coins ?? [];
            return (
              <div key={r.id} className={cls(
                'rounded-xl border bg-krypt-surface/50 p-4',
                r.enabled ? 'border-krypt-purple/40' : 'border-krypt-border',
              )}>
                <div className="flex flex-wrap items-center gap-3">
                  <input
                    value={r.name}
                    onChange={(e) => patch(r.id, { name: e.target.value })}
                    className="min-w-[8rem] flex-1 rounded-lg border border-krypt-border bg-krypt-void px-2.5 py-1.5 text-sm text-white outline-none focus:border-krypt-purple/60"
                  />
                  <div className="flex overflow-hidden rounded-lg border border-krypt-border text-xs">
                    {(['paper', 'live'] as const).map((m) => (
                      <button
                        key={m}
                        onClick={() => patch(r.id, { mode: m })}
                        className={cls(
                          'px-3 py-1.5 uppercase tracking-wide transition-colors',
                          r.mode === m
                            ? (m === 'live' ? 'bg-krypt-win/20 text-krypt-win' : 'bg-krypt-purple/20 text-krypt-purple')
                            : 'text-krypt-muted hover:text-white',
                        )}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                  <Switch checked={r.enabled} onChange={(v) => patch(r.id, { enabled: v })} />
                  <button onClick={() => toggleExpanded(r.id)} title="Bet size, stop-loss, take-profit…" className={cls('rounded-lg p-1.5 hover:bg-white/5 hover:text-white', expanded.has(r.id) ? 'text-krypt-purple' : 'text-krypt-muted')}><SlidersHorizontal className="h-4 w-4" /></button>
                  <button onClick={() => duplicate(r)} title="Duplicate" className="rounded-lg p-1.5 text-krypt-muted hover:bg-white/5 hover:text-white"><Copy className="h-4 w-4" /></button>
                  <button onClick={() => remove(r.id)} title="Remove" className="rounded-lg p-1.5 text-krypt-muted hover:bg-white/5 hover:text-krypt-loss"><Trash2 className="h-4 w-4" /></button>
                </div>

                {r.schedule && r.schedule.length > 0 && (
                  <div className="mt-2 rounded-lg border border-krypt-purple/25 bg-krypt-purple/[0.06] px-3 py-2">
                    <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-krypt-purple">
                      <CalendarClock className="h-3.5 w-3.5" /> Hourly schedule · {r.schedule.length} slots (UTC)
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {r.schedule.map((s, i) => (
                        <span key={i} className="rounded bg-krypt-surface2 px-1.5 py-0.5 text-[10px] text-krypt-muted" title={s.name || ''}>
                          {String(s.startHour).padStart(2, '0')}–{String(s.endHour).padStart(2, '0')}h {s.name ? `· ${s.name}` : ''}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {!r.schedule && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-krypt-muted">Strategy</span>
                  <select
                    value={r.profileId ?? ''}
                    onChange={(e) => {
                      const pid = e.target.value;
                      const prof = c15Profiles.find((p) => p.id === pid);
                      patch(r.id, {
                        profileId: pid || undefined,
                        config: prof ? crypto15mSlice(prof.config) : {},
                        name: prof && (r.name.startsWith('Runner') || r.name === 'From current 15m') ? prof.name : r.name,
                      });
                    }}
                    className="rounded-lg border border-krypt-border bg-krypt-void px-2.5 py-1.5 text-xs text-white outline-none focus:border-krypt-purple/60"
                  >
                    <option value="">Current 15m settings</option>
                    {c15Profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                  {c15Profiles.length === 0 && (
                    <span className="text-[11px] text-krypt-dim">Save 15m profiles on the 15m Crypto tab to assign different strategies.</span>
                  )}
                </div>
                )}

                <div className="mt-3">
                  <div className="mb-1 text-xs text-krypt-muted">Coins</div>
                  <div className="flex flex-wrap gap-1.5">
                    {C15_ASSETS.map((c) => {
                      const on = coins.includes(c);
                      const locked = !on && taken.has(c);
                      return (
                        <button
                          key={c}
                          disabled={locked}
                          onClick={() => patch(r.id, {
                            coins: on ? coins.filter((x) => x !== c) : [...coins, c],
                          })}
                          title={locked ? 'Owned by an earlier runner' : undefined}
                          className={cls(
                            'rounded-md px-2 py-1 text-xs font-medium transition-colors',
                            on ? 'bg-krypt-purple/25 text-white ring-1 ring-krypt-purple/50'
                              : locked ? 'cursor-not-allowed bg-krypt-surface2/40 text-krypt-dim line-through'
                                : 'bg-krypt-surface2 text-krypt-muted hover:text-white',
                          )}
                        >
                          {c}
                        </button>
                      );
                    })}
                  </div>
                  {r.enabled && coins.length === 0 && (
                    <div className="mt-1 text-[11px] text-krypt-warn">Pick at least one coin — this runner has nothing to trade.</div>
                  )}
                </div>

                {expanded.has(r.id) && (
                  <RunnerSettings
                    config={r.config}
                    baseSizingMode={(config?.crypto15mSizingMode as string) ?? 'fixed'}
                    scheduled={!!(r.schedule && r.schedule.length)}
                    onPatch={(c) => patch(r.id, { config: c })}
                  />
                )}

                {st && st.n > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-krypt-border pt-2 text-xs">
                    <span className="text-krypt-muted">{st.openN} open</span>
                    <span className="text-krypt-muted">{st.n} trades</span>
                    <span className="text-krypt-muted">{st.wins}W / {st.losses}L</span>
                    <span className={cls('font-mono', st.pnlUsd >= 0 ? 'text-krypt-win' : 'text-krypt-loss')}>
                      {st.pnlUsd >= 0 ? '+' : ''}{fmtUsd(st.pnlUsd)}
                    </span>
                    <span className="text-krypt-dim">({r.mode})</span>
                  </div>
                )}
              </div>
            );
          })}

          {runners.length > 0 && (
            <button
              onClick={() => addRunner()}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-krypt-border py-3 text-sm text-krypt-muted hover:border-krypt-borderHi hover:text-white"
            >
              <Plus className="h-4 w-4" /> Add runner
            </button>
          )}
        </div>

        <div className="border-t border-krypt-border px-5 py-3 text-[11px] text-krypt-dim">
          Paper runners simulate fills against live quotes through the same gates as live — a zero-risk preview. The account-wide daily stop-loss / take-profit still governs every live runner together.
        </div>
      </div>
      {showLibrary && <TurbineLibrary onClose={() => setShowLibrary(false)} onAdd={addFromLibrary} />}
      {showOptimizer && (
        <CoinOptimizer
          onClose={() => setShowOptimizer(false)}
          onSaveRunner={(r) => { persist([...runners, r]); }}
        />
      )}
    </div>
  );
}

function MiniNum({ label, suffix, value, min, max, onCommit }: {
  label: string; suffix?: string; value: number; min: number; max: number;
  onCommit: (v: number) => void;
}) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  const commit = () => {
    const n = Number(v);
    if (Number.isFinite(n)) onCommit(Math.max(min, Math.min(max, n)));
    else setV(String(value));
  };
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-krypt-dim">{label}</span>
      <span className="flex items-center gap-1 rounded-md border border-krypt-border bg-krypt-void px-2 py-1">
        <input
          value={v} inputMode="decimal"
          onChange={(e) => setV(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
          className="w-full bg-transparent text-xs text-white outline-none"
        />
        {suffix && <span className="shrink-0 text-[10px] text-krypt-dim">{suffix}</span>}
      </span>
    </label>
  );
}

function MiniSel({ label, value, opts, onChange }: {
  label: string; value: string; opts: [string, string][]; onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-krypt-dim">{label}</span>
      <select
        value={value} onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-krypt-border bg-krypt-void px-2 py-1 text-xs text-white outline-none"
      >
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function RunnerSettings({ config, baseSizingMode, scheduled, onPatch }: {
  config: Partial<TraderConfig>; baseSizingMode: string; scheduled: boolean;
  onPatch: (c: Partial<TraderConfig>) => void;
}) {
  const cfg = config as Record<string, unknown>;
  const g = (k: string, d: number) => (typeof cfg[k] === 'number' ? (cfg[k] as number) : d);
  const set = (k: string, v: unknown) => onPatch({ ...config, [k]: v });
  const setMany = (o: Partial<TraderConfig>) => onPatch({ ...config, ...o });
  const sizingMode = (cfg.crypto15mSizingMode as string) ?? baseSizingMode;
  return (
    <div className="mt-3 rounded-lg border border-krypt-border bg-krypt-void/40 p-3">
      <div className="mb-2 text-[11px] uppercase tracking-wide text-krypt-muted">Runner settings</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <MiniSel label="Bet size by" value={sizingMode} opts={[['fixed', 'Fixed ct'], ['balance_pct', '% balance']]} onChange={(v) => set('crypto15mSizingMode', v)} />
        {sizingMode === 'balance_pct'
          ? <MiniNum label="Per-bet" suffix="% bal" min={0} max={100} value={+(g('crypto15mBalancePct', 0.02) * 100).toFixed(2)} onCommit={(v) => setMany({ crypto15mBalancePct: v / 100, crypto15mSizingMode: 'balance_pct' })} />
          : <MiniNum label="Order size" suffix="ct" min={1} max={10000} value={g('crypto15mOrderSize', 1)} onCommit={(v) => setMany({ crypto15mOrderSize: Math.round(v), crypto15mSizingMode: 'fixed' })} />}
        <MiniNum label="Max loss/bet" suffix="% bal" min={0} max={100} value={+(g('crypto15mMaxLossPct', 0) * 100).toFixed(1)} onCommit={(v) => set('crypto15mMaxLossPct', v / 100)} />
        <MiniNum label="Stop-loss" suffix="%" min={0} max={100} value={Math.round(g('crypto15mStopLossPct', 0) * 100)} onCommit={(v) => set('crypto15mStopLossPct', Math.round(v) / 100)} />
        <MiniNum label="Take-profit" suffix="¢" min={0} max={99} value={g('crypto15mTakeProfitCents', 0)} onCommit={(v) => set('crypto15mTakeProfitCents', Math.round(v))} />
        <MiniNum label="Max concurrent" min={1} max={50} value={g('crypto15mMaxConcurrent', 3)} onCommit={(v) => set('crypto15mMaxConcurrent', Math.round(v))} />
        {!scheduled && (
          <MiniSel label="Entry style" value={(cfg.crypto15mEntryStyle as string) ?? 'maker'} opts={[['maker', 'Maker'], ['taker', 'Taker']]} onChange={(v) => set('crypto15mEntryStyle', v)} />
        )}
      </div>
      <div className="mt-2 text-[10px] text-krypt-dim">
        {scheduled
          ? 'Applied on top of the hourly schedule (which sets the strategy per hour). 0 = off / inherit base.'
          : '0 = off / inherit the base 15m config. Stop-loss / take-profit act only on live, held positions.'}
      </div>
    </div>
  );
}
