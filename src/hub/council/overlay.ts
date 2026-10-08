import { F_MONO, F_SANS } from '../engine/overlay';
import type { BubbleStyle } from './roster';


const EMOJI = '"Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji"';

export interface CBubble {
  x: number; y: number;
  text: string;
  style: BubbleStyle;
  age: number; life: number;
  seed: number;
}

function fontOf(s: BubbleStyle, u: number, scale = 1): string {
  return `${s.font.replace('{px}', String(Math.round(s.px * u * scale)))}, ${EMOJI}`;
}

function wrap(g: CanvasRenderingContext2D, text: string, maxW: number): string[] {
  const words = text.split(' ');
  const out: string[] = [];
  let cur = '';
  for (const w of words) {
    const t = cur ? `${cur} ${w}` : w;
    if (g.measureText(t).width > maxW && cur) { out.push(cur); cur = w; } else cur = t;
  }
  if (cur) out.push(cur);
  return out.slice(0, 3);
}

function rr(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  g.beginPath();
  g.roundRect(x, y, w, h, r);
}

function outline(g: CanvasRenderingContext2D, s: BubbleStyle, x: number, y: number, w: number, h: number, u: number, t: number, seed: number): void {
  switch (s.shape) {
    case 'burst': {
      const cx = x + w / 2, cy = y + h / 2;
      const rx = w / 2 + 14 * u, ry = h / 2 + 12 * u;
      const n = 22;
      g.beginPath();
      for (let i = 0; i <= n * 2; i++) {
        const a = (i / (n * 2)) * Math.PI * 2;
        const k = i % 2 ? 1 : 0.82 + 0.05 * Math.sin(seed + i);
        const px = cx + Math.cos(a) * rx * k, py = cy + Math.sin(a) * ry * k;
        if (i === 0) g.moveTo(px, py); else g.lineTo(px, py);
      }
      g.closePath();
      return;
    }
    case 'shaky': {
      const r = Math.min(h / 2, 18 * u);
      const steps = 48;
      g.beginPath();
      for (let i = 0; i <= steps; i++) {
        const a = (i / steps) * Math.PI * 2;
        const px = x + w / 2 + Math.cos(a) * (w / 2 + 6 * u);
        const py = y + h / 2 + Math.sin(a) * (h / 2 + 4 * u);
        const j = Math.sin(t * 30 + i * 2.3 + seed) * 1.6 * u;
        if (i === 0) g.moveTo(px + j, py + j); else g.lineTo(px + j, py - j);
      }
      void r;
      g.closePath();
      return;
    }
    case 'terminal':
    case 'sign':
      g.beginPath();
      g.rect(x, y, w, h);
      return;
    case 'pixel': {
      const s2 = 5 * u;
      g.beginPath();
      g.moveTo(x + s2, y); g.lineTo(x + w - s2, y); g.lineTo(x + w - s2, y + s2); g.lineTo(x + w, y + s2);
      g.lineTo(x + w, y + h - s2); g.lineTo(x + w - s2, y + h - s2); g.lineTo(x + w - s2, y + h); g.lineTo(x + s2, y + h);
      g.lineTo(x + s2, y + h - s2); g.lineTo(x, y + h - s2); g.lineTo(x, y + s2); g.lineTo(x + s2, y + s2);
      g.closePath();
      return;
    }
    case 'flat':
      rr(g, x, y, w, h, 6 * u);
      return;
    case 'bouncy':
    default:
      rr(g, x, y, w, h, h / 2);
  }
}

export function drawBubbles(g: CanvasRenderingContext2D, list: CBubble[], u: number, W: number, H: number, t: number): void {
  for (const b of list) {
    const s = b.style;
    const inT = Math.min(1, b.age / (s.shape === 'flat' ? 0.4 : 0.16));
    const out = Math.min(1, (b.life - b.age) / 0.3);
    if (out <= 0) continue;
    g.save();
    g.globalAlpha = out * (s.shape === 'flat' ? Math.min(1, inT * 1.2) : 1);
    const text = s.upper ? b.text.toUpperCase() : b.text;
    g.font = fontOf(s, u);
    const maxW = 250 * u;
    const lines = wrap(g, s.shape === 'terminal' ? `> ${text}` : text, maxW);
    const lh = s.px * u * 1.3;
    const tw = Math.max(...lines.map((l) => g.measureText(l).width));
    const padX = (s.shape === 'burst' ? 14 : 12) * u, padY = (s.shape === 'sign' ? 10 : 8) * u;
    const w = tw + padX * 2;
    const h = lines.length * lh + padY * 2 + (s.shape === 'sign' ? 6 * u : 0);
    const tail = 12 * u;
    let bob = 0;
    if (s.shape === 'bouncy') bob = Math.abs(Math.sin(t * 8 + b.seed)) * -6 * u;
    if (s.shape === 'flat') bob = (1 - inT) * 10 * u;
    const ax = b.x;
    const ay = b.y + bob;
    let x = ax - w / 2;
    x = Math.max(8 * u, Math.min(W - w - 8 * u, x));
    let y = ay - h - tail;
    y = Math.max(8 * u, Math.min(H - h - 8 * u, y));
    const pop = s.shape === 'flat' ? 1 : inT < 1 ? 0.5 + inT * 0.62 : 1 + Math.max(0, 0.12 - (b.age - 0.16)) * 0.8;
    const shake = s.shape === 'burst' && b.age < 0.5 ? Math.sin(t * 70) * 2.5 * u * (1 - b.age / 0.5) : 0;
    g.translate(ax + shake, ay);
    g.scale(pop, pop);
    g.translate(-ax, -ay);

    g.fillStyle = s.bg;
    g.strokeStyle = s.edge;
    g.lineWidth = (s.shape === 'sign' ? 3.5 : 2.5) * u;
    g.beginPath();
    const tx = Math.max(x + 10 * u, Math.min(x + w - 10 * u, ax));
    g.moveTo(tx - 8 * u, y + h - 2);
    g.lineTo(ax, ay - 2 * u);
    g.lineTo(tx + 8 * u, y + h - 2);
    g.closePath();
    g.fill();
    g.stroke();

    const glow = s.shape === 'terminal';
    g.shadowColor = glow ? s.edge : 'rgba(0,0,0,0.5)';
    g.shadowBlur = (glow ? 16 : 10) * u;
    g.shadowOffsetY = glow ? 0 : 3 * u;
    outline(g, s, x, y, w, h, u, t, b.seed);
    g.fill();
    g.shadowColor = 'transparent';
    g.stroke();
    if (s.shape === 'sign') {
      g.save();
      g.beginPath();
      g.rect(x, y, w, 6 * u);
      g.clip();
      g.fillStyle = '#E5383B';
      g.fillRect(x, y, w, 6 * u);
      g.fillStyle = '#FFFFFF';
      for (let sx = x - 12 * u; sx < x + w; sx += 12 * u) {
        g.beginPath();
        g.moveTo(sx, y + 6 * u); g.lineTo(sx + 6 * u, y); g.lineTo(sx + 10 * u, y); g.lineTo(sx + 4 * u, y + 6 * u);
        g.fill();
      }
      g.restore();
    }
    g.fillStyle = s.fg;
    g.textBaseline = 'middle';
    g.textAlign = 'left';
    const top = y + padY + (s.shape === 'sign' ? 6 * u : 0);
    lines.forEach((l, i) => {
      let jx = 0, jy = 0;
      if (s.shape === 'shaky') { jx = Math.sin(t * 40 + i + b.seed) * 0.9 * u; jy = Math.cos(t * 37 + i) * 0.9 * u; }
      g.fillText(l, x + padX + jx, top + lh * (i + 0.5) + jy + 1);
    });
    if (s.shape === 'terminal' && Math.floor(t * 2.5) % 2 === 0) {
      const last = lines[lines.length - 1];
      g.fillRect(x + padX + g.measureText(last).width + 3 * u, top + lh * (lines.length - 0.5) - lh * 0.35, 8 * u, lh * 0.7);
    }
    g.restore();
  }
}


export interface CardView {
  x: number; y: number;
  t: number;
  out: number;
  item: number;
  kicker: string;
  title: string;
  dirLine: string;
  dir: 'YES' | 'NO';
  facts: string;
  tally: { yes: number; no: number; shown: number } | null;
  stamp: { approved: boolean; text: string; sub: string; t: number; color?: string } | null;
  color: string;
}

export function drawCard(g: CanvasRenderingContext2D, c: CardView, u: number, W: number, H: number, time: number): void {
  const appear = Math.min(1, c.t / 0.35);
  const a = appear * (1 - c.out);
  if (a <= 0) return;
  g.save();
  const flick = 0.92 + Math.sin(time * 37) * 0.03 + (Math.random() < 0.02 ? -0.2 : 0);
  g.globalAlpha = a * flick;
  const w = 410 * u;
  g.font = `700 ${Math.round(26 * u)}px ${F_SANS}, ${EMOJI}`;
  const titleLines = wrap(g, c.title, w - 36 * u).slice(0, 2);
  const h = (118 + titleLines.length * 31 + (c.tally ? 40 : 0)) * u;
  let x = c.x - w / 2;
  let y = c.y - h;
  x = Math.max(10 * u, Math.min(W - w - 10 * u, x));
  y = Math.max(10 * u, Math.min(H - h - 10 * u, y));
  const cy = y + h / 2;
  g.translate(0, cy);
  g.scale(1, 0.15 + 0.85 * appear);
  g.translate(0, -cy);

  g.fillStyle = 'rgba(30,16,2,0.82)';
  g.fillRect(x, y, w, h);
  g.fillStyle = 'rgba(255,181,71,0.06)';
  for (let sy = y; sy < y + h; sy += 4 * u) g.fillRect(x, sy, w, 1.5 * u);
  g.strokeStyle = c.color;
  g.lineWidth = 3 * u;
  g.shadowColor = c.color;
  g.shadowBlur = 14 * u;
  const L = 22 * u;
  for (const [px, py, dx, dy] of [[x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1]] as const) {
    g.beginPath();
    g.moveTo(px, py + dy * L); g.lineTo(px, py); g.lineTo(px + dx * L, py);
    g.stroke();
  }
  g.shadowBlur = 0;
  g.lineWidth = 1 * u;
  g.strokeStyle = 'rgba(255,181,71,0.35)';
  g.strokeRect(x, y, w, h);

  let ty = y + 26 * u;
  g.textBaseline = 'middle';
  g.textAlign = 'left';
  g.fillStyle = '#C89548';
  g.font = `600 ${Math.round(12.5 * u)}px ${F_MONO}, ${EMOJI}`;
  g.fillText(`ITEM #${c.item}  ·  ${c.kicker}`, x + 18 * u, ty);
  ty += 32 * u;
  g.fillStyle = '#FFE2B0';
  g.font = `700 ${Math.round(26 * u)}px ${F_SANS}, ${EMOJI}`;
  for (const l of titleLines) { g.fillText(l, x + 18 * u, ty); ty += 31 * u; }
  ty += 6 * u;
  g.font = `800 ${Math.round(24 * u)}px ${F_SANS}`;
  g.fillStyle = c.dir === 'YES' ? '#7CFF9A' : '#FF8A7A';
  g.fillText(c.dirLine, x + 18 * u, ty);
  const dw = g.measureText(c.dirLine).width;
  g.font = `600 ${Math.round(15 * u)}px ${F_SANS}, ${EMOJI}`;
  g.fillStyle = '#FFD9A0';
  g.fillText(c.facts, x + 30 * u + dw, ty + 1);
  ty += 36 * u;

  if (c.tally) {
    const { yes, no, shown } = c.tally;
    const dot = 13 * u;
    let dx = x + 18 * u;
    g.font = `700 ${Math.round(15 * u)}px ${F_MONO}`;
    g.fillStyle = '#7CFF9A';
    g.fillText('YES', dx, ty);
    dx += 42 * u;
    let k = 0;
    for (let i = 0; i < yes; i++, k++) {
      g.fillStyle = k < shown ? '#22FF66' : 'rgba(34,255,102,0.15)';
      g.beginPath(); g.arc(dx + dot / 2, ty, dot / 2, 0, Math.PI * 2); g.fill();
      dx += dot + 6 * u;
    }
    dx += 10 * u;
    g.fillStyle = '#FFE2B0';
    g.font = `800 ${Math.round(20 * u)}px ${F_MONO}`;
    const score = `${Math.min(yes, shown)} – ${Math.max(0, Math.min(no, shown - yes))}`;
    g.fillText(score, dx, ty);
    dx += g.measureText(score).width + 14 * u;
    for (let i = 0; i < no; i++, k++) {
      g.fillStyle = k < shown ? '#FF2A2A' : 'rgba(255,42,42,0.15)';
      g.beginPath(); g.arc(dx + dot / 2, ty, dot / 2, 0, Math.PI * 2); g.fill();
      dx += dot + 6 * u;
    }
    g.font = `700 ${Math.round(15 * u)}px ${F_MONO}`;
    g.fillStyle = '#FF8A7A';
    g.fillText('NO', dx + 4 * u, ty);
  }
  g.restore();

  if (c.stamp) {
    const st = c.stamp;
    const k = Math.min(1, st.t / 0.16);
    const scale = 2.6 - 1.6 * (1 - Math.pow(1 - k, 3));
    const col = st.color ?? (st.approved ? '#22C55E' : '#EF4444');
    g.save();
    g.globalAlpha = Math.min(1, st.t / 0.08) * (1 - c.out);
    const sx = Math.max(10 * u, Math.min(W - 10 * u, c.x));
    const sy = Math.max(60 * u, c.y - h * 0.45);
    g.translate(sx, sy);
    g.rotate(-0.14);
    g.scale(scale, scale);
    g.font = `800 ${Math.round(44 * u)}px ${F_SANS}`;
    const tw = g.measureText(st.text).width;
    g.font = `700 ${Math.round(17 * u)}px ${F_SANS}`;
    const sw = st.sub ? g.measureText(st.sub).width : 0;
    const bw = Math.max(tw, sw) + 36 * u;
    const bh = (st.sub ? 92 : 66) * u;
    g.fillStyle = 'rgba(12,8,4,0.9)';
    g.fillRect(-bw / 2, -bh / 2, bw, bh);
    g.strokeStyle = col;
    g.lineWidth = 5 * u;
    g.strokeRect(-bw / 2, -bh / 2, bw, bh);
    g.lineWidth = 2 * u;
    g.strokeRect(-bw / 2 + 7 * u, -bh / 2 + 7 * u, bw - 14 * u, bh - 14 * u);
    g.fillStyle = col;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.shadowColor = col;
    g.shadowBlur = 16 * u;
    g.font = `800 ${Math.round(44 * u)}px ${F_SANS}`;
    g.fillText(st.text, 0, st.sub ? -14 * u : 2 * u);
    g.shadowBlur = 0;
    if (st.sub) {
      g.font = `700 ${Math.round(17 * u)}px ${F_SANS}`;
      g.fillText(st.sub, 0, 24 * u);
    }
    g.restore();
  }
}

export interface Plate { x: number; y: number; name: string; color: string; vote: boolean | null; dim: boolean }

export function drawPlates(g: CanvasRenderingContext2D, plates: Plate[], u: number): void {
  for (const p of plates) {
    g.save();
    g.globalAlpha = p.dim ? 0.6 : 1;
    g.font = `700 ${Math.round(12 * u)}px ${F_SANS}`;
    const label = p.name;
    const tw = g.measureText(label).width;
    const vw = p.vote === null ? 0 : 34 * u;
    const w = tw + 18 * u + vw;
    const h = 22 * u;
    const x = p.x - w / 2, y = p.y - h / 2;
    rr(g, x, y, w, h, 4 * u);
    g.fillStyle = 'rgba(20,12,4,0.88)';
    g.fill();
    g.strokeStyle = p.color;
    g.lineWidth = 1.6 * u;
    g.stroke();
    g.fillStyle = p.color;
    g.fillRect(x, y, 4 * u, h);
    g.fillStyle = '#FFE2B0';
    g.textBaseline = 'middle';
    g.fillText(label, x + 10 * u, p.y + 1);
    if (p.vote !== null) {
      const bx = x + tw + 16 * u;
      rr(g, bx, y + 3 * u, vw - 4 * u, h - 6 * u, 3 * u);
      g.fillStyle = p.vote ? '#16A34A' : '#DC2626';
      g.fill();
      g.fillStyle = '#FFFFFF';
      g.font = `800 ${Math.round(10.5 * u)}px ${F_SANS}`;
      g.textAlign = 'center';
      g.fillText(p.vote ? 'YES' : 'NO', bx + (vw - 4 * u) / 2, p.y + 1);
    }
    g.restore();
  }
}

export function drawMood(g: CanvasRenderingContext2D, x: number, y: number, name: string, color: string, u: number): void {
  g.save();
  g.font = `600 ${Math.round(10 * u)}px ${F_MONO}`;
  const k = 'MOOD';
  const kw = g.measureText(k).width;
  g.font = `800 ${Math.round(14 * u)}px ${F_SANS}`;
  const nw = g.measureText(name).width;
  const w = kw + nw + 28 * u, h = 26 * u;
  rr(g, x - w / 2, y - h / 2, w, h, h / 2);
  g.fillStyle = 'rgba(20,12,4,0.85)';
  g.fill();
  g.strokeStyle = color;
  g.lineWidth = 2 * u;
  g.shadowColor = color;
  g.shadowBlur = 12 * u;
  g.stroke();
  g.shadowBlur = 0;
  g.textBaseline = 'middle';
  g.font = `600 ${Math.round(10 * u)}px ${F_MONO}`;
  g.fillStyle = '#C89548';
  g.fillText(k, x - w / 2 + 10 * u, y + 1);
  g.font = `800 ${Math.round(14 * u)}px ${F_SANS}`;
  g.fillStyle = color;
  g.fillText(name, x - w / 2 + 18 * u + kw, y + 1);
  g.restore();
}
