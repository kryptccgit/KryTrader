import { cacheMeasureText } from '../text';
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { CrewKit, Worker, type Role } from './crew';
import { Director, type HubData, type Stage } from './director';
import { CoinPile, Flights, ItemKit, Sparks } from './items';
import { NavGraph } from './nav';
import { AGENT_DOCKS, KALSHI_POS, PROP, ROOM, ROOMS, SHIP, SHIP_WALK, WALL_H, roomAt, type RoomId } from './layout';
import { Walker, visibleFrom } from '../walk';
import { buildWalkShell, type WalkShell } from './walkshell';
import { PERSONA_BY_ID, agentPersona, type Persona } from './npcs';
import { Talk } from './dialogue';
import { drawDialogue, drawTalkPrompt, type Rect } from './talkui';
import {
  drawBubbles, drawHud, drawSigns, drawTags, type BubbleView, type FeedLine, type SignView, type TagView, type Tone,
} from './overlay';
import type { AgentIdentity } from '../../utils/agents';
import { hudNumbers } from '../data';
import { paydayLine, type PaydayEvent } from '../payday';
import type { ActivityRecord } from '../../state/activity';
import { Ship } from './ship';

export type OutputMode = 'page' | 'cinema';

interface Bubble {
  who: Worker | 'captain';
  text: string;
  tone: Tone;
  age: number;
  life: number;
  big: boolean;
}

const ISO_EL = Math.atan(1 / Math.SQRT2);
const ISO_AZ = Math.PI / 4;
const MAX_BUBBLES = 5;

const CREW: { role: Role; name: string; home: string; wander: string[] }[] = [
  { role: 'researcher', name: 'Ada', home: 'research.scanA', wander: ['research.wall', 'research.printer'] },
  { role: 'researcher', name: 'Rui', home: 'research.scanB', wander: ['research.wall'] },
  { role: 'smith', name: 'Bo', home: 'forge.furnace', wander: ['forge.idle', 'forge.anvil'] },
  { role: 'smith', name: 'Kit', home: 'forge.idle', wander: ['forge.furnace'] },
  { role: 'quant', name: 'Quinn', home: 'backtest.tableB', wander: ['backtest.tape'] },
  { role: 'quant', name: 'Nova', home: 'backtest.tape', wander: ['backtest.bin'] },
  { role: 'trader', name: 'Tess', home: 'desk.termA', wander: ['desk.tube'] },
  { role: 'trader', name: 'Max', home: 'desk.termB', wander: ['desk.rack'] },
  { role: 'keeper', name: 'Goldie', home: 'vault.idle', wander: ['vault.pileB'] },
  { role: 'keeper', name: 'Penny', home: 'vault.pileB', wander: ['vault.idle'] },
  { role: 'risk', name: 'Rex', home: 'vault.risk', wander: ['vault.idle'] },
  { role: 'engineer', name: 'Gus', home: 'optimizer.panel', wander: ['optimizer.reactor'] },
  { role: 'engineer', name: 'Ivy', home: 'optimizer.turbine', wander: ['optimizer.reactor'] },
];

function damp(a: number, b: number, k: number, dt: number): number {
  return b + (a - b) * Math.exp(-k * dt);
}

function shade(hex: string, k = 0.45): string {
  const c = new THREE.Color(hex);
  c.multiplyScalar(k);
  return `#${c.getHexString()}`;
}

export class HubEngine {
  private out: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private mode: OutputMode = 'page';
  private W = 1280;
  private H = 720;
  private portrait = false;

  private glCanvas = document.createElement('canvas');
  private renderer: THREE.WebGLRenderer;
  private composer: EffectComposer;
  private bloom: UnrealBloomPass;
  private bloomScale = 0.5;
  private rt: THREE.WebGLRenderTarget;
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 300);
  private walkCam = new THREE.PerspectiveCamera(68, 16 / 9, 0.05, 260);
  private walker = new Walker(SHIP_WALK);
  private walking = false;
  private renderPass: RenderPass;
  private shell: WalkShell = buildWalkShell();
  private doorOpen = 0;
  private talk: Talk | null = null;
  private talkWith: Worker | 'captain' | null = null;
  private talkTarget: { who: Worker | 'captain'; persona: Persona; color: string } | null = null;
  private talkColor = '#A855F7';
  private talkRects: Rect[] = [];
  private barkAt = new Map<string, number>();
  private barkNext = 0;
  private sun: THREE.DirectionalLight;
  private envRT: THREE.WebGLRenderTarget;

  private nav = new NavGraph();
  private crewKit = new CrewKit();
  private kit = new ItemKit();
  private ship: Ship;
  private flights: Flights;
  private sparks: Sparks;
  private pile: CoinPile;
  private crew: Worker[] = [];
  private agents = new Map<string, { w: Worker; lastAt: number }>();
  private director: Director;

  private bubbles: Bubble[] = [];
  private feed: FeedLine[] = [];
  private hot = new Map<RoomId, number>();
  private lastHot: RoomId = 'desk';
  private banner: { text: string; sub: string; t: number } | null = null;
  private pnlPulse = 0;
  private lastPnl: number | null = null;

  private target = new THREE.Vector3();
  private targetGoal = new THREE.Vector3();
  private home = new THREE.Vector3();
  private halfH = 10;
  private zoom = 1;
  private zoomGoal = 1;
  private focused: RoomId | null = null;
  private tour = false;
  private tourT = 0;
  private tourFocus = false;
  private paydayFocusUntil = 0;

  private drag: { x: number; y: number; moved: boolean; tx: number; tz: number } | null = null;
  private detach: (() => void) | null = null;

  private raf = 0;
  private running = false;
  private last = 0;
  private time = 0;
  private frameErr = false;
  private fpsFrames = 0;
  private fpsAcc = 0;
  fps = 0;
  onFocusChange: ((label: string | null) => void) | null = null;
  onTourChange: ((on: boolean) => void) | null = null;
  onWalkChange: ((on: boolean) => void) | null = null;

  private _v = new THREE.Vector3();
  private _v2 = new THREE.Vector3();
  private _ray = new THREE.Raycaster();
  private _plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

  constructor(canvas: HTMLCanvasElement, w: number, h: number) {
    this.out = canvas;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) throw new Error('2D canvas unavailable');
    this.ctx = cacheMeasureText(ctx);

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.glCanvas, antialias: false, alpha: false, stencil: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(1);
    this.renderer.toneMapping = THREE.NeutralToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene.background = new THREE.Color('#05030c');
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const room = new RoomEnvironment();
    this.envRT = pmrem.fromScene(room, 0.04);
    room.dispose();
    pmrem.dispose();
    this.scene.environment = this.envRT.texture;
    this.scene.environmentIntensity = 0.18;
    this.scene.add(new THREE.HemisphereLight('#d6dcff', '#4a3560', 0.95));
    this.sun = new THREE.DirectionalLight('#fff0dc', 2.0);
    this.sun.position.set(-7, 20, 11);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    const sc = this.sun.shadow.camera;
    sc.left = -19; sc.right = 19; sc.top = 15; sc.bottom = -15; sc.near = 1; sc.far = 60;
    this.sun.shadow.bias = -0.0004;
    this.sun.shadow.normalBias = 0.03;
    this.sun.shadow.radius = 3;
    this.scene.add(this.sun, this.sun.target);
    const fill = new THREE.DirectionalLight('#b4bcff', 0.7);
    fill.position.set(12, 8, 14);
    this.scene.add(fill);

    this.ship = new Ship(this.kit);
    this.scene.add(this.ship.space, this.ship.group);
    this.flights = new Flights(this.scene);
    this.sparks = new Sparks(this.kit.glowTex);
    this.scene.add(this.sparks.points);
    this.pile = new CoinPile(PROP.pile[0], PROP.pile[1]);
    this.pile.set(110);
    this.ship.group.add(this.pile.mesh);
    this.ship.group.add(this.shell.group);
    for (const c of CREW) {
      const w = new Worker(this.crewKit, c.role, c.name, c.home, c.wander, this.nav);
      this.crew.push(w);
      this.ship.group.add(w.group);
    }

    const stage: Stage = {
      ship: this.ship, kit: this.kit, flights: this.flights, sparks: this.sparks, pile: this.pile,
      crew: this.crew, root: this.ship.group,
      say: (who, text, tone, opts) => this.say(who, text, tone, opts),
      log: (text, tone) => this.log(text, tone),
      activity: (room, amount) => this.heat(room, amount),
      agent: (who) => this.agentAboard(who),
    };
    this.director = new Director(stage);

    this.rt = new THREE.WebGLRenderTarget(w, h, { type: THREE.HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(this.renderer, this.rt);
    this.renderPass = new RenderPass(this.scene, this.camera);
    this.composer.addPass(this.renderPass);
    this.bloom = new UnrealBloomPass(new THREE.Vector2(w, h), 0.6, 0.4, 1.0);
    this.bloomScale = 0.5;
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    this.setOutput(canvas, w, h, 'page');
  }


  start(): void {
    if (this.running) return;
    this.running = true;
    this.last = performance.now();
    const loop = () => {
      if (!this.running) return;
      this.raf = requestAnimationFrame(loop);
      this.frame();
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  ingest(d: HubData): void {
    this.director.ingest(d);
    const pnl = hudNumbers(d.account, d.scannerStats).pnl;
    if (pnl !== null && this.lastPnl !== null) {
      const bank = d.account?.startBankrollUsd || 1000;
      this.pnlPulse = Math.max(this.pnlPulse, Math.min(1, Math.abs(pnl - this.lastPnl) / (bank * 0.01)));
    }
    this.lastPnl = pnl;
  }

  activity(rec: ActivityRecord, replay: boolean): void {
    this.director.activity(rec, replay);
  }

  scriptLog(name: string | null, lines: string[]): void {
    this.director.scriptLog(name, lines);
  }

  payday(ev: PaydayEvent): void {
    this.banner = { text: 'PAYDAY!', sub: paydayLine(ev), t: 0 };
    this.director.payday();
    this.say('captain', 'PAYDAY! 💰💰💰', 'gold', { force: true, big: true, life: 3.5 });
    this.log(`💰 PAYDAY ${paydayLine(ev)}`, 'gold');
    this.heat('vault', 3);
    if (!this.focused || this.focused === 'vault' || this.tour) this.paydayFocusUntil = this.time + 4.5;
  }

  setOutput(canvas: HTMLCanvasElement, w: number, h: number, mode: OutputMode): void {
    w = Math.max(64, Math.round(w));
    h = Math.max(64, Math.round(h));
    if (canvas !== this.out) {
      const ctx = canvas.getContext('2d', { alpha: false });
      if (!ctx) throw new Error('2D canvas unavailable');
      this.out = canvas;
      this.ctx = cacheMeasureText(ctx);
    }
    this.mode = mode;
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    this.W = w;
    this.H = h;
    this.portrait = h > w;
    this.renderer.setSize(w, h, false);
    this.composer.setSize(w, h);
    this.bloom.setSize(Math.round(w * this.bloomScale), Math.round(h * this.bloomScale));
    const ps = this.uiScale();
    this.sparks.setPixelScale(ps);
    this.ship.setPixelScale(ps);
    this.fit();
    this.attachInput();
  }

  setTour(on: boolean): void {
    if (on && this.walking) this.setWalk(false);
    this.tour = on;
    this.tourT = 3.5;
    this.tourFocus = false;
    if (!on) this.focus(null);
    this.onTourChange?.(on);
  }

  resetView(): void {
    this.focus(null);
  }

  escape(): boolean {
    if (!this.talk) return false;
    this.endTalk();
    return true;
  }

  private walkKey(code: string): boolean {
    const t = this.talk;
    if (t) {
      if (code === 'KeyE' || code === 'Enter' || code === 'Space') t.advance();
      else if (/^Digit[1-9]$/.test(code)) t.choose(Number(code.slice(5)) - 1);
      else if (code === 'ArrowUp' || code === 'KeyW') t.move(-1);
      else if (code === 'ArrowDown' || code === 'KeyS') t.move(1);
      if (t.closed) this.endTalk();
      return true;
    }
    if (code === 'KeyE' && this.talkTarget) {
      this.startTalk();
      return true;
    }
    return false;
  }

  private walkClick(clientX: number, clientY: number): void {
    const t = this.talk;
    if (!t) return;
    const r = this.out.getBoundingClientRect();
    const x = ((clientX - r.left) / r.width) * this.W;
    const y = ((clientY - r.top) / r.height) * this.H;
    const i = this.talkRects.findIndex((b) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h);
    if (t.mode === 'choose' && i >= 0) t.choose(i);
    else if (t.mode === 'say') t.advance();
    if (t.closed) this.endTalk();
  }

  private startTalk(): void {
    const tg = this.talkTarget;
    if (!tg) return;
    this.talk = new Talk(tg.persona);
    this.talkWith = tg.who;
    this.talkColor = tg.color;
    this.walker.frozen = true;
    if (document.pointerLockElement) document.exitPointerLock();
    if (tg.who !== 'captain') tg.who.hold({ x: this.walker.x, z: this.walker.z });
  }

  private endTalk(): void {
    if (this.talkWith && this.talkWith !== 'captain') this.talkWith.hold(null);
    this.talk = null;
    this.talkWith = null;
    this.talkRects = [];
    this.walker.frozen = false;
  }

  private findTalkTarget(): void {
    const fx = -Math.sin(this.walker.yaw), fz = -Math.cos(this.walker.yaw);
    let best: { who: Worker | 'captain'; persona: Persona; color: string } | null = null;
    let bestScore = Infinity;
    const consider = (who: Worker | 'captain', x: number, z: number, persona: Persona | undefined, color: string) => {
      if (!persona) return;
      const dx = x - this.walker.x, dz = z - this.walker.z;
      const d = Math.hypot(dx, dz);
      if (d > 2.4 || d < 1e-3) return;
      const cos = (dx * fx + dz * fz) / d;
      if (cos < 0.86) return;
      const score = d * (2 - cos);
      if (score < bestScore) { bestScore = score; best = { who, persona, color }; }
    };
    for (const w of this.crew) {
      const h = w.headWorld(this._v);
      consider(w, h.x, h.z, PERSONA_BY_ID.get(w.name), ROLE_COLOR[w.role] ?? '#A855F7');
    }
    for (const { w } of this.agents.values()) {
      const h = w.headWorld(this._v);
      if (w.tag) consider(w, h.x, h.z, agentPersona(w.tag.label), w.tag.color);
    }
    consider('captain', PROP.chair[0], PROP.chair[1], PERSONA_BY_ID.get('captain'), '#86EFAC');
    this.talkTarget = best;
  }

  private barks(): void {
    if (this.time < this.barkNext) return;
    for (const w of this.crew) {
      const p = PERSONA_BY_ID.get(w.name);
      if (!p?.barks.length) continue;
      const h = w.headWorld(this._v);
      if (Math.hypot(h.x - this.walker.x, h.z - this.walker.z) > 4.2) continue;
      if ((this.barkAt.get(w.name) ?? 0) > this.time) continue;
      if (this.say(w, p.barks[Math.floor(Math.random() * p.barks.length)], 'neutral', { life: 3.4 })) {
        this.barkAt.set(w.name, this.time + 30 + Math.random() * 25);
        this.barkNext = this.time + 7 + Math.random() * 6;
        return;
      }
    }
  }

  setWalk(on: boolean): void {
    if (on === this.walking) return;
    this.walking = on;
    if (on) {
      if (this.tour) this.setTour(false);
      this.focus(null);
      this.paydayFocusUntil = 0;
      this.walker.reset();
      this.walker.onKey = (code) => this.walkKey(code);
      this.walker.onClick = (x, y) => this.walkClick(x, y);
      this.doorOpen = 0;
      this.shell.setDoor(0);
    } else {
      this.endTalk();
      this.talkTarget = null;
    }
    this.shell.group.visible = on;
    this.renderPass.camera = on ? this.walkCam : this.camera;
    this.attachInput();
    this.onWalkChange?.(on);
  }

  focus(room: RoomId | null): void {
    this.focused = room;
    if (room) {
      const r = ROOM[room];
      this.targetGoal.set(r.cx, 0.6, r.cz);
      this.zoomGoal = this.portrait ? 1.9 : 2.3;
    } else {
      this.targetGoal.copy(this.home);
      this.zoomGoal = 1;
    }
    this.onFocusChange?.(room ? ROOM[room].name.toLowerCase() : null);
  }

  get focusedRoom(): RoomId | null {
    return this.focused;
  }

  dispose(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.detach?.();
    this.flights.clear();
    const geos = new Set<THREE.BufferGeometry>();
    const mats = new Set<THREE.Material>();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.geometry) geos.add(m.geometry);
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((x) => mats.add(x));
      else if (mat) mats.add(mat);
    });
    for (const g of Object.values(this.crewKit.g)) geos.add(g);
    for (const g of Object.values(this.kit.g)) geos.add(g);
    geos.forEach((g) => g.dispose());
    mats.forEach((m) => m.dispose());
    this.ship.dispose();
    this.shell.dispose();
    this.kit.glowTex.dispose();
    this.bloom.dispose();
    this.rt.dispose();
    this.envRT.dispose();
    this.composer.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.scene.clear();
  }


  private agentAboard(who: AgentIdentity): Worker | null {
    const have = this.agents.get(who.id);
    if (have) {
      have.lastAt = this.time;
      return have.w;
    }
    const used = new Set([...this.agents.values()].map((a) => a.w.home));
    let dock: string | undefined = AGENT_DOCKS.find((d) => !used.has(d));
    if (!dock) {
      const idle = [...this.agents.entries()].filter(([, a]) => a.w.free).sort((a, b) => a[1].lastAt - b[1].lastAt)[0];
      if (!idle) return null;
      dock = idle[1].w.home;
      this.dropAgent(idle[0]);
    }
    const w = new Worker(this.crewKit, 'agent', who.name, dock, [], this.nav, { suit: who.color, trim: shade(who.color) });
    w.tag = { label: who.label, color: who.color };
    this.agents.set(who.id, { w, lastAt: this.time });
    this.crew.push(w);
    this.ship.group.add(w.group);
    const p = w.group.position;
    this.sparks.burst(p.x, 1.0, p.z, who.color, 14, 1.6, 1.8);
    return w;
  }

  private dropAgent(id: string): void {
    const a = this.agents.get(id);
    if (!a) return;
    this.agents.delete(id);
    const i = this.crew.indexOf(a.w);
    if (i >= 0) this.crew.splice(i, 1);
    this.bubbles = this.bubbles.filter((b) => b.who !== a.w);
    a.w.dispose(this.crewKit);
  }


  private say(who: Worker | 'captain', text: string, tone: Tone, opts: { big?: boolean; force?: boolean; life?: number } = {}): boolean {
    const mine = this.bubbles.findIndex((b) => b.who === who);
    if (mine >= 0) {
      if (!opts.force) return false;
      this.bubbles.splice(mine, 1);
    }
    if (this.bubbles.length >= MAX_BUBBLES) {
      if (!opts.force) return false;
      this.bubbles.sort((a, b) => b.age - a.age);
      this.bubbles.shift();
    }
    this.bubbles.push({ who, text, tone, age: 0, life: opts.life ?? (opts.big ? 3.2 : 2.7), big: !!opts.big });
    return true;
  }

  private log(text: string, tone: Tone): void {
    this.feed.push({ text, tone, age: 0 });
    if (this.feed.length > 6) this.feed.shift();
  }

  private heat(room: RoomId, amount = 1): void {
    this.hot.set(room, Math.min(1.5, (this.hot.get(room) ?? 0) + amount));
    if (amount >= 0.8) this.lastHot = room;
  }


  private uiScale(): number {
    return this.portrait ? this.W / 720 : Math.min(this.W / 1280, this.H / 720);
  }

  private viewDir(az: number, out: THREE.Vector3): THREE.Vector3 {
    return out.set(Math.cos(ISO_EL) * Math.sin(az), Math.sin(ISO_EL), Math.cos(ISO_EL) * Math.cos(az));
  }

  private fit(): void {
    const pts: THREE.Vector3[] = [];
    const { x0, x1, z0, z1, noseX } = SHIP;
    for (const [x, z] of [[x0 - 2.2, z0], [x0 - 2.2, z1], [x1, z0], [x1, z1], [noseX, 0]] as const) {
      pts.push(new THREE.Vector3(x, -1.2, z), new THREE.Vector3(x, z < 0 ? WALL_H + 2.2 : WALL_H, z));
    }
    if (!this.portrait) pts.push(new THREE.Vector3(KALSHI_POS[0], KALSHI_POS[1] + 2.2, KALSHI_POS[2]));
    const dir = this.viewDir(ISO_AZ, this._v);
    const right = new THREE.Vector3(dir.z, 0, -dir.x).normalize();
    const up = new THREE.Vector3().crossVectors(dir, right).normalize();
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of pts) {
      const sx = p.dot(right), sy = p.dot(up);
      minX = Math.min(minX, sx); maxX = Math.max(maxX, sx);
      minY = Math.min(minY, sy); maxY = Math.max(maxY, sy);
    }
    const aspect = this.W / this.H;
    const padTop = this.portrait ? 0.3 : 0.04;
    const padBot = this.portrait ? 0.26 : 0.02;
    const needH = (maxY - minY) / (1 - padTop - padBot);
    const needW = maxX - minX;
    this.halfH = Math.max(needH, needW / aspect) / 2;
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2 + (padTop - padBot) * this.halfH;
    const g = new THREE.Vector3().addScaledVector(right, cx).addScaledVector(up, cy);
    const t = -g.y / dir.y;
    g.addScaledVector(dir, t);
    this.home.copy(g);
    if (!this.focused) {
      this.targetGoal.copy(this.home);
      if (this.time === 0) this.target.copy(this.home);
    }
  }

  private updateCamera(dt: number): void {
    if (this.walking) {
      this.walker.update(dt);
      if (this.walker.exited) {
        this.setWalk(false);
        this.updateCamera(dt);
        return;
      }
      const want = Math.max(0, Math.min(1, (1.7 - this.walker.exitDist) / 0.9));
      this.doorOpen = damp(this.doorOpen, want, 6, dt);
      this.shell.setDoor(this.doorOpen);
      if (this.talk) {
        this.talk.update(dt);
        if (this.talkWith && this.talkWith !== 'captain') this.talkWith.hold({ x: this.walker.x, z: this.walker.z });
      } else {
        this.findTalkTarget();
        this.barks();
      }
      this.walker.apply(this.walkCam);
      this.walkCam.fov = this.walker.fov;
      this.walkCam.aspect = this.W / this.H;
      this.walkCam.updateProjectionMatrix();
      this.sun.target.position.set(0, 0, 0);
      return;
    }
    if (this.tour && !this.drag) {
      this.tourT -= dt;
      if (this.tourT <= 0) {
        this.tourFocus = !this.tourFocus;
        this.tourT = this.tourFocus ? 4.5 : 6;
        this.focus(this.tourFocus ? this.lastHot : null);
      }
    }
    if (this.paydayFocusUntil > this.time) {
      if (this.focused !== 'vault') this.focus('vault');
    } else if (this.paydayFocusUntil > 0) {
      this.paydayFocusUntil = 0;
      if (!this.tour) this.focus(null);
    }

    this.target.x = damp(this.target.x, this.targetGoal.x, 3.2, dt);
    this.target.y = damp(this.target.y, this.targetGoal.y, 3.2, dt);
    this.target.z = damp(this.target.z, this.targetGoal.z, 3.2, dt);
    this.zoom = damp(this.zoom, this.zoomGoal, 3.2, dt);

    const t = this.time;
    const az = ISO_AZ + Math.sin(t * 0.11) * 0.035;
    const dir = this.viewDir(az, this._v);
    const drift = this._v2.set(Math.sin(t * 0.13) * 0.35, 0, Math.cos(t * 0.1) * 0.25);
    const look = drift.add(this.target);
    this.camera.position.copy(look).addScaledVector(dir, 80);
    this.camera.up.set(0, 1, 0);
    this.camera.lookAt(look);
    const aspect = this.W / this.H;
    const hh = this.halfH;
    this.camera.left = -hh * aspect;
    this.camera.right = hh * aspect;
    this.camera.top = hh;
    this.camera.bottom = -hh;
    this.camera.near = 1;
    this.camera.far = 220;
    this.camera.zoom = this.zoom;
    this.camera.updateProjectionMatrix();
    this.camera.updateMatrixWorld();

    this.sun.target.position.set(this.target.x * 0.3, 0, this.target.z * 0.3);
  }


  private attachInput(): void {
    this.detach?.();
    const el = this.out;
    if (this.walking) {
      this.detach = this.walker.attach(el);
      return;
    }
    const pxPerUnit = () => (el.clientHeight || 1) / ((2 * this.halfH) / this.zoom);
    const down = (e: PointerEvent) => {
      if (e.button !== 0) return;
      this.drag = { x: e.clientX, y: e.clientY, moved: false, tx: this.targetGoal.x, tz: this.targetGoal.z };
      el.setPointerCapture(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      const d = this.drag;
      if (!d) return;
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (!d.moved && Math.hypot(dx, dy) < 5) return;
      if (!d.moved) {
        d.moved = true;
        if (this.tour) this.setTour(false);
      }
      const k = 1 / pxPerUnit();
      const dir = this.viewDir(ISO_AZ, this._v);
      const right = new THREE.Vector3(dir.z, 0, -dir.x).normalize();
      const fwd = new THREE.Vector3(-dir.x, 0, -dir.z).normalize();
      const fy = 1 / Math.sin(ISO_EL);
      this.targetGoal.x = d.tx - right.x * dx * k + fwd.x * dy * k * fy;
      this.targetGoal.z = d.tz - right.z * dx * k + fwd.z * dy * k * fy;
      this.targetGoal.x = Math.max(-16, Math.min(18, this.targetGoal.x));
      this.targetGoal.z = Math.max(-14, Math.min(12, this.targetGoal.z));
    };
    const up = (e: PointerEvent) => {
      const d = this.drag;
      this.drag = null;
      try { el.releasePointerCapture(e.pointerId); } catch {}
      if (!d || d.moved) return;
      const room = this.pickRoom(e.clientX, e.clientY);
      if (this.tour) this.setTour(false);
      this.focus(room && room !== this.focused ? room : null);
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      this.zoomGoal = Math.max(0.75, Math.min(3.6, this.zoomGoal * Math.exp(-e.deltaY * 0.0015)));
    };
    el.addEventListener('pointerdown', down);
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
    el.addEventListener('wheel', wheel, { passive: false });
    this.detach = () => {
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      el.removeEventListener('wheel', wheel);
    };
  }

  private pickRoom(clientX: number, clientY: number): RoomId | null {
    const r = this.out.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    this._ray.setFromCamera(ndc, this.camera);
    const hit = this._ray.ray.intersectPlane(this._plane, this._v);
    return hit ? roomAt(hit.x, hit.z) : null;
  }


  private frame(): void {
    const now = performance.now();
    const dt = Math.min(0.05, Math.max(0, (now - this.last) / 1000));
    this.last = now;
    this.fpsFrames++;
    this.fpsAcc += dt;
    if (this.fpsAcc >= 0.5) {
      this.fps = Math.round(this.fpsFrames / this.fpsAcc);
      this.fpsFrames = 0;
      this.fpsAcc = 0;
    }
    try {
      this.update(dt);
      this.render();
    } catch (err) {
      if (!this.frameErr) {
        this.frameErr = true;
        console.error('[agent-hub] frame failed', err);
      }
    }
  }

  private update(dt: number): void {
    this.time += dt;
    this.director.update(dt);
    for (const w of this.crew) w.update(dt, this.nav);
    this.ship.update(dt, this.time);
    this.flights.update(dt);
    this.sparks.update(dt);
    this.pile.update(dt);
    for (const b of this.bubbles) b.age += dt;
    this.bubbles = this.bubbles.filter((b) => b.age < b.life);
    for (const f of this.feed) f.age += dt;
    for (const [k, v] of this.hot) this.hot.set(k, Math.max(0, v - dt * 0.6));
    this.pnlPulse = Math.max(0, this.pnlPulse - dt * 2.5);
    if (this.banner) {
      this.banner.t += dt;
      if (this.banner.t > 3.4) this.banner = null;
    }
    this.updateCamera(dt);
  }

  private project(p: THREE.Vector3): { x: number; y: number } {
    this._v2.copy(p).project(this.walking ? this.walkCam : this.camera);
    return { x: (this._v2.x * 0.5 + 0.5) * this.W, y: (-this._v2.y * 0.5 + 0.5) * this.H };
  }

  private seen(p: THREE.Vector3, maxDist: number): boolean {
    return !this.walking || visibleFrom(this.walkCam, p, maxDist);
  }

  private render(): void {
    this.composer.render();
    const g = this.ctx;
    g.drawImage(this.glCanvas, 0, 0, this.W, this.H);
    const u = this.uiScale();

    const d = this.director;
    const a = d.account;
    const n = hudNumbers(a, d.stats);
    const counters: Record<RoomId, string> = {
      research: `${(n.signals ?? d.signalsSeen).toLocaleString('en-US')} signals`,
      forge: d.forgeSign,
      backtest: d.backtestSign,
      desk: n.open !== null ? `${n.open.toLocaleString('en-US')} open` : `${d.ordersSeen.toLocaleString('en-US')} orders`,
      vault: typeof a?.todayWins === 'number' ? `${a.todayWins.toLocaleString('en-US')} wins today` : `${d.winsSeen.toLocaleString('en-US')} wins`,
      optimizer: d.optimizerSign,
      bridge: d.bridgeSign,
    };
    const signs: SignView[] = [];
    for (const r of ROOMS) {
      const at = this.walking ? this._v.set(r.cx, WALL_H, r.cz) : this._v.set(...r.sign);
      if (!this.seen(at, 13)) continue;
      const p = this.project(at);
      if (this.walking && p.y < this.H * 0.2) continue;
      const focusedOther = this.focused && this.focused !== r.id;
      signs.push({
        x: p.x, y: p.y, icon: r.icon, name: r.name, counter: counters[r.id], accent: r.accent,
        alpha: focusedOther ? 0.35 : 1, hot: Math.min(1, this.hot.get(r.id) ?? 0), focused: this.focused === r.id,
      });
    }
    drawSigns(g, signs, u * (this.portrait ? 0.85 : this.zoom > 1.6 ? 1.1 : 1), this.W);

    if (this.agents.size) {
      const tags: TagView[] = [];
      for (const { w } of this.agents.values()) {
        if (!w.tag) continue;
        const head = w.headWorld(this._v).add(this._v2.set(0, 0.32, 0));
        if (!this.seen(head, 11)) continue;
        const p = this.project(head);
        const talking = this.bubbles.some((b) => b.who === w);
        tags.push({ x: p.x, y: p.y, label: w.tag.label, color: w.tag.color, dim: talking });
      }
      tags.sort((a, b) => b.y - a.y);
      for (let i = 1; i < tags.length; i++) {
        for (let j = 0; j < i; j++) {
          if (Math.abs(tags[i].x - tags[j].x) < 130 * u && Math.abs(tags[i].y - tags[j].y) < 20 * u) {
            tags[i].y = tags[j].y - 21 * u;
          }
        }
      }
      drawTags(g, tags, u * (this.zoom > 1.6 ? 1.1 : 1));
    }

    const views: BubbleView[] = [];
    for (const b of this.bubbles) {
      const anchor = b.who === 'captain'
        ? this._v.set(PROP.chair[0], 2.05 + this.ship.mossyHop * 0.1, PROP.chair[1])
        : b.who.headWorld(this._v);
      if (!this.seen(anchor, 14)) continue;
      const p = this.project(anchor);
      views.push({ x: p.x, y: p.y, text: b.text, tone: b.tone, age: b.age, life: b.life, big: b.big });
    }
    views.sort((p, q) => p.y - q.y);
    for (let i = 1; i < views.length; i++) {
      for (let j = 0; j < i; j++) {
        if (Math.abs(views[i].x - views[j].x) < 150 * u && Math.abs(views[i].y - views[j].y) < 34 * u) {
          views[i].y = views[j].y + 36 * u;
        }
      }
    }
    drawBubbles(g, views, u * (this.zoom > 1.6 ? 1.12 : 1), this.W);

    const kAt = this._v.set(this.ship.station.position.x, this.ship.station.position.y - 1.6, this.ship.station.position.z);
    const k = this.walking ? { x: -1, y: -1 } : this.project(kAt);
    drawHud(g, {
      W: this.W, H: this.H, u, portrait: this.portrait,
      pnl: n.pnl,
      roi: n.roi,
      winRate: n.winRate,
      settledToday: n.settledToday,
      signals: n.signals,
      wins: d.winsSeen, losses: d.lossesSeen,
      pnlPulse: this.pnlPulse,
      feed: this.talk ? [] : this.feed,
      banner: this.banner,
      kalshi: k.x > 0 && k.x < this.W && k.y > 0 && k.y < this.H ? k : null,
      showBrand: true,
    });

    if (this.walking) {
      if (this.talk) {
        this.talkRects = drawDialogue(g, this.talk, { W: this.W, H: this.H, u, color: this.talkColor, t: this.time });
      } else if (this.talkTarget) {
        const p = this.talkTarget.persona;
        drawTalkPrompt(g, { W: this.W, H: this.H, u, name: p.name, title: p.title, color: this.talkTarget.color });
      }
    }
  }
}

const ROLE_COLOR: Record<string, string> = {
  researcher: '#C084FC', smith: '#F59E0B', quant: '#2DD4BF', trader: '#F472B6',
  keeper: '#FBBF24', risk: '#4ADE80', engineer: '#38BDF8', agent: '#94A3B8',
};
