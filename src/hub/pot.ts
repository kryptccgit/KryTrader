import type { BotPosition } from '@shared/types';


export interface Pot {
  wins: number;
  losses: number;
  winPnl: number;
  lossPnl: number;
}

export const EMPTY_POT: Pot = { wins: 0, losses: 0, winPnl: 0, lossPnl: 0 };

export const SEEN_CAP = 4000;

export function countPot(seen: Map<number, boolean>, positions: BotPosition[], sessionStart: number | null): Pot {
  const d: Pot = { ...EMPTY_POT };
  for (const p of positions) {
    if (seen.get(p.id)) continue;
    if (!p.resolved || (p.outcomeCorrect !== 0 && p.outcomeCorrect !== 1)) continue;
    if (p.status === 'dry_run') { seen.set(p.id, true); continue; }
    if (sessionStart !== null) {
      const at = p.resolvedAt ? Date.parse(p.resolvedAt) : NaN;
      if (!Number.isFinite(at) || at < sessionStart) { seen.set(p.id, true); continue; }
    }
    seen.set(p.id, true);
    const pnl = typeof p.pnlUsd === 'number' && Number.isFinite(p.pnlUsd) ? p.pnlUsd : 0;
    if (p.outcomeCorrect === 1) { d.wins++; d.winPnl += pnl; } else { d.losses++; d.lossPnl += pnl; }
  }
  if (seen.size > SEEN_CAP) {
    const live = new Set(positions.map((p) => p.id));
    for (const id of seen.keys()) if (!live.has(id)) seen.delete(id);
  }
  return d;
}

export function addPot(a: Pot, b: Pot): Pot {
  return { wins: a.wins + b.wins, losses: a.losses + b.losses, winPnl: a.winPnl + b.winPnl, lossPnl: a.lossPnl + b.lossPnl };
}
