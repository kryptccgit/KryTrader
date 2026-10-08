import { app } from 'electron';
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { AppState, Profile, TraderConfig } from '../../shared/types';
import { migrateConfig, normalizeActiveProfileId } from './legacy-settings';
import { DEFAULT_AGENT_ID, defaultAgent } from '../../shared/agents';
import { botSettingsResetPatch } from './sanitize';


const userDataDir = (): string => app.getPath('userData');

const settingsFile = (): string => join(userDataDir(), 'settings.json');

export const DEFAULT_CONFIG: TraderConfig = {
  accountMode: 'paper',
  paperBankrollUsd: 1000,
  shardAutoMove: true,
  shardAutoMoveMaxUsdDay: 1000,
  enableTrading: false,
  autoUpgradeApiLevel: true,

  tradeWhales: true,
  tradeMomentum: true,
  tradeConvergence: false,

  minEdgePtsWhale: 5.0,
  minEdgePtsMomentum: 5.0,
  minConfidenceWhale: 55.0,
  minConfidenceMomentum: 55.0,
  feeAwareEdge: true,
  maxEntrySlippageCents: 5,
  minMarketVolume: 100,
  maxTradeAgeMin: 15,
  minEntryPriceCents: 15,
  maxEntryPriceCents: 85,
  maxResolutionDays: 30,
  allowedMomentumSignalTypes: ['trade_cluster'],
  allowedCategories: null,
  allowedWhaleCategories: null,
  allowedMomentumCategories: null,
  contrarianOnly: true,

  sizingMode: 'percent',
  fixedTradeUsd: 5,
  baseSizeFraction: 0.03,
  minSizeFraction: 0.02,
  maxSizeFraction: 0.06,
  sizingBaseEdge: 5.0,
  sizingMaxEdge: 10.0,
  hardMaxPositionUsd: 50.0,
  minCashReserveFraction: 0.05,

  orderStyle: 'limit_cross',
  crossSpreadFallbackOffset: 2,
  orderExpirationSec: 90,

  maxOpenPositions: 25,
  maxPositionsPerEvent: 1,
  maxDailyNewPositions: 40,
  unlimitedDailyNewPositions: false,
  maxTotalExposureFraction: 0.35,

  tradeScanInterval: 20,
  positionPollInterval: 30,
  balancePollInterval: 60,
  resolutionCheckInterval: 300,
  whaleScanInterval: 120,
  momentumScanInterval: 90,
  marketRefreshInterval: 300,

  maxSignalAgeSec: 120,

  startBankrollUsd: 0.0,
  stopLossOnDay: -50.0,
  stopLossOnDayPct: 0.05,
  takeProfitOnDay: 0.0,

  tradingHoursEnabled: false,
  tradingHoursStart: '00:00',
  tradingHoursEnd: '23:59',
  tradingDays: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'],
  tradingTimezoneOffsetMin: 0,

  minWhaleUsd: 2500.0,
  minEntryPriceFrac: 0.5,

  eventWebhookUrl: '',
  statsWebhookUrl: '',
  whaleWebhookUrl: '',
  momentumWebhookUrl: '',
  statsPushInterval: 1800,
  statsChartWindowHours: 168,
  enableDiscord: true,

  crypto15mEnabled: false,
  crypto15mLive: false,
  crypto15mSizingMode: 'fixed',
  crypto15mOrderSize: 1,
  crypto15mBalancePct: 0.02,
  crypto15mMaxLossPct: 0,
  crypto15mMaxTotalPct: 0.10,
  crypto15mMaxConcurrent: 3,
  crypto15mAssets: null,
  crypto15mRunners: null,
  crypto15mDirectionMode: 'favorite',
  crypto15mModelMinProb: 0.97,
  crypto15mModelMinEdgeCents: 2,
  crypto15mModelFinalMinute: true,
  crypto15mModelMidwindow: false,
  crypto15mModelAutopause: true,
  crypto15mTimeDelayMin: 8,
  crypto15mEntryThreshold: 0.70,
  crypto15mStrictThreshold: true,
  crypto15mEntryMax: 0.98,
  crypto15mExitThreshold: 0.4,
  crypto15mStopSlippageCents: 0,
  crypto15mTakeProfitCents: 0,
  crypto15mStopLossPct: 0,
  crypto15mSessionTakeProfitUsd: 0,
  crypto15mMinRsi: 0,
  crypto15mMinMacdHist: 0,
  crypto15mMinDeltaPct: 0,
  crypto15mEntryDiff: 0.02,
  crypto15mEntryStyle: 'maker',
  crypto15mMakerCancelMin: 1,
  crypto15mHoursStartUtc: 0,
  crypto15mHoursEndUtc: 24,
  crypto15mRecordSignals: true,
  mainRecordSignals: true,
  perpsWsEnabled: true,
  perpsFarmEnabled: false,
  perpsFarmSymbol: 'KXBTCPERP',
  perpsFarmClipContracts: 1,
  perpsFarmMaxInventoryContracts: 3,
  perpsFarmDailyLossUsd: 2,
  perpsFarmDailyVolumeUsd: 0,
  perpsFarmMaxCostBps: 4,
  crypto15mIndicatorDetect: true,
  crypto15mSpotWs: true,
  crypto15mArbDetect: true,
  crypto15mArbMinEdgeCents: 3,
  crypto15mUseRules: false,
  crypto15mRules: [],
  crypto15mPairsEnabled: false,
  crypto15mDirectionalEnabled: true,
  crypto15mPairsCeilingCents: 95,
  crypto15mPairsDipCents: 2,
  crypto15mPairsClip: 5,
  crypto15mPairsFirstLegMinCents: 35,
  crypto15mPairsFirstLegMaxCents: 60,

  scriptsLiveEnabled: false,
  scriptsPaperMode: false,
  scriptPollSec: 5,
  remoteDiscordEnabled: false,
  remoteTelegramEnabled: false,
  remoteTradingEnabled: false,
  remoteAlertsEnabled: true,
  remoteDiscordUserId: '',
  remoteTelegramChatId: '',

  aiProvider: 'anthropic' as const,
  aiModel: 'claude-opus-5',
  aiWebSearch: false,

  mcpEnabled: false,
  mcpPort: 47821,
  mcpTradeMode: 'paper' as const,
  mcpMaxOrderUsd: 25,
  mcpDailySpendUsd: 100,
  mcpMaxPositions: 10,
  mcpMinEdgeCents: 3,
  mcpDailyLossUsd: 50,
  mcpLiveApproval: true,
  mcpHttpEnabled: false,
  autopilotEnabled: false,
  autopilotIntervalMin: 60,
  autopilotMaxRunsPerDay: 12,
  autopilotDailyTokenBudget: 1_500_000,
  autopilotMaxSteps: 15,
  autopilotMission: '',
  autopilotAgentId: DEFAULT_AGENT_ID,
  mcpAgents: [defaultAgent('paper')],
  mcpAllowResearch: false,
  mcpAllowScripts: false,
  mcpAllowScriptRun: false,
  mcpAllowConfig: false,
  mcpAllowLiveSwitches: false,

  terminalMaxContracts: 1000,
  terminalMaxNotionalUsd: 500.0,
  scriptMaxEntryCents: 97,
  scriptMaxContracts: 20,
  scriptMaxOpen: 2,
  scriptDailyLossUsd: 25,
  scriptMaxEnabled: 10,
};

export const DEFAULT_STATE: AppState = {
  config: { ...DEFAULT_CONFIG },
  activeProfileId: null,
  activeCrypto15mProfileId: null,
  customProfiles: [],
  startMinimized: false,
  startWithWindows: false,
  enableDiscordRpc: true,
  acceptedDisclaimer: false,
  windowBounds: null,
  terminalWatchlist: [],
  trayHintShown: false,
  onboardingSeen: 0,
};

let cached: AppState | null = null;

function ensureDir(): void {
  const d = userDataDir();
  if (!existsSync(d)) mkdirSync(d, { recursive: true });
}

function mergeConfig(loaded: Partial<TraderConfig> | undefined, live = false): TraderConfig {
  return migrateConfig(loaded, DEFAULT_CONFIG, { live });
}

function mergeProfile(loaded: any): Profile | null {
  if (!loaded || typeof loaded !== 'object') return null;
  if (!loaded.id || !loaded.name || !loaded.config) return null;
  return {
    id: String(loaded.id),
    name: String(loaded.name),
    description: loaded.description ? String(loaded.description) : undefined,
    kind: loaded.kind === 'crypto15m' ? 'crypto15m' : 'main',
    createdAt: loaded.createdAt || new Date().toISOString(),
    updatedAt: loaded.updatedAt || new Date().toISOString(),
    builtin: !!loaded.builtin,
    config: mergeConfig(loaded.config),
  };
}

function mergeState(loaded: any): AppState {
  if (!loaded || typeof loaded !== 'object') return { ...DEFAULT_STATE };
  const profiles: Profile[] = Array.isArray(loaded.customProfiles)
    ? loaded.customProfiles.map(mergeProfile).filter((p: Profile | null): p is Profile => p !== null)
    : [];
  return {
    config: mergeConfig(loaded.config, true),
    activeProfileId: normalizeActiveProfileId(loaded.activeProfileId),
    activeCrypto15mProfileId: loaded.activeCrypto15mProfileId || null,
    customProfiles: profiles,
    startMinimized: !!loaded.startMinimized,
    startWithWindows: !!loaded.startWithWindows,
    enableDiscordRpc:
      typeof loaded.enableDiscordRpc === 'boolean' ? loaded.enableDiscordRpc : true,
    acceptedDisclaimer: !!loaded.acceptedDisclaimer,
    windowBounds: loaded.windowBounds || null,
    trayHintShown: !!loaded.trayHintShown,
    onboardingSeen: Number.isInteger(loaded.onboardingSeen) && loaded.onboardingSeen > 0
      ? Math.min(loaded.onboardingSeen, 1000) : 0,
    terminalWatchlist: Array.isArray(loaded.terminalWatchlist)
      ? loaded.terminalWatchlist
          .filter((t: unknown): t is string => typeof t === 'string')
          .map((t: string) => t.trim().toUpperCase())
          .filter(Boolean)
          .slice(0, 500)
      : [],
  };
}

export function load(): AppState {
  if (cached) return cached;
  ensureDir();
  const f = settingsFile();
  if (!existsSync(f)) {
    cached = { ...DEFAULT_STATE };
    save(cached);
    return cached;
  }
  try {
    const raw = readFileSync(f, 'utf-8');
    cached = mergeState(JSON.parse(raw));
  } catch (e) {
    console.error('settings parse failed, backing up + falling back to defaults:', e);
    try {
      renameSync(f, `${f}.corrupt-${Date.now()}.bak`);
    } catch {   }
    cached = { ...DEFAULT_STATE };
  }
  return cached;
}

export function save(state: AppState): AppState {
  ensureDir();
  cached = state;
  const f = settingsFile();
  const tmp = `${f}.tmp`;
  writeFileSync(tmp, JSON.stringify(state, null, 2), 'utf-8');
  renameSync(tmp, f);
  return state;
}

export function get(): AppState {
  return cached ?? load();
}

export function patchConfig(patch: Partial<TraderConfig>): AppState {
  const cur = get();
  const next: AppState = { ...cur, config: mergeConfig({ ...cur.config, ...patch }) };
  return save(next);
}

export function replaceConfig(config: TraderConfig): AppState {
  const cur = get();
  const next: AppState = { ...cur, config: mergeConfig(config) };
  return save(next);
}

export function resetBotSettings(): AppState {
  const cur = get();
  const next: AppState = {
    ...cur,
    config: mergeConfig({ ...cur.config, ...botSettingsResetPatch(DEFAULT_CONFIG) }),
    activeProfileId: null,
  };
  return save(next);
}
