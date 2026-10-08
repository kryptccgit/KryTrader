import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Footprints, Maximize2, Minimize2, Route, Undo2 } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import type { AutopilotStatus } from '@shared/market';
import type { HubData } from './data';
import {
  REPLAY_WINDOW_MS, activityBus, replayPlan, type ActivityRecord,
} from '../state/activity';
import { loadSavedBacktests, type SavedBacktest } from './library';
import { PaydayTracker, type PaydayEvent } from './payday';
import { subject } from './text';
import { isWindowVisible, onWindowVisibility } from '../state/visibility';
import { GlassButton } from '../components/glass/GlassButton';
import { GlassPanel } from '../components/glass/GlassPanel';
import { userMessage } from '../utils/errors';


export interface HubSceneEngine {
  fps: number;
  start(): void;
  stop(): void;
  ingest(d: HubData): void;
  setOutput(canvas: HTMLCanvasElement, w: number, h: number, mode: 'page' | 'cinema'): void;
  payday(ev: PaydayEvent): void;
  activity(rec: ActivityRecord, replay: boolean): void;
  scriptLog?(name: string | null, lines: string[]): void;
  setTour(on: boolean): void;
  resetView(): void;
  onTourChange: ((on: boolean) => void) | null;
  onFocusChange: ((label: string | null) => void) | null;
  setWalk?(on: boolean): void;
  onWalkChange?: ((on: boolean) => void) | null;
  escape?(): boolean;
  dispose(): void;
}

interface Props {
  create: (canvas: HTMLCanvasElement, w: number, h: number) => HubSceneEngine;
  hint: string;
  loading: string;
  tourLabel: string;
  tourTitle: string;
  frameBg: string;
  wantsAutopilot?: boolean;
  extra?: Partial<HubData>;
  controls?: ReactNode;
}

const AUTOPILOT_POLL_MS = 20_000;

const IDLE_HIDE_MS = 2_200;

async function fontsReady(): Promise<void> {
  const loads = [
    '700 40px "Chakra Petch"', '600 20px "Chakra Petch"', '600 20px "JetBrains Mono"',
    '500 20px "JetBrains Mono"', '400 20px "Press Start 2P"',
  ].map((f) => document.fonts.load(f).catch(() => []));
  await Promise.race([Promise.all(loads), new Promise((r) => setTimeout(r, 1500))]);
}

function dpr(): number {
  return Math.min(2, window.devicePixelRatio || 1);
}

export function HubStage({ create, hint, loading, tourLabel, tourTitle, frameBg, wantsAutopilot, extra, controls: sceneControls }: Props) {
  const { signals, positions, account, scannerStats, config } = useApp();
  const createRef = useRef(create);
  const paydayRef = useRef(new PaydayTracker());
  const [library, setLibrary] = useState<SavedBacktest[]>([]);
  const [autopilot, setAutopilot] = useState<AutopilotStatus | null | undefined>(undefined);

  const wrapRef = useRef<HTMLDivElement>(null);
  const pageCanvas = useRef<HTMLCanvasElement>(null);
  const fullCanvas = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<HubSceneEngine | null>(null);
  const mountedRef = useRef(true);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [tour, setTour] = useState(false);
  const [fps, setFps] = useState(0);
  const [full, setFull] = useState(false);
  const [walk, setWalk] = useState(false);
  const [canWalk, setCanWalk] = useState(false);
  const [walkHint, setWalkHint] = useState(false);
  const [controls, setControls] = useState(true);
  const hideTimer = useRef<number>(0);
  const hovering = useRef(false);

  const pageSize = useCallback((): [number, number] => {
    const el = wrapRef.current;
    return [Math.max(64, (el?.clientWidth ?? 800) * dpr()), Math.max(64, (el?.clientHeight ?? 500) * dpr())];
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    let engine: HubSceneEngine | null = null;
    let cancelled = false;
    void fontsReady().then(() => {
      if (cancelled || !pageCanvas.current) return;
      try {
        const [w, h] = pageSize();
        engine = createRef.current(pageCanvas.current, w, h);
      } catch (e) {
        setError(userMessage(e));
        return;
      }
      engine.onFocusChange = (r) => { if (mountedRef.current) setFocused(r); };
      engine.onTourChange = (on) => { if (mountedRef.current) setTour(on); };
      engine.onWalkChange = (on) => { if (mountedRef.current) setWalk(on); };
      setCanWalk(typeof engine.setWalk === 'function');
      engineRef.current = engine;
      if (import.meta.env.DEV) (window as unknown as { __agentHub?: HubSceneEngine }).__agentHub = engine;
      if (isWindowVisible()) engine.start();
      setReady(true);
    });
    const fpsI = window.setInterval(() => setFps(engineRef.current?.fps ?? 0), 500);
    return () => {
      cancelled = true;
      mountedRef.current = false;
      window.clearInterval(fpsI);
      engine?.dispose();
      engineRef.current = null;
      setReady(false);
    };
  }, [pageSize]);

  useEffect(() => {
    if (!ready) return;
    const apply = (visible: boolean) => {
      const e = engineRef.current;
      if (!e) return;
      if (visible) e.start();
      else e.stop();
    };
    apply(isWindowVisible());
    return onWindowVisibility(apply);
  }, [ready]);

  useEffect(() => {
    let alive = true;
    void loadSavedBacktests().then((rows) => { if (alive) setLibrary(rows); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!wantsAutopilot) return;
    let alive = true;
    const pull = async () => {
      try {
        const s = await window.krypt.terminal.autopilotStatus();
        if (alive) setAutopilot(s ?? null);
      } catch {
        if (alive) setAutopilot(null);
      }
    };
    void pull();
    const i = window.setInterval(pull, AUTOPILOT_POLL_MS);
    return () => { alive = false; window.clearInterval(i); };
  }, [wantsAutopilot]);

  useEffect(() => {
    engineRef.current?.ingest({ signals, positions, account, scannerStats, config, library, autopilot, ...extra });
  }, [signals, positions, account, scannerStats, config, library, autopilot, extra, ready]);

  const scriptNames = useRef(new Map<string, string>());
  useEffect(() => {
    if (!ready) return;
    const seen = new Set<number>();
    const deliver = (rec: ActivityRecord, replay: boolean) => {
      if (seen.has(rec.seq)) return;
      seen.add(rec.seq);
      if (rec.ev.kind === 'script' && rec.ev.id && rec.ev.name) scriptNames.current.set(rec.ev.id, rec.ev.name);
      engineRef.current?.activity(rec, replay);
    };
    const recent = activityBus.recent(REPLAY_WINDOW_MS);
    for (const r of recent) if (r.ev.kind === 'script' && r.ev.id && r.ev.name) scriptNames.current.set(r.ev.id, r.ev.name);
    const timers = replayPlan(recent).map(({ rec, delayMs }) => window.setTimeout(() => deliver(rec, true), delayMs));
    const off = activityBus.subscribe((rec) => deliver(rec, false));
    const offLog = window.krypt?.scripts?.onLog?.((d) => {
      try {
        engineRef.current?.scriptLog?.(scriptNames.current.get(d.id) ?? null, Array.isArray(d.lines) ? d.lines : []);
      } catch {}
    });
    return () => {
      off();
      offLog?.();
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, [ready]);

  useEffect(() => {
    const ev = paydayRef.current.check(positions, account, (p) => subject(p.ticker, p.title), performance.now());
    if (ev) engineRef.current?.payday(ev);
  }, [positions, account]);

  const fullSize = useCallback((): [number, number] => [window.innerWidth * dpr(), window.innerHeight * dpr()], []);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const e = engineRef.current;
      if (!e || full || !pageCanvas.current) return;
      const [w, h] = pageSize();
      e.setOutput(pageCanvas.current, w, h, 'page');
    });
    ro.observe(el);
    const onResize = () => {
      const e = engineRef.current;
      if (!e || !full || !fullCanvas.current) return;
      const [w, h] = fullSize();
      e.setOutput(fullCanvas.current, w, h, 'cinema');
    };
    window.addEventListener('resize', onResize);
    return () => { ro.disconnect(); window.removeEventListener('resize', onResize); };
  }, [full, pageSize, fullSize, ready]);

  useEffect(() => {
    const e = engineRef.current;
    if (!e || !ready) return;
    if (full && fullCanvas.current) {
      const [w, h] = fullSize();
      e.setOutput(fullCanvas.current, w, h, 'cinema');
    } else if (!full && pageCanvas.current) {
      const [w, h] = pageSize();
      e.setOutput(pageCanvas.current, w, h, 'page');
    }
  }, [full, ready, pageSize, fullSize]);

  useEffect(() => { engineRef.current?.setTour(tour); }, [tour, ready]);
  useEffect(() => { engineRef.current?.setWalk?.(walk); }, [walk, ready]);
  useEffect(() => {
    if (!walk) { setWalkHint(false); return; }
    setWalkHint(true);
    const t = window.setTimeout(() => setWalkHint(false), 5000);
    return () => window.clearTimeout(t);
  }, [walk]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.key === 'Escape') {
        if (engineRef.current?.escape?.()) return;
        if (walk) { setWalk(false); return; }
        if (full) setFull(false);
        else { setTour(false); engineRef.current?.resetView(); }
        return;
      }
      if (!full) return;
      if (e.key.toLowerCase() === 't') setTour((v) => !v);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [full, walk]);

  const poke = useCallback(() => {
    setControls(true);
    window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => { if (!hovering.current) setControls(false); }, IDLE_HIDE_MS);
  }, []);
  useEffect(() => { if (full) poke(); return () => window.clearTimeout(hideTimer.current); }, [full, poke]);

  const hover = { onMouseEnter: () => { hovering.current = true; }, onMouseLeave: () => { hovering.current = false; } };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-krypt-dim">
          {walk ? 'walking · click to look · WASD move · ← → turn · E talk · Shift run · wheel zoom · EXIT door or Esc' : hint}{ready ? ` · ${fps} fps` : ''}
        </span>
        {focused && (
          <GlassButton
            live={false}
            variant="active"
            onClick={() => engineRef.current?.resetView()}
            className="px-2.5 py-1 text-xs"
          >
            <Undo2 className="h-3.5 w-3.5" /> Back <span className="text-white/50">· following {focused} · Esc</span>
          </GlassButton>
        )}
        <div className="ml-auto flex items-center gap-2">
          {sceneControls}
          {canWalk && <WalkBtn walk={walk} setWalk={setWalk} />}
          <Controls tour={tour} setTour={setTour} tourLabel={tourLabel} tourTitle={tourTitle} />
          <ToolBtn onClick={() => setFull(true)} title="Fill the window with the scene (Esc to exit)">
            <Maximize2 className="h-3.5 w-3.5" /> Fullscreen
          </ToolBtn>
        </div>
      </div>
      <div
        ref={wrapRef}
        className="relative h-[calc(100vh-292px)] min-h-[440px] overflow-hidden rounded-2xl border border-white/10 shadow-[0_30px_60px_-30px_rgba(0,0,0,0.9),0_0_0_1px_rgba(168,85,247,0.08)]"
        style={{ background: frameBg }}
      >
        <canvas
          ref={pageCanvas}
          className={`absolute inset-0 h-full w-full touch-none ${walk ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing'}`}
          style={{ visibility: full ? 'hidden' : 'visible' }}
        />
        {!full && <WalkHint show={walkHint} />}
        {!ready && !error && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center">
            <div className="animate-pulse font-pixel text-xs text-krypt-purple">{loading}</div>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 grid place-items-center text-sm text-krypt-loss">WebGL could not start: {error}</div>
        )}
      </div>

      {full && createPortal(
        <div
          className="fixed inset-0 z-[66] select-none"
          style={{ WebkitAppRegion: 'no-drag', cursor: controls ? 'default' : 'none', background: frameBg } as CSSProperties}
          onMouseMove={poke}
        >
          <canvas ref={fullCanvas} className="absolute inset-0 h-full w-full touch-none" />
          <WalkHint show={walkHint} />
          <div className="absolute bottom-5 left-1/2 -translate-x-1/2" {...hover}>
            <GlassPanel
              preset="modal"
              display="flex"
              tint="linear-gradient(180deg, rgba(20,16,36,0.34), rgba(8,8,16,0.44))"
              optics={FULL_BAR_OPTICS}
              bendPx={18}
              className={`items-center gap-1 rounded-[22px] p-2 transition-all duration-300 ${controls ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-4 opacity-0'}`}
            >
              {canWalk && <WalkBtn bare walk={walk} setWalk={setWalk} />}
              <Controls bare tour={tour} setTour={setTour} tourLabel={tourLabel} tourTitle={`${tourTitle} (T)`} />
              <ToolBtn bare onClick={() => setFull(false)} title="Exit fullscreen (Esc)">
                <Minimize2 className="h-3.5 w-3.5" /> Exit
              </ToolBtn>
              <span className="px-2 font-mono text-[10px] text-white/60 [text-shadow:0_1px_6px_rgba(0,0,0,0.8)]">{fps} fps · Esc exit · T {tourLabel.toLowerCase()}</span>
            </GlassPanel>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

const FULL_BAR_OPTICS = {
  depth: 0.42, curvature: 0.18, bend: 0.7, bendWidth: 0.22, dispersion: 0.75,
  frost: 6, saturate: 1.8, sheen: 0.6, glow: 0.18,
};

function Controls({ tour, setTour, tourLabel, tourTitle, bare }: {
  tour: boolean; setTour: (fn: (v: boolean) => boolean) => void; tourLabel: string; tourTitle: string;
  bare?: boolean;
}) {
  return (
    <ToolBtn bare={bare} active={tour} onClick={() => setTour((v) => !v)} title={tourTitle}>
      <Route className="h-3.5 w-3.5" /> {tourLabel}
    </ToolBtn>
  );
}

function WalkBtn({ walk, setWalk, bare }: { walk: boolean; setWalk: (fn: (v: boolean) => boolean) => void; bare?: boolean }) {
  return (
    <ToolBtn
      bare={bare}
      active={walk}
      onClick={() => setWalk((v) => !v)}
      title="Walk it in first person: WASD to move, mouse or ← → to look, E to talk to the crew, Shift to run, an EXIT door or Esc to stop"
    >
      <Footprints className="h-3.5 w-3.5" /> Walk
    </ToolBtn>
  );
}

function WalkHint({ show }: { show: boolean }) {
  return (
    <div
      className={`pointer-events-none absolute left-1/2 top-4 -translate-x-1/2 rounded-full border border-white/15 bg-black/55 px-4 py-1.5 font-mono text-[11px] text-white/85 backdrop-blur transition-opacity duration-700 ${show ? 'opacity-100' : 'opacity-0'}`}
    >
      Click to look · WASD move · ← → turn · E talk · Shift run · wheel zoom · EXIT door or Esc to leave
    </div>
  );
}

function ToolBtn({ active, onClick, title, children, bare }: {
  active?: boolean; onClick: () => void; title?: string; children: ReactNode; bare?: boolean;
}) {
  if (bare) {
    return (
      <button
        onClick={onClick}
        title={title}
        className={`flex items-center gap-1.5 rounded-[14px] px-3 py-1.5 text-xs font-medium transition-all active:scale-95 ${active ? 'bg-krypt-purple/35 text-white shadow-[inset_0_0_0_1px_rgba(168,85,247,0.6),0_0_18px_-4px_rgba(168,85,247,0.8)]' : 'text-white/80 hover:bg-white/10 hover:text-white'}`}
      >
        {children}
      </button>
    );
  }
  return (
    <GlassButton live={false} variant={active ? 'active' : 'default'} onClick={onClick} title={title} className="px-2.5 py-1.5 text-xs">
      {children}
    </GlassButton>
  );
}
