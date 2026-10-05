import { describe, expect, it } from 'vitest';
import {
  CANDLE_INTERVALS, cleanFilters, cleanTicker, cleanTicket, clampInt,
  DISCOVER_COLUMNS, filterAgentConfigPatch, nextWatchlist,
} from '../electron/system/sanitize';

describe('cleanTicker', () => {
  it('accepts and upper-cases a real ticker', () => {
    expect(cleanTicker('kxbtcd-26aug24-t90000')).toBe('KXBTCD-26AUG24-T90000');
    expect(cleanTicker('  KXA-1  ')).toBe('KXA-1');
  });

  it('rejects anything that is not a ticker', () => {
    for (const bad of [
      '', '   ', null, undefined, {}, [],
      '../../etc/passwd',
      'http://evil.example.com',
      'KXA-1; DROP TABLE',
      'KXA 1',
      'KXA\n1',
      'KX<script>',
      'a'.repeat(121),
    ]) {
      expect(cleanTicker(bad as unknown)).toBe('');
    }
  });

  it('accepts a ticker exactly at the length limit', () => {
    expect(cleanTicker('A'.repeat(120))).toHaveLength(120);
  });

  it('lets a merely-nonexistent ticker through to be refused honestly', () => {
    expect(cleanTicker(42)).toBe('42');
  });
});

describe('clampInt', () => {
  it('clamps into range and rounds', () => {
    expect(clampInt(5, 1, 10, 3)).toBe(5);
    expect(clampInt(-99, 1, 10, 3)).toBe(1);
    expect(clampInt(1e9, 1, 10, 3)).toBe(10);
    expect(clampInt('7', 1, 10, 3)).toBe(7);
    expect(clampInt(4.6, 1, 10, 3)).toBe(5);
  });

  it('falls back to the default for anything unreadable', () => {
    for (const bad of [NaN, Infinity, -Infinity, 'abc', null, undefined, {}, '']) {
      expect(clampInt(bad as unknown, 1, 10, 3)).toBe(3);
    }
  });
});

describe('cleanFilters', () => {
  it('returns null when there is nothing to filter by', () => {
    expect(cleanFilters(null)).toBeNull();
    expect(cleanFilters({})).toBeNull();
    expect(cleanFilters('nope')).toBeNull();
    expect(cleanFilters({ categories: [] })).toBeNull();
  });

  it('keeps numeric filters and clamps them to the tradeable range', () => {
    expect(cleanFilters({ minPriceCents: 0, maxPriceCents: 500 }))
      .toEqual({ minPriceCents: 1, maxPriceCents: 99 });
  });

  it('drops empty strings rather than turning them into zero', () => {
    expect(cleanFilters({ minVolume: '', maxHoursToClose: null })).toBeNull();
  });

  it('keeps only string categories and caps the list', () => {
    const out = cleanFilters({ categories: ['Sports', 42, null, 'Politics'] });
    expect(out).toEqual({ categories: ['Sports', 'Politics'] });

    const many = cleanFilters({
      categories: Array.from({ length: 100 }, (_, i) => `c${i}`),
    });
    expect((many!.categories as string[]).length).toBe(40);
  });

  it('ignores unknown keys entirely', () => {
    expect(cleanFilters({ evil: 'x', url: 'http://x', minVolume: 5 }))
      .toEqual({ minVolume: 5 });
  });
});

describe('cleanTicket', () => {
  it('normalises a well-formed ticket', () => {
    expect(cleanTicket({
      ticker: 'kxa-1', side: 'no', action: 'sell', count: '10', priceCents: 45,
    })).toEqual({
      ticker: 'KXA-1', side: 'no', action: 'sell', count: 10, priceCents: 45,
    });
  });

  it('defaults side and action rather than passing junk through', () => {
    const t = cleanTicket({ ticker: 'KXA', side: 'maybe', action: 'short' });
    expect(t.side).toBe('yes');
    expect(t.action).toBe('buy');
  });

  it('never produces a negative count', () => {
    expect(cleanTicket({ ticker: 'KXA', count: -50 }).count).toBe(0);
  });

  it('leaves an unusable price for the backend to reject, not silently zeroed', () => {
    expect(cleanTicket({ ticker: 'KXA', priceCents: 'abc' }).priceCents).toBeNaN();
  });

  it('blanks a bad ticker so the handler can refuse it', () => {
    expect(cleanTicket({ ticker: '../../x' }).ticker).toBe('');
  });
});

describe('allow-lists', () => {
  it('names exactly the columns the backend implements', () => {
    expect([...DISCOVER_COLUMNS].sort())
      .toEqual(['closing', 'new', 'trending', 'volume', 'watchlist']);
  });

  it('names exactly the candle intervals Kalshi supports', () => {
    expect([...CANDLE_INTERVALS].sort((a, b) => a - b)).toEqual([1, 60, 1440]);
  });
});

describe('nextWatchlist', () => {
  it('adds and removes without duplicating', () => {
    expect(nextWatchlist([], 'kxa-1', true)).toEqual(['KXA-1']);
    expect(nextWatchlist(['KXA-1'], 'KXA-1', true)).toEqual(['KXA-1']);
    expect(nextWatchlist(['KXA-1', 'KXB'], 'KXA-1', false)).toEqual(['KXB']);
  });

  it('ignores a ticker that is not one', () => {
    expect(nextWatchlist(['KXA'], 'http://x', true)).toEqual(['KXA']);
  });

  it('caps the list so it cannot grow without bound', () => {
    const big = Array.from({ length: 500 }, (_, i) => `KX${i}`);
    expect(nextWatchlist(big, 'KXNEW', true, 500)).toHaveLength(500);
    expect(nextWatchlist(big, 'KXNEW', true, 500)[0]).toBe('KXNEW');
  });
});

describe('filterAgentConfigPatch', () => {
  it('passes strategy and engine keys the backend already permitted', () => {
    expect(filterAgentConfigPatch({ crypto15mEntryThreshold: 0.8, enableTrading: true }))
      .toEqual({ crypto15mEntryThreshold: 0.8, enableTrading: true });
  });

  it('never lets an agent write the environment, its own rails or credentials', () => {
    const out = filterAgentConfigPatch({
      kalshiEnv: 'production', mcpTradeMode: 'live', mcpMaxOrderUsd: 1e6,
      mcpAllowLiveSwitches: true, autopilotDailyTokenBudget: 5e7,
      remoteTradingEnabled: true, aiModel: 'x', terminalMaxNotionalUsd: 1e7,
      statsWebhookUrl: 'https://x', discordBotToken: 'x', minEdgePtsWhale: 2,
    });
    expect(out).toEqual({ minEdgePtsWhale: 2 });
  });

  it('treats anything that is not a plain object as an empty patch', () => {
    expect(filterAgentConfigPatch(null)).toEqual({});
    expect(filterAgentConfigPatch(['kalshiEnv'])).toEqual({});
    expect(filterAgentConfigPatch('kalshiEnv')).toEqual({});
  });
});
