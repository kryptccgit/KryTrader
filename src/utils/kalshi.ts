
type LinkArgs = { ticker?: string; eventTicker?: string; env?: string };

const cache = new Map<string, Promise<string>>();

export function kalshiMarketUrl(args: LinkArgs): Promise<string> {
  const key = `${args.env ?? ''}|${args.eventTicker || args.ticker || ''}`;
  let p = cache.get(key);
  if (!p) {
    p = window.krypt.kalshi
      .marketUrl({ ticker: args.ticker, eventTicker: args.eventTicker, env: args.env })
      .then((r) => r?.url ?? '')
      .catch(() => '');
    cache.set(key, p);
  }
  return p;
}

export async function openKalshiMarket(args: LinkArgs): Promise<void> {
  const url = await kalshiMarketUrl(args);
  if (url) await window.krypt.app.openExternal(url);
}
