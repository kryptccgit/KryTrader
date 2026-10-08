import * as THREE from 'three';
import spriteUrl from '../../assets/mossy.png';
import { mergeStatic } from '../engine/bake';
import { MEMBER_IDS, PERSONAS, type MemberId } from './roster';
import type { ScoreView } from './seats';
import type { WalkSpace } from '../walk';


export const TABLE_R = 2.35;
export const TABLE_Y = 0.95;
export const SEAT_R = 3.15;
const SEAT_DEG = [198, 227, 256, 285, 314, 343];
export const CHAIR_POS = new THREE.Vector3(Math.cos(0.42) * 3.95, 0, Math.sin(0.42) * 3.95);

const MOSSY_SCALE = 1.8;
const MOSSY_POS = CHAIR_POS.clone().multiplyScalar(1 - 0.35 / CHAIR_POS.length()).setY(1.82);

const VAULT_DOOR = [-6.35, 2.25, -7.0] as const;

export function seatOf(i: number): [number, number] {
  const a = (SEAT_DEG[i] * Math.PI) / 180;
  return [Math.cos(a) * SEAT_R, Math.sin(a) * SEAT_R];
}

export const COUNCIL_WALK: WalkSpace = {
  wallT: 0.2,
  walls: [
    [-8.8, -6.35, 8.8, -6.35],
    [-8.7, -6.35, -8.7, 8.6],
    [8.7, -6.35, 8.7, 8.6],
    [-8.8, 8.6, 8.8, 8.6],
  ],
  props: [
    [0, 0, TABLE_R + 0.1],
    ...SEAT_DEG.map((_, i): [number, number, number] => [...seatOf(i), 0.55]),
    [CHAIR_POS.x, CHAIR_POS.z, 1.25],
    [-5.6, -0.6, 1.0],
  ],
  start: { x: 0, z: 7.4, yaw: 0, pitch: -0.06 },
  eye: 1.65,
  speed: 2.4,
  exits: [[VAULT_DOOR[0] - 1.6, -6.35, VAULT_DOOR[0] + 1.6, -6.35]],
};

function canvasTex(w: number, h: number, draw: (g: CanvasRenderingContext2D) => void, repeat?: [number, number]): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  draw(c.getContext('2d')!);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  if (repeat) {
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(repeat[0], repeat[1]);
  }
  return t;
}

function concrete(base: string, seams: boolean): (g: CanvasRenderingContext2D) => void {
  return (g) => {
    const W = g.canvas.width, H = g.canvas.height;
    g.fillStyle = base;
    g.fillRect(0, 0, W, H);
    for (let i = 0; i < 2600; i++) {
      const v = Math.random();
      g.fillStyle = v < 0.5 ? `rgba(0,0,0,${0.03 + Math.random() * 0.05})` : `rgba(255,240,220,${0.02 + Math.random() * 0.04})`;
      const r = 1 + Math.random() * 7;
      g.beginPath();
      g.arc(Math.random() * W, Math.random() * H, r, 0, Math.PI * 2);
      g.fill();
    }
    if (seams) {
      g.strokeStyle = 'rgba(0,0,0,0.35)';
      g.lineWidth = 3;
      g.strokeRect(1, 1, W - 2, H - 2);
      g.fillStyle = 'rgba(0,0,0,0.45)';
      for (const [x, y] of [[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]]) {
        g.beginPath();
        g.arc(x * W, y * H, 5, 0, Math.PI * 2);
        g.fill();
      }
    }
  };
}

function riveted(g: CanvasRenderingContext2D): void {
  const W = g.canvas.width, H = g.canvas.height;
  const grd = g.createLinearGradient(0, 0, 0, H);
  grd.addColorStop(0, '#4a4d52');
  grd.addColorStop(1, '#383a3e');
  g.fillStyle = grd;
  g.fillRect(0, 0, W, H);
  g.strokeStyle = 'rgba(0,0,0,0.6)';
  g.lineWidth = 4;
  g.strokeRect(2, 2, W - 4, H - 4);
  for (let x = 14; x < W; x += 28) {
    for (const y of [12, H - 12]) {
      g.fillStyle = 'rgba(0,0,0,0.5)';
      g.beginPath(); g.arc(x + 1, y + 1, 4.5, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#7b7f86';
      g.beginPath(); g.arc(x, y, 4, 0, Math.PI * 2); g.fill();
    }
  }
  for (let i = 0; i < 400; i++) {
    g.fillStyle = `rgba(120,70,30,${Math.random() * 0.12})`;
    g.fillRect(Math.random() * W, Math.random() * H, 2 + Math.random() * 6, 1 + Math.random() * 3);
  }
}

class Screen {
  readonly tex: THREE.CanvasTexture;
  readonly g: CanvasRenderingContext2D;
  private acc = 0;
  constructor(w: number, h: number, private hz: number, private paint: (g: CanvasRenderingContext2D, w: number, h: number, t: number) => void) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    this.g = c.getContext('2d')!;
    this.tex = new THREE.CanvasTexture(c);
    this.tex.colorSpace = THREE.SRGBColorSpace;
    this.tex.anisotropy = 8;
    this.paint(this.g, w, h, 0);
  }
  update(dt: number, t: number, force = false): void {
    this.acc += dt;
    if (!force && this.acc < 1 / this.hz) return;
    this.acc = 0;
    this.paint(this.g, this.g.canvas.width, this.g.canvas.height, t);
    this.tex.needsUpdate = true;
  }
}

export interface ScoreRow { id: MemberId; right: number; n: number }

export class Bunker {
  readonly group = new THREE.Group();
  private textures: THREE.Texture[] = [];
  private own = new Set<THREE.Material>();

  private lampBulbs: THREE.MeshStandardMaterial[] = [];
  private keyLight: THREE.SpotLight;
  private sideLights: THREE.PointLight[] = [];
  private holoLight: THREE.PointLight;
  private holoRings: THREE.Object3D[] = [];
  private holoGlobe: THREE.Object3D;
  private holoBeam: THREE.MeshBasicMaterial;
  private holoRingMat: THREE.MeshStandardMaterial;
  holoPulse = 0;
  holoColor = new THREE.Color('#FFB547');
  private crts: Screen[] = [];
  private crtFeed: string[] = [];
  private score: Screen;
  private scoreView: ScoreView = { title: 'WHO CALLED IT?', caption: 'call accuracy · settled trades', lines: [] };
  private moodScreen: THREE.MeshStandardMaterial;
  private moodLever = new THREE.Group();
  private moodColor = new THREE.Color('#FFB547');
  private gavel = new THREE.Group();
  private gavelT = 99;
  private gavelHits = 0;
  private mossy: THREE.Sprite;
  private mossyTex: THREE.Texture;
  private mossyFrame = 0;
  private mossyAcc = 0;
  mossyHop = 0;
  private voteLamps: THREE.MeshStandardMaterial[] = [];
  private dust: THREE.Points;
  private vaultWheel = new THREE.Group();
  private warn: THREE.MeshStandardMaterial;
  readonly tableShake = { v: 0 };
  private tableTop = new THREE.Group();
  readonly placards: THREE.Vector3[] = [];
  readonly moodAnchor = new THREE.Vector3(-5.6, 2.2, -0.6);
  readonly holoAnchor = new THREE.Vector3(0, 2.25, 0);
  readonly scoreAnchor = new THREE.Vector3(3.4, 4.0, -6.8);
  readonly frontWall = new THREE.Group();
  private exitNear = 0;

  constructor() {
    const G = this.group;
    const std = (color: string, o: { e?: string; ei?: number; rough?: number; metal?: number; map?: THREE.Texture } = {}) =>
      new THREE.MeshStandardMaterial({
        color, map: o.map ?? null, emissive: o.e ?? '#000000', emissiveIntensity: o.ei ?? 0,
        roughness: o.rough ?? 0.85, metalness: o.metal ?? 0.05,
      });
    const own = (m: THREE.MeshStandardMaterial) => { this.own.add(m); return m; };
    const add = (geo: THREE.BufferGeometry, m: THREE.Material, x: number, y: number, z: number, cast = true, recv = true) => {
      const o = new THREE.Mesh(geo, m);
      o.position.set(x, y, z);
      o.castShadow = cast;
      o.receiveShadow = recv;
      G.add(o);
      return o;
    };

    const floorTex = canvasTex(512, 512, concrete('#5e574e', true), [6, 5]);
    const wallTex = canvasTex(512, 512, concrete('#6d665b', true), [5, 2]);
    const steelTex = canvasTex(512, 128, riveted, [6, 1]);
    this.textures.push(floorTex, wallTex, steelTex);
    const floor = add(new THREE.PlaneGeometry(24, 20), std('#ffffff', { map: floorTex }), 0, 0, -1, false);
    floor.rotation.x = -Math.PI / 2;
    const wallM = std('#ffffff', { map: wallTex, rough: 0.95 });
    const back = add(new THREE.PlaneGeometry(24, 8), wallM, 0, 4, -7.2, false);
    void back;
    for (const s of [-1, 1]) {
      const side = add(new THREE.PlaneGeometry(20, 8), wallM, s * 9, 4, -1, false);
      side.rotation.y = -s * Math.PI / 2;
    }
    const steelM = std('#ffffff', { map: steelTex, metal: 0.55, rough: 0.55 });
    add(new THREE.BoxGeometry(24, 1.3, 0.2), steelM, 0, 0.65, -7.1, false);
    for (const s of [-1, 1]) {
      const w = add(new THREE.BoxGeometry(0.2, 1.3, 20), steelM, s * 8.9, 0.65, -1, false);
      void w;
    }
    const beamM = std('#3a3c40', { metal: 0.6, rough: 0.5 });
    for (const x of [-8.65, -4.45, 6.2, 8.65]) {
      add(new THREE.BoxGeometry(0.5, 8, 0.45), beamM, x, 4, -6.95);
      add(new THREE.BoxGeometry(0.16, 8, 0.7), beamM, x, 4, -6.9);
    }
    add(new THREE.BoxGeometry(24, 0.5, 0.6), beamM, 0, 6.6, -6.9, false);
    const cableM = std('#1d1d1f', { rough: 0.6 });
    const cableR = std('#7a2a1d', { rough: 0.6 });
    for (const [y, r, m] of [[5.9, 0.09, cableM], [5.7, 0.06, cableR], [5.55, 0.07, cableM]] as const) {
      const c = add(new THREE.CylinderGeometry(r, r, 22, 8), m, 0, y, -6.95);
      c.rotation.z = Math.PI / 2;
    }
    for (const x of [-8.0, 0.55, 7.4]) {
      add(new THREE.CylinderGeometry(0.05, 0.05, 2.4, 8), cableM, x, 4.6, -6.98);
      add(new THREE.BoxGeometry(0.42, 0.55, 0.22), std('#4b4f45', { metal: 0.4, rough: 0.6 }), x, 3.3, -6.95);
    }
    const hazard = canvasTex(512, 32, (g) => {
      g.fillStyle = '#1a1712'; g.fillRect(0, 0, 512, 32);
      g.fillStyle = '#C8961E';
      for (let x = -32; x < 512; x += 32) { g.beginPath(); g.moveTo(x, 32); g.lineTo(x + 16, 0); g.lineTo(x + 32, 0); g.lineTo(x + 16, 32); g.fill(); }
    }, [8, 1]);
    this.textures.push(hazard);
    const ring = add(new THREE.RingGeometry(4.35, 4.6, 96, 1), std('#ffffff', { map: hazard, rough: 0.9 }), 0, 0.012, 0, false);
    ring.rotation.x = -Math.PI / 2;
    const rug = add(new THREE.CircleGeometry(4.2, 72), std('#3a1513', { rough: 1 }), 0, 0.01, 0, false);
    rug.rotation.x = -Math.PI / 2;
    const rugEdge = add(new THREE.RingGeometry(4.05, 4.18, 72), std('#9a7224', { rough: 0.8 }), 0, 0.011, 0, false);
    rugEdge.rotation.x = -Math.PI / 2;

    G.add(this.tableTop);
    const tAdd = (geo: THREE.BufferGeometry, m: THREE.Material, x: number, y: number, z: number) => {
      const o = new THREE.Mesh(geo, m);
      o.position.set(x, y, z);
      o.castShadow = true;
      o.receiveShadow = true;
      this.tableTop.add(o);
      return o;
    };
    tAdd(new THREE.CylinderGeometry(TABLE_R, TABLE_R, 0.14, 64), std('#2b2622', { metal: 0.5, rough: 0.45 }), 0, TABLE_Y - 0.07, 0);
    tAdd(new THREE.CylinderGeometry(TABLE_R - 0.18, TABLE_R - 0.18, 0.02, 64), std('#173327', { rough: 0.95 }), 0, TABLE_Y + 0.005, 0);
    const rim = tAdd(new THREE.TorusGeometry(TABLE_R, 0.06, 8, 72), std('#B8862B', { metal: 0.8, rough: 0.3 }), 0, TABLE_Y, 0);
    rim.rotation.x = Math.PI / 2;
    add(new THREE.CylinderGeometry(0.7, 1.1, TABLE_Y - 0.14, 24), std('#24211e', { metal: 0.4, rough: 0.6 }), 0, (TABLE_Y - 0.14) / 2, 0);
    const grid = canvasTex(512, 512, (g) => {
      g.clearRect(0, 0, 512, 512);
      g.strokeStyle = 'rgba(200,170,90,0.35)';
      g.lineWidth = 2;
      for (let i = 0; i <= 512; i += 64) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 512); g.moveTo(0, i); g.lineTo(512, i); g.stroke(); }
      g.beginPath(); g.arc(256, 256, 200, 0, Math.PI * 2); g.stroke();
      g.beginPath(); g.arc(256, 256, 120, 0, Math.PI * 2); g.stroke();
    });
    this.textures.push(grid);
    const felt = tAdd(new THREE.CircleGeometry(TABLE_R - 0.2, 64), new THREE.MeshStandardMaterial({ map: grid, transparent: true, roughness: 1, depthWrite: false }), 0, TABLE_Y + 0.02, 0);
    felt.rotation.x = -Math.PI / 2;

    for (let i = 0; i < MEMBER_IDS.length; i++) {
      const [sx, sz] = seatOf(i);
      const d = Math.hypot(sx, sz);
      const ux = sx / d, uz = sz / d;
      const lamp = own(std('#2a1d12', { e: '#000000', ei: 0, rough: 0.3 }));
      this.voteLamps.push(lamp);
      tAdd(new THREE.SphereGeometry(0.11, 14, 10, 0, Math.PI * 2, 0, Math.PI / 2), lamp, ux * (TABLE_R - 0.32), TABLE_Y + 0.02, uz * (TABLE_R - 0.32));
      const plate = tAdd(new THREE.BoxGeometry(0.62, 0.16, 0.05), std('#9a7224', { metal: 0.7, rough: 0.35 }), ux * (TABLE_R - 0.12), TABLE_Y + 0.08, uz * (TABLE_R - 0.12));
      plate.rotation.y = Math.atan2(ux, uz);
      plate.rotation.x = -0.4;
      this.placards.push(new THREE.Vector3(ux * (TABLE_R - 0.05), TABLE_Y + 0.02, uz * (TABLE_R - 0.05)));
      const color = PERSONAS[MEMBER_IDS[i]].color;
      const chair = new THREE.Group();
      chair.position.set(sx + ux * 0.62, 0, sz + uz * 0.62);
      chair.rotation.y = Math.atan2(-sx, -sz);
      const backM = std(color, { rough: 0.6 });
      const cb = new THREE.Mesh(new THREE.BoxGeometry(1.0, 1.9, 0.14), backM);
      cb.position.set(0, 1.25, 0);
      cb.castShadow = true;
      const cap = new THREE.Mesh(new THREE.BoxGeometry(1.08, 0.1, 0.2), std('#2a2622', { metal: 0.6, rough: 0.4 }));
      cap.position.set(0, 2.22, 0);
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.12, 0.4, 10), std('#2a2622', { metal: 0.6, rough: 0.4 }));
      leg.position.set(0, 0.2, -0.3);
      chair.add(cb, cap, leg);
      G.add(chair);
    }

    tAdd(new THREE.CylinderGeometry(0.5, 0.6, 0.16, 32), std('#33302b', { metal: 0.7, rough: 0.35 }), 0, TABLE_Y + 0.08, 0);
    this.holoRingMat = own(std('#3a2408', { e: '#FFB547', ei: 2.4 }));
    const pr = tAdd(new THREE.TorusGeometry(0.42, 0.035, 8, 40), this.holoRingMat, 0, TABLE_Y + 0.17, 0);
    pr.rotation.x = Math.PI / 2;
    this.holoBeam = new THREE.MeshBasicMaterial({ color: '#FFB547', transparent: true, opacity: 0.1, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
    add(new THREE.CylinderGeometry(1.0, 0.42, 1.5, 32, 1, true), this.holoBeam, 0, TABLE_Y + 0.92, 0, false, false);
    for (let i = 0; i < 2; i++) {
      const r = new THREE.Mesh(new THREE.TorusGeometry(0.6 + i * 0.22, 0.012, 6, 64), this.holoRingMat);
      r.position.set(0, TABLE_Y + 0.7 + i * 0.4, 0);
      r.rotation.x = Math.PI / 2;
      this.holoRings.push(r);
      G.add(r);
    }
    const globe = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.34, 1),
      new THREE.MeshBasicMaterial({ color: '#FFC36B', wireframe: true, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    globe.position.set(0, TABLE_Y + 0.62, 0);
    this.holoGlobe = globe;
    G.add(globe);
    this.holoLight = new THREE.PointLight('#FFB547', 3, 7, 2);
    this.holoLight.position.set(0, TABLE_Y + 0.9, 0);
    G.add(this.holoLight);

    {
      const throne = new THREE.Group();
      throne.position.copy(CHAIR_POS);
      throne.rotation.y = Math.atan2(-CHAIR_POS.x, -CHAIR_POS.z);
      const tadd = (geo: THREE.BufferGeometry, m: THREE.Material, x: number, y: number, z: number) => {
        const o = new THREE.Mesh(geo, m);
        o.position.set(x, y, z);
        o.castShadow = true;
        o.receiveShadow = true;
        throne.add(o);
        return o;
      };
      tadd(new THREE.CylinderGeometry(1.05, 1.2, 0.4, 40), std('#3d342b', { metal: 0.3, rough: 0.7 }), 0, 0.2, 0);
      tadd(new THREE.TorusGeometry(1.12, 0.04, 8, 48), std('#B8862B', { metal: 0.8, rough: 0.3 }), 0, 0.4, 0).rotation.x = Math.PI / 2;
      tadd(new THREE.BoxGeometry(1.4, 2.9, 0.28), std('#4a1d16', { rough: 0.6 }), 0, 1.85, -0.55);
      tadd(new THREE.BoxGeometry(1.6, 0.18, 0.4), std('#B8862B', { metal: 0.8, rough: 0.3 }), 0, 3.32, -0.55);
      tadd(new THREE.BoxGeometry(1.1, 0.5, 0.85), std('#4a1d16', { rough: 0.6 }), 0, 0.65, -0.1);
      tadd(new THREE.BoxGeometry(0.8, 1.05, 0.5), std('#3a2a1e', { rough: 0.7 }), -0.85, 0.92, 0.45);
      tadd(new THREE.CylinderGeometry(0.16, 0.16, 0.08, 20), std('#6b4a2a', { rough: 0.5 }), -0.85, 1.49, 0.45);
      this.gavel.position.set(-0.3, 1.62, 0.45);
      this.gavel.rotation.y = Math.PI;
      const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.55, 8), std('#5b3a1e', { rough: 0.5 }));
      handle.rotation.z = Math.PI / 2;
      handle.position.x = 0.275;
      const head = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.28, 14), std('#7a4f2a', { rough: 0.4 }));
      head.position.x = 0.55;
      const pivot = new THREE.Group();
      pivot.add(handle, head);
      this.gavel.add(pivot);
      head.castShadow = handle.castShadow = true;
      throne.add(this.gavel);
      G.add(throne);
    }
    this.mossyTex = new THREE.TextureLoader().load(spriteUrl);
    this.mossyTex.magFilter = this.mossyTex.minFilter = THREE.NearestFilter;
    this.mossyTex.colorSpace = THREE.SRGBColorSpace;
    this.mossyTex.repeat.set(1 / 8, 1);
    this.textures.push(this.mossyTex);
    this.mossy = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.mossyTex, transparent: true, alphaTest: 0.3, depthTest: false, depthWrite: false,
    }));
    this.mossy.renderOrder = 10;
    this.mossy.scale.setScalar(MOSSY_SCALE);
    this.mossy.position.copy(MOSSY_POS);
    G.add(this.mossy);
    const plaque = canvasTex(1024, 192, (g) => {
      const grd = g.createLinearGradient(0, 0, 0, 192);
      grd.addColorStop(0, '#d9a441'); grd.addColorStop(0.5, '#9a6a1c'); grd.addColorStop(1, '#6e4a12');
      g.fillStyle = grd; g.fillRect(0, 0, 1024, 192);
      g.strokeStyle = '#3d2706'; g.lineWidth = 10; g.strokeRect(8, 8, 1008, 176);
      g.fillStyle = '#2a1803';
      g.font = '700 108px "Chakra Petch", sans-serif';
      g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText('THE  COUNCIL', 512, 104);
    });
    this.textures.push(plaque);
    add(new THREE.PlaneGeometry(3.4, 0.64), std('#ffffff', { map: plaque, metal: 0.5, rough: 0.4 }), 0, 4.75, -7.05, false);

    {
      const [vx, vy, vz] = VAULT_DOOR;
      const door = add(new THREE.CylinderGeometry(1.75, 1.75, 0.5, 48), std('#8a8f96', { metal: 0.75, rough: 0.35 }), vx, vy, vz);
      door.rotation.x = Math.PI / 2;
      add(new THREE.TorusGeometry(1.9, 0.2, 12, 48), std('#4b4f55', { metal: 0.7, rough: 0.4 }), vx, vy, vz + 0.1);
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2;
        add(new THREE.SphereGeometry(0.08, 8, 6), std('#5d6168', { metal: 0.8, rough: 0.3 }), vx + Math.cos(a) * 1.55, vy + Math.sin(a) * 1.55, vz + 0.27, false);
      }
      for (const dy of [-1.0, 1.0]) add(new THREE.BoxGeometry(0.5, 0.36, 0.5), std('#3a3c40', { metal: 0.7, rough: 0.4 }), vx - 1.85, vy + dy, vz + 0.15);
      this.vaultWheel.position.set(vx, vy, vz + 0.36);
      const wheel = new THREE.Mesh(new THREE.TorusGeometry(0.65, 0.07, 10, 32), std('#B8862B', { metal: 0.8, rough: 0.3 }));
      this.vaultWheel.add(wheel);
      for (let i = 0; i < 3; i++) {
        const spoke = new THREE.Mesh(new THREE.BoxGeometry(0.08, 1.3, 0.08), std('#B8862B', { metal: 0.8, rough: 0.3 }));
        spoke.rotation.z = (i * Math.PI) / 3;
        this.vaultWheel.add(spoke);
      }
      G.add(this.vaultWheel);
      this.warn = own(std('#3a1a00', { e: '#FF8A00', ei: 1.5 }));
      add(new THREE.SphereGeometry(0.16, 14, 10), this.warn, vx, vy + 2.2, vz + 0.25, false);
      add(new THREE.CylinderGeometry(0.19, 0.19, 0.06, 14), std('#2a2622', { metal: 0.6 }), vx, vy + 2.05, vz + 0.25, false);
    }

    {
      const rack = std('#26231f', { metal: 0.5, rough: 0.5 });
      add(new THREE.BoxGeometry(3.5, 3.3, 0.7), rack, -2.45, 2.45, -6.8);
      const shell = std('#3b3328', { rough: 0.6 });
      for (let r = 0; r < 3; r++) {
        for (let c = 0; c < 3; c++) {
          const x = -3.52 + c * 1.07, y = 1.35 + r * 1.02, z = -6.32;
          add(new THREE.BoxGeometry(0.98, 0.9, 0.5), shell, x, y, z, false);
          const scr = new Screen(160, 120, 6, (g, w, h, t) => this.paintCrt(g, w, h, t, r * 3 + c));
          this.crts.push(scr);
          this.textures.push(scr.tex);
          const glow = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.66), new THREE.MeshBasicMaterial({ map: scr.tex, toneMapped: false }));
          glow.position.set(x, y + 0.02, z + 0.26);
          G.add(glow);
        }
      }
    }

    {
      this.score = new Screen(1024, 640, 4, (g, w, h) => this.paintScore(g, w, h));
      this.textures.push(this.score.tex);
      add(new THREE.BoxGeometry(4.6, 3.05, 0.25), std('#26231f', { metal: 0.5, rough: 0.5 }), 3.4, 2.45, -6.95);
      const s = new THREE.Mesh(new THREE.PlaneGeometry(4.3, 2.7), new THREE.MeshBasicMaterial({ map: this.score.tex, toneMapped: false }));
      s.position.set(3.4, 2.45, -6.81);
      G.add(s);
    }

    {
      const desk = new THREE.Group();
      desk.position.set(-5.6, 0, -0.6);
      desk.rotation.y = 1.1;
      const body = new THREE.Mesh(new THREE.BoxGeometry(1.8, 1.05, 0.9), std('#4a4338', { metal: 0.35, rough: 0.6 }));
      body.position.y = 0.525;
      const top = new THREE.Mesh(new THREE.BoxGeometry(1.9, 0.12, 1.0), std('#2d2924', { metal: 0.5, rough: 0.5 }));
      top.position.y = 1.08;
      top.rotation.x = -0.25;
      this.moodScreen = own(std('#111', { e: '#FFB547', ei: 2.2, rough: 0.3 }));
      const dial = new THREE.Mesh(new THREE.CircleGeometry(0.36, 32), this.moodScreen);
      dial.position.set(-0.35, 1.16, 0.08);
      dial.rotation.x = -Math.PI / 2 + 0.25;
      for (let i = 0; i < 5; i++) {
        const b = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.05, 12), std(PERSONAS[MEMBER_IDS[i]].color, { e: PERSONAS[MEMBER_IDS[i]].color, ei: 0.6 }));
        b.position.set(0.15 + (i % 3) * 0.22, 1.16, -0.12 + Math.floor(i / 3) * 0.24);
        b.rotation.x = -0.25;
        desk.add(b);
      }
      this.moodLever.position.set(0.72, 1.12, 0);
      const stick = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.6, 8), std('#9ca3af', { metal: 0.8, rough: 0.3 }));
      stick.position.y = 0.3;
      const knob = new THREE.Mesh(new THREE.SphereGeometry(0.09, 14, 10), std('#E5383B', { rough: 0.3 }));
      knob.position.y = 0.62;
      this.moodLever.add(stick, knob);
      desk.add(body, top, dial, this.moodLever);
      body.castShadow = top.castShadow = true;
      G.add(desk);
    }

    const shade = std('#2f4a3a', { metal: 0.5, rough: 0.45 });
    for (const [x, y, z, s] of [[0, 4.35, 0.2, 1.3], [-4.8, 4.9, -3.4, 0.9], [4.8, 4.9, -3.4, 0.9]] as const) {
      const cone = add(new THREE.ConeGeometry(0.55 * s, 0.5 * s, 24, 1, true), shade, x, y, z, false, false);
      (cone.material as THREE.MeshStandardMaterial).side = THREE.DoubleSide;
      add(new THREE.CylinderGeometry(0.012, 0.012, 3.5, 4), std('#111'), x, y + 1.95, z, false, false);
      const bulbM = own(std('#ffd9a0', { e: '#FFB066', ei: 4 }));
      this.lampBulbs.push(bulbM);
      add(new THREE.SphereGeometry(0.13 * s, 14, 10), bulbM, x, y - 0.2 * s, z, false, false);
    }
    this.keyLight = new THREE.SpotLight('#FFC27A', 85, 16, 0.85, 0.6, 2);
    this.keyLight.position.set(0, 4.2, 0.2);
    this.keyLight.target.position.set(0, 0.9, 0);
    this.keyLight.castShadow = true;
    this.keyLight.shadow.mapSize.set(2048, 2048);
    this.keyLight.shadow.bias = -0.0004;
    this.keyLight.shadow.normalBias = 0.02;
    this.keyLight.shadow.radius = 4;
    G.add(this.keyLight, this.keyLight.target);
    for (const x of [-4.8, 4.8]) {
      const l = new THREE.PointLight('#FFB066', 14, 11, 2);
      l.position.set(x, 4.5, -3.4);
      this.sideLights.push(l);
      G.add(l);
    }
    const crtGlow = new THREE.PointLight('#8CFF9E', 4, 7, 2);
    crtGlow.position.set(-2.4, 2.4, -5.4);
    G.add(crtGlow);
    const fill = new THREE.PointLight('#FFD2A0', 150, 22, 2);
    fill.position.set(0, 4.2, 7.5);
    G.add(fill);

    {
      const N = 260;
      const pos = new Float32Array(N * 3);
      for (let i = 0; i < N; i++) {
        const a = Math.random() * Math.PI * 2, r = Math.sqrt(Math.random()) * 3.2;
        pos[i * 3] = Math.cos(a) * r; pos[i * 3 + 1] = 1 + Math.random() * 3.3; pos[i * 3 + 2] = Math.sin(a) * r;
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      this.dust = new THREE.Points(g, new THREE.PointsMaterial({ color: '#FFD7A0', size: 0.035, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
      G.add(this.dust);
    }

    mergeStatic(
      G,
      [this.tableTop, this.gavel, this.mossy, this.vaultWheel, this.moodLever, this.holoGlobe, ...this.holoRings],
      (m) => !this.own.has(m),
    );

    {
      const F = this.frontWall;
      const wall = new THREE.Mesh(new THREE.PlaneGeometry(18, 8), wallM);
      wall.position.set(0, 4, 8.9);
      wall.rotation.y = Math.PI;
      wall.receiveShadow = true;
      const wains = new THREE.Mesh(new THREE.BoxGeometry(18, 1.3, 0.2), steelM);
      wains.position.set(0, 0.65, 8.8);
      F.add(wall, wains);
      for (const x of [-4.5, 4.5]) {
        const beam = new THREE.Mesh(new THREE.BoxGeometry(0.5, 8, 0.45), beamM);
        beam.position.set(x, 4, 8.65);
        F.add(beam);
      }
      const c = document.createElement('canvas');
      c.width = 512; c.height = 160;
      const g = c.getContext('2d')!;
      g.fillStyle = '#04140a';
      g.fillRect(0, 0, 512, 160);
      g.strokeStyle = '#4ADE80';
      g.lineWidth = 10;
      g.strokeRect(8, 8, 496, 144);
      g.fillStyle = '#86EFAC';
      g.font = '800 92px "Chakra Petch", sans-serif';
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText('◂ EXIT', 256, 86);
      const tex = new THREE.CanvasTexture(c);
      tex.colorSpace = THREE.SRGBColorSpace;
      this.textures.push(tex);
      const sign = new THREE.Mesh(new THREE.PlaneGeometry(1.3, 0.41), new THREE.MeshBasicMaterial({ map: tex, toneMapped: false }));
      sign.position.set(VAULT_DOOR[0], VAULT_DOOR[1] + 2.35, VAULT_DOOR[2] + 0.45);
      F.add(sign);
      F.visible = false;
      G.add(F);
    }
  }

  setOnFoot(on: boolean): void {
    this.frontWall.visible = on;
    (this.dust.material as THREE.PointsMaterial).size = on ? 0.012 : 0.035;
    if (!on) this.exitNear = 0;
  }

  setExitNear(f: number): void {
    this.exitNear = Math.max(0, Math.min(1, f));
  }


  feed(text: string): void {
    this.crtFeed.push(text);
    if (this.crtFeed.length > 40) this.crtFeed.shift();
  }

  private paintCrt(g: CanvasRenderingContext2D, w: number, h: number, t: number, i: number): void {
    const amber = i % 3 === 1;
    const fg = amber ? '#FFB547' : '#7CFF9A';
    g.fillStyle = amber ? '#1a0e02' : '#031407';
    g.fillRect(0, 0, w, h);
    g.fillStyle = fg;
    g.strokeStyle = fg;
    const kind = i % 4;
    if (kind === 0) {
      g.lineWidth = 3;
      g.beginPath();
      for (let x = 0; x <= w; x += 8) {
        const y = h * 0.55 + Math.sin(x * 0.07 + t * 2 + i) * 18 + Math.sin(x * 0.21 + t * 3.1) * 8;
        if (x === 0) g.moveTo(x, y); else g.lineTo(x, y);
      }
      g.stroke();
    } else if (kind === 1 || kind === 3) {
      g.font = '600 15px "JetBrains Mono", monospace';
      const lines = this.crtFeed.slice(-(5 + i)).slice(0, 5);
      lines.forEach((l, k) => g.fillText(l.slice(0, 16), 6, 22 + k * 21));
      if (Math.floor(t * 2) % 2) g.fillRect(6, 22 + lines.length * 21 - 12, 9, 14);
    } else {
      for (let b = 0; b < 7; b++) {
        const v = 0.25 + 0.7 * Math.abs(Math.sin(t * (0.8 + b * 0.3) + i));
        g.fillRect(10 + b * 20, h - 10 - v * (h - 30), 13, v * (h - 30));
      }
    }
    g.fillStyle = 'rgba(0,0,0,0.28)';
    for (let y = 0; y < h; y += 3) g.fillRect(0, y, w, 1);
    const v = g.createRadialGradient(w / 2, h / 2, h * 0.3, w / 2, h / 2, w * 0.7);
    v.addColorStop(0, 'rgba(0,0,0,0)');
    v.addColorStop(1, 'rgba(0,0,0,0.65)');
    g.fillStyle = v;
    g.fillRect(0, 0, w, h);
  }

  setScore(view: ScoreView): void {
    this.scoreView = view;
    this.score.update(0, 0, true);
  }

  private paintScore(g: CanvasRenderingContext2D, w: number, h: number): void {
    const v = this.scoreView;
    g.fillStyle = '#140b02';
    g.fillRect(0, 0, w, h);
    g.fillStyle = '#FFB547';
    g.font = '700 54px "Chakra Petch", sans-serif';
    g.textBaseline = 'middle';
    g.fillText(v.title, 34, 52);
    g.font = '600 26px "JetBrains Mono", monospace';
    g.fillStyle = '#B08040';
    g.textAlign = 'right';
    g.fillText(v.caption, w - 34, 54);
    g.textAlign = 'left';
    const rh = (h - 110) / 6;
    v.lines.slice(0, 6).forEach((r, i) => {
      const y = 110 + i * rh + rh / 2;
      g.fillStyle = 'rgba(255,181,71,0.07)';
      if (i % 2 === 0) g.fillRect(20, y - rh / 2 + 4, w - 40, rh - 8);
      g.fillStyle = r.color;
      g.fillRect(34, y - 18, 36, 36);
      g.fillStyle = '#FFD9A0';
      const nameY = r.sub ? y - 12 : y + 2;
      let px = r.sub ? 34 : 46;
      g.font = `700 ${px}px "Chakra Petch", sans-serif`;
      while (px > 22 && g.measureText(r.name).width > 320) {
        px -= 2;
        g.font = `700 ${px}px "Chakra Petch", sans-serif`;
      }
      g.fillText(r.name, 92, nameY);
      if (r.sub) {
        g.font = '500 20px "JetBrains Mono", monospace';
        g.fillStyle = '#B08040';
        g.fillText(r.sub.length > 40 ? `${r.sub.slice(0, 39)}…` : r.sub, 92, y + 22);
      }
      const bx = 430, bw = 330;
      g.fillStyle = 'rgba(255,181,71,0.15)';
      g.fillRect(bx, y - 14, bw, 28);
      if (r.bar !== null) {
        g.fillStyle = r.signed ? (r.bar >= 0 ? '#4ADE80' : '#F87171') : r.color;
        if (r.signed) {
          const mid = bx + bw / 2;
          const len = (bw / 2) * Math.min(1, Math.abs(r.bar));
          g.fillRect(r.bar >= 0 ? mid : mid - len, y - 14, len, 28);
          g.fillStyle = 'rgba(255,226,176,0.6)';
          g.fillRect(mid - 1, y - 18, 2, 36);
        } else {
          g.fillRect(bx, y - 14, bw * Math.max(0, Math.min(1, r.bar)), 28);
        }
      }
      g.textAlign = 'right';
      g.font = '700 52px "JetBrains Mono", monospace';
      g.fillStyle = r.tone === 'none' ? '#7a5a30' : r.tone === 'good' ? '#8CFF9E' : r.tone === 'bad' ? '#FF8A7A' : '#FFD9A0';
      g.fillText(r.value, w - 34, y + 2);
      g.textAlign = 'left';
    });
    g.fillStyle = 'rgba(0,0,0,0.22)';
    for (let y = 0; y < h; y += 4) g.fillRect(0, y, w, 1.5);
  }


  setVote(i: number, v: boolean | null): void {
    const m = this.voteLamps[i];
    if (!m) return;
    if (v === null) { m.emissive.set('#000000'); m.emissiveIntensity = 0; return; }
    m.emissive.set(v ? '#22FF66' : '#FF2A2A');
    m.emissiveIntensity = 3.2;
  }

  bangGavel(times = 1): void {
    this.gavelT = 0;
    this.gavelHits = times;
    this.mossyHop = 0.6;
  }

  setMood(color: string): void {
    this.moodColor.set(color);
  }

  update(dt: number, t: number): void {
    const f = 1 + Math.sin(t * 13.1) * 0.025 + Math.sin(t * 7.7) * 0.02 + (Math.random() < 0.004 ? -0.25 : 0);
    this.keyLight.intensity = 85 * f;
    this.sideLights.forEach((l, i) => { l.intensity = 14 * (1 + Math.sin(t * (9 + i * 3)) * 0.04); });
    this.lampBulbs.forEach((b) => { b.emissiveIntensity = 4 * f; });

    this.holoPulse = Math.max(0, this.holoPulse - dt * 1.5);
    this.holoRingMat.emissive.copy(this.holoColor);
    this.holoRingMat.emissiveIntensity = 1.3 + this.holoPulse * 2.5 + Math.sin(t * 6) * 0.2;
    this.holoBeam.color.copy(this.holoColor);
    this.holoBeam.opacity = 0.045 + this.holoPulse * 0.08 + Math.sin(t * 17) * 0.008;
    this.holoLight.color.copy(this.holoColor);
    this.holoLight.intensity = 1.5 + this.holoPulse * 5;
    this.holoRings.forEach((r, i) => { r.rotation.z += dt * (i ? -0.8 : 0.6); r.position.y = TABLE_Y + 0.7 + i * 0.4 + Math.sin(t * 1.5 + i) * 0.05; });
    this.holoGlobe.rotation.y += dt * 0.6;
    this.holoGlobe.rotation.x = Math.sin(t * 0.4) * 0.3;
    ((this.holoGlobe as THREE.Mesh).material as THREE.MeshBasicMaterial).color.copy(this.holoColor);

    for (const c of this.crts) c.update(dt, t);
    this.moodScreen.emissive.lerp(this.moodColor, Math.min(1, dt * 3));
    this.moodLever.rotation.x = THREE.MathUtils.lerp(this.moodLever.rotation.x, Math.sin(t * 0.7) * 0.15 + 0.35, dt * 2);

    this.gavelT += dt;
    const hitLen = 0.32;
    const pivot = this.gavel.children[0];
    if (this.gavelHits > 0 && this.gavelT < hitLen * this.gavelHits) {
      const c = (this.gavelT % hitLen) / hitLen;
      pivot.rotation.z = c < 0.6 ? (c / 0.6) * 1.1 : 1.1 - ((c - 0.6) / 0.4) * 1.1;
    } else {
      pivot.rotation.z = 0;
      this.gavelHits = 0;
    }
    this.tableShake.v = Math.max(0, this.tableShake.v - dt * 4);
    this.tableTop.position.y = Math.sin(t * 60) * 0.012 * this.tableShake.v;

    this.mossyAcc += dt;
    if (this.mossyAcc > 0.9 / 8) {
      this.mossyAcc = 0;
      this.mossyFrame = (this.mossyFrame + 1) % 8;
      this.mossyTex.offset.x = this.mossyFrame / 8;
    }
    this.mossyHop = Math.max(0, this.mossyHop - dt);
    this.mossy.position.y = MOSSY_POS.y + Math.sin(t * 2) * 0.03 + (this.mossyHop > 0 ? Math.abs(Math.sin(this.mossyHop * 10)) * 0.3 : 0);

    this.vaultWheel.rotation.z += dt * (0.05 + this.exitNear * 2.4);
    this.warn.emissiveIntensity = 0.6 + Math.max(0, Math.sin(t * 3)) * 2.4;
    this.dust.rotation.y += dt * 0.03;
    this.dust.position.y = Math.sin(t * 0.3) * 0.1;
  }

  get chairHead(): THREE.Vector3 {
    return new THREE.Vector3(MOSSY_POS.x, this.mossy.position.y + MOSSY_SCALE * 0.55, MOSSY_POS.z);
  }

  dispose(): void {
    this.textures.forEach((t) => t.dispose());
  }
}
