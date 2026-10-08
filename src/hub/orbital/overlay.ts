import { F_MONO, F_SANS } from '../engine/overlay';


const EMOJI = '"Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji"';

function font(w: number | string, px: number, fam: string, emoji = false): string {
  return `${w} ${Math.round(px)}px ${fam}${emoji ? `, ${EMOJI}` : ''}`;
}

function spaced(g: CanvasRenderingContext2D, text: string, x: number, y: number, sp: number, align: 'left' | 'center' | 'right' = 'left'): number {
  let w = 0;
  for (const ch of text) w += g.measureText(ch).width + sp;
  w -= sp;
  let cx = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
  const saved = g.textAlign;
  g.textAlign = 'left';
  for (const ch of text) {
    g.fillText(ch, cx, y);
    cx += g.measureText(ch).width + sp;
  }
  g.textAlign = saved;
  return w;
}

export interface Tag { x: number; y: number; text: string; color: string; alpha: number; size: number; dot: boolean }

export function drawTags(g: CanvasRenderingContext2D, tags: Tag[], u: number, max: number): void {
  const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
  let n = 0;
  for (const t of tags) {
    if (n >= max || t.alpha <= 0.02) continue;
    g.font = font(500, 10.5 * u * t.size, F_MONO, true);
    const w = g.measureText(t.text).width;
    const h = 13 * u * t.size;
    const x = t.x + 9 * u, y = t.y - 9 * u;
    const box = { x0: x - 3 * u, y0: y - h, x1: x + w + 3 * u, y1: y + 3 * u };
    if (placed.some((p) => box.x0 < p.x1 && box.x1 > p.x0 && box.y0 < p.y1 && box.y1 > p.y0)) continue;
    placed.push(box);
    n++;
    g.save();
    g.globalAlpha = t.alpha;
    g.strokeStyle = t.color;
    g.globalAlpha = t.alpha * 0.55;
    g.lineWidth = 1 * u;
    g.beginPath();
    g.moveTo(t.x + 2 * u, t.y - 2 * u);
    g.lineTo(x - 2 * u, y - 4 * u);
    g.stroke();
    g.globalAlpha = t.alpha;
    g.fillStyle = 'rgba(2,6,18,0.62)';
    g.fillRect(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0);
    g.fillStyle = t.color;
    g.textBaseline = 'alphabetic';
    g.fillText(t.text, x, y);
    g.restore();
  }
}

export function drawSectorLabels(g: CanvasRenderingContext2D, labels: { x: number; y: number; text: string; color: string; hot: number }[], u: number): void {
  for (const l of labels) {
    g.save();
    g.font = font(600, 11 * u, F_MONO);
    g.fillStyle = l.color;
    g.globalAlpha = 0.6 + l.hot * 0.4;
    g.shadowColor = l.color;
    g.shadowBlur = l.hot * 12 * u;
    g.textBaseline = 'middle';
    spaced(g, l.text.toUpperCase(), l.x, l.y, 2.2 * u, 'center');
    g.restore();
  }
}

export function drawLaneLabels(g: CanvasRenderingContext2D, lanes: { x: number; y: number; text: string }[], caption: { x: number; y: number } | null, u: number): void {
  g.save();
  g.font = font(500, 9.5 * u, F_MONO);
  g.fillStyle = 'rgba(165,243,252,0.7)';
  g.textBaseline = 'middle';
  for (const l of lanes) {
    g.fillStyle = 'rgba(2,6,18,0.55)';
    const w = g.measureText(l.text).width;
    g.fillRect(l.x - w / 2 - 3 * u, l.y - 7 * u, w + 6 * u, 14 * u);
    g.fillStyle = 'rgba(165,243,252,0.85)';
    g.textAlign = 'center';
    g.fillText(l.text, l.x, l.y + 0.5);
  }
  if (caption) {
    g.font = font(500, 9 * u, F_MONO);
    g.fillStyle = 'rgba(165,243,252,0.5)';
    g.textAlign = 'left';
    spaced(g, 'PRICE LANES · INNER = FAVOURITE', caption.x, caption.y, 1.2 * u);
  }
  g.restore();
}

export function drawCoreReadout(g: CanvasRenderingContext2D, x: number, y: number, pnl: number | null, bank: number | null, u: number, pulse: number): void {
  g.save();
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillStyle = 'rgba(2,6,18,0.62)';
  g.strokeStyle = 'rgba(103,232,249,0.35)';
  g.lineWidth = 1 * u;
  g.beginPath();
  g.roundRect(x - 78 * u, y - 12 * u, 156 * u, bank !== null ? 58 * u : 44 * u, 6 * u);
  g.fill();
  g.stroke();
  g.font = font(600, 9.5 * u, F_MONO);
  g.fillStyle = 'rgba(165,243,252,0.75)';
  spaced(g, 'SESSION P&L', x, y, 2 * u, 'center');
  const col = pnl === null ? '#94A3B8' : pnl >= 0 ? '#6EE7B7' : '#FCA5A5';
  g.font = font(700, (20 + pulse * 3) * u, F_SANS);
  g.fillStyle = col;
  g.shadowColor = col;
  g.shadowBlur = (8 + pulse * 14) * u;
  const txt = pnl === null ? '—' : `${pnl >= 0 ? '+' : '−'}$${Math.abs(pnl).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  g.fillText(txt, x, y + 18 * u);
  g.shadowBlur = 0;
  if (bank !== null) {
    g.font = font(500, 9.5 * u, F_MONO);
    g.fillStyle = 'rgba(203,213,225,0.7)';
    g.fillText(`BANKROLL $${bank.toLocaleString('en-US', { maximumFractionDigits: 0 })}`, x, y + 36 * u);
  }
  g.restore();
}

export function drawWell(g: CanvasRenderingContext2D, x: number, y: number, title: string, count: number, usd: number, color: string, u: number, pulse: number): void {
  g.save();
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  const sign0 = usd > 0 ? '+' : usd < 0 ? '−' : '';
  const sub0 = `${count.toLocaleString('en-US')} · ${sign0}$${Math.abs(usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  g.font = font(600, 11.5 * u, F_MONO);
  const pw = Math.max(g.measureText(sub0).width, title.length * 13 * u) + 28 * u;
  const ph = 46 * u;
  g.fillStyle = 'rgba(4,8,20,0.78)';
  g.strokeStyle = color;
  g.globalAlpha = 0.9;
  g.beginPath();
  g.roundRect(x - pw / 2, y - 14 * u, pw, ph, 8 * u);
  g.fill();
  g.lineWidth = 1 * u;
  g.globalAlpha = 0.45;
  g.stroke();
  g.globalAlpha = 1;
  g.font = font(700, 14 * u, F_MONO);
  g.fillStyle = color;
  g.shadowColor = color;
  g.shadowBlur = (2 + pulse * 10) * u;
  spaced(g, title, x, y, 4 * u, 'center');
  g.shadowBlur = 0;
  g.font = font(600, 11.5 * u, F_MONO);
  g.fillStyle = 'rgba(226,232,240,0.9)';
  const sign = usd > 0 ? '+' : usd < 0 ? '−' : '';
  g.fillText(`${count.toLocaleString('en-US')} · ${sign}$${Math.abs(usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, x, y + 17 * u);
  g.restore();
}

export interface Float { x: number; y: number; text: string; color: string; age: number; life: number; big: boolean }

export function drawFloats(g: CanvasRenderingContext2D, fl: Float[], u: number): void {
  for (const f of fl) {
    const k = f.age / f.life;
    if (k >= 1) continue;
    g.save();
    g.globalAlpha = Math.min(1, f.age / 0.12) * Math.min(1, (1 - k) / 0.35);
    const pop = 1 + Math.max(0, 0.18 - f.age) * 2.2;
    g.font = font(700, (f.big ? 22 : 16) * u * pop, F_SANS, true);
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.shadowColor = f.color;
    g.shadowBlur = 12 * u;
    g.fillStyle = f.color;
    g.fillText(f.text, f.x, f.y - k * 34 * u);
    g.restore();
  }
}

export function drawLegend(g: CanvasRenderingContext2D, W: number, H: number, u: number): void {
  const items: [string, string][] = [['#A855F7', 'whale signal'], ['#EC4899', 'momentum signal']];
  g.save();
  g.font = font(500, 10 * u, F_MONO);
  g.textBaseline = 'middle';
  g.textAlign = 'right';
  void H;
  const y1 = 66 * u;
  const y0 = y1 + 16 * u;
  const line2 = 'planets = open trades · colour = category · size = stake';
  g.fillStyle = 'rgba(165,243,252,0.6)';
  g.fillText(line2, W - 18 * u, y0);
  g.fillText('inner lane = favourite · outer lane = longshot', W - 18 * u, y0 + 15 * u);
  let x = W - 18 * u;
  for (const [c, t] of items.reverse()) {
    const w = g.measureText(t).width;
    g.fillStyle = 'rgba(226,232,240,0.75)';
    g.fillText(t, x, y1);
    x -= w + 8 * u;
    g.fillStyle = c;
    g.beginPath();
    g.arc(x, y1, 3.5 * u, 0, Math.PI * 2);
    g.fill();
    x -= 16 * u;
  }
  g.restore();
}
