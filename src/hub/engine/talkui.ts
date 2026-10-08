import { F_MONO, F_SANS } from './overlay';
import type { Talk } from './dialogue';


export interface Rect { x: number; y: number; w: number; h: number }

function rr(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  g.beginPath();
  g.roundRect(x, y, w, h, r);
}

function wrap(g: CanvasRenderingContext2D, text: string, maxW: number): string[] {
  const out: string[] = [];
  for (const para of text.split('\n')) {
    let line = '';
    for (const word of para.split(' ')) {
      const t = line ? `${line} ${word}` : word;
      if (line && g.measureText(t).width > maxW) { out.push(line); line = word; } else line = t;
    }
    out.push(line);
  }
  return out;
}

function keycap(g: CanvasRenderingContext2D, x: number, y: number, label: string, u: number): number {
  g.font = `700 ${13 * u}px ${F_MONO}`;
  const w = Math.max(22 * u, g.measureText(label).width + 12 * u);
  const h = 22 * u;
  rr(g, x, y - h / 2, w, h, 5 * u);
  g.fillStyle = '#f5f3ff';
  g.fill();
  g.fillStyle = '#1b1530';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText(label, x + w / 2, y + 1 * u);
  return w;
}

export function drawTalkPrompt(g: CanvasRenderingContext2D, v: { W: number; H: number; u: number; name: string; title: string; color: string }): void {
  const { W, H, u } = v;
  g.save();
  g.font = `700 ${17 * u}px ${F_SANS}`;
  const label = `Talk to ${v.name}`;
  const lw = g.measureText(label).width;
  g.font = `500 ${11.5 * u}px ${F_MONO}`;
  const tw = g.measureText(v.title).width;
  const w = Math.max(lw + 46 * u, tw) + 32 * u;
  const h = 58 * u;
  const x = W / 2 - w / 2;
  const y = H * 0.6;
  rr(g, x, y, w, h, 12 * u);
  g.fillStyle = 'rgba(8,6,16,0.72)';
  g.fill();
  g.strokeStyle = v.color;
  g.globalAlpha = 0.7;
  g.lineWidth = 1.5 * u;
  g.stroke();
  g.globalAlpha = 1;
  const kw = keycap(g, x + 16 * u, y + 20 * u, 'E', u);
  g.font = `700 ${17 * u}px ${F_SANS}`;
  g.fillStyle = '#ffffff';
  g.textAlign = 'left';
  g.textBaseline = 'middle';
  g.fillText(label, x + 16 * u + kw + 10 * u, y + 21 * u);
  g.font = `500 ${11.5 * u}px ${F_MONO}`;
  g.fillStyle = 'rgba(255,255,255,0.6)';
  g.fillText(v.title, x + 16 * u, y + 43 * u);
  g.restore();
}

export function drawDialogue(g: CanvasRenderingContext2D, t: Talk, v: { W: number; H: number; u: number; color: string; t: number }): Rect[] {
  const { W, H, u } = v;
  const pw = Math.min(W - 48 * u, 940 * u);
  const pad = 22 * u;
  const textW = pw - pad * 2;
  g.save();

  g.font = `500 ${19 * u}px ${F_SANS}`;
  const full = wrap(g, t.line, textW);
  const optLines = t.mode === 'choose' ? t.options : [];
  const optH = 32 * u;
  const lineH = 26 * u;
  const ph = pad + 30 * u + 18 * u + 10 * u + full.length * lineH + (optLines.length ? 14 * u + optLines.length * optH : 0) + 30 * u + pad * 0.5;
  const px = W / 2 - pw / 2;
  const py = H - ph - 26 * u;

  const grd = g.createLinearGradient(0, py, 0, py + ph);
  grd.addColorStop(0, 'rgba(14,10,28,0.9)');
  grd.addColorStop(1, 'rgba(6,4,14,0.94)');
  rr(g, px, py, pw, ph, 16 * u);
  g.fillStyle = grd;
  g.fill();
  g.strokeStyle = v.color;
  g.lineWidth = 1.6 * u;
  g.globalAlpha = 0.85;
  g.stroke();
  g.globalAlpha = 1;
  rr(g, px + pad, py - 2 * u, 64 * u, 4 * u, 2 * u);
  g.fillStyle = v.color;
  g.fill();

  let y = py + pad;
  g.textAlign = 'left';
  g.textBaseline = 'top';
  g.font = `700 ${24 * u}px ${F_SANS}`;
  g.fillStyle = v.color;
  g.fillText(t.persona.name.toUpperCase(), px + pad, y);
  y += 30 * u;
  g.font = `500 ${12 * u}px ${F_MONO}`;
  g.fillStyle = 'rgba(255,255,255,0.55)';
  g.fillText(t.persona.title, px + pad, y);
  y += 18 * u + 10 * u;

  g.font = `500 ${19 * u}px ${F_SANS}`;
  g.fillStyle = t.mode === 'choose' ? 'rgba(255,255,255,0.62)' : '#ffffff';
  let left = Math.floor(t.mode === 'choose' ? t.line.length : t.shown);
  for (const ln of full) {
    if (left <= 0) break;
    g.fillText(ln.slice(0, left), px + pad, y);
    left -= ln.length + 1;
    y += lineH;
  }
  y = py + pad + 30 * u + 18 * u + 10 * u + full.length * lineH;

  const rects: Rect[] = [];
  if (optLines.length) {
    y += 14 * u;
    optLines.forEach((o, i) => {
      const r = { x: px + pad - 8 * u, y, w: textW + 16 * u, h: optH - 4 * u };
      rects.push(r);
      const on = i === t.sel;
      if (on) {
        rr(g, r.x, r.y, r.w, r.h, 8 * u);
        g.fillStyle = 'rgba(255,255,255,0.1)';
        g.fill();
        g.fillStyle = v.color;
        g.fillRect(r.x, r.y + 5 * u, 3 * u, r.h - 10 * u);
      }
      g.font = `700 ${14 * u}px ${F_MONO}`;
      g.fillStyle = on ? v.color : 'rgba(255,255,255,0.45)';
      g.textBaseline = 'middle';
      g.fillText(`${i + 1}`, px + pad + 4 * u, r.y + r.h / 2);
      g.font = `${on ? 600 : 500} ${17 * u}px ${F_SANS}`;
      g.fillStyle = o.asked && !on ? 'rgba(255,255,255,0.5)' : '#ffffff';
      g.fillText(o.text, px + pad + 28 * u, r.y + r.h / 2);
      y += optH;
    });
  }

  g.textBaseline = 'middle';
  g.font = `500 ${11.5 * u}px ${F_MONO}`;
  g.fillStyle = 'rgba(255,255,255,0.5)';
  const fy = py + ph - 20 * u;
  const hint = t.mode === 'choose' ? '1–9, ↑ ↓ + E, or click  ·  Esc ends the conversation'
    : t.typing ? 'E  skip' : 'E  continue';
  g.textAlign = 'right';
  g.globalAlpha = t.mode === 'say' && !t.typing ? 0.55 + 0.35 * Math.sin(v.t * 4) : 1;
  g.fillText(hint, px + pw - pad, fy);
  g.restore();
  return rects;
}
