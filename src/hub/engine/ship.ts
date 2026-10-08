import * as THREE from 'three';
import spriteUrl from '../../assets/mossy.png';
import {
  DOOR_W, KALSHI_POS, PART_H, PROP, RIM_H, ROOM, ROOMS, SHIP, WALL_H, type RoomId,
} from './layout';
import type { ItemKit } from './items';
import { mergeStatic } from './bake';


type V2 = readonly [number, number];

class Mats {
  private m = new Map<string, THREE.MeshStandardMaterial>();
  get(color: string, o: { e?: string; ei?: number; metal?: number; rough?: number } = {}): THREE.MeshStandardMaterial {
    const k = `${color}|${o.e ?? ''}|${o.ei ?? 0}|${o.metal ?? 0.1}|${o.rough ?? 0.75}`;
    let mat = this.m.get(k);
    if (!mat) {
      mat = new THREE.MeshStandardMaterial({
        color, emissive: o.e ?? '#000000', emissiveIntensity: o.ei ?? 0,
        metalness: o.metal ?? 0.1, roughness: o.rough ?? 0.75,
      });
      this.m.set(k, mat);
    }
    return mat;
  }
  readonly owned = new Set<THREE.Material>();
  own(color: string, e: string, ei: number, metal = 0.1, rough = 0.6): THREE.MeshStandardMaterial {
    const m = new THREE.MeshStandardMaterial({ color, emissive: e, emissiveIntensity: ei, metalness: metal, roughness: rough });
    this.owned.add(m);
    return m;
  }
}

function at<T extends THREE.Object3D>(o: T, x: number, y: number, z: number): T {
  o.position.set(x, y, z);
  return o;
}

class Screen {
  readonly canvas = document.createElement('canvas');
  readonly ctx: CanvasRenderingContext2D;
  readonly tex: THREE.CanvasTexture;
  private acc = 0;
  constructor(w: number, h: number, private hz: number, private draw: (g: CanvasRenderingContext2D, w: number, h: number, t: number) => void) {
    this.canvas.width = w;
    this.canvas.height = h;
    this.ctx = this.canvas.getContext('2d')!;
    this.tex = new THREE.CanvasTexture(this.canvas);
    this.tex.colorSpace = THREE.SRGBColorSpace;
    this.tex.anisotropy = 4;
    this.draw(this.ctx, w, h, 0);
  }
  update(dt: number, t: number, force = false): void {
    this.acc += dt;
    if (!force && this.acc < 1 / this.hz) return;
    this.acc = 0;
    this.draw(this.ctx, this.canvas.width, this.canvas.height, t);
    this.tex.needsUpdate = true;
  }
}

function tileTexture(): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d')!;
  g.fillStyle = '#ffffff';
  g.fillRect(0, 0, 128, 128);
  g.fillStyle = 'rgba(0,0,0,0.07)';
  g.fillRect(64, 0, 64, 64);
  g.fillRect(0, 64, 64, 64);
  g.strokeStyle = 'rgba(0,0,0,0.22)';
  g.lineWidth = 3;
  g.strokeRect(0, 0, 128, 128);
  g.beginPath();
  g.moveTo(64, 0); g.lineTo(64, 128); g.moveTo(0, 64); g.lineTo(128, 64);
  g.lineWidth = 1.5;
  g.stroke();
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

export interface Blip { a: number; r: number; color: string; age: number }

export class Ship {
  readonly group = new THREE.Group();
  readonly space = new THREE.Group();
  readonly mats = new Mats();
  private tiles = tileTexture();
  private textures: THREE.Texture[] = [this.tiles];
  readonly roomFloors: THREE.Mesh[] = [];

  private dishPivot = new THREE.Group();
  private dishTip: THREE.MeshStandardMaterial;
  private dishPing = 0;
  private labScreen: Screen;
  readonly blips: Blip[] = [];
  private printerLight: THREE.MeshStandardMaterial;
  private printerFlash = 0;

  private furnaceMouth: THREE.MeshStandardMaterial;
  private furnaceLight: THREE.PointLight;
  private anvilTop: THREE.MeshStandardMaterial;
  private anvilFlash = 0;

  private holo: Screen;
  private holoMesh: THREE.Mesh;
  private holoSeries: number[] = [];
  private holoProgress = 1;
  private holoPass: boolean | null = null;
  private holoRunning = false;
  private holoLabel = 'BACKTEST';
  private holoSub = 'idle';
  private lamp: THREE.MeshStandardMaterial;
  private reels: THREE.Object3D[] = [];
  private binFlash = 0;
  private binRing: THREE.MeshStandardMaterial;

  private tubeRing: THREE.MeshStandardMaterial;
  private tubeFlash = 0;
  private hatchLight: THREE.MeshStandardMaterial;
  private hatchDisc = new THREE.Group();
  private hatchFlash = 0;
  private termScreens: THREE.MeshStandardMaterial[] = [];
  private board: Screen;
  readonly boardLines: { text: string; color: string }[] = [];

  private vaultWheel = new THREE.Group();
  private vaultSpin = 0;
  private beaconHead = new THREE.Group();
  private beaconMat: THREE.MeshStandardMaterial;
  private beaconBeams: THREE.Mesh[] = [];
  private alarmLight: THREE.PointLight;
  private vaultGlow: THREE.PointLight;
  alarm = 0;
  private vaultFlash = 0;

  private fans: THREE.Object3D[] = [];
  private fanSpeed = 1.2;
  private fanTarget = 1.2;
  private reactorMat: THREE.MeshStandardMaterial;
  private reactorRings: THREE.Object3D[] = [];
  private reactorLight: THREE.PointLight;
  private exhaust: THREE.Sprite[] = [];
  private optimizing = false;

  private mossy: THREE.Sprite;
  private mossyTex: THREE.Texture;
  private mossyFrame = 0;
  private mossyAcc = 0;
  mossyHop = 0;

  readonly station = new THREE.Group();
  private stationFlash = 0;
  private stationLights!: THREE.MeshStandardMaterial;
  private stars!: THREE.Points;
  private starMat!: THREE.ShaderMaterial;

  readonly inboxSlots: THREE.Vector3[] = [];
  readonly outboxSlots: THREE.Vector3[] = [];
  readonly rackSlots: THREE.Vector3[] = [];
  readonly airlockSlots: THREE.Vector3[] = [];
  readonly tubeMouth = new THREE.Vector3(PROP.tube[0], 0.95, PROP.tube[1] - 1.4);
  readonly tubeInside = new THREE.Vector3(PROP.tube[0], 0.95, PROP.tube[1] + 0.35);
  readonly hatchPos = new THREE.Vector3(PROP.hatch[0], 0.85, PROP.hatch[1] - 0.6);
  readonly kalshiPos = new THREE.Vector3(...KALSHI_POS);

  constructor(private kit: ItemKit) {
    const M = this.mats;
    this.buildHull();
    this.buildFloors();
    this.buildWalls();

    {
      const [dx, dz] = PROP.dish;
      const base = at(new THREE.Group(), dx, 0, dz);
      const foot = at(new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.6, 0.25, 16), M.get('#8b85a6', { metal: 0.4, rough: 0.4 })), 0, 0.125, 0);
      const ped = at(new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.22, 1.25, 12), M.get('#a8a2bf', { metal: 0.4, rough: 0.4 })), 0, 0.85, 0);
      foot.castShadow = ped.castShadow = true;
      base.add(foot, ped);
      this.dishPivot.position.y = 1.45;
      const bowl = new THREE.Group();
      bowl.rotation.x = 0.45;
      const dishMat = M.own('#F1EEFA', '#A855F7', 0.12, 0.2, 0.4);
      dishMat.side = THREE.DoubleSide;
      const dish = at(new THREE.Mesh(new THREE.SphereGeometry(1.0, 28, 10, 0, Math.PI * 2, Math.PI * 0.68, Math.PI * 0.32), dishMat), 0, 1.0, 0);
      dish.castShadow = true;
      const rimRing = at(new THREE.Mesh(new THREE.TorusGeometry(0.86, 0.05, 8, 32), M.get('#A855F7', { e: '#A855F7', ei: 1.4 })), 0, 0.5, 0);
      rimRing.rotation.x = Math.PI / 2;
      const horn = at(new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.85, 6), M.get('#4b4563')), 0, 0.42, 0);
      this.dishTip = M.own('#A855F7', '#A855F7', 2);
      const tip = at(new THREE.Mesh(new THREE.SphereGeometry(0.11, 12, 10), this.dishTip), 0, 0.88, 0);
      bowl.add(dish, rimRing, horn, tip);
      this.dishPivot.add(bowl);
      base.add(this.dishPivot);
      this.group.add(base);

      this.labScreen = new Screen(384, 216, 20, (g, w, h, t) => this.drawRadar(g, w, h, t));
      this.textures.push(this.labScreen.tex);
      this.wallScreen(PROP.labScreen, 2.7, 1.5, 1.35, this.labScreen.tex, '#A855F7');

      for (const [x, z] of [PROP.labConsoleA, PROP.labConsoleB]) this.console(x, z, 0, '#A855F7');
      const [px, pz] = PROP.printer;
      this.group.add(this.boxAt(px, pz, 0.7, 0.85, 0.65, '#d8d3ea'));
      this.printerLight = M.own('#2a1f45', '#A855F7', 0.6);
      this.group.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.06, 0.04), this.printerLight), px, 0.62, pz + 0.33));
      this.group.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.04, 0.4), M.get('#3b3456')), px, 0.87, pz));
      this.decorShelf(2.6, -6.15, '#A855F7');
    }

    {
      const [fx, fz] = PROP.furnace;
      const furnace = this.boxAt(fx, fz, 1.5, 1.5, 1.1, '#6b4636', { rough: 0.95 });
      this.group.add(furnace);
      const top = this.boxAt(fx, fz, 1.6, 0.14, 1.2, '#4a2f25');
      top.position.y = 1.5;
      this.group.add(top);
      const chim = at(new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.26, 1.1, 12), M.get('#4a2f25')), fx - 0.35, 2.1, fz - 0.2);
      chim.castShadow = true;
      this.group.add(chim);
      this.furnaceMouth = M.own('#ff7a1a', '#ff6a00', 2.6);
      const mouth = at(new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.55), this.furnaceMouth), fx + 0.2, 0.55, fz + 0.56);
      const mouth2 = at(new THREE.Mesh(new THREE.PlaneGeometry(0.6, 0.55), this.furnaceMouth), fx + 0.76, 0.55, fz + 0.1);
      mouth2.rotation.y = Math.PI / 2;
      this.group.add(mouth, mouth2);
      this.furnaceLight = at(new THREE.PointLight('#ff8a3d', 6, 6, 1.6), fx + 0.9, 0.9, fz + 0.9);
      this.group.add(this.furnaceLight);

      const [ax, az] = PROP.anvil;
      const ab = at(new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.32, 0.5, 10), M.get('#3f3a4a', { metal: 0.5, rough: 0.5 })), ax, 0.25, az);
      ab.castShadow = true;
      this.anvilTop = M.own('#5b5768', '#ffb347', 0, 0.7, 0.35);
      const at2 = at(new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.22, 0.42), this.anvilTop), ax, 0.6, az);
      at2.castShadow = true;
      const horn = at(new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.35, 10), this.anvilTop), ax - 0.55, 0.62, az);
      horn.rotation.z = Math.PI / 2;
      this.group.add(ab, at2, horn);

      const [ix, iz] = PROP.inbox;
      this.group.add(this.table(ix, iz, 0.95, 0.6, '#9a7b5c'));
      for (let i = 0; i < 3; i++) this.inboxSlots.push(new THREE.Vector3(ix - 0.28 + i * 0.28, 0.82, iz));
      const [ox, oz] = PROP.outbox;
      this.group.add(this.table(ox, oz, 0.75, 0.9, '#9a7b5c'));
      for (let i = 0; i < 3; i++) this.outboxSlots.push(new THREE.Vector3(ox, 0.85, oz - 0.3 + i * 0.3));
      this.group.add(this.table(-1.2, 5.75, 1.4, 0.55, '#7a5c43'));
      for (let i = 0; i < 4; i++) {
        const t = at(new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.3, 0.08), M.get(['#9CA3AF', '#F59E0B', '#DC2626', '#9CA3AF'][i], { metal: 0.5 })), -1.7 + i * 0.32, 0.92, 5.75);
        this.group.add(t);
      }
    }

    {
      const [hx, hz] = PROP.holo;
      const base = at(new THREE.Mesh(new THREE.CylinderGeometry(0.85, 0.95, 0.65, 24), M.get('#2e5560', { metal: 0.3, rough: 0.5 })), hx, 0.325, hz);
      base.castShadow = true;
      base.receiveShadow = true;
      const top = at(new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.8, 0.05, 24), M.get('#0b2a30', { e: '#2DD4BF', ei: 1.2 })), hx, 0.67, hz);
      this.group.add(base, top);
      this.holo = new Screen(320, 200, 30, (g, w, h) => this.drawHolo(g, w, h));
      this.textures.push(this.holo.tex);
      this.holoMesh = at(new THREE.Mesh(
        new THREE.PlaneGeometry(2.6, 1.6),
        new THREE.MeshBasicMaterial({ map: this.holo.tex, transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, toneMapped: false }),
      ), hx, 1.75, hz);
      this.holoMesh.rotation.y = Math.PI / 4;
      this.group.add(this.holoMesh);
      const beam = at(new THREE.Mesh(
        new THREE.CylinderGeometry(0.75, 0.8, 0.8, 24, 1, true),
        new THREE.MeshBasicMaterial({ color: '#2DD4BF', transparent: true, opacity: 0.08, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }),
      ), hx, 1.08, hz);
      this.group.add(beam);
      this.lamp = M.own('#334155', '#64748B', 0.5);
      const stalk = at(new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.9, 6), M.get('#64748B')), hx + 0.75, 1.1, hz - 0.45);
      const lamp = at(new THREE.Mesh(new THREE.SphereGeometry(0.15, 14, 10), this.lamp), hx + 0.75, 1.62, hz - 0.45);
      this.group.add(stalk, lamp);

      const [tx, tz] = PROP.tapeDeck;
      this.group.add(this.boxAt(tx, tz, 1.1, 1.9, 0.8, '#cfd8dc'));
      for (const dy of [1.35, 0.75]) {
        const reel = new THREE.Group();
        reel.position.set(tx, dy, tz + 0.42);
        const r = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.05, 20), M.get('#1f2937'));
        r.rotation.x = Math.PI / 2;
        const sp = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.06, 0.07), M.get('#2DD4BF', { e: '#2DD4BF', ei: 0.8 }));
        sp.position.z = 0.03;
        reel.add(r, sp);
        this.reels.push(reel);
        this.group.add(reel);
      }
      const [bx, bz] = PROP.bin;
      const bin = at(new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.26, 0.6, 16), M.get('#374151')), bx, 0.3, bz);
      bin.castShadow = true;
      this.binRing = M.own('#7f1d1d', '#EF4444', 0.6);
      const ring = at(new THREE.Mesh(new THREE.TorusGeometry(0.3, 0.04, 8, 20), this.binRing), bx, 0.6, bz);
      ring.rotation.x = Math.PI / 2;
      this.group.add(bin, ring);
    }

    {
      const [tx, tz] = PROP.tube;
      const tube = at(new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 2.6, 20, 1, true), M.get('#cfcadf', { metal: 0.5, rough: 0.35 })), tx, 0.95, tz - 0.6);
      tube.rotation.x = Math.PI / 2;
      tube.castShadow = true;
      (tube.material as THREE.MeshStandardMaterial).side = THREE.DoubleSide;
      this.tubeRing = M.own('#EC4899', '#EC4899', 1.2);
      const ring = at(new THREE.Mesh(new THREE.TorusGeometry(0.52, 0.08, 10, 24), this.tubeRing), tx, 0.95, tz + 0.65);
      const ring2 = at(new THREE.Mesh(new THREE.TorusGeometry(0.52, 0.08, 10, 24), this.tubeRing), tx, 0.95, tz - 1.85);
      const base = this.boxAt(tx, tz + 0.2, 1.2, 0.42, 0.8, '#8f88a8');
      this.group.add(tube, ring, ring2, base);

      const [hx, hz] = PROP.hatch;
      this.hatchDisc.position.set(hx, 1.0, hz + 0.14);
      const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.08, 24), M.get('#a8a2bf', { metal: 0.5, rough: 0.4 }));
      disc.rotation.x = Math.PI / 2;
      const bar = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.12, 0.1), M.get('#6b6585'));
      bar.position.z = 0.06;
      const bar2 = bar.clone();
      bar2.rotation.z = Math.PI / 2;
      this.hatchDisc.add(disc, bar, bar2);
      const rim = at(new THREE.Mesh(new THREE.TorusGeometry(0.66, 0.07, 8, 24), M.get('#FBBF24', { e: '#F59E0B', ei: 0.6, metal: 0.5 })), hx, 1.0, hz + 0.14);
      this.hatchLight = M.own('#3b2a08', '#FBBF24', 0.4);
      const hl = at(new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.12, 0.08), this.hatchLight), hx, 1.85, hz + 0.14);
      this.group.add(this.hatchDisc, rim, hl);
      for (let i = 0; i < 4; i++) this.airlockSlots.push(new THREE.Vector3(hx - 0.55 + (i % 2) * 0.55 + 0.3, 0.25, hz + 0.6 + Math.floor(i / 2) * 0.45));

      for (const [x, z] of [PROP.termA, PROP.termB]) this.termScreens.push(this.console(x, z, 0, '#EC4899', true));
      this.board = new Screen(384, 160, 8, (g, w, h) => this.drawBoard(g, w, h));
      this.textures.push(this.board.tex);
      this.wallScreen(PROP.ordersBoard, 2.3, 1.0, 1.55, this.board.tex, '#EC4899');
      const [rx, rz] = PROP.rack;
      this.group.add(this.table(rx, rz, 0.6, 1.1, '#6d6688'));
      for (let i = 0; i < 4; i++) this.rackSlots.push(new THREE.Vector3(rx, 0.85, rz - 0.4 + i * 0.27));
    }

    {
      const [vx, vz] = PROP.vaultDoor;
      const frame = this.boxAt(vx, vz - 0.12, 2.5, 2.4, 0.3, '#7d8a80', { metal: 0.4 });
      this.group.add(frame);
      this.vaultWheel.position.set(vx, 1.2, vz + 0.12);
      const door = new THREE.Mesh(new THREE.CylinderGeometry(1.0, 1.0, 0.22, 32), M.get('#b7c4bb', { metal: 0.65, rough: 0.3 }));
      door.rotation.x = Math.PI / 2;
      door.castShadow = true;
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.2, 16), M.get('#FBBF24', { e: '#B45309', ei: 0.4, metal: 0.7, rough: 0.3 }));
      hub.rotation.x = Math.PI / 2;
      hub.position.z = 0.14;
      this.vaultWheel.add(door, hub);
      for (let i = 0; i < 3; i++) {
        const spoke = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.08, 0.08), M.get('#FBBF24', { metal: 0.7, rough: 0.3 }));
        spoke.rotation.z = (i * Math.PI) / 3;
        spoke.position.z = 0.16;
        this.vaultWheel.add(spoke);
      }
      this.group.add(this.vaultWheel);
      const sign = at(new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.26, 0.06), M.get('#14532d', { e: '#22C55E', ei: 1.4 })), vx, 2.55, vz);
      this.group.add(sign);

      const [bx, bz] = PROP.beacon;
      const pole = at(new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.07, 1.9, 8), M.get('#6b7280')), bx, 0.95, bz);
      this.group.add(pole);
      this.beaconHead.position.set(bx, 2.0, bz);
      this.beaconMat = M.own('#7f1d1d', '#EF4444', 0.3);
      const dome = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2), this.beaconMat);
      this.beaconHead.add(dome);
      for (let i = 0; i < 2; i++) {
        const b = new THREE.Mesh(
          new THREE.ConeGeometry(0.5, 2.6, 16, 1, true),
          new THREE.MeshBasicMaterial({ color: '#EF4444', transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }),
        );
        b.rotation.z = Math.PI / 2;
        b.position.x = (i ? -1 : 1) * 1.3;
        b.rotation.z = i ? -Math.PI / 2 : Math.PI / 2;
        b.position.y = 0.1;
        this.beaconBeams.push(b);
        this.beaconHead.add(b);
      }
      this.group.add(this.beaconHead);
      this.alarmLight = at(new THREE.PointLight('#ff2a2a', 0, 9, 1.4), bx - 1.4, 1.8, bz + 1.6);
      this.vaultGlow = at(new THREE.PointLight('#FCD34D', 1.5, 6, 1.6), PROP.pile[0], 1.6, PROP.pile[1] + 0.6);
      this.group.add(this.alarmLight, this.vaultGlow);

      const [cx, cz] = PROP.riskConsole;
      this.console(cx, cz, Math.PI, '#EF4444');
    }

    {
      for (const [x, z] of [PROP.turbineA, PROP.turbineB]) {
        const stand = this.boxAt(x, z, 1.4, 0.5, 0.9, '#5b6478', { metal: 0.4 });
        this.group.add(stand);
        const housing = at(new THREE.Mesh(new THREE.CylinderGeometry(0.78, 0.78, 0.7, 28, 1, true), M.get('#9aa4b8', { metal: 0.6, rough: 0.35 })), x, 1.3, z);
        housing.rotation.x = Math.PI / 2;
        (housing.material as THREE.MeshStandardMaterial).side = THREE.DoubleSide;
        housing.castShadow = true;
        const back = at(new THREE.Mesh(new THREE.CircleGeometry(0.76, 28), M.get('#1e293b')), x, 1.3, z - 0.2);
        const ring = at(new THREE.Mesh(new THREE.TorusGeometry(0.8, 0.06, 8, 28), M.get('#38BDF8', { e: '#38BDF8', ei: 1.4 })), x, 1.3, z + 0.36);
        const fan = new THREE.Group();
        fan.position.set(x, 1.3, z + 0.05);
        for (let i = 0; i < 5; i++) {
          const blade = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.66, 0.04), M.get('#e2e8f0', { metal: 0.5, rough: 0.3 }));
          blade.position.y = 0.36;
          const arm = new THREE.Group();
          arm.rotation.z = (i / 5) * Math.PI * 2;
          blade.rotation.y = 0.5;
          arm.add(blade);
          fan.add(arm);
        }
        const hub = new THREE.Mesh(new THREE.SphereGeometry(0.15, 14, 10), M.get('#38BDF8', { e: '#38BDF8', ei: 2 }));
        fan.add(hub);
        this.fans.push(fan);
        this.group.add(housing, back, ring, fan);
      }
      const [rx, rz] = PROP.reactor;
      this.group.add(this.boxAt(rx, rz, 1.2, 0.3, 1.2, '#475569', { metal: 0.4 }));
      this.reactorMat = M.own('#0c4a6e', '#38BDF8', 1.6, 0.1, 0.2);
      const core = at(new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 1.8, 20), this.reactorMat), rx, 1.2, rz);
      const glass = at(new THREE.Mesh(
        new THREE.CylinderGeometry(0.48, 0.48, 1.9, 20, 1, true),
        new THREE.MeshStandardMaterial({ color: '#bae6fd', transparent: true, opacity: 0.18, roughness: 0.1, metalness: 0.2 }),
      ), rx, 1.25, rz);
      const cap = at(new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.55, 0.2, 20), M.get('#64748b', { metal: 0.5 })), rx, 2.25, rz);
      this.group.add(core, glass, cap);
      for (let i = 0; i < 3; i++) {
        const r = at(new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.04, 8, 24), M.get('#7dd3fc', { e: '#38BDF8', ei: 2.2 })), rx, 0.6 + i * 0.6, rz);
        r.rotation.x = Math.PI / 2;
        this.reactorRings.push(r);
        this.group.add(r);
      }
      this.reactorLight = at(new THREE.PointLight('#38BDF8', 4, 6, 1.6), rx + 0.6, 1.4, rz + 0.9);
      this.group.add(this.reactorLight);
      this.console(PROP.optPanel[0], PROP.optPanel[1], Math.PI / 2, '#38BDF8');
      for (const y of [0.55, 1.85]) {
        const p = at(new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 5.4, 10), M.get('#94a3b8', { metal: 0.6, rough: 0.35 })), SHIP.x0 + 0.2, y, -3.8);
        p.rotation.x = Math.PI / 2;
        this.group.add(p);
      }
      for (const z of [-4.0, 0, 4.0]) {
        const nozzle = at(new THREE.Mesh(new THREE.CylinderGeometry(0.75, 1.05, 1.3, 20, 1, true), M.get('#6b6585', { metal: 0.5, rough: 0.4 })), SHIP.x0 - 0.75, -0.25, z);
        nozzle.rotation.z = -Math.PI / 2;
        (nozzle.material as THREE.MeshStandardMaterial).side = THREE.DoubleSide;
        const inner = at(new THREE.Mesh(new THREE.CircleGeometry(0.8, 20), M.get('#38BDF8', { e: '#7dd3fc', ei: 3 })), SHIP.x0 - 1.3, -0.25, z);
        inner.rotation.y = -Math.PI / 2;
        const glow = kit.glow('#38BDF8', 3.2, 0.8);
        glow.position.set(SHIP.x0 - 2.3, -0.25, z);
        const glow2 = kit.glow('#A855F7', 5.5, 0.35);
        glow2.position.set(SHIP.x0 - 3.6, -0.25, z);
        this.exhaust.push(glow, glow2);
        this.group.add(nozzle, inner, glow, glow2);
      }
    }

    {
      const [cx, cz] = PROP.chair;
      const seat = this.boxAt(cx, cz, 0.75, 0.5, 0.75, '#4c1d95');
      const back = this.boxAt(cx - 0.42, cz, 0.16, 1.15, 0.8, '#5b21b6');
      const post = this.boxAt(cx, cz, 0.2, 0.3, 0.2, '#334155');
      this.group.add(post, seat, back);
      const [hx, hz] = PROP.helm;
      const helm = this.boxAt(hx, hz, 0.6, 0.8, 1.9, '#3b3456');
      const scr = at(new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.5, 1.7), M.get('#1e1b4b', { e: '#A855F7', ei: 1.6 })), hx - 0.32, 1.0, hz);
      scr.rotation.z = 0.35;
      this.group.add(helm, scr);
      this.mossyTex = new THREE.TextureLoader().load(spriteUrl);
      this.mossyTex.magFilter = THREE.NearestFilter;
      this.mossyTex.minFilter = THREE.NearestFilter;
      this.mossyTex.colorSpace = THREE.SRGBColorSpace;
      this.mossyTex.repeat.set(1 / 8, 1);
      this.textures.push(this.mossyTex);
      this.mossy = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.mossyTex, transparent: true, alphaTest: 0.3 }));
      this.mossy.scale.setScalar(1.55);
      this.mossy.position.set(cx + 0.05, 1.18, cz);
      this.group.add(this.mossy);
      const cap = at(new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.26, 0.14, 16), M.get('#1f1b2e')), cx + 0.05, 1.75, cz);
      const capBrim = at(new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.03, 16), M.get('#1f1b2e')), cx + 0.05, 1.69, cz);
      const badge = at(new THREE.Mesh(new THREE.SphereGeometry(0.05, 8, 6), M.get('#FBBF24', { e: '#FBBF24', ei: 1.5 })), cx + 0.25, 1.76, cz + 0.12);
      this.mossyHat = new THREE.Group();
      this.mossyHat.add(cap, capBrim, badge);
      this.group.add(this.mossyHat);
    }

    this.buildSpace();
    mergeStatic(
      this.group,
      [this.dishPivot, this.hatchDisc, this.vaultWheel, this.beaconHead, this.mossy, this.mossyHat, this.holoMesh,
        ...this.fans, ...this.reels, ...this.reactorRings],
      (m) => !this.mats.owned.has(m),
    );
  }
  private mossyHat: THREE.Group;


  private boxAt(x: number, z: number, w: number, h: number, d: number, color: string, o: { metal?: number; rough?: number } = {}): THREE.Mesh {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), this.mats.get(color, o));
    m.position.set(x, h / 2, z);
    m.castShadow = true;
    m.receiveShadow = true;
    return m;
  }

  private table(x: number, z: number, w: number, d: number, color: string): THREE.Group {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    const top = new THREE.Mesh(new THREE.BoxGeometry(w, 0.08, d), this.mats.get(color));
    top.position.y = 0.76;
    top.castShadow = true;
    top.receiveShadow = true;
    g.add(top);
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.74, 0.07), this.mats.get('#4b4563'));
      leg.position.set(sx * (w / 2 - 0.08), 0.37, sz * (d / 2 - 0.08));
      g.add(leg);
    }
    return g;
  }

  private console(x: number, z: number, rotY: number, accent: string, own = false): THREE.MeshStandardMaterial {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.rotation.y = rotY;
    const desk = new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.72, 0.55), this.mats.get('#d6d1e6'));
    desk.position.y = 0.36;
    desk.castShadow = true;
    desk.receiveShadow = true;
    const kb = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.04, 0.2), this.mats.get('#2a2540', { e: accent, ei: 0.4 }));
    kb.position.set(0, 0.74, -0.12);
    const stand = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.3, 0.08), this.mats.get('#4b4563'));
    stand.position.set(0, 0.87, 0.12);
    const mon = new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.5, 0.07), this.mats.get('#2a2540'));
    mon.position.set(0, 1.18, 0.14);
    mon.castShadow = true;
    const scrMat = own ? this.mats.own('#120d22', accent, 1.4) : this.mats.get('#120d22', { e: accent, ei: 1.3 });
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.76, 0.42), scrMat);
    scr.position.set(0, 1.18, 0.1);
    scr.rotation.y = Math.PI;
    const led = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.05, 0.02), this.mats.get('#120d22', { e: accent, ei: 1.8 }));
    led.position.set(0, 1.35, 0.18);
    g.add(desk, kb, stand, mon, scr, led);
    this.group.add(g);
    return scrMat;
  }

  private wallScreen(p: V2, w: number, h: number, y: number, tex: THREE.Texture, accent: string): void {
    const [x, z] = p;
    const frame = new THREE.Mesh(new THREE.BoxGeometry(w + 0.16, h + 0.16, 0.1), this.mats.get('#2a2540'));
    frame.position.set(x, y, z + 0.06);
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, toneMapped: false }));
    scr.position.set(x, y, z + 0.115);
    const trim = new THREE.Mesh(new THREE.BoxGeometry(w + 0.16, 0.05, 0.12), this.mats.get(accent, { e: accent, ei: 1.5 }));
    trim.position.set(x, y - h / 2 - 0.1, z + 0.07);
    this.group.add(frame, scr, trim);
  }

  private decorShelf(x: number, z: number, accent: string): void {
    const s = this.boxAt(x, z, 0.9, 1.6, 0.4, '#cbc5dd');
    this.group.add(s);
    for (let i = 0; i < 3; i++) {
      const jar = at(new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.24, 10), this.mats.get('#ffffff', { e: i === 1 ? '#22C55E' : accent, ei: 0.9 })), x - 0.28 + i * 0.28, 1.72, z + 0.02);
      this.group.add(jar);
    }
  }

  private buildHull(): void {
    const shape = new THREE.Shape();
    const { x0, x1, z0, z1, noseX, bridgeX1, bridgeZ } = SHIP;
    shape.moveTo(x0, -z0);
    shape.lineTo(x1, -z0);
    shape.lineTo(x1, bridgeZ);
    shape.lineTo(bridgeX1, bridgeZ);
    shape.lineTo(noseX, 0);
    shape.lineTo(bridgeX1, -bridgeZ);
    shape.lineTo(x1, -bridgeZ);
    shape.lineTo(x1, -z1);
    shape.lineTo(x0, -z1);
    shape.closePath();
    const mk = (depth: number, color: string, y: number, scale: number, e?: string, ei = 0) => {
      const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelSize: 0.12, bevelThickness: 0.1, bevelSegments: 2 });
      const m = new THREE.Mesh(g, this.mats.get(color, { e, ei, metal: 0.35, rough: 0.55 }));
      m.rotation.x = -Math.PI / 2;
      m.position.y = y;
      m.scale.set(scale, scale, 1);
      m.receiveShadow = true;
      return m;
    };
    this.group.add(
      mk(0.55, '#8d86a8', -0.58, 1),
      mk(0.06, '#A855F7', -0.66, 1.012, '#A855F7', 2.2),
      mk(0.45, '#5b5578', -1.15, 0.97),
    );
  }

  private buildFloors(): void {
    const floor = (x0: number, x1: number, z0: number, z1: number, color: string, room: RoomId | null) => {
      const w = x1 - x0, d = z1 - z0;
      const tex = this.tiles.clone();
      tex.repeat.set(w / 1.2, d / 1.2);
      tex.needsUpdate = true;
      this.textures.push(tex);
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, 0.06, d), new THREE.MeshStandardMaterial({ color, map: tex, roughness: 0.85, metalness: 0.05 }));
      m.position.set((x0 + x1) / 2, 0, (z0 + z1) / 2);
      m.receiveShadow = true;
      m.userData.room = room;
      this.group.add(m);
      if (room) this.roomFloors.push(m);
    };
    for (const r of ROOMS) {
      if (r.id === 'bridge') continue;
      floor(r.x0, r.x1, r.z0, r.z1, r.floor, r.id);
    }
    floor(SHIP.x0, SHIP.x1 + 0.9, -1, 1, '#34304a', null);
    const b = ROOM.bridge;
    floor(b.x0, b.x1, b.z0, b.z1, b.floor, 'bridge');
    const wedge = new THREE.Shape();
    wedge.moveTo(SHIP.bridgeX1, SHIP.bridgeZ);
    wedge.lineTo(SHIP.noseX - 0.2, 0);
    wedge.lineTo(SHIP.bridgeX1, -SHIP.bridgeZ);
    wedge.closePath();
    const wm = new THREE.Mesh(new THREE.ExtrudeGeometry(wedge, { depth: 0.06, bevelEnabled: false }), this.mats.get(b.floor));
    wm.rotation.x = -Math.PI / 2;
    wm.position.y = -0.03;
    wm.receiveShadow = true;
    this.group.add(wm);
    for (let x = SHIP.x0 + 0.8; x < SHIP.x1; x += 1.2) {
      for (const z of [-0.85, 0.85]) {
        this.group.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.02, 0.07), this.mats.get('#A855F7', { e: '#C084FC', ei: 1.4 })), x, 0.04, z));
      }
    }
  }

  private wall(x0: number, z0: number, x1: number, z1: number, h: number, color: string, t = 0.18): void {
    const len = Math.hypot(x1 - x0, z1 - z0);
    if (len < 0.01) return;
    const m = new THREE.Mesh(new THREE.BoxGeometry(len, h, t), this.mats.get(color, { rough: 0.7 }));
    m.position.set((x0 + x1) / 2, h / 2, (z0 + z1) / 2);
    m.rotation.y = -Math.atan2(z1 - z0, x1 - x0);
    m.castShadow = true;
    m.receiveShadow = true;
    this.group.add(m);
    if (h <= PART_H + 0.01) {
      const cap = new THREE.Mesh(new THREE.BoxGeometry(len, 0.04, t + 0.04), this.mats.get('#efeaff'));
      cap.position.set(m.position.x, h + 0.02, m.position.z);
      cap.rotation.y = m.rotation.y;
      this.group.add(cap);
    }
  }

  private wallWithDoors(z: number, x0: number, x1: number, doors: number[], h: number, color: string): void {
    let cur = x0;
    for (const d of doors) {
      this.wall(cur, z, d - DOOR_W / 2, z, h, color);
      cur = d + DOOR_W / 2;
      for (const s of [-1, 1]) {
        const post = new THREE.Mesh(new THREE.BoxGeometry(0.16, 1.15, 0.26), this.mats.get('#efeaff'));
        post.position.set(d + s * (DOOR_W / 2 + 0.02), 0.575, z);
        post.castShadow = true;
        const lamp = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.1, 0.28), this.mats.get('#A855F7', { e: '#C084FC', ei: 2 }));
        lamp.position.set(post.position.x, 1.2, z);
        this.group.add(post, lamp);
      }
    }
    this.wall(cur, z, x1, z, h, color);
  }

  private buildWalls(): void {
    const tall = '#c3bcd9';
    const low = '#aca4c8';
    const { x0, x1, z0, z1 } = SHIP;
    this.wall(x0 - 0.1, z0 - 0.1, x1 + 0.1, z0 - 0.1, WALL_H, tall, 0.22);
    this.wall(x0 - 0.1, z0 - 0.1, x0 - 0.1, z1 + 0.1, WALL_H, tall, 0.22);
    for (const r of ROOMS) {
      if (r.cz > -1 || r.id === 'bridge') continue;
      this.group.add(at(new THREE.Mesh(new THREE.BoxGeometry(r.x1 - r.x0 - 0.3, 0.08, 0.05), this.mats.get(r.accent, { e: r.accent, ei: 1.8 })), r.cx, WALL_H - 0.18, z0 + 0.02));
    }
    for (const z of [2.2, 5.2]) {
      const p = at(new THREE.Mesh(new THREE.CircleGeometry(0.34, 20), this.mats.get('#0b0920', { e: '#312e81', ei: 0.8 })), x0 + 0.02, 1.5, z);
      p.rotation.y = Math.PI / 2;
      const rim = at(new THREE.Mesh(new THREE.TorusGeometry(0.36, 0.05, 8, 20), this.mats.get('#a8a2bf', { metal: 0.5 })), x0 + 0.03, 1.5, z);
      rim.rotation.y = Math.PI / 2;
      this.group.add(p, rim);
    }
    this.group.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.08, z1 - 1.3), this.mats.get('#2DD4BF', { e: '#2DD4BF', ei: 1.8 })), x0 + 0.02, WALL_H - 0.18, (1 + z1) / 2));
    this.group.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.08, 1.8), this.mats.get('#A855F7', { e: '#A855F7', ei: 1.8 })), x0 + 0.02, WALL_H - 0.18, 0));
    this.wall(x0 - 0.1, z1 + 0.1, x1 + 0.1, z1 + 0.1, RIM_H, low);
    this.wall(x1 + 0.1, z0, x1 + 0.1, -SHIP.bridgeZ, RIM_H, low);
    this.wall(x1 + 0.1, SHIP.bridgeZ, x1 + 0.1, z1, RIM_H, low);
    this.wallWithDoors(-1, x0, x1, [-6.4, 0, 6.4], PART_H, low);
    this.wallWithDoors(1, x0, x1, [-6.4, 0, 6.4], PART_H, low);
    for (const x of [-3.2, 3.2]) {
      this.wall(x, z0, x, -1, PART_H, low);
      this.wall(x, 1, x, z1, PART_H, low);
    }
    this.wall(x1, -SHIP.bridgeZ - 0.05, SHIP.bridgeX1, -SHIP.bridgeZ - 0.05, 1.0, tall);
    const glass = this.mats.get('#67e8f9', { e: '#22d3ee', ei: 1.2, rough: 0.2 });
    const nose: [number, number][] = [[SHIP.bridgeX1, -SHIP.bridgeZ], [SHIP.noseX - 0.1, 0], [SHIP.bridgeX1, SHIP.bridgeZ], [x1, SHIP.bridgeZ]];
    for (let i = 0; i < nose.length - 1; i++) {
      const [ax, az] = nose[i];
      const [bx, bz] = nose[i + 1];
      this.wall(ax, az, bx, bz, RIM_H, low);
      const len = Math.hypot(bx - ax, bz - az);
      const g = new THREE.Mesh(new THREE.BoxGeometry(len, 0.06, 0.12), glass);
      g.position.set((ax + bx) / 2, RIM_H + 0.05, (az + bz) / 2);
      g.rotation.y = -Math.atan2(bz - az, bx - ax);
      this.group.add(g);
    }
  }

  private buildSpace(): void {
    const N = 2600;
    const pos = new Float32Array(N * 3);
    const size = new Float32Array(N);
    const tint = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 160;
      pos[i * 3 + 1] = -14 - Math.random() * 40;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 160;
      size[i] = Math.random() < 0.08 ? 2.6 + Math.random() * 1.6 : 0.9 + Math.random() * 1.3;
      tint[i] = Math.random();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('size', new THREE.BufferAttribute(size, 1));
    g.setAttribute('tint', new THREE.BufferAttribute(tint, 1));
    this.starMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uPx: { value: 1 } },
      vertexShader: `
        attribute float size; attribute float tint;
        uniform float uTime; uniform float uPx;
        varying float vT; varying float vA;
        void main() {
          vec3 p = position;
          p.x = mod(p.x + 80.0 - uTime * (0.6 + tint * 0.9), 160.0) - 80.0;
          vT = tint;
          vA = 0.55 + 0.45 * sin(uTime * (1.0 + tint * 3.0) + tint * 40.0);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
          gl_PointSize = size * uPx;
        }`,
      fragmentShader: `
        varying float vT; varying float vA;
        void main() {
          vec2 c = gl_PointCoord - 0.5;
          float d = length(c);
          float a = smoothstep(0.5, 0.0, d);
          vec3 col = mix(vec3(0.75, 0.8, 1.0), vec3(1.0, 0.75, 0.95), vT);
          gl_FragColor = vec4(col * a * vA, a * vA);
        }`,
    });
    this.stars = new THREE.Points(g, this.starMat);
    this.stars.frustumCulled = false;
    this.space.add(this.stars);

    for (const [x, y, z, c, s, o] of [
      [-30, -40, -10, '#7C3AED', 60, 0.22], [25, -45, 20, '#DB2777', 55, 0.16], [5, -50, -35, '#4F46E5', 70, 0.2],
    ] as const) {
      const neb = this.kit.glow(c, s, o);
      neb.position.set(x, y, z);
      this.space.add(neb);
    }

    const planet = new THREE.Mesh(
      new THREE.SphereGeometry(7, 48, 32),
      new THREE.ShaderMaterial({
        uniforms: {},
        vertexShader: `
          varying vec3 vN; varying vec3 vP;
          void main() { vN = normalize(normalMatrix * normal); vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
        fragmentShader: `
          varying vec3 vN; varying vec3 vP;
          void main() {
            vec3 L = normalize(vec3(0.6, 0.7, 0.3));
            float d = max(dot(vN, L), 0.0);
            float bands = 0.5 + 0.5 * sin(vP.y * 0.9 + sin(vP.x * 0.35) * 1.6);
            vec3 a = mix(vec3(0.33, 0.16, 0.55), vec3(0.85, 0.35, 0.65), bands * 0.6);
            vec3 col = a * (0.15 + 0.95 * d);
            float rim = pow(1.0 - max(vN.z, 0.0), 2.5);
            col += vec3(0.75, 0.45, 1.0) * rim * 0.9;
            gl_FragColor = vec4(col, 1.0);
          }`,
      }),
    );
    planet.position.set(-9.3, -34, -34.5);
    planet.rotation.z = 0.4;
    this.space.add(planet);
    const atmo = this.kit.glow('#C084FC', 22, 0.4);
    atmo.position.copy(planet.position);
    this.space.add(atmo);

    const s = this.station;
    s.position.copy(this.kalshiPos);
    const ringMat = this.mats.get('#e2e8f0', { metal: 0.6, rough: 0.3 });
    const ring = new THREE.Mesh(new THREE.TorusGeometry(1.8, 0.22, 12, 40), ringMat);
    ring.rotation.x = Math.PI / 2;
    const hub = new THREE.Mesh(new THREE.SphereGeometry(0.75, 24, 16), this.mats.get('#cbd5e1', { metal: 0.5, rough: 0.35 }));
    this.stationLights = this.mats.own('#064e3b', '#10D9A0', 1.8);
    const band = new THREE.Mesh(new THREE.TorusGeometry(1.8, 0.09, 8, 40), this.stationLights);
    band.rotation.x = Math.PI / 2;
    band.position.y = 0.2;
    const core = new THREE.Mesh(new THREE.SphereGeometry(0.4, 16, 12), this.stationLights);
    core.position.y = 0.55;
    s.add(ring, hub, band, core);
    for (let i = 0; i < 4; i++) {
      const sp = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 3.6, 6), ringMat);
      sp.rotation.z = Math.PI / 2;
      sp.rotation.y = (i * Math.PI) / 4;
      s.add(sp);
    }
    const halo = this.kit.glow('#10D9A0', 6, 0.35);
    s.add(halo);
    this.space.add(s);
  }


  private drawRadar(g: CanvasRenderingContext2D, w: number, h: number, t: number): void {
    g.fillStyle = '#0d0820';
    g.fillRect(0, 0, w, h);
    const cx = w * 0.32, cy = h * 0.52, R = h * 0.42;
    g.strokeStyle = 'rgba(168,85,247,0.45)';
    g.lineWidth = 2;
    for (const k of [0.33, 0.66, 1]) {
      g.beginPath();
      g.arc(cx, cy, R * k, 0, Math.PI * 2);
      g.stroke();
    }
    const a = t * 1.8;
    const grd = g.createConicGradient(a - 0.9, cx, cy);
    grd.addColorStop(0, 'rgba(168,85,247,0)');
    grd.addColorStop(0.14, 'rgba(192,132,252,0.55)');
    grd.addColorStop(0.15, 'rgba(168,85,247,0)');
    g.fillStyle = grd;
    g.beginPath();
    g.arc(cx, cy, R, 0, Math.PI * 2);
    g.fill();
    for (const b of this.blips) {
      const al = Math.max(0, 1 - b.age / 4);
      g.fillStyle = b.color;
      g.globalAlpha = al;
      g.beginPath();
      g.arc(cx + Math.cos(b.a) * b.r * R, cy + Math.sin(b.a) * b.r * R, 7 + (1 - al) * 5, 0, Math.PI * 2);
      g.fill();
    }
    g.globalAlpha = 1;
    const x0 = w * 0.64;
    for (let i = 0; i < 6; i++) {
      const v = 0.3 + 0.7 * Math.abs(Math.sin(t * (1.3 + i * 0.4) + i));
      g.fillStyle = i % 2 ? '#EC4899' : '#A855F7';
      g.fillRect(x0, 22 + i * 30, (w * 0.32) * v * (0.6 + this.dishPing * 0.4), 16);
    }
    if (this.dishPing > 0.05) {
      g.fillStyle = `rgba(236,72,153,${this.dishPing * 0.25})`;
      g.fillRect(0, 0, w, h);
    }
  }

  private drawHolo(g: CanvasRenderingContext2D, w: number, h: number): void {
    g.clearRect(0, 0, w, h);
    g.fillStyle = 'rgba(45,212,191,0.10)';
    g.fillRect(4, 4, w - 8, h - 8);
    g.strokeStyle = 'rgba(45,212,191,0.8)';
    g.lineWidth = 5;
    g.strokeRect(4, 4, w - 8, h - 8);
    if (this.holoSeries.length < 2) {
      g.fillStyle = '#5EEAD4';
      g.font = '700 30px "Chakra Petch", sans-serif';
      g.fillText(this.holoLabel, 16, 38);
      g.font = '600 20px "JetBrains Mono", monospace';
      g.fillText(this.holoSub, 16, h / 2 + 20);
      return;
    }
    g.strokeStyle = 'rgba(45,212,191,0.18)';
    for (let i = 1; i < 4; i++) {
      g.beginPath();
      g.moveTo(4, (h * i) / 4);
      g.lineTo(w - 4, (h * i) / 4);
      g.stroke();
    }
    const s = this.holoSeries;
    if (s.length > 1) {
      let lo = Infinity, hi = -Infinity;
      for (const v of s) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      const span = Math.max(1e-6, hi - lo);
      const n = Math.max(2, Math.floor(s.length * this.holoProgress));
      const col = this.holoPass === null ? '#5EEAD4' : this.holoPass ? '#4ADE80' : '#F87171';
      g.strokeStyle = col;
      g.lineWidth = 9;
      g.lineJoin = 'round';
      g.beginPath();
      for (let i = 0; i < n; i++) {
        const x = 14 + (i / (s.length - 1)) * (w - 28);
        const y = h - 18 - ((s[i] - lo) / span) * (h - 50);
        if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
      }
      g.stroke();
      if (this.holoRunning) {
        const x = 14 + ((n - 1) / (s.length - 1)) * (w - 28);
        g.fillStyle = 'rgba(94,234,212,0.25)';
        g.fillRect(x - 3, 8, 6, h - 16);
      }
    }
    g.fillStyle = '#99F6E4';
    g.font = '700 30px "Chakra Petch", sans-serif';
    g.fillText(this.holoLabel, 16, 38);
  }

  private drawBoard(g: CanvasRenderingContext2D, w: number, h: number): void {
    g.fillStyle = '#12091c';
    g.fillRect(0, 0, w, h);
    g.fillStyle = '#EC4899';
    g.font = '700 22px "Chakra Petch", sans-serif';
    g.fillText('ORDERS →  KALSHI', 12, 28);
    g.font = '500 19px "JetBrains Mono", monospace';
    this.boardLines.slice(-5).forEach((l, i, arr) => {
      g.fillStyle = l.color;
      g.globalAlpha = 0.45 + 0.55 * ((i + 1) / arr.length);
      g.fillText(l.text, 12, 56 + i * 24);
    });
    g.globalAlpha = 1;
  }


  ping(color: string): void {
    this.dishPing = 1;
    this.dishTip.emissive.set(color);
    this.blips.push({ a: Math.random() * Math.PI * 2, r: 0.25 + Math.random() * 0.7, color, age: 0 });
    if (this.blips.length > 12) this.blips.shift();
  }

  printFlash(): void { this.printerFlash = 1; }
  anvilHit(): void { this.anvilFlash = 1; }
  binPuff(): void { this.binFlash = 1; }
  fireTube(): void { this.tubeFlash = 1; }
  hatchBlink(): void { this.hatchFlash = 1; }
  stationHit(): void { this.stationFlash = 1; }
  vaultDeposit(big = false): void { this.vaultSpin = big ? 6 : 1.6; this.vaultFlash = big ? 2 : 1; }
  setOptimizing(on: boolean): void { this.optimizing = on; this.fanTarget = on ? 16 : 1.2; }

  pushOrder(text: string, color: string): void {
    this.boardLines.push({ text, color });
    if (this.boardLines.length > 8) this.boardLines.shift();
  }

  setHoloIdle(label: string, sub: string): void {
    if (this.holoRunning) return;
    this.holoSeries = [];
    this.holoPass = null;
    this.holoLabel = label;
    this.holoSub = sub;
    this.holo.update(0, 0, true);
  }

  startBacktest(series: number[], label: string, sub = ''): void {
    this.holoSeries = series;
    this.holoSub = sub;
    this.holoProgress = 0;
    this.holoPass = null;
    this.holoRunning = true;
    this.holoLabel = label;
    this.lamp.emissive.set('#5EEAD4');
    this.lamp.emissiveIntensity = 1;
  }

  finishBacktest(pass: boolean | null, label: string): void {
    this.holoProgress = 1;
    this.holoRunning = false;
    this.holoPass = pass;
    this.holoLabel = label;
    this.lamp.emissive.set(pass === null ? '#5EEAD4' : pass ? '#22C55E' : '#EF4444');
    this.lamp.emissiveIntensity = 3;
    this.holo.update(0, 0, true);
  }

  get backtestRunning(): boolean { return this.holoRunning; }

  setPixelScale(s: number): void {
    this.starMat.uniforms.uPx.value = s;
  }

  update(dt: number, t: number): void {
    this.starMat.uniforms.uTime.value = t;

    this.dishPivot.rotation.y = Math.sin(t * 0.35) * 1.1;
    this.dishPing = Math.max(0, this.dishPing - dt * 1.6);
    this.dishTip.emissiveIntensity = 1.2 + this.dishPing * 6 + Math.max(0, Math.sin(t * 5)) * 0.8;
    for (const b of this.blips) b.age += dt;
    this.labScreen.update(dt, t);
    this.printerFlash = Math.max(0, this.printerFlash - dt * 2);
    this.printerLight.emissiveIntensity = 0.6 + this.printerFlash * 4;

    const flick = 0.85 + Math.sin(t * 13) * 0.08 + Math.sin(t * 7.3) * 0.07;
    this.anvilFlash = Math.max(0, this.anvilFlash - dt * 4);
    this.furnaceMouth.emissiveIntensity = 2.4 * flick + this.anvilFlash;
    this.furnaceLight.intensity = 5 * flick + this.anvilFlash * 5;
    this.anvilTop.emissiveIntensity = this.anvilFlash * 2.5;

    if (this.holoRunning) this.holoProgress = Math.min(1, this.holoProgress + dt / 2.4);
    this.holo.update(dt, t, false);
    for (const r of this.reels) r.rotation.z -= dt * (this.holoRunning ? 9 : 0.4);
    this.lamp.emissiveIntensity = Math.max(this.holoRunning ? 1 + Math.sin(t * 14) * 0.6 : 0.5, this.lamp.emissiveIntensity - dt * 0.6);
    this.binFlash = Math.max(0, this.binFlash - dt * 1.5);
    this.binRing.emissiveIntensity = 0.6 + this.binFlash * 4;
    (this.holoMesh.material as THREE.MeshBasicMaterial).opacity = 0.8 + Math.sin(t * 9) * 0.06;

    this.tubeFlash = Math.max(0, this.tubeFlash - dt * 3);
    this.tubeRing.emissiveIntensity = 1.2 + this.tubeFlash * 5;
    this.hatchFlash = Math.max(0, this.hatchFlash - dt * 1.4);
    this.hatchLight.emissiveIntensity = 0.4 + this.hatchFlash * 5 * (0.6 + 0.4 * Math.sin(t * 20));
    this.hatchDisc.rotation.z += dt * this.hatchFlash * 6;
    this.termScreens.forEach((m, i) => { m.emissiveIntensity = 1.1 + Math.sin(t * (6 + i * 3)) * 0.25 + this.tubeFlash * 0.8; });
    this.board.update(dt, t);

    this.vaultSpin = Math.max(0, this.vaultSpin - dt * 1.2);
    this.vaultWheel.rotation.z -= dt * this.vaultSpin * 2.2;
    this.vaultFlash = Math.max(0, this.vaultFlash - dt * 1.2);
    this.vaultGlow.intensity = 1.2 + this.vaultFlash * 2.5;
    this.alarm = Math.max(0, this.alarm - dt);
    const al = Math.min(1, this.alarm);
    this.beaconHead.rotation.y += dt * (al > 0 ? 9 : 0.4);
    this.beaconMat.emissiveIntensity = 0.3 + al * (3 + Math.sin(t * 18) * 1.5);
    for (const b of this.beaconBeams) (b.material as THREE.MeshBasicMaterial).opacity = al * 0.22;
    this.alarmLight.intensity = al * (10 + Math.sin(t * 18) * 6);

    this.fanSpeed += (this.fanTarget - this.fanSpeed) * Math.min(1, dt * 1.4);
    for (const f of this.fans) f.rotation.z -= dt * this.fanSpeed;
    const boost = (this.fanSpeed - 1.2) / 14.8;
    this.reactorMat.emissiveIntensity = 1.4 + Math.sin(t * 3) * 0.3 + boost * 2.5;
    this.reactorLight.intensity = 3.5 + boost * 8;
    this.reactorRings.forEach((r, i) => {
      r.position.y = 0.45 + ((t * (0.35 + boost * 1.6) + i / 3) % 1) * 1.6;
    });
    this.exhaust.forEach((e, i) => {
      const base = i % 2 ? 5.5 : 3.2;
      e.scale.setScalar(base * (1 + boost * 0.5 + Math.sin(t * 17 + i) * 0.06));
    });
    void this.optimizing;

    this.mossyAcc += dt;
    if (this.mossyAcc > 0.9 / 8) {
      this.mossyAcc = 0;
      this.mossyFrame = (this.mossyFrame + 1) % 8;
      this.mossyTex.offset.x = this.mossyFrame / 8;
    }
    this.mossyHop = Math.max(0, this.mossyHop - dt);
    const hop = this.mossyHop > 0 ? Math.abs(Math.sin(this.mossyHop * 12)) * 0.35 : 0;
    this.mossy.position.y = 1.18 + Math.sin(t * 2) * 0.03 + hop;
    this.mossyHat.position.y = this.mossy.position.y - 1.18;

    this.station.rotation.y += dt * 0.25;
    this.station.position.y = this.kalshiPos.y + Math.sin(t * 0.8) * 0.25;
    this.stationFlash = Math.max(0, this.stationFlash - dt * 2.5);
    this.stationLights.emissiveIntensity = 1.6 + this.stationFlash * 5;
  }

  dispose(): void {
    for (const t of this.textures) t.dispose();
  }
}
