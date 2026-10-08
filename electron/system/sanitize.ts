import { cleanAgents, DEFAULT_AGENT_ID, isValidAgentId } from '../../shared/agents';

export const TICKER_RE = /^[A-Za-z0-9._-]{1,120}$/;

export function cleanTicker(v: unknown): string {
  const t = String(v ?? '').trim().toUpperCase();
  return TICKER_RE.test(t) ? t : '';
}

export function clampInt(v: unknown, lo: number, hi: number, dflt: number): number {
  if (v === null || v === undefined || v === '') return dflt;
  const n = typeof v === 'number' ? v : Number(v);
  if (!Number.isFinite(n)) return dflt;
  return Math.min(hi, Math.max(lo, Math.round(n)));
}

export const DISCOVER_COLUMNS = new Set([
  'trending', 'closing', 'new', 'volume', 'watchlist',
]);

export const CANDLE_INTERVALS = new Set([1, 60, 1440]);

export function cleanFilters(f: unknown): Record<string, unknown> | null {
  if (!f || typeof f !== 'object') return null;
  const src = f as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  const cats = Array.isArray(src.categories)
    ? src.categories.filter((c): c is string => typeof c === 'string').slice(0, 40)
    : [];
  if (cats.length) out.categories = cats;
  for (const [key, lo, hi] of [
    ['minPriceCents', 1, 99], ['maxPriceCents', 1, 99],
    ['minVolume', 0, 1e9], ['maxHoursToClose', 0, 24 * 365],
  ] as const) {
    const v = src[key];
    if (v === undefined || v === null || v === '') continue;
    const n = Number(v);
    if (Number.isFinite(n)) out[key] = Math.min(hi, Math.max(lo, n));
  }
  return Object.keys(out).length ? out : null;
}

export function cleanTicket(req: unknown): {
  ticker: string;
  side: 'yes' | 'no';
  action: 'buy' | 'sell';
  count: number;
  priceCents: number;
  expectMode?: 'paper' | 'live';
} {
  const r = (req ?? {}) as Record<string, unknown>;
  const out: ReturnType<typeof cleanTicket> = {
    ticker: cleanTicker(r.ticker),
    side: r.side === 'no' ? 'no' : 'yes',
    action: r.action === 'sell' ? 'sell' : 'buy',
    count: clampInt(r.count, 0, 1_000_000, 0),
    priceCents: Number(r.priceCents),
  };
  if (r.expectMode === 'paper' || r.expectMode === 'live') out.expectMode = r.expectMode;
  return out;
}


export const BOOK_ENVS = new Set(['paper', 'production', 'demo']);
const POSITION_ENVS = new Set(['paper', 'production', 'demo', 'all']);
const POSITION_STATUSES = new Set([
  'submitted', 'partial', 'filled', 'canceled', 'expired', 'gone', 'error', 'dry_run',
]);
const SIGNAL_SOURCES = new Set(['whale', 'momentum', 'manual', 'external', 'convergence']);

export function cleanBookEnv(v: unknown): 'paper' | 'production' | 'demo' | null {
  const s = String(v ?? '').trim().toLowerCase();
  return BOOK_ENVS.has(s) ? (s as 'paper' | 'production' | 'demo') : null;
}

export function cleanPositionFilter(raw: unknown): Record<string, unknown> {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {};
  const out: Record<string, unknown> = { limit: clampInt(r.limit, 1, 2000, 500) };
  if (Array.isArray(r.status)) {
    const st = r.status.filter((s): s is string => typeof s === 'string' && POSITION_STATUSES.has(s));
    if (st.length) out.status = Array.from(new Set(st));
  }
  if (r.resolved === true || r.resolved === false) out.resolved = r.resolved;
  const src = String(r.signalSource ?? '');
  if (SIGNAL_SOURCES.has(src)) out.signalSource = src;
  const env = String(r.env ?? '').trim().toLowerCase();
  if (POSITION_ENVS.has(env)) out.env = env;
  return out;
}

export function cleanSignalFilter(raw: unknown): Record<string, unknown> {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {};
  const out: Record<string, unknown> = { limit: clampInt(r.limit, 1, 1000, 200) };
  const src = String(r.source ?? '');
  if (src === 'whale' || src === 'momentum') out.source = src;
  for (const [k, lo, hi] of [['minConfidence', 0, 100], ['minEdge', -100, 100]] as const) {
    const v = r[k];
    if (v === undefined || v === null || v === '') continue;
    const n = Number(v);
    if (Number.isFinite(n)) out[k] = Math.min(hi, Math.max(lo, n));
  }
  if (r.resolved === true || r.resolved === false) out.resolved = r.resolved;
  return out;
}

export function cleanBotRunsArgs(env: unknown, limit: unknown): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const e = cleanBookEnv(env);
  if (e) out.env = e;
  if (limit !== undefined && limit !== null && limit !== '') out.limit = clampInt(limit, 1, 1000, 100);
  return out;
}

export function cleanSinceHours(v: unknown): number {
  return clampInt(v, 1, 24 * 366, 168);
}


const BACKTEST_MAX_KEYS = 400;

function cleanConfigValue(v: unknown, depth = 0): unknown {
  if (v === null || typeof v === 'boolean') return v;
  if (typeof v === 'number') return Number.isFinite(v) ? v : undefined;
  if (typeof v === 'string') return v.length <= 200 ? v : undefined;
  if (Array.isArray(v) && depth === 0) {
    const items = v.slice(0, 200).map((x) => cleanConfigValue(x, depth + 1));
    return items.every((x) => x !== undefined) ? items : undefined;
  }
  if (v && typeof v === 'object' && !Array.isArray(v) && depth === 1) {
    const o: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v as Record<string, unknown>).slice(0, 20)) {
      if (!/^[A-Za-z0-9_]{1,64}$/.test(k)) return undefined;
      const c = cleanConfigValue(x, depth + 1);
      if (c === undefined || (typeof c === 'object' && c !== null)) return undefined;
      o[k] = c;
    }
    return o;
  }
  return undefined;
}

export function cleanBacktestConfig(raw: unknown, knownKeys: ReadonlySet<string>): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const out: Record<string, unknown> = {};
  let n = 0;
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (n >= BACKTEST_MAX_KEYS) break;
    if (!knownKeys.has(k) || isPersonalKey(k) || MAIN_EXCLUDE.has(k) || k === 'crypto15mRunners') continue;
    const c = cleanConfigValue(v);
    if (c === undefined) continue;
    out[k] = c;
    n++;
  }
  return out;
}

export function cleanBacktestArgs(raw: unknown, knownKeys: ReadonlySet<string>): {
  sinceDays: number; config?: Record<string, unknown>;
} {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {};
  const out: { sinceDays: number; config?: Record<string, unknown> } = {
    sinceDays: clampInt(r.sinceDays, 1, 365, 60),
  };
  if (r.config !== undefined) out.config = cleanBacktestConfig(r.config, knownKeys);
  return out;
}

export function cleanC15HistoryArgs(raw: unknown): { limit: number; includePaper: boolean } {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {};
  return { limit: clampInt(r.limit, 1, 500, 200), includePaper: r.includePaper === true };
}


export const SCRIPT_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
export const SCRIPT_CODE_MAX = 200_000;

export function cleanScriptId(v: unknown): string {
  if (typeof v !== 'string') return '';
  const s = v.trim();
  return SCRIPT_ID_RE.test(s) ? s : '';
}

export function cleanScriptCode(v: unknown): string | null {
  if (v === undefined || v === null) return '';
  if (typeof v !== 'string') return null;
  return v.length <= SCRIPT_CODE_MAX ? v : null;
}

const clip = (v: unknown, max: number): string | undefined =>
  (typeof v === 'string' ? v.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').slice(0, max) : undefined);

export function cleanScriptSave(raw: unknown): Record<string, unknown> | null {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {};
  const code = cleanScriptCode(r.code);
  if (code === null) return null;
  const out: Record<string, unknown> = { code };
  if (r.id !== undefined && r.id !== null && r.id !== '') {
    const id = cleanScriptId(r.id);
    if (!id) return null;
    out.id = id;
  }
  const name = clip(r.name, 120);
  if (name !== undefined) out.name = name;
  const description = clip(r.description, 500);
  if (description !== undefined) out.description = description;
  const notes = clip(r.notes, 5000);
  if (notes !== undefined) out.notes = notes;
  return out;
}

export function cleanScriptBacktestArgs(raw: unknown, knownKeys: ReadonlySet<string>): Record<string, unknown> | null {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {};
  const out: Record<string, unknown> = { sinceDays: clampInt(r.sinceDays, 1, 365, 60) };
  if (r.code !== undefined && r.code !== null && r.code !== '') {
    const code = cleanScriptCode(r.code);
    if (code === null) return null;
    out.code = code;
  } else {
    const id = cleanScriptId(r.id);
    if (!id) return null;
    out.id = id;
  }
  if (r.config !== undefined) out.config = cleanBacktestConfig(r.config, knownKeys);
  return out;
}


export function cleanTurbineLibraryArgs(raw: unknown): { rerun?: true; days?: number } {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {};
  const out: { rerun?: true; days?: number } = {};
  if (r.rerun === true) out.rerun = true;
  if (r.days !== undefined && r.days !== null && r.days !== '') out.days = clampInt(r.days, 1, 365, 90);
  return out;
}

const OPTIMIZE_GRANULARITY = new Set([1, 2, 3, 4, 6, 8, 12, 24]);

export function cleanOptimizeArgs(raw: unknown): Record<string, unknown> | null {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {};
  const coin = String(r.coin ?? '').trim().toUpperCase();
  if (!/^[A-Z]{2,10}$/.test(coin)) return null;
  const g = Number(r.granularityH);
  const out: Record<string, unknown> = {
    coin,
    granularityH: OPTIMIZE_GRANULARITY.has(g) ? g : 4,
    sinceDays: clampInt(r.sinceDays, 1, 365, 30),
    minTrades: clampInt(r.minTrades, 1, 100_000, 12),
    minTradesCoin: clampInt(r.minTradesCoin, 1, 1_000_000, 30),
    holdout: r.holdout === 'off' ? 'off' : 'auto',
  };
  if (Array.isArray(r.strategyNames)) {
    const names = r.strategyNames
      .filter((s): s is string => typeof s === 'string' && s.length > 0 && s.length <= 120)
      .slice(0, 500);
    if (names.length) out.strategyNames = names;
  }
  return out;
}

export function cleanMarketUrlArgs(raw: unknown): { ticker: string; eventTicker: string; env: 'paper' | 'production' | 'demo' } | null {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw as Record<string, unknown> : {};
  const ticker = cleanTicker(r.ticker);
  const eventTicker = cleanTicker(r.eventTicker);
  if (!ticker && !eventTicker) return null;
  return { ticker, eventTicker, env: cleanBookEnv(r.env) ?? 'production' };
}

export function nextWatchlist(
  current: string[], ticker: string, watched: boolean, cap = 500,
): string[] {
  const t = cleanTicker(ticker);
  if (!t) return current;
  if (watched) {
    return current.includes(t) ? current : [t, ...current].slice(0, cap);
  }
  return current.filter((x) => x !== t);
}

export function cleanHealthArgs(raw: unknown): { deep: boolean } {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw))
    ? raw as Record<string, unknown> : {};
  return { deep: r.deep === true };
}


export const cleanMcpAgents = cleanAgents;

export function cleanConfigPatch<T extends Record<string, unknown>>(patch: T): T {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return {} as T;
  const out: Record<string, unknown> = { ...patch };
  if ('mcpAgents' in out) {
    if (Array.isArray(out.mcpAgents)) out.mcpAgents = cleanAgents(out.mcpAgents);
    else delete out.mcpAgents;
  }
  if ('autopilotAgentId' in out) {
    const id = String(out.autopilotAgentId ?? '').trim().toLowerCase();
    if (isValidAgentId(id)) out.autopilotAgentId = id;
    else delete out.autopilotAgentId;
  }
  return out as T;
}

export function removedAgentIds(before: unknown, after: unknown): string[] {
  const ids = (l: unknown): string[] => (Array.isArray(l)
    ? l.map((a) => String((a as { id?: unknown })?.id ?? '').trim().toLowerCase()).filter(Boolean) : []);
  const keep = new Set(ids(after));
  return ids(before).filter((id) => !keep.has(id));
}

export function cleanAgentIdArg(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const id = v.trim().toLowerCase();
  return isValidAgentId(id) ? id : null;
}

const AGENT_NEVER_KEYS = new Set(['accountMode', 'paperBankrollUsd', 'kalshiEnv', 'shardAutoMove', 'shardAutoMoveMaxUsdDay']);

export function filterAgentConfigPatch(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw as Record<string, unknown>).filter(([k]) =>
    !AGENT_NEVER_KEYS.has(k)
    && !/^(mcp|remote|ai|autopilot|terminalMax)/.test(k)
    && !/webhook|url|token|discord|telegram|key|secret/i.test(k)));
}


export const AI_PROVIDERS = [
  'anthropic', 'openai', 'openrouter', 'gemini', 'ollama', 'lmstudio',
] as const;
export type AiProviderId = typeof AI_PROVIDERS[number];

export const AI_KEYED_PROVIDERS: readonly AiProviderId[] = [
  'anthropic', 'openai', 'openrouter', 'gemini',
];

export function cleanAiProvider(v: unknown): AiProviderId | null {
  const p = String(v ?? '').trim().toLowerCase();
  return (AI_PROVIDERS as readonly string[]).includes(p) ? (p as AiProviderId) : null;
}

export function cleanAiKeyProvider(v: unknown): AiProviderId | null {
  const p = cleanAiProvider(v);
  return p && AI_KEYED_PROVIDERS.includes(p) ? p : null;
}

export function cleanApiKey(v: unknown): string | null {
  if (v === null || v === undefined) return '';
  const k = String(v).trim();
  if (k === '') return '';
  if (k.length > 400) return null;
  return /^[\x21-\x7e]+$/.test(k) ? k : null;
}

const PERSONAL_PREFIXES = ['mcp', 'autopilot', 'remote', 'perps'];
const PERSONAL_KEYS = new Set([
  'accountMode', 'paperBankrollUsd',
  'shardAutoMove', 'shardAutoMoveMaxUsdDay',
  'aiProvider', 'aiModel', 'aiWebSearch',
  'scriptsLiveEnabled', 'scriptsPaperMode',
  'terminalMaxContracts', 'terminalMaxNotionalUsd',
  'enableDiscord',
]);

export function isWebhookKey(k: string): boolean {
  return /webhook/i.test(k);
}

export function isPersonalKey(k: string): boolean {
  return PERSONAL_KEYS.has(k) || PERSONAL_PREFIXES.some((p) => k.startsWith(p)) || isWebhookKey(k);
}

export function omitPersonal<T extends object>(config: T): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(config as Record<string, unknown>)) {
    if (!isPersonalKey(k)) out[k] = v;
  }
  return out as Partial<T>;
}

const SHARE_EXCLUDE = new Set([
  'kalshiEnv', 'enableTrading', 'crypto15mEnabled', 'crypto15mLive', 'crypto15mRunners',
]);

export function omitForShare<T extends object>(config: T): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(config as Record<string, unknown>)) {
    if (!isPersonalKey(k) && !SHARE_EXCLUDE.has(k)) out[k] = v;
  }
  return out as Partial<T>;
}

export function profileExportJson<P extends { config: object }>(p: P): string {
  return JSON.stringify({ kryptTraderProfile: 1, profile: { ...p, config: omitForShare(p.config) } }, null, 2);
}

export const MAIN_EXCLUDE: ReadonlySet<string> = new Set([
  'accountMode', 'paperBankrollUsd', 'kalshiEnv', 'enableTrading',
  'eventWebhookUrl', 'statsWebhookUrl', 'whaleWebhookUrl', 'momentumWebhookUrl',
]);

export const isCrypto15mKey = (k: string): boolean => k.startsWith('crypto15m');

export function isBotSettingKey(k: string): boolean {
  return !isCrypto15mKey(k) && !MAIN_EXCLUDE.has(k) && !isPersonalKey(k);
}

export function botSettingsResetPatch<T extends object>(defaults: T): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(defaults as Record<string, unknown>)) {
    if (isBotSettingKey(k)) out[k] = Array.isArray(v) ? [...v] : v;
  }
  return out as Partial<T>;
}

export function blankWebhooks<T extends object>(config: T): T {
  const out: Record<string, unknown> = { ...(config as Record<string, unknown>) };
  for (const k of Object.keys(out)) {
    if (isWebhookKey(k) && typeof out[k] === 'string') out[k] = '';
  }
  return out as T;
}
