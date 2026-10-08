import type { Crypto15mRunner, TraderConfig } from '@shared/types';

export function c15RealOrderRunners(
  config: Partial<TraderConfig> | null | undefined,
): Crypto15mRunner[] | null {
  if (!config?.crypto15mEnabled || !config.crypto15mLive || config.accountMode !== 'live') {
    return [];
  }
  const roster = (config.crypto15mRunners ?? []) as Crypto15mRunner[];
  if (roster.length === 0) return null;
  return roster.filter((r) => r.enabled && r.mode === 'live');
}

export function c15PlacesRealOrders(config: Partial<TraderConfig> | null | undefined): boolean {
  const r = c15RealOrderRunners(config);
  return r === null || r.length > 0;
}

export function c15WaitingLiveRunners(
  config: Partial<TraderConfig> | null | undefined,
): Crypto15mRunner[] {
  if (config?.crypto15mLive) return [];
  return ((config?.crypto15mRunners ?? []) as Crypto15mRunner[])
    .filter((r) => r.enabled && r.mode === 'live');
}
