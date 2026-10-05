
import type { TerminalApi } from './market';

export type KalshiEnv = 'demo' | 'production';

export type OrderStyle = 'limit_cross' | 'limit_mid' | 'market';

export type SignalSource =
  | 'whale' | 'momentum' | 'convergence' | 'external' | 'manual';

export interface RuleCondition {
  field: string;
  op: '>=' | '<=' | '>' | '<';
  value: number;
}


export interface TraderConfig {
  kalshiEnv: KalshiEnv;
  enableTrading: boolean;
  autoUpgradeApiLevel?: boolean;

  tradeWhales: boolean;
  tradeMomentum: boolean;
  tradeConvergence: boolean;

  minEdgePtsWhale: number;
  minEdgePtsMomentum: number;
  minConfidenceWhale: number;
  minConfidenceMomentum: number;
  feeAwareEdge?: boolean;
  maxEntrySlippageCents?: number;
  minMarketVolume?: number;
  maxTradeAgeMin?: number;
  minEntryPriceCents: number;
  maxEntryPriceCents: number;
  maxResolutionDays?: number;
  allowedMomentumSignalTypes: string[];
  allowedCategories: string[] | null;
  allowedWhaleCategories: string[] | null;
  allowedMomentumCategories: string[] | null;
  contrarianOnly: boolean;

  gamblingMode: boolean;
  gamblingTradeProbability: number;

  sizingMode: 'percent' | 'fixed';
  fixedTradeUsd: number;
  baseSizeFraction: number;
  minSizeFraction: number;
  maxSizeFraction: number;
  sizingBaseEdge: number;
  sizingMaxEdge: number;
  hardMaxPositionUsd: number;
  minCashReserveFraction: number;

  orderStyle: OrderStyle;
  crossSpreadFallbackOffset: number;
  orderExpirationSec: number | null;

  maxOpenPositions: number;
  maxPositionsPerEvent: number;
  maxDailyNewPositions: number;
  unlimitedDailyNewPositions: boolean;
  maxTotalExposureFraction: number;

  tradeScanInterval: number;
  positionPollInterval: number;
  balancePollInterval: number;
  resolutionCheckInterval: number;
  whaleScanInterval: number;
  momentumScanInterval: number;
  marketRefreshInterval: number;

  maxSignalAgeSec: number;

  startBankrollUsd: number;
  stopLossOnDay: number;
  stopLossOnDayPct?: number;
  takeProfitOnDay: number;

  tradingHoursEnabled: boolean;
  tradingHoursStart: string;
  tradingHoursEnd: string;
  tradingDays: string[];
  tradingTimezoneOffsetMin: number;

  minWhaleUsd: number;
  minEntryPriceFrac: number;

  eventWebhookUrl: string;
  statsWebhookUrl: string;
  whaleWebhookUrl: string;
  momentumWebhookUrl: string;
  statsPushInterval: number;
  statsChartWindowHours: number;
  enableDiscord: boolean;

  crypto15mEnabled?: boolean;
  crypto15mLive?: boolean;
  crypto15mSizingMode?: 'fixed' | 'balance_pct';
  crypto15mOrderSize?: number;
  crypto15mBalancePct?: number;
  crypto15mMaxLossPct?: number;
  crypto15mMaxTotalPct?: number;
  crypto15mMaxConcurrent?: number;
  crypto15mAssets?: string[] | null;
  crypto15mRunners?: Crypto15mRunner[] | null;
  crypto15mDirectionMode?: 'favorite' | 'contrarian' | 'model';
  crypto15mModelMinProb?: number;
  crypto15mModelMinEdgeCents?: number;
  crypto15mModelFinalMinute?: boolean;
  crypto15mModelMidwindow?: boolean;
  crypto15mModelAutopause?: boolean;
  crypto15mTimeDelayMin?: number;
  crypto15mEntryThreshold?: number;
  crypto15mStrictThreshold?: boolean;
  crypto15mEntryMax?: number;
  crypto15mExitThreshold?: number;
  crypto15mStopSlippageCents?: number;
  crypto15mTakeProfitCents?: number;
  crypto15mStopLossPct?: number;
  crypto15mSessionTakeProfitUsd?: number;
  crypto15mMinRsi?: number;
  crypto15mMinMacdHist?: number;
  crypto15mMinDeltaPct?: number;
  crypto15mEntryDiff?: number;
  crypto15mEntryStyle?: 'maker' | 'taker';
  crypto15mMakerCancelMin?: number;
  crypto15mHoursStartUtc?: number;
  crypto15mHoursEndUtc?: number;
  crypto15mHours?: number[] | null;
  crypto15mRecordSignals?: boolean;
  mainRecordSignals?: boolean;
  perpsWsEnabled?: boolean;
  perpsFarmEnabled?: boolean;
  perpsFarmSymbol?: string;
  perpsFarmClipContracts?: number;
  perpsFarmMaxInventoryContracts?: number;
  perpsFarmDailyLossUsd?: number;
  perpsFarmDailyVolumeUsd?: number;
  perpsFarmMaxCostBps?: number;
  perpsFarmMaxFeeBps?: number;
  crypto15mIndicatorDetect?: boolean;
  crypto15mSpotWs?: boolean;
  crypto15mArbDetect?: boolean;
  crypto15mArbMinEdgeCents?: number;
  crypto15mUseRules?: boolean;
  crypto15mRules?: RuleCondition[];
  crypto15mPairsEnabled?: boolean;
  crypto15mDirectionalEnabled?: boolean;
  crypto15mPairsCeilingCents?: number;
  crypto15mPairsDipCents?: number;
  crypto15mPairsClip?: number;
  crypto15mPairsFirstLegMinCents?: number;
  crypto15mPairsFirstLegMaxCents?: number;

  scriptsLiveEnabled?: boolean;
  scriptsPaperMode?: boolean;
  scriptPollSec?: number;
  remoteDiscordEnabled?: boolean;
  remoteTelegramEnabled?: boolean;
  remoteTradingEnabled?: boolean;
  remoteAlertsEnabled?: boolean;
  remoteDiscordUserId?: string;
  remoteTelegramChatId?: string;

  aiProvider?: 'anthropic' | 'openai';
  aiModel?: string;
  aiWebSearch?: boolean;

  mcpEnabled?: boolean;
  mcpPort?: number;
  mcpTradeMode?: 'off' | 'paper' | 'live';
  mcpMaxOrderUsd?: number;
  mcpDailySpendUsd?: number;
  mcpMaxPositions?: number;
  mcpMinEdgeCents?: number;
  mcpPaperBankrollUsd?: number;
  mcpDailyLossUsd?: number;
  mcpLiveApproval?: boolean;
  autopilotEnabled?: boolean;
  autopilotIntervalMin?: number;
  autopilotMaxRunsPerDay?: number;
  autopilotDailyTokenBudget?: number;
  autopilotMaxSteps?: number;
  autopilotMission?: string;
  mcpAllowResearch?: boolean;
  mcpAllowScripts?: boolean;
  mcpAllowScriptRun?: boolean;
  mcpAllowConfig?: boolean;
  mcpAllowLiveSwitches?: boolean;

  terminalMaxContracts?: number;
  terminalMaxNotionalUsd?: number;
  scriptMaxEntryCents?: number;
  scriptMaxContracts?: number;
  scriptMaxOpen?: number;
  scriptDailyLossUsd?: number;
  scriptMaxEnabled?: number;
}

export interface CredentialsState {
  env?: 'demo' | 'production';
  hasApiKey: boolean;
  /** Kept as `hasRsaKey` for IPC compatibility; true for an RSA or Ed25519 key. */
  hasRsaKey: boolean;
  apiKeyPreview: string;
  fingerprint: string;
  keyType?: 'rsa' | 'ed25519';
}

export interface CredentialsStatusAll {
  current: 'demo' | 'production';
  demo: CredentialsState;
  production: CredentialsState;
}

export interface CredentialsInput {
  apiKey: string;
  rsaPem: string;
  env?: 'demo' | 'production';
}


export type ProfileKind = 'main' | 'crypto15m';

export interface Profile {
  id: string;
  name: string;
  description?: string;
  kind?: ProfileKind;
  createdAt: string;
  updatedAt: string;
  config: TraderConfig;
  builtin?: boolean;
}


export interface AppState {
  config: TraderConfig;
  activeProfileId: string | null;
  activeCrypto15mProfileId: string | null;
  customProfiles: Profile[];
  startMinimized: boolean;
  startWithWindows: boolean;
  enableDiscordRpc: boolean;
  acceptedDisclaimer: boolean;
  windowBounds: { x: number; y: number; width: number; height: number } | null;
  terminalWatchlist: string[];
}


export type BackendStatus =
  | 'stopped'
  | 'starting'
  | 'running'
  | 'restarting'
  | 'crashed';

export interface BackendInfo {
  status: BackendStatus;
  pid: number | null;
  startedAt: string | null;
  lastError: string | null;
  pythonOk: boolean;
  authOk: boolean;
}

export interface AccountSnapshot {
  cashUsd: number;
  portfolioUsd: number;
  totalUsd: number;
  apiTier?: string | null;
  balanceSyncing?: boolean;
  startBankrollUsd: number;
  bankrollSource?: 'user' | 'auto' | 'live';
  roiPct: number;
  realizedPnlUsd: number;
  todayPnlUsd?: number;
  alltimePnlUsd?: number;
  todayBaselineUsd?: number | null;
  alltimeBaselineUsd?: number | null;
  todayWins?: number;
  todayLosses?: number;
  unrealizedPnlUsd: number;
  openCostUsd: number;
  feesUsd: number;
  wins: number;
  losses: number;
  winRate: number;
  pendingCount: number;
  openCount: number;
  resolvedCount: number;
  totalOpened: number;
  byEnv: { demo: AccountByEnv; production: AccountByEnv };
  sessionPnlUsd?: number;
  sessionRoiPct?: number;
  sessionBaselineUsd?: number;
  sessionStartedAt?: string;
  sessionRunId?: number;
  shardCash?: Record<string, { name: string; cashUsd: number }> | null;
  shardTransferUrl?: string;
}

export interface BotRun {
  id: number;
  kalshiEnv: KalshiEnv;
  startedAt: string;
  endedAt: string | null;
  startCashUsd: number;
  startPortfolioUsd: number;
  startTotalUsd: number;
  endCashUsd: number | null;
  endPortfolioUsd: number | null;
  endTotalUsd: number | null;
  pnlUsd: number;
  tradesOpened: number;
  tradesWon: number;
  tradesLost: number;
  isActive: boolean;
}

export interface BotRunsResponse {
  runs: BotRun[];
  activeRunId: number;
  activeRun: BotRun | null;
}

export interface AccountByEnv {
  wins: number;
  losses: number;
  realizedPnl: number;
}

export interface PnlPoint {
  at: string;
  cashUsd: number;
  portfolioUsd: number;
  totalUsd: number;
  realizedPnlUsd: number;
  openPositions: number;
}

export interface BotPosition {
  id: number;
  signalSource: SignalSource;
  signalId: number;
  ticker: string;
  eventTicker: string;
  title: string;
  category: string;
  direction: 'yes' | 'no';
  action: 'buy' | 'sell';
  targetContracts: number;
  limitPriceCents: number;
  filledContracts: number;
  avgFillPriceCents: number | null;
  costUsd: number;
  feesUsd: number;
  clientOrderId: string;
  kalshiOrderId: string | null;
  status:
    | 'submitted'
    | 'partial'
    | 'filled'
    | 'canceled'
    | 'expired'
    | 'gone'
    | 'error'
    | 'dry_run';
  confidence: number;
  edgePts: number;
  signalPriceCents: number;
  resolved: boolean;
  outcomeCorrect: number | null;
  settlementUsd: number | null;
  pnlUsd: number | null;
  markPriceCents: number | null;
  livePnlUsd: number | null;
  balanceBeforeUsd: number | null;
  kalshiEnv: KalshiEnv;
  createdAt: string;
  lastUpdated: string;
  resolvedAt: string | null;
  error: string | null;
}

export interface SignalRow {
  id: number;
  source: SignalSource;
  ticker: string;
  eventTicker: string;
  title: string;
  category: string;
  direction: 'yes' | 'no';
  priceCents: number;
  confidence: number;
  edgePts: number;
  signalType?: string;
  dollarValue?: number;
  createdAt: string;
  resolved: boolean;
  outcomeCorrect: number | null;
  pnlEstimate: number | null;
  traded: boolean;
}

export interface ScannerStats {
  whales: { total: number; sent: number; resolved: number; winRate: number };
  momentum: { total: number; sent: number; resolved: number; winRate: number };
  marketsTracked: number;
  lastWhaleScanAt: string | null;
  lastMomentumScanAt: string | null;
  lastTradeScanAt: string | null;
}

export interface LogEntry {
  ts: string;
  level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL';
  source: 'main' | 'backend' | 'trader' | 'whale' | 'momentum' | 'discord';
  msg: string;
}

export interface ActionResult<T = void> {
  ok: boolean;
  message?: string;
  data?: T;
}


export interface StrategyPreset {
  id: string;
  name: string;
  tagline: string;
  description: string;
  riskLabel: 'safe' | 'balanced' | 'aggressive' | 'experimental';
  badge?: 'recommended' | 'new' | 'soon' | null;
  comingSoon?: boolean;
  secret?: boolean;
  backtest?: {
    netCents: number;
    t: number;
    n: number;
    approx?: boolean;
  } | null;
  config: TraderConfig;
}


export interface Crypto15mConstants {
  timeDelayMin: number;
  entryThreshold: number;
  exitThreshold: number;
  entryMax: number;
  minDeltaPct?: number;
  entryDiff: number;
  directionMode?: 'favorite' | 'contrarian';
  entryStyle?: 'maker' | 'taker';
  hoursStartUtc?: number;
  hoursEndUtc?: number;
  indicatorDetect?: boolean;
  arbDetect?: boolean;
  useRules?: boolean;
}

export interface Crypto15mAsset {
  asset: string;
  series: string;
  spotUsd: number | null;
  open15mUsd: number | null;
  deltaUsd: number | null;
  deltaPct?: number | null;
  hasMarket: boolean;
  ticker: string | null;
  closeTime: string | null;
  minsLeft: number | null;
  upProb: number | null;
  downProb: number | null;
  favorite: 'up' | 'down' | null;
  favoritePrice: number | null;
  entryCost: number | null;
  yesBid?: number | null;
  yesAsk?: number | null;
  inWindow: boolean;
  signal: boolean;
  openMarketCount: number;
  error: string | null;
  hourUtc?: number | null;
  peersAgree?: number | null;
  marketBias?: number | null;
  upAsk?: number | null;
  downAsk?: number | null;
  arbEdgeCents?: number | null;
  arbSignal?: boolean;
  macd?: number | null;
  macdSignal?: number | null;
  macdHist?: number | null;
  macdCross?: number | null;
  rsi?: number | null;
  strikeUsd?: number | null;
  deltaSignedPct?: number | null;
  sigma1m?: number | null;
  modelProb?: number | null;
  edgeNetCents?: number | null;
  settlePrints?: number;
}

export interface Crypto15mSnapshot {
  fetchedAt: string;
  spotOk: boolean;
  spotSource: string;
  hoursOk?: boolean;
  constants: Crypto15mConstants;
  assets: Crypto15mAsset[];
}

export type Crypto15mStatusName =
  | 'dry_run' | 'submitted' | 'filled' | 'exiting'
  | 'exited' | 'settled' | 'canceled' | 'error';

export interface Crypto15mPosition {
  id: number;
  asset: string;
  series: string;
  ticker: string;
  side: 'up' | 'down' | '';
  direction: 'yes' | 'no' | '';
  strategy?: string;
  runnerId?: string;
  targetContracts: number;
  filledContracts: number;
  entryLimitCents: number;
  avgEntryCents: number | null;
  costUsd: number;
  status: Crypto15mStatusName | string;
  exitReason: string | null;
  exitLimitCents: number | null;
  proceedsUsd: number | null;
  confidence: number;
  entryDeltaUsd: number | null;
  outcomeCorrect: number | null;
  settlementUsd: number | null;
  pnlUsd: number | null;
  resolved: boolean;
  dryRun: boolean;
  closeTime: string;
  kalshiEnv: KalshiEnv;
  createdAt: string;
  resolvedAt: string | null;
  error: string | null;
}

export interface Crypto15mStats {
  openCount: number;
  wins: number;
  losses: number;
  realizedPnlUsd: number;
  total: number;
}

export type Crypto15mRunnerMode = 'paper' | 'live';

export interface Crypto15mScheduleSlot {
  startHour: number;
  endHour: number;
  name?: string;
  config: Partial<TraderConfig>;
}

export interface Crypto15mRunner {
  id: string;
  name: string;
  coins: string[] | null;
  mode: Crypto15mRunnerMode;
  enabled: boolean;
  config: Partial<TraderConfig>;
  schedule?: Crypto15mScheduleSlot[] | null;
  profileId?: string;
}

export interface TurbineStrategy {
  name: string;
  asset: string | null;
  archetype: string;
  turbine: { netPnl?: number; returnPct?: number; winPct?: number; sharpe?: number } | null;
  config: Partial<TraderConfig>;
  backtest: {
    netCentsPerContract: number | null;
    t: number | null;
    n: number | null;
    winRate: number | null;
    rankScore: number | null;
  } | null;
}

export interface TurbineLibrary {
  strategies: TurbineStrategy[];
  skipped: string[];
}

export interface CoinOptimizeAgg {
  n: number;
  wins: number;
  winRate: number | null;
  netCents: number;
  t: number | null;
  pnlUsd: number;
}

export interface CoinOptimizeSlot {
  bucket: string;
  start: number;
  end: number;
  winner: string | null;
  config: Partial<TraderConfig> | null;
  train: CoinOptimizeAgg | null;
  holdout: CoinOptimizeAgg | null;
}

export interface CoinOptimizeResult {
  coin: string;
  granularityH: number;
  sinceDays: number;
  holdoutDays: number;
  strategiesSwept: number;
  schedule: CoinOptimizeSlot[];
  coinWinner: (CoinOptimizeAgg & { name: string; score: number }) | null;
  assembled: CoinOptimizeAgg;
  caveat: string;
}

export interface Crypto15mRunnerStatus {
  id: string;
  name: string;
  mode: Crypto15mRunnerMode;
  enabled: boolean;
  coins: string[];
  n: number;
  wins: number;
  losses: number;
  pnlUsd: number;
  openN: number;
}

export interface Crypto15mSizing {
  mode: 'fixed' | 'balance_pct';
  balancePct: number;
  maxLossPct: number;
  balanceUsd: number;
  estPriceCents: number;
  estContracts: number;
  estCostUsd: number;
  note: string;
}

export interface Crypto15mBacktest {
  n: number;
  wins: number;
  winRate: number;
  netEvCentsPerContract: number;
  totalPnlUsd: number;
  maxDrawdownUsd: number;
  contracts: number;
  windowsScanned: number;
  byAsset: Record<string, { n: number; wins: number; pnlUsd: number }>;
  equity: { at: string | null; value: number }[];
  byHourUtc: { hour: number; n: number; wins: number; pnlUsd: number }[];
  byDay: { day: string; n: number; wins: number; pnlUsd: number }[];
  trades: { ticker: string; asset: string; side: string; costCents: number; minsLeft: number | null; won: boolean; pnlUsd: number; at: string }[];
  caveats: string[];
}

export interface UserScriptStats {
  n: number;
  open: number;
  wins: number;
  losses: number;
  pnlUsd: number;
}

export interface UserScript {
  id: string;
  name: string;
  description: string;
  code: string;
  enabled: boolean;
  trusted: boolean;
  notes: string;
  lastError: string | null;
  lastErrorAt: string | null;
  createdAt: string;
  updatedAt: string;
  stats: UserScriptStats | null;
}

export interface ScriptValidation {
  ok: boolean;
  errors: string[];
  warnings: string[];
  name: string;
  description: string;
  hasHeader: boolean;
  ctxFields: string[];
}

export interface ScriptApiDocs {
  contract: string;
  fields: { name: string; doc: string; backtestable: boolean }[];
  builtins: string[];
  rails: {
    maxEntryCents: number; maxContracts: number; maxOpen: number;
    dailyLossUsd: number; defaultOrderSize: number;
  };
  examples: { name: string; code: string }[];
}

export interface ScriptBacktest extends Crypto15mBacktest {
  tStat?: number | null;
  scriptError?: string | null;
  scriptLogs?: string[];
  signalResult?: (Crypto15mBacktest & { tStat?: number | null; scriptError?: string | null }) | null;
}

export interface CollectionStats {
  c15: {
    windows: number; resolved: number; ticks: number;
    firstAt: string | null; lastAt: string | null;
    recent: { ticker: string; asset: string; favorite: string | null; favorite_price: number | null; up_won: number | null; resolved: number; close_time: string }[];
  };
  main: {
    whales: number; whalesResolved: number; alerts: number; alertsResolved: number;
    firstAt: string | null; lastAt: string | null;
    topCategories: { category: string; n: number }[];
    recent: { ticker: string; category: string; taker_side: string; price: number; dollar_value: number; outcome_correct: number | null; resolved: number; created_at: string }[];
  };
  collecting: { c15: boolean; main: boolean };
}

export interface PerpsWallet {
  env: string;
  settledUsd: number | null;
  availableUsd: number | null;
  positionValueUsd: number | null;
  restingMarginUsd: number | null;
  maintenanceMarginUsd: number | null;
}

export interface PerpsStatus {
  wallet?: PerpsWallet | null;
  farmer: PerpsFarmerStatus;
}

export interface PerpsFarmerStatus {
  enabled: boolean;
  running: boolean;
  halted: boolean;
  haltReason: string;
  lastError: string;
  symbol: string;
  makerFeeBps: number | null;
  maxFeeBps: number;
  inventoryContracts: number;
  avgEntry: number | null;
  liveOrders: { side: string; price: number; contracts: number }[];
  today: {
    fills: number; volumeUsd: number; feesUsd: number;
    realizedUsd: number; netUsd: number; costBps: number;
  };
  maintenanceWindow: boolean;
}

export interface EdgeHealthWindow {
  n: number;
  wins: number;
  losses: number;
  winRate: number;
  netCentsPerContract: number;
  t: number | null;
  avgEntryCents: number;
  sinceLastLoss: number;
}

export interface EdgeHealthRow {
  strategy: string;
  mode: 'paper' | 'live';
  w7: EdgeHealthWindow | null;
  w30: EdgeHealthWindow | null;
  w90: EdgeHealthWindow | null;
  verdict: string;
}

export interface EdgeHealth {
  rows: EdgeHealthRow[];
  calibration: { ok: boolean; rate: number | null; n: number | null; lb: number | null };
  note: string;
}

export interface TradingGate {
  id: string;
  label: string;
  state: 'ok' | 'blocked' | 'off';
  reason: string;
}

export interface TradingStatus {
  main: TradingGate[];
  mainFilterCounts: Record<string, number>;
  mainCandidates: number;
  mainPlaced: number;
  c15: {
    enabled: boolean;
    live: boolean;
    authed: boolean;
    env: string;
    blockReasons: Record<string, string>;
    takeProfitHalted?: boolean;
  };
}

export interface Crypto15mStatus {
  byStrategy?: { strategy: string; n: number; wins: number; losses: number; pnl_usd: number; fees_usd: number }[];
  runners?: Crypto15mRunnerStatus[];
  modelCalibration?: { ok: boolean; n: number; rate: number | null; lb: number | null };
  enabled: boolean;
  live: boolean;
  liveArmed: boolean;
  liveSupported: boolean;
  authed: boolean;
  orderSize: number;
  maxConcurrent: number;
  takeProfitCents: number;
  sessionTakeProfitUsd: number;
  sessionPnlUsd: number;
  takeProfitHalted: boolean;
  sizing: Crypto15mSizing;
  shardFunding?: {
    index: number | null;
    name: string | null;
    cashUsd: number | null;
    starved: boolean;
    known: boolean;
    perEntryMaxUsd: number;
    allOpenMaxUsd: number;
    shards: { index: number; name: string; cashUsd: number }[];
    transferUrl: string;
  };
  env: KalshiEnv;
  stats: Crypto15mStats;
  open: Crypto15mPosition[];
  recent: Crypto15mPosition[];
}


export interface KryptApi {
  app: {
    version: () => Promise<string>;
    openExternal: (url: string) => Promise<void>;
    showItemInFolder: (filePath: string) => Promise<void>;
    getUserDataPath: () => Promise<string>;
    getReferralUrl: () => Promise<string>;
    factoryReset: () => Promise<ActionResult<{ deleted: Record<string, number> }>>;
    onDataReset: (cb: (payload: unknown) => void) => () => void;
  };
  state: {
    get: () => Promise<AppState>;
    onChange: (cb: (state: AppState) => void) => () => void;
    setStartMinimized: (v: boolean) => Promise<ActionResult>;
    setStartWithWindows: (v: boolean) => Promise<ActionResult>;
    setEnableDiscordRpc: (v: boolean) => Promise<ActionResult>;
    acceptDisclaimer: () => Promise<ActionResult>;
  };
  config: {
    get: () => Promise<TraderConfig>;
    update: (patch: Partial<TraderConfig>) => Promise<TraderConfig>;
    replace: (config: TraderConfig) => Promise<TraderConfig>;
    reset: () => Promise<TraderConfig>;
    listStrategies: () => Promise<StrategyPreset[]>;
    applyStrategy: (id: string) => Promise<TraderConfig>;
  };
  profiles: {
    list: () => Promise<Profile[]>;
    save: (name: string, description?: string, kind?: ProfileKind) => Promise<ActionResult<Profile>>;
    apply: (id: string) => Promise<ActionResult<TraderConfig>>;
    rename: (id: string, name: string) => Promise<ActionResult>;
    update: (id: string) => Promise<ActionResult<Profile>>;
    delete: (id: string) => Promise<ActionResult>;
    duplicate: (id: string) => Promise<ActionResult<Profile>>;
    export: (id: string) => Promise<ActionResult<string>>;
    import: (json: string) => Promise<ActionResult<Profile>>;
  };
  credentials: {
    status: () => Promise<CredentialsState>;
    statusAll: () => Promise<CredentialsStatusAll>;
    save: (input: CredentialsInput) => Promise<ActionResult>;
    test: (env?: KalshiEnv) => Promise<ActionResult<{ env: KalshiEnv; balanceUsd: number }>>;
    clear: (env?: KalshiEnv) => Promise<ActionResult>;
    onChanged: (cb: (payload: unknown) => void) => () => void;
  };
  backend: {
    info: () => Promise<BackendInfo>;
    start: () => Promise<ActionResult>;
    stop: () => Promise<ActionResult>;
    restart: () => Promise<ActionResult>;
    onInfo: (cb: (info: BackendInfo) => void) => () => void;
    runOnce: (
      action:
        | 'syncMarkets'
        | 'pollOrders'
        | 'resolveAll'
        | 'reconcilePositions'
        | 'recomputePnl'
        | 'reconcileFills'
        | 'auditPnl'
    ) => Promise<ActionResult<{ summary: string }>>;
  };
  trading: {
    setEnabled: (enabled: boolean) => Promise<ActionResult>;
    cancelAllOpen: () => Promise<ActionResult<{ canceled: number }>>;
    status: () => Promise<TradingStatus | null>;
    collection: () => Promise<CollectionStats | null>;
    exportData: () => Promise<{ dir: string; files: string[] } | null>;
    flatten: () => Promise<ActionResult<{ closed: number }>>;
  };
  data: {
    account: () => Promise<AccountSnapshot>;
    pnlSeries: (sinceHours?: number) => Promise<PnlPoint[]>;
    positions: (filter?: PositionFilter) => Promise<BotPosition[]>;
    signals: (filter?: SignalFilter) => Promise<SignalRow[]>;
    scannerStats: () => Promise<ScannerStats>;
    botRuns: (env?: KalshiEnv | null, limit?: number) => Promise<BotRunsResponse>;
    onAccount: (cb: (snap: AccountSnapshot) => void) => () => void;
    onPosition: (cb: (pos: BotPosition) => void) => () => void;
    onSignal: (cb: (sig: SignalRow) => void) => () => void;
  };
  crypto15m: {
    snapshot: () => Promise<Crypto15mSnapshot>;
    status: () => Promise<Crypto15mStatus>;
    edgeHealth: () => Promise<EdgeHealth | null>;
    backtest: (args?: { sinceDays?: number; config?: Partial<TraderConfig> }) => Promise<Crypto15mBacktest | null>;
    backtestMain: (args?: { sinceDays?: number; config?: Partial<TraderConfig> }) => Promise<Crypto15mBacktest | null>;
    history: (args?: { limit?: number; includePaper?: boolean }) => Promise<{ rows: Crypto15mPosition[] } | null>;
  };
  scripts: {
    list: () => Promise<{ scripts: UserScript[] }>;
    save: (s: { id?: string; name?: string; description?: string; code: string; notes?: string }) =>
      Promise<{ script: UserScript; errors: string[]; warnings: string[] }>;
    delete: (id: string) => Promise<{ ok: boolean }>;
    setEnabled: (id: string, enabled: boolean) => Promise<{ script: UserScript }>;
    setTrusted: (id: string, trusted: boolean) => Promise<{ script: UserScript }>;
    validate: (code: string, trusted?: boolean) => Promise<ScriptValidation>;
    backtest: (args: { id?: string; code?: string; sinceDays?: number; config?: Record<string, unknown> }) =>
      Promise<ScriptBacktest | null>;
    contextPack: () => Promise<{ text: string }>;
    docs: () => Promise<ScriptApiDocs>;
    exportPack: () => Promise<ActionResult<string>>;
    onStatus: (cb: (d: { id: string; enabled: boolean; lastError?: string }) => void) => () => void;
    onLog: (cb: (d: { id: string; lines: string[] }) => void) => () => void;
  };
  turbine: {
    library: (args?: { rerun?: boolean; days?: number }) => Promise<TurbineLibrary | null>;
    optimize: (args: { coin: string; granularityH?: number; sinceDays?: number; minTrades?: number; minTradesCoin?: number; holdout?: string; strategyNames?: string[] }) => Promise<CoinOptimizeResult | null>;
  };
  perps: {
    status: () => Promise<PerpsStatus | null>;
    farmFlatten: () => Promise<{ inventoryCc: number } | null>;
  };
  kalshi: {
    marketUrl: (args: { eventTicker?: string; ticker?: string; env?: string }) =>
      Promise<{ url: string }>;
  };
  terminal: TerminalApi;
  logs: {
    tail: (limit?: number) => Promise<LogEntry[]>;
    onAppend: (cb: (entry: LogEntry) => void) => () => void;
    clear: () => Promise<ActionResult>;
    openFolder: () => Promise<void>;
    diagnostics: (args?: { lines?: number }) =>
      Promise<ActionResult<{ chars: number }>>;
  };
  window: {
    minimize: () => void;
    maximize: () => void;
    close: () => void;
    isMaximized: () => Promise<boolean>;
    onMaximizeChange: (cb: (max: boolean) => void) => () => void;
  };
}

export interface PositionFilter {
  status?: BotPosition['status'][];
  resolved?: boolean | null;
  signalSource?: SignalSource | null;
  limit?: number;
}

export interface SignalFilter {
  source?: SignalSource | null;
  minConfidence?: number;
  minEdge?: number;
  resolved?: boolean | null;
  limit?: number;
}

declare global {
  interface Window {
    krypt: KryptApi;
  }
}
