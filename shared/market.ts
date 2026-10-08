
import type { BookEnv } from './types';

export type DataSource =
  | 'kalshi-ws'
  | 'kalshi-rest'
  | 'kalshi-cache'
  | 'local-db'
  | 'derived';

export type SourcedField =
  | 'yesBid' | 'yesAsk' | 'lastPrice' | 'volume' | 'volume24h'
  | 'openInterest' | 'liquidity' | 'status';

export type MarketSideName = 'yes' | 'no';
export type OrderAction = 'buy' | 'sell';

export interface MarketSummary {
  ticker: string;
  eventTicker: string | null;
  seriesTicker: string | null;
  title: string;
  yesSubTitle: string | null;
  category: string | null;
  status: string | null;

  openTime: string | null;
  closeTime: string | null;
  expirationTime: string | null;

  yesBid: number | null;
  yesAsk: number | null;
  noBid: number | null;
  noAsk: number | null;
  yesBidSize: number | null;
  yesAskSize: number | null;
  lastPrice: number | null;
  previousPrice: number | null;
  spreadCents: number | null;
  midCents: number | null;

  volume: number | null;
  volume24h: number | null;
  openInterest: number | null;
  liquidityUsd: number | null;

  result: string | null;
  settlementValue: number | null;
  canCloseEarly: boolean | null;

  minutesToClose: number | null;
  exchangeIndex: number | null;

  sources: Partial<Record<SourcedField, DataSource>>;
  observedAt: string;
}


export type DiscoverColumn =
  | 'trending'
  | 'closing'
  | 'new'
  | 'volume'
  | 'watchlist';

export interface DiscoverFilters {
  categories?: string[];
  minPriceCents?: number;
  maxPriceCents?: number;
  minVolume?: number;
  maxHoursToClose?: number;
}

export interface DiscoverResult {
  column: DiscoverColumn | 'search';
  rows: MarketSummary[];
  categories?: string[];
  scanned: number | null;
  truncated: boolean;
  note: string | null;
  fetchedAt: string;
  ageSec: number | null;
}


export interface BookLevel {
  priceCents: number;
  contracts: number;
  cumulative: number;
}

export interface OrderBookSnapshot {
  ticker: string;
  yes: BookLevel[];
  no: BookLevel[];
  yesBid: number | null;
  yesAsk: number | null;
  spreadCents: number | null;
  midCents: number | null;
  yesDepthContracts: number | null;
  noDepthContracts: number | null;
  source: DataSource;
  observedAt: string;
  stale: boolean;
  note: string | null;
}


export type CandleInterval = 1 | 60 | 1440;

export interface MarketCandle {
  ts: number;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  mean: number | null;
  yesBidClose: number | null;
  yesAskClose: number | null;
  volume: number | null;
  openInterest: number | null;
}

export interface CandleSeries {
  ticker: string;
  intervalMin: CandleInterval;
  candles: MarketCandle[];
  emptyPeriods: number;
  startTs: number;
  endTs: number;
  source: DataSource;
  note: string | null;
}


export interface TapeTrade {
  tradeId: string;
  ticker: string;
  takerSide: MarketSideName | null;
  yesPrice: number | null;
  noPrice: number | null;
  contracts: number | null;
  notionalUsd: number | null;
  createdAt: string | null;
  observedAt: string | null;
  isBlockTrade: boolean;
  source: DataSource;
}

export interface TapeResult {
  ticker: string;
  trades: TapeTrade[];
  source: DataSource;
  note: string | null;
  fetchedAt: string;
}


export type RiskVerdict = 'pass' | 'warn' | 'fail' | 'unknown';

export interface RiskCheck {
  id: string;
  label: string;
  verdict: RiskVerdict;
  detail: string;
}

export interface ResolutionRisk {
  ticker: string;
  checks: RiskCheck[];
  resolvedCount: number;
  totalCount: number;
  score: number | null;
  scoreNote: string;
  settlementSources: { name: string; url: string | null }[] | null;
  rulesPrimary: string | null;
  rulesSecondary: string | null;
  closeTime: string | null;
  expirationTime: string | null;
  settlementTimerSeconds: number | null;
  canCloseEarly: boolean | null;
  venue: 'kalshi';
  venueNote: string;
}


export interface MarketDetail {
  market: MarketSummary;
  event: {
    eventTicker: string;
    title: string | null;
    subTitle: string | null;
    category: string | null;
    siblings: MarketSummary[];
  } | null;
  series: {
    seriesTicker: string;
    title: string | null;
    frequency: string | null;
    contractUrl: string | null;
  } | null;
  risk: ResolutionRisk;
  book: OrderBookSnapshot | null;
  position: TerminalPosition | null;
  restingOrders: RestingOrder[];
  quoteDriftCents: number | null;
  fetchedAt: string;
  errors: { panel: string; message: string }[];
}


export interface TerminalPosition {
  ticker: string;
  title: string | null;
  eventTicker: string | null;
  side: MarketSideName;
  contracts: number;
  avgCostCents: number | null;
  costBasisUsd: number | null;
  feesPaidUsd: number | null;
  markCents: number | null;
  marketValueUsd: number | null;
  unrealizedUsd: number | null;
  realizedUsd: number | null;
  reconciled: boolean;
  reconcileNote: string | null;
  closeTime: string | null;
  status: string | null;
}

export interface TerminalPortfolio {
  positions: TerminalPosition[];
  unreconciledCount: number;
  totalCostBasisUsd: number | null;
  totalMarketValueUsd: number | null;
  totalUnrealizedUsd: number | null;
  totalRealizedUsd: number | null;
  cashUsd: number | null;
  shardCash: Record<string, { name: string; cashUsd: number }>;
  shardTransferUrl: string;
  env: BookEnv;
  fetchedAt: string;
  note: string | null;
}

export interface RestingOrder {
  orderId: string;
  clientOrderId: string | null;
  ticker: string;
  title: string | null;
  side: MarketSideName;
  action: OrderAction;
  priceCents: number | null;
  count: number | null;
  remaining: number | null;
  status: string;
  createdAt: string | null;
  manual: boolean;
}


export interface TicketRequest {
  ticker: string;
  side: MarketSideName;
  action: OrderAction;
  count: number;
  priceCents: number;
  expectMode?: 'paper' | 'live';
}

export interface TicketPreview extends TicketRequest {
  costUsd: number | null;
  feeUsd: number | null;
  totalUsd: number | null;
  maxPayoutUsd: number | null;
  maxProfitUsd: number | null;
  maxLossUsd: number | null;
  breakevenProb: number | null;
  restingBestCents: number | null;
  marketableNow: boolean | null;
  warnings: string[];
  blockers: string[];
}

export interface TicketResult {
  ok: boolean;
  message: string;
  orderId: string | null;
  clientOrderId: string;
  status: string | null;
  filledContracts: number | null;
  avgFillCents: number | null;
  feesUsd: number | null;
  reconciled: boolean;
  code?: string;
}

export interface ManualTrade {
  id: number;
  ticker: string;
  title: string | null;
  side: MarketSideName;
  contracts: number;
  avgCostCents: number | null;
  costUsd: number | null;
  feesUsd: number | null;
  status: string | null;
  resolved: boolean;
  outcomeCorrect: boolean | null;
  pnlUsd: number | null;
  settlementUsd: number | null;
  closedEarly: boolean;
  createdAt: string | null;
  resolvedAt: string | null;
}

export interface CalibrationBucket {
  loCents: number;
  hiCents: number;
  trades: number;
  wins: number;
  hitRate: number | null;
  impliedRate: number | null;
  note: string | null;
}

export interface ManualHistory {
  env: BookEnv;
  trades: ManualTrade[];
  closedCount: number;
  openCount: number;
  wins: number;
  losses: number;
  winRate: number | null;
  realizedUsd: number | null;
  feesUsd: number | null;
  buckets: CalibrationBucket[];
  calibratableCount: number;
  minTradesPerBucket: number;
  fetchedAt: string;
  note: string | null;
}


export type RuleKind = 'stop' | 'take' | 'alert';

export interface TerminalRule {
  id: number;
  kind: RuleKind;
  ticker: string;
  title: string | null;
  side: MarketSideName;
  thresholdCents: number | null;
  direction: 'below' | 'above';
  contracts: number | null;
  status: 'armed' | 'firing' | 'triggered' | 'cancelled' | 'error';
  note: string | null;
  lastError: string | null;
  lastCheckedAt: string | null;
  lastPriceCents: number | null;
  lastPriceSource: string | null;
  unevaluableCount: number;
  triggeredAt: string | null;
  triggeredOrderId: string | null;
  createdAt: string | null;
}

export interface RuleList {
  rules: TerminalRule[];
  armedCount: number;
  env: BookEnv;
  fetchedAt: string;
}

export interface RuleRequest {
  kind: RuleKind;
  ticker: string;
  side: MarketSideName;
  thresholdCents: number;
  direction?: 'below' | 'above';
  contracts?: number | null;
  note?: string;
}


export interface MicroSample {
  ts: number;
  bid: number | null;
  ask: number | null;
  bidSize: number | null;
  askSize: number | null;
}

export interface Microstructure {
  ticker: string;
  samples: MicroSample[];
  sampleCount: number;
  windowSec: number | null;
  twoSidedPct: number | null;
  medianSpreadCents: number | null;
  p90SpreadCents: number | null;
  bestSpreadCents: number | null;
  quoteLifetimeSec: number | null;
  probeCents: number | null;
  probeFillablePct: number | null;
  note: string | null;
}


export interface HostReport {
  host: string;
  purpose: string;
  when: string;
  sends: string;
  required: boolean;
  optional_off: string | null;
  calls: number | null;
  errors: number | null;
  lastMs: number | null;
  avgMs: number | null;
  lastAt: string | null;
  lastError: string | null;
}

export interface NetworkReport {
  hosts: HostReport[];
  unlisted: { host: string; calls: number; errors: number }[];
  totalCalls: number;
  websocket: {
    enabled: boolean;
    connected: boolean;
    env: string | null;
    subscribedBooks: number | null;
    lastMsgAgeSec: number | null;
  };
  fetchedAt: string;
  note: string;
}


export interface PolyMarket {
  conditionId: string;
  slug: string | null;
  question: string;
  endDate: string | null;
  yesBid: number | null;
  yesAsk: number | null;
  spreadCents: number | null;
  midCents: number | null;
  lastPrice: number | null;
  volume24h: number | null;
  liquidityUsd: number | null;
  acceptingOrders: boolean;
  negRisk: boolean;
  url: string;
  observedAt: string;
}

export interface VenueComparison {
  kalshiBid: number | null;
  kalshiAsk: number | null;
  kalshiMid: number | null;
  polyBid: number | null;
  polyAsk: number | null;
  polyMid: number | null;
  differenceCents: number | null;
  cheaperToBuyYes: 'kalshi' | 'polymarket' | 'neither' | null;
  askDifferenceCents: number | null;
}

export interface CrossVenueMatch {
  confidence: number;
  confident: boolean;
  reasons: string[];
  market: PolyMarket;
  comparison: VenueComparison | null;
}

export interface CrossVenueResult {
  ticker: string;
  available: boolean;
  geoblocked: boolean;
  matches: CrossVenueMatch[];
  scanned: number | null;
  polymarketAgeSec: number | null;
  kalshiObservedAt: string | null;
  note: string | null;
  venueNote: string;
  fetchedAt: string;
}


export interface RemoteBotStatus {
  configured: boolean;
  running: boolean;
  connected: boolean;
  botName: string | null;
  lastError: string | null;
  lastMessageAt: number | null;
  enabled: boolean;
  hasToken: boolean;
}

export interface RemoteDiscordStatus extends RemoteBotStatus {
  userId: string;
  sawMessageContent: boolean;
}

export interface RemoteTelegramStatus extends RemoteBotStatus {
  paired: boolean;
  chatId: string;
  pairCode: string | null;
}

export interface RemoteStatus {
  discord: RemoteDiscordStatus;
  telegram: RemoteTelegramStatus;
  tradingEnabled: boolean;
  alertsEnabled: boolean;
}


export type AiProvider =
  | 'anthropic' | 'openai' | 'openrouter' | 'gemini' | 'ollama' | 'lmstudio';

export interface AiProviderCaps {
  label: string;
  local: boolean;
  needsKey: boolean;
  webSearch: boolean;
  webSearchHow: string;
  tools: 'all' | 'per-model';
  toolsHow: string;
  tokens: string;
  pricing: 'published' | 'provider' | 'none' | 'free';
  catalogue: 'curated' | 'listed';
  modelsEndpoint: string;
}

export interface AiProviderCheck {
  ok: boolean;
  provider: AiProvider;
  message: string;
  model?: string;
  models?: string[];
  modelInfo?: { id: string; tools: boolean | null; context: number | null; loaded: boolean | null }[];
  tools?: boolean;
  webSearch?: boolean;
}

export type AiVerdict = 'cheap' | 'rich' | 'fair' | 'unclear';

export interface AiInsight {
  heading: string;
  body: string;
}

export interface AiCitation {
  title: string;
  url: string;
}

export interface AiAnalysis {
  ticker: string;
  provider: AiProvider;
  model: string;
  webSearchUsed: boolean;

  summary: string;
  drivers: AiInsight[];
  resolutionNotes: string | null;

  fairValueCents: number | null;
  fairValueLowCents: number | null;
  fairValueHighCents: number | null;
  verdict: AiVerdict;
  confidence: 'low' | 'medium' | 'high';
  wouldChangeMyMind: string[];

  citations: AiCitation[];
  raw: string | null;

  inputTokens: number | null;
  outputTokens: number | null;
  costUsd: number | null;
  elapsedSec: number;
  generatedAt: string;
}

export interface AiStatus {
  provider: AiProvider;
  model: string;
  webSearch: boolean;
  hasKey: boolean;
  keys: Record<AiProvider, boolean>;
  models: Record<AiProvider, string[]>;
  providers: AiProvider[];
  capabilities: Record<AiProvider, AiProviderCaps>;
  prices?: Record<string, { inPerMTok: number; outPerMTok: number }>;
}

export type AiAnalyzeResult =
  | { ok: true; analysis: AiAnalysis }
  | { ok: false; error: string };


export interface TerminalApi {
  discover: (args: {
    column: DiscoverColumn; limit?: number; refresh?: boolean;
    filters?: DiscoverFilters;
  }) => Promise<DiscoverResult>;
  search: (args: { query: string; limit?: number }) => Promise<DiscoverResult>;
  market: (args: { ticker: string }) => Promise<MarketDetail>;
  book: (args: { ticker: string }) => Promise<OrderBookSnapshot>;
  candles: (args: { ticker: string; intervalMin: CandleInterval; lookbackMin?: number }) =>
    Promise<CandleSeries>;
  tape: (args: { ticker: string; limit?: number }) => Promise<TapeResult>;
  portfolio: () => Promise<TerminalPortfolio>;
  orders: () => Promise<{ orders: RestingOrder[]; note: string | null }>;
  history: (args?: { limit?: number }) => Promise<ManualHistory>;
  rules: (args?: { limit?: number }) => Promise<RuleList>;
  armRule: (req: RuleRequest) => Promise<TerminalRule>;
  cancelRule: (args: { id: number }) => Promise<{ ok: boolean; message: string }>;
  micro: (args: { ticker: string; probeCents?: number }) => Promise<Microstructure>;
  hosts: () => Promise<NetworkReport>;
  crossVenue: (args: { ticker: string }) => Promise<CrossVenueResult>;
  remoteStatus: () => Promise<RemoteStatus>;
  remoteSetToken: (args: { which: 'discord' | 'telegram'; token: string }) =>
    Promise<{ ok: boolean; hasToken: boolean }>;
  remotePairCode: () => Promise<{ code: string; ttlSec: number }>;
  remoteUnpair: (args: { which: 'discord' | 'telegram' }) => Promise<{ ok: boolean }>;
  remoteTest: () => Promise<{ sent: { which: string; ok: boolean; error: string | null }[] }>;
  onRule: (cb: (d: { rule: TerminalRule; message: string }) => void) => () => void;
  preview: (req: TicketRequest) => Promise<TicketPreview>;
  submit: (req: TicketRequest) => Promise<TicketResult>;
  cancel: (args: { orderId: string }) => Promise<TicketResult>;
  shardTransfer: (args: { amountUsd: number; fromShard: number; toShard: number })
    => Promise<{ ok: boolean; message: string; transferId?: string }>;
  watchlist: () => Promise<string[]>;
  setWatched: (args: { ticker: string; watched: boolean }) => Promise<string[]>;

  aiStatus: () => Promise<AiStatus>;
  aiSetKey: (args: { provider: AiProvider; key: string })
    => Promise<{ ok: boolean; provider: AiProvider; hasKey: boolean }>;
  aiCheckProvider: (args: { provider: AiProvider }) => Promise<AiProviderCheck>;
  aiAnalyze: (args: { ticker: string }) => Promise<AiAnalyzeResult>;
  aiScoreboard: () => Promise<ForecastScoreboard>;

  mcpStatus: () => Promise<McpStatus>;
  mcpRotateToken: (args?: { agentId?: string }) => Promise<{ ok: boolean }>;
  mcpCopyConfig: (args: { client: McpClient; agentId?: string }) => Promise<{ ok: boolean }>;
  mcpCopyHttpSnippet: (args?: { agentId?: string }) => Promise<{ ok: boolean }>;
  mcpInstallConfig?: (args: { client: 'claude-desktop' | 'codex'; agentId?: string }) => Promise<{
    ok: boolean; message: string; files: string[]; backups: string[];
  }>;
  mcpOpenConfigFolder?: (args: { client: 'claude-desktop' | 'codex' }) => Promise<{ ok: boolean; message?: string }>;
  agentsClosePaper?: (args: { agentId: string }) => Promise<{
    ok?: boolean; message?: string;
    closed?: { ticker: string; side: string; contracts: number; avgPriceCents: number | null; feeUsd: number | null }[];
    open?: { ticker: string; side: string; contracts: number; reason: string }[];
  }>;
  healthCheck: (args?: { deep?: boolean }) => Promise<HealthReport>;
  mcpActivity: (args?: { limit?: number }) => Promise<McpActivity>;
  mcpPaperReset: () => Promise<{ ok: boolean; removed: Record<string, number> }>;
  mcpDecide: (args: { id: number; approve: boolean }) => Promise<{ ok: boolean; message: string }>;
  autopilotStatus: () => Promise<AutopilotStatus>;
  autopilotRunNow: () => Promise<{ ok: boolean; message: string }>;
  onMcpOrder: (cb: (d: { mode: McpTradeMode | 'action'; message: string }) => void) => () => void;
  mcpSeen: () => Promise<McpSeen>;
  onMcpToolCall: (cb: (d: McpToolCallEvent) => void) => () => void;
}

export interface McpToolCallEvent {
  v: 1;
  kind: 'call' | 'connect';
  at: number;
  client: string;
  transport: string | null;
  model: string | null;
  tool: string | null;
  outcome: 'ok' | 'refused' | 'error';
  reason: string | null;
  durationMs: number;
  summary: string;
  ticker: string | null;
  fairCents: number | null;
  edgeCents: number | null;
  midCents?: number | null;
  side: 'yes' | 'no' | null;
  mode: 'paper' | 'live' | null;
  suppressed?: number;
  agentId?: string | null;
  agentName?: string | null;
}

export interface McpSeen {
  clients: { client: string; firstAt: number; lastAt: number; calls: number; model: string | null; agentId?: string }[];
  agents?: { agentId: string; firstAt: number; lastAt: number; calls: number; clients: string[] }[];
  now: number;
}


export type ForecastVerdict = 'too-few' | 'indistinguishable' | 'ai-better' | 'market-better';

export interface ForecastScore {
  n: number;
  nPaired: number;
  brierAi: number | null;
  brierAiPaired: number | null;
  brierMarket: number | null;
  skill: number | null;
  diffMean: number | null;
  diffSe: number | null;
  verdict: ForecastVerdict;
}

export interface ForecastRow {
  id: number;
  createdAt: string | null;
  ticker: string;
  title: string | null;
  source: 'panel' | 'mcp';
  model: string | null;
  client: string | null;
  agentId?: string | null;
  fairValueCents: number | null;
  marketMidCents: number | null;
  outcome: number | null;
  resolvedAt: string | null;
  brierAi: number | null;
  brierMarket: number | null;
}

export interface ForecastScoreboard {
  totalForecasts: number;
  pending: number;
  resolved: number;
  scoredMarkets: number;
  minScored: number;
  overall: ForecastScore;
  bySource: (ForecastScore & { source: 'panel' | 'mcp' })[];
  buckets: { lo: number; hi: number; n: number; meanForecast: number; hitRate: number }[];
  byForecaster?: ForecasterScore[];
  byAgent?: AgentScore[];
  recent: ForecastRow[];
}

export interface AgentScore extends ForecastScore {
  agentId: string;
  total: number;
  pending: number;
  lastAt: string | null;
}

export interface ForecasterScore extends ForecastScore {
  source: 'panel' | 'mcp';
  client: string | null;
  model: string | null;
  agentId?: string | null;
  total: number;
  pending: number;
  lastAt: string | null;
  open: { ticker: string; fairValueCents: number; marketMidCents: number | null; createdAt: string | null }[];
}


export type McpTradeMode = 'off' | 'paper' | 'live';
export type McpClient = 'cursor' | 'claude-code' | 'claude-desktop' | 'codex';

export interface McpRails {
  maxOrderUsd: number;
  dailySpendUsd: number;
  maxOpenPositions: number;
  minEdgeCents: number;
  dailyLossUsd: number;
  forecastTtlMin: number;
}

export interface McpStatus {
  enabled: boolean;
  running: boolean;
  port: number;
  lastError: string | null;
  hasToken: boolean;
  tradeMode: McpTradeMode;
  env: string;
  calls: number;
  lastCallAt: string | null;
  lastTool: string | null;
  clients: string[];
  lastSeen: { client: string; at: string } | null;
  httpEnabled: boolean;
  spentTodayUsd: number;
  rails: McpRails;
  permissions: Record<McpPermission, boolean>;
  liveApproval: boolean;
  pending: McpOrderRow[];
  lossToday: {
    realizedUsd: number; unrealizedUsd: number; lossUsd: number; unmarked: string[];
    unmarkedCostUsd?: number;
    positionsUnreadable?: boolean;
  } | null;
  toolCount: number;
  agents?: McpAgentStatus[];
}

export interface McpAgentStatus {
  id: string;
  hasToken: boolean;
  effectiveMode: McpTradeMode;
  serverName: string;
  spentTodayUsd: number | null;
  lastSeenAt: number | null;
  calls: number;
  clients: string[];
}


export type HealthStatus = 'ok' | 'warn' | 'fail' | 'off';

export type HealthAction =
  | { kind: 'nav'; page: string; label: string }
  | { kind: 'copy'; text: string; label: string };

export interface HealthRow {
  id: string;
  label: string;
  status: HealthStatus;
  detail: string;
  fix: string | null;
  action: HealthAction | null;
  network: boolean;
  tested: boolean;
}

export interface HealthReport {
  checkedAt: string;
  deep: boolean;
  rows: HealthRow[];
}

export type McpPermission =
  | 'mcp_allow_research' | 'mcp_allow_scripts' | 'mcp_allow_script_run'
  | 'mcp_allow_config' | 'mcp_allow_live_switches';

export interface McpActionRow {
  id: number;
  at: string;
  client: string | null;
  tool: string;
  ok: boolean;
  summary: string;
}

export interface McpOrderRow {
  id: number;
  at: string;
  env: string;
  mode: 'paper' | 'live';
  client: string | null;
  agentId?: string;
  agentName?: string | null;
  ticker: string;
  side: 'yes' | 'no';
  action: 'buy' | 'sell';
  count: number;
  priceCents: number;
  forecastId: number | null;
  committedUsd: number | null;
  ok: boolean;
  orderId: string | null;
  filled: number | null;
  avgFillCents: number | null;
  message: string;
  status: 'pending' | 'deciding' | 'approved' | 'rejected' | 'expired' | 'failed'
    | 'unknown' | 'cancelled' | null;
}

export interface PaperPosition {
  ticker: string;
  title: string | null;
  side: 'yes' | 'no';
  contracts: number;
  avgCostCents: number;
  costUsd: number;
  markCents: number | null;
  unrealizedUsd: number | null;
  agentId?: string;
}

export interface AgentPaperSummary {
  agentId: string;
  realizedUsd: number;
  unrealizedUsd: number | null;
  openPositions: number;
  fills: number;
}

export interface PaperBook {
  bankrollUsd: number;
  cashUsd: number;
  realizedUsd: number;
  positions: PaperPosition[];
  fills: {
    id: number; at: string; ticker: string; side: 'yes' | 'no';
    kind: 'buy' | 'sell' | 'settle'; contracts: number; priceCents: number;
    feeUsd: number; cashDeltaUsd: number; forecastId: number | null;
  }[];
}

export interface AutopilotRun {
  id: number;
  startedAt: string;
  finishedAt: string | null;
  trigger: 'schedule' | 'manual';
  provider: string;
  model: string;
  status: 'running' | 'ok' | 'steps' | 'budget' | 'context' | 'stopped' | 'error';
  steps: number;
  inputTokens: number | null;
  outputTokens: number | null;
  tokensEstimated?: boolean;
  costUsd: number | null;
  summary: string;
  error: string | null;
  tools: { tool: string; ok: boolean; brief: string }[];
}

export interface AutopilotStatus {
  enabled: boolean;
  running: boolean;
  startedAt: string | null;
  step: number;
  lastError: string | null;
  nextRunAt: string | null;
  blockedReason: string | null;
  today: { runs: number; tokens: number; costUsd: number | null };
  limits: { intervalMin: number; maxRunsPerDay: number; dailyTokenBudget: number; maxSteps: number };
  provider: string;
  providerLabel?: string;
  model: string;
  tokenAccounting?: string;
  toolCount: number;
  runs: AutopilotRun[];
  agentId?: string;
  agentName?: string | null;
}

export interface McpActivity {
  orders: McpOrderRow[];
  paper: PaperBook;
  paperByAgent?: Record<string, AgentPaperSummary>;
  actions: McpActionRow[];
}
