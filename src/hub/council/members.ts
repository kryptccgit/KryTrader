import * as THREE from 'three';
import type { MemberId } from './roster';
import { PERSONAS } from './roster';


export type Pose =
  | 'idle' | 'talk' | 'vote' | 'bang' | 'cower' | 'nod' | 'gloat' | 'cheer' | 'wild' | 'whistle' | 'tabletop';

const M = new Map<string, THREE.MeshStandardMaterial>();
function mat(color: string, o: { e?: string; ei?: number; rough?: number; metal?: number } = {}): THREE.MeshStandardMaterial {
  const key = `${color}|${o.e ?? ''}|${o.ei ?? 0}|${o.rough ?? 0.55}|${o.metal ?? 0.05}`;
  let m = M.get(key);
  if (!m) {
    m = new THREE.MeshStandardMaterial({ color, emissive: o.e ?? '#000000', emissiveIntensity: o.ei ?? 0, roughness: o.rough ?? 0.55, metalness: o.metal ?? 0.05 });
    M.set(key, m);
  }
  return m;
}

export function disposeMemberMaterials(): void {
  M.forEach((m) => m.dispose());
  M.clear();
}

function mesh(g: THREE.BufferGeometry, m: THREE.Material, x = 0, y = 0, z = 0, cast = true): THREE.Mesh {
  const o = new THREE.Mesh(g, m);
  o.position.set(x, y, z);
  o.castShadow = cast;
  return o;
}

function stripeTexture(a: string, b: string): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 64; c.height = 64;
  const g = c.getContext('2d')!;
  g.fillStyle = a; g.fillRect(0, 0, 64, 64);
  g.fillStyle = b;
  for (let x = 0; x < 64; x += 16) g.fillRect(x, 0, 8, 64);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(3, 1);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

interface Rig {
  headY: number;
  shoulderY: number;
  shoulderX: number;
  armLen: number;
  eyeR: number;
  eyeSpread: number;
  eyeZ: number;
  armColor: string;
}

export class Member {
  readonly id: MemberId;
  readonly group = new THREE.Group();
  readonly body = new THREE.Group();
  readonly head = new THREE.Group();
  readonly armL = new THREE.Group();
  readonly armR = new THREE.Group();
  readonly handR = new THREE.Object3D();
  private eyes: THREE.Group[] = [];
  private pupils: THREE.Mesh[] = [];
  private browL: THREE.Mesh;
  private browR: THREE.Mesh;
  private mouthO: THREE.Mesh;
  private mouthLine: THREE.Mesh;
  private lids: THREE.Mesh[] = [];
  readonly rig: Rig;
  readonly seat = new THREE.Vector3();
  readonly facing: number;
  pose: Pose = 'idle';
  poseT = 0;
  private blinkT = 2 + Math.random() * 3;
  private blink = 0;
  private phase = Math.random() * 10;
  readonly lookAt = new THREE.Vector3();
  talking = 0;
  private tex: THREE.Texture[] = [];
  private tableT = 0;

  constructor(id: MemberId, seatX: number, seatZ: number) {
    this.id = id;
    const color = PERSONAS[id].color;
    this.seat.set(seatX, 0, seatZ);
    this.facing = Math.atan2(-seatX, 3.2 - seatZ);
    this.group.position.copy(this.seat);
    this.group.rotation.y = this.facing;
    this.group.add(this.body);
    const dark = '#1b1410';

    let rig: Rig;
    switch (id) {
      case 'greed': {
        const b = mesh(new THREE.SphereGeometry(0.52, 32, 24), mat(color, { rough: 0.55, metal: 0.12 }), 0, 1.22, 0);
        b.scale.set(1.35, 1.0, 1.1);
        const hat = mesh(new THREE.CylinderGeometry(0.26, 0.26, 0.42, 20), mat('#151515', { rough: 0.4 }), 0, 1.92, -0.04);
        const brim = mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.04, 24), mat('#151515', { rough: 0.4 }), 0, 1.71, -0.04);
        const band = mesh(new THREE.CylinderGeometry(0.265, 0.265, 0.08, 20), mat('#B45309'), 0, 1.78, -0.04);
        const chain = mesh(new THREE.TorusGeometry(0.42, 0.025, 6, 24, Math.PI), mat('#FDE68A', { metal: 0.8, rough: 0.25, e: '#B45309', ei: 0.2 }), 0, 1.05, 0.3);
        chain.rotation.z = Math.PI;
        const coin = mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.03, 18), mat('#FDE68A', { metal: 0.8, rough: 0.25, e: '#B45309', ei: 0.3 }), 0, 0.68, 0.5);
        coin.rotation.x = Math.PI / 2;
        this.body.add(b, hat, brim, band, chain, coin);
        rig = { headY: 1.42, shoulderY: 1.25, shoulderX: 0.66, armLen: 0.42, eyeR: 0.11, eyeSpread: 0.17, eyeZ: 0.5, armColor: color };
        break;
      }
      case 'panic': {
        const b = mesh(new THREE.CapsuleGeometry(0.24, 0.62, 8, 16), mat(color), 0, 1.22, 0);
        const h = mesh(new THREE.SphereGeometry(0.38, 28, 20), mat(color), 0, 2.02, 0);
        h.scale.set(1, 1.12, 0.95);
        this.head.add(h);
        for (let i = -2; i <= 2; i++) {
          const tuft = mesh(new THREE.ConeGeometry(0.06, 0.32, 8), mat('#DBEAFE'), i * 0.09, 2.5, -0.02);
          tuft.rotation.z = -i * 0.28;
          this.head.add(tuft);
        }
        this.body.add(b);
        rig = { headY: 2.06, shoulderY: 1.52, shoulderX: 0.3, armLen: 0.48, eyeR: 0.13, eyeSpread: 0.15, eyeZ: 0.34, armColor: color };
        break;
      }
      case 'quant': {
        const b = mesh(new THREE.BoxGeometry(0.62, 0.72, 0.46), mat(color), 0, 1.2, 0);
        const tie = mesh(new THREE.BoxGeometry(0.1, 0.42, 0.02), mat('#14532D'), 0, 1.25, 0.24);
        const h = mesh(new THREE.BoxGeometry(0.56, 0.52, 0.5), mat(color), 0, 1.86, 0);
        const hair = mesh(new THREE.BoxGeometry(0.58, 0.12, 0.52), mat('#2F3B33'), 0, 2.15, 0);
        this.head.add(h, hair);
        for (const sx of [-0.13, 0.13]) {
          const frame = mesh(new THREE.TorusGeometry(0.1, 0.022, 4, 4), mat('#111827'), sx, 1.88, 0.27, false);
          frame.rotation.z = Math.PI / 4;
          this.head.add(frame);
        }
        this.head.add(mesh(new THREE.BoxGeometry(0.08, 0.02, 0.02), mat('#111827'), 0, 1.88, 0.27, false));
        this.body.add(b, tie);
        rig = { headY: 1.88, shoulderY: 1.48, shoulderX: 0.37, armLen: 0.42, eyeR: 0.07, eyeSpread: 0.13, eyeZ: 0.25, armColor: color };
        break;
      }
      case 'fomo': {
        const b = mesh(new THREE.SphereGeometry(0.36, 24, 18), mat(color), 0, 1.12, 0);
        const h = mesh(new THREE.SphereGeometry(0.4, 28, 20), mat(color), 0, 1.72, 0);
        this.head.add(h);
        for (let i = 0; i < 9; i++) {
          const a = (i / 9) * Math.PI * 2;
          const spike = mesh(new THREE.ConeGeometry(0.09, 0.36, 8), mat('#FFB3D6'), Math.cos(a) * 0.4, 1.74 + Math.sin(a) * 0.4, -0.08);
          spike.rotation.z = a - Math.PI / 2;
          if (Math.sin(a) > -0.4) this.head.add(spike);
        }
        this.body.add(b);
        rig = { headY: 1.74, shoulderY: 1.25, shoulderX: 0.34, armLen: 0.36, eyeR: 0.11, eyeSpread: 0.15, eyeZ: 0.36, armColor: color };
        break;
      }
      case 'doubt': {
        const b = mesh(new THREE.SphereGeometry(0.5, 28, 20), mat(color, { rough: 0.8 }), 0, 1.22, 0);
        b.scale.set(1, 1.28, 0.95);
        const tuft = mesh(new THREE.SphereGeometry(0.16, 12, 10), mat('#6B6B76', { rough: 0.9 }), 0.1, 1.86, 0);
        tuft.scale.set(1.4, 0.5, 1);
        this.body.add(b, tuft);
        rig = { headY: 1.55, shoulderY: 1.2, shoulderX: 0.48, armLen: 0.4, eyeR: 0.1, eyeSpread: 0.15, eyeZ: 0.44, armColor: color };
        break;
      }
      case 'risk':
      default: {
        const stripes = stripeTexture('#F5F5F5', '#18181B');
        this.tex.push(stripes);
        const b = mesh(new THREE.CylinderGeometry(0.5, 0.3, 0.8, 20), new THREE.MeshStandardMaterial({ map: stripes, roughness: 0.7 }), 0, 1.18, 0);
        const h = mesh(new THREE.SphereGeometry(0.33, 24, 18), mat(color), 0, 1.86, 0);
        const cap = mesh(new THREE.SphereGeometry(0.345, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), mat('#18181B'), 0, 1.9, 0);
        const brim = mesh(new THREE.BoxGeometry(0.34, 0.03, 0.26), mat('#18181B'), 0, 1.93, 0.36);
        this.head.add(h, cap, brim);
        const whistle = mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.14, 10), mat('#D4D4D8', { metal: 0.9, rough: 0.2 }), 0.08, 1.45, 0.42);
        whistle.rotation.z = Math.PI / 2;
        const cord = mesh(new THREE.TorusGeometry(0.22, 0.012, 4, 20, Math.PI), mat('#E5383B'), 0, 1.6, 0.25, false);
        cord.rotation.z = Math.PI;
        this.body.add(b, whistle, cord);
        rig = { headY: 1.86, shoulderY: 1.5, shoulderX: 0.52, armLen: 0.42, eyeR: 0.085, eyeSpread: 0.12, eyeZ: 0.3, armColor: color };
        break;
      }
    }
    this.rig = rig;
    this.body.add(this.head);

    for (const sx of [-rig.eyeSpread, rig.eyeSpread]) {
      const eye = new THREE.Group();
      eye.position.set(sx, rig.headY, rig.eyeZ);
      const white = mesh(new THREE.SphereGeometry(rig.eyeR, 16, 12), mat('#FFFFFF', { rough: 0.25 }), 0, 0, 0, false);
      const pupil = mesh(new THREE.SphereGeometry(rig.eyeR * 0.5, 12, 10), mat('#0B0B0F', { rough: 0.2 }), 0, 0, rig.eyeR * 0.7, false);
      eye.add(white, pupil);
      this.eyes.push(eye);
      this.pupils.push(pupil);
      this.head.add(eye);
      if (id === 'doubt' || id === 'quant') {
        const lid = mesh(new THREE.SphereGeometry(rig.eyeR * 1.08, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.5), mat(id === 'doubt' ? '#7C7C88' : PERSONAS[id].color), 0, 0, 0, false);
        lid.rotation.x = 0.55;
        eye.add(lid);
        this.lids.push(lid);
      }
    }
    const browG = new THREE.BoxGeometry(rig.eyeR * 2.2, 0.035, 0.04);
    this.browL = mesh(browG, mat(dark), -rig.eyeSpread, rig.headY + rig.eyeR * 1.5, rig.eyeZ + 0.02, false);
    this.browR = mesh(browG, mat(dark), rig.eyeSpread, rig.headY + rig.eyeR * 1.5, rig.eyeZ + 0.02, false);
    this.mouthO = mesh(new THREE.SphereGeometry(0.075, 14, 10), mat('#3B0A0A', { rough: 0.4 }), 0, rig.headY - rig.eyeR * 2.1, rig.eyeZ - 0.01, false);
    this.mouthO.scale.set(1.3, 0.5, 0.4);
    this.mouthLine = mesh(new THREE.TorusGeometry(0.085, 0.018, 6, 16, Math.PI), mat('#3B0A0A'), 0, rig.headY - rig.eyeR * 1.7, rig.eyeZ, false);
    this.mouthLine.rotation.z = Math.PI;
    this.head.add(this.browL, this.browR, this.mouthO, this.mouthLine);

    const armG = new THREE.CapsuleGeometry(0.075, rig.armLen, 4, 8);
    for (const [arm, sx] of [[this.armL, -rig.shoulderX], [this.armR, rig.shoulderX]] as const) {
      arm.position.set(sx, rig.shoulderY, 0.05);
      const a = mesh(armG, mat(rig.armColor), 0, -rig.armLen / 2 - 0.04, 0);
      const hand = mesh(new THREE.SphereGeometry(0.1, 12, 10), mat(id === 'risk' ? '#E5383B' : rig.armColor), 0, -rig.armLen - 0.1, 0);
      arm.add(a, hand);
      this.body.add(arm);
    }
    this.handR.position.set(0, -rig.armLen - 0.1, 0);
    this.armR.add(this.handR);

    if (id === 'quant') {
      const cb = new THREE.Group();
      cb.add(mesh(new THREE.BoxGeometry(0.28, 0.36, 0.03), mat('#92400E')), mesh(new THREE.BoxGeometry(0.23, 0.28, 0.01), mat('#FAFAF9'), 0, -0.02, 0.02));
      cb.position.set(0, -rig.armLen - 0.15, 0.1);
      cb.rotation.x = -1.0;
      this.armL.add(cb);
    } else if (id === 'fomo') {
      const phone = mesh(new THREE.BoxGeometry(0.14, 0.26, 0.03), mat('#111827', { e: '#FF7AC0', ei: 0.9 }), 0, -rig.armLen - 0.16, 0.06);
      phone.rotation.x = -0.6;
      this.armL.add(phone);
    }
  }

  bubbleAnchor(out: THREE.Vector3): THREE.Vector3 {
    const topY = this.id === 'greed' ? 2.25 : this.id === 'panic' ? 2.7 : this.id === 'fomo' ? 2.25 : this.id === 'doubt' ? 2.0 : 2.3;
    out.set(0, topY + this.body.position.y, 0);
    return this.group.localToWorld(out);
  }

  set(pose: Pose): void {
    if (this.pose === pose) return;
    this.pose = pose;
    this.poseT = 0;
  }

  climbTable(seconds: number): void {
    this.tableT = seconds;
  }

  update(dt: number, t: number): void {
    this.poseT += dt;
    this.phase += dt;
    this.talking = Math.max(0, this.talking - dt);
    const ph = this.phase;
    const id = this.id;

    let bodyY = 0, bodyX = 0, lean = 0, tilt = 0, spin = 0;
    let aL = 0.15, aR = 0.15, aLz = 0.2, aRz = -0.2;
    let headTilt = 0, headTurn = 0;
    let browL = 0, browR = 0, browY = 0;
    let mouthOpen = 0;
    let smile = 1;

    switch (id) {
      case 'greed': bodyY = Math.sin(ph * 1.6) * 0.02; browL = 0.35; browR = -0.35; smile = 1; aL = -0.5; aR = -0.5; aLz = 0.6; aRz = -0.6; break;
      case 'panic': bodyX = Math.sin(ph * 41) * 0.015; bodyY = Math.sin(ph * 37) * 0.01; browL = -0.45; browR = 0.45; browY = 0.04; smile = -1; aL = -0.3; aR = -0.3; break;
      case 'quant': browL = 0; browR = 0; smile = 0; aL = -1.2; aLz = 0.5; aR = -0.2; headTilt = 0.08; break;
      case 'fomo': bodyY = Math.abs(Math.sin(ph * 6)) * 0.12; aL = -0.9 + Math.sin(ph * 6) * 0.2; aR = -0.4 - Math.sin(ph * 6) * 0.3; smile = 1; headTurn = Math.sin(ph * 2.2) * 0.3; break;
      case 'doubt':
        bodyY = Math.sin(ph * 0.7) * 0.025; smile = 0; browL = 0.0; browR = 0.4; browY = 0.03; headTilt = 0.12;
        aL = -1.35; aR = -1.35; aLz = -0.9; aRz = 0.9;
        break;
      case 'risk': default: aL = 0.35; aR = 0.35; aLz = 0.1; aRz = -0.1; headTurn = Math.sin(ph * 0.8) * 0.35; smile = 0; browL = 0.25; browR = -0.25; break;
    }

    const pt = this.poseT;
    switch (this.pose) {
      case 'talk':
        mouthOpen = 0.6 + Math.abs(Math.sin(t * 16)) * 0.9;
        aR = -1.4 + Math.sin(t * 7) * 0.45;
        if (id === 'greed') { aL = -1.3 + Math.sin(t * 7 + 1) * 0.4; }
        if (id === 'fomo') { aR = -2.6 + Math.sin(t * 12) * 0.4; bodyY = Math.abs(Math.sin(t * 9)) * 0.2; }
        if (id === 'panic') { aL = -2.4 + Math.sin(t * 20) * 0.3; aR = -2.4 - Math.sin(t * 20) * 0.3; bodyX = Math.sin(t * 50) * 0.03; }
        if (id === 'quant') { aR = -1.0; headTilt = 0.18; mouthOpen *= 0.5; }
        if (id === 'doubt') { mouthOpen *= 0.4; headTurn = -0.25; }
        if (id === 'risk') { aR = -2.2; aRz = -0.2; lean = 0.1; }
        lean += 0.06;
        break;
      case 'bang': {
        const c = (pt % 0.55) / 0.55;
        const v = c < 0.55 ? -2.7 + c * 0.6 : -1.0;
        aL = v; aR = v; aLz = 0.15; aRz = -0.15;
        lean = c < 0.55 ? -0.05 : 0.22;
        mouthOpen = 1.2; browL = 0.5; browR = -0.5;
        break;
      }
      case 'cower':
        bodyY = -0.55 * Math.min(1, pt * 4) + Math.sin(t * 40) * 0.02;
        aL = -2.2; aR = -2.2; aLz = -0.6; aRz = 0.6;
        mouthOpen = 1; smile = -1;
        break;
      case 'nod':
        headTilt = 0.25 + Math.sin(pt * 9) * 0.18;
        break;
      case 'gloat':
        lean = -0.2; bodyY += Math.abs(Math.sin(t * 14)) * 0.04;
        aL = -0.6; aR = -0.6; aLz = 1.1; aRz = -1.1; mouthOpen = 1.2; smile = 1;
        break;
      case 'whistle':
        aR = -2.2; aRz = 0.5; aL = -2.6; mouthOpen = 0.4; lean = 0.12;
        break;
      case 'vote':
        aR = -2.95 + Math.sin(t * 3 + this.phase) * 0.06; aRz = -0.1;
        break;
      case 'cheer':
      case 'wild': {
        bodyY = Math.abs(Math.sin(t * 9 + this.phase)) * (this.pose === 'wild' ? 0.45 : 0.25);
        aL = -2.8 + Math.sin(t * 16) * 0.3; aR = -2.8 - Math.sin(t * 16) * 0.3; aLz = 0.35; aRz = -0.35;
        mouthOpen = 1.3; smile = 1;
        if (this.pose === 'wild') spin = Math.sin(t * 3 + this.phase) * 0.6;
        if (id === 'panic') { aL = -2.6; aR = -2.6; bodyX = Math.sin(t * 50) * 0.05; smile = -1; }
        break;
      }
      default: break;
    }
    if (this.talking > 0 && this.pose === 'idle') mouthOpen = 0.5 + Math.abs(Math.sin(t * 16)) * 0.8;

    let gx = this.seat.x, gz = this.seat.z, gy = 0;
    if (this.tableT > 0) {
      this.tableT -= dt;
      const k = Math.min(1, Math.min(this.poseT * 2, this.tableT * 2));
      gx = this.seat.x * (1 - k * 0.85);
      gz = this.seat.z * (1 - k * 0.85);
      gy = k * (0.42 + Math.abs(Math.sin(t * 8)) * 0.3);
      spin = Math.sin(t * 4) * 1.2 * k;
      aL = -2.9; aR = -2.9; mouthOpen = 1.4;
    }
    this.group.position.set(gx, gy, gz);
    this.group.rotation.y = this.facing + spin;

    this.body.position.set(bodyX, bodyY, 0);
    this.body.rotation.x = lean;
    this.body.rotation.z = tilt;
    this.armL.rotation.set(aL, 0, aLz);
    this.armR.rotation.set(aR, 0, aRz);

    this.head.rotation.x = headTilt;
    const local = this.group.worldToLocal(this._v.copy(this.lookAt));
    const look = Math.atan2(local.x, Math.max(0.1, local.z));
    this.head.rotation.y = headTurn * 0.5 + THREE.MathUtils.clamp(look, -0.7, 0.7) * 0.6;

    const px = THREE.MathUtils.clamp(local.x * 0.02, -0.035, 0.035);
    for (const p of this.pupils) p.position.x = px;

    this.blinkT -= dt;
    if (this.blinkT <= 0) { this.blink = 0.14; this.blinkT = 2.5 + Math.random() * 3.5; }
    this.blink = Math.max(0, this.blink - dt);
    const eyeScaleY = this.blink > 0 ? 0.12 : id === 'panic' ? 1.15 : 1;
    for (const e of this.eyes) e.scale.set(1, eyeScaleY, 1);

    this.browL.rotation.z = browL;
    this.browR.rotation.z = browR;
    this.browL.position.y = this.browR.position.y = this.rig.headY + this.rig.eyeR * 1.5 + browY;
    const open = mouthOpen > 0.1;
    this.mouthO.visible = open;
    this.mouthLine.visible = !open;
    if (open) this.mouthO.scale.set(1.3, 0.35 + mouthOpen * 0.55, 0.4);
    this.mouthLine.rotation.z = smile >= 0 ? Math.PI : 0;
    this.mouthLine.scale.set(1, smile === 0 ? 0.15 : 1, 1);
  }
  private _v = new THREE.Vector3();

  dispose(): void {
    this.tex.forEach((t) => t.dispose());
  }
}
