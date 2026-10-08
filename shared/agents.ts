
export const DEFAULT_AGENT_ID = 'default';
export const MAX_AGENTS = 12;
export const AGENT_NAME_MAX = 40;
export const AGENT_GUIDE_MAX = 4000;
export const DEFAULT_AGENT_EMOJI = '🤖';
export const DEFAULT_AGENT_COLOR = '#A855F7';

export const AGENT_CATEGORIES = [
  { id: 'sports', label: 'Sports' },
  { id: 'politics', label: 'Politics' },
  { id: 'economics', label: 'Economics' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'climate', label: 'Climate' },
  { id: 'entertainment', label: 'Entertainment' },
  { id: 'world', label: 'World' },
  { id: 'exotics', label: 'Exotics' },
] as const;
export type AgentCategory = typeof AGENT_CATEGORIES[number]['id'];
const CATEGORY_IDS: readonly string[] = AGENT_CATEGORIES.map((c) => c.id);

export const AGENT_COLORS = [
  '#A855F7', '#F59E0B', '#22C55E', '#38BDF8', '#F472B6', '#EF4444', '#14B8A6', '#E2E8F0',
] as const;

export type AgentMode = 'paper' | 'live';
export type AgentSides = 'yes' | 'no' | 'both';

export interface McpAgentRules {
  categoriesAllow: AgentCategory[] | null;
  categoriesDeny: AgentCategory[] | null;
  minPriceCents: number | null;
  maxPriceCents: number | null;
  minHoursToClose: number | null;
  maxHoursToClose: number | null;
  sides: AgentSides;
  maxContractsPerMarket: number | null;
  maxOpenPositions: number | null;
  minEdgeCents: number | null;
  dailySpendUsd: number | null;
  maxOrderUsd: number | null;
}

export interface McpAgent {
  id: string;
  name: string;
  emoji: string;
  color: string;
  createdAt: string | null;
  updatedAt: string | null;
  guide: string;
  rules: McpAgentRules;
  mode: AgentMode;
  enabled: boolean;
}

const ID_RE = /^[a-z0-9]{1,24}$/;
const RESERVED_IDS = new Set(['account']);
const COLOR_RE = /^#[0-9A-Fa-f]{6}$/;
const CTRL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029\u200e\u200f\u202a-\u202e\u2066-\u2069]/g;
const CTRL_GUIDE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g;

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};
const clamp = (v: unknown, lo: number, hi: number): number | null => {
  const n = num(v);
  return n === null ? null : Math.min(hi, Math.max(lo, n));
};
const clampInt = (v: unknown, lo: number, hi: number): number | null => {
  const n = clamp(v, lo, hi);
  return n === null ? null : Math.round(n);
};

const cut = (s: string, n: number): string => Array.from(s).slice(0, n).join('');

export function cleanAgentName(raw: unknown, fallback = 'Agent'): string {
  const s = cut(String(raw ?? '').replace(/[\t\n\r\v\f\u2028\u2029]/g, ' ').replace(CTRL, '')
    .replace(/\s+/g, ' ').trim(), AGENT_NAME_MAX).trim();
  return s || fallback;
}

export function cleanGuide(raw: unknown): string {
  return cut(String(raw ?? '').replace(CTRL_GUIDE, '').replace(/\r\n?/g, '\n').trim(),
    AGENT_GUIDE_MAX);
}

function cleanCats(raw: unknown): AgentCategory[] | null {
  if (!Array.isArray(raw)) return null;
  const out: AgentCategory[] = [];
  for (const c of raw) {
    const id = String(c ?? '').trim().toLowerCase();
    if (CATEGORY_IDS.includes(id) && !out.includes(id as AgentCategory)) out.push(id as AgentCategory);
  }
  return out.length ? out : null;
}

export const EMPTY_RULES: Readonly<McpAgentRules> = Object.freeze({
  categoriesAllow: null, categoriesDeny: null, minPriceCents: null, maxPriceCents: null,
  minHoursToClose: null, maxHoursToClose: null, sides: 'both', maxContractsPerMarket: null,
  maxOpenPositions: null, minEdgeCents: null, dailySpendUsd: null, maxOrderUsd: null,
});

export function cleanRules(raw: unknown): McpAgentRules {
  const r = (raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}) as Record<string, unknown>;
  return {
    categoriesAllow: cleanCats(r.categoriesAllow),
    categoriesDeny: cleanCats(r.categoriesDeny),
    minPriceCents: clampInt(r.minPriceCents, 1, 99),
    maxPriceCents: clampInt(r.maxPriceCents, 1, 99),
    minHoursToClose: clamp(r.minHoursToClose, 0, 24 * 365),
    maxHoursToClose: clamp(r.maxHoursToClose, 0, 24 * 365),
    sides: r.sides === 'yes' || r.sides === 'no' ? r.sides : 'both',
    maxContractsPerMarket: clampInt(r.maxContractsPerMarket, 0, 100_000),
    maxOpenPositions: clampInt(r.maxOpenPositions, 0, 200),
    minEdgeCents: clamp(r.minEdgeCents, 0, 50),
    dailySpendUsd: clamp(r.dailySpendUsd, 0, 1e7),
    maxOrderUsd: clamp(r.maxOrderUsd, 0, 1e6),
  };
}

export function defaultAgent(mode: 'off' | 'paper' | 'live' | undefined = 'paper'): McpAgent {
  return {
    id: DEFAULT_AGENT_ID, name: 'Default', emoji: DEFAULT_AGENT_EMOJI, color: DEFAULT_AGENT_COLOR,
    createdAt: null, updatedAt: null, guide: '', rules: { ...EMPTY_RULES },
    mode: mode === 'live' ? 'live' : 'paper', enabled: true,
  };
}

function cleanTs(v: unknown): string | null {
  const s = String(v ?? '').replace(CTRL, '').trim().slice(0, 40);
  return s || null;
}

export function cleanAgent(raw: unknown): McpAgent | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const id = String(r.id ?? '').trim().toLowerCase();
  if (!ID_RE.test(id) || RESERVED_IDS.has(id)) return null;
  const emoji = String(r.emoji ?? '').replace(CTRL, '').trim();
  const color = String(r.color ?? '');
  const en = r.enabled === undefined ? true : r.enabled;
  return {
    id,
    name: cleanAgentName(r.name, id === DEFAULT_AGENT_ID ? 'Default' : 'Agent'),
    emoji: emoji ? Array.from(emoji).slice(0, 8).join('') : DEFAULT_AGENT_EMOJI,
    color: COLOR_RE.test(color) ? color : DEFAULT_AGENT_COLOR,
    createdAt: cleanTs(r.createdAt),
    updatedAt: cleanTs(r.updatedAt),
    guide: cleanGuide(r.guide),
    rules: cleanRules(r.rules),
    mode: r.mode === 'live' ? 'live' : 'paper',
    enabled: typeof en === 'boolean' ? en : false,
  };
}

export function cleanAgents(raw: unknown, tradeMode?: string | null): McpAgent[] {
  if (!Array.isArray(raw)) return [defaultAgent(tradeMode === 'live' ? 'live' : 'paper')];
  const out: McpAgent[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    const a = cleanAgent(item);
    if (!a || seen.has(a.id)) continue;
    seen.add(a.id);
    out.push(a);
  }
  const def = out.find((a) => a.id === DEFAULT_AGENT_ID) ?? defaultAgent('paper');
  const rest = out.filter((a) => a.id !== DEFAULT_AGENT_ID);
  return [def, ...rest.slice(0, MAX_AGENTS - 1)];
}

type Cfg = {
  mcpAgents?: unknown; mcpTradeMode?: 'off' | 'paper' | 'live';
  mcpMaxOrderUsd?: number; mcpDailySpendUsd?: number; mcpMinEdgeCents?: number;
  mcpMaxPositions?: number;
} | null | undefined;

export function agentsOf(c: Cfg): McpAgent[] {
  return cleanAgents(c?.mcpAgents, c?.mcpTradeMode);
}

export function isValidAgentId(v: unknown): v is string {
  return typeof v === 'string' && ID_RE.test(v) && !RESERVED_IDS.has(v);
}

export function newAgentId(taken: Iterable<string> = []): string {
  const used = new Set(taken);
  const abc = 'abcdefghijklmnopqrstuvwxyz0123456789';
  for (;;) {
    const bytes = new Uint8Array(8);
    const c = (globalThis as { crypto?: { getRandomValues?: (a: Uint8Array) => Uint8Array } }).crypto;
    if (c?.getRandomValues) c.getRandomValues(bytes);
    else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
    const id = Array.from(bytes, (b) => abc[b % abc.length]).join('');
    if (id !== DEFAULT_AGENT_ID && !used.has(id)) return id;
  }
}

export function effectiveAgentMode(
  global: 'off' | 'paper' | 'live' | undefined, a: McpAgent | null, accountMode?: 'paper' | 'live',
): 'off' | 'paper' | 'live' {
  if (!a || (global !== 'paper' && global !== 'live')) return 'off';
  if (global === 'paper') return 'paper';
  if (accountMode !== undefined && accountMode !== 'live') return 'paper';
  return a.mode === 'live' ? 'live' : 'paper';
}

const GLOBAL_DEFAULTS = { maxOrderUsd: 25, dailySpendUsd: 100, minEdgeCents: 3, maxOpenPositions: 10 };

export interface EffectiveCaps {
  maxOrderUsd: number; dailySpendUsd: number; minEdgeCents: number;
  agentBinds: { maxOrderUsd: boolean; dailySpendUsd: boolean; minEdgeCents: boolean };
  global: { maxOrderUsd: number; dailySpendUsd: number; minEdgeCents: number; maxOpenPositions: number };
}

export function effectiveCaps(c: Cfg, rules: McpAgentRules): EffectiveCaps {
  const g = {
    maxOrderUsd: c?.mcpMaxOrderUsd ?? GLOBAL_DEFAULTS.maxOrderUsd,
    dailySpendUsd: c?.mcpDailySpendUsd ?? GLOBAL_DEFAULTS.dailySpendUsd,
    minEdgeCents: c?.mcpMinEdgeCents ?? GLOBAL_DEFAULTS.minEdgeCents,
    maxOpenPositions: c?.mcpMaxPositions ?? GLOBAL_DEFAULTS.maxOpenPositions,
  };
  const order = rules.maxOrderUsd !== null && rules.maxOrderUsd < g.maxOrderUsd;
  const day = rules.dailySpendUsd !== null && rules.dailySpendUsd < g.dailySpendUsd;
  const edge = rules.minEdgeCents !== null && rules.minEdgeCents > g.minEdgeCents;
  return {
    maxOrderUsd: order ? rules.maxOrderUsd as number : g.maxOrderUsd,
    dailySpendUsd: day ? rules.dailySpendUsd as number : g.dailySpendUsd,
    minEdgeCents: edge ? rules.minEdgeCents as number : g.minEdgeCents,
    agentBinds: { maxOrderUsd: order, dailySpendUsd: day, minEdgeCents: edge },
    global: g,
  };
}

const catList = (cats: readonly string[]): string => {
  const names = cats.map((c) => AGENT_CATEGORIES.find((x) => x.id === c)?.label ?? c);
  return names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`;
};
const hoursTxt = (h: number): string => (h >= 72 && Math.abs(h / 24 - Math.round(h / 24)) < 1e-9
  ? `${Math.round(h / 24)} days` : `${h}h`);

export function rulesInWords(r: McpAgentRules): string[] {
  const out: string[] = [];
  if (r.categoriesAllow?.length) out.push(`Only ${catList(r.categoriesAllow)}`);
  if (r.categoriesDeny?.length) out.push(`Never ${catList(r.categoriesDeny)}`);
  if (r.minPriceCents !== null && r.maxPriceCents !== null) out.push(`${r.minPriceCents}–${r.maxPriceCents}¢ entries`);
  else if (r.minPriceCents !== null) out.push(`Entries ≥ ${r.minPriceCents}¢`);
  else if (r.maxPriceCents !== null) out.push(`Entries ≤ ${r.maxPriceCents}¢`);
  if (r.maxHoursToClose !== null) out.push(`Closes within ${hoursTxt(r.maxHoursToClose)}`);
  if (r.minHoursToClose !== null) out.push(`≥ ${hoursTxt(r.minHoursToClose)} to close`);
  if (r.sides !== 'both') out.push(`${r.sides.toUpperCase()} only`);
  if (r.maxOpenPositions === 0 || r.maxContractsPerMarket === 0) out.push('Forecasts only — no orders');
  else {
    if (r.maxContractsPerMarket !== null) out.push(`≤ ${r.maxContractsPerMarket} contracts/market`);
    if (r.maxOpenPositions !== null) out.push(`≤ ${r.maxOpenPositions} positions`);
  }
  if (r.minEdgeCents !== null) out.push(`Edge ≥ ${r.minEdgeCents}¢`);
  return out;
}


export const AGENT_FILE_KIND = 'kryptTraderAgent';

export interface AgentShare {
  name: string; emoji: string; color: string; guide: string; rules: McpAgentRules;
}

export function agentForShare(a: McpAgent): AgentShare {
  return { name: a.name, emoji: a.emoji, color: a.color, guide: a.guide, rules: cleanRules(a.rules) };
}

export function agentExportJson(a: McpAgent): string {
  return JSON.stringify({ [AGENT_FILE_KIND]: 1, agent: agentForShare(a) }, null, 2);
}

export type AgentImport = { ok: true; agent: McpAgent } | { ok: false; error: string };

export function parseAgentImport(text: string, taken: Iterable<string>, now = new Date()): AgentImport {
  let parsed: unknown;
  if (text.length > 64 * 1024) return { ok: false, error: 'That file is too big to be an agent.' };
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, error: 'Not valid JSON.' };
  }
  const p = parsed as Record<string, unknown> | null;
  if (!p || typeof p !== 'object' || p[AGENT_FILE_KIND] !== 1 || !p.agent || typeof p.agent !== 'object') {
    return { ok: false, error: 'Not a Krypt Trader agent file.' };
  }
  const src = p.agent as Record<string, unknown>;
  const ts = now.toISOString();
  const agent = cleanAgent({
    id: newAgentId(taken), name: src.name, emoji: src.emoji, color: src.color,
    guide: src.guide, rules: src.rules, mode: 'paper', enabled: true, createdAt: ts, updatedAt: ts,
  });
  return agent ? { ok: true, agent } : { ok: false, error: 'The agent in that file could not be read.' };
}
