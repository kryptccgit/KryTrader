import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import type { BotPosition, SignalRow } from '@shared/types';
import { balanceOf, hudNumbers, type HubData } from '../data';
import type { HubSceneEngine } from '../HubStage';
import { paydayLine, type PaydayEvent } from '../payday';
import type { ActivityRecord } from '../../state/activity';
import { beatFor } from '../engine/jobs';
import { cacheMeasureText, subject } from '../text';
import { drawHud, type FeedLine, type Tone } from '../engine/overlay';
import { Particles, Shockwaves } from './fx';
import {
  CATS, CAT_COLOR, EDGE_R, LANES, LOSS_POS, Orrery, SECTOR_R1, WINS_POS, catOf, laneRadius, sectorAngle, type Cat,
} from './system';
import { drawCoreReadout, drawFloats, drawLaneLabels, drawLegend, drawSectorLabels, drawTags, drawWell, type Float, type Tag } from './overlay';


const MAX_PLANETS = 30;
const MIN_LIFE = 4.5;
const MAX_COMETS = 3;

const WHALE = '#A855F7';
const MOMO = '#EC4899';

type PlanetState = 'arrive' | 'orbit' | 'nova' | 'implode' | 'fade';

interface Planet {
  key: string;
  posId: number | null;
  sigId: number | null;
  ticker: string;
  dir: 'yes' | 'no';
  label: string;
  cat: Cat;
  r: number;
  theta: number;
  omega: number;
  size: number;
  mesh: THREE.Mesh;
  halo: THREE.Sprite;
  born: number;
  from: { r: number; theta: number; y: number } | null;
  state: PlanetState;
  stateT: number;
  finaleAt: number | null;
  won: boolean | null;
  pnl: number | null;
}

interface Comet {
  sig: SignalRow;
  whale: boolean;
  color: string;
  a0: number;
  laneR: number;
  t: number;
  dur: number;
  capture: boolean;
  head: THREE.Sprite;
  label: string;
  pos: THREE.Vector3;
  emitAcc: number;
}

function damp(a: number, b: number, k: number, dt: number): number {
  return b + (a - b) * Math.exp(-k * dt);
}

function polar(r: number, theta: number, y: number, out: THREE.Vector3): THREE.Vector3 {
  return out.set(Math.cos(theta) * r, y, -Math.sin(theta) * r);
}

function k(v: number): string {
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(v >= 1e4 ? 0 : 1)}K`;
  return `$${v.toFixed(0)}`;
}

function priceOf(c: number | null | undefined): number | null {
  return typeof c === 'number' && c >= 1 && c <= 99 ? c : null;
}

export class OrbitalEngine implements HubSceneEngine {
  private out: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private W = 1280;
  private H = 720;
  private glCanvas = document.createElement('canvas');
  private renderer: THREE.WebGLRenderer;
  private composer: EffectComposer;
  private bloom: UnrealBloomPass;
  private rt: THREE.WebGLRenderTarget;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(38, 16 / 9, 0.1, 300);

  private orrery = new Orrery();
  private particles = new Particles(3200);
  private waves = new Shockwaves(12);
  private planetGeo = new THREE.SphereGeometry(1, 28, 18);
  private catMats = new Map<Cat, THREE.MeshStandardMaterial>();
  private haloMats = new Map<Cat, THREE.SpriteMaterial>();
  private headMats = { whale: null as THREE.SpriteMaterial | null, momo: null as THREE.SpriteMaterial | null };
  private planets: Planet[] = [];
  private comets: Comet[] = [];

  private seenSig = new Set<string>();
  private seenPos = new Map<number, string>();
  private primed = false;
  private runId: number | null = null;
  private latest: HubData | null = null;
  private posById = new Map<number, BotPosition>();
  private sigQ: SignalRow[] = [];
  private openQ: BotPosition[] = [];
  private cometCd = 0.5;
  private spawnCd = 0.3;
  private finaleCd = 0;
  private wins = 0;
  private losses = 0;
  private winUsd = 0;
  private lossUsd = 0;

  private feed: FeedLine[] = [];
  private floats: (Float & { wx: number; wy: number; wz: number })[] = [];
  private banner: { text: string; sub: string; t: number } | null = null;
  private pnlPulse = 0;
  private lastPnl: number | null = null;
  private lastNova: { pos: THREE.Vector3; t: number } | null = null;
  private stormT = 0;

  private yaw = 0;
  private pitch = 0.95;
  private dist = 25;
  private target = new THREE.Vector3(0, 0, 1);
  private userYaw = 0;
  private userPitch = 0;
  private userZoom = 1;
  private follow: Planet | null = null;
  private tour = false;
  private drag: { x: number; y: number; moved: boolean; yaw: number; pitch: number } | null = null;
  private detach: (() => void) | null = null;

  private raf = 0;
  private running = false;
  private last = 0;
  private time = 0;
  private frameErr = false;
  private fpsFrames = 0;
  private fpsAcc = 0;
  fps = 0;
  onTourChange: ((on: boolean) => void) | null = null;
  onFocusChange: ((label: string | null) => void) | null = null;

  private _v = new THREE.Vector3();
  private _v2 = new THREE.Vector3();
  private _c = new THREE.Color();

  constructor(canvas: HTMLCanvasElement, w: number, h: number) {
    this.out = canvas;
    const ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) throw new Error('2D canvas unavailable');
    this.ctx = cacheMeasureText(ctx);

    this.renderer = new THREE.WebGLRenderer({ canvas: this.glCanvas, antialias: false, alpha: false, stencil: false, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(1);
    this.renderer.toneMapping = THREE.NeutralToneMapping;
    this.renderer.toneMappingExposure = 1.0;

    this.scene.background = new THREE.Color('#02040c');
    this.scene.add(new THREE.AmbientLight('#4c5c9a', 0.45));
    this.scene.add(this.orrery.group, this.particles.points, this.waves.group);
    for (const cat of CATS) {
      this.catMats.set(cat, new THREE.MeshStandardMaterial({ color: CAT_COLOR[cat], emissive: CAT_COLOR[cat], emissiveIntensity: 0.25, roughness: 0.45, metalness: 0.1 }));
      this.haloMats.set(cat, new THREE.SpriteMaterial({ map: this.orrery.glowTex, color: CAT_COLOR[cat], transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
    }
    this.headMats.whale = new THREE.SpriteMaterial({ map: this.orrery.glowTex, color: WHALE, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
    this.headMats.momo = new THREE.SpriteMaterial({ map: this.orrery.glowTex, color: MOMO, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });

    this.rt = new THREE.WebGLRenderTarget(w, h, { type: THREE.HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(this.renderer, this.rt);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(w, h), 0.7, 0.5, 0.9);
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
    this.latest = d;
    const runId = d.account?.sessionRunId ?? 0;
    if (this.primed && this.runId !== null && runId !== this.runId) {
      this.seenSig.clear();
      this.seenPos.clear();
      this.primed = false;
      this.wins = this.losses = 0;
      this.winUsd = this.lossUsd = 0;
    }
    this.runId = runId;

    this.posById.clear();
    for (const p of d.positions) this.posById.set(p.id, p);

    for (const s of d.signals.slice(0, 60)) {
      const key = `${s.source}:${s.id}`;
      if (this.seenSig.has(key)) continue;
      this.seenSig.add(key);
      if (!this.primed) continue;
      this.sigQ.push(s);
    }
    if (this.sigQ.length > 3) {
      this.sigQ.sort((a, b) => (b.source === 'whale' ? 1 : 0) - (a.source === 'whale' ? 1 : 0) || (b.dollarValue ?? 0) - (a.dollarValue ?? 0));
      this.sigQ.length = 3;
    }
    if (this.seenSig.size > 4000) this.seenSig = new Set(d.signals.map((x) => `${x.source}:${x.id}`));

    for (const p of d.positions) {
      const sig = p.resolved ? `r:${p.outcomeCorrect}` : 'o';
      const prev = this.seenPos.get(p.id);
      this.seenPos.set(p.id, sig);
      if (!this.primed || prev === sig) continue;
      const live = p.status === 'filled' || p.status === 'partial';
      if (prev === undefined && live && !p.resolved) {
        this.openQ.push(p);
        if (this.openQ.length > 6) this.openQ.shift();
      }
      if (p.resolved && prev !== sig) {
        if (p.outcomeCorrect === 1) { this.wins++; this.winUsd += p.pnlUsd ?? 0; }
        else if (p.outcomeCorrect === 0) { this.losses++; this.lossUsd += p.pnlUsd ?? 0; }
      }
    }
    if (this.seenPos.size > 6000) {
      for (const id of this.seenPos.keys()) if (!this.posById.has(id)) this.seenPos.delete(id);
    }
    this.primed = true;

    const now = this.time;
    const bound = new Set(this.planets.map((p) => p.posId).filter((x): x is number => x !== null));
    for (const pl of this.planets) {
      if (pl.state !== 'orbit' && pl.state !== 'arrive') continue;
      if (pl.posId === null && pl.sigId !== null) {
        const match = d.positions.find((p) => !bound.has(p.id) && !p.resolved
          && (p.signalId === pl.sigId || (p.ticker === pl.ticker && p.direction === pl.dir)));
        if (match) {
          pl.posId = match.id;
          bound.add(match.id);
          pl.size = THREE.MathUtils.clamp(0.13 + Math.sqrt(Math.max(0, match.costUsd ?? 0)) * 0.045, 0.13, 0.42);
        }
        else if (now - pl.born > 12) { pl.state = 'fade'; pl.stateT = 0; }
      }
      if (pl.posId === null || pl.finaleAt !== null) continue;
      const p = this.posById.get(pl.posId);
      if (!p) { pl.state = 'fade'; pl.stateT = 0; continue; }
      if (p.resolved && p.outcomeCorrect !== null) {
        pl.won = p.outcomeCorrect === 1;
        pl.pnl = p.pnlUsd ?? null;
        pl.finaleAt = Math.max(now, pl.born + MIN_LIFE);
      }
    }

    const a = d.account;
    const bal = balanceOf(a);
    if (a && bal !== null && a.startBankrollUsd > 0) this.orrery.setBankroll(bal / a.startBankrollUsd);
    const pnl = hudNumbers(a, d.scannerStats).pnl;
    if (pnl !== null && this.lastPnl !== null) {
      const bank = a?.startBankrollUsd || 1000;
      this.pnlPulse = Math.max(this.pnlPulse, Math.min(1, Math.abs(pnl - this.lastPnl) / (bank * 0.01)));
    }
    this.lastPnl = pnl;
  }

  activity(rec: ActivityRecord, _replay: boolean): void {
    const ev = rec.ev;
    if (ev.kind !== 'manualOrder' && ev.kind !== 'agent' && ev.kind !== 'aiAnalysis') return;
    const b = beatFor(ev);
    if (b && (b.room === 'desk' || b.room === 'research')) this.log(b.log, b.tone);
  }

  payday(ev: PaydayEvent): void {
    this.banner = { text: 'PAYDAY!', sub: paydayLine(ev), t: 0 };
    this.orrery.flare = 1;
    this.waves.fire(0, 0.1, 0, '#FFD27A', 13, 1.6);
    this.waves.fire(0, 0.1, 0, '#FDE68A', 8, 1.1);
    this.particles.burst(0, 0.3, 0, '#FFE08A', 160, 9, 2.4, 1.4);
    this.stormT = 2.6;
    this.lastNova = { pos: new THREE.Vector3(0, 0, 0), t: this.time };
    this.log(`☀️ PAYDAY ${paydayLine(ev)}`, 'gold');
  }

  setOutput(canvas: HTMLCanvasElement, w: number, h: number, _mode: 'page' | 'cinema'): void {
    w = Math.max(64, Math.round(w));
    h = Math.max(64, Math.round(h));
    if (canvas !== this.out) {
      const ctx = canvas.getContext('2d', { alpha: false });
      if (!ctx) throw new Error('2D canvas unavailable');
      this.out = canvas;
      this.ctx = cacheMeasureText(ctx);
    }
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    this.W = w;
    this.H = h;
    this.renderer.setSize(w, h, false);
    this.composer.setSize(w, h);
    this.bloom.setSize(Math.round(w / 2), Math.round(h / 2));
    this.particles.setPixelScale(Math.max(0.6, h / 720));
    this.orrery.setPixelScale(Math.max(0.75, h / 720));
    this.attachInput();
  }

  setTour(on: boolean): void {
    if (this.tour === on) return;
    this.tour = on;
    if (on) this.setFollow(null);
    this.onTourChange?.(on);
  }

  resetView(): void {
    this.userYaw = 0;
    this.userPitch = 0;
    this.userZoom = 1;
    this.setFollow(null);
  }

  private setFollow(p: Planet | null): void {
    this.follow = p;
    this.onFocusChange?.(p ? p.label.toLowerCase() : null);
  }

  dispose(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
    this.detach?.();
    const geos = new Set<THREE.BufferGeometry>();
    const mats = new Set<THREE.Material>();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.geometry) geos.add(m.geometry);
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((x) => mats.add(x));
      else if (mat) mats.add(mat);
    });
    geos.add(this.planetGeo);
    this.catMats.forEach((m) => mats.add(m));
    this.haloMats.forEach((m) => mats.add(m));
    if (this.headMats.whale) mats.add(this.headMats.whale);
    if (this.headMats.momo) mats.add(this.headMats.momo);
    geos.forEach((g) => g.dispose());
    mats.forEach((m) => m.dispose());
    this.particles.dispose();
    this.waves.dispose();
    this.orrery.dispose();
    this.bloom.dispose();
    this.rt.dispose();
    this.composer.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.scene.clear();
    this.planets = [];
    this.comets = [];
  }

  private log(text: string, tone: Tone): void {
    this.feed.push({ text, tone, age: 0 });
    if (this.feed.length > 6) this.feed.shift();
  }

  private float(pos: THREE.Vector3, text: string, color: string, big = false): void {
    this.floats.push({ x: 0, y: 0, wx: pos.x, wy: pos.y + 0.6, wz: pos.z, text, color, age: 0, life: big ? 2.4 : 1.8, big });
    if (this.floats.length > 8) this.floats.shift();
  }


  private spawnComet(s: SignalRow): void {
    const whale = s.source === 'whale';
    const cat = catOf(s.category);
    const price = priceOf(s.priceCents);
    const head = new THREE.Sprite((whale ? this.headMats.whale : this.headMats.momo)!.clone());
    head.scale.setScalar(whale ? 1.3 : 1.0);
    this.scene.add(head);
    const subj = subject(s.ticker, s.title);
    const dir = s.direction.toUpperCase();
    const a0 = sectorAngle(cat) + (Math.random() - 0.5) * 0.5;
    const c: Comet = {
      sig: s, whale, color: whale ? WHALE : MOMO, a0,
      laneR: price !== null ? laneRadius(price) : 6,
      t: 0, dur: s.traded ? 2.6 : 3.2, capture: s.traded,
      head,
      label: whale && s.dollarValue ? `🐋 ${k(s.dollarValue)} ${dir} · ${subj}` : `↗ ${subj} ${dir}${price !== null ? ` ${price}¢` : ''}`,
      pos: new THREE.Vector3(),
      emitAcc: 0,
    };
    this.comets.push(c);
    this.orrery.pulseSector(cat);
    this.log(whale && s.dollarValue ? `🐋 ${k(s.dollarValue)} ${dir} on ${subj}` : `☄️ momentum: ${subj} ${dir}`, whale ? 'whale' : 'momo');
  }

  private makePlanet(opts: { key: string; posId: number | null; sigId: number | null; ticker: string; title: string; dir: 'yes' | 'no'; cat: Cat; price: number | null; stake: number; from: { r: number; theta: number; y: number } | null; theta: number }): Planet {
    const r = opts.price !== null ? laneRadius(opts.price) : 6;
    const size = THREE.MathUtils.clamp(0.13 + Math.sqrt(Math.max(0, opts.stake)) * 0.045, 0.13, 0.42);
    const mesh = new THREE.Mesh(this.planetGeo, this.catMats.get(opts.cat)!);
    const halo = new THREE.Sprite(this.haloMats.get(opts.cat)!);
    this.scene.add(mesh, halo);
    const p: Planet = {
      key: opts.key, posId: opts.posId, sigId: opts.sigId, ticker: opts.ticker, dir: opts.dir,
      label: subject(opts.ticker, opts.title).slice(0, 14), cat: opts.cat,
      r, theta: opts.theta,
      omega: (0.9 / Math.pow(r, 1.5)) * 3.2,
      size, mesh, halo, born: this.time, from: opts.from,
      state: opts.from ? 'arrive' : 'orbit', stateT: 0, finaleAt: null, won: null, pnl: null,
    };
    this.planets.push(p);
    return p;
  }

  private spawnFromPosition(pos: BotPosition): void {
    const cat = catOf(pos.category);
    const theta = sectorAngle(cat) + (Math.random() - 0.5) * 0.6;
    this.makePlanet({
      key: `p:${pos.id}`, posId: pos.id, sigId: pos.signalId, ticker: pos.ticker, title: pos.title, dir: pos.direction, cat,
      price: priceOf(pos.avgFillPriceCents ?? pos.limitPriceCents), stake: pos.costUsd ?? 0,
      from: { r: SECTOR_R1 + 1.2, theta: theta - 0.25, y: 0.8 }, theta,
    });
  }

  private finale(p: Planet): void {
    const pos = p.mesh.position.clone();
    p.stateT = 0;
    if (p.won) {
      p.state = 'nova';
      const col = CAT_COLOR[p.cat];
      this.waves.fire(pos.x, pos.y, pos.z, '#86EFAC', 2.6, 0.9);
      this.particles.burst(pos.x, pos.y, pos.z, '#FFFFFF', 26, 4.5, 1.6, 0.8);
      this.particles.burst(pos.x, pos.y, pos.z, col, 20, 3, 1.4, 0.9);
      const n = THREE.MathUtils.clamp(Math.round((p.pnl ?? 10) / 1.2), 12, 30);
      for (let i = 0; i < n; i++) {
        this.particles.emit({
          x: pos.x + (Math.random() - 0.5) * 0.4, y: pos.y, z: pos.z + (Math.random() - 0.5) * 0.4,
          color: i % 3 ? '#FCD34D' : '#FEF3C7', size: 2.6, life: 1.3 + i * 0.035,
          home: WINS_POS.clone().add(this._v2.set((Math.random() - 0.5) * 0.8, 0.2, (Math.random() - 0.5) * 0.8)),
        });
      }
      window.setTimeout(() => this.orrery.pulseWins(), 1300);
      const txt = p.pnl !== null ? `+$${p.pnl.toFixed(2)}` : 'WIN';
      this.float(pos, txt, '#6EE7B7', (p.pnl ?? 0) >= 25);
      this.log(`💥 nova ${txt} · ${p.label}`, 'win');
    } else {
      p.state = 'implode';
      this.waves.fire(pos.x, pos.y, pos.z, '#F87171', 2.2, 0.7, true);
      for (let i = 0; i < 18; i++) {
        const a = Math.random() * Math.PI * 2, r = 1 + Math.random() * 0.8;
        this.particles.emit({ x: pos.x + Math.cos(a) * r, y: pos.y, z: pos.z + Math.sin(a) * r, color: '#F87171', size: 1.1, life: 0.5, home: pos.clone() });
      }
      for (let i = 0; i < 8; i++) {
        this.particles.emit({ x: pos.x, y: pos.y, z: pos.z, color: '#7F1D1D', size: 1.4, life: 1.2 + i * 0.05, home: LOSS_POS.clone().setY(0.3) });
      }
      window.setTimeout(() => this.orrery.pulseLoss(), 1200);
      const txt = p.pnl !== null ? `−$${Math.abs(p.pnl).toFixed(2)}` : 'LOSS';
      this.float(pos, txt, '#FCA5A5');
      this.log(`🕳 imploded ${txt} · ${p.label}`, 'loss');
    }
    this.lastNova = { pos, t: this.time };
  }

  private removePlanet(p: Planet): void {
    p.mesh.removeFromParent();
    p.halo.removeFromParent();
    if (this.follow === p) this.setFollow(null);
  }


  private ui(): number {
    return Math.min(this.W / 1280, this.H / 720);
  }

  private updateCamera(dt: number): void {
    let dist = 31;
    let pitch = 0.95;
    const target = this._v.set(0, 0, 0.4);
    if (this.tour) {
      const comet = this.comets[this.comets.length - 1];
      const nova = this.lastNova && this.time - this.lastNova.t < 2.4 ? this.lastNova : null;
      if (nova) { target.copy(nova.pos); dist = 10; pitch = 0.7; }
      else if (comet && comet.t < comet.dur * 0.85) { target.copy(comet.pos).multiplyScalar(0.7); dist = 13; pitch = 0.72; }
    }
    if (this.stormT > 0 && !this.follow) { target.set(-4, 0, 0.5); dist = 24; }
    if (this.follow) {
      target.copy(this.follow.mesh.position);
      dist = 8;
      pitch = 0.7;
    }
    const yawGoal = this.userYaw + Math.sin(this.time * 0.05) * 0.18;
    const pitchGoal = THREE.MathUtils.clamp(pitch + this.userPitch, 0.25, 1.4);
    const kk = this.tour || this.follow ? 2.0 : 1.4;
    this.target.x = damp(this.target.x, target.x, kk, dt);
    this.target.y = damp(this.target.y, target.y, kk, dt);
    this.target.z = damp(this.target.z, target.z, kk, dt);
    this.dist = damp(this.dist, dist * this.userZoom, kk, dt);
    this.yaw = damp(this.yaw, yawGoal, kk, dt);
    this.pitch = damp(this.pitch, pitchGoal, kk, dt);
    const cp = Math.cos(this.pitch);
    this.camera.position.set(
      this.target.x + Math.sin(this.yaw) * cp * this.dist,
      this.target.y + Math.sin(this.pitch) * this.dist,
      this.target.z + Math.cos(this.yaw) * cp * this.dist,
    );
    this.camera.lookAt(this.target);
    const aspect = this.W / this.H;
    const byW = 2 * Math.atan(0.62 / aspect);
    const byH = 2 * Math.atan(9.6 / 31);
    this.camera.fov = THREE.MathUtils.clamp(THREE.MathUtils.radToDeg(Math.max(byW, byH)), 26, 52);
    this.camera.aspect = aspect;
    this.camera.updateProjectionMatrix();
  }


  private attachInput(): void {
    this.detach?.();
    const el = this.out;
    const down = (e: PointerEvent) => {
      if (e.button !== 0) return;
      this.drag = { x: e.clientX, y: e.clientY, moved: false, yaw: this.userYaw, pitch: this.userPitch };
      el.setPointerCapture(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      const d = this.drag;
      if (!d) return;
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (!d.moved && Math.hypot(dx, dy) < 5) return;
      d.moved = true;
      this.userYaw = d.yaw - dx * 0.004;
      this.userPitch = THREE.MathUtils.clamp(d.pitch + dy * 0.003, -0.6, 0.45);
    };
    const up = (e: PointerEvent) => {
      const d = this.drag;
      this.drag = null;
      try { el.releasePointerCapture(e.pointerId); } catch {}
      if (!d || d.moved) return;
      const p = this.pick(e.clientX, e.clientY);
      if (this.tour && p) this.setTour(false);
      this.setFollow(p && p !== this.follow ? p : null);
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      this.userZoom = THREE.MathUtils.clamp(this.userZoom * Math.exp(e.deltaY * 0.0012), 0.4, 1.5);
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

  private pick(clientX: number, clientY: number): Planet | null {
    const r = this.out.getBoundingClientRect();
    const px = ((clientX - r.left) / r.width) * this.W;
    const py = ((clientY - r.top) / r.height) * this.H;
    let best: Planet | null = null;
    let bd = (40 * this.ui()) ** 2;
    for (const p of this.planets) {
      if (p.state !== 'orbit' && p.state !== 'arrive') continue;
      const s = this.project(p.mesh.position);
      const d = (s.x - px) ** 2 + (s.y - py) ** 2;
      if (d < bd) { bd = d; best = p; }
    }
    return best;
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
        console.error('[orbital] frame failed', err);
      }
    }
  }

  private update(dt: number): void {
    this.time += dt;
    const t = this.time;

    this.cometCd -= dt;
    if (this.cometCd <= 0 && this.sigQ.length && this.comets.length < MAX_COMETS) {
      this.cometCd = 0.9 + Math.random() * 0.6;
      this.spawnComet(this.sigQ.shift()!);
    }
    this.spawnCd -= dt;
    const alive = this.planets.filter((p) => p.state === 'orbit' || p.state === 'arrive').length;
    if (this.spawnCd <= 0 && this.openQ.length && alive < MAX_PLANETS) {
      this.spawnCd = 0.55 + Math.random() * 0.35;
      const p = this.openQ.pop()!;
      const cur = this.posById.get(p.id);
      if (cur && !cur.resolved) this.spawnFromPosition(cur);
    }
    this.finaleCd -= dt;

    for (let i = this.comets.length - 1; i >= 0; i--) {
      const c = this.comets[i];
      c.t += dt;
      const u = Math.min(1, c.t / c.dur);
      let r: number, a: number, y: number;
      if (c.capture) {
        const e = 1 - Math.pow(1 - u, 2.4);
        r = EDGE_R + (c.laneR - EDGE_R) * e;
        a = c.a0 + e * 1.5;
        y = 3.2 * (1 - e);
      } else {
        const e = u;
        const rr = Math.abs(1 - 2 * e);
        r = 1.9 + (EDGE_R + 4 - 1.9) * rr * rr;
        a = c.a0 + e * 3.4;
        y = 3.2 * (1 - e) + (e > 0.5 ? (e - 0.5) * 4 : 0);
      }
      polar(r, a, y, c.pos);
      c.head.position.copy(c.pos);
      const fade = c.capture ? 1 : Math.min(1, (1 - u) * 4);
      c.head.material.opacity = fade;
      c.emitAcc += dt;
      while (c.emitAcc > 1 / 70) {
        c.emitAcc -= 1 / 70;
        this.particles.emit({ x: c.pos.x, y: c.pos.y, z: c.pos.z, vx: (Math.random() - 0.5) * 0.2, vy: (Math.random() - 0.5) * 0.2, vz: (Math.random() - 0.5) * 0.2, color: c.color, size: c.whale ? 1.6 : 1.2, life: 0.55 * fade, drag: 1 });
      }
      if (u >= 1) {
        c.head.removeFromParent();
        c.head.material.dispose();
        this.comets.splice(i, 1);
        if (c.capture) {
          const s = c.sig;
          this.particles.burst(c.pos.x, c.pos.y, c.pos.z, c.color, 14, 2, 1.2, 0.6);
          this.waves.fire(c.pos.x, 0, c.pos.z, c.color, 1.2, 0.6);
          const pl = this.makePlanet({
            key: `s:${s.source}:${s.id}`, posId: null, sigId: s.id, ticker: s.ticker, title: s.title, dir: s.direction,
            cat: catOf(s.category), price: priceOf(s.priceCents), stake: s.dollarValue ? Math.min(400, s.dollarValue / 100) : 20,
            from: null, theta: a,
          });
          this.float(c.pos, 'CAPTURED · BUY', c.color);
          if (this.tour) this.lastNova = { pos: new THREE.Vector3(c.pos.x, 0, c.pos.z), t: this.time - 1.2 };
          void pl;
        } else {
          this.log(`↺ slingshot: skipped ${subject(c.sig.ticker, c.sig.title)}`, 'neutral');
        }
      }
    }

    for (let i = this.planets.length - 1; i >= 0; i--) {
      const p = this.planets[i];
      p.stateT += dt;
      p.theta += p.omega * dt;
      const pos = p.mesh.position;
      let scale = p.size;
      switch (p.state) {
        case 'arrive': {
          const k2 = Math.min(1, p.stateT / 1.5);
          const e = 1 - Math.pow(1 - k2, 3);
          const f = p.from!;
          polar(f.r + (p.r - f.r) * e, f.theta + (p.theta - f.theta) * e, f.y * (1 - e) + 0.15, pos);
          scale *= 0.3 + 0.7 * e;
          if (k2 >= 1) { p.state = 'orbit'; p.stateT = 0; }
          break;
        }
        case 'orbit':
          polar(p.r, p.theta, 0.15 + Math.sin(t * 1.3 + p.r) * 0.04, pos);
          if (p.finaleAt !== null && t >= p.finaleAt) {
            if (this.finaleCd <= 0) { this.finaleCd = 0.32; this.finale(p); }
            else if (t - p.finaleAt > 3) { p.state = 'fade'; p.stateT = 0; }
          }
          break;
        case 'nova': {
          const k2 = p.stateT / 0.55;
          scale *= 1 + k2 * 2.5;
          const m = p.mesh.material as THREE.MeshStandardMaterial;
          if (m === this.catMats.get(p.cat)) p.mesh.material = m.clone();
          const own = p.mesh.material as THREE.MeshStandardMaterial;
          own.emissive.set('#FFFFFF');
          own.emissiveIntensity = 2 + k2 * 4;
          own.transparent = true;
          own.opacity = Math.max(0, 1 - k2);
          if (p.halo.material === this.haloMats.get(p.cat)) p.halo.material = p.halo.material.clone();
          p.halo.material.opacity = 0.9 * Math.max(0, 1 - k2);
          if (k2 >= 1) {
            this.removePlanet(p);
            own.dispose();
            p.halo.material.dispose();
            this.planets.splice(i, 1);
            continue;
          }
          break;
        }
        case 'implode': {
          const k2 = p.stateT / 0.6;
          scale *= Math.max(0.02, 1 - k2 * k2);
          if (k2 >= 1) { this.removePlanet(p); this.planets.splice(i, 1); continue; }
          break;
        }
        case 'fade': {
          const k2 = p.stateT / 0.8;
          scale *= Math.max(0.02, 1 - k2);
          polar(p.r, p.theta, 0.15, pos);
          if (k2 >= 1) { this.removePlanet(p); this.planets.splice(i, 1); continue; }
          break;
        }
      }
      p.mesh.scale.setScalar(scale);
      p.halo.position.copy(pos);
      p.halo.scale.setScalar(scale * (p.state === 'nova' ? 9 : 5.5));
    }

    if (this.stormT > 0) {
      this.stormT -= dt;
      for (let i = 0; i < 3; i++) {
        const a = Math.random() * Math.PI * 2;
        this.particles.emit({
          x: Math.cos(a) * 1.4, y: 0.4, z: Math.sin(a) * 1.4, color: Math.random() < 0.7 ? '#FCD34D' : '#FFFFFF', size: 1.7,
          life: 1.2 + Math.random() * 0.5, home: WINS_POS.clone().add(this._v2.set((Math.random() - 0.5), 0.2, (Math.random() - 0.5))),
        });
      }
      if (Math.random() < dt * 4) this.orrery.pulseWins();
    }

    this.orrery.update(dt, t);
    this.particles.update(dt);
    this.waves.update(dt);
    for (const f of this.feed) f.age += dt;
    for (const f of this.floats) f.age += dt;
    this.floats = this.floats.filter((f) => f.age < f.life);
    this.pnlPulse = Math.max(0, this.pnlPulse - dt * 2.5);
    if (this.banner) {
      this.banner.t += dt;
      if (this.banner.t > 3.4) this.banner = null;
    }
    this.updateCamera(dt);
  }

  private project(p: THREE.Vector3): { x: number; y: number; ok: boolean } {
    this._v2.copy(p).project(this.camera);
    return { x: (this._v2.x * 0.5 + 0.5) * this.W, y: (-this._v2.y * 0.5 + 0.5) * this.H, ok: this._v2.z < 1 };
  }

  private render(): void {
    this.composer.render();
    const g = this.ctx;
    g.drawImage(this.glCanvas, 0, 0, this.W, this.H);
    const u = this.ui();
    const P = (x: number, y: number, z: number) => this.project(this._v.set(x, y, z));

    const sl = CATS.map((cat) => {
      const a = sectorAngle(cat);
      const s = P(Math.cos(a) * (SECTOR_R1 + 1.6), 0, -Math.sin(a) * (SECTOR_R1 + 1.6));
      return { x: s.x, y: s.y, text: cat, color: CAT_COLOR[cat], hot: 0 };
    });
    drawSectorLabels(g, sl, u);
    const la = -0.42;
    const lanes = LANES.map((p) => {
      const r = laneRadius(p);
      const s = P(Math.cos(la) * r, 0, -Math.sin(la) * r);
      return { x: s.x, y: s.y, text: `${p}¢` };
    });
    drawLaneLabels(g, lanes, null, u);

    const tags: Tag[] = [];
    for (const c of this.comets) {
      const s = this.project(c.pos);
      if (s.ok) tags.push({ x: s.x, y: s.y, text: c.label, color: c.color === WHALE ? '#D8B4FE' : '#F9A8D4', alpha: Math.min(1, c.t * 3) * (c.capture ? 1 : Math.min(1, (1 - c.t / c.dur) * 3)), size: c.whale ? 1.2 : 1.05, dot: true });
    }
    const ordered = [...this.planets].sort((a, b) => (b === this.follow ? 1 : 0) - (a === this.follow ? 1 : 0) || b.size - a.size);
    for (const p of ordered) {
      if (p.state !== 'orbit' && p.state !== 'arrive') continue;
      const s = this.project(p.mesh.position);
      if (!s.ok) continue;
      tags.push({ x: s.x, y: s.y, text: `${p.label} ${p.dir.toUpperCase()}`, color: CAT_COLOR[p.cat], alpha: p.state === 'arrive' ? Math.min(1, p.stateT * 2) : 0.92, size: p === this.follow ? 1.3 : 0.95, dot: true });
    }
    drawTags(g, tags, u, 16);

    const a = this.latest?.account ?? null;
    const cs = P(0, 0, 2.3);
    const n = hudNumbers(a, this.latest?.scannerStats ?? null);
    drawCoreReadout(g, cs.x, cs.y, n.pnl, balanceOf(a), u, this.pnlPulse);
    const ws = P(WINS_POS.x, 0, WINS_POS.z + 2.9);
    drawWell(g, ws.x, ws.y, 'WINS', this.wins, this.winUsd, '#4ADE80', u, 0);
    const ls = P(LOSS_POS.x, 0, LOSS_POS.z + 2.9);
    drawWell(g, ls.x, ls.y, 'LOSSES', this.losses, this.lossUsd, '#F87171', u, 0);
    for (const f of this.floats) {
      const s = P(f.wx, f.wy, f.wz);
      f.x = s.x; f.y = s.y;
    }
    drawFloats(g, this.floats, u);
    drawLegend(g, this.W, this.H, u);

    drawHud(g, {
      W: this.W, H: this.H, u, portrait: false,
      pnl: n.pnl,
      roi: n.roi,
      winRate: n.winRate,
      settledToday: n.settledToday,
      signals: n.signals,
      wins: this.wins, losses: this.losses,
      pnlPulse: this.pnlPulse,
      feed: this.feed,
      banner: this.banner,
      kalshi: null,
      showBrand: true,
      brandSub: 'ORBITAL · krypt.cc',
      brandColors: ['#67E8F9', '#818CF8', '#C084FC'],
    });
  }
}
