import * as THREE from 'three';
import { makeGlowTexture } from '../engine/items';


export function laneRadius(priceCents: number): number {
  const p = THREE.MathUtils.clamp(priceCents, 1, 99);
  return 2.4 + (1 - p / 100) * 6.0;
}
export const LANES = [90, 70, 50, 30, 10];
export const SECTOR_R0 = 9.05;
export const SECTOR_R1 = 9.4;
export const EDGE_R = 16;
export const WINS_POS = new THREE.Vector3(-13.4, 0, 0.6);
export const LOSS_POS = new THREE.Vector3(13.4, 0, 0.6);

export const CATS = ['Crypto', 'Sports', 'Politics', 'Economics', 'Financials', 'Climate', 'Entertainment', 'Other'] as const;
export type Cat = (typeof CATS)[number];
export const CAT_COLOR: Record<Cat, string> = {
  Crypto: '#22D3EE', Sports: '#4ADE80', Politics: '#A78BFA', Economics: '#FBBF24',
  Financials: '#FB923C', Climate: '#60A5FA', Entertainment: '#F472B6', Other: '#CBD5E1',
};

export function catOf(category: string | null | undefined): Cat {
  const c = (category ?? '').trim().toLowerCase();
  for (const k of CATS) if (k.toLowerCase() === c) return k;
  if (/weather|climate/.test(c)) return 'Climate';
  if (/financ|compan|stock/.test(c)) return 'Financials';
  if (/econ/.test(c)) return 'Economics';
  if (/sport/.test(c)) return 'Sports';
  if (/polit|election/.test(c)) return 'Politics';
  if (/crypto/.test(c)) return 'Crypto';
  if (/entertain|culture|music|film|tv/.test(c)) return 'Entertainment';
  return 'Other';
}

export function sectorAngle(cat: Cat): number {
  const i = CATS.indexOf(cat);
  return ((i + 0.5) / CATS.length) * Math.PI * 2;
}

function dialTexture(): THREE.CanvasTexture {
  const S = 1024;
  const c = document.createElement('canvas');
  c.width = c.height = S;
  const g = c.getContext('2d')!;
  const R = 10.5;
  const px = S / (2 * R);
  const cx = S / 2;
  g.clearRect(0, 0, S, S);
  g.strokeStyle = 'rgba(103,232,249,0.22)';
  g.lineWidth = 1;
  for (let r = 1.8; r <= 8.6; r += 0.6) {
    g.beginPath(); g.arc(cx, cx, r * px, 0, Math.PI * 2); g.stroke();
  }
  g.strokeStyle = 'rgba(167,139,250,0.18)';
  for (let a = 0; a < 360; a += 15) {
    const t = (a * Math.PI) / 180;
    g.beginPath();
    g.moveTo(cx + Math.cos(t) * 1.6 * px, cx + Math.sin(t) * 1.6 * px);
    g.lineTo(cx + Math.cos(t) * 8.9 * px, cx + Math.sin(t) * 8.9 * px);
    g.stroke();
  }
  for (let a = 0; a < 360; a += 2.5) {
    const t = (a * Math.PI) / 180;
    const major = a % 15 === 0;
    g.strokeStyle = major ? 'rgba(103,232,249,0.75)' : 'rgba(103,232,249,0.3)';
    g.lineWidth = major ? 2.5 : 1.2;
    const r0 = (major ? 9.55 : 9.62) * px, r1 = 9.9 * px;
    g.beginPath();
    g.moveTo(cx + Math.cos(t) * r0, cx + Math.sin(t) * r0);
    g.lineTo(cx + Math.cos(t) * r1, cx + Math.sin(t) * r1);
    g.stroke();
  }
  g.strokeStyle = 'rgba(103,232,249,0.5)';
  g.lineWidth = 2;
  g.beginPath(); g.arc(cx, cx, 9.98 * px, 0, Math.PI * 2); g.stroke();
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

export class Orrery {
  readonly group = new THREE.Group();
  readonly glowTex = makeGlowTexture();
  private dial = dialTexture();
  private coreMat: THREE.ShaderMaterial;
  private core: THREE.Mesh;
  private coreGlow: THREE.Sprite;
  private coreHalo: THREE.Sprite;
  private corona: THREE.Mesh;
  private coreLight: THREE.PointLight;
  private lanes: { mesh: THREE.Mesh; mat: THREE.MeshBasicMaterial; base: number }[] = [];
  private sectors = new Map<Cat, { mat: THREE.MeshBasicMaterial; pulse: number }>();
  private wellMat: THREE.ShaderMaterial;
  private wells: THREE.Object3D[] = [];
  private winsPulse = 0;
  private lossPulse = 0;
  private winRing: THREE.MeshBasicMaterial;
  private lossDisk: THREE.ShaderMaterial;
  private stars: THREE.Points;
  private starMat: THREE.ShaderMaterial;
  flare = 0;
  private bank = 1;
  private sweep: THREE.Mesh;

  constructor() {
    const G = this.group;

    const N = 1800;
    const pos = new Float32Array(N * 3);
    const tw = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const u = Math.random() * 2 - 1, a = Math.random() * Math.PI * 2, r = 70 + Math.random() * 30;
      const h = Math.sqrt(1 - u * u);
      pos[i * 3] = Math.cos(a) * h * r; pos[i * 3 + 1] = u * r * 0.7 - 10; pos[i * 3 + 2] = Math.sin(a) * h * r;
      tw[i] = Math.random();
    }
    const sg = new THREE.BufferGeometry();
    sg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    sg.setAttribute('tw', new THREE.BufferAttribute(tw, 1));
    this.starMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uPx: { value: 1 } },
      vertexShader: `
        attribute float tw; uniform float uTime; uniform float uPx; varying float vA; varying float vT;
        void main() {
          vT = tw;
          vA = 0.45 + 0.55 * sin(uTime * (0.6 + tw * 2.2) + tw * 50.0);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          gl_PointSize = (tw > 0.93 ? 3.2 : 1.6) * uPx;
        }`,
      fragmentShader: `
        varying float vA; varying float vT;
        void main() {
          float a = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
          vec3 c = mix(vec3(0.6, 0.85, 1.0), vec3(0.8, 0.7, 1.0), vT);
          gl_FragColor = vec4(c * a * vA, a * vA);
        }`,
    });
    this.stars = new THREE.Points(sg, this.starMat);
    this.stars.frustumCulled = false;
    G.add(this.stars);
    for (const [x, y, z, col, s, o] of [[-40, -18, -55, '#4C1D95', 70, 0.35], [45, -22, -40, '#0E7490', 60, 0.28], [0, -30, -70, '#312E81', 90, 0.3]] as const) {
      const neb = this.glow(col, s, o);
      neb.position.set(x, y, z);
      G.add(neb);
    }

    const dial = new THREE.Mesh(
      new THREE.PlaneGeometry(21, 21),
      new THREE.MeshBasicMaterial({ map: this.dial, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }),
    );
    dial.rotation.x = -Math.PI / 2;
    dial.position.y = -0.03;
    G.add(dial);
    const glass = new THREE.Mesh(
      new THREE.RingGeometry(1.6, 9.0, 128, 1),
      new THREE.ShaderMaterial({
        transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
        vertexShader: `varying vec2 vP; void main() { vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
        fragmentShader: `
          varying vec2 vP;
          void main() {
            float r = length(vP) / 9.0;
            float a = 0.03 + 0.07 * smoothstep(0.55, 1.0, r);
            gl_FragColor = vec4(vec3(0.35, 0.3, 0.9) * a, a);
          }`,
      }),
    );
    glass.rotation.x = -Math.PI / 2;
    glass.position.y = -0.05;
    G.add(glass);
    this.sweep = new THREE.Mesh(
      new THREE.CircleGeometry(9.0, 64, 0, 0.55),
      new THREE.MeshBasicMaterial({ color: '#22D3EE', transparent: true, opacity: 0.06, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }),
    );
    this.sweep.rotation.x = -Math.PI / 2;
    this.sweep.position.y = -0.02;
    G.add(this.sweep);

    for (const p of LANES) {
      const r = laneRadius(p);
      const base = p === 50 ? 0.85 : 0.55;
      const mat = new THREE.MeshBasicMaterial({ color: '#67E8F9', transparent: true, opacity: base, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false });
      const m = new THREE.Mesh(new THREE.TorusGeometry(r, 0.016, 6, 200), mat);
      m.rotation.x = Math.PI / 2;
      G.add(m);
      this.lanes.push({ mesh: m, mat, base });
    }

    const span = (Math.PI * 2) / CATS.length;
    CATS.forEach((cat, i) => {
      const mat = new THREE.MeshBasicMaterial({ color: CAT_COLOR[cat], transparent: true, opacity: 0.45, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
      const m = new THREE.Mesh(new THREE.RingGeometry(SECTOR_R0, SECTOR_R1, 48, 1, i * span + 0.04, span - 0.08), mat);
      m.rotation.x = -Math.PI / 2;
      m.position.y = 0.01;
      G.add(m);
      this.sectors.set(cat, { mat, pulse: 0 });
    });

    this.coreMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uHeat: { value: 0 } },
      vertexShader: `
        varying vec3 vN; varying vec3 vP;
        void main() { vN = normalize(normalMatrix * normal); vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader: `
        uniform float uTime; uniform float uHeat; varying vec3 vN; varying vec3 vP;
        void main() {
          float n = sin(vP.x * 5.0 + uTime * 1.3) * sin(vP.y * 6.0 - uTime * 1.1) * sin(vP.z * 5.5 + uTime * 0.9);
          float n2 = sin(vP.x * 13.0 - uTime * 2.1 + vP.y * 7.0) * 0.5 + 0.5;
          float rim = pow(1.0 - abs(vN.z), 2.2);
          vec3 base = mix(vec3(0.25, 0.8, 1.0), vec3(0.65, 0.5, 1.0), n * 0.5 + 0.5);
          vec3 hot = vec3(1.0, 0.82, 0.45);
          vec3 c = mix(base, hot, uHeat) * (1.1 + n2 * 0.5) + rim * mix(vec3(0.5, 0.85, 1.0), vec3(1.0, 0.7, 0.3), uHeat) * 1.6;
          gl_FragColor = vec4(c * 0.9, 1.0);
        }`,
    });
    this.core = new THREE.Mesh(new THREE.SphereGeometry(1.0, 48, 32), this.coreMat);
    this.core.position.y = 0.2;
    G.add(this.core);
    this.coreGlow = this.glow('#67E8F9', 6.5, 0.45);
    this.coreHalo = this.glow('#8B5CF6', 13, 0.3);
    this.coreGlow.position.y = this.coreHalo.position.y = 0.2;
    G.add(this.coreHalo, this.coreGlow);
    this.corona = new THREE.Mesh(
      new THREE.TorusGeometry(1.55, 0.025, 6, 96),
      new THREE.MeshBasicMaterial({ color: '#A5F3FC', transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, toneMapped: false }),
    );
    this.corona.position.y = 0.2;
    G.add(this.corona);
    this.coreLight = new THREE.PointLight('#BDEBFF', 60, 30, 1.6);
    this.coreLight.position.y = 0.4;
    G.add(this.coreLight);

    this.wellMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      uniforms: { uTime: { value: 0 }, uPulse: { value: 0 }, uColor: { value: new THREE.Color('#4ADE80') } },
      vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader: `
        uniform float uTime; uniform float uPulse; uniform vec3 uColor; varying vec2 vUv;
        void main() {
          vec2 p = vUv * 2.0 - 1.0;
          float r = length(p);
          if (r > 1.0) discard;
          float a = atan(p.y, p.x);
          float arms = smoothstep(0.1, 1.0, sin(a * 3.0 + r * 11.0 - uTime * 3.2));
          float fall = smoothstep(1.0, 0.1, r);
          float core = smoothstep(0.32, 0.0, r);
          vec3 c = uColor * (arms * 0.75 + 0.2) * fall * (1.0 + uPulse * 1.5) + vec3(0.8, 1.0, 0.85) * core * (0.7 + uPulse);
          gl_FragColor = vec4(c, (arms * 0.6 + 0.2) * fall + core);
        }`,
    });
    const win = new THREE.Group();
    win.position.copy(WINS_POS);
    const disc = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 4.2), this.wellMat);
    disc.rotation.x = -Math.PI / 2;
    this.winRing = new THREE.MeshBasicMaterial({ color: '#86EFAC', transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, toneMapped: false });
    const ring = new THREE.Mesh(new THREE.TorusGeometry(2.15, 0.03, 6, 96), this.winRing);
    ring.rotation.x = Math.PI / 2;
    win.add(disc, ring, this.glow('#22C55E', 5, 0.35));
    G.add(win);
    this.wells.push(win);

    const loss = new THREE.Group();
    loss.position.copy(LOSS_POS);
    const hole = new THREE.Mesh(new THREE.SphereGeometry(0.7, 32, 24), new THREE.MeshBasicMaterial({ color: '#000000' }));
    hole.position.y = 0.25;
    this.lossDisk = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      uniforms: { uTime: { value: 0 }, uPulse: { value: 0 } },
      vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader: `
        uniform float uTime; uniform float uPulse; varying vec2 vUv;
        void main() {
          vec2 p = vUv * 2.0 - 1.0;
          float r = length(p);
          if (r > 1.0 || r < 0.33) discard;
          float a = atan(p.y, p.x);
          float streak = 0.55 + 0.45 * sin(a * 9.0 - uTime * 4.0 + r * 18.0);
          float band = smoothstep(0.33, 0.45, r) * smoothstep(1.0, 0.55, r);
          vec3 c = mix(vec3(1.0, 0.35, 0.15), vec3(0.9, 0.1, 0.25), r) * band * streak * (1.2 + uPulse * 2.0);
          gl_FragColor = vec4(c, band * streak);
        }`,
    });
    const disk = new THREE.Mesh(new THREE.PlaneGeometry(4.0, 4.0), this.lossDisk);
    disk.rotation.x = -Math.PI / 2 + 0.25;
    disk.position.y = 0.25;
    loss.add(disk, hole, this.glow('#EF4444', 4, 0.22));
    G.add(loss);
    this.wells.push(loss);
  }

  glow(color: string, size: number, opacity: number): THREE.Sprite {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glowTex, color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false }));
    s.scale.setScalar(size);
    return s;
  }

  setBankroll(ratio: number): void {
    this.bank = THREE.MathUtils.clamp(ratio, 0.5, 2.5);
  }

  pulseSector(cat: Cat): void {
    const s = this.sectors.get(cat);
    if (s) s.pulse = 1;
  }

  pulseWins(): void { this.winsPulse = 1; }
  pulseLoss(): void { this.lossPulse = 1; }

  setPixelScale(s: number): void {
    this.starMat.uniforms.uPx.value = s;
  }

  update(dt: number, t: number): void {
    this.starMat.uniforms.uTime.value = t;
    this.coreMat.uniforms.uTime.value = t;
    this.flare = Math.max(0, this.flare - dt * 0.35);
    const heat = Math.min(1, this.flare * 1.4);
    this.coreMat.uniforms.uHeat.value = heat;
    const s = (0.85 + 0.25 * this.bank) * (1 + Math.sin(t * 2.2) * 0.035) * (1 + this.flare * 0.6);
    this.core.scale.setScalar(s);
    this.coreGlow.scale.setScalar(6.5 * s * (1 + this.flare * 1.5));
    this.coreHalo.scale.setScalar(13 * s * (1 + this.flare * 2.2));
    (this.coreGlow.material as THREE.SpriteMaterial).color.set(heat > 0.05 ? '#FFD27A' : '#67E8F9');
    this.coreLight.intensity = 60 * (1 + this.flare * 2);
    this.corona.rotation.x = Math.PI / 2 + Math.sin(t * 0.4) * 0.35;
    this.corona.rotation.y = t * 0.3;
    this.corona.scale.setScalar(s);
    this.sweep.rotation.z = -t * 0.7;
    for (const l of this.lanes) l.mat.opacity = l.base * (0.85 + Math.sin(t * 1.3 + l.base * 9) * 0.15);
    for (const s2 of this.sectors.values()) {
      s2.pulse = Math.max(0, s2.pulse - dt * 1.2);
      s2.mat.opacity = 0.4 + s2.pulse * 0.6;
    }
    this.winsPulse = Math.max(0, this.winsPulse - dt * 1.5);
    this.lossPulse = Math.max(0, this.lossPulse - dt * 1.5);
    this.wellMat.uniforms.uTime.value = t;
    this.wellMat.uniforms.uPulse.value = this.winsPulse;
    this.winRing.opacity = 0.6 + this.winsPulse * 0.4;
    this.lossDisk.uniforms.uTime.value = t;
    this.lossDisk.uniforms.uPulse.value = this.lossPulse;
    this.wells[1].rotation.y = t * 0.2;
  }

  dispose(): void {
    this.glowTex.dispose();
    this.dial.dispose();
  }
}
