import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TraderConfig } from '@shared/types';
import {
  migrateConfig, normalizeActiveProfileId, REMOVED_PRESET_IDS,
} from '../electron/system/legacy-settings';


let userData = '';
vi.mock('electron', () => ({ app: { getPath: () => userData } }));

async function freshStore() {
  vi.resetModules();
  return import('../electron/system/settings-store');
}

const SECRET_GATES = {
  minConfidenceWhale: 0,
  minConfidenceMomentum: 0,
  minEdgePtsWhale: -1000,
  minEdgePtsMomentum: -1000,
  minEntryPriceCents: 1,
  maxEntryPriceCents: 99,
  contrarianOnly: false,
};

describe('removed preset ids', () => {
  it('normalizes every removed built-in preset id to null', () => {
    for (const id of ['krypt-edge', 'krypt-sports-momentum', 'krypt-crypto-whale', 'krypt-secret']) {
      expect(REMOVED_PRESET_IDS.has(id)).toBe(true);
      expect(normalizeActiveProfileId(id)).toBeNull();
    }
  });

  it("keeps a user's own profile id, and treats junk as no selection", () => {
    expect(normalizeActiveProfileId('p_1726000000_ab12')).toBe('p_1726000000_ab12');
    for (const junk of [null, undefined, '', 0, {}, ['krypt-edge']]) {
      expect(normalizeActiveProfileId(junk)).toBeNull();
    }
  });
});

describe('migrateConfig', () => {
  let defaults: TraderConfig;
  beforeEach(async () => {
    userData = mkdtempSync(join(tmpdir(), 'krypt-legacy-'));
    defaults = (await freshStore()).DEFAULT_CONFIG;
  });
  afterEach(() => rmSync(userData, { recursive: true, force: true }));

  it('the defaults no longer carry the gambling keys at all', () => {
    expect('gamblingMode' in defaults).toBe(false);
    expect('gamblingTradeProbability' in defaults).toBe(false);
  });

  it('drops gamblingMode and gamblingTradeProbability', () => {
    const out = migrateConfig({ gamblingMode: true, gamblingTradeProbability: 1 }, defaults);
    expect('gamblingMode' in out).toBe(false);
    expect('gamblingTradeProbability' in out).toBe(false);
  });

  it("closes the gates the Secret Strategy threw open — dropping the flag alone would trade every signal", () => {
    const out = migrateConfig({ gamblingMode: true, ...SECRET_GATES }, defaults);
    expect(out.minConfidenceWhale).toBe(defaults.minConfidenceWhale);
    expect(out.minConfidenceMomentum).toBe(defaults.minConfidenceMomentum);
    expect(out.minEdgePtsWhale).toBe(defaults.minEdgePtsWhale);
    expect(out.minEdgePtsMomentum).toBe(defaults.minEdgePtsMomentum);
    expect(out.minEntryPriceCents).toBe(defaults.minEntryPriceCents);
    expect(out.maxEntryPriceCents).toBe(defaults.maxEntryPriceCents);
    expect(out.contrarianOnly).toBe(true);
  });

  it('keeps a gate the user had set stricter than the default', () => {
    const out = migrateConfig({
      gamblingMode: true, minConfidenceWhale: 80, minEdgePtsMomentum: 9, maxEntryPriceCents: 60,
    }, defaults);
    expect(out.minConfidenceWhale).toBe(80);
    expect(out.minEdgePtsMomentum).toBe(9);
    expect(out.maxEntryPriceCents).toBe(60);
  });

  it('disarms a live config that had gambling on, but never touches a profile snapshot', () => {
    expect(migrateConfig({ gamblingMode: true, enableTrading: true }, defaults, { live: true }).enableTrading)
      .toBe(false);
    expect(migrateConfig({ gamblingMode: true, enableTrading: true }, defaults).enableTrading).toBe(true);
  });

  it('changes nothing else for a config that never had gambling on', () => {
    const raw = { ...SECRET_GATES, enableTrading: true, gamblingMode: false, gamblingTradeProbability: 0.1 };
    const out = migrateConfig(raw, defaults, { live: true });
    const { gamblingMode: _g, gamblingTradeProbability: _p, ...rest } = raw;
    expect(out).toEqual({ ...defaults, ...rest });
  });
});

describe('settings-store load', () => {
  beforeEach(() => { userData = mkdtempSync(join(tmpdir(), 'krypt-legacy-')); });
  afterEach(() => rmSync(userData, { recursive: true, force: true }));

  const writeSettings = (state: unknown): void => {
    writeFileSync(join(userData, 'settings.json'), JSON.stringify(state), 'utf-8');
  };

  it('a settings.json from the Secret Strategy loads with no trace of it', async () => {
    writeSettings({
      activeProfileId: 'krypt-secret',
      config: { enableTrading: true, gamblingMode: true, gamblingTradeProbability: 0.1, ...SECRET_GATES },
      customProfiles: [{
        id: 'p_mine', name: 'Saved while gambling', kind: 'main',
        config: { gamblingMode: true, gamblingTradeProbability: 0.1, ...SECRET_GATES },
      }],
    });
    const store = await freshStore();
    const s = store.load();
    expect(s.activeProfileId).toBeNull();
    expect('gamblingMode' in s.config).toBe(false);
    expect('gamblingTradeProbability' in s.config).toBe(false);
    expect(s.config.enableTrading).toBe(false);
    expect(s.config.minEdgePtsWhale).toBe(store.DEFAULT_CONFIG.minEdgePtsWhale);
    const p = s.customProfiles[0];
    expect(p.id).toBe('p_mine');
    expect('gamblingMode' in p.config).toBe(false);
    expect(p.config.minConfidenceWhale).toBe(store.DEFAULT_CONFIG.minConfidenceWhale);
  });

  it('an applied preset id becomes no selection; the config the user was running is kept', async () => {
    writeSettings({
      activeProfileId: 'krypt-edge',
      config: {
        enableTrading: true, maxEntryPriceCents: 85,
        allowedWhaleCategories: ['crypto', 'exotics', 'entertainment'],
        allowedMomentumCategories: ['sports'],
      },
    });
    const s = (await freshStore()).load();
    expect(s.activeProfileId).toBeNull();
    expect(s.config.enableTrading).toBe(true);
    expect(s.config.allowedWhaleCategories).toEqual(['crypto', 'exotics', 'entertainment']);
  });

  it("a user's own active strategy survives the load", async () => {
    writeSettings({
      activeProfileId: 'p_mine',
      customProfiles: [{ id: 'p_mine', name: 'Mine', kind: 'main', config: {} }],
    });
    expect((await freshStore()).load().activeProfileId).toBe('p_mine');
  });

  it('a patch or replace carrying gamblingMode cannot put it back', async () => {
    writeSettings({});
    const store = await freshStore();
    store.load();
    store.patchConfig({ gamblingMode: true } as unknown as Partial<TraderConfig>);
    expect('gamblingMode' in store.get().config).toBe(false);
    store.replaceConfig({ ...store.DEFAULT_CONFIG, gamblingMode: true } as unknown as TraderConfig);
    expect('gamblingMode' in store.get().config).toBe(false);
    const onDisk = JSON.parse(readFileSync(join(userData, 'settings.json'), 'utf-8'));
    expect('gamblingMode' in onDisk.config).toBe(false);
  });
});
