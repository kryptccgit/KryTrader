import { useEffect, useRef, useState } from 'react';
import { cls } from '../utils/format';

const SEGMENTS = 10;
const GREEN = 0;
const SEG = 360 / SEGMENTS;

const BG = (() => {
  const stops: string[] = [];
  for (let i = 0; i < SEGMENTS; i++) {
    const c = i === GREEN ? '#10b981' : i % 2 === 0 ? '#7f1d1d' : '#3f0d0d';
    stops.push(`${c} ${i * SEG}deg ${(i + 1) * SEG}deg`);
  }
  return `conic-gradient(from ${-SEG / 2}deg, ${stops.join(', ')})`;
})();

export function RouletteWheel({ winSignal }: { winSignal: number }) {
  const [angle, setAngle] = useState(0);
  const [spinning, setSpinning] = useState(false);
  const [result, setResult] = useState<'win' | 'lose' | null>(null);
  const angleRef = useRef(0);
  const spinningRef = useRef(false);
  const lastWin = useRef(winSignal);

  const spin = (forceGreen: boolean): void => {
    if (spinningRef.current) return;
    const pocket = forceGreen ? GREEN : Math.floor(Math.random() * SEGMENTS);
    const cur = ((angleRef.current % 360) + 360) % 360;
    const finalMod = ((-(pocket * SEG)) % 360 + 360) % 360;
    let delta = finalMod - cur;
    if (delta <= 0) delta += 360;
    const turns = 4 + Math.floor(Math.random() * 3);
    const next = angleRef.current + turns * 360 + delta;
    angleRef.current = next;
    spinningRef.current = true;
    setSpinning(true);
    setResult(null);
    setAngle(next);
    window.setTimeout(() => {
      spinningRef.current = false;
      setSpinning(false);
      setResult(pocket === GREEN ? 'win' : 'lose');
    }, 3700);
  };

  useEffect(() => {
    const t = window.setTimeout(() => spin(false), 500);
    const iv = window.setInterval(() => spin(false), 6500);
    return () => { window.clearTimeout(t); window.clearInterval(iv); };
  }, []);

  useEffect(() => {
    if (winSignal > lastWin.current) spin(true);
    lastWin.current = winSignal;
  }, [winSignal]);

  return (
    <div className="flex flex-col items-center gap-5">
      <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-krypt-muted">
        🎰 Secret Strategy · 10% roulette
      </div>
      <div className="relative h-72 w-72">
        <div className="absolute left-1/2 top-[-7px] z-10 h-0 w-0 -translate-x-1/2 border-l-[9px] border-r-[9px] border-t-[15px] border-l-transparent border-r-transparent border-t-white" />
        <div
          className="h-full w-full rounded-full border-4 border-white/20 shadow-krypt-strong"
          style={{
            background: BG,
            transform: `rotate(${angle}deg)`,
            transition: spinning ? 'transform 3.6s cubic-bezier(0.1,0.75,0.1,1)' : 'none',
          }}
        />
        <div className="absolute left-1/2 top-1/2 grid h-16 w-16 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/20 bg-krypt-void text-2xl">
          {result === 'win' ? '🤑' : spinning ? '🎲' : '🎰'}
        </div>
      </div>
      <div
        className={cls(
          'text-sm font-semibold',
          result === 'win'
            ? 'text-krypt-win'
            : result === 'lose'
              ? 'text-krypt-muted'
              : 'text-krypt-dim',
        )}
      >
        {spinning
          ? 'Spinning…'
          : result === 'win'
            ? 'GREEN — TRADE!'
            : result === 'lose'
              ? 'No hit — spinning again soon'
              : 'Waiting on the wheel…'}
      </div>
    </div>
  );
}
