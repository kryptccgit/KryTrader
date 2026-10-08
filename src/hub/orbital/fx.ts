import * as THREE from 'three';


export interface Emit {
  x: number; y: number; z: number;
  vx?: number; vy?: number; vz?: number;
  color: THREE.Color | string;
  size: number;
  life: number;
  drag?: number;
  home?: THREE.Vector3;
}

export class Particles {
  readonly points: THREE.Points;
  private n: number;
  private pos: Float32Array;
  private col: Float32Array;
  private size: Float32Array;
  private alpha: Float32Array;
  private vel: Float32Array;
  private life: Float32Array;
  private max: Float32Array;
  private drag: Float32Array;
  private home: (THREE.Vector3 | null)[];
  private start: Float32Array;
  private baseSize: Float32Array;
  private next = 0;
  private live = 0;
  private mat: THREE.ShaderMaterial;
  private _c = new THREE.Color();

  constructor(n = 3000) {
    this.n = n;
    this.pos = new Float32Array(n * 3).fill(0);
    this.col = new Float32Array(n * 3);
    this.size = new Float32Array(n);
    this.alpha = new Float32Array(n);
    this.vel = new Float32Array(n * 3);
    this.life = new Float32Array(n);
    this.max = new Float32Array(n);
    this.drag = new Float32Array(n);
    this.start = new Float32Array(n * 3);
    this.baseSize = new Float32Array(n);
    this.home = new Array(n).fill(null);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(this.col, 3));
    g.setAttribute('size', new THREE.BufferAttribute(this.size, 1));
    g.setAttribute('alpha', new THREE.BufferAttribute(this.alpha, 1));
    this.mat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uPx: { value: 1 } },
      vertexShader: `
        attribute vec3 color; attribute float size; attribute float alpha;
        uniform float uPx; varying vec3 vC; varying float vA;
        void main() {
          vC = color; vA = alpha;
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          gl_Position = projectionMatrix * mv;
          gl_PointSize = size * uPx * (110.0 / max(1.0, -mv.z));
        }`,
      fragmentShader: `
        varying vec3 vC; varying float vA;
        void main() {
          float d = length(gl_PointCoord - 0.5);
          float a = smoothstep(0.5, 0.0, d);
          a *= a;
          gl_FragColor = vec4(vC * 1.6 * a * vA, a * vA);
        }`,
    });
    this.points = new THREE.Points(g, this.mat);
    this.points.frustumCulled = false;
  }

  setPixelScale(s: number): void {
    this.mat.uniforms.uPx.value = s;
  }

  emit(e: Emit): void {
    const i = this.next;
    this.next = (this.next + 1) % this.n;
    if (this.life[i] <= 0) this.live++;
    this.pos[i * 3] = e.x; this.pos[i * 3 + 1] = e.y; this.pos[i * 3 + 2] = e.z;
    this.start[i * 3] = e.x; this.start[i * 3 + 1] = e.y; this.start[i * 3 + 2] = e.z;
    this.vel[i * 3] = e.vx ?? 0; this.vel[i * 3 + 1] = e.vy ?? 0; this.vel[i * 3 + 2] = e.vz ?? 0;
    this.life[i] = e.life;
    this.max[i] = e.life;
    this.drag[i] = e.drag ?? 0;
    this.home[i] = e.home ?? null;
    this._c.set(e.color);
    this.col[i * 3] = this._c.r; this.col[i * 3 + 1] = this._c.g; this.col[i * 3 + 2] = this._c.b;
    this.baseSize[i] = e.size;
    this.size[i] = e.size;
    this.alpha[i] = 1;
  }

  burst(x: number, y: number, z: number, color: string, count: number, speed: number, size: number, life: number): void {
    for (let k = 0; k < count; k++) {
      const a = Math.random() * Math.PI * 2;
      const u = Math.random() * 2 - 1;
      const s = speed * (0.4 + Math.random() * 0.8);
      const h = Math.sqrt(1 - u * u);
      this.emit({ x, y, z, vx: Math.cos(a) * h * s, vy: u * s * 0.45, vz: Math.sin(a) * h * s, color, size: size * (0.6 + Math.random() * 0.7), life: life * (0.6 + Math.random() * 0.6), drag: 2.2 });
    }
  }

  update(dt: number): void {
    if (this.live <= 0) return;
    let live = 0;
    for (let i = 0; i < this.n; i++) {
      if (this.life[i] <= 0) continue;
      this.life[i] -= dt;
      if (this.life[i] <= 0) {
        this.alpha[i] = 0;
        this.size[i] = 0;
        continue;
      }
      live++;
      const k = 1 - this.life[i] / this.max[i];
      const h = this.home[i];
      if (h) {
        const e = k * k * (3 - 2 * k);
        const sx = this.start[i * 3], sy = this.start[i * 3 + 1], sz = this.start[i * 3 + 2];
        this.pos[i * 3] = sx + (h.x - sx) * e;
        this.pos[i * 3 + 1] = sy + (h.y - sy) * e + Math.sin(e * Math.PI) * 1.6;
        this.pos[i * 3 + 2] = sz + (h.z - sz) * e;
        this.alpha[i] = Math.min(1, (1 - k) * 6);
      } else {
        const d = Math.max(0, 1 - this.drag[i] * dt);
        this.vel[i * 3] *= d; this.vel[i * 3 + 1] *= d; this.vel[i * 3 + 2] *= d;
        this.pos[i * 3] += this.vel[i * 3] * dt;
        this.pos[i * 3 + 1] += this.vel[i * 3 + 1] * dt;
        this.pos[i * 3 + 2] += this.vel[i * 3 + 2] * dt;
        this.alpha[i] = 1 - k;
      }
      this.size[i] = this.baseSize[i] * (h ? 1 : 1 - k * 0.5);
    }
    this.live = live;
    const g = this.points.geometry;
    g.attributes.position.needsUpdate = true;
    g.attributes.size.needsUpdate = true;
    g.attributes.alpha.needsUpdate = true;
    g.attributes.color.needsUpdate = true;
  }

  dispose(): void {
    this.points.geometry.dispose();
    this.mat.dispose();
  }
}

export class Shockwaves {
  readonly group = new THREE.Group();
  private pool: { m: THREE.Mesh; mat: THREE.MeshBasicMaterial; t: number; dur: number; to: number; inward: boolean }[] = [];
  private geo = new THREE.RingGeometry(0.92, 1, 96);

  constructor(n = 10) {
    for (let i = 0; i < n; i++) {
      const mat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
      const m = new THREE.Mesh(this.geo, mat);
      m.rotation.x = -Math.PI / 2;
      m.visible = false;
      this.group.add(m);
      this.pool.push({ m, mat, t: 0, dur: 1, to: 1, inward: false });
    }
  }

  fire(x: number, y: number, z: number, color: string, radius: number, dur: number, inward = false): void {
    const s = this.pool.find((p) => !p.m.visible) ?? this.pool[0];
    s.m.position.set(x, y, z);
    s.mat.color.set(color);
    s.t = 0;
    s.dur = dur;
    s.to = radius;
    s.inward = inward;
    s.m.visible = true;
  }

  update(dt: number): void {
    for (const s of this.pool) {
      if (!s.m.visible) continue;
      s.t += dt;
      const k = Math.min(1, s.t / s.dur);
      const e = 1 - Math.pow(1 - k, 3);
      const r = s.inward ? s.to * (1 - e) + 0.05 : s.to * e + 0.05;
      s.m.scale.setScalar(r);
      s.mat.opacity = (1 - k) * 1.4;
      if (k >= 1) s.m.visible = false;
    }
  }

  dispose(): void {
    this.geo.dispose();
    this.pool.forEach((p) => p.mat.dispose());
  }
}
