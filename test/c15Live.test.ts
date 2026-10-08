import { describe, expect, it } from 'vitest';
import type { Crypto15mRunner, TraderConfig } from '@shared/types';
import { c15PlacesRealOrders, c15RealOrderRunners, c15WaitingLiveRunners } from '../src/utils/c15Live';


const runner = (id: string, mode: 'paper' | 'live', enabled = true): Crypto15mRunner => ({
  id, name: id, coins: ['BTC'], mode, enabled, config: {},
});

const cfg = (p: Partial<TraderConfig>): Partial<TraderConfig> => ({
  crypto15mEnabled: true, crypto15mLive: true, accountMode: 'live', crypto15mRunners: null, ...p,
});

describe('c15RealOrderRunners', () => {
  it('treats the legacy single engine as live exactly when armed with the app Live', () => {
    expect(c15RealOrderRunners(cfg({}))).toBeNull();
    expect(c15PlacesRealOrders(cfg({}))).toBe(true);
    expect(c15PlacesRealOrders(cfg({ crypto15mLive: false }))).toBe(false);
    expect(c15PlacesRealOrders(cfg({ accountMode: 'paper' }))).toBe(false);
    expect(c15PlacesRealOrders(cfg({ crypto15mEnabled: false }))).toBe(false);
  });

  it('never counts a live runner while the master switch is off', () => {
    const c = cfg({ crypto15mLive: false, crypto15mRunners: [runner('a', 'live')] });
    expect(c15PlacesRealOrders(c)).toBe(false);
    expect(c15WaitingLiveRunners(c).map((r) => r.id)).toEqual(['a']);
  });

  it('names only the enabled live runners, and is not live with only paper ones', () => {
    const c = cfg({ crypto15mRunners: [runner('a', 'live'), runner('b', 'paper'), runner('c', 'live', false)] });
    expect(c15RealOrderRunners(c)?.map((r) => r.id)).toEqual(['a']);
    expect(c15WaitingLiveRunners(c)).toEqual([]);
    expect(c15PlacesRealOrders(cfg({ crypto15mRunners: [runner('b', 'paper')] }))).toBe(false);
  });

  it('copes with no config at all', () => {
    expect(c15PlacesRealOrders(null)).toBe(false);
    expect(c15WaitingLiveRunners(undefined)).toEqual([]);
  });
});
