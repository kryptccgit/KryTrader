import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';


const KEEP = ['position', 'normal', 'uv'];

function prep(g: THREE.BufferGeometry, m: THREE.Matrix4, color?: THREE.Color): THREE.BufferGeometry {
  const out = g.index ? g.toNonIndexed() : g.clone();
  for (const name of Object.keys(out.attributes)) if (!KEEP.includes(name)) out.deleteAttribute(name);
  if (!out.attributes.uv) {
    out.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(out.attributes.position.count * 2), 2));
  }
  out.morphAttributes = {};
  out.applyMatrix4(m);
  if (color) {
    const n = out.attributes.position.count;
    const c = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { c[i * 3] = color.r; c[i * 3 + 1] = color.g; c[i * 3 + 2] = color.b; }
    out.setAttribute('color', new THREE.BufferAttribute(c, 3));
  }
  return out;
}

export function mergeStatic(root: THREE.Object3D, dynamic: THREE.Object3D[], mergeable: (m: THREE.Material) => boolean): void {
  const skip = new Set<THREE.Object3D>();
  for (const d of dynamic) d.traverse((o) => skip.add(o));
  root.updateMatrixWorld(true);
  const inv = new THREE.Matrix4().copy(root.matrixWorld).invert();
  const buckets = new Map<string, { mat: THREE.Material; cast: boolean; meshes: THREE.Mesh[] }>();
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh || skip.has(m) || (m as THREE.InstancedMesh).isInstancedMesh) return;
    const mat = m.material;
    if (Array.isArray(mat) || mat.transparent || !mergeable(mat)) return;
    const key = `${mat.uuid}|${m.castShadow ? 1 : 0}`;
    let b = buckets.get(key);
    if (!b) { b = { mat, cast: m.castShadow, meshes: [] }; buckets.set(key, b); }
    b.meshes.push(m);
  });
  const rel = new THREE.Matrix4();
  for (const b of buckets.values()) {
    if (b.meshes.length < 2) continue;
    const geos = b.meshes.map((m) => prep(m.geometry, rel.multiplyMatrices(inv, m.matrixWorld)));
    const merged = mergeGeometries(geos);
    geos.forEach((g) => g.dispose());
    if (!merged) continue;
    for (const m of b.meshes) {
      m.removeFromParent();
      m.geometry.dispose();
    }
    const mesh = new THREE.Mesh(merged, b.mat);
    mesh.castShadow = b.cast;
    mesh.receiveShadow = true;
    root.add(mesh);
  }
}

export function bakePart(group: THREE.Object3D, mat: THREE.Material, castShadow: boolean): void {
  const parts: THREE.Mesh[] = [];
  for (const c of group.children) {
    const m = c as THREE.Mesh;
    if (!m.isMesh) continue;
    const sm = m.material as THREE.MeshStandardMaterial;
    if (Array.isArray(sm) || !sm.color || sm.transparent || (sm.emissiveIntensity ?? 0) > 0) continue;
    parts.push(m);
  }
  if (parts.length < 1) return;
  const geos = parts.map((m) => {
    m.updateMatrix();
    return prep(m.geometry, m.matrix, (m.material as THREE.MeshStandardMaterial).color);
  });
  const merged = mergeGeometries(geos);
  geos.forEach((g) => g.dispose());
  if (!merged) return;
  for (const m of parts) m.removeFromParent();
  const mesh = new THREE.Mesh(merged, mat);
  mesh.castShadow = castShadow;
  group.add(mesh);
}
