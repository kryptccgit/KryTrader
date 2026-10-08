import * as THREE from 'three';
import { DOOR_W, ROOMS, SHIP, SHIP_DOORS, SHIP_EXIT, SHIP_GLASS_WALLS, WALL_H } from './layout';


const GLASS_SILL = 0.8;
const LINTEL = 0.3;
const WALL_T = 0.24;
const PANE_MAX = 2.0;

export interface WalkShell {
  group: THREE.Group;
  setDoor(open: number): void;
  dispose(): void;
}

function exitSignTexture(): THREE.CanvasTexture {
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
  g.fillText('EXIT ▸', 256, 86);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function buildWalkShell(): WalkShell {
  const group = new THREE.Group();
  group.visible = false;
  const textures: THREE.Texture[] = [];

  const frame = new THREE.MeshStandardMaterial({ color: '#c3bcd9', roughness: 0.7, metalness: 0.05 });
  const trim = new THREE.MeshStandardMaterial({ color: '#efeaff', roughness: 0.6 });
  const glass = new THREE.MeshStandardMaterial({
    color: '#9fd4ff', transparent: true, opacity: 0.2, roughness: 0.05, metalness: 0.3,
    depthWrite: false, side: THREE.DoubleSide,
  });
  const neon = new THREE.MeshStandardMaterial({ color: '#A855F7', emissive: '#C084FC', emissiveIntensity: 1.6 });

  const along = (ax: number, az: number, bx: number, bz: number) => {
    const len = Math.hypot(bx - ax, bz - az);
    const ux = (bx - ax) / len, uz = (bz - az) / len;
    const rot = -Math.atan2(bz - az, bx - ax);
    return {
      len,
      put(m: THREE.Mesh, s: number, y: number) {
        m.position.set(ax + ux * s, y, az + uz * s);
        m.rotation.y = rot;
        m.receiveShadow = true;
        group.add(m);
        return m;
      },
    };
  };

  for (const [ax, az, bx, bz] of SHIP_GLASS_WALLS) {
    const w = along(ax, az, bx, bz);
    if (w.len < 0.05) continue;
    w.put(new THREE.Mesh(new THREE.BoxGeometry(w.len, GLASS_SILL, WALL_T), frame), w.len / 2, GLASS_SILL / 2);
    w.put(new THREE.Mesh(new THREE.BoxGeometry(w.len, LINTEL, WALL_T), frame), w.len / 2, WALL_H - LINTEL / 2);
    w.put(new THREE.Mesh(new THREE.BoxGeometry(w.len, 0.04, WALL_T + 0.04), trim), w.len / 2, GLASS_SILL + 0.02);
    const paneH = WALL_H - LINTEL - GLASS_SILL;
    w.put(new THREE.Mesh(new THREE.PlaneGeometry(w.len, paneH), glass), w.len / 2, GLASS_SILL + paneH / 2);
    const n = Math.max(1, Math.ceil(w.len / PANE_MAX));
    for (let i = 0; i <= n; i++) {
      w.put(new THREE.Mesh(new THREE.BoxGeometry(0.1, paneH, WALL_T + 0.02), frame), (w.len * i) / n, GLASS_SILL + paneH / 2);
    }
  }

  for (const [x, z] of SHIP_DOORS) {
    const h = new THREE.Mesh(new THREE.BoxGeometry(DOOR_W + 0.1, LINTEL, WALL_T), frame);
    h.position.set(x, WALL_H - LINTEL / 2, z);
    const strip = new THREE.Mesh(new THREE.BoxGeometry(DOOR_W - 0.2, 0.05, WALL_T + 0.02), neon);
    strip.position.set(x, WALL_H - LINTEL - 0.03, z);
    group.add(h, strip);
  }

  {
    const { x0, x1, z0, z1, noseX, bridgeX1, bridgeZ } = SHIP;
    const s = new THREE.Shape();
    s.moveTo(x0 - 0.2, -(z0 - 0.2));
    s.lineTo(x1 + 0.2, -(z0 - 0.2));
    s.lineTo(x1 + 0.2, bridgeZ + 0.1);
    s.lineTo(bridgeX1, bridgeZ + 0.1);
    s.lineTo(noseX + 0.1, 0);
    s.lineTo(bridgeX1, -bridgeZ - 0.1);
    s.lineTo(x1 + 0.2, -bridgeZ - 0.1);
    s.lineTo(x1 + 0.2, -(z1 + 0.2));
    s.lineTo(x0 - 0.2, -(z1 + 0.2));
    s.closePath();
    const roof = new THREE.Mesh(
      new THREE.ShapeGeometry(s),
      new THREE.MeshStandardMaterial({ color: '#5a537c', emissive: '#231d3a', emissiveIntensity: 1, roughness: 0.85, metalness: 0.1, side: THREE.DoubleSide }),
    );
    roof.rotation.x = -Math.PI / 2;
    roof.position.y = WALL_H + 0.01;
    roof.receiveShadow = false;
    group.add(roof);

    const panel = (x: number, z: number, w: number, d: number, color: string, ei: number) => {
      const m = new THREE.Mesh(
        new THREE.BoxGeometry(w, 0.03, d),
        new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: color, emissiveIntensity: ei }),
      );
      m.position.set(x, WALL_H - 0.02, z);
      group.add(m);
    };
    for (let x = x0 + 1.2; x < x1 + 0.5; x += 2.4) panel(x, 0, 1.4, 0.22, '#E9D5FF', 1.4);
    for (const r of ROOMS) panel(r.cx, r.cz, 2.2, 0.5, r.accent, 1.1);
  }

  const ex = SHIP_EXIT[0];
  const ez = (SHIP_EXIT[1] + SHIP_EXIT[3]) / 2;
  const face = ex + 0.13;
  const doorH = 1.95;
  const halfW = 0.62;
  const panels: THREE.Mesh[] = [];
  {
    const dark = new THREE.Mesh(new THREE.PlaneGeometry(halfW * 2, doorH), new THREE.MeshBasicMaterial({ color: '#05030c' }));
    dark.position.set(face + 0.005, doorH / 2, ez);
    dark.rotation.y = Math.PI / 2;
    group.add(dark);
    const green = new THREE.MeshStandardMaterial({ color: '#14532d', emissive: '#4ADE80', emissiveIntensity: 1.8 });
    const panelM = new THREE.MeshStandardMaterial({ color: '#d9d3ee', roughness: 0.45, metalness: 0.35 });
    for (const side of [-1, 1]) {
      const p = new THREE.Mesh(new THREE.BoxGeometry(0.06, doorH, halfW), panelM);
      p.position.set(face + 0.05, doorH / 2, ez + side * halfW / 2);
      p.userData.side = side;
      const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.02, doorH - 0.3, 0.04), green);
      stripe.position.set(0.035, 0, -side * (halfW / 2 - 0.06));
      p.add(stripe);
      panels.push(p);
      group.add(p);
      const post = new THREE.Mesh(new THREE.BoxGeometry(0.16, doorH + 0.15, 0.14), frame);
      post.position.set(face + 0.06, (doorH + 0.15) / 2, ez + side * (halfW + 0.07));
      group.add(post);
    }
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.15, halfW * 2 + 0.28), frame);
    head.position.set(face + 0.06, doorH + 0.075, ez);
    const tex = exitSignTexture();
    textures.push(tex);
    const sign = new THREE.Mesh(
      new THREE.PlaneGeometry(0.75, 0.235),
      new THREE.MeshBasicMaterial({ map: tex, toneMapped: false }),
    );
    sign.position.set(face + 0.15, doorH + 0.28, ez);
    sign.rotation.y = Math.PI / 2;
    group.add(head, sign);
  }

  return {
    group,
    setDoor(open: number) {
      const o = Math.max(0, Math.min(1, open));
      for (const p of panels) p.position.z = ez + (p.userData.side as number) * (halfW / 2 + o * halfW * 0.95);
    },
    dispose() {
      textures.forEach((t) => t.dispose());
    },
  };
}
