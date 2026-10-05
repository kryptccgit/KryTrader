import { useState } from 'react';
import {
  Check, ChevronRight, Dices, Download, FolderOpen, Pencil, Save, Sparkles, Trash2,
} from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { ConfirmDialog, Empty, NameDialog, Page } from '../components/common';
import { cls, fmtDateTime, fmtPct, fmtUsd } from '../utils/format';
import type { Profile, StrategyPreset } from '@shared/types';

function rankScore(b?: StrategyPreset['backtest'] | null): number {
  if (!b) return -Infinity;
  if (b.t <= 0) return b.netCents - Math.abs(b.netCents);
  return b.netCents - Math.abs(b.netCents) / b.t;
}

export function StrategiesPage() {
  const { strategies, state, refresh } = useApp();
  const toast = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [secretOpen, setSecretOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Profile | null>(null);

  const apply = async (s: StrategyPreset): Promise<void> => {
    if (s.comingSoon) return;
    setBusyId(s.id);
    try {
      await window.krypt.config.applyStrategy(s.id);
      await refresh.state();
      toast.success(`Applied "${s.name}"`);
    } catch (e: any) {
      toast.error(`Could not apply: ${e?.message || e}`);
    } finally {
      setBusyId(null);
    }
  };

  const saveCurrent = async (name: string): Promise<void> => {
    setSaveOpen(false);
    const r = await window.krypt.profiles.save(name);
    if (r.ok) {
      toast.success(r.message || `Saved "${name}"`);
      await refresh.state();
    } else toast.error(r.message || 'Could not save strategy');
  };

  const applyProfile = async (p: Profile): Promise<void> => {
    setBusyId(p.id);
    try {
      const r = await window.krypt.profiles.apply(p.id);
      if (r.ok) {
        toast.success(r.message || `Applied "${p.name}"`);
        await refresh.state();
      } else toast.error(r.message || 'Failed');
    } finally {
      setBusyId(null);
    }
  };

  const renameProfile = async (name: string): Promise<void> => {
    const target = renameTarget;
    setRenameTarget(null);
    if (!target || name === target.name) return;
    const r = await window.krypt.profiles.rename(target.id, name);
    if (r.ok) {
      toast.success('Renamed');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const deleteProfile = async (p: Profile): Promise<void> => {
    if (!window.confirm(`Delete your strategy "${p.name}"?`)) return;
    const r = await window.krypt.profiles.delete(p.id);
    if (r.ok) {
      toast.success('Deleted');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const updateProfile = async (p: Profile): Promise<void> => {
    const r = await window.krypt.profiles.update(p.id);
    if (r.ok) {
      toast.success(`Updated "${p.name}" to your current settings`);
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const shareProfile = async (p: Profile): Promise<void> => {
    const r = await window.krypt.profiles.export(p.id);
    if (!r.ok || !r.data) {
      toast.error(r.message || 'Export failed');
      return;
    }
    const blob = new Blob([r.data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${p.name.replace(/[^a-z0-9-_]+/gi, '_')}.kryptprofile.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast.success(`Exported "${p.name}" — share the .json file`);
  };

  const activeId = state?.activeProfileId ?? null;
  const profiles = state?.customProfiles ?? [];
  const secret = strategies.find((s) => s.secret) ?? null;

  const ranked = [...strategies]
    .filter((s) => !s.secret)
    .sort((a, b) => rankScore(b.backtest) - rankScore(a.backtest));

  return (
    <Page
      title="Strategies"
      subtitle="Ranked by a risk-adjusted backtest on the author's historical signal sample — fixed reference numbers shipped with the app, not computed from your own data. These are experimental heuristics — none has a proven forward edge, so test the top pick on the Demo environment first. Apply one, tweak in Settings, then save it below as your own strategy."
      actions={
        <>
          {secret && (
            <button
              onClick={() => setSecretOpen(true)}
              className={cls('krypt-btn-rainbow', activeId === secret.id && 'ring-2 ring-white/80')}
              title="A pure-gambling, just-for-fun strategy"
            >
              <Dices className="h-4 w-4" />
              {activeId === secret.id ? 'Secret Strategy: ON' : 'Secret Strategy'}
            </button>
          )}
          <button onClick={() => setSaveOpen(true)} className="krypt-btn-primary">
            <Save className="h-4 w-4" /> Save current as strategy
          </button>
        </>
      }
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {ranked.map((s, i) => {
          const active = activeId === s.id;
          const comingSoon = !!s.comingSoon;
          const rank = s.backtest ? i + 1 : null;
          return (
            <div
              key={s.id}
              className={cls(
                'group relative flex flex-col overflow-hidden rounded-xl border bg-krypt-surface p-5 transition-colors',
                comingSoon
                  ? 'border-krypt-border opacity-60'
                  : active
                    ? 'border-krypt-purple shadow-krypt-soft'
                    : 'border-krypt-border hover:border-krypt-borderHi',
              )}
            >
              {s.badge && (
                <span className={cls(
                  'absolute right-3 top-3 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider',
                  s.badge === 'recommended' && 'bg-krypt-glow text-white shadow-krypt-soft',
                  s.badge === 'new' && 'border border-krypt-pink/40 bg-krypt-pink/10 text-krypt-pink',
                  s.badge === 'soon' && 'border border-krypt-border bg-krypt-surface2 text-krypt-muted',
                )}>
                  {s.badge}
                </span>
              )}
              <div className="flex items-center gap-3">
                <div className={cls(
                  'grid h-9 w-9 place-items-center rounded-lg',
                  s.riskLabel === 'safe' && 'bg-krypt-win/10 text-krypt-win',
                  s.riskLabel === 'balanced' && 'bg-krypt-purple/15 text-krypt-purple',
                  s.riskLabel === 'aggressive' && 'bg-krypt-loss/10 text-krypt-loss',
                  s.riskLabel === 'experimental' && 'bg-krypt-warn/10 text-krypt-warn',
                )}>
                  <Sparkles className="h-4 w-4" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-white">{s.name}</div>
                  <div className="text-[11px] uppercase tracking-wider text-krypt-muted">
                    {s.riskLabel}
                  </div>
                </div>
              </div>

              <p className="mt-3 text-xs italic text-krypt-purple/80">{s.tagline}</p>
              <p className="mt-2 flex-1 text-xs leading-relaxed text-krypt-muted">
                {s.description}
              </p>

              {s.backtest && (
                <div className={cls(
                  'mt-3 flex items-center gap-3 rounded-lg border px-3 py-2',
                  s.backtest.netCents > 0.05
                    ? 'border-krypt-win/30 bg-krypt-win/10'
                    : s.backtest.netCents < -0.05
                      ? 'border-krypt-loss/25 bg-krypt-loss/5'
                      : 'border-krypt-border bg-krypt-surface2',
                )}>
                  <span className={cls(
                    'grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold',
                    rank === 1
                      ? 'bg-krypt-glow text-white shadow-krypt-soft'
                      : 'bg-krypt-surface2 text-krypt-muted',
                  )}>
                    {rank}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[9px] uppercase tracking-wider text-krypt-dim">
                      Backtested edge
                    </div>
                    <div className="flex items-baseline gap-2">
                      <span className={cls(
                        'font-mono text-sm font-semibold',
                        s.backtest.netCents > 0.05
                          ? 'text-krypt-win'
                          : s.backtest.netCents < -0.05
                            ? 'text-krypt-loss'
                            : 'text-krypt-muted',
                      )}>
                        {s.backtest.netCents >= 0 ? '+' : ''}{s.backtest.netCents.toFixed(1)}¢/contract
                      </span>
                      <span className="truncate text-[10px] text-krypt-dim">
                        t&nbsp;{s.backtest.t >= 0 ? '+' : ''}{s.backtest.t.toFixed(1)} · n&nbsp;{s.backtest.n}
                        {Math.abs(s.backtest.t) >= 2 && s.backtest.n >= 30 ? ' · sig' : ''}
                        {s.backtest.approx ? ' · ≈' : ''}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                <Stat label="Edge ≥" value={`${s.config.minEdgePtsWhale}pt`} />
                <Stat label="Conf ≥" value={`${s.config.minConfidenceWhale.toFixed(0)}%`} />
                <Stat label="Cap" value={fmtUsd(s.config.hardMaxPositionUsd)} />
                <Stat label="Sizing" value={`${fmtPct(s.config.minSizeFraction * 100, 0)}–${fmtPct(s.config.maxSizeFraction * 100, 0)}`} />
                <Stat label="Max open" value={`${s.config.maxOpenPositions}`} />
                <Stat label="Daily" value={`${s.config.maxDailyNewPositions}`} />
              </div>

              <button
                onClick={() => apply(s)}
                disabled={busyId === s.id || comingSoon}
                title={comingSoon ? 'This strategy is not available yet' : undefined}
                className={cls(
                  active ? 'krypt-btn-default' : 'krypt-btn-primary',
                  'mt-4 w-full',
                  comingSoon && 'cursor-not-allowed',
                )}
              >
                {comingSoon ? (
                  'Coming soon'
                ) : active ? (
                  <>
                    <Check className="h-4 w-4" /> Active
                  </>
                ) : (
                  <>
                    Apply <ChevronRight className="h-4 w-4" />
                  </>
                )}
              </button>
            </div>
          );
        })}
      </div>

      <p className="mt-5 max-w-3xl text-[11px] leading-relaxed text-krypt-dim">
        <span className="font-semibold text-krypt-muted">How the ranking works:</span>{' '}
        each preset's gates (source, confidence, category, entry-price) were
        replayed against a historical sample of the author's resolved signals
        and scored net of an estimated Kalshi fee. The chips are illustrative
        reference numbers shipped with the app — they are <strong>not</strong>{' '}
        recomputed from your own trading history. The chip shows mean net{' '}
        <span className="font-mono">¢/contract</span>, the t-stat{' '}
        <span className="font-mono">t</span> (≥&nbsp;2 ≈ a real edge, not
        noise), and sample size <span className="font-mono">n</span>. Cards are
        ordered by the <em>best risk-adjusted in-sample result</em> — a
        risk-adjusted edge (net minus one standard error), <strong>not</strong>{' '}
        the biggest raw number — so a steadier edge can outrank a larger but
        noisier one (Edge Stack ranks above Sports Momentum even though Sports
        has a higher ¢, because its smaller n / lower t make it less reliable).{' '}
        <span className="font-mono">≈</span> marks presets whose edge-point gate
        can't be replayed, so their number ignores it. All figures are{' '}
        <em>in-sample</em> on a small, fixed history — run the top pick on the{' '}
        <span className="font-semibold">Demo</span> environment (Settings) before
        risking real money.
      </p>

      <div className="mt-9 mb-4 flex items-baseline justify-between gap-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-krypt-muted">
          Your Strategies
        </h3>
        <p className="text-xs text-krypt-dim">
          Snapshots of your own settings. Tweak in Settings, then “Save current as strategy”.
        </p>
      </div>

      {profiles.length === 0 ? (
        <Empty
          title="No saved strategies yet"
          description="Apply a preset above or tune the knobs in Settings, then save the current config here to switch back to it anytime."
          action={
            <button onClick={() => setSaveOpen(true)} className="krypt-btn-primary">
              <Save className="h-4 w-4" /> Save current as strategy
            </button>
          }
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {profiles.map((p) => {
            const active = activeId === p.id;
            return (
              <div
                key={p.id}
                className={cls(
                  'rounded-xl border bg-krypt-surface p-4 transition-colors',
                  active
                    ? 'border-krypt-purple shadow-krypt-soft'
                    : 'border-krypt-border hover:border-krypt-borderHi',
                )}
              >
                <div className="flex items-start gap-3">
                  <div className={cls(
                    'grid h-10 w-10 place-items-center rounded-lg',
                    active ? 'bg-krypt-glow text-white' : 'bg-krypt-surface2 text-krypt-muted',
                  )}>
                    <FolderOpen className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-white">{p.name}</div>
                    <div className="text-xs text-krypt-muted">
                      Updated {fmtDateTime(p.updatedAt)}
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                  <Stat label="env" value={p.config.kalshiEnv} />
                  <Stat label="cap" value={fmtUsd(p.config.hardMaxPositionUsd)} />
                  <Stat label="open" value={`${p.config.maxOpenPositions}`} />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  {active ? (
                    <span className="krypt-pill border-krypt-purple/40 bg-krypt-purple/10 text-krypt-purple">
                      <Check className="h-3 w-3" /> Active
                    </span>
                  ) : (
                    <button
                      onClick={() => applyProfile(p)}
                      disabled={busyId === p.id}
                      className="krypt-btn-primary text-xs"
                    >
                      Apply
                    </button>
                  )}
                  <button onClick={() => setRenameTarget(p)} className="krypt-btn-ghost text-xs">
                    <Pencil className="h-3.5 w-3.5" /> Rename
                  </button>
                  <button
                    onClick={() => void updateProfile(p)}
                    className="krypt-btn-ghost text-xs"
                    title="Overwrite this strategy with your current settings"
                  >
                    <Save className="h-3.5 w-3.5" /> Update
                  </button>
                  <button
                    onClick={() => void shareProfile(p)}
                    className="krypt-btn-ghost text-xs"
                    title="Export to a .json file you can share or import elsewhere"
                  >
                    <Download className="h-3.5 w-3.5" /> Share
                  </button>
                  <button
                    onClick={() => deleteProfile(p)}
                    className="krypt-btn-ghost text-xs text-krypt-loss/80 hover:text-krypt-loss"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Delete
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {secret && (
        <ConfirmDialog
          open={secretOpen}
          danger
          title="🎰 Apply the Secret Strategy?"
          confirmLabel="I understand — gamble"
          cancelLabel="Nope"
          body={
            <>
              This is <span className="font-semibold text-white">not a real strategy</span> — it's pure gambling for
              fun. It <span className="font-semibold text-white">ignores every safety gate</span> (confidence, edge,
              category, price) and gives each fresh whale or momentum signal a flat{' '}
              <span className="font-semibold text-white">10% random chance to trade</span>. On a live account that
              risks real money on coin-flips. The Visualizer turns into a roulette wheel while it's on — switch to any
              other strategy to turn it off.
            </>
          }
          onConfirm={() => { setSecretOpen(false); void apply(secret); }}
          onClose={() => setSecretOpen(false)}
        />
      )}
      <NameDialog
        open={saveOpen}
        title="Save current settings as a strategy"
        label="Give this snapshot of your settings a name."
        placeholder="e.g. My small-balance sports config"
        confirmLabel="Save"
        onSubmit={(name) => void saveCurrent(name)}
        onClose={() => setSaveOpen(false)}
      />
      <NameDialog
        open={renameTarget !== null}
        title="Rename strategy"
        initialValue={renameTarget?.name ?? ''}
        confirmLabel="Rename"
        onSubmit={(name) => void renameProfile(name)}
        onClose={() => setRenameTarget(null)}
      />
    </Page>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1">
      <div className="text-[9px] uppercase tracking-wider text-krypt-dim">{label}</div>
      <div className="font-mono text-[11px] text-white">{value}</div>
    </div>
  );
}
