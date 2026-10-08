import * as THREE from 'three';


export type Seg = readonly [x0: number, z0: number, x1: number, z1: number];
export type Circle = readonly [x: number, z: number, r: number];

export interface WalkSpace {
  walls: Seg[];
  props: Circle[];
  wallT: number;
  start: { x: number; z: number; yaw: number; pitch?: number };
  eye: number;
  speed: number;
  exits?: Seg[];
}

function segDist(x: number, z: number, [ax, az, bx, bz]: Seg): number {
  const dx = bx - ax, dz = bz - az;
  const len2 = dx * dx + dz * dz || 1e-9;
  const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / len2));
  return Math.hypot(x - (ax + dx * t), z - (az + dz * t));
}

export function exitDistance(x: number, z: number, space: Pick<WalkSpace, 'exits'>): number {
  let best = Infinity;
  for (const s of space.exits ?? []) best = Math.min(best, segDist(x, z, s));
  return best;
}

export function atExit(x: number, z: number, space: Pick<WalkSpace, 'exits' | 'wallT'>): boolean {
  return exitDistance(x, z, space) <= BODY_R + space.wallT / 2 + 0.06;
}

export const BODY_R = 0.28;

export function collide(x: number, z: number, space: Pick<WalkSpace, 'walls' | 'props' | 'wallT'>, r = BODY_R): [number, number] {
  for (let pass = 0; pass < 3; pass++) {
    let moved = false;
    for (const [ax, az, bx, bz] of space.walls) {
      const dx = bx - ax, dz = bz - az;
      const len2 = dx * dx + dz * dz || 1e-9;
      const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / len2));
      const px = ax + dx * t, pz = az + dz * t;
      const ox = x - px, oz = z - pz;
      const d = Math.hypot(ox, oz);
      const min = r + space.wallT / 2;
      if (d < min) {
        const [nx, nz] = d > 1e-6 ? [ox / d, oz / d] : [-dz / Math.sqrt(len2), dx / Math.sqrt(len2)];
        x = px + nx * min;
        z = pz + nz * min;
        moved = true;
      }
    }
    for (const [cx, cz, cr] of space.props) {
      const ox = x - cx, oz = z - cz;
      const d = Math.hypot(ox, oz);
      const min = r + cr;
      if (d < min) {
        const [nx, nz] = d > 1e-6 ? [ox / d, oz / d] : [1, 0];
        x = cx + nx * min;
        z = cz + nz * min;
        moved = true;
      }
    }
    if (!moved) break;
  }
  return [x, z];
}

export function step(x: number, z: number, dx: number, dz: number, space: Pick<WalkSpace, 'walls' | 'props' | 'wallT'>): [number, number] {
  const dist = Math.hypot(dx, dz);
  const n = Math.max(1, Math.ceil(dist / (BODY_R * 0.5)));
  for (let i = 0; i < n; i++) [x, z] = collide(x + dx / n, z + dz / n, space);
  return [x, z];
}

type Key = 'f' | 'b' | 'l' | 'r' | 'tl' | 'tr';
const MOVE_KEYS: Record<string, Key> = {
  KeyW: 'f', ArrowUp: 'f', KeyS: 'b', ArrowDown: 'b',
  KeyA: 'l', KeyD: 'r',
  ArrowLeft: 'tl', ArrowRight: 'tr',
};
const TURN_RATE = 1.1;

export class Walker {
  x = 0;
  z = 0;
  yaw = 0;
  pitch = 0;
  locked = false;
  fov = 68;
  exited = false;
  frozen = false;
  onKey: ((code: string) => boolean) | null = null;
  onClick: ((clientX: number, clientY: number) => void) | null = null;
  private vx = 0;
  private vz = 0;
  private bob = 0;
  private keys = new Set<Key>();
  private run = false;
  private dragLook: { x: number; y: number; yaw: number; pitch: number } | null = null;

  constructor(public space: WalkSpace) {
    this.reset();
  }

  reset(): void {
    const s = this.space.start;
    [this.x, this.z] = collide(s.x, s.z, this.space);
    this.yaw = s.yaw;
    this.pitch = s.pitch ?? 0;
    this.vx = this.vz = 0;
    this.fov = 68;
    this.exited = false;
    this.keys.clear();
  }

  get exitDist(): number {
    return exitDistance(this.x, this.z, this.space);
  }

  attach(el: HTMLCanvasElement): () => void {
    const onKey = (down: boolean) => (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.key === 'Shift') this.run = down;
      if (down && this.onKey?.(e.code)) { e.preventDefault(); return; }
      if (e.code === 'Space') { e.preventDefault(); return; }
      const k = MOVE_KEYS[e.code];
      if (!k) return;
      e.preventDefault();
      if (down) this.keys.add(k);
      else this.keys.delete(k);
    };
    const kd = onKey(true), ku = onKey(false);
    const blur = () => { this.keys.clear(); this.run = false; };
    const look = (mx: number, my: number) => {
      if (this.frozen) return;
      this.yaw -= mx * 0.0022;
      this.pitch = THREE.MathUtils.clamp(this.pitch - my * 0.0022, -1.2, 1.2);
    };
    const move = (e: PointerEvent) => {
      if (document.pointerLockElement === el) { look(e.movementX, e.movementY); return; }
      const d = this.dragLook;
      if (!d || this.frozen) return;
      this.yaw = d.yaw - (e.clientX - d.x) * 0.0035;
      this.pitch = THREE.MathUtils.clamp(d.pitch - (e.clientY - d.y) * 0.0035, -1.2, 1.2);
    };
    const down = (e: PointerEvent) => {
      if (e.button !== 0 || document.pointerLockElement === el) return;
      if (this.frozen) { this.onClick?.(e.clientX, e.clientY); return; }
      this.dragLook = { x: e.clientX, y: e.clientY, yaw: this.yaw, pitch: this.pitch };
      try {
        const p = el.requestPointerLock() as unknown;
        if (p instanceof Promise) p.catch(() => {});
      } catch {}
    };
    const up = () => { this.dragLook = null; };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      this.fov = THREE.MathUtils.clamp(this.fov * Math.exp(e.deltaY * 0.001), 35, 85);
    };
    const lockChange = () => { this.locked = document.pointerLockElement === el; };
    el.addEventListener('pointerdown', down);
    el.addEventListener('pointermove', move);
    el.addEventListener('wheel', wheel, { passive: false });
    window.addEventListener('pointerup', up);
    window.addEventListener('keydown', kd);
    window.addEventListener('keyup', ku);
    window.addEventListener('blur', blur);
    document.addEventListener('pointerlockchange', lockChange);
    return () => {
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('pointermove', move);
      el.removeEventListener('wheel', wheel);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('keydown', kd);
      window.removeEventListener('keyup', ku);
      window.removeEventListener('blur', blur);
      document.removeEventListener('pointerlockchange', lockChange);
      if (document.pointerLockElement === el) document.exitPointerLock();
      this.locked = false;
      blur();
    };
  }

  update(dt: number): void {
    if (this.frozen) {
      this.vx = this.vz = 0;
      return;
    }
    this.yaw += ((this.keys.has('tl') ? 1 : 0) - (this.keys.has('tr') ? 1 : 0)) * TURN_RATE * dt;
    const fwd = (this.keys.has('f') ? 1 : 0) - (this.keys.has('b') ? 1 : 0);
    const side = (this.keys.has('r') ? 1 : 0) - (this.keys.has('l') ? 1 : 0);
    const sy = Math.sin(this.yaw), cy = Math.cos(this.yaw);
    let wx = -sy * fwd + cy * side;
    let wz = -cy * fwd - sy * side;
    const len = Math.hypot(wx, wz);
    if (len > 0) { wx /= len; wz /= len; }
    const speed = this.space.speed * (this.run ? 2 : 1);
    const k = 1 - Math.exp(-10 * dt);
    this.vx += (wx * speed - this.vx) * k;
    this.vz += (wz * speed - this.vz) * k;
    [this.x, this.z] = step(this.x, this.z, this.vx * dt, this.vz * dt, this.space);
    if (len > 0 && atExit(this.x, this.z, this.space)) this.exited = true;
    const v = Math.hypot(this.vx, this.vz);
    this.bob += dt * v * 2.1;
  }

  apply(cam: THREE.PerspectiveCamera): void {
    const v = Math.min(1, Math.hypot(this.vx, this.vz) / this.space.speed);
    const bobY = Math.sin(this.bob * 2) * 0.035 * v;
    const bobX = Math.cos(this.bob) * 0.02 * v;
    cam.position.set(this.x + Math.cos(this.yaw) * bobX, this.space.eye + bobY, this.z - Math.sin(this.yaw) * bobX);
    cam.rotation.set(this.pitch, this.yaw, 0, 'YXZ');
    cam.updateMatrixWorld();
  }
}

export function visibleFrom(cam: THREE.Camera, p: THREE.Vector3, maxDist: number): boolean {
  const toP = p.clone().sub(cam.position);
  if (toP.lengthSq() > maxDist * maxDist) return false;
  const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(cam.quaternion);
  return toP.dot(fwd) > 0.3;
}
