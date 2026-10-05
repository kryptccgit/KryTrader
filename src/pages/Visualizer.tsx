import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, Pause, Play, RotateCcw, Sparkles, TrendingDown, TrendingUp,
  Wallet,
} from 'lucide-react';
import { Area, AreaChart, Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { BotPosition, PnlPoint, SignalSource } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { Card, Page, ShareButton } from '../components/common';
import { RouletteWheel } from '../components/RouletteWheel';
import { cls, fmtUsd } from '../utils/format';


type OrbStage = 'scan' | 'orbit' | 'win-fly' | 'loss-fly' | 'eject';

interface Orb {
  key: string;
  source: SignalSource;
  ticker: string;
  title: string;
  stage: OrbStage;
  x: number; y: number;
  vx: number; vy: number;
  radius: number;
  color: string;
  born: number;
  orbitRadius: number;
  orbitAngle: number;
  orbitSpeed: number;
  pnl?: number;
}

const TAU = Math.PI * 2;
const SCAN_LIFE_MS = 8_000;
const RESOLVE_FLY_MS = 2_500;
const MAX_ORBS = 240;

export function VisualizerPage() {
  const { signals, positions, account, scannerStats, config } = useApp();
  const [running, setRunning] = useState(true);
  const gambling = !!config?.gamblingMode;
  const openCount = positions.filter((p) => !p.resolved).length;

  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number | null>(null);

  const orbsRef = useRef<Orb[]>([]);
  const seenSignalsRef = useRef<Set<string>>(new Set());
  const seenPosRef = useRef<Map<number, string>>(new Map());

  const [pot, setPot] = useState({ wins: 0, losses: 0, winPnl: 0, lossPnl: 0 });
  const sessionRunId = account?.sessionRunId ?? 0;
  const lastRunIdRef = useRef<number>(sessionRunId);
  useEffect(() => {
    if (sessionRunId !== lastRunIdRef.current) {
      lastRunIdRef.current = sessionRunId;
      setPot({ wins: 0, losses: 0, winPnl: 0, lossPnl: 0 });
      seenPosRef.current = new Map();
    }
  }, [sessionRunId]);

  const [series, setSeries] = useState<PnlPoint[]>([]);
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const s = await window.krypt.data.pnlSeries(24);
        if (mounted) setSeries(s);
      } catch {   }
    };
    void load();
    const i = window.setInterval(load, 30_000);
    return () => { mounted = false; window.clearInterval(i); };
  }, []);

  const hourlyBars = useMemo(() => {
    const now = Date.now();
    const bins: { hour: string; wins: number; losses: number; pnl: number }[] = [];
    for (let h = 11; h >= 0; h--) {
      const t = new Date(now - h * 3600_000);
      bins.push({
        hour: `${t.getHours()}h`,
        wins: 0, losses: 0, pnl: 0,
      });
    }
    for (const p of positions) {
      if (!p.resolved || !p.resolvedAt) continue;
      const ts = new Date(p.resolvedAt).getTime();
      const hoursAgo = Math.floor((now - ts) / 3600_000);
      if (hoursAgo < 0 || hoursAgo > 11) continue;
      const slot = bins[11 - hoursAgo];
      if (!slot) continue;
      if (p.outcomeCorrect === 1) slot.wins += 1;
      else if (p.outcomeCorrect === 0) slot.losses += 1;
      slot.pnl += p.pnlUsd ?? 0;
    }
    return bins;
  }, [positions]);

  const hotTickers = useMemo(() => {
    const cutoff = Date.now() - 24 * 3600_000;
    const acc = new Map<string, { wins: number; losses: number; pnl: number; title: string }>();
    for (const p of positions) {
      if (!p.resolved || !p.resolvedAt) continue;
      if (new Date(p.resolvedAt).getTime() < cutoff) continue;
      const cur = acc.get(p.ticker) || { wins: 0, losses: 0, pnl: 0, title: p.title };
      if (p.outcomeCorrect === 1) cur.wins += 1;
      else if (p.outcomeCorrect === 0) cur.losses += 1;
      cur.pnl += p.pnlUsd ?? 0;
      acc.set(p.ticker, cur);
    }
    return Array.from(acc.entries())
      .map(([ticker, v]) => ({ ticker, ...v }))
      .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
      .slice(0, 6);
  }, [positions]);

  useEffect(() => {
    const w = wrapperRef.current?.clientWidth ?? 800;
    const h = wrapperRef.current?.clientHeight ?? 500;
    const cx = w / 2, cy = h / 2;
    for (const s of signals.slice(0, 40)) {
      const key = `sig:${s.source}:${s.id}`;
      if (seenSignalsRef.current.has(key)) continue;
      seenSignalsRef.current.add(key);
      orbsRef.current.push(spawnScanOrb(key, s.source, s.ticker, s.title, cx, cy, w, h));
      if (orbsRef.current.length > MAX_ORBS) orbsRef.current.shift();
    }
  }, [signals]);

  useEffect(() => {
    const w = wrapperRef.current?.clientWidth ?? 800;
    const h = wrapperRef.current?.clientHeight ?? 500;
    const cx = w / 2, cy = h / 2;
    let dWins = 0, dLosses = 0, dWinPnl = 0, dLossPnl = 0;

    for (const p of positions) {
      const sigKey = `sig:${p.signalSource}:${p.signalId}`;
      const posKey = `pos:${p.id}`;
      const resolvedSig = p.resolved ? `${p.outcomeCorrect}:${p.pnlUsd ?? 0}` : 'open';
      const prevResolvedSig = seenPosRef.current.get(p.id);
      seenPosRef.current.set(p.id, resolvedSig);

      let orb =
        orbsRef.current.find((o) => o.key === posKey)
        ?? orbsRef.current.find((o) => o.key === sigKey);

      const filled = p.filledContracts ?? p.targetContracts ?? 0;
      const cost = p.costUsd ?? 0;
      const potential = Math.max(0, filled - cost) || cost;
      const sizePx = Math.max(4, Math.min(16, 4 + Math.sqrt(potential) * 1.6));

      const isOpen = !p.resolved && (p.status === 'filled' || p.status === 'partial');
      if (isOpen) {
        if (!orb) {
          orb = spawnScanOrb(posKey, p.signalSource, p.ticker, p.title, cx, cy, w, h);
          orbsRef.current.push(orb);
        }
        if (orb.stage !== 'orbit') {
          orb.key = posKey;
          orb.stage = 'orbit';
          const dx = orb.x - cx, dy = orb.y - cy;
          const d = Math.max(40, Math.min(180, Math.hypot(dx, dy)));
          orb.orbitRadius = 65 + (d / 180) * 65;
          orb.orbitAngle = Math.atan2(dy, dx);
          orb.orbitSpeed = (Math.random() * 0.6 + 0.7) * (Math.random() < 0.5 ? 1 : -1) * 0.020;
          orb.color = p.signalSource === 'whale' ? '#A855F7' : '#EC4899';
        }
        orb.radius = sizePx;
        continue;
      }

      if (p.resolved && prevResolvedSig !== resolvedSig) {
        if (!orb) {
          orb = spawnScanOrb(posKey, p.signalSource, p.ticker, p.title, cx, cy, w, h);
          orb.key = posKey;
          orb.stage = 'orbit';
          orb.orbitRadius = 120;
          orb.orbitAngle = Math.random() * TAU;
          orb.orbitSpeed = 0;
          orbsRef.current.push(orb);
        }
        orb.pnl = p.pnlUsd ?? 0;
        if (p.outcomeCorrect === 1) {
          orb.stage = 'win-fly';
          orb.color = '#22C55E';
          orb.born = performance.now();
          dWins++;
          dWinPnl += p.pnlUsd ?? 0;
        } else if (p.outcomeCorrect === 0) {
          orb.stage = 'loss-fly';
          orb.color = '#EF4444';
          orb.born = performance.now();
          dLosses++;
          dLossPnl += p.pnlUsd ?? 0;
        } else {
          orb.stage = 'eject';
          orb.born = performance.now();
        }
      }
    }

    if (dWins || dLosses || dWinPnl || dLossPnl) {
      setPot((prev) => ({
        wins: prev.wins + dWins,
        losses: prev.losses + dLosses,
        winPnl: prev.winPnl + dWinPnl,
        lossPnl: prev.lossPnl + dLossPnl,
      }));
    }
  }, [positions]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrapper = wrapperRef.current;
    if (!canvas || !wrapper) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = wrapper.clientWidth;
      const h = wrapper.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener('resize', resize);

    let last = performance.now();
    const tick = (ts: number) => {
      const dt = Math.min(50, ts - last);
      last = ts;
      const w = wrapper.clientWidth;
      const h = wrapper.clientHeight;
      const cx = w / 2;
      const cy = h / 2;
      const bucketY = h + 30;
      const winBucketX = w * 0.25;
      const lossBucketX = w * 0.75;

      ctx.clearRect(0, 0, w, h);
      const bgGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * 0.8);
      bgGrad.addColorStop(0, 'rgba(168, 85, 247, 0.06)');
      bgGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, w, h);

      drawSweep(ctx, cx, cy, ts, Math.max(w, h));

      drawSun(ctx, cx, cy, ts);

      const live: Orb[] = [];
      for (const orb of orbsRef.current) {
        if (running) {
          stepOrb(orb, ts, dt, cx, cy, w, h, winBucketX, lossBucketX, bucketY);
        }
        const ejectedTooLong = orb.stage === 'eject' && ts - orb.born > 2500;
        const offscreen =
          orb.x < -60 || orb.x > w + 60 || orb.y < -60 || orb.y > h + 60;
        if (ejectedTooLong || (orb.stage === 'eject' && offscreen)) continue;

        if (orb.stage === 'scan' && ts - orb.born > SCAN_LIFE_MS) {
          const ang = Math.atan2(orb.y - cy, orb.x - cx);
          orb.vx = Math.cos(ang) * 5;
          orb.vy = Math.sin(ang) * 5;
          orb.stage = 'eject';
          orb.born = ts;
        }

        drawOrb(ctx, orb, cx, cy, ts);
        live.push(orb);
      }
      orbsRef.current = live;

      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener('resize', resize);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [running]);

  const reset = () => {
    orbsRef.current = [];
    seenSignalsRef.current = new Set();
    seenPosRef.current = new Map();
    setPot({ wins: 0, losses: 0, winPnl: 0, lossPnl: 0 });
  };

  const sessionPnl = account?.sessionPnlUsd ?? 0;
  const sessionRoi = account?.sessionRoiPct ?? 0;
  const sessionStartedAt = account?.sessionStartedAt;
  const sessionSeries = useMemo(() => {
    if (!sessionStartedAt) return series;
    const t0 = new Date(sessionStartedAt).getTime();
    const filtered = series.filter((p) => new Date(p.at).getTime() >= t0 - 60_000);
    return filtered.length >= 2 ? filtered : series;
  }, [series, sessionStartedAt]);

  return (
    <Page
      title="Trade Visualizer"
      subtitle="Live orbital map of every signal the bot sees and every trade it takes. Buckets at the bottom catch resolved positions."
      actions={
        <>
          <button onClick={() => setRunning((v) => !v)} className="krypt-btn-default">
            {running ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            {running ? 'Pause' : 'Resume'}
          </button>
          <button onClick={reset} className="krypt-btn-default">
            <RotateCcw className="h-4 w-4" /> Reset view
          </button>
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[320px,1fr]">
        <div className="space-y-3">
          <Card header={<div className="text-xs uppercase tracking-wider text-krypt-muted">Equity (session)</div>}>
            <div className="text-lg font-mono text-white">{fmtUsd(account?.totalUsd)}</div>
            <div className={cls(
              'text-xs',
              sessionPnl >= 0 ? 'text-krypt-win' : 'text-krypt-loss',
            )}>
              {fmtUsd(sessionPnl, { sign: true })} session &middot;{' '}
              <span className="text-krypt-dim">{sessionRoi >= 0 ? '+' : ''}{sessionRoi.toFixed(2)}%</span>
            </div>
            <div className="mt-2 h-20">
              {sessionSeries.length < 3 ? (
                <div className="grid h-full place-items-center text-[11px] text-krypt-dim">collecting data…</div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={sessionSeries}>
                    <defs>
                      <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#A855F7" stopOpacity={0.7} />
                        <stop offset="100%" stopColor="#A855F7" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <Tooltip
                      labelStyle={{ color: '#A1A1AA' }} itemStyle={{ color: '#FFFFFF' }} contentStyle={{ background: '#171722', border: '1px solid #ffffff14', borderRadius: 6, fontSize: 11 }}
                      formatter={(v: number) => [`$${v.toFixed(2)}`, 'Equity']}
                      labelFormatter={() => ''}
                    />
                    <Area type="monotone" dataKey="totalUsd" stroke="#A855F7" strokeWidth={1.5} fill="url(#sparkGrad)" />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </Card>

          <Card header={<div className="text-xs uppercase tracking-wider text-krypt-muted">P&amp;L per hour (12h)</div>}>
            <div className="h-24">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={hourlyBars}>
                  <Tooltip
                    labelStyle={{ color: '#A1A1AA' }} itemStyle={{ color: '#FFFFFF' }} contentStyle={{ background: '#171722', border: '1px solid #ffffff14', borderRadius: 6, fontSize: 11 }}
                    formatter={(v: number, n: string) => {
                      if (n === 'pnl') return [`$${v.toFixed(2)}`, 'pnl'];
                      return [v, n];
                    }}
                  />
                  <XAxis dataKey="hour" hide />
                  <YAxis hide />
                  <Bar dataKey="pnl" fill="#A855F7" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-krypt-muted">
              <Mini label="Today wins" value={String(account?.todayWins ?? 0)} tone="good" />
              <Mini label="Today losses" value={String(account?.todayLosses ?? 0)} tone="bad" />
              <Mini label="Win rate" value={`${(account?.winRate ?? 0).toFixed(1)}%`} />
              <Mini label="Open" value={String(account?.openCount ?? 0)} />
            </div>
          </Card>

          <Card header={<div className="text-xs uppercase tracking-wider text-krypt-muted">Scanner activity</div>}>
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <Mini label="Whales seen" value={String(scannerStats?.whales.total ?? 0)} tone="purple" />
              <Mini label="Whales hit" value={`${(scannerStats?.whales.winRate ?? 0).toFixed(1)}%`} tone="good" />
              <Mini label="Momentum seen" value={String(scannerStats?.momentum.total ?? 0)} tone="pink" />
              <Mini label="Momentum hit" value={`${(scannerStats?.momentum.winRate ?? 0).toFixed(1)}%`} tone="good" />
              <Mini label="Markets" value={String(scannerStats?.marketsTracked ?? 0)} />
              <Mini label="Live orbs" value={String(orbsRef.current.length)} />
            </div>
          </Card>

          <Card header={<div className="text-xs uppercase tracking-wider text-krypt-muted">Hot tickers (24h)</div>}>
            {hotTickers.length === 0 ? (
              <div className="py-3 text-center text-[11px] text-krypt-dim">no resolutions yet</div>
            ) : (
              <div className="divide-y divide-krypt-border">
                {hotTickers.map((t) => (
                  <div key={t.ticker} className="flex items-center gap-2 py-1.5 text-[11px]">
                    <span className="font-mono text-krypt-muted truncate" title={t.ticker}>
                      {t.ticker.split('-').pop() || t.ticker}
                    </span>
                    <span className="ml-auto text-krypt-win">{t.wins}W</span>
                    <span className="text-krypt-loss">{t.losses}L</span>
                    <span className={cls(
                      'min-w-[52px] text-right font-mono',
                      t.pnl >= 0 ? 'text-krypt-win' : 'text-krypt-loss',
                    )}>
                      {fmtUsd(t.pnl, { sign: true })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <div className="flex flex-col gap-2">
          <div ref={wrapperRef} className="relative h-[calc(100vh-280px)] min-h-[440px] overflow-hidden rounded-2xl border border-krypt-border bg-krypt-void">
            <canvas ref={canvasRef} className="absolute inset-0" />
            {gambling && (
              <div className="absolute inset-0 grid place-items-center bg-krypt-void/90 backdrop-blur-sm">
                <RouletteWheel winSignal={openCount} />
              </div>
            )}

            <div className="pointer-events-none absolute right-3 top-3 flex flex-col gap-1 rounded-lg border border-krypt-border bg-krypt-void/80 px-3 py-2 text-[11px] text-krypt-muted backdrop-blur">
              <LegendDot color="#A855F7" label="Whale signal" />
              <LegendDot color="#EC4899" label="Momentum signal" />
              <LegendDot color="#FFFFFF" label="Open position (orbiting)" outline />
              <LegendDot color="#22C55E" label="Won → wins pot" />
              <LegendDot color="#EF4444" label="Lost → losses pot" />
              <div className="mt-1 text-[10px] text-krypt-dim">orb size = potential profit</div>
            </div>

            <div className="absolute left-3 top-3 flex items-center gap-2 rounded-lg border border-krypt-border bg-krypt-void/80 px-3 py-2 text-[11px] backdrop-blur">
              <Wallet className="h-3.5 w-3.5 text-krypt-purple" />
              <div>
                <div className="text-[10px] uppercase tracking-wider text-krypt-muted">Session P&amp;L</div>
                <div className={cls(
                  'font-mono text-sm',
                  (account?.sessionPnlUsd ?? 0) >= 0 ? 'text-krypt-win' : 'text-krypt-loss',
                )}>
                  {fmtUsd(account?.sessionPnlUsd ?? 0, { sign: true })}
                </div>
                <div className="text-[10px] text-krypt-dim">
                  visualized: {pot.wins}W / {pot.losses}L this session
                </div>
              </div>
              <ShareButton
                size="xs"
                text={
                  `Krypt Trader session P&L: `
                  + `${fmtUsd(account?.sessionPnlUsd ?? 0, { sign: true })} `
                  + `(${pot.wins}W / ${pot.losses}L). `
                  + `Free Kalshi auto-trader by @YuhgoSlavia · krypt.cc/tools/trader`
                }
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <BucketTile
              tone="good"
              label="Wins pot"
              count={pot.wins}
              pnl={pot.winPnl}
              icon={TrendingUp}
            />
            <BucketTile
              tone="bad"
              label="Losses pot"
              count={pot.losses}
              pnl={pot.lossPnl}
              icon={TrendingDown}
            />
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card header={<div className="text-xs uppercase tracking-wider text-krypt-muted"><Activity className="mr-1 inline h-3 w-3" />Latest signals</div>}>
          {signals.slice(0, 8).map((s) => (
            <div key={`${s.source}:${s.id}`} className="flex items-center gap-2 border-t border-krypt-border py-1.5 first:border-t-0 text-xs">
              <span className="h-2 w-2 rounded-full" style={{ background: s.source === 'whale' ? '#A855F7' : '#EC4899' }} />
              <span className="font-mono text-krypt-muted">{s.ticker}</span>
              <span className="ml-auto text-krypt-dim truncate">{s.title}</span>
            </div>
          ))}
        </Card>
        <Card header={<div className="text-xs uppercase tracking-wider text-krypt-muted"><Sparkles className="mr-1 inline h-3 w-3" />Latest trades</div>}>
          {positions.slice(0, 8).map((p) => (
            <TradeRow key={p.id} p={p} />
          ))}
        </Card>
      </div>
    </Page>
  );
}


function spawnScanOrb(
  key: string,
  source: SignalSource,
  ticker: string,
  title: string,
  cx: number, cy: number,
  w: number, h: number,
): Orb {
  const angle = Math.random() * TAU;
  const r = Math.min(w, h) * (0.42 + Math.random() * 0.08);
  const x = cx + Math.cos(angle) * r;
  const y = cy + Math.sin(angle) * r;
  const inwardX = (cx - x) / r;
  const inwardY = (cy - y) / r;
  const tangX = -inwardY;
  const tangY = inwardX;
  const speed = 1.4 + Math.random() * 0.8;
  const swirl = (Math.random() < 0.5 ? 1 : -1) * (0.6 + Math.random() * 0.5);
  return {
    key,
    source,
    ticker,
    title,
    stage: 'scan',
    x, y,
    vx: inwardX * speed + tangX * swirl,
    vy: inwardY * speed + tangY * swirl,
    radius: 2.5 + Math.random() * 1.5,
    color: source === 'whale' ? '#A855F7' : '#EC4899',
    born: performance.now(),
    orbitRadius: 0,
    orbitAngle: 0,
    orbitSpeed: 0,
  };
}

function stepOrb(
  orb: Orb,
  ts: number,
  dt: number,
  cx: number, cy: number,
  w: number, h: number,
  winX: number, lossX: number, bucketY: number,
) {
  const k = dt / 16;
  switch (orb.stage) {
    case 'scan': {
      const dx = cx - orb.x;
      const dy = cy - orb.y;
      const d = Math.hypot(dx, dy) || 1;
      orb.vx += (dx / d) * 0.10 * k;
      orb.vy += (dy / d) * 0.10 * k;
      orb.vx *= 0.985;
      orb.vy *= 0.985;
      orb.x += orb.vx * k;
      orb.y += orb.vy * k;
      if (d < 18) {
        const ang = Math.atan2(orb.y - cy, orb.x - cx);
        orb.vx = Math.cos(ang) * 5;
        orb.vy = Math.sin(ang) * 5;
        orb.stage = 'eject';
      }
      break;
    }
    case 'orbit': {
      orb.orbitAngle += orb.orbitSpeed * k;
      const breath = Math.sin((ts + orb.x) / 800) * 6;
      const r = orb.orbitRadius + breath;
      orb.x = cx + Math.cos(orb.orbitAngle) * r;
      orb.y = cy + Math.sin(orb.orbitAngle) * r;
      break;
    }
    case 'win-fly':
    case 'loss-fly': {
      const targetX = orb.stage === 'win-fly' ? winX : lossX;
      const targetY = bucketY - 6;
      const age = ts - orb.born;
      const t = Math.min(1, age / RESOLVE_FLY_MS);
      const ease = 1 - Math.pow(1 - t, 3);
      const sx = orb.x, sy = orb.y;
      if (!('_fly' in orb) || (orb as any)._fly?.target !== targetX) {
        (orb as any)._fly = { sx, sy, target: targetX, midX: (sx + targetX) / 2, midY: Math.min(sy, targetY) - 80 };
      }
      const f = (orb as any)._fly;
      const mx = f.midX, my = f.midY;
      const u = 1 - ease;
      orb.x = u * u * f.sx + 2 * u * ease * mx + ease * ease * targetX;
      orb.y = u * u * f.sy + 2 * u * ease * my + ease * ease * targetY;
      orb.radius = Math.max(2, 6 - ease * 2);
      if (t >= 1) orb.stage = 'eject';
      break;
    }
    case 'eject': {
      orb.x += orb.vx * k;
      orb.y += orb.vy * k;
      orb.vx *= 0.99;
      orb.vy *= 0.99;
      break;
    }
  }
}

function drawOrb(ctx: CanvasRenderingContext2D, orb: Orb, cx: number, cy: number, ts: number) {
  const ageMs = ts - orb.born;
  let alpha = 1;
  if (orb.stage === 'scan') alpha = Math.max(0.25, 1 - ageMs / SCAN_LIFE_MS);
  if (orb.stage === 'eject') alpha = Math.max(0, 0.8 - ageMs / 4000);

  const lineAlpha =
    orb.stage === 'orbit' ? 0.55
    : orb.stage === 'scan' ? 0.10 + 0.2 * Math.max(0, 1 - ageMs / SCAN_LIFE_MS)
    : orb.stage === 'win-fly' ? 0.5
    : orb.stage === 'loss-fly' ? 0.5
    : 0.05;

  if (lineAlpha > 0.02) {
    const grad = ctx.createLinearGradient(cx, cy, orb.x, orb.y);
    grad.addColorStop(0, withAlpha('#A855F7', lineAlpha * 0.4));
    grad.addColorStop(1, withAlpha(orb.color, lineAlpha));
    ctx.strokeStyle = grad;
    ctx.lineWidth = orb.stage === 'orbit' ? 1.2 : 0.7;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(orb.x, orb.y);
    ctx.stroke();
  }

  const halo = ctx.createRadialGradient(orb.x, orb.y, 0, orb.x, orb.y, orb.radius * 4);
  halo.addColorStop(0, withAlpha(orb.color, 0.55 * alpha));
  halo.addColorStop(1, withAlpha(orb.color, 0));
  ctx.fillStyle = halo;
  ctx.beginPath();
  ctx.arc(orb.x, orb.y, orb.radius * 4, 0, TAU);
  ctx.fill();

  if (orb.stage === 'orbit') {
    ctx.fillStyle = withAlpha(orb.color, alpha);
    ctx.beginPath();
    ctx.arc(orb.x, orb.y, orb.radius, 0, TAU);
    ctx.fill();
    ctx.fillStyle = withAlpha('#FFFFFF', 0.55 * alpha);
    ctx.beginPath();
    ctx.arc(orb.x - orb.radius * 0.35, orb.y - orb.radius * 0.35, orb.radius * 0.4, 0, TAU);
    ctx.fill();
  } else if (orb.stage === 'scan') {
    ctx.strokeStyle = withAlpha(orb.color, alpha);
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.arc(orb.x, orb.y, orb.radius, 0, TAU);
    ctx.stroke();
  } else {
    ctx.fillStyle = withAlpha(orb.color, alpha);
    ctx.beginPath();
    ctx.arc(orb.x, orb.y, orb.radius, 0, TAU);
    ctx.fill();
  }
}

function drawSweep(ctx: CanvasRenderingContext2D, cx: number, cy: number, ts: number, maxR: number) {
  const sweep = (ts / 1500) % 1;
  const r = sweep * maxR * 0.6;
  ctx.strokeStyle = `rgba(168, 85, 247, ${0.18 * (1 - sweep)})`;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, TAU);
  ctx.stroke();
}

function drawSun(ctx: CanvasRenderingContext2D, cx: number, cy: number, t: number) {
  const pulse = 1 + Math.sin(t / 700) * 0.08;
  const halo = ctx.createRadialGradient(cx, cy, 14 * pulse, cx, cy, 140);
  halo.addColorStop(0, 'rgba(168, 85, 247, 0.55)');
  halo.addColorStop(0.4, 'rgba(168, 85, 247, 0.2)');
  halo.addColorStop(1, 'rgba(168, 85, 247, 0)');
  ctx.fillStyle = halo;
  ctx.beginPath();
  ctx.arc(cx, cy, 140, 0, TAU);
  ctx.fill();
  const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, 22 * pulse);
  core.addColorStop(0, '#FFFFFF');
  core.addColorStop(0.4, '#A855F7');
  core.addColorStop(1, 'rgba(168, 85, 247, 0)');
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(cx, cy, 28 * pulse, 0, TAU);
  ctx.fill();
  ctx.fillStyle = 'rgba(255,255,255,0.85)';
  ctx.font = "600 11px ui-monospace, monospace";
  ctx.textAlign = 'center';
  ctx.fillText('KRYPT', cx, cy + 4);
}

function withAlpha(hex: string, alpha: number): string {
  const m = hex.replace('#', '');
  const r = parseInt(m.slice(0, 2), 16);
  const g = parseInt(m.slice(2, 4), 16);
  const b = parseInt(m.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}


function Mini({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'bad' | 'purple' | 'pink' }) {
  const cn = (() => {
    switch (tone) {
      case 'good': return 'text-krypt-win';
      case 'bad': return 'text-krypt-loss';
      case 'purple': return 'text-krypt-purple';
      case 'pink': return 'text-krypt-pink';
      default: return 'text-white';
    }
  })();
  return (
    <div className="rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-krypt-muted">{label}</div>
      <div className={cls('font-mono text-sm', cn)}>{value}</div>
    </div>
  );
}

function LegendDot({ color, label, outline }: { color: string; label: string; outline?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className="h-2 w-2 rounded-full"
        style={{
          background: outline ? 'transparent' : color,
          boxShadow: `0 0 6px ${color}`,
          border: outline ? `1px solid ${color}` : 'none',
        }}
      />
      <span>{label}</span>
    </div>
  );
}

interface BucketTileProps {
  tone: 'good' | 'bad';
  label: string;
  count: number;
  pnl: number;
  icon: React.ComponentType<{ className?: string }>;
}

function BucketTile({ tone, label, count, pnl, icon: Icon }: BucketTileProps) {
  const bg = tone === 'good'
    ? 'border-krypt-win/50 bg-krypt-win/10 text-krypt-win'
    : 'border-krypt-loss/50 bg-krypt-loss/10 text-krypt-loss';
  return (
    <div className={cls('flex items-center gap-3 rounded-xl border px-4 py-3 backdrop-blur', bg)}>
      <div className={cls(
        'grid h-9 w-9 place-items-center rounded-lg',
        tone === 'good' ? 'bg-krypt-win/20' : 'bg-krypt-loss/20',
      )}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex-1">
        <div className="text-[10px] uppercase tracking-wider opacity-70">{label}</div>
        <div className="font-mono text-base">{count} · {fmtUsd(pnl, { sign: true })}</div>
      </div>
    </div>
  );
}

function TradeRow({ p }: { p: BotPosition }) {
  const tone = p.resolved
    ? p.outcomeCorrect === 1 ? 'text-krypt-win'
    : p.outcomeCorrect === 0 ? 'text-krypt-loss'
    : 'text-krypt-muted'
    : 'text-krypt-muted';
  return (
    <div className="flex items-center gap-2 border-t border-krypt-border py-1.5 first:border-t-0 text-xs">
      <span
        className="h-2 w-2 rounded-full"
        style={{ background: p.signalSource === 'whale' ? '#A855F7' : '#EC4899' }}
      />
      <span className="font-mono text-krypt-muted">{p.ticker.split('-').pop() || p.ticker}</span>
      <span className="ml-auto truncate text-krypt-dim">{p.title}</span>
      <span className={cls('min-w-[60px] text-right font-mono', tone)}>
        {p.resolved ? fmtUsd(p.pnlUsd ?? 0, { sign: true }) : '—'}
      </span>
    </div>
  );
}
