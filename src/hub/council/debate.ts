import type { BotPosition, SignalRow } from '@shared/types';
import type { ActivityEvent } from '../../state/activity';
import { aiName } from '../engine/jobs';
import type { HubData } from '../data';
import { subject } from '../text';
import type { Member, Pose } from './members';
import { MEMBER_IDS, PERSONAS, line, type Features, type MemberId, type Speaker } from './roster';
import type { Bunker, ScoreRow } from './room';
import { cents, personaScoreView, seatLine, seatValue, seatVote, type Seat } from './seats';


export const OVERRULE_RATE = 0.12;

export const PERSUADABLE: MemberId[] = ['quant', 'fomo', 'doubt', 'risk'];

export function readTheRoom(votes: Record<MemberId, boolean>, target: boolean): Record<MemberId, boolean> {
  const out = { ...votes };
  const majority = () => {
    const y = MEMBER_IDS.filter((id) => out[id]).length;
    return target ? y > MEMBER_IDS.length - y : MEMBER_IDS.length - y > y;
  };
  for (const id of PERSUADABLE) {
    if (majority()) break;
    out[id] = target;
  }
  return out;
}

export type Phase = 'idle' | 'present' | 'argue' | 'vote' | 'verdict' | 'out';

interface Cue { at: number; done: boolean; run: () => void }

export interface DebateView {
  n: number;
  phase: Phase;
  t: number;
  sig: SignalRow | null;
  f: Features;
  votes: Record<MemberId, boolean>;
  yes: number;
  no: number;
  shownVotes: number;
  approved: boolean | null;
  stampText: string;
  stampSub: string;
  stampT: number | null;
  outT: number;
  agent?: { ticker: string; kicker: string; dirLine: string; facts: string; stampColor: string };
  doneAt?: number;
}

export interface CouncilHost {
  members: Record<MemberId, Member>;
  bunker: Bunker;
  say(who: Speaker, text: string, opts?: { life?: number; force?: boolean }): boolean;
  log(text: string, tone: 'win' | 'loss' | 'gold' | 'neutral' | 'whale' | 'momo' | 'test'): void;
  speaking(who: Speaker | null): void;
  coins(n: number): void;
}

const T_ARGUE = 0.9;
const T_VOTE = 5.6;
const T_VERDICT = 7.6;
const T_OUT = 10.6;
const T_DONE = 11.4;

function money(v: number): string {
  return `$${Math.abs(v).toFixed(2)}`;
}

function pick<T>(xs: T[]): T {
  return xs[Math.floor(Math.random() * xs.length)];
}

export class Council {
  debate: DebateView | null = null;
  private cues: Cue[] = [];
  private queue: SignalRow[] = [];
  private seenSig = new Set<string>();
  private seenPos = new Map<number, string>();
  private primed = false;
  private runId: number | null = null;
  private n = 0;
  private gap = 1.2;
  private latest: HubData | null = null;
  private score: Record<MemberId, { right: number; n: number }> = Object.fromEntries(MEMBER_IDS.map((id) => [id, { right: 0, n: 0 }])) as Record<MemberId, { right: number; n: number }>;
  private scoreDirty = true;
  private scoreCd = 0;
  private settleQ: BotPosition[] = [];
  private settleCd = 6;
  private ruleVotes = new Map<number, Record<MemberId, boolean>>();
  mood: Speaker = 'quant';
  paydayT = 0;
  mode: 'personas' | 'agents' = 'personas';
  private seats: Seat[] = [];
  private agenda: { ticker: string; title: string | null }[] = [];
  seatOf(id: MemberId): Seat | undefined {
    return this.seats.find((x) => x.member === id);
  }
  get currentTicker(): string | null {
    return this.debate?.agent?.ticker ?? null;
  }
  private ai = new Map<string, { ev: Extract<ActivityEvent, { kind: 'aiAnalysis' }>; at: number }>();

  constructor(private host: CouncilHost) {}


  setSeats(seats: Seat[] | null): void {
    const mode = seats ? 'agents' : 'personas';
    const changed = mode !== this.mode
      || (seats && seats.map((x) => x.f.who.seatId).join() !== this.seats.map((x) => x.f.who.seatId).join());
    this.seats = seats ?? [];
    if (!changed) return;
    this.mode = mode;
    this.abort();
    if (mode === 'personas') {
      this.agenda = [];
      this.scoreDirty = true;
    }
  }

  noteAgenda(ticker: string, title: string | null = null): void {
    if (this.agenda.some((a) => a.ticker === ticker)) return;
    if (this.debate?.agent?.ticker === ticker && this.debate.phase !== 'out') return;
    this.agenda.push({ ticker, title });
    if (this.agenda.length > 4) this.agenda.splice(0, this.agenda.length - 4);
  }

  private abort(): void {
    this.debate = null;
    this.cues = [];
    this.gap = 0.8;
    for (let i = 0; i < MEMBER_IDS.length; i++) this.host.bunker?.setVote(i, null);
    for (const id of MEMBER_IDS) this.host.members?.[id]?.set('idle');
  }


  noteAnalysis(ev: Extract<ActivityEvent, { kind: 'aiAnalysis' }>, at: number): void {
    this.ai.delete(ev.ticker);
    this.ai.set(ev.ticker, { ev, at });
    if (this.ai.size > 50) this.ai.delete(this.ai.keys().next().value as string);
  }

  aiCite(ticker: string, now = Date.now()): string | null {
    const a = this.ai.get(ticker);
    if (!a || now - a.at > 24 * 3600_000) return null;
    const mins = Math.max(0, Math.round((now - a.at) / 60_000));
    const when = mins < 1 ? 'just now' : mins < 60 ? `${mins}m ago` : `${Math.round(mins / 60)}h ago`;
    const who = aiName(a.ev.provider);
    const fair = a.ev.fairCents !== null ? `fair ${Math.round(a.ev.fairCents)}¢` : 'no fair value';
    return `${who}, ${when}: ${fair} · ${a.ev.verdict}`;
  }

  ingest(d: HubData): void {
    this.latest = d;
    const runId = d.account?.sessionRunId ?? 0;
    if (this.primed && this.runId !== null && runId !== this.runId) {
      this.seenSig.clear();
      this.seenPos.clear();
      this.primed = false;
      for (const id of MEMBER_IDS) this.score[id] = { right: 0, n: 0 };
      this.scoreDirty = true;
    }
    this.runId = runId;
    for (const s of d.signals.slice(0, 60)) {
      const k = `${s.source}:${s.id}`;
      if (this.seenSig.has(k)) continue;
      this.seenSig.add(k);
      if (!this.primed && this.queue.length) continue;
      this.queue.push(s);
    }
    if (this.queue.length > 4) {
      this.queue.sort((a, b) => (b.source === 'whale' ? 1 : 0) - (a.source === 'whale' ? 1 : 0) || (b.dollarValue ?? 0) - (a.dollarValue ?? 0));
      this.queue.length = 4;
    }
    if (this.seenSig.size > 4000) this.seenSig = new Set(d.signals.map((x) => `${x.source}:${x.id}`));

    for (const p of d.positions) {
      const sig = p.resolved ? `r:${p.outcomeCorrect}` : 'o';
      const prev = this.seenPos.get(p.id);
      this.seenPos.set(p.id, sig);
      if (!this.primed || prev === sig || !p.resolved || p.outcomeCorrect === null) continue;
      this.settle(p, this.mode === 'personas');
    }
    if (this.seenPos.size > 6000) {
      const keep = new Set(d.positions.map((p) => p.id));
      for (const id of this.seenPos.keys()) if (!keep.has(id)) this.seenPos.delete(id);
    }
    this.primed = true;
  }

  private features(x: { ticker: string; title: string; category: string; direction: 'yes' | 'no'; price: number | null; edge: number | null; conf: number | null; whale: boolean; whaleUsd: number | null }): Features {
    const a = this.latest?.account;
    const cap = this.latest?.config?.maxOpenPositions;
    return {
      subj: subject(x.ticker, x.title),
      title: x.title,
      dir: x.direction === 'yes' ? 'YES' : 'NO',
      price: x.price !== null && x.price >= 1 && x.price <= 99 ? Math.round(x.price) : null,
      edge: x.edge,
      conf: x.conf,
      whale: x.whale,
      whaleUsd: x.whaleUsd,
      cat: x.category,
      open: typeof a?.openCount === 'number' ? a.openCount : null,
      cap: typeof cap === 'number' && cap > 0 ? cap : null,
    };
  }

  private sigFeatures(s: SignalRow): Features {
    return this.features({
      ticker: s.ticker, title: s.title, category: s.category, direction: s.direction,
      price: s.priceCents, edge: s.edgePts ?? null, conf: s.confidence ?? null,
      whale: s.source === 'whale', whaleUsd: s.source === 'whale' && s.dollarValue ? s.dollarValue : null,
    });
  }

  private posFeatures(p: BotPosition): Features {
    return this.features({
      ticker: p.ticker, title: p.title, category: p.category, direction: p.direction,
      price: p.avgFillPriceCents ?? p.limitPriceCents, edge: p.edgePts ?? null, conf: p.confidence ?? null,
      whale: p.signalSource === 'whale', whaleUsd: null,
    });
  }

  private settle(p: BotPosition, stage = true): void {
    const won = p.outcomeCorrect === 1;
    const votes = this.ruleVotes.get(p.signalId) ?? this.rules(this.posFeatures(p));
    for (const id of MEMBER_IDS) {
      const s = this.score[id];
      s.n++;
      if (votes[id] === won) s.right++;
    }
    this.scoreDirty = true;
    if (!stage) return;
    this.settleQ.push(p);
    if (this.settleQ.length > 6) {
      this.settleQ.sort((a, b) => Math.abs(b.pnlUsd ?? 0) - Math.abs(a.pnlUsd ?? 0));
      this.settleQ.length = 6;
    }
  }

  private rules(f: Features): Record<MemberId, boolean> {
    return Object.fromEntries(MEMBER_IDS.map((id) => [id, PERSONAS[id].votes(f)])) as Record<MemberId, boolean>;
  }

  scoreRows(): ScoreRow[] {
    return MEMBER_IDS.map((id) => ({ id, right: this.score[id].right, n: this.score[id].n }));
  }


  update(dt: number): void {
    this.paydayT = Math.max(0, this.paydayT - dt);
    this.scoreCd -= dt;
    if (this.scoreDirty && this.scoreCd <= 0 && this.mode === 'personas') {
      this.scoreCd = 0.5;
      this.scoreDirty = false;
      this.host.bunker.setScore(personaScoreView(this.scoreRows()));
    }

    const d = this.debate;
    if (!d) {
      this.gap -= dt;
      if (this.gap <= 0) {
        if (this.mode === 'agents') {
          if (this.agenda.length) this.beginAgents(this.agenda.shift()!);
        } else if (this.queue.length) {
          this.begin(this.queue.shift()!);
        }
      }
    } else {
      d.t += dt;
      for (const c of this.cues) {
        if (!c.done && d.t >= c.at) { c.done = true; c.run(); }
      }
      if (d.stampT !== null) d.stampT += dt;
      if (d.phase === 'out') d.outT = Math.min(1, d.outT + dt / 0.7);
      if (d.t >= (d.doneAt ?? T_DONE)) {
        this.debate = null;
        this.gap = 0.6;
        for (let i = 0; i < MEMBER_IDS.length; i++) this.host.bunker.setVote(i, null);
      }
    }

    this.settleCd -= dt;
    const quiet = !d || d.phase === 'present' || d.phase === 'out' || d.phase === 'idle';
    if (this.settleCd <= 0 && quiet && this.settleQ.length && this.mode === 'personas') {
      this.settleCd = 5.5;
      this.react(this.settleQ.shift()!);
    }
  }

  private pose(id: MemberId, p: Pose, dur: number): void {
    const m = this.host.members[id];
    m.set(p);
    const until = (this.debate?.t ?? 0) + dur;
    const d = this.debate;
    if (d) this.cues.push({ at: until, done: false, run: () => { if (m.pose === p) m.set('idle'); } });
    else window.setTimeout(() => { if (m.pose === p) m.set('idle'); }, dur * 1000);
  }

  private speak(who: Speaker, text: string, dur = 1.8, force = false): void {
    if (this.host.say(who, text, { force, life: 2.9 })) {
      this.host.speaking(who);
      if (who !== 'chair') {
        this.host.members[who].talking = dur;
        this.mood = who;
        this.host.bunker.setMood(PERSONAS[who].color);
      }
    }
  }


  private begin(sig: SignalRow): void {
    const f = this.sigFeatures(sig);
    const rule = this.rules(f);
    this.ruleVotes.set(sig.id, rule);
    if (this.ruleVotes.size > 300) this.ruleVotes.delete(this.ruleVotes.keys().next().value as number);
    const votes = Math.random() < OVERRULE_RATE ? { ...rule } : readTheRoom(rule, !!sig.traded);
    const yes = MEMBER_IDS.filter((id) => votes[id]).length;
    this.n++;
    const d: DebateView = {
      n: this.n, phase: 'present', t: 0, sig, f, votes, yes, no: MEMBER_IDS.length - yes,
      shownVotes: 0, approved: null, stampText: '', stampSub: '', stampT: null, outT: 0,
    };
    this.debate = d;
    this.cues = [];
    const B = this.host.bunker;
    B.holoPulse = 1;
    B.holoColor.set('#FFB547');
    B.feed(`#${d.n} ${f.subj}`.slice(0, 16));
    if (Math.random() < 0.45) this.at(0.3, () => this.speak('chair', line(PERSONAS.chair.pro(f)), 1.4));

    const pro = MEMBER_IDS.filter((id) => votes[id]);
    const con = MEMBER_IDS.filter((id) => !votes[id]);
    let opener: MemberId;
    if (f.whale && votes.fomo) opener = 'fomo';
    else if (votes.greed && Math.random() < 0.5) opener = 'greed';
    else if ((f.price ?? 0) >= 70 && !votes.panic) opener = 'panic';
    else opener = pick(MEMBER_IDS.filter((id) => id !== 'quant'));
    const order: MemberId[] = [opener];
    const other = (side: MemberId[]) => side.filter((id) => !order.includes(id) && id !== 'quant');
    const oppSide = votes[opener] ? con : pro;
    const reply = other(oppSide);
    if (reply.length) order.push(pick(reply));
    order.push('quant');
    const nearCap = f.open !== null && f.cap !== null && f.open / f.cap >= 0.85;
    if (!order.includes('risk') && (nearCap || (order.includes('greed') && Math.random() < 0.6))) order.push('risk');
    else {
      const rest = other(MEMBER_IDS);
      if (rest.length && Math.random() < 0.7) order.push(pick(rest));
    }
    let at = T_ARGUE;
    order.slice(0, 4).forEach((id) => {
      const mine = votes[id];
      const p = PERSONAS[id];
      const cite = id === 'quant' ? this.aiCite(sig.ticker) : null;
      const text = cite ?? line(mine ? p.pro(f) : p.con(f), mine ? 'yes.' : 'no.');
      this.at(at, () => {
        d.phase = 'argue';
        this.speak(id, text, 1.8);
        if (id === 'greed' && mine) { this.pose('greed', 'bang', 1.2); this.at(d.t + 0.35, () => { B.tableShake.v = 1; }); }
        else if (id === 'panic' && !mine) this.pose('panic', 'cower', 1.9);
        else if (id === 'risk' && !mine) this.pose('risk', 'whistle', 1.4);
        else if (id === 'doubt') this.pose('doubt', 'nod', 1.3);
        else this.pose(id, 'talk', 1.6);
        if (id === 'greed' && mine && !votes.panic) this.at(d.t + 0.5, () => this.pose('panic', 'cower', 1.2));
      });
      at += 0.95 + Math.random() * 0.35;
    });
    if (order.length >= 4 && Math.random() < 0.4) {
      this.at(at - 0.1, () => { this.speak('chair', 'ORDER! ORDER!', 1, true); B.bangGavel(2); });
    }

    this.at(T_VOTE, () => {
      d.phase = 'vote';
      this.host.speaking(null);
    });
    MEMBER_IDS.forEach((id, i) => {
      this.at(T_VOTE + 0.15 + i * 0.16, () => {
        this.host.members[id].set('vote');
        B.setVote(i, votes[id]);
        d.shownVotes++;
      });
    });

    this.at(T_VERDICT, () => this.verdict(d));
    this.at(T_OUT, () => {
      d.phase = 'out';
      for (const id of MEMBER_IDS) if (this.host.members[id].pose === 'vote') this.host.members[id].set('idle');
      B.holoColor.set('#FFB547');
    });
  }


  private beginAgents(item: { ticker: string; title: string | null }): void {
    const { ticker } = item;
    const seated = this.seats.filter((x) => seatValue(x, ticker) !== null);
    if (!seated.length) return;
    const title = item.title ?? ticker;
    const f = this.features({
      ticker, title, category: '', direction: 'yes', price: null, edge: null, conf: null, whale: false, whaleUsd: null,
    });
    const votesTri = Object.fromEntries(MEMBER_IDS.map((id) => [id, seatVote(this.seatOf(id), ticker)])) as Record<MemberId, boolean | null>;
    const votes = Object.fromEntries(MEMBER_IDS.map((id) => [id, votesTri[id] === true])) as Record<MemberId, boolean>;
    const yes = MEMBER_IDS.filter((id) => votesTri[id] === true).length;
    const no = MEMBER_IDS.filter((id) => votesTri[id] === false).length;
    const vals = seated.map((x) => seatValue(x, ticker) as number);
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const mids = seated.map((x) => x.f.calls.get(ticker)?.mid ?? null).filter((m): m is number => m !== null);
    this.n++;
    const d: DebateView = {
      n: this.n, phase: 'present', t: 0, sig: null, f, votes, yes, no,
      shownVotes: 0, approved: null, stampText: '', stampSub: '', stampT: null, outT: 0,
      agent: {
        ticker,
        kicker: `${ticker}  ·  ${seated.length} FORECAST${seated.length === 1 ? '' : 'S'}`,
        dirLine: lo === hi ? `fair ${cents(lo)}` : `fair ${cents(lo)}–${cents(hi)}`,
        facts: mids.length ? `mid was ${Math.min(...mids) === Math.max(...mids) ? cents(mids[0]) : `${cents(Math.min(...mids))}–${cents(Math.max(...mids))}`}` : 'no two-sided quote',
        stampColor: '#FFB547',
      },
    };
    this.debate = d;
    this.cues = [];
    const B = this.host.bunker;
    B.holoPulse = 1;
    B.holoColor.set('#FFB547');
    B.feed(`#${d.n} ${ticker}`.slice(0, 16));

    const order = [...seated].sort((a, b) => (b.f.calls.get(ticker)?.at ?? 0) - (a.f.calls.get(ticker)?.at ?? 0));
    let at = T_ARGUE;
    for (const x of order.slice(0, 5)) {
      const text = seatLine(x, ticker);
      if (!text) continue;
      this.at(at, () => {
        d.phase = 'argue';
        this.speak(x.member, text, 1.8);
        this.pose(x.member, 'talk', 1.6);
      });
      at += 1.05;
    }

    const voteAt = Math.max(T_VOTE, at + 0.4);
    this.at(voteAt, () => {
      d.phase = 'vote';
      this.host.speaking(null);
    });
    MEMBER_IDS.forEach((id, i) => {
      if (votesTri[id] === null) return;
      this.at(voteAt + 0.15 + i * 0.16, () => {
        this.host.members[id].set('vote');
        B.setVote(i, votesTri[id]);
        d.shownVotes++;
      });
    });

    const verdictAt = voteAt + 2.0;
    this.at(verdictAt, () => {
      d.phase = 'verdict';
      d.stampT = 0;
      d.stampText = yes && !no ? 'YES CHEAP' : no && !yes ? 'NO CHEAP' : yes && no ? 'SPLIT' : 'NO VOTE';
      d.stampSub = `${seated.length} call${seated.length === 1 ? '' : 's'} · ${d.agent!.dirLine}`;
      B.bangGavel(1);
      B.holoPulse = 1;
      this.speak('chair', 'THE FORECASTS ARE IN.', 1.2, true);
      this.host.log(`⚖️ #${d.n} ${ticker} · ${d.agent!.dirLine}${yes + no ? ` · ${yes}–${no}` : ''}`, 'gold');
    });
    this.at(verdictAt + 3.0, () => {
      d.phase = 'out';
      for (const id of MEMBER_IDS) if (this.host.members[id].pose === 'vote') this.host.members[id].set('idle');
    });
    d.doneAt = verdictAt + 3.8;
  }

  private at(t: number, run: () => void): void {
    this.cues.push({ at: t, done: false, run });
  }

  private verdict(d: DebateView): void {
    const B = this.host.bunker;
    const sig = d.sig;
    if (!sig) return;
    const now = this.latest?.signals.find((s) => s.id === sig.id && s.source === sig.source) ?? sig;
    const approved = now.traded;
    d.approved = approved;
    d.phase = 'verdict';
    d.stampT = 0;
    const majority = d.yes > d.no ? true : d.yes < d.no ? false : null;
    const f = d.f;
    const px = f.price !== null ? ` @ ${f.price}¢` : '';
    if (approved) {
      const pos = this.latest?.positions.find((p) => !p.resolved && p.ticker === sig.ticker && p.direction === sig.direction && p.filledContracts > 0);
      d.stampText = 'APPROVED';
      d.stampSub = pos ? `BUY ${pos.filledContracts}× ${f.dir}${px}` : `BUY ${f.dir}${px}`;
    } else {
      d.stampText = 'REJECTED';
      d.stampSub = `pass on ${f.subj}`;
    }
    let chairLine = approved ? 'APPROVED.' : 'REJECTED.';
    if (majority === null) chairLine = 'a tie. the chair decides.';
    else if (majority !== approved) {
      chairLine = 'OVERRULED!';
      d.stampSub = `${d.stampSub} · overruled ${d.yes}–${d.no}`;
    }
    B.bangGavel(majority !== null && majority !== approved ? 3 : 1);
    B.tableShake.v = 1;
    B.holoPulse = 1;
    B.holoColor.set(approved ? '#4ADE80' : '#F87171');
    this.speak('chair', chairLine, 1.2, true);
    this.host.log(`⚖️ #${d.n} ${approved ? 'APPROVED' : 'REJECTED'} ${d.yes}–${d.no} · ${f.subj}`, approved ? 'win' : 'loss');

    const losers = MEMBER_IDS.filter((id) => d.votes[id] !== approved);
    const winners = MEMBER_IDS.filter((id) => d.votes[id] === approved);
    this.at(T_VERDICT + 0.9, () => {
      const sore = losers.includes('greed') ? 'greed' : losers.includes('panic') ? 'panic' : losers[0];
      if (sore) {
        this.speak(sore, pick(PERSONAS[sore].sore), 1.4);
        this.pose(sore, sore === 'panic' ? 'cower' : 'talk', 1.4);
      }
      const happy = winners.includes('greed') ? 'greed' : winners.includes('fomo') ? 'fomo' : null;
      if (happy && approved) this.pose(happy, 'cheer', 1.4);
    });
  }


  private react(p: BotPosition): void {
    const won = p.outcomeCorrect === 1;
    const votes = this.ruleVotes.get(p.signalId) ?? this.rules(this.posFeatures(p));
    const pnl = money(p.pnlUsd ?? 0);
    const subj = subject(p.ticker, p.title);
    if (won) {
      const gloat: MemberId = votes.greed ? 'greed' : votes.fomo ? 'fomo' : MEMBER_IDS.find((id) => votes[id]) ?? 'quant';
      this.speak(gloat, pick(PERSONAS[gloat].win(pnl)), 1.6, true);
      this.pose(gloat, 'gloat', 1.6);
      const sulk = MEMBER_IDS.find((id) => !votes[id] && id !== gloat);
      if (sulk && Math.random() < 0.5) window.setTimeout(() => this.speak(sulk, pick(PERSONAS[sulk].sore), 1.2), 700);
      this.host.coins(Math.max(3, Math.min(18, Math.round((p.pnlUsd ?? 0) / 2))));
      this.host.log(`💰 settled +${pnl} · ${subj}`, 'win');
    } else {
      if (!votes.panic) {
        this.speak('panic', pick(PERSONAS.panic.loss(pnl)), 1.6, true);
        this.pose('panic', 'cower', 1.8);
      }
      if (!votes.doubt) {
        window.setTimeout(() => {
          this.speak('doubt', pick(PERSONAS.doubt.loss(pnl)), 1.2);
          this.pose('doubt', 'nod', 1.4);
        }, 650);
      }
      if (votes.panic && votes.doubt) this.speak('risk', pick(PERSONAS.risk.loss(pnl)), 1.4, true);
      this.host.log(`🚨 settled −${pnl} · ${subj}`, 'loss');
    }
  }

  payday(): void {
    this.paydayT = 5.5;
    const M = this.host.members;
    if (this.mode === 'agents') {
      for (const id of MEMBER_IDS) if (this.seatOf(id)) M[id].set('cheer');
      window.setTimeout(() => { for (const id of MEMBER_IDS) if (M[id].pose === 'cheer') M[id].set('idle'); }, 4000);
      this.speak('chair', pick(PERSONAS.chair.payday), 2, true);
      this.host.bunker.bangGavel(6);
      this.host.coins(160);
      return;
    }
    M.greed.climbTable(5.5);
    for (const id of MEMBER_IDS) M[id].set(id === 'panic' ? 'cower' : 'wild');
    window.setTimeout(() => { for (const id of MEMBER_IDS) if (M[id].pose === 'wild' || M[id].pose === 'cower') M[id].set('idle'); }, 5500);
    this.speak('greed', pick(PERSONAS.greed.payday), 2.4, true);
    const others: MemberId[] = ['fomo', 'panic', 'doubt', 'quant', 'risk'];
    others.forEach((id, i) => window.setTimeout(() => this.speak(id, pick(PERSONAS[id].payday), 2), 450 + i * 520));
    window.setTimeout(() => this.speak('chair', pick(PERSONAS.chair.payday), 2, true), 3100);
    this.host.bunker.bangGavel(6);
    this.host.bunker.tableShake.v = 1.5;
    this.host.coins(160);
  }
}
