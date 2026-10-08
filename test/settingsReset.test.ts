import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TraderConfig } from '@shared/types';


let userData = '';
vi.mock('electron', () => ({ app: { getPath: () => userData } }));

async function freshStore() {
  vi.resetModules();
  return import('../electron/system/settings-store');
}

beforeEach(() => { userData = mkdtempSync(join(tmpdir(), 'krypt-reset-')); });
afterEach(() => rmSync(userData, { recursive: true, force: true }));

describe('resetBotSettings', () => {
  it('puts the strategy knobs back and keeps the user\'s own setup', async () => {
    const store = await freshStore();
    store.load();
    const sam = { ...store.DEFAULT_CONFIG.mcpAgents[0], id: 'sam', name: 'Sports Sam' };
    store.patchConfig({
      minEdgePtsWhale: 12, maxOpenPositions: 3, tradingDays: ['mon'],
      accountMode: 'live', enableTrading: true,
      mcpAgents: [...store.DEFAULT_CONFIG.mcpAgents, sam], mcpTradeMode: 'live',
      autopilotEnabled: true, autopilotAgentId: 'sam', aiProvider: 'gemini', aiModel: 'gemini-x',
      remoteTelegramChatId: '12345', remoteTradingEnabled: true,
      eventWebhookUrl: 'https://discord.com/api/webhooks/1/abc',
      terminalMaxContracts: 7, crypto15mEntryThreshold: 0.91, scriptsLiveEnabled: true,
    } as Partial<TraderConfig>);
    store.save({ ...store.get(), activeProfileId: 'p_x', activeCrypto15mProfileId: 'p_c' });

    const c = store.resetBotSettings().config;
    const d = store.DEFAULT_CONFIG;
    expect(c.minEdgePtsWhale).toBe(d.minEdgePtsWhale);
    expect(c.maxOpenPositions).toBe(d.maxOpenPositions);
    expect(c.tradingDays).toEqual(d.tradingDays);
    expect(c.accountMode).toBe('live');
    expect(c.enableTrading).toBe(true);
    expect(c.mcpAgents.map((a) => a.id)).toEqual(['default', 'sam']);
    expect(c.mcpTradeMode).toBe('live');
    expect(c.autopilotEnabled).toBe(true);
    expect(c.autopilotAgentId).toBe('sam');
    expect(c.aiProvider).toBe('gemini');
    expect(c.remoteTelegramChatId).toBe('12345');
    expect(c.remoteTradingEnabled).toBe(true);
    expect(c.eventWebhookUrl).toBe('https://discord.com/api/webhooks/1/abc');
    expect(c.terminalMaxContracts).toBe(7);
    expect(c.crypto15mEntryThreshold).toBe(0.91);
    expect(c.scriptsLiveEnabled).toBe(true);
    expect(store.get().activeProfileId).toBeNull();
    expect(store.get().activeCrypto15mProfileId).toBe('p_c');
  });

  it('remembers that the tray notice was shown, across a reload', async () => {
    let store = await freshStore();
    expect(store.load().trayHintShown).toBe(false);
    store.save({ ...store.get(), trayHintShown: true });
    store = await freshStore();
    expect(store.load().trayHintShown).toBe(true);
  });
});
