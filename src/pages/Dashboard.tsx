import { useEffect, useState } from 'react';
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Sparkles, TrendingDown, TrendingUp } from 'lucide-react';
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { PnlPoint } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { Card, Empty, Page, ShareableStat, StatCard } from '../components/common';
import { cls, fmtPct, fmtRelative, fmtUsd } from '../utils/format';
import { computeTradeWarnings } from '../utils/warnings';
import { BOOK_LABEL, bookEnvOf, isLive } from '../utils/account';
import { balanceView } from '../utils/balance';
import { bragText } from '../utils/brag';
import { hitRate } from '../utils/stats';
import { WhyNotTrading } from '../components/WhyNotTrading';
import type { PageId } from '../App';

interface DashboardProps {
  onNav: (p: PageId) => void;
}

export function DashboardPage({ onNav }: DashboardProps) {
  const { account, scannerStats, signals, positions, backend, credentialsAll, config } = useApp();
  const [series, setSeries] = useState<PnlPoint[]>([]);
  const mode = config?.accountMode;

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const s = await window.krypt.data.pnlSeries(168);
        if (mounted) setSeries(s);
      } catch {   }
    };
    setSeries([]);
    void load();
    const i = window.setInterval(load, 30000);
    return () => {
      mounted = false;
      window.clearInterval(i);
    };
  }, [mode]);

  const openPos = positions.filter(
    (p) => !p.resolved
      && p.status !== 'dry_run'
      && (p.status === 'filled' || p.status === 'partial' || p.status === 'submitted'),
  );
  const book = bookEnvOf(config);
  const botOpenPos = openPos.filter(
    (p) => p.signalSource !== 'external' && (!config || p.kalshiEnv === book),
  );
  const botPendingCount = botOpenPos.filter((p) => p.status === 'submitted').length;
  const externalOpenCount = openPos.length - botOpenPos.length;
  const recentResolved = positions
    .filter((p) => p.resolved && (!config || p.kalshiEnv === book))
    .slice(0, 5);

  const issues: { label: string; tone: 'warn' | 'bad' | 'good'; cta?: { label: string; page: PageId } }[] = [];
  const hasKeys = !!credentialsAll?.production?.hasApiKey && !!credentialsAll?.production?.hasRsaKey;
  const live = isLive(config);
  const bal = balanceView(account, {
    config, authOk: backend.authOk, hasKeys: credentialsAll ? hasKeys : null,
    engineRunning: backend.status === 'running',
  });
  const brag = (t: string): string => bragText(t, live);
  if (live && !hasKeys) {
    issues.push({
      label: 'The app is Live but no Kalshi key is saved — nothing can trade. Add a key, or switch back to Paper.',
      tone: 'bad',
      cta: { label: 'Add Keys', page: 'api' },
    });
  } else if (live && !backend.authOk) {
    issues.push({
      label: 'Saved keys could not authenticate to Kalshi',
      tone: 'bad',
      cta: { label: 'Re-test', page: 'api' },
    });
  }
  if (config && !config.enableTrading && (hasKeys || !live)) {
    issues.push({
      label: 'Auto-trading is paused — flip the switch in the top bar to enable',
      tone: 'warn',
    });
  }
  if (config && !live) {
    issues.push({
      label: 'PAPER mode — real Kalshi prices, imaginary money. Nothing here can send a real order. Go live in Settings → Account.',
      tone: 'good',
      cta: { label: 'Account', page: 'settings' },
    });
  }
  if (backend.status !== 'running' && backend.status !== 'starting') {
    issues.push({
      label: `Backend is ${backend.status}${backend.lastError ? ` — ${backend.lastError}` : ''}`,
      tone: 'bad',
    });
  }
  for (const tw of computeTradeWarnings(config, account)) {
    issues.push({
      label: tw.message,
      tone: tw.severity === 'block' ? 'bad' : 'warn',
      cta: tw.page ? { label: tw.fixLabel ?? 'Fix', page: tw.page } : undefined,
    });
  }
  if (issues.length === 0) {
    issues.push({ label: 'Everything looks good. Bot is online and watching.', tone: 'good' });
  }

  const sessionPnl = bal.sessionPnlUsd;
  const sessionBaseline = bal.known ? account?.sessionBaselineUsd ?? null : null;
  const sessionRoi = bal.sessionRoiPct;
  const sessionStartedAt = account?.sessionStartedAt;
  const alltimePnl = bal.alltimePnlUsd;
  const realizedPos = account?.realizedPnlUsd ?? null;
  const alltimeBaseline = bal.known ? account?.alltimeBaselineUsd ?? null : null;
  const decided = (account?.wins ?? 0) + (account?.losses ?? 0);
  const tone = (v: number | null): 'good' | 'bad' | undefined => (v === null ? undefined : v >= 0 ? 'good' : 'bad');

  return (
    <Page title="Dashboard" subtitle="A snapshot of the book you are in now: balance, signals and bot health.">
      <div className="grid gap-4 md:grid-cols-3">
        {bal.known ? (
          <ShareableStat
            label={`Total Balance · ${live ? 'Live' : 'Paper'}`}
            value={fmtUsd(bal.totalUsd)}
            hint={account?.balanceSyncing
              ? '⏳ syncing — an order just filled or settled; Kalshi reflects it in a moment'
              : `cash ${fmtUsd(bal.cashUsd)} · port ${fmtUsd(bal.portfolioUsd)}`}
            shareText={brag(`Krypt Trader balance: ${fmtUsd(bal.totalUsd)}`
              + (alltimePnl !== null ? ` (${fmtUsd(alltimePnl, { sign: true })} since I started)` : '')
              + '. Free Kalshi auto-trader by @YuhgoSlavia · krypt.cc/tools/trader')}
          />
        ) : (
          <StatCard label={`Total Balance · ${live ? 'Live' : 'Paper'}`} value="—" hint={bal.why ?? undefined} />
        )}
        {sessionPnl !== null ? (
          <ShareableStat
            label="Session P&L"
            value={fmtUsd(sessionPnl, { sign: true })}
            hint={
              account?.balanceSyncing
                ? '⏳ syncing — a fill/settlement is landing; this number self-corrects in a moment'
                : `${fmtUsd(sessionBaseline)} → ${fmtUsd(bal.totalUsd)} · ${fmtPct(sessionRoi)} · since ${fmtRelative(sessionStartedAt)}`
            }
            accent={account?.balanceSyncing ? undefined : tone(sessionPnl)}
            shareText={brag(`This session on Krypt Trader: ${fmtUsd(sessionPnl, { sign: true })}`
              + (sessionRoi !== null ? ` (${fmtPct(sessionRoi)} ROI)` : '')
              + '. Free Kalshi auto-trader by @YuhgoSlavia · krypt.cc/tools/trader')}
          />
        ) : (
          <StatCard
            label="Session P&L"
            value="—"
            hint={bal.known ? 'session baseline pending' : bal.why ?? undefined}
          />
        )}
        <StatCard
          label="Open Positions"
          value={`${botOpenPos.length} / ${config?.maxOpenPositions ?? 25}`}
          hint={`${botPendingCount} pending · ${botOpenPos.length - botPendingCount} filled`
            + (externalOpenCount > 0 ? ` · +${externalOpenCount} external/other-env (not in cap)` : '')}
        />
      </div>

      <div className="mt-3 grid gap-4 md:grid-cols-2">
        {alltimePnl !== null ? (
          <ShareableStat
            label="All-time P&L"
            value={fmtUsd(alltimePnl, { sign: true })}
            hint={`${fmtUsd(alltimeBaseline)} → ${fmtUsd(bal.totalUsd)} · change in balance`}
            accent={tone(alltimePnl)}
            shareText={brag(`All-time on Krypt Trader: ${fmtUsd(alltimePnl, { sign: true })}`
              + (bal.roiPct !== null ? ` (${fmtPct(bal.roiPct)})` : '')
              + '. Free Kalshi auto-trader by @YuhgoSlavia · krypt.cc/tools/trader')}
          />
        ) : (
          <StatCard
            label="All-time P&L"
            value="—"
            hint={bal.known ? 'Starts once the first balance snapshot is saved.' : bal.why ?? undefined}
          />
        )}
        {decided > 0 ? (
          <ShareableStat
            label="Win Rate"
            value={`${(account?.winRate ?? 0).toFixed(1)}%`}
            hint={`${account?.wins ?? 0}W / ${account?.losses ?? 0}L · settled trades P&L ${fmtUsd(realizedPos, { sign: true })}`}
            shareText={brag(`Krypt Trader win rate: ${(account?.winRate ?? 0).toFixed(1)}% `
              + `(${account?.wins ?? 0}W / ${account?.losses ?? 0}L). `
              + 'Free Kalshi auto-trader by @YuhgoSlavia · krypt.cc/tools/trader')}
          />
        ) : (
          <StatCard label="Win Rate" value="—" hint="No settled trades yet in this book." />
        )}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" header={
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wider text-krypt-muted">Equity curve</div>
              <div className="mt-0.5 text-sm text-white">
                Last {Math.min(168, Math.floor(((Date.now() - new Date(series[0]?.at ?? Date.now()).getTime()) / 3600000) || 168))}h
              </div>
            </div>
            <div className="text-xs text-krypt-muted">
              {series.length} samples
            </div>
          </div>
        }>
          {series.length < 3 ? (
            <Empty
              title="Not enough data yet"
              description="The equity curve fills in as the bot runs. Come back in a few cycles."
            />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={series}>
                  <defs>
                    <linearGradient id="fillGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#A855F7" stopOpacity={0.55} />
                      <stop offset="100%" stopColor="#A855F7" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="at"
                    hide
                  />
                  <YAxis
                    domain={['dataMin - 5', 'dataMax + 5']}
                    tickFormatter={(v) => `$${Math.round(v)}`}
                    width={50}
                    tick={{ fill: '#71717A', fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    labelStyle={{ color: '#A1A1AA' }} itemStyle={{ color: '#FFFFFF' }} contentStyle={{
                      background: '#171722',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    formatter={(v: number) => [`$${v.toFixed(2)}`, 'Equity']}
                    labelFormatter={(v) => fmtRelative(String(v))}
                  />
                  <Area
                    type="monotone"
                    dataKey="totalUsd"
                    stroke="#A855F7"
                    strokeWidth={2}
                    fill="url(#fillGrad)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card header={<div className="text-xs uppercase tracking-wider text-krypt-muted">Status</div>}>
          <div className="flex flex-col gap-2">
            {issues.map((i, idx) => (
              <div
                key={idx}
                className={cls(
                  'flex items-start gap-2 rounded-lg border p-2 text-xs',
                  i.tone === 'good' && 'border-krypt-win/30 bg-krypt-win/5 text-krypt-win',
                  i.tone === 'warn' && 'border-krypt-warn/30 bg-krypt-warn/5 text-krypt-warn',
                  i.tone === 'bad' && 'border-krypt-loss/30 bg-krypt-loss/5 text-krypt-loss',
                )}
              >
                {i.tone === 'good' ? (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                ) : (
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                )}
                <div className="flex-1">{i.label}</div>
                {i.cta && (
                  <button
                    onClick={() => onNav(i.cta!.page)}
                    className="rounded-md border border-current px-2 py-0.5 text-[11px] hover:bg-current/10"
                  >
                    {i.cta.label}
                  </button>
                )}
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <Mini label="Whales seen" value={scannerStats ? `${scannerStats.whales.total}` : '—'} />
            <Mini label="Whales hit" value={hitRate(scannerStats?.whales)} />
            <Mini label="Momentum seen" value={scannerStats ? `${scannerStats.momentum.total}` : '—'} />
            <Mini label="Momentum hit" value={hitRate(scannerStats?.momentum)} />
            <Mini label="Markets" value={scannerStats ? `${scannerStats.marketsTracked}` : '—'} />
            <Mini label="Last scan" value={fmtRelative(scannerStats?.lastTradeScanAt)} />
          </div>
          <div className="mt-4">
            <WhyNotTrading />
          </div>
        </Card>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card header={
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-krypt-purple" />
              <span className="text-sm text-white">Latest signals</span>
            </div>
            <button onClick={() => onNav('signals')} className="text-xs text-krypt-muted hover:text-white">
              View all <ArrowRight className="ml-1 inline h-3 w-3" />
            </button>
          </div>
        }>
          {signals.length === 0 ? (
            <Empty title="No signals yet" description="The scanners need a few minutes after launch." />
          ) : (
            <div className="flex flex-col divide-y divide-krypt-border">
              {signals.slice(0, 7).map((s) => (
                <div key={`${s.source}:${s.id}`} className="flex items-center gap-3 py-2 text-sm">
                  <span className={cls(
                    'inline-flex h-6 w-14 items-center justify-center rounded-md text-[10px] font-medium uppercase',
                    s.source === 'whale' ? 'bg-krypt-purple/15 text-krypt-purple' : 'bg-krypt-pink/15 text-krypt-pink',
                  )}>
                    {s.source}
                  </span>
                  <span className="font-mono text-xs text-krypt-muted">{s.ticker}</span>
                  <span className="ml-auto truncate text-xs text-krypt-muted">{s.title}</span>
                  <span className={cls(
                    'min-w-[44px] text-right font-mono text-xs',
                    s.direction === 'yes' ? 'text-krypt-win' : 'text-krypt-loss',
                  )}>
                    {s.direction.toUpperCase()} {s.priceCents}¢
                  </span>
                  <span className="min-w-[40px] text-right font-mono text-xs text-krypt-purple">
                    +{s.edgePts.toFixed(1)}
                  </span>
                  {s.traded && (
                    <span className="krypt-pill border-krypt-indigo/40 bg-krypt-indigo/10 text-krypt-indigo">
                      traded
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card header={
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-krypt-pink" />
              <span className="text-sm text-white">Recent resolutions</span>
              <span className="text-[11px] text-krypt-dim">· {BOOK_LABEL[book]} book</span>
            </div>
            <button onClick={() => onNav('history')} className="text-xs text-krypt-muted hover:text-white">
              View all <ArrowRight className="ml-1 inline h-3 w-3" />
            </button>
          </div>
        }>
          {recentResolved.length === 0 ? (
            <Empty
              title="No resolved trades yet"
              description="Wins and losses show up here as markets settle."
            />
          ) : (
            <div className="flex flex-col divide-y divide-krypt-border">
              {recentResolved.map((p) => (
                <div key={p.id} className="flex items-center gap-3 py-2 text-sm">
                  {p.outcomeCorrect === 1 ? (
                    <TrendingUp className="h-4 w-4 text-krypt-win" />
                  ) : p.outcomeCorrect === 0 ? (
                    <TrendingDown className="h-4 w-4 text-krypt-loss" />
                  ) : (
                    <span className="h-4 w-4" />
                  )}
                  <span className="font-mono text-xs text-krypt-muted">{p.ticker}</span>
                  <span className="ml-auto truncate text-xs text-krypt-muted">{p.title}</span>
                  <span className={cls(
                    'min-w-[60px] text-right font-mono text-sm',
                    (p.pnlUsd ?? 0) >= 0 ? 'text-krypt-win' : 'text-krypt-loss',
                  )}>
                    {fmtUsd(p.pnlUsd, { sign: true })}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </Page>
  );
}


function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-krypt-muted">{label}</div>
      <div className="font-mono text-sm text-white">{value}</div>
    </div>
  );
}
