import type { AccountSnapshot, BotPosition, ScannerStats, SignalRow, TraderConfig } from '@shared/types';
import type { AutopilotStatus, ForecastScoreboard } from '@shared/market';
import type { SavedBacktest } from './library';
import { sessionPnlOf } from './payday';

export interface HubData {
  signals: SignalRow[];
  positions: BotPosition[];
  account: AccountSnapshot | null;
  scannerStats: ScannerStats | null;
  config?: TraderConfig | null;
  library?: SavedBacktest[];
  autopilot?: AutopilotStatus | null;
  scoreboard?: ForecastScoreboard | null;
  councilChoice?: 'personas' | 'agents' | null;
}

export interface HudNumbers {
  pnl: number | null;
  roi: number | null;
  winRate: number | null;
  settledToday: number | null;
  open: number | null;
  signals: number | null;
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

export function hudNumbers(a: AccountSnapshot | null, s: ScannerStats | null): HudNumbers {
  const pnl = sessionPnlOf(a);
  const wins = num(a?.wins);
  const losses = num(a?.losses);
  const tw = num(a?.todayWins);
  const tl = num(a?.todayLosses);
  return {
    pnl,
    roi: pnl === null ? null : num(a?.sessionRoiPct),
    winRate: wins !== null && losses !== null && wins + losses > 0 ? num(a?.winRate) : null,
    settledToday: tw !== null && tl !== null ? tw + tl : null,
    open: num(a?.openCount),
    signals: s ? s.whales.total + s.momentum.total : null,
  };
}

export function balanceOf(a: AccountSnapshot | null): number | null {
  if (!a) return null;
  const t = num(a.totalUsd);
  if (t === null) return null;
  if (t > 0) return t;
  return num(a.sessionBaselineUsd) !== null && (a.sessionBaselineUsd as number) > 0 ? t : null;
}
