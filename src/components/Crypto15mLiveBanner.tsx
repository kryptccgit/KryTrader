import { useState } from 'react';
import { Zap } from 'lucide-react';
import type { TraderConfig } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { c15RealOrderRunners } from '../utils/c15Live';
import { userMessage } from '../utils/errors';

export function Crypto15mLiveBanner() {
  const { config } = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const runners = c15RealOrderRunners(config);
  if (runners !== null && runners.length === 0) return null;

  const patch = async (p: Partial<TraderConfig>, msg: string): Promise<void> => {
    setBusy(true);
    try {
      await window.krypt.config.update(p);
      toast.success(msg);
    } catch (e: any) {
      toast.error(userMessage(e, 'Failed to stop trading'));
    } finally {
      setBusy(false);
    }
  };

  const who = runners === null
    ? '15-minute crypto executor is LIVE'
    : `15-minute crypto: ${runners.length} Multi-Run runner${runners.length === 1 ? '' : 's'} LIVE`
      + ` (${runners.map((r) => r.name).join(', ')})`;

  return (
    <div className="z-10 flex shrink-0 items-center gap-3 border-b border-krypt-warn/40 bg-krypt-warn/10 px-6 py-2 text-xs text-krypt-warn">
      <Zap className="h-4 w-4 shrink-0" />
      <div className="flex-1 leading-snug">
        <span className="font-semibold">{who}</span>
        {' — it places real Kalshi orders on its own, independent of the main '}
        Auto-trading switch (the top-bar <span className="font-semibold">Pause</span> won&apos;t stop it).
      </div>
      <button
        onClick={() => void patch({ crypto15mLive: false }, '15m real orders off — no runner opens a new real position')}
        disabled={busy}
        className="shrink-0 rounded-md border border-krypt-warn/50 px-2.5 py-1 font-medium transition-colors hover:bg-krypt-warn/15 disabled:opacity-50"
        title="Turn off 15m Real orders (LIVE): the executor and every Multi-Run runner stop opening real positions. Existing positions keep being managed."
      >
        Stop 15m
      </button>
      <button
        onClick={() => void patch({ enableTrading: false, crypto15mLive: false }, 'All trading stopped')}
        disabled={busy}
        className="shrink-0 rounded-md border border-krypt-loss/60 bg-krypt-loss/10 px-2.5 py-1 font-semibold text-krypt-loss transition-colors hover:bg-krypt-loss/20 disabled:opacity-50"
        title="Stop both engines — main bot, and 15m real orders (executor and every live runner)"
      >
        Stop all trading
      </button>
    </div>
  );
}
