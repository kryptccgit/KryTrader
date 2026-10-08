import * as THREE from 'three';


export function makeGlowTexture(): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d')!;
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.25, 'rgba(255,255,255,0.55)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export class ItemKit {
  readonly glowTex = makeGlowTexture();
  readonly g = {
    card: new THREE.BoxGeometry(0.36, 0.05, 0.48),
    chip: new THREE.CylinderGeometry(0.2, 0.2, 0.1, 6),
    capsule: new THREE.CapsuleGeometry(0.15, 0.32, 6, 12),
    band: new THREE.CylinderGeometry(0.155, 0.155, 0.08, 12),
    bag: new THREE.SphereGeometry(0.24, 16, 12),
    tie: new THREE.CylinderGeometry(0.06, 0.1, 0.1, 10),
    tablet: new THREE.BoxGeometry(0.34, 0.04, 0.26),
  };
  private mats = new Map<string, THREE.Material>();

  private mat(color: string, emissive: string, ei: number, metal = 0.1, rough = 0.5): THREE.Material {
    const k = `${color}|${emissive}|${ei}|${metal}|${rough}`;
    let m = this.mats.get(k);
    if (!m) {
      m = new THREE.MeshStandardMaterial({ color, emissive, emissiveIntensity: ei, metalness: metal, roughness: rough });
      this.mats.set(k, m);
    }
    return m;
  }

  glow(color: string, size: number, opacity = 0.75): THREE.Sprite {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.glowTex, color, transparent: true, opacity,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    s.scale.setScalar(size);
    return s;
  }

  card(color: string): THREE.Group {
    const g = new THREE.Group();
    const m = new THREE.Mesh(this.g.card, this.mat('#1b1530', color, 2.4));
    m.castShadow = true;
    m.rotation.x = -0.35;
    g.add(m, this.glow(color, 0.95));
    return g;
  }

  chip(color: string): THREE.Group {
    const g = new THREE.Group();
    const m = new THREE.Mesh(this.g.chip, this.mat(color, color, 1.6, 0.3, 0.35));
    m.castShadow = true;
    g.add(m, this.glow(color, 0.9));
    g.userData.core = m;
    return g;
  }

  setChipColor(chip: THREE.Object3D, color: string): void {
    const core = chip.userData.core as THREE.Mesh | undefined;
    if (core) core.material = this.mat(color, color, 1.6, 0.3, 0.35);
    chip.children.forEach((c) => {
      if (c instanceof THREE.Sprite) (c.material as THREE.SpriteMaterial).color.set(color);
    });
  }

  capsule(): THREE.Group {
    const g = new THREE.Group();
    const body = new THREE.Mesh(this.g.capsule, this.mat('#F5F3FF', '#000000', 0, 0.3, 0.3));
    body.rotation.x = Math.PI / 2;
    const band = new THREE.Mesh(this.g.band, this.mat('#EC4899', '#EC4899', 2.5));
    band.rotation.x = Math.PI / 2;
    const tail = this.glow('#EC4899', 1.3, 0.95);
    tail.position.z = -0.4;
    const tail2 = this.glow('#F9A8D4', 0.9, 0.6);
    tail2.position.z = -0.95;
    const tail3 = this.glow('#A855F7', 0.6, 0.4);
    tail3.position.z = -1.45;
    g.add(body, band, tail, tail2, tail3);
    g.scale.setScalar(1.5);
    return g;
  }

  bag(): THREE.Group {
    const g = new THREE.Group();
    const b = new THREE.Mesh(this.g.bag, this.mat('#FBBF24', '#F59E0B', 0.45, 0.55, 0.35));
    b.scale.set(1, 0.9, 1);
    b.castShadow = true;
    const tie = new THREE.Mesh(this.g.tie, this.mat('#B45309', '#000000', 0));
    tie.position.y = 0.23;
    g.add(b, tie, this.glow('#FCD34D', 1.0, 0.6));
    return g;
  }

  tablet(): THREE.Group {
    const g = new THREE.Group();
    const m = new THREE.Mesh(this.g.tablet, this.mat('#0B1220', '#38BDF8', 1.8));
    m.rotation.x = -0.4;
    g.add(m, this.glow('#38BDF8', 0.8));
    return g;
  }
}


interface Flight {
  obj: THREE.Object3D;
  from: THREE.Vector3;
  to: THREE.Vector3;
  arc: number;
  t: number;
  dur: number;
  base: number;
  spin: boolean;
  onArrive?: () => void;
}

export class Flights {
  private list: Flight[] = [];
  private _p = new THREE.Vector3();
  private _q = new THREE.Vector3();
  constructor(private parent: THREE.Object3D) {}

  get count(): number {
    return this.list.length;
  }

  launch(obj: THREE.Object3D, from: THREE.Vector3, to: THREE.Vector3, dur: number, arc: number, onArrive?: () => void, spin = false): void {
    obj.position.copy(from);
    this.parent.add(obj);
    this.list.push({ obj, from: from.clone(), to: to.clone(), arc, t: 0, dur, spin, onArrive, base: obj.scale.x });
  }

  update(dt: number): void {
    for (let i = this.list.length - 1; i >= 0; i--) {
      const f = this.list[i];
      f.t += dt;
      const u = Math.min(1, f.t / f.dur);
      const e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
      this.pos(f, e, this._p);
      this.pos(f, Math.min(1, e + 0.02), this._q);
      f.obj.position.copy(this._p);
      if (f.spin) f.obj.rotation.y += dt * 6;
      else if (this._q.distanceToSquared(this._p) > 1e-8) f.obj.lookAt(this._q);
      const s = u > 0.85 ? Math.max(0.05, 1 - (u - 0.85) / 0.15) : 1;
      f.obj.scale.setScalar(s * f.base);
      if (u >= 1) {
        this.list.splice(i, 1);
        f.obj.removeFromParent();
        f.onArrive?.();
      }
    }
  }

  private pos(f: Flight, e: number, out: THREE.Vector3): void {
    out.lerpVectors(f.from, f.to, e);
    out.y += Math.sin(e * Math.PI) * f.arc;
  }

  clear(): void {
    for (const f of this.list) f.obj.removeFromParent();
    this.list = [];
  }
}


export class Sparks {
  readonly points: THREE.Points;
  private pos: Float32Array;
  private col: Float32Array;
  private vel: Float32Array;
  private life: Float32Array;
  private next = 0;
  private _c = new THREE.Color();
  private mat: THREE.PointsMaterial;

  constructor(tex: THREE.Texture, private n = 360) {
    this.pos = new Float32Array(n * 3).fill(-999);
    this.col = new Float32Array(n * 3);
    this.vel = new Float32Array(n * 3);
    this.life = new Float32Array(n);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(this.col, 3));
    this.mat = new THREE.PointsMaterial({
      size: 10, map: tex, vertexColors: true, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, sizeAttenuation: false,
    });
    this.points = new THREE.Points(g, this.mat);
    this.points.frustumCulled = false;
  }

  setPixelScale(s: number): void {
    this.mat.size = 11 * s;
  }

  burst(x: number, y: number, z: number, color: string, count: number, speed: number, up = 1.5): void {
    this._c.set(color);
    for (let k = 0; k < count; k++) {
      const i = this.next;
      this.next = (this.next + 1) % this.n;
      const a = Math.random() * Math.PI * 2;
      const s = speed * (0.4 + Math.random() * 0.8);
      this.pos[i * 3] = x; this.pos[i * 3 + 1] = y; this.pos[i * 3 + 2] = z;
      this.vel[i * 3] = Math.cos(a) * s;
      this.vel[i * 3 + 1] = up * (0.5 + Math.random());
      this.vel[i * 3 + 2] = Math.sin(a) * s;
      this.life[i] = 0.5 + Math.random() * 0.5;
      this.col[i * 3] = this._c.r; this.col[i * 3 + 1] = this._c.g; this.col[i * 3 + 2] = this._c.b;
    }
  }

  update(dt: number): void {
    let any = false;
    for (let i = 0; i < this.n; i++) {
      if (this.life[i] <= 0) continue;
      any = true;
      this.life[i] -= dt;
      this.vel[i * 3 + 1] -= 6 * dt;
      this.pos[i * 3] += this.vel[i * 3] * dt;
      this.pos[i * 3 + 1] = Math.max(0.03, this.pos[i * 3 + 1] + this.vel[i * 3 + 1] * dt);
      this.pos[i * 3 + 2] += this.vel[i * 3 + 2] * dt;
      const f = Math.max(0, this.life[i] / 0.8);
      this.col[i * 3] *= 0.985; this.col[i * 3 + 1] *= 0.985; this.col[i * 3 + 2] *= 0.985;
      if (this.life[i] <= 0) this.pos[i * 3 + 1] = -999;
      void f;
    }
    if (any) {
      this.points.geometry.attributes.position.needsUpdate = true;
      this.points.geometry.attributes.color.needsUpdate = true;
    }
  }
}


export class CoinPile {
  readonly mesh: THREE.InstancedMesh;
  private slots: THREE.Matrix4[] = [];
  private shown = 0;
  private target = 0;
  private born: number[] = [];
  private _m = new THREE.Matrix4();
  private _p = new THREE.Vector3();
  private _q = new THREE.Quaternion();
  private _s = new THREE.Vector3();
  private _e = new THREE.Euler();
  readonly max: number;

  constructor(x: number, z: number, max = 900) {
    this.max = max;
    const g = new THREE.CylinderGeometry(0.14, 0.14, 0.045, 14);
    const m = new THREE.MeshStandardMaterial({ color: '#FCD34D', metalness: 0.45, roughness: 0.32, emissive: '#B45309', emissiveIntensity: 0.22 });
    this.mesh = new THREE.InstancedMesh(g, m, max);
    this.mesh.castShadow = true;
    this.mesh.receiveShadow = true;
    this.mesh.count = 0;
    this.mesh.position.set(x, 0, z);
    const pts: { x: number; y: number; z: number }[] = [];
    for (let i = 0; i < max; i++) {
      const f = (i + 1) / max;
      const R = 0.3 + 1.0 * Math.pow(f, 0.45);
      const H = 0.22 + 1.45 * Math.pow(f, 0.55);
      const d = R * Math.sqrt(Math.random());
      const a = Math.random() * Math.PI * 2;
      const y = Math.max(0.02, H * (1 - d / R) - Math.random() * 0.06);
      pts.push({ x: Math.cos(a) * d, y, z: Math.sin(a) * d });
    }
    for (const p of pts) {
      this._e.set((Math.random() - 0.5) * 0.7, Math.random() * Math.PI, (Math.random() - 0.5) * 0.7);
      this.slots.push(new THREE.Matrix4().compose(this._p.set(p.x, p.y, p.z), this._q.setFromEuler(this._e), this._s.set(1, 1, 1)));
    }
  }

  get size(): number {
    return this.target;
  }

  add(n: number): void {
    this.target = Math.min(this.max, this.target + n);
  }

  set(n: number): void {
    this.target = Math.min(this.max, n);
    if (this.shown > this.target) {
      this.shown = this.target;
      this.mesh.count = this.shown;
    }
  }

  top(out: THREE.Vector3): THREE.Vector3 {
    const h = this.shown > 0 ? this.slots[this.shown - 1].elements[13] : 0;
    return out.set(this.mesh.position.x, h + 0.15, this.mesh.position.z);
  }

  update(dt: number): void {
    const step = Math.max(1, Math.ceil((this.target - this.shown) / 12));
    for (let k = 0; k < step && this.shown < this.target; k++) {
      this.born[this.shown] = 0;
      this.shown++;
    }
    let dirty = false;
    const lo = Math.max(0, this.shown - 260);
    for (let i = lo; i < this.shown; i++) {
      const b = this.born[i];
      if (b === undefined || b >= 1) {
        if (b !== undefined && b >= 1 && b < 2) {
          this.mesh.setMatrixAt(i, this.slots[i]);
          this.born[i] = 2;
          dirty = true;
        }
        continue;
      }
      const nb = Math.min(1, b + dt * 3.5);
      this.born[i] = nb;
      this._m.copy(this.slots[i]);
      this._m.elements[13] += (1 - nb) * (1 - nb) * 0.9;
      this.mesh.setMatrixAt(i, this._m);
      dirty = true;
    }
    if (this.mesh.count !== this.shown) {
      this.mesh.count = this.shown;
      dirty = true;
    }
    if (dirty) this.mesh.instanceMatrix.needsUpdate = true;
  }
}
