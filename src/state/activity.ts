import type { CoinOptimizeResult, Crypto15mBacktest } from '@shared/types';
import { cleanAgentName, isValidAgentId } from '@shared/agents';


export type BacktestEngine = '15m' | 'main' | 'script';

export type ActivityEvent =
  | {
    kind: 'backtest';
    engine: BacktestEngine;
    strategy: string;
    days: number | null;
    trades: number | null;
    netCents: number | null;
    winRatePct: number | null;
    totalPnlUsd: number | null;
    t: number | null;
    equity: number[];
  }
  | {
    kind: 'optimizer';
    coin: string;
    granularityH: number | null;
    days: number | null;
    swept: number | null;
    winner: string | null;
    winnerNetCents: number | null;
    slots: { start: number; end: number; name: string }[];
  }
  | {
    kind: 'script';
    op: 'saved' | 'created' | 'validated' | 'enabled' | 'disabled' | 'autoDisabled';
    name: string | null;
    id: string | null;
    ok: boolean;
    errors: number | null;
    detail: string | null;
  }
  | { kind: 'preset'; what: 'strategy' | 'profile'; name: string; ok: boolean }
  | {
    kind: 'manualOrder';
    op: 'submit' | 'close' | 'cancel';
    ok: boolean;
    ticker: string | null;
    side: 'yes' | 'no' | null;
    action: 'buy' | 'sell' | null;
    status: string | null;
    filled: number | null;
    avgCents: number | null;
    message: string;
  }
  | {
    kind: 'aiAnalysis';
    ticker: string;
    title: string | null;
    provider: string;
    verdict: 'cheap' | 'rich' | 'fair' | 'unclear';
    fairCents: number | null;
    confidence: 'low' | 'medium' | 'high';
  }
  | { kind: 'rule'; ruleKind: 'stop' | 'take' | 'alert' | null; ticker: string | null; message: string }
  | {
    kind: 'agent';
    mode: 'paper' | 'live' | 'action' | 'off';
    message: string;
    approvalId: number | null;
    decision: 'approved' | 'rejected' | null;
  }
  | { kind: 'halt'; scope: 'daily' | 'c15TakeProfit'; reason: string }
  | AgentCallActivity;

export interface AgentCallActivity {
  kind: 'agentCall';
  call: 'call' | 'connect';
  client: string;
  transport: string | null;
  model: string | null;
  tool: string | null;
  outcome: 'ok' | 'refused' | 'error';
  reason: string | null;
  summary: string;
  ticker: string | null;
  fairCents: number | null;
  edgeCents: number | null;
  midCents: number | null;
  side: 'yes' | 'no' | null;
  mode: 'paper' | 'live' | null;
  durationMs: number | null;
  suppressed: number;
  agentId?: string | null;
  agentName?: string | null;
}

export type ActivityKind = ActivityEvent['kind'];

export interface ActivityRecord {
  seq: number;
  at: number;
  ev: ActivityEvent;
}

export type ActivityListener = (rec: ActivityRecord) => void;

export const ACTIVITY_CAP = 200;
export const AGENT_CALL_CAP = 120;

export interface ActivityBus {
  publish(ev: ActivityEvent, now?: number): ActivityRecord;
  subscribe(fn: ActivityListener): () => void;
  recent(windowMs: number, now?: number): ActivityRecord[];
  size(): number;
  clear(): void;
}

function ring(cap: number) {
  const slots: (ActivityRecord | undefined)[] = new Array(cap);
  let head = 0;
  let count = 0;
  return {
    push(rec: ActivityRecord) {
      slots[head] = rec;
      head = (head + 1) % cap;
      count = Math.min(cap, count + 1);
    },
    each(fn: (r: ActivityRecord) => void) {
      for (let i = 0; i < count; i++) {
        const r = slots[(head - count + i + cap) % cap];
        if (r) fn(r);
      }
    },
    get count() { return count; },
    clear() { slots.fill(undefined); head = 0; count = 0; },
  };
}

export function createActivityBus(cap = ACTIVITY_CAP, agentCap = AGENT_CALL_CAP): ActivityBus {
  const main = ring(cap);
  const calls = ring(agentCap);
  let seq = 0;
  const listeners = new Set<ActivityListener>();
  return {
    publish(ev, now = Date.now()) {
      const rec: ActivityRecord = { seq: ++seq, at: now, ev };
      (ev.kind === 'agentCall' ? calls : main).push(rec);
      for (const fn of [...listeners]) {
        try { fn(rec); } catch {}
      }
      return rec;
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => { listeners.delete(fn); };
    },
    recent(windowMs, now = Date.now()) {
      const out: ActivityRecord[] = [];
      const take = (r: ActivityRecord) => { if (now - r.at <= windowMs && r.at <= now) out.push(r); };
      main.each(take);
      calls.each(take);
      return out.sort((a, b) => a.seq - b.seq);
    },
    size: () => main.count + calls.count,
    clear() {
      main.clear();
      calls.clear();
    },
  };
}

export const activityBus: ActivityBus = createActivityBus();

export function publishActivity(build: ActivityEvent | (() => ActivityEvent | null), bus: ActivityBus = activityBus): void {
  try {
    const ev = typeof build === 'function' ? build() : build;
    if (ev) bus.publish(ev);
  } catch {}
}


export const REPLAY_WINDOW_MS = 3 * 60_000;
export const REPLAY_BEAT_MS = 1_400;
export const REPLAY_MAX = 12;

export function replayPlan(
  records: ActivityRecord[], opts: { beatMs?: number; max?: number; firstMs?: number } = {},
): { rec: ActivityRecord; delayMs: number }[] {
  const beat = opts.beatMs ?? REPLAY_BEAT_MS;
  const max = opts.max ?? REPLAY_MAX;
  const first = opts.firstMs ?? 600;
  const keep = [...records].sort((a, b) => a.at - b.at || a.seq - b.seq).slice(-max);
  return keep.map((rec, i) => ({ rec, delayMs: first + i * beat }));
}


function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

export function downsample(xs: number[], n = 48): number[] {
  const clean = xs.filter((x) => Number.isFinite(x));
  if (clean.length <= n) return clean;
  const out: number[] = [];
  for (let i = 0; i < n; i++) out.push(clean[Math.round((i * (clean.length - 1)) / (n - 1))]);
  return out;
}

export function backtestEvent(
  engine: BacktestEngine, strategy: string, days: number | null,
  r: (Crypto15mBacktest & { tStat?: number | null }) | null | undefined,
): ActivityEvent | null {
  if (!r) return null;
  const n = num(r.n);
  const traded = n !== null && n > 0;
  return {
    kind: 'backtest', engine, strategy, days,
    trades: n,
    netCents: traded ? num(r.netEvCentsPerContract) : null,
    winRatePct: traded && num(r.winRate) !== null ? (r.winRate as number) * 100 : null,
    totalPnlUsd: traded ? num(r.totalPnlUsd) : null,
    t: num(r.tStat),
    equity: Array.isArray(r.equity) ? downsample(r.equity.map((p) => p?.value as number)) : [],
  };
}

export function optimizerEvent(r: CoinOptimizeResult | null | undefined): ActivityEvent | null {
  if (!r) return null;
  const w = r.coinWinner;
  return {
    kind: 'optimizer',
    coin: r.coin,
    granularityH: num(r.granularityH),
    days: num(r.sinceDays),
    swept: num(r.strategiesSwept),
    winner: w?.name ?? null,
    winnerNetCents: w && w.n > 0 ? num(w.netCents) : null,
    slots: (r.schedule ?? [])
      .filter((s) => !!s.winner)
      .map((s) => ({ start: s.start, end: s.end, name: s.winner as string })),
  };
}

export function ruleEvent(d: { rule?: unknown; message?: unknown } | null | undefined): ActivityEvent | null {
  if (!d || typeof d.message !== 'string') return null;
  const rule = (d.rule && typeof d.rule === 'object') ? d.rule as Record<string, unknown> : {};
  const k = rule.kind;
  return {
    kind: 'rule',
    ruleKind: k === 'stop' || k === 'take' || k === 'alert' ? k : null,
    ticker: typeof rule.ticker === 'string' ? rule.ticker : null,
    message: d.message,
  };
}

function str(v: unknown, max: number): string | null {
  if (typeof v !== 'string') return null;
  const t = v.replace(/\s+/g, ' ').trim();
  if (!t) return null;
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

export function agentCallEvent(d: unknown): AgentCallActivity | null {
  if (!d || typeof d !== 'object') return null;
  const o = d as Record<string, unknown>;
  const client = str(o.client, 60);
  const summary = str(o.summary, 120);
  if (!client || !summary) return null;
  const outcome = o.outcome === 'ok' || o.outcome === 'refused' || o.outcome === 'error' ? o.outcome : null;
  if (!outcome) return null;
  const fair = num(o.fairCents);
  const mid = num(o.midCents);
  const dur = num(o.durationMs);
  const sup = num(o.suppressed);
  return {
    kind: 'agentCall',
    call: o.kind === 'connect' ? 'connect' : 'call',
    client,
    transport: str(o.transport, 24),
    model: str(o.model, 40),
    tool: str(o.tool, 48),
    outcome,
    reason: str(o.reason, 160),
    summary,
    ticker: str(o.ticker, 48),
    fairCents: fair !== null && fair >= 1 && fair <= 99 ? fair : null,
    edgeCents: num(o.edgeCents),
    midCents: mid !== null && mid >= 1 && mid <= 99 ? mid : null,
    side: o.side === 'yes' || o.side === 'no' ? o.side : null,
    mode: o.mode === 'paper' || o.mode === 'live' ? o.mode : null,
    durationMs: dur !== null && dur >= 0 ? Math.round(dur) : null,
    suppressed: sup !== null && sup > 0 ? Math.trunc(sup) : 0,
    agentId: isValidAgentId(o.agentId) ? o.agentId : null,
    agentName: typeof o.agentName === 'string' ? cleanAgentName(o.agentName, '') || null : null,
  };
}

export function agentEvent(d: { mode?: unknown; message?: unknown; approvalId?: unknown } | null | undefined): ActivityEvent | null {
  if (!d || typeof d.message !== 'string') return null;
  const m = d.mode;
  const id = num(d.approvalId);
  return {
    kind: 'agent',
    mode: m === 'paper' || m === 'live' || m === 'action' || m === 'off' ? m : 'action',
    message: d.message,
    approvalId: id !== null ? Math.trunc(id) : null,
    decision: null,
  };
}
