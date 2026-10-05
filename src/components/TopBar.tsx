import { Pause, Play, Power, RefreshCw } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { ShareButton } from './common';
import { ShardStrip } from './terminal/ShardBalances';
import { cls, fmtPct, fmtUsd } from '../utils/format';
import { computeTradeWarnings } from '../utils/warnings';

export function TopBar() {
  const { config, account, backend, refresh } = useApp();
  const toast = useToast();

  const tradingOn = !!config?.enableTrading;

  const toggle = async (): Promise<void> => {
    const next = !tradingOn;
    if (next && config?.kalshiEnv === 'production' && !window.confirm(
      'Start auto-trading on PRODUCTION?\n\nThe bot will place REAL-money orders on your Kalshi account.',
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

  const restart = async (): Promise<void> => {
    toast.info('Restarting backend…');
    await window.krypt.backend.restart();
    setTimeout(() => void refresh.backend(), 1000);
  };

  return (
    <header className="z-20 flex items-center gap-4 border-b border-krypt-border bg-krypt-void/70 px-6 py-3 backdrop-blur">
      <div className="flex items-baseline gap-2">
        <h1 className="text-lg font-semibold text-white">
          {config?.kalshiEnv === 'production' ? 'Live Trading' : 'Demo Trading'}
        </h1>
        <span className="text-xs text-krypt-muted">
          · {backend.status === 'running' ? 'Engine online' : `Engine ${backend.status}`}
        </span>
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
          <Stat label="Balance" value={fmtUsd(account?.totalUsd ?? 0)} />
          <Stat
            label="Session P&L"
            value={fmtUsd(account?.sessionPnlUsd ?? 0, { sign: true })}
            color={
              (account?.sessionPnlUsd ?? 0) >= 0 ? 'text-krypt-win' : 'text-krypt-loss'
            }
          />
          <Stat
            label="ROI"
            value={fmtPct(account?.sessionRoiPct ?? account?.roiPct ?? 0)}
            color={
              (account?.sessionRoiPct ?? account?.roiPct ?? 0) >= 0
                ? 'text-krypt-win' : 'text-krypt-loss'
            }
          />
          <ShareButton
            size="xs"
            text={
              `Krypt Trader: ${fmtUsd(account?.totalUsd ?? 0)} balance · `
              + `${fmtUsd(account?.sessionPnlUsd ?? 0, { sign: true })} this session · `
              + `${fmtPct(account?.sessionRoiPct ?? account?.roiPct ?? 0)} ROI. `
              + `Free Kalshi auto-trader by @YuhgoSlavia · krypt.cc/tools/trader`
            }
          />
        </div>

        <button
          onClick={restart}
          className="krypt-btn-default"
          title="Restart Python backend"
        >
          <RefreshCw className="h-4 w-4" />
          Restart
        </button>

        <button
          onClick={toggle}
          className={cls(
            tradingOn ? 'krypt-btn-danger' : 'krypt-btn-primary',
            'min-w-[120px]',
          )}
        >
          {tradingOn ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          {tradingOn ? 'Pause' : 'Start Trading'}
          {!backend.authOk && (
            <Power className="ml-1 h-3 w-3 opacity-60" />
          )}
        </button>
      </div>
    </header>
  );
}

function Stat({
  label, value, color,
}: { label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col items-end leading-tight">
      <span className="text-[10px] uppercase tracking-wider text-krypt-muted">
        {label}
      </span>
      <span className={cls('font-mono text-sm', color || 'text-white')}>
        {value}
      </span>
    </div>
  );
}
