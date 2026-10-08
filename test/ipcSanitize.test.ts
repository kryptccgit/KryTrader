import { describe, expect, it } from 'vitest';
import {
  botSettingsResetPatch, cleanBacktestArgs, cleanBacktestConfig, cleanBookEnv, cleanBotRunsArgs,
  cleanC15HistoryArgs, cleanMarketUrlArgs, cleanOptimizeArgs, cleanPositionFilter, cleanScriptBacktestArgs,
  cleanScriptCode, cleanScriptId, cleanScriptSave, cleanSignalFilter, cleanSinceHours, cleanTicket,
  cleanTurbineLibraryArgs, isBotSettingKey, MAIN_EXCLUDE, removedAgentIds, SCRIPT_CODE_MAX,
} from '../electron/system/sanitize';


const KEYS = new Set([
  'minEdgePtsWhale', 'crypto15mEntryThreshold', 'crypto15mRules', 'crypto15mAssets', 'tradingDays',
  'accountMode', 'enableTrading', 'mcpTradeMode', 'autopilotEnabled', 'eventWebhookUrl',
  'crypto15mRunners', 'aiModel', 'paperBankrollUsd', 'orderStyle',
]);

describe('cleanTicket expectMode', () => {
  it('passes only the two exact words, and drops anything else', () => {
    expect(cleanTicket({ ticker: 'KXA-1', expectMode: 'paper' }).expectMode).toBe('paper');
    expect(cleanTicket({ ticker: 'KXA-1', expectMode: 'live' }).expectMode).toBe('live');
    for (const bad of ['LIVE', 'production', true, 1, null, undefined, {}]) {
      expect('expectMode' in cleanTicket({ ticker: 'KXA-1', expectMode: bad })).toBe(false);
    }
  });
});

describe('position / signal / run reads', () => {
  it('clamps the limit and keeps only real statuses, sources and books', () => {
    expect(cleanPositionFilter(undefined)).toEqual({ limit: 500 });
    expect(cleanPositionFilter({ limit: 1e9 }).limit).toBe(2000);
    expect(cleanPositionFilter({ limit: null }).limit).toBe(500);
    const f = cleanPositionFilter({
      status: ['filled', 'filled', 'nope', 7, "x' OR 1=1"], resolved: 'yes', signalSource: 'whale', env: 'paper',
    });
    expect(f).toEqual({ limit: 500, status: ['filled'], signalSource: 'whale', env: 'paper' });
    expect(cleanPositionFilter({ resolved: false }).resolved).toBe(false);
    expect('env' in cleanPositionFilter({ env: 'mainnet' })).toBe(false);
    expect('signalSource' in cleanPositionFilter({ signalSource: 'evil' })).toBe(false);
  });

  it('signals: whale/momentum only, numbers clamped', () => {
    expect(cleanSignalFilter({ limit: 99999, source: 'x', minConfidence: 500 }))
      .toEqual({ limit: 1000, minConfidence: 100 });
    expect(cleanSignalFilter({ source: 'momentum', minEdge: 'abc' })).toEqual({ limit: 200, source: 'momentum' });
  });

  it('books and runs', () => {
    expect(cleanBookEnv('PRODUCTION')).toBe('production');
    expect(cleanBookEnv('../x')).toBeNull();
    expect(cleanBotRunsArgs('demo', 5)).toEqual({ env: 'demo', limit: 5 });
    expect(cleanBotRunsArgs('nope', 1e7)).toEqual({ limit: 1000 });
    expect(cleanBotRunsArgs(null, undefined)).toEqual({});
    expect(cleanSinceHours(undefined)).toBe(168);
    expect(cleanSinceHours(1e12)).toBe(24 * 366);
    expect(cleanC15HistoryArgs({ limit: 9999, includePaper: 'yes' })).toEqual({ limit: 500, includePaper: false });
  });
});

describe('backtest config blobs', () => {
  it('keeps known, non-personal keys with primitive values', () => {
    const out = cleanBacktestConfig({
      minEdgePtsWhale: 7, crypto15mEntryThreshold: 0.8, tradingDays: ['mon', 'tue'], orderStyle: 'limit_mid',
      crypto15mRules: [{ field: 'rsi', op: '>=', value: 40 }],
    }, KEYS);
    expect(out).toEqual({
      minEdgePtsWhale: 7, crypto15mEntryThreshold: 0.8, tradingDays: ['mon', 'tue'], orderStyle: 'limit_mid',
      crypto15mRules: [{ field: 'rsi', op: '>=', value: 40 }],
    });
  });

  it('never carries the account mode, an arm switch, an agent or AI setting, a webhook, or the runner roster', () => {
    const out = cleanBacktestConfig({
      accountMode: 'live', enableTrading: true, mcpTradeMode: 'live', autopilotEnabled: true,
      eventWebhookUrl: 'https://discord.com/api/webhooks/x', crypto15mRunners: [], aiModel: 'x',
      paperBankrollUsd: 1e9,
    }, KEYS);
    expect(out).toEqual({});
  });

  it('drops unknown keys and shapes that are not config values', () => {
    const out = cleanBacktestConfig({
      unknownKey: 1, minEdgePtsWhale: { nested: { deep: 1 } }, crypto15mEntryThreshold: NaN,
      orderStyle: 'x'.repeat(5000), tradingDays: [[1]],
    }, KEYS);
    expect(out).toEqual({});
    expect(cleanBacktestConfig('nope', KEYS)).toEqual({});
    expect(cleanBacktestConfig([1, 2], KEYS)).toEqual({});
  });

  it('clamps the window', () => {
    expect(cleanBacktestArgs(undefined, KEYS)).toEqual({ sinceDays: 60 });
    expect(cleanBacktestArgs({ sinceDays: 1e6, config: { accountMode: 'live' } }, KEYS))
      .toEqual({ sinceDays: 365, config: {} });
  });
});

describe('scripts', () => {
  it('ids are script ids, code is bounded', () => {
    expect(cleanScriptId('a1b2c3d4e5f60718')).toBe('a1b2c3d4e5f60718');
    for (const bad of ['', '../x', 'a b', 'x'.repeat(65), null, 5, {}]) expect(cleanScriptId(bad)).toBe('');
    expect(cleanScriptCode('print(1)')).toBe('print(1)');
    expect(cleanScriptCode(undefined)).toBe('');
    expect(cleanScriptCode(42)).toBeNull();
    expect(cleanScriptCode('x'.repeat(SCRIPT_CODE_MAX + 1))).toBeNull();
  });

  it('save: refuses a malformed id rather than silently saving a NEW script', () => {
    expect(cleanScriptSave({ id: '../../x', code: 'a' })).toBeNull();
    expect(cleanScriptSave({ code: 'x'.repeat(SCRIPT_CODE_MAX + 1) })).toBeNull();
    const ok = cleanScriptSave({ id: 'abc', code: 'a', name: `n\u0007${'y'.repeat(300)}`, extra: 'dropped', trusted: true });
    expect(ok).toEqual({ id: 'abc', code: 'a', name: `n${'y'.repeat(119)}` });
    expect(cleanScriptSave({ code: 'a' })).toEqual({ code: 'a' });
  });

  it('backtest: either code or a script id, never neither', () => {
    expect(cleanScriptBacktestArgs({}, KEYS)).toBeNull();
    expect(cleanScriptBacktestArgs({ id: 'bad id' }, KEYS)).toBeNull();
    expect(cleanScriptBacktestArgs({ id: 'abc', sinceDays: 0 }, KEYS)).toEqual({ sinceDays: 1, id: 'abc' });
    expect(cleanScriptBacktestArgs({ code: 'x', config: { mcpTradeMode: 'live' } }, KEYS))
      .toEqual({ sinceDays: 60, code: 'x', config: {} });
  });
});

describe('turbine and the optimizer', () => {
  it('rerun only on a literal true (it costs minutes of CPU)', () => {
    expect(cleanTurbineLibraryArgs({ rerun: 'true' })).toEqual({});
    expect(cleanTurbineLibraryArgs({ rerun: 1 })).toEqual({});
    expect(cleanTurbineLibraryArgs({ rerun: true, days: 1e5 })).toEqual({ rerun: true, days: 365 });
    expect(cleanTurbineLibraryArgs(undefined)).toEqual({});
  });

  it('optimize: a coin, allowed buckets, clamped numbers', () => {
    expect(cleanOptimizeArgs({})).toBeNull();
    expect(cleanOptimizeArgs({ coin: '../BTC' })).toBeNull();
    expect(cleanOptimizeArgs({ coin: 'btc', granularityH: 5, sinceDays: -3, holdout: 'nope', env: 'paper' })).toEqual({
      coin: 'BTC', granularityH: 4, sinceDays: 1, minTrades: 12, minTradesCoin: 30, holdout: 'auto',
    });
    const o = cleanOptimizeArgs({ coin: 'ETH', granularityH: 6, holdout: 'off', strategyNames: ['a', 7, ''] });
    expect(o).toMatchObject({ granularityH: 6, holdout: 'off', strategyNames: ['a'] });
    expect('env' in (o ?? {})).toBe(false);
  });
});

describe('kalshi:marketUrl', () => {
  it('takes tickers only, never a URL', () => {
    expect(cleanMarketUrlArgs({ ticker: 'kxa-1', eventTicker: 'KXA', env: 'paper' }))
      .toEqual({ ticker: 'KXA-1', eventTicker: 'KXA', env: 'paper' });
    expect(cleanMarketUrlArgs({ ticker: 'https://evil.example/x' })).toBeNull();
    expect(cleanMarketUrlArgs({ eventTicker: 'KXA', env: 'https://x' })).toEqual({ ticker: '', eventTicker: 'KXA', env: 'production' });
    expect(cleanMarketUrlArgs(undefined)).toBeNull();
  });
});

describe('agent token pruning is only for agents the user removed', () => {
  it('names the ids that disappeared, and nothing on an add, an edit or a no-op', () => {
    const d = { id: 'default' };
    expect(removedAgentIds([d, { id: 'sam' }], [d])).toEqual(['sam']);
    expect(removedAgentIds([d], [d, { id: 'sam' }])).toEqual([]);
    expect(removedAgentIds([d, { id: 'Sam' }], [d, { id: 'sam', name: 'renamed' }])).toEqual([]);
    expect(removedAgentIds(undefined, [d])).toEqual([]);
  });
});

describe('positions env', () => {
  it("accepts 'all' and the three books; absent means the backend's default (current book)", () => {
    expect(cleanPositionFilter({ env: 'all' }).env).toBe('all');
    expect(cleanPositionFilter({ env: 'demo' }).env).toBe('demo');
    expect('env' in cleanPositionFilter({})).toBe(false);
  });
});

describe('Settings → Reset touches the bot settings only', () => {
  const defaults = {
    minEdgePtsWhale: 5, tradingDays: ['mon'], maxOpenPositions: 25,
    accountMode: 'paper', enableTrading: false, paperBankrollUsd: 1000,
    mcpAgents: [{ id: 'default' }], mcpTradeMode: 'paper', autopilotEnabled: false, autopilotAgentId: 'default',
    aiProvider: 'anthropic', aiModel: 'x', remoteDiscordUserId: '', remoteTradingEnabled: false,
    eventWebhookUrl: '', terminalMaxContracts: 1000, crypto15mEnabled: false, crypto15mEntryThreshold: 0.7,
    scriptsLiveEnabled: false, perpsFarmEnabled: false,
  };

  it('resets strategy knobs and nothing personal or armed', () => {
    const patch = botSettingsResetPatch(defaults);
    expect(Object.keys(patch).sort()).toEqual(['maxOpenPositions', 'minEdgePtsWhale', 'tradingDays']);
    expect(patch.tradingDays).not.toBe(defaults.tradingDays);
  });

  it('isBotSettingKey shares profileSlice\'s rule', () => {
    for (const k of MAIN_EXCLUDE) expect(isBotSettingKey(k)).toBe(false);
    for (const k of ['mcpAgents', 'autopilotAgentId', 'aiProvider', 'remoteTelegramChatId',
      'terminalMaxNotionalUsd', 'crypto15mLive', 'statsWebhookUrl']) {
      expect(isBotSettingKey(k)).toBe(false);
    }
    expect(isBotSettingKey('minConfidenceWhale')).toBe(true);
  });
});
