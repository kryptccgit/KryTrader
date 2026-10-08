import { Pause, Play, Power, RefreshCw } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { ShareButton } from './common';
import { ShardStrip } from './terminal/ShardBalances';
import { cls, fmtPct, fmtUsd } from '../utils/format';
import { computeTradeWarnings } from '../utils/warnings';
import { GlassPanel } from './glass/GlassPanel';
import { GlassButton } from './glass/GlassButton';
import { GLASS_TINTS } from './glass/glassPresets';
import { armedEngines, isRealMoney, type ArmedEngine } from '../utils/liveEngines';
import { useBalance } from '../state/useBalance';
import { bragText } from '../utils/brag';

export function useSetTrading(): (next: boolean) => Promise<void> {
  const { config, account } = useApp();
  const toast = useToast();
  return async (next: boolean): Promise<void> => {
    if (next && config?.accountMode === 'live' && !window.confirm(
      'Start auto-trading LIVE?\n\nThe bot will place REAL-money orders on your Kalshi account.',
    )) return;
    const r = await window.krypt.trading.setEnabled(next);
    if (!r.ok) {
      toast.error(r.message || 'Failed to toggle trading');
      return;
    }
    toast.success(next ? 'Trading enabled' : 'Trading paused');
    if (next && config) {
      const blockers = computeTradeWarnings({ ...config, enableTrading: true }, account)
        .filter((w) => w.severity === 'block');
      if (blockers.length) toast.error(`Won't trade: ${blockers[0].message}`);
    }
  };
}

export function TopBar() {
  const { config, account, backend, refresh } = useApp();
  const toast = useToast();
  const setTrading = useSetTrading();
  const bal = useBalance();
  const roi = bal.sessionRoiPct ?? bal.roiPct;

  const tradingOn = !!config?.enableTrading;
  const toggle = (): Promise<void> => setTrading(!tradingOn);
  const realMoney = isRealMoney(config) ? armedEngines(config) : [];

  const restart = async (): Promise<void> => {
    toast.info('Restarting backend…');
    await window.krypt.backend.restart();
    setTimeout(() => void refresh.backend(), 1000);
  };

  return (
    <GlassPanel
      preset="chrome"
      display="flex"
      tint={GLASS_TINTS.chrome}
      className="z-20 shrink-0 items-center gap-4 border-b border-white/[0.06] px-6 py-3"
    >
      <div className="flex items-baseline gap-2">
        <h1 className="glass-title text-lg font-semibold">
          {config?.accountMode === 'live' ? 'Live Trading' : 'Paper Trading'}
        </h1>
        <span className="text-xs text-krypt-muted">
          · {backend.status === 'running' ? 'Engine online' : `Engine ${backend.status}`}
        </span>
        <LiveEnginesPill engines={realMoney} />
      </div>

      <div className="ml-auto flex items-center gap-2">
        {account?.shardCash && (
          <ShardStrip
            shards={Object.entries(account.shardCash).map(([idx, sh]) => ({
              index: Number(idx), name: sh.name, cashUsd: sh.cashUsd,
            }))}
            transferUrl={account.shardTransferUrl ?? ''}
            onDone={() => void refresh.account()}
          />
        )}
        <div className="hidden items-center gap-3 px-3 md:flex">
          <Stat label="Balance" value={fmtUsd(bal.totalUsd)} title={bal.why ?? undefined} />
          <Stat
            label="Session P&L"
            value={fmtUsd(bal.sessionPnlUsd, { sign: true })}
            color={bal.sessionPnlUsd === null ? 'text-krypt-dim'
              : bal.sessionPnlUsd >= 0 ? 'text-krypt-win' : 'text-krypt-loss'}
            title={bal.why ?? undefined}
          />
          <Stat
            label="ROI"
            value={fmtPct(roi)}
            color={roi === null ? 'text-krypt-dim' : roi >= 0 ? 'text-krypt-win' : 'text-krypt-loss'}
            title={bal.why ?? undefined}
          />
          {bal.known && (
            <ShareButton
              size="xs"
              text={bragText(
                `Krypt Trader: ${fmtUsd(bal.totalUsd)} balance`
                + (bal.sessionPnlUsd !== null ? ` · ${fmtUsd(bal.sessionPnlUsd, { sign: true })} this session` : '')
                + (roi !== null ? ` · ${fmtPct(roi)} ROI` : '')
                + '. Free Kalshi auto-trader by @YuhgoSlavia · krypt.cc/tools/trader',
                config?.accountMode === 'live',
              )}
            />
          )}
        </div>

        <GlassButton
          onClick={restart}
          title="Restart the trading engine (the background part of the app that talks to Kalshi)"
        >
          <RefreshCw className="h-4 w-4" />
          Restart
        </GlassButton>

        <GlassButton
          onClick={toggle}
          variant={tradingOn ? 'danger' : 'primary'}
          className="min-w-[120px]"
          data-tour="trading-toggle"
        >
          {tradingOn ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          {tradingOn ? 'Pause' : 'Start Trading'}
          {!backend.authOk && (
            <Power className="ml-1 h-3 w-3 opacity-60" />
          )}
        </GlassButton>
      </div>
    </GlassPanel>
  );
}

export function LiveEnginesPill({ engines, className }: { engines: ArmedEngine[]; className?: string }) {
  if (!engines.length) return null;
  return (
    <span
      role="status"
      title={`Armed with REAL money:\n${engines.map((e) => `• ${e.label}`).join('\n')}`}
      className={cls(
        'inline-flex min-w-0 items-center gap-1.5 self-center truncate rounded-full border border-krypt-loss/60 bg-krypt-loss/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-krypt-loss shadow-[0_0_12px_-3px_rgba(239,68,68,0.7)]',
        className,
      )}
    >
      <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-krypt-loss" />
      <span className="truncate">LIVE · {engines.map((e) => e.short).join(' · ')}</span>
    </span>
  );
}

function Stat({
  label, value, color, title,
}: { label: string; value: string; color?: string; title?: string }) {
  return (
    <div className="flex flex-col items-end leading-tight" title={title}>
      <span className="text-[10px] uppercase tracking-wider text-krypt-muted">
        {label}
      </span>
      <span className={cls('font-mono text-sm tabular-nums', color || 'text-white')}>
        {value}
      </span>
    </div>
  );
}
