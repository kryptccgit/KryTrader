import type { TurbineStrategy } from '@shared/types';

export interface SavedBacktest {
  name: string;
  net: number;
  t: number | null;
  n: number | null;
}


const TTL_MS = 10 * 60_000;
let cache: { at: number; rows: Promise<SavedBacktest[]> } | null = null;

export function shortStrategy(name: string): string {
  let s = name.replace('★', '').split(/ — | \(/)[0].trim();
  s = s.replace(/^(BTC|ETH|SOL|XRP|DOGE|HYPE|BNB)\s+15m\s+/i, '');
  if (s.length > 20) s = s.split(' ').slice(-2).join(' ');
  return s;
}

export function savedBacktests(strategies: TurbineStrategy[] | null | undefined): SavedBacktest[] {
  const out: SavedBacktest[] = [];
  for (const st of strategies ?? []) {
    const net = st.backtest?.netCentsPerContract;
    if (typeof net !== 'number' || !Number.isFinite(net)) continue;
    out.push({ name: shortStrategy(st.name), net, t: st.backtest?.t ?? null, n: st.backtest?.n ?? null });
  }
  return out;
}

export function hasEdge(b: SavedBacktest): boolean {
  return b.net > 0 && typeof b.t === 'number' && b.t >= 2;
}

export function loadSavedBacktests(now = Date.now()): Promise<SavedBacktest[]> {
  if (cache && now - cache.at < TTL_MS) return cache.rows;
  const rows = (async () => {
    try {
      const lib = await window.krypt?.turbine?.library?.();
      return savedBacktests(lib?.strategies);
    } catch {
      return [];
    }
  })();
  cache = { at: now, rows };
  return rows;
}
