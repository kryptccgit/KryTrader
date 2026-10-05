export const TICKER_RE = /^[A-Za-z0-9._-]{1,120}$/;

export function cleanTicker(v: unknown): string {
  const t = String(v ?? '').trim().toUpperCase();
  return TICKER_RE.test(t) ? t : '';
}

export function clampInt(v: unknown, lo: number, hi: number, dflt: number): number {
  if (v === null || v === undefined || v === '') return dflt;
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n)) return dflt;
  return Math.min(hi, Math.max(lo, Math.round(n)));
}

export const DISCOVER_COLUMNS = new Set([
  'trending', 'closing', 'new', 'volume', 'watchlist',
]);

export const CANDLE_INTERVALS = new Set([1, 60, 1440]);

export function cleanFilters(f: unknown): Record<string, unknown> | null {
  if (!f || typeof f !== 'object') return null;
  const src = f as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  const cats = Array.isArray(src.categories)
    ? src.categories.filter((c): c is string => typeof c === 'string').slice(0, 40)
    : [];
  if (cats.length) out.categories = cats;
  for (const [key, lo, hi] of [
    ['minPriceCents', 1, 99], ['maxPriceCents', 1, 99],
    ['minVolume', 0, 1e9], ['maxHoursToClose', 0, 24 * 365],
  ] as const) {
    const v = src[key];
    if (v === undefined || v === null || v === '') continue;
    const n = Number(v);
    if (Number.isFinite(n)) out[key] = Math.min(hi, Math.max(lo, n));
  }
  return Object.keys(out).length ? out : null;
}

export function cleanTicket(req: unknown): {
  ticker: string;
  side: 'yes' | 'no';
  action: 'buy' | 'sell';
  count: number;
  priceCents: number;
} {
  const r = (req ?? {}) as Record<string, unknown>;
  return {
    ticker: cleanTicker(r.ticker),
    side: r.side === 'no' ? 'no' : 'yes',
    action: r.action === 'sell' ? 'sell' : 'buy',
    count: clampInt(r.count, 0, 1_000_000, 0),
    priceCents: Number(r.priceCents),
  };
}

export function nextWatchlist(
  current: string[], ticker: string, watched: boolean, cap = 500,
): string[] {
  const t = cleanTicker(ticker);
  if (!t) return current;
  if (watched) {
    return current.includes(t) ? current : [t, ...current].slice(0, cap);
  }
  return current.filter((x) => x !== t);
}

export function filterAgentConfigPatch(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw as Record<string, unknown>).filter(([k]) =>
    k !== 'kalshiEnv'
    && !/^(mcp|remote|ai|autopilot|terminalMax)/.test(k)
    && !/webhook|url|token|discord|telegram|key|secret/i.test(k)));
}
