import { describe, expect, it } from 'vitest';
import {
  AI_KEYED_PROVIDERS, AI_PROVIDERS, CANDLE_INTERVALS, cleanAiKeyProvider, cleanAiProvider,
  cleanApiKey, cleanFilters, cleanHealthArgs, cleanTicker, cleanTicket, clampInt,
  DISCOVER_COLUMNS, filterAgentConfigPatch, isPersonalKey, nextWatchlist, omitPersonal,
  blankWebhooks, isWebhookKey, omitForShare, profileExportJson,
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

  it('never lets an agent switch on the HTTP API', () => {
    expect(filterAgentConfigPatch({ mcpHttpEnabled: true, minEdgePtsWhale: 2 }))
      .toEqual({ minEdgePtsWhale: 2 });
  });

  it('never lets an agent switch the AI provider or model it runs on', () => {
    expect(filterAgentConfigPatch({ aiProvider: 'ollama', aiModel: 'x' })).toEqual({});
  });
});

describe('cleanHealthArgs', () => {
  it('runs the network checks only on a literal true', () => {
    expect(cleanHealthArgs({ deep: true })).toEqual({ deep: true });
  });

  it('falls to the local-only run for anything else', () => {
    for (const v of [undefined, null, 'true', 1, {}, [], { deep: 'true' }, { deep: 1 },
      [{ deep: true }], 'deep']) {
      expect(cleanHealthArgs(v)).toEqual({ deep: false });
    }
  });

  it('drops every other field, so nothing else reaches the backend', () => {
    expect(cleanHealthArgs({ deep: true, host: 'evil.example', port: 1 }))
      .toEqual({ deep: true });
  });
});

describe('AI provider ids and keys', () => {
  it('accepts exactly the six provider ids, case-insensitively', () => {
    for (const p of AI_PROVIDERS) expect(cleanAiProvider(p)).toBe(p);
    expect(cleanAiProvider(' Gemini ')).toBe('gemini');
  });

  it('rejects anything else instead of defaulting to a provider', () => {
    for (const bad of [
      '', null, undefined, {}, 'claude', 'http://127.0.0.1:11434',
      'https://openrouter.ai/api/v1', 'ollama;rm', '../anthropic',
    ]) {
      expect(cleanAiProvider(bad as unknown)).toBeNull();
    }
  });

  it('only keyed providers can have a key set', () => {
    expect(cleanAiKeyProvider('openrouter')).toBe('openrouter');
    expect(cleanAiKeyProvider('gemini')).toBe('gemini');
    expect(cleanAiKeyProvider('ollama')).toBeNull();
    expect(cleanAiKeyProvider('lmstudio')).toBeNull();
    expect(AI_KEYED_PROVIDERS).not.toContain('ollama');
  });

  it('passes a pasted key through, trimmed', () => {
    const k = 'sk-' + 'or-v1-' + 'ab'.repeat(32);
    expect(cleanApiKey(`  ${k}\n`)).toBe(k);
  });

  it('treats empty as "remove the key", but never turns a bad key into empty', () => {
    expect(cleanApiKey('')).toBe('');
    expect(cleanApiKey('   ')).toBe('');
    expect(cleanApiKey(undefined)).toBe('');
    for (const bad of ['abc\ndef', 'key with space', 'k\u0000ey', 'kéy', 'x'.repeat(401)]) {
      expect(cleanApiKey(bad)).toBeNull();
    }
  });
});

describe('profiles never carry personal or arm-switch settings', () => {
  const hostile = {
    minEdgePtsWhale: 7, maxSizeFraction: 0.05,
    mcpTradeMode: 'live', mcpLiveApproval: false, mcpHttpEnabled: true, mcpMaxOrderUsd: 9999,
    autopilotEnabled: true, remoteTradingEnabled: true, remoteDiscordUserId: '284019571203948544',
    remoteTelegramChatId: '7301948826', scriptsLiveEnabled: true, scriptsPaperMode: false,
    perpsFarmEnabled: true, terminalMaxContracts: 100000, terminalMaxNotionalUsd: 1e9,
    aiProvider: 'openrouter', aiModel: 'x',
  };

  it('keeps the strategy tuning', () => {
    expect(omitPersonal(hostile)).toEqual({ minEdgePtsWhale: 7, maxSizeFraction: 0.05 });
  });

  it('classifies every agent, remote, AI, live-switch, farmer and cap key as personal', () => {
    for (const k of Object.keys(hostile)) {
      if (k === 'minEdgePtsWhale' || k === 'maxSizeFraction') continue;
      expect(isPersonalKey(k)).toBe(true);
    }
  });

  it('leaves ordinary engine keys alone', () => {
    for (const k of ['minEdgePtsWhale', 'maxOpenPositions', 'crypto15mDirectionMode', 'stopLossOnDay']) {
      expect(isPersonalKey(k)).toBe(false);
    }
  });
});

describe('a shared profile file never carries a webhook URL', () => {
  const hook = (n: number) => `https://discord.com/api/web${'hooks'}/1234567890${n}/tok-${n}`;
  const saved = {
    id: 'p1', name: 'Mine', kind: 'main', createdAt: 'x', updatedAt: 'x',
    config: {
      minEdgePtsWhale: 7, maxOpenPositions: 4, crypto15mDirectionMode: 'model',
      eventWebhookUrl: hook(1), statsWebhookUrl: hook(2), whaleWebhookUrl: hook(3), momentumWebhookUrl: hook(4),
      enableDiscord: true, remoteDiscordUserId: '284019571203948544', remoteTelegramChatId: '7301948826',
      kalshiEnv: 'production', enableTrading: true, crypto15mEnabled: true, crypto15mLive: true,
      crypto15mRunners: [{ id: 'r', name: 'r', coins: null, mode: 'live', enabled: true, config: {} }],
      mcpTradeMode: 'live', scriptsLiveEnabled: true, perpsFarmEnabled: true,
    },
  };

  it('exports none of them, nor any personal, env or arm key', () => {
    const json = profileExportJson(saved);
    expect(json).not.toMatch(/discord\.com\/api\/webhooks/i);
    const exported = JSON.parse(json).profile.config as Record<string, unknown>;
    for (const k of Object.keys(exported)) {
      expect(k).not.toMatch(/webhook|token|secret/i);
      expect(isPersonalKey(k)).toBe(false);
    }
    for (const k of ['kalshiEnv', 'enableTrading', 'crypto15mEnabled', 'crypto15mLive', 'crypto15mRunners']) {
      expect(exported).not.toHaveProperty(k);
    }
    expect(exported).toEqual({ minEdgePtsWhale: 7, maxOpenPositions: 4, crypto15mDirectionMode: 'model' });
    expect(JSON.parse(json).profile.name).toBe('Mine');
  });

  it("imports none of them either: a stranger's file must not redirect your alerts", () => {
    const imported = omitForShare(saved.config) as Record<string, unknown>;
    expect(Object.keys(imported).filter((k) => /webhook/i.test(k))).toEqual([]);
    expect(imported).not.toHaveProperty('kalshiEnv');
    expect(imported).not.toHaveProperty('mcpTradeMode');
  });

  it('classifies any webhook-named key as personal, including ones added later', () => {
    for (const k of ['eventWebhookUrl', 'statsWebhookUrl', 'whaleWebhookUrl', 'momentumWebhookUrl', 'fillsWebhookUrl']) {
      expect(isWebhookKey(k)).toBe(true);
      expect(isPersonalKey(k)).toBe(true);
    }
    expect(isWebhookKey('minEdgePtsWhale')).toBe(false);
  });

  it('stores a saved snapshot with the URLs blanked and everything else intact', () => {
    const snap = blankWebhooks(saved.config) as Record<string, unknown>;
    expect(snap.eventWebhookUrl).toBe('');
    expect(snap.momentumWebhookUrl).toBe('');
    expect(snap.minEdgePtsWhale).toBe(7);
    expect(snap.enableDiscord).toBe(true);
    expect(saved.config.eventWebhookUrl).toBe(hook(1));
  });
});
