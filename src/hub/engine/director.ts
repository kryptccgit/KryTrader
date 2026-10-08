import * as THREE from 'three';
import type { AccountSnapshot, BotPosition, ScannerStats, SignalRow } from '@shared/types';
import type { AutopilotStatus } from '@shared/market';
import type { Ship } from './ship';
import type { CoinPile, Flights, ItemKit, Sparks } from './items';
import type { Worker, Step } from './crew';
import type { Tone } from './overlay';
import type { RoomId } from './layout';
import type { ActivityRecord, AgentCallActivity } from '../../state/activity';
import { configuredAgents, hubAgentIdentity, tagLabel, type AgentIdentity } from '../../utils/agents';


import { hudNumbers, type HubData } from '../data';
import { hasEdge, type SavedBacktest } from '../library';
import { subject } from '../text';
import {
  activeSlots, agentCallBeat, beatFor, flipLine, positionSource, scheduleFlips, signalHandoff,
  type AgentBeat, type Beat, type SlotNow,
} from './jobs';
export type { HubData };

export interface Stage {
  ship: Ship;
  kit: ItemKit;
  flights: Flights;
  sparks: Sparks;
  pile: CoinPile;
  crew: Worker[];
  root: THREE.Object3D;
  say(who: Worker | 'captain', text: string, tone: Tone, opts?: { big?: boolean; force?: boolean; life?: number }): boolean;
  log(text: string, tone: Tone): void;
  activity(room: RoomId, amount?: number): void;
  agent?(who: AgentIdentity): Worker | null;
}

export interface DirectorOptions {
  now?: () => number;
}

interface Chip { obj: THREE.Object3D }
interface Bag { obj: THREE.Object3D; pnl: number; title: string }

function k(v: number): string {
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(v >= 1e4 ? 0 : 1)}K`;
  return v.toFixed(0);
}

function money(v: number): string {
  return `$${Math.abs(v).toFixed(2)}`;
}

function rand(a: number, b: number): number {
  return a + Math.random() * (b - a);
}

function pick<T>(xs: T[]): T {
  return xs[Math.floor(Math.random() * xs.length)];
}

function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s}s ago` : `${Math.round(s / 60)}m ago`;
}

function push<T>(q: T[], x: T, cap: number): void {
  q.push(x);
  if (q.length > cap) q.splice(0, q.length - cap);
}

const ROOM_CAP = 4;
const AGENT_CAP = 3;
const AGENT_STREAM_MS = 30_000;

export class Director {
  signalsSeen = 0;
  ordersSeen = 0;
  winsSeen = 0;
  lossesSeen = 0;
  forgeEvents = 0;

  account: AccountSnapshot | null = null;
  stats: ScannerStats | null = null;
  autopilot: AutopilotStatus | null = null;

  private seenSig = new Set<string>();
  private seenPos = new Map<number, string>();
  private primed = false;
  private runId: number | null = null;

  private sigQ: SignalRow[] = [];
  private orderQ: BotPosition[] = [];
  private winQ: BotPosition[] = [];
  private lossQ: BotPosition[] = [];
  private pings = 0;

  private researchQ: Beat[] = [];
  private forgeQ: Beat[] = [];
  private backtestQ: Beat[] = [];
  private optQ: Beat[] = [];
  private deskQ: Beat[] = [];
  private riskQ: Beat[] = [];
  private bridgeQ: Beat[] = [];
  private agentQ = new Map<string, { who: AgentIdentity; beats: AgentBeat[] }>();
  private agentStreamAt = -Infinity;
  agentCalls = 0;

  private outbox: Chip[] = [];
  private rack: Chip[] = [];
  private airlock: Bag[] = [];
  private cardsMoving = 0;
  private bagsFlying = 0;

  private pingCd = 0;
  private fireCd = 1;
  private inCd = 1.5;
  private alarmCd = 2;
  private bridgeCd = 0;
  private traderTalkCd = 0;
  private lossTalkCd = 0;
  private clockCd = 0;
  private scriptLogCd = 0;
  private pnlMark: number | null = null;

  private library: SavedBacktest[] = [];
  private lastRun: { stamp: string } | null = null;
  private signals: SignalRow[] = [];
  private config: HubData['config'] = null;
  private slotsNow: Map<string, SlotNow> | null = null;
  private slotHour = -1;
  private savedSlotCount = 0;
  private optimizing = false;
  private tableBooked = false;
  private autopilotRunning: boolean | null = null;
  private idleShown = '';
  private now: () => number;

  constructor(private s: Stage, opts: DirectorOptions = {}) {
    this.now = opts.now ?? Date.now;
  }

  get backtestSign(): string {
    if (this.lastRun) return `last ${this.lastRun.stamp}`;
    if (!this.library.length) return 'no saved runs';
    return `${this.library.filter(hasEdge).length}/${this.library.length} edge`;
  }

  get optimizerSign(): string {
    return this.savedSlotCount ? `${this.savedSlotCount} slots` : 'idle';
  }

  get forgeSign(): string {
    return this.forgeEvents ? `${this.forgeEvents} update${this.forgeEvents === 1 ? '' : 's'}` : 'idle';
  }

  get bridgeSign(): string {
    const a = this.autopilot;
    if (a?.running) return `autopilot · step ${a.step}`;
    const n = this.agentQ.size;
    if (n) return `${n} agent${n === 1 ? '' : 's'} aboard`;
    if (a?.enabled) return 'autopilot on';
    return 'CAPT. MOSSY';
  }

  private worker(role: Worker['role'], prefer?: (w: Worker) => boolean): Worker | null {
    const free = this.s.crew.filter((w) => w.role === role && w.free);
    if (!free.length) return null;
    return free.find((w) => prefer?.(w)) ?? free[Math.floor(Math.random() * free.length)];
  }


  ingest(d: HubData): void {
    this.account = d.account;
    this.stats = d.scannerStats;
    this.signals = d.signals;
    this.config = d.config ?? null;
    this.savedSlotCount = (d.config?.crypto15mRunners ?? []).reduce((n, r) => n + (r.schedule?.length ?? 0), 0);
    if (d.library) {
      this.library = d.library;
      this.showIdleReadout();
    }
    if (d.autopilot !== undefined) this.ingestAutopilot(d.autopilot ?? null);
    const runId = d.account?.sessionRunId ?? 0;
    if (this.primed && this.runId !== null && runId !== this.runId) {
      this.seenSig.clear();
      this.seenPos.clear();
      this.primed = false;
      this.signalsSeen = 0;
      this.ordersSeen = this.winsSeen = this.lossesSeen = 0;
      this.pnlMark = null;
    }
    this.runId = runId;

    for (const sg of d.signals.slice(0, 80)) {
      const key = `${sg.source}:${sg.id}`;
      if (this.seenSig.has(key)) continue;
      this.seenSig.add(key);
      if (!this.primed) continue;
      this.signalsSeen++;
      this.pings++;
      push(this.sigQ, sg, 3);
    }
    if (this.seenSig.size > 4000) this.seenSig = new Set(d.signals.map((x) => `${x.source}:${x.id}`));

    for (const p of d.positions) {
      const sig = p.resolved ? `r:${p.outcomeCorrect}` : 'o';
      const prev = this.seenPos.get(p.id);
      this.seenPos.set(p.id, sig);
      if (!this.primed || prev === sig) continue;
      const live = p.status === 'filled' || p.status === 'partial';
      if (prev === undefined && (live || p.resolved)) {
        this.ordersSeen++;
        push(this.orderQ, p, 5);
      }
      if (p.resolved && prev !== sig) {
        if (p.outcomeCorrect === 1) {
          this.winsSeen++;
          this.winQ.push(p);
          if (this.winQ.length > 6) {
            this.winQ.sort((a, b) => (b.pnlUsd ?? 0) - (a.pnlUsd ?? 0));
            this.winQ.length = 6;
          }
        } else if (p.outcomeCorrect === 0) {
          this.lossesSeen++;
          this.lossQ.push(p);
          if (this.lossQ.length > 2) {
            this.lossQ.sort((a, b) => (a.pnlUsd ?? 0) - (b.pnlUsd ?? 0));
            this.lossQ.length = 2;
          }
        }
      }
    }
    if (this.seenPos.size > 6000) {
      const keep = new Set(d.positions.map((p) => p.id));
      for (const id of this.seenPos.keys()) if (!keep.has(id)) this.seenPos.delete(id);
    }
    this.primed = true;

    const pnl = hudNumbers(d.account, d.scannerStats).pnl;
    if (pnl !== null) {
      const step = this.milestoneStep(d.account);
      if (this.pnlMark === null) this.pnlMark = Math.floor(pnl / step) * step;
      else if (pnl >= this.pnlMark + step) {
        this.pnlMark = Math.floor(pnl / step) * step;
        this.s.say('captain', `🚀 P&L ${pnl >= 0 ? '+' : '−'}$${Math.abs(this.pnlMark).toFixed(0)}! nice work, crew`, 'win', { force: true });
        this.s.ship.mossyHop = 1.2;
      } else if (pnl < this.pnlMark - step) {
        this.pnlMark = Math.floor(pnl / step) * step;
      }
    }
  }

  private showIdleReadout(): void {
    if (this.lastRun || this.tableBooked) return;
    let label = 'BACKTEST';
    let sub = 'idle · no saved runs';
    if (this.library.length) {
      const best = [...this.library].sort((a, b) => b.net - a.net)[0];
      label = 'SAVED · BEST';
      sub = `${best.name.slice(0, 14)} ${best.net >= 0 ? '+' : '−'}${Math.abs(best.net).toFixed(1)}¢${hasEdge(best) ? ' ✓' : ''}`;
    }
    const key = `${label}|${sub}`;
    if (key === this.idleShown) return;
    this.idleShown = key;
    this.s.ship.setHoloIdle(label, sub);
  }

  private ingestAutopilot(a: AutopilotStatus | null): void {
    this.autopilot = a;
    const running = a ? !!a.running : null;
    if (running && this.autopilotRunning === false) {
      const head = a?.runs?.[0];
      const trig = head && head.finishedAt === null ? head.trigger : null;
      const t = `🤖 Autopilot run started${trig ? ` (${trig})` : ''}`;
      push(this.bridgeQ, { room: 'bridge', text: t, log: t, tone: 'gold' }, ROOM_CAP);
    }
    this.autopilotRunning = running;
  }

  activity(rec: ActivityRecord, replay = false): void {
    if (rec.ev.kind === 'agentCall') {
      this.agentCall(rec.ev, rec.at, replay);
      return;
    }
    const beat = beatFor(rec.ev);
    if (!beat) return;
    if (replay) beat.log = `${beat.log} · ${ago(this.now() - rec.at)}`;
    switch (beat.room) {
      case 'research': push(this.researchQ, beat, ROOM_CAP); break;
      case 'forge': this.forgeEvents++; push(this.forgeQ, beat, ROOM_CAP); break;
      case 'backtest': push(this.backtestQ, beat, ROOM_CAP); break;
      case 'optimizer': push(this.optQ, beat, ROOM_CAP); break;
      case 'desk': push(this.deskQ, beat, ROOM_CAP); break;
      case 'vault': push(this.riskQ, beat, ROOM_CAP); break;
      case 'bridge': push(this.bridgeQ, beat, ROOM_CAP); break;
    }
  }

  private agentCall(ev: AgentCallActivity, at: number, replay: boolean): void {
    const agents = configuredAgents(this.config);
    let who = hubAgentIdentity(ev, agents);
    const prev = this.agentQ.get(who.id);
    if (!who.model && prev?.who.model) who = hubAgentIdentity({ ...ev, model: prev.who.model }, agents);
    const beat = agentCallBeat(ev, tagLabel(who));
    if (!beat) return;
    if (ev.call === 'call') {
      this.agentCalls++;
      this.agentStreamAt = this.now();
    }
    if (replay) beat.log = `${beat.log} · ${ago(this.now() - at)}`;
    let q = prev;
    if (!q) {
      q = { who, beats: [] };
      this.agentQ.set(who.id, q);
    }
    q.who = who;
    q.beats.push(beat);
    if (q.beats.length > AGENT_CAP) {
      const routine = q.beats.findIndex((b) => !b.run && b.room !== 'desk' && !b.text.includes('forecast'));
      q.beats.splice(routine >= 0 ? routine : 0, 1);
    }
  }

  scriptLog(name: string | null, lines: string[]): void {
    const last = [...lines].reverse().find((l) => typeof l === 'string' && l.trim());
    if (!last || this.scriptLogCd > 0) return;
    this.scriptLogCd = 6;
    const raw = `📜 ${name ? `${name.slice(0, 16)}: ` : ''}${last.replace(/\s+/g, ' ').trim()}`;
    const text = raw.length > 56 ? `${raw.slice(0, 55)}…` : raw;
    this.s.log(text, 'forge');
    const w = this.worker('smith');
    if (w) this.s.say(w, text, 'forge');
    this.s.activity('forge', 0.5);
  }

  private milestoneStep(a: AccountSnapshot | null): number {
    const bank = a?.startBankrollUsd ?? 1000;
    return Math.max(25, Math.round((bank * 0.05) / 25) * 25);
  }


  update(dt: number): void {
    this.pingCd -= dt;
    this.fireCd -= dt;
    this.inCd -= dt;
    this.alarmCd -= dt;
    this.bridgeCd -= dt;
    this.traderTalkCd -= dt;
    this.lossTalkCd -= dt;
    this.clockCd -= dt;
    this.scriptLogCd -= dt;

    if (this.pings > 0 && this.pingCd <= 0) {
      this.pingCd = 0.35;
      this.pings = 0;
      this.s.ship.ping(Math.random() < 0.5 ? '#A855F7' : '#EC4899');
      this.s.activity('research', 0.4);
    }
    if (this.clockCd <= 0) {
      this.clockCd = 1;
      this.checkSchedule();
    }
    this.research();
    this.forge();
    this.backtest();
    this.orders();
    this.incoming();
    this.vault();
    this.losses();
    this.risk();
    this.optimizer();
    this.bridge();
    this.agents();
  }


  private research(): void {
    if (this.researchQ.length) {
      const w = this.worker('researcher');
      if (!w) return;
      const b = this.researchQ.shift()!;
      w.assign([
        { k: 'go', to: w.home },
        { k: 'work', anim: 'type', dur: 0.7 },
        { k: 'do', fn: (wk) => {
          this.s.ship.ping('#A855F7');
          this.s.say(wk, b.text, b.tone, { force: true, life: 3.4 });
          this.s.log(b.log, b.tone);
          this.s.activity('research', 1);
        } },
        { k: 'work', anim: 'look', dur: 1.4 },
      ]);
      return;
    }
    if (!this.sigQ.length || this.cardsMoving >= 2) return;
    const w = this.worker('researcher');
    if (!w) return;
    this.sigQ.sort((a, b) => (b.source === 'whale' ? 1 : 0) - (a.source === 'whale' ? 1 : 0) || (b.dollarValue ?? 0) - (a.dollarValue ?? 0));
    const sg = this.sigQ.shift()!;
    this.sigQ.length = Math.min(this.sigQ.length, 1);
    const whale = sg.source === 'whale';
    const color = whale ? '#A855F7' : '#EC4899';
    const subj = subject(sg.ticker, sg.title);
    const dir = sg.direction.toUpperCase();
    const text = whale && sg.dollarValue
      ? `🐋 $${k(sg.dollarValue)} ${dir} on ${subj}!`
      : `📈 momentum: ${subj} ${dir} ${sg.priceCents}¢`;
    this.cardsMoving++;
    w.assign([
      { k: 'go', to: w.home },
      { k: 'work', anim: 'type', dur: 0.6 },
      { k: 'do', fn: (wk) => {
        this.s.ship.ping(color);
        this.s.say(wk, text, whale ? 'whale' : 'momo');
        this.s.log(text, whale ? 'whale' : 'momo');
        this.s.activity('research', 1);
      } },
      { k: 'work', anim: 'look', dur: 0.7 },
      { k: 'go', to: 'research.printer' },
      { k: 'do', fn: () => this.s.ship.printFlash() },
      { k: 'work', anim: 'grab', dur: 0.45 },
      { k: 'do', fn: (wk) => wk.pickUp(this.s.kit.card(color)) },
      { k: 'work', anim: 'look', dur: 0.8 },
      { k: 'do', fn: (wk) => {
        const now = this.signals.find((x) => x.id === sg.id && x.source === sg.source) ?? sg;
        const h = signalHandoff(now);
        if (!h.traded) {
          wk.drop()?.removeFromParent();
          this.cardsMoving--;
          this.s.ship.printFlash();
          this.s.say(wk, h.text, 'neutral');
          return;
        }
        this.s.say(wk, h.text, whale ? 'whale' : 'momo');
        wk.assign([
          { k: 'go', to: 'desk.rack' },
          { k: 'work', anim: 'grab', dur: 0.3 },
          { k: 'do', fn: (w2) => {
            const o = w2.drop();
            this.cardsMoving--;
            if (o) this.toRack(o);
            this.s.activity('desk', 0.6);
          } },
        ]);
      } },
    ]);
  }

  private place(o: THREE.Object3D, at: THREE.Vector3): void {
    this.s.root.add(o);
    o.position.copy(at);
    o.rotation.set(0, Math.random() * 0.6 - 0.3, 0);
    o.scale.setScalar(1);
  }

  private toRack(o: THREE.Object3D): void {
    if (this.rack.length >= this.s.ship.rackSlots.length) this.rack.shift()?.obj.removeFromParent();
    this.rack.push({ obj: o });
    this.rack.forEach((c, i) => this.place(c.obj, this.s.ship.rackSlots[i]));
  }


  private forge(): void {
    if (!this.forgeQ.length) return;
    const w = this.worker('smith');
    if (!w) return;
    const b = this.forgeQ.shift()!;
    const ok = b.tone !== 'loss';
    w.assign([
      { k: 'go', to: 'forge.anvil' },
      { k: 'work', anim: 'hammer', dur: ok ? 1.5 : 0.9, onBeat: () => {
        this.s.ship.anvilHit();
        this.s.sparks.burst(0.75, 0.8, 4.0, ok ? '#FDBA74' : '#9CA3AF', 10, 2.2, 2.2);
        this.s.activity('forge', 0.6);
      } },
      { k: 'do', fn: (wk) => {
        this.s.say(wk, b.text, b.tone, { force: true, life: 3.2 });
        this.s.log(b.log, b.tone);
        this.s.activity('forge', 1);
        if (!ok) return;
        const chip = this.s.kit.chip(b.deploy ? '#2DD4BF' : '#F59E0B');
        this.s.sparks.burst(0.75, 0.9, 4.0, '#FDE68A', 20, 2.6, 2.4);
        wk.pickUp(chip);
        wk.assign(b.deploy ? [
          { k: 'go', to: 'desk.rack' },
          { k: 'work', anim: 'grab', dur: 0.3 },
          { k: 'do', fn: (w2) => {
            const o = w2.drop();
            if (o) this.toRack(o);
            this.s.activity('desk', 0.6);
          } },
        ] : [
          { k: 'go', to: 'forge.outbox' },
          { k: 'work', anim: 'grab', dur: 0.3 },
          { k: 'do', fn: (w2) => {
            const o = w2.drop();
            if (!o) return;
            if (this.outbox.length >= this.s.ship.outboxSlots.length) this.outbox.shift()?.obj.removeFromParent();
            this.outbox.push({ obj: o });
            this.outbox.forEach((c, i) => this.place(c.obj, this.s.ship.outboxSlots[i]));
          } },
        ]);
      } },
    ]);
  }


  private backtest(): void {
    if (!this.backtestQ.length || this.tableBooked || this.s.ship.backtestRunning) return;
    const w = this.worker('quant');
    if (!w) return;
    const b = this.backtestQ.shift()!;
    this.tableBooked = true;
    const series = b.series && b.series.length > 1 ? b.series : [];
    w.assign([
      { k: 'go', to: 'backtest.table' },
      { k: 'do', fn: () => {
        this.s.ship.startBacktest(series, b.holo ?? 'BACKTEST', series.length ? '' : 'no equity curve');
        this.s.activity('backtest', 1);
      } },
      { k: 'work', anim: 'type', dur: 2.5 },
      { k: 'do', fn: (wk) => {
        this.tableBooked = false;
        this.lastRun = { stamp: b.stamp ?? '—' };
        this.s.ship.finishBacktest(b.pass ?? null, b.stamp ?? '');
        this.s.say(wk, b.text, b.tone, { force: true, life: 3.6 });
        this.s.log(b.log, b.tone);
        this.s.activity('backtest', 1);
      } },
      { k: 'work', anim: b.pass ? 'cheer' : 'look', dur: 1.2 },
    ]);
  }


  private capsule(): void {
    const ship = this.s.ship;
    ship.fireTube();
    const cap = this.s.kit.capsule();
    this.s.flights.launch(cap, ship.tubeInside, ship.kalshiPos, 1.5, 2.2, () => {
      ship.stationHit();
      const sp = ship.station.position;
      this.s.sparks.burst(sp.x, sp.y, sp.z, '#6EE7B7', 8, 1.6, 0.6);
    });
  }

  private orders(): void {
    if (this.fireCd > 0) return;
    if (this.deskQ.length) {
      this.fireCd = rand(0.9, 1.3);
      const b = this.deskQ.shift()!;
      if (b.capsule) this.capsule();
      if (b.board) this.s.ship.pushOrder(b.board.text, b.board.color);
      this.s.activity('desk', 0.9);
      if (b.agentOrder && this.now() - this.agentStreamAt < AGENT_STREAM_MS) return;
      this.s.log(b.log, b.tone);
      const w = this.worker('trader') ?? pick(this.s.crew.filter((c) => c.role === 'trader'));
      if (w) this.s.say(w, b.text, b.tone, { force: true, life: 3.2 });
      return;
    }
    if (!this.orderQ.length) return;
    this.fireCd = rand(0.55, 0.85);
    const p = this.orderQ.pop()!;
    this.orderQ.length = Math.min(this.orderQ.length, 3);
    this.capsule();
    this.s.activity('desk', 0.7);
    const filled = p.filledContracts > 0;
    const qty = filled ? p.filledContracts : p.targetContracts;
    const price = p.avgFillPriceCents ?? p.limitPriceCents;
    const px = typeof price === 'number' && Number.isFinite(price) ? ` @${Math.round(price)}¢` : '';
    const side = p.action === 'sell' ? 'SELL' : 'BUY';
    const dir = p.direction.toUpperCase();
    const subj = subject(p.ticker, p.title);
    const src = positionSource(p.signalSource);
    this.s.ship.pushOrder(`${src} ${side} ${qty}× ${dir}${px} ${subj.slice(0, 10)}`, dir === 'YES' ? '#4ADE80' : '#F9A8D4');
    if (this.traderTalkCd <= 0) {
      const w = pick(this.s.crew.filter((c) => c.role === 'trader'));
      if (w) {
        const lines = [
          `${src} ${side} ${qty}× ${dir}${px}`,
          filled ? `${src} filled ${qty}×${px}` : `${src} working${px}`,
          `🚀 ${subj} ${dir} → KALSHI`,
        ];
        if (this.s.say(w, pick(lines), 'momo')) this.traderTalkCd = rand(2.8, 4.2);
      }
    }
  }


  private incoming(): void {
    if (this.inCd > 0 || !this.winQ.length) return;
    if (this.airlock.length + this.bagsFlying >= 4) return;
    this.inCd = rand(0.55, 0.9);
    this.winQ.sort((a, b) => (b.pnlUsd ?? 0) - (a.pnlUsd ?? 0));
    const p = this.winQ.shift()!;
    const ship = this.s.ship;
    const bag = this.s.kit.bag();
    this.bagsFlying++;
    this.s.flights.launch(bag, ship.station.position, ship.hatchPos, 1.4, 2.6, () => {
      this.bagsFlying--;
      ship.hatchBlink();
      this.s.activity('desk', 0.4);
      const slot = ship.airlockSlots[this.airlock.length % ship.airlockSlots.length];
      const b = this.s.kit.bag();
      b.scale.setScalar(0.85);
      this.s.root.add(b);
      b.position.copy(slot);
      this.airlock.push({ obj: b, pnl: p.pnlUsd ?? 0, title: subject(p.ticker, p.title) });
      this.s.log(`💰 +${money(p.pnlUsd ?? 0)} · ${subject(p.ticker, p.title)}`, 'win');
    }, true);
  }

  private vault(): void {
    if (!this.airlock.length) return;
    const w = this.worker('keeper');
    if (!w) return;
    const bag = this.airlock.shift()!;
    this.airlock.forEach((b, i) => b.obj.position.copy(this.s.ship.airlockSlots[i]));
    const spot = this.s.crew.filter((c) => c.role === 'keeper').indexOf(w) % 2 ? 'vault.pileB' : 'vault.pile';
    w.assign([
      { k: 'go', to: 'desk.airlock' },
      { k: 'work', anim: 'grab', dur: 0.35 },
      { k: 'do', fn: (wk) => wk.pickUp(bag.obj, true) },
      { k: 'go', to: spot },
      { k: 'work', anim: 'grab', dur: 0.3 },
      { k: 'do', fn: (wk) => {
        wk.drop()?.removeFromParent();
        const pile = this.s.pile;
        pile.add(Math.max(2, Math.min(16, Math.round(bag.pnl / 2))));
        this.s.ship.vaultDeposit(bag.pnl >= 40);
        const top = pile.top(new THREE.Vector3());
        this.s.sparks.burst(top.x, top.y + 0.3, top.z, '#FDE047', 9, 1.4, 2.0);
        const big = bag.pnl >= 25;
        const txt = big ? `+${money(bag.pnl)} BIG WIN 💰` : `+${money(bag.pnl)} 💰`;
        this.s.say(wk, txt, 'win', { big });
        this.s.activity('vault', 1);
      } },
      { k: 'work', anim: bag.pnl >= 25 ? 'cheer' : 'idle', dur: bag.pnl >= 25 ? 1.4 : 0.2 },
    ]);
  }


  private losses(): void {
    if (this.alarmCd > 0 || !this.lossQ.length) return;
    this.alarmCd = rand(6, 9);
    const p = this.lossQ.splice(Math.floor(Math.random() * this.lossQ.length), 1)[0]!;
    const amt = money(p.pnlUsd ?? 0);
    const subj = subject(p.ticker, p.title);
    this.s.ship.alarm = 2.6;
    this.s.activity('vault', 0.8);
    this.s.log(`🚨 −${amt} · ${subj}`, 'loss');
    const w = this.worker('risk');
    if (w) {
      w.assign([
        { k: 'work', anim: 'panic', dur: 0.5 },
        { k: 'go', to: 'desk.termB', run: true },
        { k: 'work', anim: 'type', dur: 1.1 },
        { k: 'do', fn: (wk) => {
          this.s.say(wk, pick([`settled against us · −${amt}`, `logged it: −${amt}`, `lost the stake · −${amt}`]), 'loss', { force: true });
          this.s.activity('desk', 0.6);
        } },
        { k: 'work', anim: 'type', dur: 0.8 },
      ]);
    } else if (this.lossTalkCd <= 0) {
      const t = pick(this.s.crew.filter((c) => c.role === 'trader'));
      if (t && this.s.say(t, `ouch · −${amt} on ${subj}`, 'loss')) this.lossTalkCd = 4;
    }
  }


  private risk(): void {
    if (!this.riskQ.length) return;
    const w = this.worker('risk');
    if (!w) return;
    const b = this.riskQ.shift()!;
    if (b.alarm) this.s.ship.alarm = 2.6;
    this.s.log(b.log, b.tone);
    this.s.activity('vault', 1);
    w.assign([
      ...(b.alarm ? [{ k: 'work', anim: 'panic', dur: 0.5 } as Step] : []),
      { k: 'go', to: 'vault.risk', run: !!b.alarm },
      { k: 'work', anim: 'type', dur: 0.7 },
      { k: 'do', fn: (wk) => { this.s.say(wk, b.text, b.tone, { force: true, life: 3.4 }); } },
      { k: 'work', anim: 'type', dur: 1.0 },
    ]);
  }


  private checkSchedule(): void {
    const t = new Date(this.now());
    const hour = t.getUTCHours();
    const next = activeSlots(this.config?.crypto15mRunners, hour);
    const prev = this.slotsNow;
    this.slotsNow = next;
    if (prev === null || hour === this.slotHour) {
      this.slotHour = hour;
      return;
    }
    this.slotHour = hour;
    for (const f of scheduleFlips(prev, next)) {
      const line = flipLine(f, hour);
      push(this.optQ, { room: 'optimizer', text: line, log: line, tone: 'opt' }, ROOM_CAP);
    }
  }

  private optimizer(): void {
    if (!this.optQ.length || this.optimizing) return;
    const w = this.worker('engineer', (x) => x.home === 'optimizer.panel');
    if (!w) return;
    const b = this.optQ.shift()!;
    this.optimizing = true;
    w.assign([
      { k: 'go', to: 'optimizer.panel' },
      { k: 'do', fn: () => {
        this.s.ship.setOptimizing(true);
        this.s.activity('optimizer', 1);
      } },
      { k: 'work', anim: 'type', dur: 2.0 },
      { k: 'do', fn: (wk) => {
        this.s.ship.setOptimizing(false);
        this.s.say(wk, b.text, b.tone, { force: true, life: 3.4 });
        this.s.log(b.log, b.tone);
        this.s.activity('optimizer', 1);
        wk.pickUp(this.s.kit.tablet());
      } },
      { k: 'go', to: 'bridge.report' },
      { k: 'work', anim: 'grab', dur: 0.3 },
      { k: 'do', fn: (wk) => {
        wk.drop()?.removeFromParent();
        this.optimizing = false;
        this.s.ship.mossyHop = 0.8;
      } },
    ]);
  }


  private bridge(): void {
    if (this.bridgeCd > 0 || !this.bridgeQ.length) return;
    this.bridgeCd = 3.2;
    const b = this.bridgeQ.shift()!;
    this.s.say('captain', b.text, b.tone, { force: true, life: 3.4 });
    this.s.log(b.log, b.tone);
    this.s.ship.mossyHop = 1;
    this.s.activity('bridge', 1);
  }


  private agents(): void {
    if (!this.agentQ.size || !this.s.agent) return;
    for (const q of this.agentQ.values()) {
      if (!q.beats.length) continue;
      const w = this.s.agent(q.who);
      if (!w) {
        q.beats.length = 0;
        continue;
      }
      w.tag = { label: tagLabel(q.who), color: q.who.color };
      if (!w.free) continue;
      const b = q.beats.shift()!;
      const say = (wk: Worker) => {
        this.s.say(wk, b.text, b.tone, { force: true, life: 3.4 });
        this.s.log(b.log, b.tone);
        this.s.activity(b.room, 1);
        if (b.run) this.s.ship.alarm = Math.max(this.s.ship.alarm, 1.4);
        if (b.room === 'research') this.s.ship.ping(q.who.color);
      };
      if (b.connect) {
        w.assign([
          { k: 'go', to: w.home },
          { k: 'do', fn: say },
          { k: 'work', anim: 'cheer', dur: 1.1 },
        ]);
        continue;
      }
      const side = ((w as { id?: number }).id ?? 0) % 2 ? 'B' : 'A';
      w.assign([
        ...(b.run ? [{ k: 'work', anim: 'panic', dur: 0.4 } as Step] : []),
        { k: 'go', to: `${b.room}.agent${side}`, run: b.run },
        { k: 'work', anim: b.anim, dur: 0.6 },
        { k: 'do', fn: say },
        { k: 'work', anim: b.run ? 'type' : 'look', dur: 0.9 },
      ]);
    }
  }

  payday(): void {
    const ship = this.s.ship;
    const pile = this.s.pile;
    for (let i = 0; i < 28; i++) {
      window.setTimeout(() => {
        const bag = this.s.kit.bag();
        bag.scale.setScalar(0.7);
        const top = pile.top(new THREE.Vector3());
        top.x += rand(-0.5, 0.5);
        top.z += rand(-0.5, 0.5);
        this.s.flights.launch(bag, ship.station.position, top, 1.3 + Math.random() * 0.4, 5 + Math.random() * 2, () => {
          pile.add(6);
          this.s.sparks.burst(top.x, top.y, top.z, '#FDE047', 10, 2, 2.5);
          ship.vaultDeposit(true);
        }, true);
      }, i * 70);
    }
    for (const w of this.s.crew) {
      if (w.role === 'keeper' || w.role === 'trader' || (w.free && Math.random() < 0.6)) {
        w.assign([{ k: 'work', anim: 'cheer', dur: 2.6 + Math.random() }]);
      }
    }
    ship.mossyHop = 2.5;
  }
}
