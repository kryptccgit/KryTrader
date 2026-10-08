import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Bitcoin, FolderPlus, RefreshCw, RotateCcw, SlidersHorizontal, Wallet, Zap } from 'lucide-react';
import type {
  Crypto15mAsset, Crypto15mPosition,
  Crypto15mSizing, Crypto15mSnapshot, Crypto15mStatus, RuleCondition, TraderConfig,
} from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Empty, NameDialog, Page, Switch, useOptimisticValue } from '../components/common';
import { TickerLink } from '../components/KalshiTicker';
import { BacktestPanel } from '../components/BacktestPanel';
import { ShardBalances } from '../components/terminal/ShardBalances';
import { cls, fmtUsd } from '../utils/format';
import { c15WaitingLiveRunners } from '../utils/c15Live';
import { userMessage } from '../utils/errors';

const POLL_MS = 4000;

function fmtSpot(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const dp = v >= 100 ? 2 : v >= 1 ? 4 : 6;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: dp })}`;
}

function fmtDelta(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const dp = v >= 100 ? 2 : v >= 1 ? 3 : 5;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: dp })}`;
}

function fmtMins(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${v.toFixed(1)}m`;
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${Math.round(v * 100)}%`;
}

export function Crypto15mPage() {
  const { config } = useApp();
  const [snap, setSnap] = useState<Crypto15mSnapshot | null>(null);
  const [status, setStatus] = useState<Crypto15mStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  async function load() {
    const api = window.krypt?.crypto15m;
    if (!api) {
      setErr('15m crypto API unavailable (restart the app after this update).');
      setLoading(false);
      return;
    }
    try {
      const [s, st] = await Promise.all([api.snapshot(), api.status()]);
      setSnap(s);
      setStatus(st);
      setErr(null);
    } catch (e: any) {
      setErr(userMessage(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    timer.current = window.setInterval(() => void load(), POLL_MS) as unknown as number;
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  async function patchAndReload(patch: Partial<TraderConfig>) {
    setBusy(true);
    try {
      await window.krypt.config.update(patch);
      await load();
    } catch (e: any) {
      setErr(userMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const toggleEnabled = (next: boolean) => patchAndReload({ crypto15mEnabled: next });

  const roster = config?.crypto15mRunners ?? [];
  const rosterLive = roster.filter((r) => r.enabled && r.mode === 'live');
  const waitingLive = c15WaitingLiveRunners(config);

  async function toggleLive(next: boolean) {
    const what = roster.length === 0
      ? 'The 15-minute crypto executor will place REAL orders'
      : rosterLive.length > 0
        ? `${rosterLive.length} Multi-Run runner${rosterLive.length === 1 ? '' : 's'} set to LIVE `
          + `(${rosterLive.map((r) => r.name).join(', ')}) will place REAL orders`
        : 'No Multi-Run runner is set to LIVE yet, but any you switch to LIVE will place REAL orders';
    if (next && !window.confirm(
      `Arm 15m LIVE? ${what} with your Kalshi balance — independently of the main bot's `
      + 'Start Trading switch.'
      + (config?.accountMode === 'live' ? '' : ' (The app is in Paper now: nothing is real until you Go live in Settings → Account.)'),
    )) return;
    await patchAndReload({ crypto15mLive: next });
  }

  const live = snap?.assets.filter((a) => a.signal).length ?? 0;
  const enabled = !!config?.crypto15mEnabled;
  const liveArmed = !!config?.crypto15mLive;
  const isLive = !!status?.live;
  const authed = !!status?.authed;
  const liveSupported = status?.liveSupported ?? true;
  const paperRunning = (status?.runners ?? []).some((r) => r.enabled && r.mode === 'paper');
  const mode: Mode = !enabled ? 'OFF' : isLive ? 'LIVE' : paperRunning ? 'PAPER' : 'MONITOR';
  const openPos = status?.open ?? [];
  const recentPos = (status?.recent ?? []).filter((p) => p.resolved);
  const runnerNames: Record<string, string> = {};
  for (const r of status?.runners ?? []) runnerNames[r.id] = r.name;
  const hasRunners = (status?.runners ?? []).some((r) => r.id !== '');

  return (
    <Page
      title="15m Crypto"
      subtitle="Kalshi 15-minute crypto markets. Settlement Sniper is the evidence-backed preset (it buys what the live settlement feed says is near-certain while the quote lags); everything else is experimental. Validate any change on the Backtest page before arming, and start small — one bad tail erases many small wins."
      actions={
        <button
          onClick={() => void load()}
          className="inline-flex items-center gap-2 rounded-md border border-krypt-border bg-krypt-surface2 px-3 py-1.5 text-xs text-krypt-muted transition-colors hover:border-krypt-purple/40 hover:text-white"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      }
    >
      <div className="mb-4 rounded-xl border border-krypt-border bg-krypt-surface p-3">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <div className="min-w-[260px] flex-1">
            <Switch
              checked={enabled}
              disabled={busy}
              onChange={(v) => void toggleEnabled(v)}
              label="Enable 15-minute crypto executor"
              description={
                mode === 'LIVE'
                  ? (hasRunners
                    ? `LIVE — ${status?.liveRunners ?? 0} runner${(status?.liveRunners ?? 0) === 1 ? '' : 's'} placing real orders on your Kalshi account.`
                    : 'LIVE — placing real orders on your Kalshi account.')
                  : mode === 'PAPER'
                    ? 'Paper — Multi-Run paper runners simulate fills; no real orders.'
                    : mode === 'MONITOR'
                      ? 'Monitor only — tracking signals but not placing orders.'
                      : 'Off — monitor only.'
              }
            />
          </div>
          {enabled && (
            <div className="min-w-[220px]">
              <Switch
                checked={liveArmed}
                disabled={busy}
                onChange={(v) => void toggleLive(v)}
                label="Real orders (LIVE)"
                description={roster.length > 0
                  ? 'Master switch for Multi-Run: a runner set to LIVE places real orders only while this is on. Off stops them all.'
                  : "Runs on its own — the main bot's Start Trading switch is not required."}
              />
            </div>
          )}
          <ModePill mode={mode} />
          <div className="flex items-center gap-4 text-xs">
            <KV
              label="Size"
              value={status?.sizing?.mode === 'balance_pct'
                ? `${(status.sizing.balancePct * 100).toFixed(1)}% bal`
                  + (status.sizing.balanceUsd > 0 ? ` (~${status.sizing.estContracts}c)` : '')
                : `${status?.orderSize ?? 1}c`}
            />
            <KV label="Max open" value={`${status?.maxConcurrent ?? 3}`} />
            <KV label="Open" value={`${status?.stats.openCount ?? 0}`} />
            <KV label="W / L" value={`${status?.stats.wins ?? 0} / ${status?.stats.losses ?? 0}`} />
            <KV
              label="P&L (net)"
              value={fmtUsd(status?.stats.realizedPnlUsd ?? 0, { sign: true })}
              accent={(status?.stats.realizedPnlUsd ?? 0) >= 0 ? 'good' : 'bad'}
            />
          </div>
        </div>
        {enabled && (status?.shardFunding?.shards.length ?? 0) > 1 && (
          <ShardBalances
            className="mt-2"
            shards={status!.shardFunding!.shards}
            transferUrl={status!.shardFunding!.transferUrl}
            onDone={() => void load()}
          />
        )}

        {enabled && status?.shardFunding?.starved && (
          <div className="mt-2 flex items-start gap-2 rounded-lg border border-krypt-loss/40 bg-krypt-loss/[0.07] px-3 py-2 text-[11px] leading-relaxed text-krypt-loss">
            <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
            <div>
              <div>
                <span className="font-medium">
                  No collateral on the {status.shardFunding.name} exchange.
                </span>{' '}
                Kalshi holds your cash per exchange, and the 15-minute crypto
                markets settle on {status.shardFunding.name} — so entries are
                rejected there even though your total balance looks fine.
              </div>
              <div className="mt-1 font-mono text-[10px] text-krypt-loss/80">
                {status.shardFunding.shards.map((sh) => (
                  <span key={sh.index} className="mr-3">
                    {sh.name} ${sh.cashUsd.toFixed(2)}
                  </span>
                ))}
              </div>
              <div className="mt-1 text-krypt-loss/90">
                Move at least{' '}
                <span className="font-medium">
                  ${status.shardFunding.perEntryMaxUsd.toFixed(2)}
                </span>{' '}
                for one entry, or{' '}
                <span className="font-medium">
                  ${status.shardFunding.allOpenMaxUsd.toFixed(2)}
                </span>{' '}
                to run all {status.maxConcurrent} at once. (A contract costs at
                most 99c, so these are ceilings, not estimates.)
              </div>
            </div>
          </div>
        )}
        {enabled && status?.modelCalibration && !status.modelCalibration.ok && (
          <div className="mt-2 text-[11px] text-krypt-loss">
            ⛔ Model calibration degraded — high-confidence predictions hit{' '}
            {Math.round((status.modelCalibration.rate ?? 0) * 100)}% over the last {status.modelCalibration.n} windows,
            and the statistical floor on that record ({Math.round((status.modelCalibration.lb ?? 0) * 100)}%)
            is below the bar the sniper needs to stay armed. Entries are auto-paused and resume as
            newer windows restore calibration.
          </div>
        )}
        {enabled && (status?.byStrategy?.length ?? 0) > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {status!.byStrategy!.map((st) => (
              <span key={st.strategy} className="rounded bg-krypt-surface2 px-1.5 py-0.5 font-mono text-[10px] text-krypt-dim" title={`fees $${st.fees_usd.toFixed(2)}`}>
                {st.strategy} {st.wins}/{st.n}{' '}
                <span className={st.pnl_usd >= 0 ? 'text-krypt-win' : 'text-krypt-loss'}>
                  {st.pnl_usd >= 0 ? '+' : ''}${st.pnl_usd.toFixed(2)}
                </span>
              </span>
            ))}
          </div>
        )}
        {enabled && status?.takeProfitHalted && (
          <div className="mt-2 text-[11px] text-krypt-win">
            🎯 Session take-profit reached ({fmtUsd(status.sessionPnlUsd, { sign: true })} ≥ {fmtUsd(status.sessionTakeProfitUsd)}).
            Not opening new 15-minute bets; open positions are still managed.
            Restart the app or raise “Stop at profit” to resume.
          </div>
        )}
        {enabled && !liveSupported && (
          <div className="mt-2 text-[11px] text-krypt-warn">
            The app is in <span className="text-krypt-muted">Paper</span>: every runner trades the paper
            simulation on the real 15-minute markets, whatever its own mode. Go live in
            Settings → Account to trade them for real.
          </div>
        )}
        {enabled && liveSupported && liveArmed && !authed && (
          <div className="mt-2 text-[11px] text-krypt-warn">
            Live is armed but Kalshi isn't connected — not trading until you connect your account in
            <span className="text-krypt-muted"> Settings → Credentials</span>.
          </div>
        )}
        {enabled && liveSupported && !liveArmed && waitingLive.length > 0 && (
          <div className="mt-2 text-[11px] text-krypt-warn">
            {waitingLive.length} Multi-Run runner{waitingLive.length === 1 ? ' is' : 's are'} set to LIVE
            ({waitingLive.map((r) => r.name).join(', ')}) but place nothing — not even paper — until you flip
            <span className="text-krypt-muted"> Real orders (LIVE)</span>.
          </div>
        )}
        {enabled && liveSupported && !liveArmed && waitingLive.length === 0 && (
          <div className="mt-2 text-[11px] text-krypt-dim">
            {roster.length > 0 ? 'No real orders.' : 'Monitor only.'} Flip{' '}
            <span className="text-krypt-muted">Real orders (LIVE)</span> to trade your Kalshi
            balance{roster.length > 0 ? ' with runners set to LIVE.' : ' — no other settings needed.'}
          </div>
        )}
        {enabled && liveSupported && liveArmed && authed && roster.length > 0 && rosterLive.length === 0 && (
          <div className="mt-2 text-[11px] text-krypt-dim">
            Real orders are armed, but no enabled Multi-Run runner is set to LIVE — nothing is placing real orders.
          </div>
        )}
      </div>

      <StrategySettings
        config={config}
        liveSignals={live}
        spotSource={snap?.spotSource ?? 'cryptocompare'}
        spotOk={snap?.spotOk ?? true}
        hoursOk={snap?.hoursOk ?? true}
        sizing={status?.sizing ?? null}
      />

      {err && (
        <div className="mb-4 rounded-lg border border-krypt-loss/40 bg-krypt-loss/10 px-3 py-2 text-xs text-krypt-loss">
          {err}
        </div>
      )}

      <AssetTradeToggles config={config} busy={busy} onPatch={patchAndReload} />
      <HourTradeToggles config={config} busy={busy} onPatch={patchAndReload} />

      {!snap && loading ? (
        <Empty title="Loading 15-minute crypto markets…" description="Fetching Kalshi markets and spot prices." />
      ) : snap && snap.assets.length === 0 ? (
        <Empty title="No data" description="Could not load any 15-minute crypto series." />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {snap?.assets.map((a) => <AssetCard key={a.series} a={a} />)}
        </div>
      )}

      {(openPos.length > 0 || recentPos.length > 0) && (
        <div className="mt-6 space-y-4">
          {openPos.length > 0 && <PositionsTable title="Open positions" rows={openPos} runnerNames={runnerNames} showRunner={hasRunners} />}
          {recentPos.length > 0 && <PositionsTable title="Recent (resolved)" rows={recentPos.slice(0, 20)} runnerNames={runnerNames} showRunner={hasRunners} />}
        </div>
      )}
    </Page>
  );
}

const C15_ALL_ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'HYPE', 'BNB'];

function AssetTradeToggles({
  config, busy, onPatch,
}: {
  config?: TraderConfig | null;
  busy: boolean;
  onPatch: (p: Partial<TraderConfig>) => Promise<void> | void;
}) {
  const [local, apply] = useOptimisticValue<string[] | null>(
    config?.crypto15mAssets ?? null,
    (next) => onPatch({ crypto15mAssets: next ?? [] }),
  );
  const enabled = local ?? C15_ALL_ASSETS;
  const toggle = (s: string): void => {
    const cur = local ?? [...C15_ALL_ASSETS];
    const next = cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s];
    apply(next);
  };
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5 rounded-xl border border-krypt-border bg-krypt-surface p-3">
      <span className="mr-1 text-[11px] uppercase tracking-wider text-krypt-dim">Trade</span>
      {C15_ALL_ASSETS.map((s) => (
        <button
          key={s}
          disabled={busy}
          onClick={() => toggle(s)}
          className={cls(
            'rounded-md border px-2.5 py-1 text-[11px] font-semibold transition-colors',
            enabled.includes(s)
              ? 'border-krypt-win/40 bg-krypt-win/10 text-white'
              : 'border-krypt-border bg-krypt-surface2 text-krypt-dim line-through',
          )}
          title={enabled.includes(s) ? `Trading ${s} — click to disable` : `${s} disabled — click to enable`}
        >
          {s}
        </button>
      ))}
      <span className="ml-2 text-[11px] text-krypt-dim">
        New entries only — disabled assets are still monitored and open positions keep being managed.
      </span>
    </div>
  );
}

function windowHours(start: number, end: number): number[] {
  const s = ((start % 24) + 24) % 24;
  const e = end === 24 ? 24 : ((end % 24) + 24) % 24;
  if (s === e || (s === 0 && end === 24)) return Array.from({ length: 24 }, (_, i) => i);
  const out: number[] = [];
  for (let h = 0; h < 24; h++) {
    if (s < e ? (h >= s && h < e) : (h >= s || h < e)) out.push(h);
  }
  return out;
}

function HourTradeToggles({
  config, busy, onPatch,
}: {
  config?: TraderConfig | null;
  busy: boolean;
  onPatch: (p: Partial<TraderConfig>) => Promise<void> | void;
}) {
  const start = config?.crypto15mHoursStartUtc ?? 0;
  const end = config?.crypto15mHoursEndUtc ?? 24;
  const [local, apply] = useOptimisticValue<number[] | null>(
    config?.crypto15mHours ?? null,
    (next) => onPatch({ crypto15mHours: next ?? [] }),
  );
  const on = new Set(local ?? windowHours(start, end));
  const toggle = (h: number): void => {
    const base = local ?? windowHours(start, end);
    const next = base.includes(h) ? base.filter((x) => x !== h) : [...base, h].sort((a, b) => a - b);
    apply(next);
  };
  const allHours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <div className="mb-3 rounded-xl border border-krypt-border bg-krypt-surface p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-wider text-krypt-dim">Trade hours (UTC)</span>
        <span className="text-[11px] text-krypt-dim">{on.size}/24 on</span>
        <button
          disabled={busy}
          onClick={() => apply(allHours)}
          className="rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-0.5 text-[10px] text-krypt-dim transition-colors hover:text-white"
        >
          all
        </button>
        <button
          disabled={busy}
          onClick={() => apply([])}
          className="rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-0.5 text-[10px] text-krypt-dim transition-colors hover:text-white"
        >
          none
        </button>
        <span className="ml-auto text-[11px] text-krypt-dim">green = enter new trades this hour · open positions keep being managed</span>
      </div>
      <div className="grid grid-cols-12 gap-1">
        {Array.from({ length: 24 }, (_, h) => (
          <button
            key={h}
            disabled={busy}
            onClick={() => toggle(h)}
            title={`${String(h).padStart(2, '0')}:00 UTC — ${on.has(h) ? 'trading, click to disable' : 'disabled, click to enable'}`}
            className={cls(
              'rounded border py-1 text-[10px] font-semibold tabular-nums transition-colors',
              on.has(h)
                ? 'border-krypt-win/40 bg-krypt-win/10 text-white'
                : 'border-krypt-border bg-krypt-surface2 text-krypt-dim line-through',
            )}
          >
            {String(h).padStart(2, '0')}
          </button>
        ))}
      </div>
    </div>
  );
}

type Mode = 'OFF' | 'MONITOR' | 'PAPER' | 'LIVE';

function ModePill({ mode }: { mode: Mode }) {
  const sty =
    mode === 'LIVE'
      ? 'border-krypt-loss/50 bg-krypt-loss/15 text-krypt-loss'
      : mode === 'PAPER'
        ? 'border-krypt-purple/50 bg-krypt-purple/15 text-krypt-purple'
      : mode === 'MONITOR'
        ? 'border-krypt-warn/50 bg-krypt-warn/15 text-krypt-warn'
        : 'border-krypt-border bg-krypt-surface2 text-krypt-muted';
  return (
    <span className={cls('rounded-full border px-3 py-1 text-[11px] font-bold uppercase tracking-wider', sty)}>
      {mode}
    </span>
  );
}

function KV({ label, value, accent }: { label: string; value: string; accent?: 'good' | 'bad' }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-krypt-dim">
      {label}
      <span className={cls('font-mono', accent === 'good' ? 'text-krypt-win' : accent === 'bad' ? 'text-krypt-loss' : 'text-white')}>
        {value}
      </span>
    </span>
  );
}


const C15_DEFAULTS = {
  directionMode: 'favorite' as 'favorite' | 'contrarian',
  timeDelayMin: 8,
  entryThreshold: 0.70,
  entryMax: 0.98,
  exitThreshold: 0.4,
  stopSlippageCents: 0,
  takeProfitCents: 0,
  stopLossPct: 0,
  sessionTakeProfitUsd: 0,
  minRsi: 0,
  minMacdHist: 0,
  minDeltaPct: 0,
  entryDiff: 0.02,
  entryStyle: 'maker' as 'maker' | 'taker',
  makerCancelMin: 1,
  hoursStartUtc: 0,
  hoursEndUtc: 24,
  orderSize: 1,
  maxConcurrent: 3,
};

const C15_PRESETS: { id: string; name: string; hint: string; patch: Partial<TraderConfig> }[] = [
  {
    id: 'sniper', name: '★ Settlement Sniper',
    hint: 'The one mechanism that survived this app\'s 19,819-window historical replay: enter ONLY inside the final 60s, when ≥30 of the 60 settlement prints are already in, the model is ~3σ certain, and the quote still leaves ≥2¢ net of fees. Rare entries by design (a few per day across coins). Tail losses are real — paper-trade first, size small.',
    patch: {
      crypto15mDirectionalEnabled: true, crypto15mPairsEnabled: false, crypto15mUseRules: false,
      crypto15mDirectionMode: 'model',
      crypto15mModelMinProb: 0.99, crypto15mModelMinEdgeCents: 2,
      crypto15mModelFinalMinute: true, crypto15mModelMidwindow: false,
      crypto15mEntryStyle: 'taker',
      crypto15mExitThreshold: 0.4,
      crypto15mIndicatorDetect: true, crypto15mSpotWs: true,
    },
  },
  {
    id: 'favorite', name: 'Deep Favorite',
    hint: 'Only the deepest favorites (95–98¢) — the one band that didn\'t lose in collected data (small sample).',
    patch: { crypto15mDirectionalEnabled: true, crypto15mPairsEnabled: false, crypto15mDirectionMode: 'favorite', crypto15mEntryThreshold: 0.95, crypto15mEntryMax: 0.98, crypto15mMinDeltaPct: 0, crypto15mExitThreshold: 0.4, crypto15mEntryStyle: 'maker', crypto15mUseRules: false },
  },
  {
    id: 'contrarian', name: 'Contrarian Fade',
    hint: 'Fade extreme favorites — buy the cheap side, hold to settle. Measured ≈ break-even.',
    patch: { crypto15mDirectionalEnabled: true, crypto15mPairsEnabled: false, crypto15mDirectionMode: 'contrarian', crypto15mEntryThreshold: 0.9, crypto15mEntryMax: 0.98, crypto15mMinDeltaPct: 0, crypto15mExitThreshold: 0, crypto15mEntryStyle: 'maker', crypto15mUseRules: false },
  },
  {
    id: 'momentum', name: 'Momentum (Δ-confirmed)',
    hint: 'Buy the favorite only once the underlying has already moved ≥0.2% this window — a momentum filter on the 15-min open.',
    patch: { crypto15mDirectionalEnabled: true, crypto15mPairsEnabled: false, crypto15mDirectionMode: 'favorite', crypto15mEntryThreshold: 0.80, crypto15mEntryMax: 0.98, crypto15mMinDeltaPct: 0.002, crypto15mExitThreshold: 0.4, crypto15mEntryStyle: 'maker', crypto15mUseRules: false },
  },
  {
    id: 'fav-90-95', name: 'Favorite 90–95¢',
    hint: 'Favorites in the 90–95¢ pocket. Caveat: priced off the mid — unconfirmed on real fills near close.',
    patch: { crypto15mDirectionalEnabled: true, crypto15mPairsEnabled: false, crypto15mDirectionMode: 'favorite', crypto15mEntryThreshold: 0.90, crypto15mEntryMax: 0.95, crypto15mMinDeltaPct: 0, crypto15mExitThreshold: 0.4, crypto15mEntryStyle: 'maker', crypto15mUseRules: false },
  },
  {
    id: 'macd-trend', name: 'MACD Trend (rules)',
    hint: 'Experimental: enter Up when Up is favored and the 1-min underlying MACD is bullish, in the last 6 min. Uses the rule builder + MACD field — recorded, not yet backtested.',
    patch: {
      crypto15mDirectionalEnabled: true, crypto15mPairsEnabled: false,
      crypto15mDirectionMode: 'favorite', crypto15mEntryStyle: 'maker', crypto15mExitThreshold: 0.4,
      crypto15mMinDeltaPct: 0, crypto15mIndicatorDetect: true, crypto15mUseRules: true,
      crypto15mRules: [
        { field: 'upProb', op: '>=', value: 0.55 },
        { field: 'macdHist', op: '>', value: 0 },
        { field: 'minsLeft', op: '<=', value: 6 },
      ],
    },
  },
];

const C15_RULE_FIELDS: { v: string; label: string }[] = [
  { v: 'favoritePrice', label: 'Favorite price (0–1)' },
  { v: 'entryCost', label: 'Entry cost (0–1)' },
  { v: 'upProb', label: 'Up probability (0–1)' },
  { v: 'downProb', label: 'Down probability (0–1)' },
  { v: 'deltaPct', label: 'Underlying Δ (fraction)' },
  { v: 'deltaSignedPct', label: 'Underlying Δ signed (+ = above strike)' },
  { v: 'minsLeft', label: 'Minutes left' },
  { v: 'hourUtc', label: 'Hour (UTC 0–23)' },
  { v: 'peersAgree', label: 'Peers agree (0–1)' },
  { v: 'marketBias', label: 'Market bias (−1..1)' },
  { v: 'settlePrints', label: 'Settlement prints in (0-60)' },
  { v: 'upAsk', label: 'UP ask ($)' },
  { v: 'downAsk', label: 'DOWN ask ($)' },
  { v: 'macd', label: 'MACD line' },
  { v: 'macdSignal', label: 'MACD signal' },
  { v: 'macdHist', label: 'MACD histogram' },
  { v: 'macdCross', label: 'MACD cross (+1/0/−1)' },
  { v: 'rsi', label: 'RSI (0–100)' },
  { v: 'sigma1m', label: '1-min volatility (fraction)' },
  { v: 'modelProb', label: 'Model P(up) (0–1)' },
  { v: 'edgeNetCents', label: 'Model edge net of fees (¢)' },
];
const C15_RULE_OPS = ['>=', '<=', '>', '<'] as const;

function StrategySettings({
  config, liveSignals, spotSource, spotOk, hoursOk, sizing,
}: {
  config: TraderConfig | null;
  liveSignals: number;
  spotSource: string;
  spotOk: boolean;
  hoursOk: boolean;
  sizing: Crypto15mSizing | null;
}) {
  const sizingMode = config?.crypto15mSizingMode ?? 'fixed';
  const [savingPreset, setSavingPreset] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const toast = useToast();
  const update = async (patch: Partial<TraderConfig>) => {
    try { await window.krypt.config.update(patch); } catch {   }
  };
  const saveProfile = async (name: string): Promise<void> => {
    setSaveOpen(false);
    const r = await window.krypt.profiles.save(name, undefined, 'crypto15m');
    if (r.ok) toast.success(r.message || 'Saved 15m crypto profile');
    else toast.error(r.message || 'Failed to save profile');
  };
  const num = (k: keyof TraderConfig, d: number) => {
    const v = config?.[k] as number | undefined;
    return typeof v === 'number' && !Number.isNaN(v) ? v : d;
  };
  const dir = (config?.crypto15mDirectionMode ?? C15_DEFAULTS.directionMode);
  const entryStyle = (config?.crypto15mEntryStyle ?? C15_DEFAULTS.entryStyle);
  const dimCls = '';
  const dimTitle = undefined;

  const applyPreset = async (p: typeof C15_PRESETS[number]) => {
    setSavingPreset(p.id);
    try { await window.krypt.config.update(p.patch); } finally { setSavingPreset(null); }
  };

  const resetDefaults = () => void update({
    crypto15mDirectionMode: C15_DEFAULTS.directionMode,
    crypto15mDirectionalEnabled: true,
    crypto15mPairsEnabled: false,
    crypto15mUseRules: false,
    crypto15mTimeDelayMin: C15_DEFAULTS.timeDelayMin,
    crypto15mEntryThreshold: C15_DEFAULTS.entryThreshold,
    crypto15mEntryMax: C15_DEFAULTS.entryMax,
    crypto15mExitThreshold: C15_DEFAULTS.exitThreshold,
    crypto15mStopSlippageCents: C15_DEFAULTS.stopSlippageCents,
    crypto15mTakeProfitCents: C15_DEFAULTS.takeProfitCents,
    crypto15mStopLossPct: C15_DEFAULTS.stopLossPct,
    crypto15mSessionTakeProfitUsd: C15_DEFAULTS.sessionTakeProfitUsd,
    crypto15mMinRsi: C15_DEFAULTS.minRsi,
    crypto15mMinMacdHist: C15_DEFAULTS.minMacdHist,
    crypto15mMinDeltaPct: C15_DEFAULTS.minDeltaPct,
    crypto15mEntryDiff: C15_DEFAULTS.entryDiff,
    crypto15mEntryStyle: C15_DEFAULTS.entryStyle,
    crypto15mMakerCancelMin: C15_DEFAULTS.makerCancelMin,
    crypto15mHoursStartUtc: C15_DEFAULTS.hoursStartUtc,
    crypto15mHoursEndUtc: C15_DEFAULTS.hoursEndUtc,
  });

  return (
    <div className="mb-4 rounded-xl border border-krypt-border bg-krypt-surface p-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-krypt-muted">
          <SlidersHorizontal className="h-3.5 w-3.5" /> Strategy settings
        </span>
        <span className="text-[11px] text-krypt-dim">changes apply live</span>
        <div className="ml-auto flex items-center gap-3">
          {liveSignals > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-krypt-win/10 px-2 py-0.5 text-[11px] font-semibold text-krypt-win">
              <Zap className="h-3 w-3" /> {liveSignals} live signal{liveSignals === 1 ? '' : 's'}
            </span>
          )}
          {!hoursOk && (
            <span className="inline-flex items-center gap-1 rounded-full bg-krypt-warn/10 px-2 py-0.5 text-[11px] font-semibold text-krypt-warn">
              outside trading hours
            </span>
          )}
          <span className={cls('inline-flex items-center gap-1.5 text-[11px]', spotOk ? 'text-krypt-muted' : 'text-krypt-warn')}>
            <span className={cls('h-1.5 w-1.5 rounded-full', spotOk ? 'bg-krypt-win' : 'bg-krypt-warn')} />
            spot: {spotSource}{spotOk ? '' : ' (down)'}
          </span>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {C15_PRESETS.map((p) => (
          <button
            key={p.id}
            onClick={() => void applyPreset(p)}
            disabled={savingPreset !== null}
            title={p.hint}
            className="rounded-md border border-krypt-border bg-krypt-surface2 px-2.5 py-1 text-[11px] text-krypt-muted transition-colors hover:border-krypt-purple/40 hover:text-white disabled:opacity-50"
          >
            {p.name}
          </button>
        ))}
        <button
          onClick={() => setSaveOpen(true)}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-krypt-border bg-krypt-surface2 px-2.5 py-1 text-[11px] text-krypt-muted transition-colors hover:border-krypt-purple/40 hover:text-white"
          title="Save these 15m crypto settings as a profile"
        >
          <FolderPlus className="h-3 w-3" /> Save as profile
        </button>
        <button
          onClick={resetDefaults}
          className="inline-flex items-center gap-1 rounded-md border border-krypt-border bg-krypt-surface2 px-2.5 py-1 text-[11px] text-krypt-dim transition-colors hover:border-krypt-warn/40 hover:text-krypt-warn"
        >
          <RotateCcw className="h-3 w-3" /> Reset
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        <SelectField
          label="Direction" value={dir}
          options={[['model', 'Model — settlement sniper'], ['favorite', 'Favorite-follow'], ['contrarian', 'Contrarian fade']]}
          hint="Model buys whichever side the settlement model calls near-certain (the sniper); Favorite buys the market's favorite; Contrarian fades it."
          onCommit={(v) => void update({ crypto15mDirectionalEnabled: true, crypto15mDirectionMode: v as 'favorite' | 'contrarian' | 'model' })}
        />
        {dir === 'model' && (
          <>
            <NumField
              label="Model certainty" suffix="%" min={50} max={100} step={1}
              value={Math.round(num('crypto15mModelMinProb', 0.97) * 100)}
              hint="Only enter when the settlement model gives the bought side at least this probability. Set your own threshold and validate it on the Backtest page."
              onCommit={(v) => void update({ crypto15mModelMinProb: Math.max(50, Math.min(100, Math.round(v))) / 100 })}
            />
            <NumField
              label="Min net edge" suffix="¢" min={0} max={50} step={0.5}
              value={num('crypto15mModelMinEdgeCents', 2)}
              hint="Model probability minus the executable ask minus the taker fee must be at least this many cents — the margin you're paid for taking the trade."
              onCommit={(v) => void update({ crypto15mModelMinEdgeCents: v })}
            />
            <SelectField
              label="Calibration guard" value={(config?.crypto15mModelAutopause ?? true) ? 'on' : 'off'}
              options={[['on', 'Auto-pause (recommended)'], ['off', 'Off']]}
              hint="Watches whether the model's ≥97% predictions keep actually winning ≥~96%. If the rolling hit rate drops below break-even, sniper entries pause automatically and resume when calibration recovers."
              onCommit={(v) => void update({ crypto15mModelAutopause: v === 'on' })}
            />
            <SelectField
              label="Final-minute strikes" value={(config?.crypto15mModelFinalMinute ?? true) ? 'on' : 'off'}
              options={[['on', 'On (recommended)'], ['off', 'Off']]}
              hint="Trade inside the last 60s once ≥30 of the 60 settlement prints are locked and certainty passes 3σ — the settlement average is being realized in real time while stale quotes linger."
              onCommit={(v) => void update({ crypto15mModelFinalMinute: v === 'on' })}
            />
          </>
        )}
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Entry window" suffix="min" min={1} max={15} step={1}
          value={num('crypto15mTimeDelayMin', C15_DEFAULTS.timeDelayMin)}
          hint="Only act inside the last N minutes of the 15-min quarter."
          onCommit={(v) => void update({ crypto15mTimeDelayMin: v })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Favorite ≥" suffix="¢" min={1} max={99} step={1}
          value={Math.round(num('crypto15mEntryThreshold', C15_DEFAULTS.entryThreshold) * 100)}
          hint="The favorite side must be at least this likely to enter."
          onCommit={(v) => void update({ crypto15mEntryThreshold: v / 100 })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Skip above" suffix="¢" min={1} max={99} step={1}
          value={Math.round(num('crypto15mEntryMax', C15_DEFAULTS.entryMax) * 100)}
          hint="Don't pay more than this — too little room left to profit."
          onCommit={(v) => void update({ crypto15mEntryMax: v / 100 })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Min move Δ" suffix="%" min={0} max={50} step={0.05}
          value={+(num('crypto15mMinDeltaPct', C15_DEFAULTS.minDeltaPct) * 100).toFixed(2)}
          hint="Required underlying move from the 15-min open (CoinGecko spot). 0 = off."
          onCommit={(v) => void update({ crypto15mMinDeltaPct: v / 100 })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Min RSI" suffix="0–100" min={0} max={100} step={1}
          value={num('crypto15mMinRsi', C15_DEFAULTS.minRsi)}
          hint="Direction-aware momentum gate: an up-bet needs RSI ≥ this; a down-bet needs RSI ≤ (100 − this). Pair with a wide Entry window to enter early only on strong momentum. Needs Detect MACD/RSI (auto-enabled). 0 = off."
          onCommit={(v) => void update({ crypto15mMinRsi: Math.round(v), ...(v > 0 ? { crypto15mIndicatorDetect: true } : {}) })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Min MACD" suffix="|hist|" min={0} max={100000} step={0.5}
          value={num('crypto15mMinMacdHist', C15_DEFAULTS.minMacdHist)}
          hint="Direction-aware: an up-bet needs MACD histogram ≥ this; a down-bet needs ≤ −this. Raw price units, so the right value differs per asset (larger for BTC than DOGE — watch the MACD chip on each card). Needs Detect MACD/RSI (auto-enabled). 0 = off."
          onCommit={(v) => void update({ crypto15mMinMacdHist: v, ...(v > 0 ? { crypto15mIndicatorDetect: true } : {}) })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Stop-loss" suffix="¢" min={0} max={99} step={1}
          value={Math.round(num('crypto15mExitThreshold', C15_DEFAULTS.exitThreshold) * 100)}
          hint="Executor sells if the held side falls to this price. 0 = hold to settlement. (Pairs never stop-loss — a matched pair pays $1 at settlement.)"
          onCommit={(v) => void update({ crypto15mExitThreshold: v / 100 })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Stop slippage" suffix="¢" min={0} max={50} step={1}
          value={num('crypto15mStopSlippageCents', C15_DEFAULTS.stopSlippageCents)}
          hint="When the stop-loss sells, price this many cents BELOW the bid so it sweeps the book and fills fast in a drop instead of resting unfilled. 0 = sell at the bid."
          onCommit={(v) => void update({ crypto15mStopSlippageCents: Math.round(v) })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Take-profit" suffix="¢" min={0} max={99} step={1}
          value={num('crypto15mTakeProfitCents', C15_DEFAULTS.takeProfitCents)}
          hint="Sell a winning position once the held side reaches this price. Set it ABOVE your entry price, or it sells the instant a position fills. 0 = off (hold to settlement)."
          onCommit={(v) => void update({ crypto15mTakeProfitCents: Math.round(v) })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Stop-loss %" suffix="%" min={0} max={100} step={1}
          value={Math.round(num('crypto15mStopLossPct', C15_DEFAULTS.stopLossPct) * 100)}
          hint="Sell once a position is down this % from what it cost (e.g. 20 = exit at −20%). Works alongside the cents Stop-loss above — whichever hits first exits. 0 = off."
          onCommit={(v) => void update({ crypto15mStopLossPct: Math.max(0, Math.min(100, Math.round(v))) / 100 })}
        />
        </div>
        <NumField
          label="Stop at profit" suffix="$ / session" min={0} max={1000000} step={5}
          value={num('crypto15mSessionTakeProfitUsd', C15_DEFAULTS.sessionTakeProfitUsd)}
          hint="Once this session's realized 15m profit reaches this many dollars, stop opening new 15m bets (open positions keep being managed). Applies to Pairs too. Resets when the app restarts. 0 = off."
          onCommit={(v) => void update({ crypto15mSessionTakeProfitUsd: v })}
        />
        <div className={dimCls} title={dimTitle}>
        <SelectField
          label="Entry style" value={entryStyle}
          options={[['maker', 'Rest at bid (maker)'], ['taker', 'Cross spread (taker)']]}
          hint="Maker rests a limit at the bid: no spread paid, ~zero Kalshi fee, but it may not fill. Taker crosses the ask: always fills, pays spread + the full taker fee. (Pairs always buys marketable at the ask.)"
          onCommit={(v) => void update({ crypto15mEntryStyle: v as 'maker' | 'taker' })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        {entryStyle === 'maker' ? (
          <NumField
            label="Cancel unfilled" suffix="min left" min={0} max={15} step={0.5}
            value={num('crypto15mMakerCancelMin', C15_DEFAULTS.makerCancelMin)}
            hint="Give up on a resting entry this many minutes before the market closes. 0 = keep it until close."
            onCommit={(v) => void update({ crypto15mMakerCancelMin: v })}
          />
        ) : (
          <NumField
            label="Entry markup" suffix="¢" min={0} max={20} step={1}
            value={Math.round(num('crypto15mEntryDiff', C15_DEFAULTS.entryDiff) * 100)}
            hint="How far through the spread the limit order crosses to get filled."
            onCommit={(v) => void update({ crypto15mEntryDiff: v / 100 })}
          />
        )}
        </div>
        <div className={dimCls} title={dimTitle}>
        <SelectField
          label="Bet size by" value={sizingMode}
          options={[['fixed', 'Fixed contracts'], ['balance_pct', '% of balance']]}
          hint="Buy a fixed number of contracts, or spend a % of your balance each bet. (Pairs sizes with its own Leg size below.)"
          onCommit={(v) => void update({ crypto15mSizingMode: v as 'fixed' | 'balance_pct' })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        {sizingMode === 'balance_pct' ? (
          <NumField
            label="Per bet" suffix="% bal" min={0.1} max={100} step={0.1}
            value={+(num('crypto15mBalancePct', 0.02) * 100).toFixed(2)}
            hint="Spend this % of your balance on each entry (contracts = budget ÷ price)."
            onCommit={(v) => void update({ crypto15mBalancePct: v / 100 })}
          />
        ) : (
          <NumField
            label="Order size" suffix="ct" min={1} max={1000} step={1}
            value={num('crypto15mOrderSize', C15_DEFAULTS.orderSize)}
            hint="Contracts per entry."
            onCommit={(v) => void update({ crypto15mOrderSize: Math.round(v) })}
          />
        )}
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Max loss / bet" suffix="% bal" min={0} max={100} step={0.5}
          value={+(num('crypto15mMaxLossPct', 0) * 100).toFixed(2)}
          hint="Never risk more than this % of balance on one bet (it's bought outright, so cost = max loss). 0 = off."
          onCommit={(v) => void update({ crypto15mMaxLossPct: v / 100 })}
        />
        </div>
        <div className={dimCls} title={dimTitle}>
        <NumField
          label="Max concurrent" min={1} max={50} step={1}
          value={num('crypto15mMaxConcurrent', C15_DEFAULTS.maxConcurrent)}
          hint="Most open 15-min positions at once. The 7 assets move together — several concurrent favorites are ONE correlated crypto bet, not diversification. (Pairs has its own cap: 2 unmatched windows.)"
          onCommit={(v) => void update({ crypto15mMaxConcurrent: Math.round(v) })}
        />
        </div>
        <NumField
          label="Max total 15m" suffix="% bal" min={0} max={100} step={1}
          value={+(num('crypto15mMaxTotalPct', 0.10) * 100).toFixed(1)}
          hint="Aggregate cap: total money committed to open 15m bets can't exceed this % of your bankroll (order sizes are trimmed to fit). 0 = off."
          onCommit={(v) => void update({ crypto15mMaxTotalPct: Math.max(0, Math.min(100, v)) / 100 })}
        />
      </div>

      <SizingPreview sizing={sizing} mode={sizingMode} />
      {dir === 'contrarian' && config?.crypto15mDirectionalEnabled !== false && (
        <p className="mt-2 text-[11px] text-krypt-warn/90">
          Contrarian: when a side is an extreme favorite (≥ threshold) the executor buys the CHEAP opposite side — a low-win, high-payoff longshot. Set stop-loss to 0 to hold to settlement.
        </p>
      )}

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Switch
          checked={config?.crypto15mStrictThreshold ?? true}
          onChange={(v) => void update({ crypto15mStrictThreshold: v })}
          label="Strict entry threshold"
          description={'Hard floor: only enter when the price actually paid is at least "Favorite ≥" (and the market has both a bid and an ask). Off = the threshold checks the mid-market probability only, so thin books can fill below your number.'}
        />
        <Switch
          checked={config?.crypto15mIndicatorDetect ?? true}
          onChange={(v) => void update({ crypto15mIndicatorDetect: v })}
          label="Underlying MACD / RSI"
          description="Compute MACD & RSI on the 1-min underlying (Hyperliquid). Detection-only — surfaced per asset and usable as rule fields."
        />
        <Switch
          checked={config?.crypto15mSpotWs ?? true}
          onChange={(v) => void update({ crypto15mSpotWs: v })}
          label="Live spot feed (Coinbase)"
          description="Real-time spot prices from Coinbase — a constituent of the CF Benchmarks index Kalshi settles against — plus a final-minute settlement-average tracker that sharpens the model. Off = slower REST price polling only."
        />
      </div>

      <RuleBuilder config={config} update={update} />

      <EdgeHealthCard />

      <BacktestPanel />

      <NameDialog
        open={saveOpen}
        title="Save 15m crypto profile"
        label="Saves the current 15-minute crypto strategy as a reusable profile (separate from the main engine — find it under Profiles → 15m crypto)."
        placeholder="Profile name"
        confirmLabel="Save"
        onSubmit={(name) => void saveProfile(name)}
        onClose={() => setSaveOpen(false)}
      />
    </div>
  );
}

function RuleBuilder({
  config, update,
}: {
  config: TraderConfig | null;
  update: (patch: Partial<TraderConfig>) => void | Promise<void>;
}) {
  const useRules = !!config?.crypto15mUseRules;
  const [rules, setRules] = useOptimisticValue<RuleCondition[]>(
    config?.crypto15mRules ?? [],
    (next) => update({ crypto15mRules: next }),
  );
  const addRule = () => setRules([...rules, { field: 'rsi', op: '<', value: 30 }]);
  const removeRule = (i: number) => setRules(rules.filter((_, idx) => idx !== i));
  const patchRule = (i: number, patch: Partial<RuleCondition>) =>
    setRules(rules.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  return (
    <div className="mt-3 rounded-lg border border-krypt-border bg-krypt-surface2 p-3">
      <Switch
        checked={useRules}
        onChange={(v) => void update({ crypto15mUseRules: v })}
        label="Custom entry rules"
        description="Replace the built-in favorite/signal gate with your own conditions (ALL must pass). The entry window & trading hours still apply; the side bought still follows Direction."
      />
      {useRules && (
        <div className="mt-3 flex flex-col gap-2">
          {rules.length === 0 && (
            <div className="rounded-md border border-krypt-warn/30 bg-krypt-warn/5 px-2 py-1.5 text-[11px] text-krypt-warn">
              Rules are on but none are set — nothing will enter. Add at least one condition.
            </div>
          )}
          {rules.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <select
                value={r.field}
                onChange={(e) => patchRule(i, { field: e.target.value })}
                className="krypt-input flex-1 py-1 text-xs"
              >
                {C15_RULE_FIELDS.map((f) => <option key={f.v} value={f.v}>{f.label}</option>)}
              </select>
              <select
                value={r.op}
                onChange={(e) => patchRule(i, { op: e.target.value as RuleCondition['op'] })}
                className="krypt-input w-16 py-1 text-xs"
              >
                {C15_RULE_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
              <RuleValueInput value={r.value} onCommit={(n) => patchRule(i, { value: n })} />
              <button
                onClick={() => removeRule(i)}
                className="krypt-btn-ghost px-2 py-1 text-xs text-krypt-loss"
                title="Remove condition"
              >
                ✕
              </button>
            </div>
          ))}
          <button
            onClick={addRule}
            className="self-start rounded-md border border-krypt-border bg-krypt-surface px-2.5 py-1 text-[11px] text-krypt-muted transition-colors hover:border-krypt-purple/40 hover:text-white"
          >
            + Add condition
          </button>
          <p className="text-[10px] text-krypt-dim">
            e.g. <span className="font-mono">macdHist &gt; 0</span>, <span className="font-mono">rsi &lt; 35</span>, <span className="font-mono">favoritePrice ≥ 0.95</span>. Indicator/arb fields need their detector above turned on to populate (a missing field rejects the entry).
          </p>
        </div>
      )}
    </div>
  );
}

function RuleValueInput({ value, onCommit }: { value: number; onCommit: (n: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => { setText(String(value)); }, [value]);
  const commit = (): void => {
    const n = Number(text);
    if (text.trim() !== '' && !Number.isNaN(n) && n !== value) onCommit(n);
    else setText(String(value));
  };
  return (
    <input
      type="text"
      inputMode="decimal"
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
      className="krypt-input w-24 py-1 font-mono text-xs"
    />
  );
}

function SizingPreview({ sizing, mode }: { sizing: Crypto15mSizing | null; mode: 'fixed' | 'balance_pct' }) {
  if (!sizing) return null;
  const { estContracts, estCostUsd, estPriceCents, balanceUsd, balancePct, maxLossPct, note } = sizing;
  const known = balanceUsd > 0;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-krypt-border bg-krypt-surface2 px-3 py-2 text-[11px]">
      <span className="inline-flex items-center gap-1.5 font-semibold uppercase tracking-wider text-krypt-dim">
        <Wallet className="h-3.5 w-3.5" /> Per bet
      </span>
      <span className="font-mono text-sm text-white">≈ {fmtUsd(estCostUsd)}</span>
      <span className="text-krypt-muted">
        {estContracts} contract{estContracts === 1 ? '' : 's'} @ ~{estPriceCents}¢
      </span>
      {mode === 'balance_pct' && (
        <span className="text-krypt-dim">
          {(balancePct * 100).toFixed(1)}% of {known ? fmtUsd(balanceUsd) : 'balance'}
        </span>
      )}
      {maxLossPct > 0 && (
        <span className="text-krypt-dim">
          max risk {(maxLossPct * 100).toFixed(1)}%{known ? ` · ${fmtUsd(balanceUsd * maxLossPct)}` : ''}
        </span>
      )}
      {known && <span className="ml-auto text-krypt-dim">balance {fmtUsd(balanceUsd)}</span>}
      {note && <span className="w-full text-krypt-warn">{note}</span>}
    </div>
  );
}

function NumField({
  label, value, onCommit, suffix, min, max, step, hint,
}: {
  label: string;
  value: number;
  onCommit: (v: number) => void;
  suffix?: string;
  min: number;
  max: number;
  step: number;
  hint?: string;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => { setText(String(value)); }, [value]);

  const commit = () => {
    const parsed = Number(text);
    if (Number.isNaN(parsed)) { setText(String(value)); return; }
    const clamped = Math.min(max, Math.max(min, parsed));
    setText(String(clamped));
    if (clamped !== value) onCommit(clamped);
  };

  return (
    <label className="block rounded-lg border border-krypt-border bg-krypt-surface2 px-2.5 py-1.5" title={hint}>
      <div className="flex items-center justify-between text-[9px] uppercase tracking-wider text-krypt-dim">
        <span>{label}</span>
        {suffix && <span className="text-krypt-dim/70">{suffix}</span>}
      </div>
      <input
        type="number"
        inputMode="decimal"
        value={text}
        min={min}
        max={max}
        step={step}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
        className="mt-0.5 w-full bg-transparent font-mono text-sm text-white outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
      />
    </label>
  );
}

function SelectField({
  label, value, options, onCommit, hint,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onCommit: (v: string) => void;
  hint?: string;
}) {
  return (
    <label className="block rounded-lg border border-krypt-border bg-krypt-surface2 px-2.5 py-1.5" title={hint}>
      <div className="text-[9px] uppercase tracking-wider text-krypt-dim">{label}</div>
      <select
        value={value}
        onChange={(e) => onCommit(e.target.value)}
        className="mt-0.5 w-full cursor-pointer bg-transparent font-mono text-sm text-white outline-none"
      >
        {options.map(([v, lbl]) => (
          <option key={v} value={v} className="bg-krypt-surface text-white">{lbl}</option>
        ))}
      </select>
    </label>
  );
}

type CardState = 'signal' | 'window' | 'watching' | 'idle';

function EdgeHealthCard() {
  const [eh, setEh] = useState<import('@shared/types').EdgeHealth | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await window.krypt.crypto15m.edgeHealth();
        if (alive) setEh(r);
      } catch {}
    };
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const verdictTone = (v: string) =>
    v.startsWith('edge holding') ? 'border-krypt-win/40 bg-krypt-win/10 text-krypt-win'
      : v.startsWith('measured NEGATIVE') ? 'border-krypt-loss/40 bg-krypt-loss/10 text-krypt-loss'
        : v.startsWith('possible decay') ? 'border-krypt-warn/40 bg-krypt-warn/10 text-krypt-warn'
          : 'border-krypt-border bg-krypt-surface2/60 text-krypt-dim';

  const W = ({ w }: { w: import('@shared/types').EdgeHealthWindow | null }) => (
    w ? (
      <span className="font-mono">
        {w.n}<span className="text-krypt-dim">n</span>{' '}
        <span className={w.netCentsPerContract >= 0 ? 'text-krypt-win' : 'text-krypt-loss'}>
          {w.netCentsPerContract >= 0 ? '+' : ''}{w.netCentsPerContract.toFixed(2)}¢
        </span>
        {w.t != null && <span className="text-krypt-dim"> t{w.t >= 0 ? '+' : ''}{w.t.toFixed(1)}</span>}
      </span>
    ) : <span className="text-krypt-dim">—</span>
  );

  return (
    <div className="mt-4 rounded-xl border border-krypt-border bg-krypt-surface p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs uppercase tracking-wider text-krypt-muted">Edge health — is it still working?</div>
        {eh && (
          <span className={cls(
            'rounded-full border px-2 py-0.5 text-[10px]',
            eh.calibration.ok ? 'border-krypt-border text-krypt-dim' : 'border-krypt-loss/40 bg-krypt-loss/10 text-krypt-loss',
          )}>
            model calibration {eh.calibration.ok ? 'OK' : 'DEGRADED'}
            {eh.calibration.rate != null ? ` · ${(eh.calibration.rate * 100).toFixed(0)}% hit / last ${eh.calibration.n}` : ''}
          </span>
        )}
      </div>
      <p className="mb-3 text-[11px] leading-relaxed text-krypt-dim">
        Rolling results of every strategy this account has actually traded, after fees, measured on
        settled positions — 7 / 30 / 90 days. Edges on this venue decay (our own mid-window model edge
        vanished within two months of the 15m launch) — so nothing here is ever “proven”, only
        currently-holding or not. Paper and live are separate rows and never mixed.
      </p>
      {!eh || eh.rows.length === 0 ? (
        <div className="text-xs text-krypt-dim">
          No settled positions yet — run a paper strategy and this panel fills in as windows resolve.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-krypt-dim">
                <th className="py-1 pr-3 font-normal">Strategy</th>
                <th className="py-1 pr-3 font-normal">Mode</th>
                <th className="py-1 pr-3 font-normal">7d</th>
                <th className="py-1 pr-3 font-normal">30d</th>
                <th className="py-1 pr-3 font-normal">90d</th>
                <th className="py-1 pr-3 font-normal">Win% (30d)</th>
                <th className="py-1 pr-3 font-normal">Since loss</th>
                <th className="py-1 font-normal">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {eh.rows.map((r) => (
                <tr key={`${r.strategy}-${r.mode}`} className="border-t border-krypt-border/50">
                  <td className="py-1.5 pr-3 font-mono text-white">{r.strategy}</td>
                  <td className="py-1.5 pr-3">
                    <span className={cls(
                      'rounded px-1.5 py-0.5 text-[10px] uppercase',
                      r.mode === 'live' ? 'bg-krypt-purple/20 text-krypt-purple' : 'bg-krypt-surface2 text-krypt-dim',
                    )}>{r.mode}</span>
                  </td>
                  <td className="py-1.5 pr-3"><W w={r.w7} /></td>
                  <td className="py-1.5 pr-3"><W w={r.w30} /></td>
                  <td className="py-1.5 pr-3"><W w={r.w90} /></td>
                  <td className="py-1.5 pr-3 font-mono text-krypt-dim">
                    {r.w30 ? `${(r.w30.winRate * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className="py-1.5 pr-3 font-mono text-krypt-dim">
                    {r.w90 ? (r.w90.losses ? `${r.w90.sinceLastLoss} wins` : `never (${r.w90.n})`) : '—'}
                  </td>
                  <td className="py-1.5">
                    <span className={cls('rounded-full border px-2 py-0.5 text-[10px]', verdictTone(r.verdict))}>
                      {r.verdict}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function cardState(a: Crypto15mAsset): CardState {
  if (a.signal) return 'signal';
  if (a.inWindow) return 'window';
  if (a.hasMarket) return 'watching';
  return 'idle';
}

function AssetCard({ a }: { a: Crypto15mAsset }) {
  const state = cardState(a);
  const ring =
    state === 'signal'
      ? 'border-krypt-win/60 shadow-[0_0_22px_rgba(34,197,94,0.18)]'
      : state === 'window'
        ? 'border-krypt-warn/50'
        : 'border-krypt-border';

  const upFav = a.favorite === 'up';
  const downFav = a.favorite === 'down';

  return (
    <div className={cls('krypt-card flex flex-col gap-3 border', ring)}>
      <div className="flex items-center gap-2">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-krypt-surface2 text-krypt-purple">
          <Bitcoin className="h-4 w-4" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">{a.asset}</div>
          <div className="font-mono text-[10px] text-krypt-dim">{a.series}</div>
        </div>
        <div className="ml-auto">
          <StatePill state={state} />
        </div>
      </div>

      {a.error ? (
        <div className="rounded-md border border-krypt-loss/30 bg-krypt-loss/5 px-2 py-1.5 text-[11px] text-krypt-loss">
          {a.error}
        </div>
      ) : !a.hasMarket ? (
        <div className="py-2 text-center text-xs text-krypt-dim">No open contract right now.</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <SideBox label="UP" prob={a.upProb} fav={upFav} good />
            <SideBox label="DOWN" prob={a.downProb} fav={downFav} />
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-krypt-muted">
              closes in <span className="font-mono text-white">{fmtMins(a.minsLeft)}</span>
            </span>
            <span className="text-krypt-muted">
              entry <span className="font-mono text-white">{pct(a.entryCost)}</span>
            </span>
          </div>
          <IndicatorStrip a={a} />
        </>
      )}

      <div className="-mx-5 -mb-5 mt-1 grid grid-cols-3 gap-px border-t border-krypt-border bg-krypt-border/40 text-center text-[11px]">
        <Foot label="Spot" value={fmtSpot(a.spotUsd)} />
        <Foot label="Open" value={fmtSpot(a.open15mUsd)} />
        <Foot label="Δ move" value={fmtDelta(a.deltaUsd)} />
      </div>
    </div>
  );
}

function StatePill({ state }: { state: CardState }) {
  if (state === 'signal') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-krypt-win/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-krypt-win">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-krypt-win shadow-[0_0_8px_currentColor]" />
        Signal
      </span>
    );
  }
  if (state === 'window') {
    return (
      <span className="rounded-full bg-krypt-warn/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-krypt-warn">
        In window
      </span>
    );
  }
  if (state === 'watching') {
    return (
      <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] uppercase tracking-wider text-krypt-muted">
        watching
      </span>
    );
  }
  return <span className="text-[10px] uppercase tracking-wider text-krypt-dim">idle</span>;
}

function SideBox({
  label, prob, fav, good,
}: { label: string; prob: number | null; fav: boolean; good?: boolean }) {
  return (
    <div
      className={cls(
        'rounded-lg border px-2 py-1.5 text-center',
        fav
          ? good
            ? 'border-krypt-win/40 bg-krypt-win/10'
            : 'border-krypt-loss/40 bg-krypt-loss/10'
          : 'border-krypt-border bg-krypt-surface2',
      )}
    >
      <div className={cls('text-[10px] uppercase tracking-wider', fav ? (good ? 'text-krypt-win' : 'text-krypt-loss') : 'text-krypt-dim')}>
        {label}{fav ? ' ★' : ''}
      </div>
      <div className="font-mono text-lg text-white">{pct(prob)}</div>
    </div>
  );
}

function Foot({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-krypt-surface px-2 py-2">
      <div className="text-[9px] uppercase tracking-wider text-krypt-dim">{label}</div>
      <div className="mt-0.5 font-mono text-white">{value}</div>
    </div>
  );
}

function IndicatorStrip({ a }: { a: Crypto15mAsset }) {
  const hasInd = a.macdHist != null || a.rsi != null;
  const hasModel = a.modelProb != null;
  if (!hasInd && !hasModel) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
      {a.rsi != null && (
        <span className="rounded bg-krypt-surface2 px-1.5 py-0.5 text-krypt-dim">
          RSI{' '}
          <span className={cls('font-mono', a.rsi >= 70 ? 'text-krypt-loss' : a.rsi <= 30 ? 'text-krypt-win' : 'text-white')}>
            {a.rsi.toFixed(0)}
          </span>
        </span>
      )}
      {a.macdHist != null && (
        <span className="rounded bg-krypt-surface2 px-1.5 py-0.5 text-krypt-dim">
          MACD{' '}
          <span className={cls('font-mono', a.macdHist >= 0 ? 'text-krypt-win' : 'text-krypt-loss')}>
            {a.macdHist >= 0 ? '+' : ''}{a.macdHist.toFixed(3)}
          </span>
          {a.macdCross === 1 && <span className="ml-0.5 text-krypt-win">▲</span>}
          {a.macdCross === -1 && <span className="ml-0.5 text-krypt-loss">▼</span>}
        </span>
      )}
      {hasModel && (
        <span
          className="rounded bg-krypt-surface2 px-1.5 py-0.5 text-krypt-dim"
          title="Settlement model: P(up) from the spot's distance to the strike scaled by realized 1-min volatility. The ¢ value is the best fee-adjusted edge the model sees vs the current asks (detection-only — gate on it via the rule builder)."
        >
          model{' '}
          <span className="font-mono text-white">{((a.modelProb ?? 0) * 100).toFixed(0)}%↑</span>
          {a.edgeNetCents != null && (
            <span className={cls('ml-1 font-mono', a.edgeNetCents > 0 ? 'text-krypt-win' : 'text-krypt-dim')}>
              {a.edgeNetCents > 0 ? '+' : ''}{a.edgeNetCents.toFixed(1)}¢
            </span>
          )}
          {(a.settlePrints ?? 0) > 0 && (
            <span className="ml-1 font-mono text-krypt-purple" title="Settlement prints already locked in — Kalshi averages ~60 once-per-second index prints over the final minute; these have been observed live.">
              {a.settlePrints}/60
            </span>
          )}
        </span>
      )}
    </div>
  );
}

function PositionsTable({ title, rows, runnerNames, showRunner }: {
  title: string; rows: Crypto15mPosition[];
  runnerNames?: Record<string, string>; showRunner?: boolean;
}) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-[0.16em] text-krypt-muted">{title}</h3>
      <div className="overflow-hidden rounded-xl border border-krypt-border">
        <table className="krypt-table">
          <thead>
            <tr>
              <th>Asset</th>
              <th>Side</th>
              {showRunner && <th>Runner</th>}
              <th>Status</th>
              <th>Contracts</th>
              <th>Entry</th>
              <th>Cost</th>
              <th>P&amp;L</th>
              <th>Mode</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => <PositionRow key={p.id} p={p} runnerNames={runnerNames} showRunner={showRunner} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PositionRow({ p, runnerNames, showRunner }: {
  p: Crypto15mPosition; runnerNames?: Record<string, string>; showRunner?: boolean;
}) {
  const entryC = p.avgEntryCents ?? p.entryLimitCents;
  const runnerLabel = p.runnerId ? (runnerNames?.[p.runnerId] ?? p.runnerId) : 'default';
  return (
    <tr>
      <td><TickerLink ticker={p.ticker} env={p.kalshiEnv} label={p.asset} /></td>
      <td>
        <span className={cls(
          'rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase',
          p.side === 'up' ? 'bg-krypt-win/10 text-krypt-win' : 'bg-krypt-loss/10 text-krypt-loss',
        )}>
          {p.side || p.direction}
        </span>
        {p.strategy === 'pair' && (
          <span
            className="ml-1 rounded-md bg-krypt-purple/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-krypt-purple"
            title="Complement-accumulation leg — held to settlement; a matched UP+DOWN pair pays $1 regardless of direction."
          >
            pair
          </span>
        )}
      </td>
      {showRunner && (
        <td className="text-xs">
          <span className={cls(
            'rounded-md px-1.5 py-0.5 text-[10px] font-medium',
            p.runnerId ? 'bg-krypt-purple/15 text-krypt-purple' : 'bg-krypt-surface2 text-krypt-dim',
          )} title={p.runnerId ? `Opened by runner "${runnerLabel}"` : 'Default runner'}>
            {runnerLabel}
          </span>
        </td>
      )}
      <td className="text-xs text-krypt-muted">
        {p.status}{p.exitReason === 'stop_loss' ? ' · stop' : p.exitReason === 'take_profit' ? ' · profit' : ''}
      </td>
      <td className="font-mono text-xs">{p.filledContracts}/{p.targetContracts}</td>
      <td className="font-mono text-xs">{entryC ? `${Math.round(entryC)}¢` : '—'}</td>
      <td className="font-mono text-xs text-krypt-muted">{fmtUsd(p.costUsd)}</td>
      <td className={cls(
        'font-mono text-xs',
        p.pnlUsd === null ? 'text-krypt-dim' : p.pnlUsd >= 0 ? 'text-krypt-win' : 'text-krypt-loss',
      )}>
        {p.pnlUsd === null ? '—' : fmtUsd(p.pnlUsd, { sign: true })}
      </td>
      <td>
        {p.dryRun
          ? <span className="rounded-md bg-krypt-warn/10 px-1.5 py-0.5 text-[10px] uppercase text-krypt-warn">paper</span>
          : <span className="rounded-md bg-krypt-loss/10 px-1.5 py-0.5 text-[10px] uppercase text-krypt-loss">live</span>}
      </td>
    </tr>
  );
}
