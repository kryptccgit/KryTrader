import { fmtNum } from './format';


export function hitRate(s: { resolved: number; winRate: number } | null | undefined): string {
  if (!s || !(s.resolved > 0) || !Number.isFinite(s.winRate)) return '—';
  return `${s.winRate.toFixed(1)}%`;
}

export function winRatePct(wins: number | null | undefined, losses: number | null | undefined): number | null {
  const w = Number(wins ?? 0);
  const l = Number(losses ?? 0);
  if (!Number.isFinite(w) || !Number.isFinite(l) || w + l <= 0) return null;
  return (w / (w + l)) * 100;
}

export function fmtTokens(input: number | null | undefined, output: number | null | undefined, estimated?: boolean): string {
  const parts = [input, output].filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (!parts.length) return '—';
  const n = parts.reduce((a, b) => a + b, 0);
  return estimated ? `~${fmtNum(n)} tok (estimated)` : `${fmtNum(n)} tok`;
}
