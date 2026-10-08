
const COINS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'HYPE', 'BNB'];

export function subject(ticker: string, title: string): string {
  const m = /^KX([A-Z]+?)(15M|D|W|-)/.exec(ticker);
  if (m && COINS.includes(m[1])) return m[1];
  let t = title.replace(/^(Will|Is|Does|Do|Can|Are)\s+(there\s+be\s+)?(the\s+|an?\s+)?/i, '').replace(/\?$/, '');
  t = t.replace(/\s+(tonight|today|this week|this month|in 20\d\d|by .*)$/i, '');
  t = t.replace(/\bthe\s+/gi, '');
  return t.length > 24 ? `${t.slice(0, 23).trimEnd()}…` : t;
}

export function cacheMeasureText(ctx: CanvasRenderingContext2D): CanvasRenderingContext2D {
  const orig = ctx.measureText.bind(ctx);
  const cache = new Map<string, TextMetrics>();
  ctx.measureText = (text: string): TextMetrics => {
    const key = `${ctx.font}\u0000${text}`;
    let m = cache.get(key);
    if (!m) {
      if (cache.size > 4000) cache.clear();
      m = orig(text);
      cache.set(key, m);
    }
    return m;
  };
  return ctx;
}
