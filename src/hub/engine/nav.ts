import { NAV_EDGES, NAV_NODES, type NavNode } from './layout';

export class NavGraph {
  readonly nodes = new Map<string, NavNode>();
  private adj = new Map<string, { to: string; d: number }[]>();
  private cache = new Map<string, NavNode[]>();

  constructor() {
    for (const n of NAV_NODES) {
      this.nodes.set(n.id, n);
      this.adj.set(n.id, []);
    }
    for (const [a, b] of NAV_EDGES) {
      const na = this.nodes.get(a);
      const nb = this.nodes.get(b);
      if (!na || !nb) throw new Error(`nav edge ${a}-${b} names a missing node`);
      const d = Math.hypot(na.x - nb.x, na.z - nb.z);
      this.adj.get(a)!.push({ to: b, d });
      this.adj.get(b)!.push({ to: a, d });
    }
  }

  get(id: string): NavNode {
    const n = this.nodes.get(id);
    if (!n) throw new Error(`no nav node ${id}`);
    return n;
  }

  nearest(x: number, z: number): NavNode {
    let best: NavNode | null = null;
    let bd = Infinity;
    for (const n of this.nodes.values()) {
      const d = (n.x - x) ** 2 + (n.z - z) ** 2;
      if (d < bd) { bd = d; best = n; }
    }
    return best!;
  }

  path(from: string, to: string): NavNode[] {
    const key = `${from}>${to}`;
    const hit = this.cache.get(key);
    if (hit) return hit;
    const dist = new Map<string, number>([[from, 0]]);
    const prev = new Map<string, string>();
    const open = new Set<string>([from]);
    const done = new Set<string>();
    while (open.size) {
      let cur = '';
      let cd = Infinity;
      for (const id of open) {
        const d = dist.get(id)!;
        if (d < cd) { cd = d; cur = id; }
      }
      open.delete(cur);
      if (cur === to) break;
      done.add(cur);
      for (const { to: nb, d } of this.adj.get(cur) ?? []) {
        if (done.has(nb)) continue;
        const nd = cd + d;
        if (nd < (dist.get(nb) ?? Infinity)) {
          dist.set(nb, nd);
          prev.set(nb, cur);
          open.add(nb);
        }
      }
    }
    const out: NavNode[] = [];
    let c: string | undefined = to;
    while (c) {
      out.unshift(this.get(c));
      if (c === from) break;
      c = prev.get(c);
    }
    if (out[0]?.id !== from) out.splice(0, out.length, this.get(to));
    this.cache.set(key, out);
    return out;
  }
}
