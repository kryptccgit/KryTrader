import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CredentialsStatusAll, TraderConfig } from '@shared/types';
import { migrateAccountMode, migrateConfig } from '../electron/system/legacy-settings';
import {
  filterAgentConfigPatch, isPersonalKey, omitForShare, omitPersonal, profileExportJson,
} from '../electron/system/sanitize';
import { cleanAgent, isValidAgentId as isAgentId } from '@shared/agents';
import {
  accountGoLiveChecklist, accountGoLivePatch, backToPaperAccountPatch,
} from '../src/utils/goLive';
import { bookEnvOf, isLive } from '../src/utils/account';
import { liveSwitchLines } from '../src/utils/liveEngines';


let userData = '';
vi.mock('electron', () => ({ app: { getPath: () => userData } }));

async function freshStore() {
  vi.resetModules();
  return import('../electron/system/settings-store');
}

describe('migrating a settings.json from before Paper', () => {
  beforeEach(() => { userData = mkdtempSync(join(tmpdir(), 'krypt-paper-')); });
  afterEach(() => rmSync(userData, { recursive: true, force: true }));
  const write = (state: unknown): void => {
    writeFileSync(join(userData, 'settings.json'), JSON.stringify(state), 'utf-8');
  };

  it('a demo profile lands on Paper and forgets the environment', async () => {
    write({ config: { kalshiEnv: 'demo', enableTrading: true } });
    const cfg = (await freshStore()).load().config;
    expect(cfg.accountMode).toBe('paper');
    expect(cfg.enableTrading).toBe(true);
    expect('kalshiEnv' in cfg).toBe(false);
  });

  it('a production profile lands on Live, every engine switch exactly as it was', async () => {
    write({ config: {
      kalshiEnv: 'production', enableTrading: true, crypto15mLive: true,
      scriptsLiveEnabled: true, mcpTradeMode: 'live',
    } });
    const cfg = (await freshStore()).load().config;
    expect(cfg.accountMode).toBe('live');
    expect(cfg).toMatchObject({
      enableTrading: true, crypto15mLive: true, scriptsLiveEnabled: true, mcpTradeMode: 'live',
    });
  });

  it('is idempotent: a second load, and a config that names its mode, change nothing', async () => {
    write({ config: { kalshiEnv: 'production' } });
    const store = await freshStore();
    expect(store.load().config.accountMode).toBe('live');
    store.save(store.get());
    const onDisk = JSON.parse(readFileSync(join(userData, 'settings.json'), 'utf-8'));
    expect(onDisk.config.accountMode).toBe('live');
    expect('kalshiEnv' in onDisk.config).toBe(false);
    const again = (await freshStore()).load().config;
    expect(again.accountMode).toBe('live');
    write({ config: { accountMode: 'paper', kalshiEnv: 'production' } });
    expect((await freshStore()).load().config.accountMode).toBe('paper');
  });

  it('a brand-new install starts on Paper', async () => {
    expect((await freshStore()).load().config.accountMode).toBe('paper');
  });

  it('only the stored running config may come out Live from an old kalshiEnv', () => {
    const d = { accountMode: 'paper', paperBankrollUsd: 1000 } as unknown as TraderConfig;
    expect(migrateConfig({ kalshiEnv: 'production' }, d).accountMode).toBe('paper');
    expect(migrateConfig({ kalshiEnv: 'production' }, d, { live: true }).accountMode).toBe('live');
    const src: Record<string, unknown> = { accountMode: 'LIVE' };
    migrateAccountMode(src, true);
    expect(src.accountMode).toBe('paper');
  });

  it('the agents paper bankroll becomes the one paper bankroll', () => {
    const d = { accountMode: 'paper', paperBankrollUsd: 1000 } as unknown as TraderConfig;
    const out = migrateConfig({ mcpPaperBankrollUsd: 250 }, d) as unknown as Record<string, unknown>;
    expect(out.paperBankrollUsd).toBe(250);
    expect('mcpPaperBankrollUsd' in out).toBe(false);
  });

  it('a patch with a bad accountMode is Paper, not whatever was sent', async () => {
    write({ config: { kalshiEnv: 'production' } });
    const store = await freshStore();
    store.load();
    store.patchConfig({ accountMode: 'yes please' } as unknown as Partial<TraderConfig>);
    expect(store.get().config.accountMode).toBe('paper');
  });
});

describe('profiles never carry the account mode', () => {
  const cfg = { accountMode: 'live', paperBankrollUsd: 99999, kalshiEnv: 'production', minEdgePtsWhale: 7 };

  it('is personal: never applied from, exported in or imported with a profile', () => {
    expect(isPersonalKey('accountMode')).toBe(true);
    expect(isPersonalKey('paperBankrollUsd')).toBe(true);
    expect(omitPersonal(cfg)).toEqual({ kalshiEnv: 'production', minEdgePtsWhale: 7 });
    expect(omitForShare(cfg)).toEqual({ minEdgePtsWhale: 7 });
    const exported = JSON.parse(profileExportJson({ id: 'p', name: 'P', config: cfg })).profile.config;
    expect(exported).toEqual({ minEdgePtsWhale: 7 });
  });
});

describe('agents never write the account mode or the paper bankroll', () => {
  it('drops them from an agent settings patch', () => {
    expect(filterAgentConfigPatch({
      accountMode: 'live', paperBankrollUsd: 1e9, kalshiEnv: 'production', minEdgePtsWhale: 2,
    })).toEqual({ minEdgePtsWhale: 2 });
  });

  it("'account' is the paper account's ledger owner, never an agent id", () => {
    expect(isAgentId('account')).toBe(false);
    expect(cleanAgent({ id: 'account', name: 'x' })).toBeNull();
  });
});

describe('the account Go live checklist', () => {
  const creds = (has: boolean): CredentialsStatusAll => ({
    current: 'paper',
    production: { hasApiKey: has, hasRsaKey: has, apiKeyPreview: has ? 'abcd' : '', fingerprint: has ? 'fp1' : '' },
  });
  const verified = { ok: true, message: 'ok', fingerprint: 'fp1', balanceUsd: 40 };
  const base = { config: { accountMode: 'paper' as const }, armed: [] as string[] };

  it('a no-account Paper user is blocked at the key, with where to get one', () => {
    const l = accountGoLiveChecklist({ ...base, creds: creds(false), verify: null, ack: true });
    expect(l.ready).toBe(false);
    expect(l.steps[0].state).toBe('block');
    expect(l.steps[0].detail).toMatch(/kalshi\.com/);
  });

  it('needs a verify of the current key and an explicit acknowledgement', () => {
    expect(accountGoLiveChecklist({ ...base, creds: creds(true), verify: null, ack: true }).ready).toBe(false);
    expect(accountGoLiveChecklist({ ...base, creds: creds(true), verify: verified, ack: false }).ready).toBe(false);
    expect(accountGoLiveChecklist({ ...base, creds: creds(true), verify: verified, ack: true }).ready).toBe(true);
  });

  it('names every arm that starts spending, and still lets you go live knowingly', () => {
    const cfg: Partial<TraderConfig> = {
      accountMode: 'paper', enableTrading: true, crypto15mEnabled: true, crypto15mLive: true,
      scriptsLiveEnabled: true,
    };
    const armed = liveSwitchLines(cfg);
    expect(armed).toEqual(expect.arrayContaining([
      'Main bot: auto-trading on', '15-minute crypto: Real orders (LIVE)', 'Scripts: live, Paper mode off',
    ]));
    const l = accountGoLiveChecklist({ config: cfg, creds: creds(true), verify: verified, armed, ack: true });
    expect(l.steps.find((s) => s.id === 'engines')!.state).toBe('warn');
    expect(l.ready).toBe(true);
  });

  it('writes the account mode and nothing else; Paper is always one write away', () => {
    expect(accountGoLivePatch()).toEqual({ accountMode: 'live' });
    expect(backToPaperAccountPatch()).toEqual({ accountMode: 'paper' });
  });
});

describe('reading the mode', () => {
  it('is Live only on the exact word, and scopes rows to paper or production', () => {
    expect(isLive({ accountMode: 'live' })).toBe(true);
    expect(isLive({ accountMode: 'paper' })).toBe(false);
    expect(isLive(null)).toBe(false);
    expect(bookEnvOf({ accountMode: 'live' })).toBe('production');
    expect(bookEnvOf(undefined)).toBe('paper');
  });
});
