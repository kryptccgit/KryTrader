import type { ForecastScoreboard, ForecastVerdict, ForecasterScore } from '@shared/market';
import type { AgentCallActivity, ActivityEvent } from '../../state/activity';
import type { McpAgent } from '@shared/agents';
import { agentIdentity, hubAgentIdentity, type AgentIdentity } from '../../utils/agents';
import { MEMBER_IDS, PERSONAS, type MemberId } from './roster';


export const MIN_REAL_FORECASTERS = 2;

export interface Call {
  fair: number;
  mid: number | null;
  at: number;
}

export interface Forecaster {
  who: AgentIdentity;
  calls: Map<string, Call>;
  score: Pick<ForecasterScore, 'n' | 'nPaired' | 'brierAi' | 'brierAiPaired' | 'brierMarket' | 'skill' | 'verdict'> | null;
  total: number;
  lastAt: number;
}

export interface Seat {
  member: MemberId;
  f: Forecaster;
  label: string;
}

function ts(v: string | null | undefined): number {
  if (!v) return 0;
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : `${v.replace(' ', 'T')}Z`);
  return Number.isFinite(t) ? t : 0;
}

export function forecastersFrom(
  board: ForecastScoreboard | null | undefined, agents: readonly McpAgent[] | null = null,
): Map<string, Forecaster> {
  const out = new Map<string, Forecaster>();
  for (const r of board?.byForecaster ?? []) {
    const who = hubAgentIdentity({ agentId: r.agentId, client: r.client, model: r.model, source: r.source }, agents);
    if (out.has(who.seatId)) continue;
    const calls = new Map<string, Call>();
    for (const o of r.open ?? []) {
      if (calls.has(o.ticker)) continue;
      if (!(o.fairValueCents >= 1 && o.fairValueCents <= 99)) continue;
      calls.set(o.ticker, { fair: o.fairValueCents, mid: o.marketMidCents ?? null, at: ts(o.createdAt) });
    }
    out.set(who.seatId, {
      who, calls, total: r.total, lastAt: ts(r.lastAt),
      score: r.n > 0 ? {
        n: r.n, nPaired: r.nPaired, brierAi: r.brierAi, brierAiPaired: r.brierAiPaired,
        brierMarket: r.brierMarket, skill: r.skill, verdict: r.verdict,
      } : null,
    });
  }
  return out;
}

export function noteLiveForecast(
  roster: Map<string, Forecaster>, ev: ActivityEvent, at: number, agents: readonly McpAgent[] | null = null,
): { ticker: string; seatId: string } | null {
  let who: AgentIdentity;
  let ticker: string | null;
  let fair: number | null;
  let mid: number | null = null;
  if (ev.kind === 'agentCall') {
    const c = ev as AgentCallActivity;
    if (c.call !== 'call' || c.tool !== 'record_forecast' || c.outcome !== 'ok') return null;
    who = hubAgentIdentity(c, agents);
    ticker = c.ticker;
    fair = c.fairCents;
    mid = c.midCents;
  } else if (ev.kind === 'aiAnalysis') {
    who = agentIdentity({ source: 'panel', model: ev.provider === 'openai' ? 'gpt' : ev.provider === 'anthropic' ? 'claude' : ev.provider });
    ticker = ev.ticker;
    fair = ev.fairCents;
  } else {
    return null;
  }
  if (!ticker || fair === null || !(fair >= 1 && fair <= 99)) return null;
  let f = roster.get(who.seatId);
  if (!f) {
    f = { who, calls: new Map(), score: null, total: 0, lastAt: at };
    roster.set(who.seatId, f);
  }
  f.total++;
  f.lastAt = Math.max(f.lastAt, at);
  const prev = f.calls.get(ticker);
  if (!prev || prev.at <= at) f.calls.set(ticker, { fair, mid, at });
  return { ticker, seatId: who.seatId };
}

const SEAT_ORDER = [2, 3, 1, 4, 0, 5];

export function assignSeats(roster: Map<string, Forecaster>, max = MEMBER_IDS.length): Seat[] {
  const fs = [...roster.values()]
    .filter((f) => f.total > 0 || f.calls.size > 0)
    .sort((a, b) => b.lastAt - a.lastAt || b.total - a.total)
    .slice(0, Math.min(max, MEMBER_IDS.length));
  const seats = fs.map((f, i) => ({ member: MEMBER_IDS[SEAT_ORDER[i]], f, label: f.who.label }));
  const dup = new Map<string, number>();
  for (const s of seats) dup.set(s.label, (dup.get(s.label) ?? 0) + 1);
  for (const s of seats) {
    if ((dup.get(s.label) ?? 0) > 1) s.label = `${s.label} (${s.f.who.seatId.split('|').pop() || '?'})`;
  }
  return seats;
}

export type CouncilChoice = 'personas' | 'agents';

export function councilMode(choice: CouncilChoice | null, realCount: number): CouncilChoice {
  if (realCount < MIN_REAL_FORECASTERS) return 'personas';
  return choice ?? 'agents';
}

export function seatValue(seat: Seat | undefined, ticker: string | null): number | null {
  if (!seat || !ticker) return null;
  return seat.f.calls.get(ticker)?.fair ?? null;
}

export function cents(v: number): string {
  return `${Math.round(v)}¢`;
}

export function plateText(seat: Seat, ticker: string | null): string {
  const v = seatValue(seat, ticker);
  const name = seat.f.who.emoji ? `${seat.f.who.emoji} ${seat.label}` : seat.label;
  return `${name} · ${v === null ? '—' : cents(v)}`;
}

export function seatVote(seat: Seat | undefined, ticker: string | null): boolean | null {
  if (!seat || !ticker) return null;
  const c = seat.f.calls.get(ticker);
  if (!c || c.mid === null || c.fair === c.mid) return null;
  return c.fair > c.mid;
}

export function seatLine(seat: Seat, ticker: string): string | null {
  const c = seat.f.calls.get(ticker);
  if (!c) return null;
  const line = c.mid === null ? `fair ${cents(c.fair)}` : `fair ${cents(c.fair)} · mid was ${cents(c.mid)}`;
  return seat.f.who.motto ? `${line} · “${seat.f.who.motto}”` : line;
}


export interface ScoreLine {
  name: string;
  color: string;
  value: string;
  sub?: string;
  bar: number | null;
  signed?: boolean;
  tone: 'good' | 'bad' | 'neutral' | 'none';
}

export interface ScoreView { title: string; caption: string; lines: ScoreLine[] }

const TONE_OF: Record<ForecastVerdict, ScoreLine['tone']> = {
  'ai-better': 'good', 'market-better': 'bad', indistinguishable: 'neutral', 'too-few': 'neutral',
};

export function agentScoreView(seats: Seat[]): ScoreView {
  const lines = seats.map((s): ScoreLine & { k: number } => {
    const sc = s.f.score;
    const skill = sc?.skill ?? null;
    const brier = sc ? (sc.brierAiPaired ?? sc.brierAi) : null;
    const open = s.f.calls.size;
    const sub = sc && brier !== null
      ? `Brier ${brier.toFixed(3)}${sc.brierMarket !== null ? ` vs mkt ${sc.brierMarket.toFixed(3)}` : ''} · ${sc.nPaired} settled`
      : `nothing settled yet · ${open} open`;
    return {
      name: s.label, color: s.f.who.color, sub,
      value: skill === null ? '—' : `${skill > 0 ? '+' : skill < 0 ? '−' : ''}${Math.abs(skill * 100).toFixed(0)}%`,
      bar: skill === null ? null : Math.max(-1, Math.min(1, skill * 2)),
      signed: true,
      tone: skill === null || !sc ? 'none' : TONE_OF[sc.verdict],
      k: skill === null ? -Infinity : skill,
    };
  });
  lines.sort((a, b) => b.k - a.k);
  return { title: 'WHO CALLED IT?', caption: 'skill vs market · settled', lines: lines.map(({ k: _k, ...l }) => l) };
}

export function personaScoreView(rows: { id: MemberId; right: number; n: number }[]): ScoreView {
  const sorted = [...rows].sort((a, b) => (b.n ? b.right / b.n : -1) - (a.n ? a.right / a.n : -1));
  return {
    title: 'WHO CALLED IT?',
    caption: 'call accuracy · settled trades',
    lines: sorted.map((r) => {
      const pct = r.n ? (r.right / r.n) * 100 : null;
      return {
        name: PERSONAS[r.id].name, color: PERSONAS[r.id].color,
        value: pct === null ? '—' : `${pct.toFixed(0)}%`,
        bar: pct === null ? null : pct / 100,
        tone: pct === null ? 'none' : pct >= 55 ? 'good' : pct < 45 ? 'bad' : 'neutral',
      };
    }),
  };
}

export function recentTickers(seats: Seat[], max = 3): string[] {
  const latest = new Map<string, number>();
  for (const s of seats) {
    for (const [t, c] of s.f.calls) latest.set(t, Math.max(latest.get(t) ?? 0, c.at));
  }
  return [...latest.entries()].sort((a, b) => b[1] - a[1]).slice(0, max).map(([t]) => t).reverse();
}
