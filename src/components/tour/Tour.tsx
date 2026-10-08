import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, ArrowRight, CornerDownRight, X } from 'lucide-react';
import type { PageId } from '../../state/lastPage';
import { GlassPanel } from '../glass/GlassPanel';
import { GlassButton } from '../glass/GlassButton';
import { GLASS_TINTS } from '../glass/glassPresets';
import { TOUR_STEPS, type TourStep } from './tourSteps';
import { findTarget, placeCard, revealTarget, type Box, type Placement } from './useTour';

const CARD_W = 320;
const PAD = 4;

export function Tour({
  open, onClose, onNavigate, steps = TOUR_STEPS,
}: {
  open: boolean;
  onClose: () => void;
  onNavigate: (page: PageId) => void;
  steps?: TourStep[];
}) {
  const [curId, setCurId] = useState<string | null>(null);
  const [rect, setRect] = useState<Box | null>(null);
  const [place, setPlace] = useState<Placement | null>(null);
  const [avail, setAvail] = useState<string[]>([]);
  const cardRef = useRef<HTMLDivElement>(null);
  const curRef = useRef<string | null>(null);
  curRef.current = curId;
  const dirRef = useRef<1 | -1>(1);
  const returnFocus = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const bodyId = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  const step = steps.find((s) => s.id === curId) ?? null;

  const close = useCallback((): void => {
    setCurId(null);
    onCloseRef.current();
  }, []);

  const scan = useCallback((from: number, dir: 1 | -1): string | null => {
    const all = stepsRef.current;
    for (let i = from; i >= 0 && i < all.length; i += dir) {
      if (findTarget(all[i].id)) return all[i].id;
    }
    return null;
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    returnFocus.current = document.activeElement as HTMLElement | null;
    dirRef.current = 1;
    const first = scan(0, 1);
    if (!first) { onCloseRef.current(); return undefined; }
    setCurId(first);
    return () => {
      setCurId(null);
      setRect(null);
      setPlace(null);
      const back = returnFocus.current;
      if (back && document.contains(back)) back.focus();
    };
  }, [open, scan]);

  const move = useCallback((dir: 1 | -1): void => {
    const i = stepsRef.current.findIndex((s) => s.id === curRef.current);
    const nextId = scan(i + dir, dir);
    if (nextId) {
      dirRef.current = dir;
      setCurId(nextId);
    } else if (dir === 1) {
      close();
    }
  }, [scan, close]);

  const measure = useCallback((): void => {
    const s = stepsRef.current.find((x) => x.id === curRef.current);
    const el = s ? findTarget(s.id) : null;
    if (!s || !el) return;
    const r = el.getBoundingClientRect();
    const box: Box = { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 };
    const card = cardRef.current;
    setRect(box);
    setPlace(placeCard(
      box,
      { width: card?.offsetWidth || CARD_W, height: card?.offsetHeight || 200 },
      { width: window.innerWidth, height: window.innerHeight },
      s.prefer,
    ));
  }, []);

  useLayoutEffect(() => {
    if (!open || !curId) return;
    const el = findTarget(curId);
    if (!el) { move(dirRef.current); return; }
    setAvail(stepsRef.current.filter((s) => findTarget(s.id)).map((s) => s.id));
    revealTarget(el);
    measure();
    cardRef.current?.focus({ preventScroll: true });
  }, [open, curId, move, measure]);

  useEffect(() => {
    if (!open) return undefined;
    let raf = 0;
    const onChange = (): void => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; measure(); });
    };
    window.addEventListener('resize', onChange);
    window.addEventListener('scroll', onChange, true);
    return () => {
      window.removeEventListener('resize', onChange);
      window.removeEventListener('scroll', onChange, true);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [open, measure]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent): void => {
      const t = e.target as HTMLElement | null;
      if (e.key === 'Escape') {
        e.preventDefault(); e.stopPropagation(); close();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault(); e.stopPropagation(); move(1);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault(); e.stopPropagation(); move(-1);
      } else if (e.key === 'Enter') {
        if (t?.closest?.('button, a, input, textarea, select')) return;
        e.preventDefault(); e.stopPropagation(); move(1);
      } else if (e.key === 'Tab') {
        const card = cardRef.current;
        if (!card) return;
        const items = Array.from(card.querySelectorAll<HTMLElement>('button:not([disabled])'));
        if (!items.length) return;
        const at = items.indexOf(document.activeElement as HTMLElement);
        const nextAt = e.shiftKey ? (at <= 0 ? items.length - 1 : at - 1) : (at + 1) % items.length;
        e.preventDefault();
        items[nextAt].focus();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [open, move, close]);

  if (!open || !step) return null;

  const pos = avail.indexOf(step.id);
  const total = avail.length || steps.length;
  const isFirst = pos <= 0;
  const isLast = pos === avail.length - 1;
  const goThere = (): void => {
    if (step.page) onNavigate(step.page);
    move(1);
  };

  return createPortal(
    <div className="fixed inset-0 z-[80]" data-testid="tour">
      <div
        className="absolute inset-0"
        aria-hidden
        onMouseDown={(e) => { e.preventDefault(); cardRef.current?.focus({ preventScroll: true }); }}
      />
      {rect ? (
        <div
          aria-hidden
          data-testid="tour-ring"
          className="pointer-events-none absolute rounded-[12px] motion-safe:transition-[top,left,width,height] motion-safe:duration-300 motion-safe:ease-out"
          style={{
            top: rect.top, left: rect.left, width: rect.width, height: rect.height,
            boxShadow: '0 0 0 2px rgba(168,85,247,0.95), 0 0 24px 2px rgba(168,85,247,0.5), 0 0 0 9999px rgba(5,4,12,0.68)',
          }}
        />
      ) : (
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[rgba(5,4,12,0.68)]" />
      )}

      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        data-side={place?.side}
        className="absolute outline-none motion-safe:transition-[top,left] motion-safe:duration-300 motion-safe:ease-out"
        style={{
          width: CARD_W, maxWidth: 'calc(100vw - 24px)',
          top: place?.top ?? 0, left: place?.left ?? 0,
          visibility: place ? 'visible' : 'hidden',
        }}
      >
        <GlassPanel
          preset="card"
          tint={GLASS_TINTS.modal}
          className="rounded-2xl border border-white/[0.08] p-4 glass-pop motion-reduce:[animation:none]"
          style={{ boxShadow: '0 0 60px -18px rgba(168,85,247,0.6), var(--glass-shadow)' }}
        >
          <div className="flex items-center gap-2">
            <span className="text-[9px] font-semibold uppercase tracking-[0.18em] text-krypt-purple">
              {step.group}
            </span>
            <span className="ml-auto font-mono text-[11px] tabular-nums text-krypt-muted" data-testid="tour-count">
              {pos + 1} / {total}
            </span>
            <button
              type="button"
              onClick={close}
              aria-label="Close tour"
              className="-mr-1 grid h-6 w-6 place-items-center rounded-md text-krypt-dim transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-krypt-purple/60"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="mt-1.5 h-0.5 overflow-hidden rounded-full bg-white/[0.06]" aria-hidden>
            <div
              className="h-full rounded-full bg-krypt-glow motion-safe:transition-[width] motion-safe:duration-300"
              style={{ width: `${((pos + 1) / total) * 100}%` }}
            />
          </div>

          <h2 id={titleId} className="mt-3 text-base font-semibold text-white">{step.title}</h2>
          <p id={bodyId} className="mt-1 text-[13px] leading-relaxed text-white/80">{step.body}</p>

          {step.page && (
            <button
              type="button"
              onClick={goThere}
              data-testid="tour-go"
              className="mt-2 inline-flex items-center gap-1 rounded text-xs font-medium text-krypt-purple hover:text-white hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-krypt-purple/60"
            >
              <CornerDownRight className="h-3.5 w-3.5" /> Go there
            </button>
          )}

          <div className="mt-4 flex items-center gap-2">
            <button type="button" onClick={close} className="krypt-btn-ghost px-2 text-xs text-krypt-muted">
              Skip tour
            </button>
            <div className="ml-auto flex items-center gap-2">
              {!isFirst && (
                <button type="button" onClick={() => move(-1)} className="krypt-btn-default px-2.5 text-xs">
                  <ArrowLeft className="h-3.5 w-3.5" /> Back
                </button>
              )}
              <GlassButton variant="primary" onClick={() => move(1)} className="px-3 py-1.5 text-xs" data-testid="tour-next">
                {isLast ? 'Done' : <>Next <ArrowRight className="h-3.5 w-3.5" /></>}
              </GlassButton>
            </div>
          </div>
          <div className="mt-2 text-[10px] text-krypt-dim">
            Arrow keys to move · Esc to close
          </div>
        </GlassPanel>
      </div>
    </div>,
    document.body,
  );
}
