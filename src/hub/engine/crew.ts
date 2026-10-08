import * as THREE from 'three';
import type { NavGraph } from './nav';
import type { NavNode } from './layout';
import { bakePart } from './bake';

export type Role = 'researcher' | 'smith' | 'quant' | 'trader' | 'keeper' | 'risk' | 'engineer' | 'agent';
export type Anim = 'idle' | 'type' | 'hammer' | 'look' | 'wrench' | 'cheer' | 'grab' | 'panic';

export type Step =
  | { k: 'go'; to: string; run?: boolean }
  | { k: 'work'; anim: Anim; dur: number; onBeat?: () => void }
  | { k: 'do'; fn: (w: Worker) => void }
  | { k: 'waitFor'; cond: () => boolean; max: number; anim?: Anim };

export interface RoleStyle {
  suit: string;
  trim: string;
  homeAnim: Anim;
  speed: number;
  hat: 'none' | 'hardhat' | 'cap' | 'helmet' | 'goggles' | 'headset' | 'glasses' | 'bandana' | 'antenna';
  tool: 'none' | 'clipboard' | 'hammer' | 'tablet' | 'wrench';
  coat?: boolean;
}

export const ROLE_STYLE: Record<Role, RoleStyle> = {
  researcher: { suit: '#F4F2FA', trim: '#A855F7', homeAnim: 'type', speed: 1.7, hat: 'goggles', tool: 'clipboard', coat: true },
  smith: { suit: '#F97316', trim: '#7C2D12', homeAnim: 'idle', speed: 1.6, hat: 'bandana', tool: 'hammer' },
  quant: { suit: '#14B8A6', trim: '#0F766E', homeAnim: 'look', speed: 2.0, hat: 'glasses', tool: 'tablet' },
  trader: { suit: '#EC4899', trim: '#831843', homeAnim: 'type', speed: 1.8, hat: 'headset', tool: 'none' },
  keeper: { suit: '#22C55E', trim: '#14532D', homeAnim: 'idle', speed: 2.1, hat: 'cap', tool: 'none' },
  risk: { suit: '#EF4444', trim: '#7F1D1D', homeAnim: 'type', speed: 1.9, hat: 'helmet', tool: 'none' },
  engineer: { suit: '#FACC15', trim: '#854D0E', homeAnim: 'wrench', speed: 1.6, hat: 'hardhat', tool: 'wrench' },
  agent: { suit: '#94A3B8', trim: '#1E293B', homeAnim: 'look', speed: 2.6, hat: 'antenna', tool: 'tablet' },
};

const SKIN = ['#F5D0B5', '#E0AC8A', '#C68863', '#8D5A3B', '#F2C9A0', '#D9A37E'];
const HAIR = ['#2B1D14', '#5B3A1E', '#C9A227', '#1F1F2E', '#B45309', '#E5E7EB'];

export class CrewKit {
  readonly g = {
    head: new THREE.SphereGeometry(0.3, 24, 18),
    hair: new THREE.SphereGeometry(0.31, 24, 12, 0, Math.PI * 2, 0, Math.PI * 0.42),
    eye: new THREE.SphereGeometry(0.048, 10, 8),
    blush: new THREE.CircleGeometry(0.05, 12),
    body: new THREE.CapsuleGeometry(0.2, 0.2, 6, 16),
    coat: new THREE.CylinderGeometry(0.2, 0.27, 0.34, 16, 1, true),
    limb: new THREE.CapsuleGeometry(0.068, 0.17, 4, 8),
    hand: new THREE.SphereGeometry(0.07, 10, 8),
    shoe: new THREE.BoxGeometry(0.13, 0.08, 0.2),
    hardhat: new THREE.SphereGeometry(0.33, 20, 10, 0, Math.PI * 2, 0, Math.PI * 0.5),
    brim: new THREE.CylinderGeometry(0.4, 0.4, 0.03, 20),
    capBrim: new THREE.BoxGeometry(0.26, 0.03, 0.2),
    goggle: new THREE.TorusGeometry(0.075, 0.025, 8, 16),
    band: new THREE.TorusGeometry(0.305, 0.04, 8, 24),
    headset: new THREE.TorusGeometry(0.31, 0.025, 8, 24, Math.PI),
    mic: new THREE.SphereGeometry(0.045, 8, 6),
    clipboard: new THREE.BoxGeometry(0.2, 0.26, 0.025),
    tablet: new THREE.BoxGeometry(0.26, 0.18, 0.025),
    hammerHead: new THREE.BoxGeometry(0.18, 0.09, 0.09),
    handle: new THREE.CylinderGeometry(0.022, 0.022, 0.3, 6),
    wrench: new THREE.TorusGeometry(0.06, 0.022, 6, 10, Math.PI * 1.5),
    antenna: new THREE.CylinderGeometry(0.014, 0.014, 0.26, 6),
    shadow: new THREE.CircleGeometry(0.34, 20),
  };
  private mats = new Map<string, THREE.Material>();

  mat(color: string, opts: { emissive?: string; ei?: number; rough?: number } = {}): THREE.Material {
    const key = `${color}|${opts.emissive ?? ''}|${opts.ei ?? 0}|${opts.rough ?? 0.7}`;
    let m = this.mats.get(key);
    if (!m) {
      m = new THREE.MeshStandardMaterial({
        color, roughness: opts.rough ?? 0.7, metalness: 0.05,
        emissive: opts.emissive ?? '#000000', emissiveIntensity: opts.ei ?? 0,
      });
      this.mats.set(key, m);
    }
    return m;
  }

  readonly skinMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.62, metalness: 0.05 });
  readonly shadowMat = new THREE.MeshBasicMaterial({ color: '#000000', transparent: true, opacity: 0.28, depthWrite: false });
}

function mesh(g: THREE.BufferGeometry, m: THREE.Material, cast = true): THREE.Mesh {
  const o = new THREE.Mesh(g, m);
  o.castShadow = cast;
  return o;
}

let seq = 0;

export class Worker {
  readonly id = seq++;
  readonly role: Role;
  readonly name: string;
  readonly home: string;
  readonly group = new THREE.Group();
  private rig = new THREE.Group();
  private head = new THREE.Group();
  private legL = new THREE.Group();
  private legR = new THREE.Group();
  private armL = new THREE.Group();
  private armR = new THREE.Group();
  private toolObj: THREE.Object3D | null = null;
  readonly holdFront = new THREE.Group();
  readonly holdOver = new THREE.Group();

  x = 0;
  z = 0;
  heading = 0;
  private headingTarget = 0;
  private at: string | null;
  private path: NavNode[] = [];
  private pathI = 0;
  private running = false;
  private lane: number;

  private steps: Step[] = [];
  private cur: Step | null = null;
  private stepT = 0;
  private anim: Anim = 'idle';
  private phase = Math.random() * 10;
  private beatPhase = 0;
  private wanderT = 4 + Math.random() * 8;
  carrying: THREE.Object3D | null = null;
  carryOver = false;
  quietUntil = 0;
  wander: string[];
  tag: { label: string; color: string } | null = null;
  private heldBy: { x: number; z: number } | null = null;
  private style: RoleStyle;

  constructor(
    kit: CrewKit, role: Role, name: string, home: string, wander: string[], nav: NavGraph,
    style?: Partial<RoleStyle>,
  ) {
    this.role = role;
    this.name = name;
    this.home = home;
    this.wander = wander;
    this.lane = (this.id % 2 === 0 ? 1 : -1) * (0.16 + (this.id % 3) * 0.06);
    const s = { ...ROLE_STYLE[role], ...style };
    this.style = s;
    const skin = SKIN[(this.id * 7 + 3) % SKIN.length];
    const hair = HAIR[(this.id * 5 + 1) % HAIR.length];
    const g = kit.g;

    const shadow = new THREE.Mesh(g.shadow, kit.shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = 0.012;
    shadow.renderOrder = 1;
    this.group.add(shadow, this.rig);

    for (const [leg, sx] of [[this.legL, -0.1], [this.legR, 0.1]] as const) {
      leg.position.set(sx, 0.36, 0);
      const l = mesh(g.limb, kit.mat(s.trim));
      l.position.y = -0.15;
      const shoe = mesh(g.shoe, kit.mat('#26232f'));
      shoe.position.set(0, -0.3, 0.03);
      leg.add(l, shoe);
      this.rig.add(leg);
    }
    const body = mesh(g.body, kit.mat(s.suit));
    body.position.y = 0.58;
    this.rig.add(body);
    if (s.coat) {
      const coat = mesh(g.coat, kit.mat('#FFFFFF'));
      coat.position.y = 0.44;
      this.rig.add(coat);
    }
    const belt = mesh(g.band, kit.mat(s.trim));
    belt.scale.set(0.68, 0.68, 0.68);
    belt.rotation.x = Math.PI / 2;
    belt.position.y = 0.52;
    this.rig.add(belt);

    for (const [arm, sx] of [[this.armL, -0.25], [this.armR, 0.25]] as const) {
      arm.position.set(sx, 0.76, 0);
      const a = mesh(g.limb, kit.mat(s.suit));
      a.position.y = -0.13;
      const hand = mesh(g.hand, kit.mat(skin));
      hand.position.y = -0.27;
      arm.add(a, hand);
      this.rig.add(arm);
    }

    this.head.position.y = 1.1;
    const h = mesh(g.head, kit.mat(skin, { rough: 0.6 }));
    this.head.add(h);
    const hairM = mesh(g.hair, kit.mat(hair));
    hairM.rotation.x = -0.35;
    hairM.position.z = -0.02;
    if (s.hat !== 'hardhat' && s.hat !== 'helmet') this.head.add(hairM);
    for (const sx of [-0.105, 0.105]) {
      const eye = mesh(g.eye, kit.mat('#141018', { rough: 0.3 }), false);
      eye.position.set(sx, 0.0, 0.272);
      eye.scale.set(1, 1.3, 0.6);
      const bl = new THREE.Mesh(g.blush, kit.mat('#FF8FA3'));
      bl.position.set(sx * 1.75, -0.08, 0.255);
      bl.rotation.y = sx > 0 ? 0.55 : -0.55;
      this.head.add(eye, bl);
    }
    this.addHat(kit, s);
    this.rig.add(this.head);

    this.holdFront.position.set(0, 0.7, 0.36);
    this.holdOver.position.set(0, 1.62, 0.05);
    this.rig.add(this.holdFront, this.holdOver);
    this.addTool(kit, s);

    for (const p of [this.legL, this.legR, this.armL, this.armR]) bakePart(p, kit.skinMat, false);
    const cast = role !== 'agent';
    bakePart(this.rig, kit.skinMat, cast);
    bakePart(this.head, kit.skinMat, cast);
    if (!cast) this.rig.traverse((o) => { o.castShadow = false; });

    const start = nav.get(home);
    this.x = start.x;
    this.z = start.z;
    this.at = home;
    this.heading = this.headingTarget = start.face ?? 0;
    this.group.position.set(this.x, 0, this.z);
  }

  private addHat(kit: CrewKit, s: RoleStyle): void {
    const g = kit.g;
    switch (s.hat) {
      case 'hardhat': {
        const hat = mesh(g.hardhat, kit.mat('#F59E0B', { rough: 0.4 }));
        hat.position.y = 0.04;
        const brim = mesh(g.brim, kit.mat('#F59E0B', { rough: 0.4 }));
        brim.position.y = 0.05;
        brim.scale.set(1, 1, 0.9);
        this.head.add(hat, brim);
        break;
      }
      case 'helmet': {
        const hat = mesh(g.hardhat, kit.mat('#F8FAFC', { rough: 0.3 }));
        hat.position.y = 0.02;
        hat.scale.setScalar(1.04);
        const light = mesh(g.mic, kit.mat('#EF4444', { emissive: '#EF4444', ei: 2.2 }), false);
        light.position.set(0, 0.36, 0);
        light.scale.setScalar(1.3);
        this.head.add(hat, light);
        break;
      }
      case 'cap': {
        const hat = mesh(g.hardhat, kit.mat('#15803D'));
        hat.position.y = 0.05;
        hat.scale.set(1, 0.8, 1);
        const brim = mesh(g.capBrim, kit.mat('#15803D'));
        brim.position.set(0, 0.07, 0.3);
        this.head.add(hat, brim);
        break;
      }
      case 'goggles': {
        for (const sx of [-0.1, 0.1]) {
          const gg = mesh(g.goggle, kit.mat('#A855F7', { emissive: '#A855F7', ei: 0.6 }), false);
          gg.position.set(sx, 0.2, 0.22);
          gg.rotation.x = -0.6;
          this.head.add(gg);
        }
        break;
      }
      case 'bandana': {
        const b = mesh(g.band, kit.mat('#DC2626'));
        b.rotation.x = Math.PI / 2 - 0.25;
        b.position.y = 0.1;
        this.head.add(b);
        break;
      }
      case 'headset': {
        const hs = mesh(g.headset, kit.mat('#1F1B2E'), false);
        hs.rotation.z = 0;
        hs.position.y = 0.02;
        const mic = mesh(g.mic, kit.mat('#EC4899', { emissive: '#EC4899', ei: 1.5 }), false);
        mic.position.set(0.2, -0.16, 0.2);
        this.head.add(hs, mic);
        break;
      }
      case 'antenna': {
        const stalk = mesh(g.antenna, kit.mat('#CBD5E1', { rough: 0.35 }), false);
        stalk.position.set(0, 0.42, 0);
        const tip = mesh(g.mic, kit.mat(s.suit, { emissive: s.suit, ei: 2.4 }), false);
        tip.position.set(0, 0.57, 0);
        tip.scale.setScalar(1.35);
        this.head.add(stalk, tip);
        break;
      }
      case 'glasses': {
        for (const sx of [-0.105, 0.105]) {
          const gl = mesh(g.goggle, kit.mat('#0F172A'), false);
          gl.position.set(sx, 0.0, 0.285);
          gl.scale.setScalar(0.85);
          this.head.add(gl);
        }
        break;
      }
      default: break;
    }
  }

  private addTool(kit: CrewKit, s: RoleStyle): void {
    const g = kit.g;
    let t: THREE.Object3D | null = null;
    switch (s.tool) {
      case 'clipboard': {
        const cb = new THREE.Group();
        const b = mesh(g.clipboard, kit.mat('#B45309'));
        const p = mesh(g.clipboard, kit.mat('#FFFFFF'));
        p.scale.set(0.82, 0.8, 0.5);
        p.position.z = 0.014;
        cb.add(b, p);
        cb.rotation.x = -0.5;
        t = cb;
        break;
      }
      case 'tablet': {
        const tb = mesh(g.tablet, kit.mat('#0F172A', { emissive: '#2DD4BF', ei: 0.5 }));
        tb.rotation.x = -0.9;
        t = tb;
        break;
      }
      case 'hammer': {
        const hm = new THREE.Group();
        const hd = mesh(g.handle, kit.mat('#7C4A23'));
        const head = mesh(g.hammerHead, kit.mat('#6B7280', { rough: 0.35 }));
        head.position.y = 0.15;
        hm.add(hd, head);
        hm.rotation.x = Math.PI / 2;
        t = hm;
        break;
      }
      case 'wrench': {
        const w = new THREE.Group();
        const hd = mesh(g.handle, kit.mat('#9CA3AF', { rough: 0.35 }));
        const jaw = mesh(g.wrench, kit.mat('#9CA3AF', { rough: 0.35 }));
        jaw.position.y = 0.17;
        w.add(hd, jaw);
        w.rotation.x = Math.PI / 2;
        t = w;
        break;
      }
      default: break;
    }
    if (!t) return;
    t.position.set(0, -0.3, 0.08);
    this.armR.add(t);
    this.toolObj = t;
  }


  get busy(): boolean {
    return this.cur !== null || this.steps.length > 0;
  }

  get free(): boolean {
    return !this.busy || this.idleJob;
  }
  private idleJob = false;

  assign(steps: Step[]): void {
    if (this.idleJob) {
      this.steps = [];
      this.cur = null;
      this.idleJob = false;
      this.snapToGraph();
    }
    this.steps.push(...steps);
  }

  private snapToGraph(): void {
    if (this.path.length && this.pathI < this.path.length) this.at = null;
  }

  dispose(kit: CrewKit): void {
    const shared = new Set<THREE.BufferGeometry>(Object.values(kit.g));
    this.drop()?.removeFromParent();
    this.group.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh && m.geometry && !shared.has(m.geometry)) m.geometry.dispose();
    });
    this.group.removeFromParent();
  }

  headWorld(out: THREE.Vector3): THREE.Vector3 {
    return out.set(this.group.position.x, this.group.position.y + 1.55, this.group.position.z);
  }

  pickUp(obj: THREE.Object3D, over = false): void {
    this.drop();
    this.carrying = obj;
    this.carryOver = over;
    (over ? this.holdOver : this.holdFront).add(obj);
    obj.position.set(0, 0, 0);
    obj.rotation.set(0, 0, 0);
    if (this.toolObj) this.toolObj.visible = false;
  }

  drop(): THREE.Object3D | null {
    const o = this.carrying;
    if (!o) return null;
    this.carrying = null;
    const wp = new THREE.Vector3();
    o.getWorldPosition(wp);
    o.removeFromParent();
    o.position.copy(wp);
    if (this.toolObj) this.toolObj.visible = true;
    return o;
  }


  hold(at: { x: number; z: number } | null): void {
    this.heldBy = at;
  }

  update(dt: number, nav: NavGraph): void {
    if (this.heldBy) {
      this.anim = 'idle';
      this.headingTarget = Math.atan2(this.heldBy.x - this.x, this.heldBy.z - this.z);
      let dh = this.headingTarget - this.heading;
      dh = Math.atan2(Math.sin(dh), Math.cos(dh));
      this.heading += dh * Math.min(1, dt * 8);
      this.pose(dt, false);
      return;
    }
    this.stepT += dt;
    if (!this.cur) this.nextStep(nav);
    const c = this.cur;
    let moving = false;
    if (c) {
      switch (c.k) {
        case 'go':
          moving = this.walk(dt);
          if (!moving) this.finishStep();
          break;
        case 'work':
          this.anim = c.anim;
          if (c.onBeat) {
            const period = c.anim === 'hammer' ? 0.42 : 0.5;
            const before = Math.floor(this.beatPhase / period);
            this.beatPhase += dt;
            if (Math.floor(this.beatPhase / period) > before) c.onBeat();
          }
          if (this.stepT >= c.dur) this.finishStep();
          break;
        case 'waitFor':
          this.anim = c.anim ?? 'idle';
          if (c.cond() || this.stepT >= c.max) this.finishStep();
          break;
        case 'do':
          this.finishStep();
          break;
      }
    } else {
      this.anim = this.at === this.home ? this.style.homeAnim : 'idle';
      this.wanderT -= dt;
      if (this.wanderT <= 0) {
        this.wanderT = 7 + Math.random() * 10;
        this.idleWander();
      }
    }

    let dh = this.headingTarget - this.heading;
    dh = Math.atan2(Math.sin(dh), Math.cos(dh));
    this.heading += dh * Math.min(1, dt * 10);
    this.pose(dt, moving);
  }

  private idleWander(): void {
    if (!this.wander.length) return;
    const atHome = this.at === this.home;
    const dest = atHome ? this.wander[Math.floor(Math.random() * this.wander.length)] : this.home;
    if (dest === this.at) return;
    this.steps.push({ k: 'go', to: dest }, { k: 'work', anim: 'look', dur: 1.5 + Math.random() * 2 });
    this.idleJob = true;
  }

  private nextStep(nav: NavGraph): void {
    while (!this.cur) {
      const s = this.steps.shift();
      if (!s) {
        this.idleJob = false;
        if (this.at !== this.home) {
          this.steps.push({ k: 'go', to: this.home });
          this.idleJob = true;
          continue;
        }
        return;
      }
      this.stepT = 0;
      this.beatPhase = 0;
      if (s.k === 'do') {
        s.fn(this);
        continue;
      }
      this.cur = s;
      if (s.k === 'go') this.plan(s.to, !!s.run, nav);
    }
  }

  private finishStep(): void {
    this.cur = null;
    this.stepT = 0;
  }

  private plan(to: string, run: boolean, nav: NavGraph): void {
    this.running = run;
    const from = this.at ?? nav.nearest(this.x, this.z).id;
    this.path = nav.path(from, to);
    this.pathI = 0;
    while (this.pathI < this.path.length - 1) {
      const p = this.path[this.pathI];
      if (Math.hypot(p.x - this.x, p.z - this.z) > 0.05) break;
      this.pathI++;
    }
    this.at = null;
  }

  private walk(dt: number): boolean {
    if (this.pathI >= this.path.length) return false;
    const speed = this.style.speed * (this.running ? 1.9 : 1);
    let budget = speed * dt;
    while (budget > 0 && this.pathI < this.path.length) {
      const t = this.path[this.pathI];
      const dx = t.x - this.x;
      const dz = t.z - this.z;
      const d = Math.hypot(dx, dz);
      if (d > 1e-4) this.headingTarget = Math.atan2(dx, dz);
      if (d <= budget) {
        this.x = t.x;
        this.z = t.z;
        budget -= d;
        this.pathI++;
        if (this.pathI >= this.path.length) {
          this.at = t.id;
          if (t.face !== undefined) this.headingTarget = t.face;
          return false;
        }
      } else {
        this.x += (dx / d) * budget;
        this.z += (dz / d) * budget;
        budget = 0;
      }
    }
    return true;
  }

  private pose(dt: number, moving: boolean): void {
    const run = this.running && moving;
    const carryingFront = !!this.carrying && !this.carryOver;
    const carryingOver = !!this.carrying && this.carryOver;
    this.phase += dt * (moving ? (run ? 15 : 10) : 1);
    const ph = this.phase;

    let ox = 0, oz = 0;
    if (moving && this.pathI < this.path.length) {
      const end = this.path[this.path.length - 1];
      const dEnd = Math.hypot(end.x - this.x, end.z - this.z);
      const k = Math.min(1, dEnd / 0.9) * this.lane;
      ox = Math.cos(this.heading) * k;
      oz = -Math.sin(this.heading) * k;
    }
    this.group.position.set(this.x + ox, 0, this.z + oz);
    this.group.rotation.y = this.heading;

    let legSwing = 0, armL = 0, armR = 0, bob = 0, lean = 0, headX = 0, headY = 0, jump = 0;
    let armLz = 0, armRz = 0;
    if (moving) {
      const amp = run ? 0.95 : 0.65;
      legSwing = Math.sin(ph) * amp;
      armL = -Math.sin(ph) * amp * 0.9;
      armR = Math.sin(ph) * amp * 0.9;
      bob = Math.abs(Math.sin(ph)) * (run ? 0.09 : 0.055);
      lean = run ? 0.18 : 0.06;
    } else {
      bob = Math.sin(ph * 2.2) * 0.012;
      switch (this.anim) {
        case 'type':
          armL = -1.15 + Math.sin(ph * 22) * 0.12;
          armR = -1.15 + Math.sin(ph * 22 + 1.7) * 0.12;
          headX = 0.12 + Math.sin(ph * 3) * 0.04;
          this.phase += dt * 1.5;
          break;
        case 'hammer': {
          const p = (this.beatPhase % 0.42) / 0.42;
          armR = p < 0.3 ? -2.7 + (p / 0.3) * 2.3 : -0.4 - ((p - 0.3) / 0.7) * 2.3;
          armL = -0.9;
          lean = p < 0.3 ? 0.12 : 0.02;
          headX = 0.25;
          break;
        }
        case 'look':
          headX = -0.22 + Math.sin(ph * 0.9) * 0.05;
          headY = Math.sin(ph * 0.6) * 0.35;
          armR = -0.9;
          break;
        case 'wrench':
          armR = -1.3 + Math.sin(ph * 9) * 0.25;
          armRz = Math.sin(ph * 9) * 0.3;
          armL = -0.4;
          headX = 0.15;
          this.phase += dt * 1.5;
          break;
        case 'grab':
          armL = -1.0;
          armR = -1.0;
          lean = 0.25;
          headX = 0.3;
          break;
        case 'cheer':
          jump = Math.abs(Math.sin(ph * 7)) * 0.32;
          armL = -2.8 + Math.sin(ph * 14) * 0.25;
          armR = -2.8 - Math.sin(ph * 14) * 0.25;
          armLz = -0.3;
          armRz = 0.3;
          this.phase += dt * 1.5;
          break;
        case 'panic':
          jump = Math.abs(Math.sin(ph * 9)) * 0.12;
          armL = -2.6 + Math.sin(ph * 18) * 0.5;
          armR = -2.6 - Math.sin(ph * 18) * 0.5;
          this.phase += dt * 2;
          break;
        default:
          headY = Math.sin(ph * 0.35) * 0.4;
          armL = Math.sin(ph * 1.1) * 0.05;
          armR = -Math.sin(ph * 1.1) * 0.05;
      }
    }
    if (this.anim === 'panic' && moving) {
      armL = -2.6 + Math.sin(ph * 2) * 0.5;
      armR = -2.6 - Math.sin(ph * 2) * 0.5;
    }
    if (carryingFront) { armL = -1.25; armR = -1.25; armLz = 0.25; armRz = -0.25; }
    if (carryingOver) { armL = -2.95; armR = -2.95; armLz = 0.18; armRz = -0.18; }

    this.rig.position.y = bob + jump;
    this.rig.rotation.x = lean;
    this.legL.rotation.x = legSwing;
    this.legR.rotation.x = -legSwing;
    this.armL.rotation.x = armL;
    this.armR.rotation.x = armR;
    this.armL.rotation.z = armLz;
    this.armR.rotation.z = armRz;
    this.head.rotation.x = headX;
    this.head.rotation.y = headY;
    if (this.carrying) {
      this.carrying.rotation.y += dt * 1.2;
      this.carrying.position.y = Math.sin(ph * 0.5) * 0.02;
    }
  }
}
