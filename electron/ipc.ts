import { app, BrowserWindow, clipboard, dialog, ipcMain, shell } from 'electron';
import * as os from 'node:os';
import { closeSync, existsSync, openSync, readSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type {
  ActionResult,
  AppState,
  BotPosition,
  CredentialsInput,
  CredentialsState,
  PositionFilter,
  Profile,
  ProfileKind,
  RuleCondition,
  SignalFilter,
  StrategyPreset,
  TraderConfig,
} from '../shared/types';
import { setStartWithWindows } from './system/autostart';
import { pythonBackend } from './system/python-backend';
import { getReferralUrl } from './system/referrals';
import * as store from './system/settings-store';
import { findStrategy, listStrategies } from './system/strategies';
import {
  CANDLE_INTERVALS, cleanFilters, cleanTicker, cleanTicket, clampInt,
  DISCOVER_COLUMNS, nextWatchlist,
} from './system/sanitize';


const ok = <T>(data?: T, message?: string): ActionResult<T> => ({
  ok: true,
  data,
  message,
});
const err = (message: string): ActionResult => ({ ok: false, message });

const MAIN_EXCLUDE = new Set([
  'kalshiEnv', 'enableTrading',
  'eventWebhookUrl', 'statsWebhookUrl', 'whaleWebhookUrl', 'momentumWebhookUrl',
]);
const CRYPTO_ARM_EXCLUDE = new Set(['crypto15mEnabled', 'crypto15mLive', 'crypto15mRunners']);

const PRESET_ONLY = new Set(['allowedWhaleCategories', 'allowedMomentumCategories']);

const isCrypto15mKey = (k: string): boolean => k.startsWith('crypto15m');

function profileSlice(config: TraderConfig, kind: ProfileKind): Partial<TraderConfig> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(config)) {
    const crypto = isCrypto15mKey(k);
    if (kind === 'crypto15m') {
      if (crypto && !CRYPTO_ARM_EXCLUDE.has(k)) out[k] = v;
    } else if (!crypto && !MAIN_EXCLUDE.has(k) && !PRESET_ONLY.has(k)) {
      out[k] = v;
    }
  }
  return out as Partial<TraderConfig>;
}

const STRATEGY_PRESERVE: string[] = [
  ...MAIN_EXCLUDE,
  'enableDiscord', 'statsPushInterval', 'statsChartWindowHours',
  'startBankrollUsd', 'stopLossOnDay', 'stopLossOnDayPct', 'takeProfitOnDay',
  'tradingHoursEnabled', 'tradingHoursStart', 'tradingHoursEnd',
  'tradingDays', 'tradingTimezoneOffsetMin',
  'tradeScanInterval', 'positionPollInterval', 'balancePollInterval',
  'resolutionCheckInterval', 'whaleScanInterval', 'momentumScanInterval',
  'marketRefreshInterval',
];

function applyStrategyPreset(s: StrategyPreset): AppState {
  const curCfg = store.get().config;
  const preserved: Record<string, unknown> = {};
  for (const k of STRATEGY_PRESERVE) preserved[k] = (curCfg as unknown as Record<string, unknown>)[k];
  return store.replaceConfig({
    ...s.config,
    ...profileSlice(curCfg, 'crypto15m'),
    crypto15mEnabled: curCfg.crypto15mEnabled,
    crypto15mLive: curCfg.crypto15mLive,
    ...preserved,
  } as TraderConfig);
}

function sanitizeImportedConfig(raw: unknown): Partial<TraderConfig> {
  const out: Record<string, unknown> = {};
  if (!raw || typeof raw !== 'object') return out as Partial<TraderConfig>;
  const defaults = store.DEFAULT_CONFIG as unknown as Record<string, unknown>;
  const drop = (k: string, why: string): void => {
    appendLog({
      ts: new Date().toISOString(), level: 'WARN', source: 'main',
      msg: `profile import: dropped config key "${k}" (${why})`,
    });
  };
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!(k in defaults)) { drop(k, 'unknown key'); continue; }
    if (k === 'crypto15mRules') {
      if (!Array.isArray(v)) { drop(k, 'expected an array'); continue; }
      out[k] = v
        .filter((r: any) => r && typeof r === 'object'
          && typeof r.field === 'string'
          && ['>=', '<=', '>', '<'].includes(r.op)
          && Number.isFinite(Number(r.value)))
        .map((r: any): RuleCondition => ({ field: r.field, op: r.op, value: Number(r.value) }));
      continue;
    }
    if (k === 'crypto15mHours') {
      if (v === null) { out[k] = null; continue; }
      if (Array.isArray(v)) {
        out[k] = v.filter((x) => typeof x === 'number' && x >= 0 && x <= 23);
        continue;
      }
      drop(k, 'expected an hour list'); continue;
    }
    const d = defaults[k];
    if (d === null || Array.isArray(d)) {
      if (v === null && d === null) { out[k] = null; continue; }
      if (Array.isArray(v)) { out[k] = v.filter((x) => typeof x === 'string'); continue; }
      drop(k, 'expected a string list');
      continue;
    }
    switch (typeof d) {
      case 'number': {
        if (v === null && k === 'orderExpirationSec') { out[k] = null; break; }
        const n = typeof v === 'number' ? v
          : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN;
        if (Number.isFinite(n)) out[k] = n;
        else drop(k, 'expected a number');
        break;
      }
      case 'boolean':
        if (typeof v === 'boolean') out[k] = v;
        else if (v === 'true' || v === 'false') out[k] = v === 'true';
        else drop(k, 'expected a boolean');
        break;
      case 'string':
        if (typeof v === 'string') out[k] = v;
        else drop(k, 'expected a string');
        break;
      default:
        drop(k, 'unsupported type');
        break;
    }
  }
  return out as Partial<TraderConfig>;
}

const profileKindOf = (p: Profile): ProfileKind => (p.kind === 'crypto15m' ? 'crypto15m' : 'main');

function clearActiveMarkersForPatch(patch: Partial<TraderConfig>): void {
  const keys = Object.keys(patch || {});
  const touchesMain = keys.some((k) => !isCrypto15mKey(k) && !MAIN_EXCLUDE.has(k));
  const touchesCrypto = keys.some((k) => isCrypto15mKey(k) && !CRYPTO_ARM_EXCLUDE.has(k));
  const cur = store.get();
  const next = { ...cur };
  let changed = false;
  if (touchesMain && cur.activeProfileId) { next.activeProfileId = null; changed = true; }
  if (touchesCrypto && cur.activeCrypto15mProfileId) { next.activeCrypto15mProfileId = null; changed = true; }
  if (changed) store.save(next);
}

function broadcastState(state: AppState): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send('state:changed', state);
    }
  }
}

function genId(): string {
  return `p_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e6).toString(36)}`;
}

type PushResult = 'ok' | 'not_running' | 'failed';

async function pushConfigToBackend(): Promise<PushResult> {
  if (!pythonBackend.isRunning()) return 'not_running';
  const state = store.get();
  try {
    await pythonBackend.request('setConfig', { config: state.config });
    return 'ok';
  } catch (e) {
    return 'failed';
  }
}

export function registerIpc(): void {
  ipcMain.handle('app:version', () => app.getVersion());
  ipcMain.handle('app:openExternal', async (_e, url: string) => {
    if (typeof url === 'string' && /^(https?|mailto):/i.test(url)) {
      await shell.openExternal(url);
    }
  });
  ipcMain.handle('app:showItemInFolder', async (_e, p: string) => {
    shell.showItemInFolder(p);
  });
  ipcMain.handle('app:getUserDataPath', () => app.getPath('userData'));
  ipcMain.handle('app:getReferralUrl', () => getReferralUrl());

  ipcMain.handle('state:get', () => store.get());
  ipcMain.handle('state:setStartMinimized', (_e, v: boolean) => {
    const next = store.save({ ...store.get(), startMinimized: !!v });
    broadcastState(next);
    return ok();
  });
  ipcMain.handle('state:setStartWithWindows', (_e, v: boolean) => {
    setStartWithWindows(!!v);
    const next = store.save({ ...store.get(), startWithWindows: !!v });
    broadcastState(next);
    return ok();
  });
  ipcMain.handle('state:setEnableDiscordRpc', async () => {
    return ok();
  });
  ipcMain.handle('state:acceptDisclaimer', () => {
    const next = store.save({ ...store.get(), acceptedDisclaimer: true });
    broadcastState(next);
    return ok();
  });

  ipcMain.handle('config:get', () => store.get().config);
  ipcMain.handle('config:update', async (_e, patch: Partial<TraderConfig>) => {
    store.patchConfig(patch);
    clearActiveMarkersForPatch(patch);
    const next = store.get();
    broadcastState(next);
    await pushConfigToBackend();
    return next.config;
  });
  ipcMain.handle('config:replace', async (_e, cfg: TraderConfig) => {
    store.replaceConfig(cfg);
    const next = store.save({
      ...store.get(), activeProfileId: null, activeCrypto15mProfileId: null,
    });
    broadcastState(next);
    await pushConfigToBackend();
    return next.config;
  });
  ipcMain.handle('config:reset', async () => {
    const next = store.resetConfig();
    broadcastState(next);
    await pushConfigToBackend();
    return next.config;
  });
  ipcMain.handle('config:listStrategies', () => listStrategies());
  ipcMain.handle('config:applyStrategy', async (_e, id: string) => {
    const s = findStrategy(id);
    if (!s || s.comingSoon) return store.get().config;
    const next = applyStrategyPreset(s);
    const stateNext = store.save({ ...store.get(), activeProfileId: id });
    broadcastState(stateNext);
    await pushConfigToBackend();
    return next.config;
  });

  ipcMain.handle('profiles:list', () => store.get().customProfiles);
  ipcMain.handle('profiles:save', (_e, name: string, description?: string, kind?: ProfileKind) => {
    if (!name?.trim()) return err('Profile name required');
    const cur = store.get();
    const now = new Date().toISOString();
    const pkind: ProfileKind = kind === 'crypto15m' ? 'crypto15m' : 'main';
    const profile: Profile = {
      id: genId(),
      name: name.trim(),
      description: description?.trim() || undefined,
      kind: pkind,
      createdAt: now,
      updatedAt: now,
      config: { ...cur.config },
    };
    const next = store.save({
      ...cur,
      customProfiles: [...cur.customProfiles, profile],
      ...(pkind === 'crypto15m'
        ? { activeCrypto15mProfileId: profile.id }
        : { activeProfileId: profile.id }),
    });
    broadcastState(next);
    return ok(profile, `Saved ${pkind === 'crypto15m' ? '15m crypto ' : ''}profile "${profile.name}"`);
  });
  ipcMain.handle('profiles:apply', async (_e, id: string) => {
    const cur = store.get();
    const p = cur.customProfiles.find((x) => x.id === id);
    if (!p) {
      const s = findStrategy(id);
      if (s?.comingSoon) return err(`"${s.name}" is coming soon`);
      if (s) {
        const next = applyStrategyPreset(s);
        const stateNext = store.save({ ...store.get(), activeProfileId: id });
        broadcastState(stateNext);
        await pushConfigToBackend();
        return ok(next.config, `Applied "${s.name}"`);
      }
      return err('Profile not found');
    }
    const pkind = profileKindOf(p);
    const slice = profileSlice(p.config, pkind);
    if (pkind === 'main') {
      slice.allowedWhaleCategories = null;
      slice.allowedMomentumCategories = null;
    }
    const next = store.patchConfig(slice);
    const stateNext = store.save({
      ...store.get(),
      ...(pkind === 'crypto15m'
        ? { activeCrypto15mProfileId: id }
        : { activeProfileId: id }),
    });
    broadcastState(stateNext);
    await pushConfigToBackend();
    return ok(next.config, `Applied profile "${p.name}"`);
  });
  ipcMain.handle('profiles:rename', (_e, id: string, name: string) => {
    if (!name?.trim()) return err('Name required');
    const cur = store.get();
    const idx = cur.customProfiles.findIndex((p) => p.id === id);
    if (idx < 0) return err('Profile not found');
    const updated = [...cur.customProfiles];
    updated[idx] = { ...updated[idx], name: name.trim(), updatedAt: new Date().toISOString() };
    const next = store.save({ ...cur, customProfiles: updated });
    broadcastState(next);
    return ok();
  });
  ipcMain.handle('profiles:update', (_e, id: string) => {
    const cur = store.get();
    const idx = cur.customProfiles.findIndex((p) => p.id === id);
    if (idx < 0) return err('Profile not found');
    const updated = [...cur.customProfiles];
    updated[idx] = {
      ...updated[idx],
      config: { ...cur.config },
      updatedAt: new Date().toISOString(),
    };
    const next = store.save({ ...cur, customProfiles: updated });
    broadcastState(next);
    return ok(updated[idx]);
  });
  ipcMain.handle('profiles:delete', (_e, id: string) => {
    const cur = store.get();
    const next = store.save({
      ...cur,
      customProfiles: cur.customProfiles.filter((p) => p.id !== id),
      activeProfileId: cur.activeProfileId === id ? null : cur.activeProfileId,
      activeCrypto15mProfileId:
        cur.activeCrypto15mProfileId === id ? null : cur.activeCrypto15mProfileId,
    });
    broadcastState(next);
    return ok();
  });
  ipcMain.handle('profiles:duplicate', (_e, id: string) => {
    const cur = store.get();
    const orig = cur.customProfiles.find((p) => p.id === id);
    if (!orig) return err('Profile not found');
    const dup: Profile = {
      ...orig,
      id: genId(),
      name: `${orig.name} (copy)`,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    const next = store.save({
      ...cur,
      customProfiles: [...cur.customProfiles, dup],
    });
    broadcastState(next);
    return ok(dup);
  });
  ipcMain.handle('profiles:export', (_e, id: string) => {
    const cur = store.get();
    const p = cur.customProfiles.find((x) => x.id === id);
    if (!p) return err('Profile not found');
    const json = JSON.stringify(
      { kryptTraderProfile: 1, profile: p },
      null,
      2,
    );
    return ok(json);
  });
  ipcMain.handle('profiles:import', (_e, json: string) => {
    try {
      const parsed = JSON.parse(json);
      if (!parsed?.profile?.config || typeof parsed.profile.config !== 'object') {
        return err('Not a Krypt Trader profile');
      }
      const cur = store.get();
      const p = parsed.profile as Profile;
      const now = new Date().toISOString();
      const dup: Profile = {
        id: genId(),
        name: typeof p.name === 'string' && p.name.trim() ? p.name.trim() : 'Imported profile',
        description: typeof p.description === 'string' ? p.description : undefined,
        kind: p.kind === 'crypto15m' ? 'crypto15m' : 'main',
        createdAt: now,
        updatedAt: now,
        config: { ...store.DEFAULT_CONFIG, ...sanitizeImportedConfig(p.config) },
      };
      const next = store.save({ ...cur, customProfiles: [...cur.customProfiles, dup] });
      broadcastState(next);
      return ok(dup, `Imported "${dup.name}"`);
    } catch (e: any) {
      return err(`Invalid profile JSON: ${e?.message || e}`);
    }
  });

  const emptyAllCreds = () => ({
    current: 'demo' as const,
    demo: { env: 'demo' as const, hasApiKey: false, hasRsaKey: false, apiKeyPreview: '', fingerprint: '' },
    production: { env: 'production' as const, hasApiKey: false, hasRsaKey: false, apiKeyPreview: '', fingerprint: '' },
  });
  ipcMain.handle('credentials:status', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        hasApiKey: false,
        hasRsaKey: false,
        apiKeyPreview: '',
        fingerprint: '',
      } satisfies CredentialsState;
    }
    const all = await pythonBackend.request('credentialStatus', {}) as any;
    if (all && all.current && all[all.current]) {
      return all[all.current] as CredentialsState;
    }
    return all as CredentialsState;
  });
  ipcMain.handle('credentials:statusAll', async () => {
    if (!pythonBackend.isRunning()) return emptyAllCreds();
    return await pythonBackend.request('credentialStatus', {});
  });
  ipcMain.handle('credentials:save', async (_e, input: CredentialsInput) => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      await pythonBackend.request('setCredentials', input);
      return ok();
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });
  ipcMain.handle('credentials:test', async (_e, env?: string) => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('testCredentials', env ? { env } : {});
      return ok(data, 'Connected to Kalshi');
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });
  ipcMain.handle('credentials:clear', async (_e, env?: string) => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      await pythonBackend.request('clearCredentials', env ? { env } : {});
      return ok();
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });

  ipcMain.handle('backend:info', () => pythonBackend.info());
  ipcMain.handle('backend:start', async () => {
    await pythonBackend.start();
    return ok();
  });
  ipcMain.handle('backend:stop', async () => {
    await pythonBackend.stop();
    return ok();
  });
  ipcMain.handle('backend:restart', async () => {
    await pythonBackend.restart();
    return ok();
  });
  ipcMain.handle('backend:runOnce', async (_e, action: string) => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('runOnce', { action });
      return ok(data, (data as any)?.summary || 'Done');
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });

  ipcMain.handle('trading:setEnabled', async (_e, enabled: boolean) => {
    const next = store.patchConfig({ enableTrading: !!enabled });
    broadcastState(next);
    const push = await pushConfigToBackend();
    if (push === 'failed') {
      return err(
        `Setting saved, but the backend did not confirm it — the engine may still be ${enabled ? 'stopped' : 'trading'}. Restart the backend to re-sync.`,
      );
    }
    if (push === 'not_running') {
      return ok(undefined, 'Backend not running — setting saved and will apply when it starts');
    }
    return ok();
  });
  ipcMain.handle('trading:cancelAllOpen', async () => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('cancelAllOpen', {});
      return ok(data, `Canceled ${data.canceled} order(s)`);
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });
  ipcMain.handle('trading:flatten', async () => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('flatten', {});
      return ok(data, `Flattened ${data.closed} order(s)`);
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });

  ipcMain.handle('app:factoryReset', async () => {
    if (!pythonBackend.isRunning()) return err('Backend not running');
    try {
      const data = await pythonBackend.request('factoryReset', {}) as any;
      const total = Object.values(data?.deleted || {}).reduce(
        (a: number, b: any) => a + (Number(b) || 0), 0,
      );
      return ok(data, `Cleared ${total} row(s)`);
    } catch (e: any) {
      return err(`${e?.message || e}`);
    }
  });

  ipcMain.handle('data:account', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        cashUsd: 0, portfolioUsd: 0, totalUsd: 0,
        startBankrollUsd: store.get().config.startBankrollUsd,
        roiPct: 0, realizedPnlUsd: 0, unrealizedPnlUsd: 0,
        openCostUsd: 0, feesUsd: 0, wins: 0, losses: 0, winRate: 0,
        pendingCount: 0, openCount: 0, resolvedCount: 0, totalOpened: 0,
        byEnv: {
          demo: { wins: 0, losses: 0, realizedPnl: 0 },
          production: { wins: 0, losses: 0, realizedPnl: 0 },
        },
      };
    }
    return await pythonBackend.request('account', {});
  });
  ipcMain.handle('data:pnlSeries', async (_e, sinceHours?: number) => {
    if (!pythonBackend.isRunning()) return [];
    return await pythonBackend.request('pnlSeries', { sinceHours });
  });
  ipcMain.handle('data:positions', async (_e, filter?: PositionFilter) => {
    if (!pythonBackend.isRunning()) return [];
    return await pythonBackend.request('positions', filter || {});
  });
  ipcMain.handle('data:signals', async (_e, filter?: SignalFilter) => {
    if (!pythonBackend.isRunning()) return [];
    return await pythonBackend.request('signals', filter || {});
  });
  ipcMain.handle('data:scannerStats', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        whales: { total: 0, sent: 0, resolved: 0, winRate: 0 },
        momentum: { total: 0, sent: 0, resolved: 0, winRate: 0 },
        marketsTracked: 0,
        lastWhaleScanAt: null,
        lastMomentumScanAt: null,
        lastTradeScanAt: null,
      };
    }
    return await pythonBackend.request('scannerStats', {});
  });
  ipcMain.handle('data:botRuns', async (_e, env?: string | null, limit?: number) => {
    if (!pythonBackend.isRunning()) {
      return { runs: [], activeRunId: 0, activeRun: null };
    }
    const params: Record<string, unknown> = {};
    if (env) params.env = env;
    if (limit) params.limit = limit;
    return await pythonBackend.request('botRuns', params);
  });

  ipcMain.handle('crypto15m:snapshot', async () => {
    if (!pythonBackend.isRunning()) {
      return {
        fetchedAt: new Date().toISOString(),
        spotOk: false,
        spotSource: 'unavailable',
        constants: {
          timeDelayMin: 8, entryThreshold: 0.95, entryMax: 0.98,
          exitThreshold: 0.4, minDeltaPct: 0, entryDiff: 0.02, directionMode: 'favorite',
          entryStyle: 'maker', hoursStartUtc: 0, hoursEndUtc: 24,
        },
        assets: [],
      };
    }
    return await pythonBackend.request('crypto15m', {});
  });
  ipcMain.handle('crypto15m:edgeHealth', async () => {
    if (!pythonBackend.isRunning()) return null;
    try {
      return await pythonBackend.request('edgeHealth', {});
    } catch {
      return null;
    }
  });
  ipcMain.handle('crypto15m:status', async () => {
    if (!pythonBackend.isRunning()) {
      const cfg = store.get().config;
      return {
        enabled: false, live: false, liveArmed: false, authed: false,
        orderSize: cfg.crypto15mOrderSize ?? 1,
        maxConcurrent: cfg.crypto15mMaxConcurrent ?? 3,
        env: 'demo',
        sizing: {
          mode: 'fixed', balancePct: 0.02, maxLossPct: 0, balanceUsd: 0,
          estPriceCents: 0, estContracts: 1, estCostUsd: 0, note: '',
        },
        stats: { openCount: 0, wins: 0, losses: 0, realizedPnlUsd: 0, total: 0 },
        open: [], recent: [],
      };
    }
    return await pythonBackend.request('crypto15mStatus', {});
  });
  ipcMain.handle('crypto15m:backtest', async (_e, args?: { sinceDays?: number }) => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('c15Backtest', args || {});
  });
  ipcMain.handle('main:backtest', async (_e, args?: { sinceDays?: number; config?: Record<string, unknown> }) => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('mainBacktest', args || {});
  });
  ipcMain.handle('crypto15m:history', async (_e, args?: { limit?: number; includePaper?: boolean }) => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('c15History', args || {});
  });

  ipcMain.handle('scripts:list', async () => {
    if (!pythonBackend.isRunning()) return { scripts: [] };
    return await pythonBackend.request('scriptsList', {});
  });
  ipcMain.handle('scripts:save', async (_e, s: Record<string, unknown>) => {
    return await pythonBackend.request('scriptSave', s || {});
  });
  ipcMain.handle('scripts:delete', async (_e, id: string) => {
    return await pythonBackend.request('scriptDelete', { id });
  });
  ipcMain.handle('scripts:setEnabled', async (_e, id: string, enabled: boolean) => {
    return await pythonBackend.request('scriptSetEnabled', { id, enabled });
  });
  ipcMain.handle('scripts:setTrusted', async (_e, id: string, trusted: boolean) => {
    return await pythonBackend.request('scriptSetTrusted', { id, trusted });
  });
  ipcMain.handle('scripts:validate', async (_e, code: string, trusted?: boolean) => {
    return await pythonBackend.request('scriptValidate', { code, trusted: !!trusted });
  });
  ipcMain.handle('scripts:backtest', async (_e, args?: Record<string, unknown>) => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('scriptBacktest', args || {}, 120_000);
  });
  ipcMain.handle('scripts:contextPack', async () => {
    return await pythonBackend.request('scriptContextPack', {}, 60_000);
  });
  ipcMain.handle('scripts:docs', async () => {
    return await pythonBackend.request('scriptApiDocs', {}, 60_000);
  });
  ipcMain.handle('scripts:exportPack', async (e) => {
    if (!pythonBackend.isRunning()) return err('Engine not running');
    const r = (await pythonBackend.request('scriptContextPack', {})) as { text?: string } | null;
    if (!r?.text) return err('Context pack generation failed');
    const win = BrowserWindow.fromWebContents(e.sender) ?? undefined;
    const res = await dialog.showSaveDialog(win!, {
      title: 'Save AI context pack',
      defaultPath: join(app.getPath('documents'), 'krypt-ai-context-pack.txt'),
      filters: [{ name: 'Text file', extensions: ['txt'] }],
    });
    if (res.canceled || !res.filePath) return err('canceled');
    writeFileSync(res.filePath, r.text, 'utf-8');
    shell.showItemInFolder(res.filePath);
    return ok(res.filePath);
  });

  ipcMain.handle('turbine:library', async (_e, args?: { rerun?: boolean; days?: number }) => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('turbineLibrary', args || {});
  });

  ipcMain.handle('turbine:optimize', async (_e, args: Record<string, unknown>) => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('coinOptimize', args || {}, 120_000);
  });
  ipcMain.handle('backtest:export', async () => {
    if (!pythonBackend.isRunning()) return null;
    const r = await pythonBackend.request('exportResearch', {}) as { dir?: string } | null;
    if (r?.dir) shell.showItemInFolder(r.dir);
    return r;
  });
  ipcMain.handle('backtest:collection', async () => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('collectionStats', {});
  });
  ipcMain.handle('perps:status', async () => {
    if (!pythonBackend.isRunning()) return null;
    try {
      return await pythonBackend.request('perpsStatus', {});
    } catch {
      return null;
    }
  });
  ipcMain.handle('perps:farmFlatten', async () => {
    if (!pythonBackend.isRunning()) return null;
    return await pythonBackend.request('perpsFarmFlatten', {});
  });
  ipcMain.handle('trading:status', async () => {
    if (!pythonBackend.isRunning()) return null;
    try {
      return await pythonBackend.request('tradingStatus', {});
    } catch {
      return null;
    }
  });
  ipcMain.handle(
    'kalshi:marketUrl',
    async (_e, args?: { eventTicker?: string; ticker?: string; env?: string }) => {
      if (!pythonBackend.isRunning()) return { url: '' };
      return await pythonBackend.request('kalshiMarketUrl', args || {});
    },
  );

  registerTerminalIpc();
  ipcMain.handle('logs:tail', async (_e, _limit?: number) => {
    return logsBuffer.slice(-1 * (_limit || 500));
  });
  ipcMain.handle('logs:clear', () => {
    logsBuffer.length = 0;
    return ok();
  });
  ipcMain.handle('logs:diagnostics', async (_e, args?: { lines?: number }) => {
    const text = buildDiagnostics(clampInt(args?.lines, 0, 2000, 300));
    clipboard.writeText(text);
    appendLog({
      ts: new Date().toISOString(), level: 'INFO', source: 'main',
      msg: 'diagnostics copied to the clipboard',
    });
    return ok({ chars: text.length }, 'Diagnostics copied to your clipboard.');
  });

  ipcMain.handle('logs:openFolder', async () => {
    const p = join(app.getPath('userData'), 'logs');
    if (existsSync(p)) shell.openPath(p);
  });

  ipcMain.on('window:minimize', (e) => {
    BrowserWindow.fromWebContents(e.sender)?.minimize();
  });
  ipcMain.on('window:maximize', (e) => {
    const w = BrowserWindow.fromWebContents(e.sender);
    if (!w) return;
    if (w.isMaximized()) w.unmaximize();
    else w.maximize();
  });
  ipcMain.on('window:close', (e) => {
    BrowserWindow.fromWebContents(e.sender)?.close();
  });
  ipcMain.handle('window:isMaximized', (e) => {
    return BrowserWindow.fromWebContents(e.sender)?.isMaximized() ?? false;
  });
}

const backendDown = (what: string): never => {
  throw new Error(
    `The trading backend is not running, so ${what} cannot be read. ` +
    'Start it from the Logs page, or check API Keys.',
  );
};

function readWatchlist(): string[] {
  return store.get().terminalWatchlist ?? [];
}

function registerTerminalIpc(): void {
  ipcMain.handle('terminal:discover', async (_e, args?: {
    column?: string; limit?: number; refresh?: boolean; filters?: unknown;
  }) => {
    if (!pythonBackend.isRunning()) backendDown('markets');
    const column = DISCOVER_COLUMNS.has(String(args?.column))
      ? String(args?.column) : 'trending';
    return await pythonBackend.request('terminalDiscover', {
      column,
      limit: clampInt(args?.limit, 1, 250, 60),
      refresh: !!args?.refresh,
      watchlist: column === 'watchlist' ? readWatchlist() : [],
      filters: cleanFilters(args?.filters),
    }, 45_000);
  });

  ipcMain.handle('terminal:search', async (_e, args?: { query?: string; limit?: number }) => {
    if (!pythonBackend.isRunning()) backendDown('markets');
    return await pythonBackend.request('terminalSearch', {
      query: String(args?.query ?? '').slice(0, 200),
      limit: clampInt(args?.limit, 1, 250, 60),
    }, 45_000);
  });

  ipcMain.handle('terminal:market', async (_e, args?: { ticker?: string }) => {
    if (!pythonBackend.isRunning()) backendDown('this market');
    const ticker = cleanTicker(args?.ticker);
    if (!ticker) throw new Error('That is not a Kalshi ticker.');
    return await pythonBackend.request('terminalMarket', { ticker }, 45_000);
  });

  ipcMain.handle('terminal:book', async (_e, args?: { ticker?: string }) => {
    if (!pythonBackend.isRunning()) backendDown('the order book');
    const ticker = cleanTicker(args?.ticker);
    if (!ticker) throw new Error('That is not a Kalshi ticker.');
    return await pythonBackend.request('terminalBook', { ticker }, 20_000);
  });

  ipcMain.handle('terminal:candles', async (_e, args?: {
    ticker?: string; intervalMin?: number; lookbackMin?: number;
  }) => {
    if (!pythonBackend.isRunning()) backendDown('price history');
    const ticker = cleanTicker(args?.ticker);
    if (!ticker) throw new Error('That is not a Kalshi ticker.');
    const intervalMin = CANDLE_INTERVALS.has(Number(args?.intervalMin))
      ? Number(args?.intervalMin) : 1;
    return await pythonBackend.request('terminalCandles', {
      ticker,
      intervalMin,
      lookbackMin: clampInt(args?.lookbackMin, intervalMin, 60 * 24 * 90, 240),
    }, 30_000);
  });

  ipcMain.handle('terminal:tape', async (_e, args?: { ticker?: string; limit?: number }) => {
    if (!pythonBackend.isRunning()) backendDown('the trade tape');
    const ticker = cleanTicker(args?.ticker);
    if (!ticker) throw new Error('That is not a Kalshi ticker.');
    return await pythonBackend.request('terminalTape', {
      ticker, limit: clampInt(args?.limit, 1, 200, 50),
    }, 20_000);
  });

  ipcMain.handle('terminal:portfolio', async () => {
    if (!pythonBackend.isRunning()) backendDown('your positions');
    return await pythonBackend.request('terminalPortfolio', {}, 30_000);
  });

  ipcMain.handle('terminal:orders', async () => {
    if (!pythonBackend.isRunning()) backendDown('your resting orders');
    return await pythonBackend.request('terminalOrders', {}, 30_000);
  });

  ipcMain.handle('terminal:history', async (_e, args?: { limit?: number }) => {
    if (!pythonBackend.isRunning()) backendDown('your trade history');
    return await pythonBackend.request('terminalHistory', {
      limit: clampInt(args?.limit, 1, 2000, 300),
    }, 30_000);
  });

  ipcMain.handle('terminal:rules', async (_e, args?: { limit?: number }) => {
    if (!pythonBackend.isRunning()) backendDown('your standing instructions');
    return await pythonBackend.request('terminalRules', {
      limit: clampInt(args?.limit, 1, 1000, 300),
    }, 20_000);
  });

  ipcMain.handle('terminal:armRule', async (_e, req?: any) => {
    if (!pythonBackend.isRunning()) backendDown('standing instructions');
    const ticker = cleanTicker(req?.ticker);
    if (!ticker) throw new Error('That is not a Kalshi ticker.');
    const kind = ['stop', 'take', 'alert'].includes(String(req?.kind))
      ? String(req.kind) : 'alert';
    const res = await pythonBackend.request<any>('terminalRuleCreate', {
      kind,
      ticker,
      side: req?.side === 'no' ? 'no' : 'yes',
      thresholdCents: Number(req?.thresholdCents),
      direction: req?.direction === 'above' ? 'above'
        : req?.direction === 'below' ? 'below' : undefined,
      contracts: req?.contracts == null ? null
        : clampInt(req.contracts, 1, 1_000_000, 1),
      note: String(req?.note ?? '').slice(0, 200),
    }, 20_000);
    appendLog({
      ts: new Date().toISOString(), level: 'INFO', source: 'terminal',
      msg: `armed ${kind} on ${ticker} ${res?.side ?? ''} `
         + `${res?.direction ?? ''} ${res?.thresholdCents ?? '?'}c`,
    });
    return res;
  });

  ipcMain.handle('terminal:cancelRule', async (_e, args?: { id?: number }) => {
    if (!pythonBackend.isRunning()) backendDown('standing instructions');
    return await pythonBackend.request('terminalRuleCancel', {
      id: clampInt(args?.id, 1, 1e12, 0),
    }, 20_000);
  });

  ipcMain.handle('terminal:micro', async (_e, args?: {
    ticker?: string; probeCents?: number;
  }) => {
    if (!pythonBackend.isRunning()) backendDown('the microstructure recorder');
    const ticker = cleanTicker(args?.ticker);
    if (!ticker) throw new Error('That is not a Kalshi ticker.');
    const probe = Number(args?.probeCents);
    return await pythonBackend.request('terminalMicro', {
      ticker,
      probeCents: Number.isFinite(probe) ? Math.min(99, Math.max(1, probe)) : null,
    }, 20_000);
  });

  ipcMain.handle('terminal:crossVenue', async (_e, args?: { ticker?: string }) => {
    if (!pythonBackend.isRunning()) backendDown('the other venue');
    const ticker = cleanTicker(args?.ticker);
    if (!ticker) throw new Error('That is not a Kalshi ticker.');
    return await pythonBackend.request('crossVenue', { ticker }, 45_000);
  });

  ipcMain.handle('remote:status', async () => {
    if (!pythonBackend.isRunning()) backendDown('the remote bots');
    return await pythonBackend.request('remoteStatus', {}, 20_000);
  });

  ipcMain.handle('remote:setToken', async (_e, args?: {
    which?: string; token?: string;
  }) => {
    if (!pythonBackend.isRunning()) backendDown('the remote bots');
    const which = args?.which === 'telegram' ? 'telegram' : 'discord';
    const res = await pythonBackend.request('remoteSetToken', {
      which, token: String(args?.token ?? '').trim().slice(0, 400),
    }, 20_000);
    appendLog({
      ts: new Date().toISOString(), level: 'INFO', source: 'remote',
      msg: `${which} bot token ${args?.token ? 'saved' : 'cleared'}`,
    });
    return res;
  });

  ipcMain.handle('remote:pairCode', async () => {
    if (!pythonBackend.isRunning()) backendDown('the remote bots');
    return await pythonBackend.request('remotePairCode', {}, 20_000);
  });

  ipcMain.handle('remote:unpair', async (_e, args?: { which?: string }) => {
    if (!pythonBackend.isRunning()) backendDown('the remote bots');
    const which = args?.which === 'telegram' ? 'telegram' : 'discord';
    const res = await pythonBackend.request('remoteUnpair', { which }, 20_000);
    const patch = which === 'telegram'
      ? { remoteTelegramChatId: '', remoteTelegramEnabled: false }
      : { remoteDiscordUserId: '', remoteDiscordEnabled: false };
    broadcastState(store.patchConfig(patch as never));
    await pushConfigToBackend();
    return res;
  });

  ipcMain.handle('remote:test', async () => {
    if (!pythonBackend.isRunning()) backendDown('the remote bots');
    return await pythonBackend.request('remoteTest', {}, 30_000);
  });

  ipcMain.handle('ai:status', async () => {
    if (!pythonBackend.isRunning()) backendDown('AI analysis');
    return await pythonBackend.request('aiStatus', {}, 20_000);
  });

  ipcMain.handle('ai:setKey', async (_e, args?: { provider?: string; key?: string }) => {
    if (!pythonBackend.isRunning()) backendDown('AI analysis');
    const provider = args?.provider === 'openai' ? 'openai' : 'anthropic';
    const res = await pythonBackend.request('aiSetKey', {
      provider, key: String(args?.key ?? '').trim().slice(0, 400),
    }, 20_000);
    appendLog({
      ts: new Date().toISOString(), level: 'INFO', source: 'app',
      msg: `${provider} API key ${args?.key ? 'saved' : 'cleared'}`,
    });
    return res;
  });

  ipcMain.handle('ai:analyze', async (_e, args?: { ticker?: string }) => {
    if (!pythonBackend.isRunning()) backendDown('AI analysis');
    const ticker = cleanTicker(args?.ticker);
    if (!ticker) throw new Error('That is not a Kalshi ticker.');
    return await pythonBackend.request('aiAnalyze', { ticker }, 260_000);
  });

  ipcMain.handle('terminal:hosts', async () => {
    if (!pythonBackend.isRunning()) backendDown('the network report');
    return await pythonBackend.request('terminalHosts', {}, 20_000);
  });

  ipcMain.handle('ai:scoreboard', async () => {
    if (!pythonBackend.isRunning()) backendDown('the forecast scoreboard');
    return await pythonBackend.request('aiScoreboard', {}, 20_000);
  });

  ipcMain.handle('mcp:status', async () => {
    if (!pythonBackend.isRunning()) backendDown('AI agents');
    return await pythonBackend.request('mcpStatus', {}, 20_000);
  });
  ipcMain.handle('mcp:rotateToken', async () => {
    if (!pythonBackend.isRunning()) backendDown('AI agents');
    return await pythonBackend.request('mcpRotateToken', {}, 20_000);
  });
  ipcMain.handle('mcp:copyConfig', async (_e, args?: { client?: string }) => {
    if (!pythonBackend.isRunning()) backendDown('AI agents');
    const allowed = ['cursor', 'claude-code', 'claude-desktop', 'codex'];
    const client = allowed.includes(String(args?.client)) ? String(args?.client) : null;
    if (!client) throw new Error('Unknown MCP client.');
    const res = await pythonBackend.request<{ text: string }>(
      'mcpClientConfig', { client }, 20_000);
    clipboard.writeText(res.text);
    return { ok: true };
  });
  ipcMain.handle('mcp:activity', async (_e, args?: { limit?: number }) => {
    if (!pythonBackend.isRunning()) backendDown('AI agents');
    const limit = Math.min(500, Math.max(1, Math.floor(Number(args?.limit) || 100)));
    return await pythonBackend.request('mcpActivity', { limit }, 30_000);
  });
  ipcMain.handle('autopilot:status', async () => {
    if (!pythonBackend.isRunning()) backendDown('Autopilot');
    return await pythonBackend.request('autopilotStatus', {}, 20_000);
  });
  ipcMain.handle('autopilot:runNow', async () => {
    if (!pythonBackend.isRunning()) backendDown('Autopilot');
    return await pythonBackend.request('autopilotRunNow', {}, 20_000);
  });
  ipcMain.handle('mcp:decide', async (_e, args?: { id?: number; approve?: boolean }) => {
    if (!pythonBackend.isRunning()) backendDown('AI agents');
    const id = Math.floor(Number(args?.id));
    if (!Number.isFinite(id) || id <= 0) throw new Error('No such agent order.');
    return await pythonBackend.request('mcpDecide', { id, approve: args?.approve === true }, 60_000);
  });
  ipcMain.handle('mcp:paperReset', async () => {
    if (!pythonBackend.isRunning()) backendDown('AI agents');
    return await pythonBackend.request('mcpPaperReset', {}, 20_000);
  });

  const ticket = cleanTicket;

  ipcMain.handle('terminal:preview', async (_e, req?: unknown) => {
    if (!pythonBackend.isRunning()) backendDown('this order');
    return await pythonBackend.request('terminalPreview', ticket(req), 20_000);
  });

  ipcMain.handle('terminal:submit', async (_e, req?: unknown) => {
    if (!pythonBackend.isRunning()) backendDown('this order');
    const t = ticket(req);
    if (!t.ticker) throw new Error('That is not a Kalshi ticker.');
    const res = await pythonBackend.request<any>('terminalSubmit', t, 45_000);
    appendLog({
      ts: new Date().toISOString(),
      level: res?.ok ? 'INFO' : 'WARN',
      source: 'terminal',
      msg: `manual ${t.action} ${t.count} ${t.side.toUpperCase()} ` +
           `${t.ticker} @ ${t.priceCents}c — ${res?.message ?? 'no response'}`,
    });
    return res;
  });

  ipcMain.handle('shard:transfer', async (_e, args?: unknown) => {
    if (!pythonBackend.isRunning()) backendDown('this transfer');
    const a = (args ?? {}) as Record<string, unknown>;
    const payload = {
      amountUsd: Number(a.amountUsd),
      fromShard: clampInt(a.fromShard, 0, 100, 0),
      toShard: clampInt(a.toShard, 0, 100, 0),
    };
    if (!Number.isFinite(payload.amountUsd) || payload.amountUsd <= 0) {
      throw new Error('Enter an amount greater than $0.00.');
    }
    const res = await pythonBackend.request<any>('shardTransfer', payload, 30_000);
    appendLog({
      ts: new Date().toISOString(),
      level: res?.ok ? 'INFO' : 'WARN',
      source: 'terminal',
      msg: `shard transfer $${payload.amountUsd.toFixed(2)} ` +
           `${payload.fromShard} -> ${payload.toShard} — ${res?.message ?? 'no response'}`,
    });
    return res;
  });
  ipcMain.handle('terminal:cancel', async (_e, args?: { orderId?: string }) => {
    if (!pythonBackend.isRunning()) backendDown('this order');
    const orderId = String(args?.orderId ?? '').trim().slice(0, 128);
    if (!orderId) throw new Error('No order id.');
    return await pythonBackend.request('terminalCancel', { orderId }, 20_000);
  });

  ipcMain.handle('terminal:watchlist', () => readWatchlist());

  ipcMain.handle('terminal:setWatched', (_e, args?: { ticker?: string; watched?: boolean }) => {
    const ticker = cleanTicker(args?.ticker);
    if (!ticker) return readWatchlist();
    const next = nextWatchlist(readWatchlist(), ticker, !!args?.watched);
    const state = store.save({ ...store.get(), terminalWatchlist: next });
    broadcastState(state);
    return next;
  });
}

const DIAGNOSTIC_CONFIG_KEYS = [
  'kalshiEnv', 'enableTrading',
  'tradeWhales', 'tradeMomentum', 'tradeConvergence',
  'minEdgePtsWhale', 'minEdgePtsMomentum', 'minConfidenceWhale',
  'minConfidenceMomentum', 'sizingMode', 'fixedTradeUsd', 'baseSizeFraction',
  'maxOpenPositions', 'maxDailyNewPositions', 'orderStyle',
  'orderExpirationSec', 'stopLossOnDay', 'stopLossOnDayPct',
  'crypto15mEnabled', 'crypto15mLive', 'scriptsLiveEnabled',
  'terminalMaxContracts', 'terminalMaxNotionalUsd',
  'remoteDiscordEnabled', 'remoteTelegramEnabled', 'remoteTradingEnabled',
  'remoteAlertsEnabled',
  'aiProvider', 'aiModel', 'aiWebSearch',
  'mcpEnabled', 'mcpPort', 'mcpTradeMode', 'mcpMaxOrderUsd',
  'mcpDailySpendUsd', 'mcpMaxPositions', 'mcpMinEdgeCents',
  'mcpAllowResearch', 'mcpAllowScripts', 'mcpAllowScriptRun', 'mcpAllowConfig',
  'mcpAllowLiveSwitches', 'mcpDailyLossUsd', 'mcpLiveApproval',
  'autopilotEnabled', 'autopilotIntervalMin', 'autopilotMaxRunsPerDay',
  'autopilotDailyTokenBudget', 'autopilotMaxSteps',
  'perpsFarmEnabled',
] as const;

function readBackendLogTail(lines: number): string[] {
  const TAIL_BYTES = 512 * 1024;
  try {
    const p = join(app.getPath('userData'), 'logs', 'backend.log');
    if (!existsSync(p)) return [];
    const size = statSync(p).size;
    const start = Math.max(0, size - TAIL_BYTES);
    const fd = openSync(p, 'r');
    try {
      const len = size - start;
      const buf = Buffer.alloc(len);
      readSync(fd, buf, 0, len, start);
      const text = buf.toString('utf8');
      const all = text.split(/\r?\n/);
      if (start > 0 && all.length) all.shift();
      return all.filter((l) => l.trim()).slice(-Math.max(0, lines));
    } finally {
      closeSync(fd);
    }
  } catch {
    return [];
  }
}

function buildDiagnostics(logLines: number): string {
  const state = store.get();
  const cfg = state.config as unknown as Record<string, unknown>;
  const info = pythonBackend.info();

  const config: Record<string, unknown> = {};
  for (const k of DIAGNOSTIC_CONFIG_KEYS) {
    if (k in cfg) config[k] = cfg[k];
  }
  config['remoteDiscordUserId'] = cfg.remoteDiscordUserId ? '(set)' : '(unset)';
  config['remoteTelegramChatId'] = cfg.remoteTelegramChatId ? '(paired)' : '(unpaired)';
  for (const k of ['eventWebhookUrl', 'statsWebhookUrl', 'whaleWebhookUrl',
                   'momentumWebhookUrl']) {
    config[k] = cfg[k] ? '(set)' : '(unset)';
  }

  const tail = logsBuffer.slice(-Math.max(0, logLines)).map((e: any) =>
    `${e?.ts ?? ''} ${String(e?.level ?? '').padEnd(5)} ${e?.source ?? ''}: ${e?.msg ?? ''}`);

  const fileTail = readBackendLogTail(logLines);

  return [
    '=== Krypt Trader diagnostics ===',
    `generated:      ${new Date().toISOString()}`,
    `app version:    ${app.getVersion()}`,
    `electron:       ${process.versions.electron}  node ${process.versions.node}`,
    `platform:       ${process.platform} ${process.arch} (${os.release()})`,
    '',
    '--- backend ---',
    `status:         ${info.status}`,
    `pid:            ${info.pid ?? '—'}`,
    `started:        ${info.startedAt ?? '—'}`,
    `python ok:      ${info.pythonOk}`,
    `authenticated:  ${info.authOk}`,
    `last error:     ${info.lastError ?? '—'}`,
    '',
    '--- config (behavioural keys only; secrets are never included) ---',
    JSON.stringify(config, null, 2),
    '',
    `--- this session: last ${tail.length} line(s) (app + backend, in memory) ---`,
    ...tail,
    '',
    `--- backend.log on disk: last ${fileTail.length} line(s) ---`,
    ...(fileTail.length
      ? fileTail
      : ['(unavailable — the log file could not be read; use Logs → Open log '
         + 'folder and attach backend.log)']),
    '=== end ===',
  ].join('\n');
}

const MAX_LOGS = 5000;
export const logsBuffer: any[] = [];

export function appendLog(entry: any): void {
  logsBuffer.push(entry);
  if (logsBuffer.length > MAX_LOGS) logsBuffer.shift();
}

export { broadcastState };
