import type { AccountSnapshot, BotPosition } from '@shared/types';


export const PAYDAY_MIN_USD = 25;
export const PAYDAY_BALANCE_FRAC = 0.02;
export const PAYDAY_PNL_STEP_USD = 100;
export const PAYDAY_COOLDOWN_MS = 60_000;

export interface PaydayEvent {
  kind: 'settlement' | 'milestone';
  amountUsd: number;
  label: string;
}

export function settlementThreshold(balanceUsd: number | null | undefined): number {
  const b = typeof balanceUsd === 'number' && Number.isFinite(balanceUsd) && balanceUsd > 0 ? balanceUsd : 0;
  return Math.max(PAYDAY_MIN_USD, b * PAYDAY_BALANCE_FRAC);
}

export function sessionPnlOf(a: AccountSnapshot | null | undefined): number | null {
  if (!a || typeof a.sessionPnlUsd !== 'number' || !Number.isFinite(a.sessionPnlUsd)) return null;
  if (!(typeof a.sessionBaselineUsd === 'number' && a.sessionBaselineUsd > 0)) return null;
  return a.sessionPnlUsd;
}

export class PaydayTracker {
  private seen = new Map<number, boolean>();
  private primed = false;
  private runId: number | null = null;
  private step: number | null = null;
  private lastAt = -Infinity;

  check(positions: BotPosition[], account: AccountSnapshot | null, label: (p: BotPosition) => string, now: number): PaydayEvent | null {
    const runId = account?.sessionRunId ?? null;
    if (this.primed && runId !== null && this.runId !== null && runId !== this.runId) {
      this.step = null;
    }
    if (runId !== null) this.runId = runId;

    let best: BotPosition | null = null;
    for (const p of positions) {
      const settled = p.resolved && p.outcomeCorrect !== null;
      const was = this.seen.get(p.id);
      this.seen.set(p.id, settled);
      if (!this.primed || !settled || was === true) continue;
      if (p.status === 'dry_run') continue;
      if (typeof p.pnlUsd !== 'number' || !Number.isFinite(p.pnlUsd)) continue;
      if (!best || p.pnlUsd > (best.pnlUsd ?? -Infinity)) best = p;
    }
    if (this.seen.size > 6000) {
      const live = new Set(positions.map((p) => p.id));
      for (const id of this.seen.keys()) if (!live.has(id)) this.seen.delete(id);
    }

    const pnl = sessionPnlOf(account);
    let crossed = false;
    if (pnl !== null) {
      const s = Math.max(0, Math.floor(pnl / PAYDAY_PNL_STEP_USD));
      if (this.step === null || !this.primed) this.step = s;
      else if (s > this.step) {
        this.step = s;
        crossed = true;
      }
    }
    this.primed = true;

    let ev: PaydayEvent | null = null;
    if (best && (best.pnlUsd as number) >= settlementThreshold(account?.totalUsd)) {
      ev = { kind: 'settlement', amountUsd: best.pnlUsd as number, label: label(best) };
    } else if (crossed && pnl !== null) {
      ev = { kind: 'milestone', amountUsd: pnl, label: 'session P&L' };
    }
    if (!ev) return null;
    if (now - this.lastAt < PAYDAY_COOLDOWN_MS) return null;
    this.lastAt = now;
    return ev;
  }
}

export function paydayLine(ev: PaydayEvent): string {
  const v = ev.amountUsd;
  const amt = `${v < 0 ? '−' : '+'}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return ev.kind === 'milestone' ? `${amt} session P&L` : `${amt} · ${ev.label}`;
}
