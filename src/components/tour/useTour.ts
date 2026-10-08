import { createContext, useContext } from 'react';
import type { TourSide } from './tourSteps';

export interface GuideApi {
  startTour: () => void;
  replayOnboarding: () => void;
}

const noop = (): void => {};
export const GuideContext = createContext<GuideApi>({ startTour: noop, replayOnboarding: noop });
export const useGuide = (): GuideApi => useContext(GuideContext);

export const TOUR_OFFERED_KEY = 'krypt.tour.offered';

export function wasTourOffered(): boolean {
  try { return localStorage.getItem(TOUR_OFFERED_KEY) === '1'; } catch { return false; }
}

export function markTourOffered(): void {
  try { localStorage.setItem(TOUR_OFFERED_KEY, '1'); } catch {}
}

export interface Box { top: number; left: number; width: number; height: number }
export interface Placement { top: number; left: number; side: TourSide | 'center' }

export const TOP_INSET = 44;
const GAP = 14;
const MARGIN = 12;

const clamp = (v: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, v));

export function placeCard(
  t: Box,
  card: { width: number; height: number },
  vp: { width: number; height: number },
  prefer: TourSide[] = ['right', 'left', 'bottom', 'top'],
): Placement {
  const maxTop = Math.max(TOP_INSET, vp.height - card.height - MARGIN);
  const maxLeft = Math.max(MARGIN, vp.width - card.width - MARGIN);
  const midY = clamp(t.top + t.height / 2 - card.height / 2, TOP_INSET, maxTop);
  const midX = clamp(t.left + t.width / 2 - card.width / 2, MARGIN, maxLeft);
  for (const side of prefer) {
    if (side === 'right') {
      const left = t.left + t.width + GAP;
      if (left + card.width <= vp.width - MARGIN) return { side, left, top: midY };
    } else if (side === 'left') {
      const left = t.left - GAP - card.width;
      if (left >= MARGIN) return { side, left, top: midY };
    } else if (side === 'bottom') {
      const top = t.top + t.height + GAP;
      if (top + card.height <= vp.height - MARGIN) return { side, top: Math.max(top, TOP_INSET), left: midX };
    } else {
      const top = t.top - GAP - card.height;
      if (top >= TOP_INSET) return { side, top, left: midX };
    }
  }
  return {
    side: 'center',
    top: clamp((vp.height - card.height) / 2, TOP_INSET, maxTop),
    left: clamp((vp.width - card.width) / 2, MARGIN, maxLeft),
  };
}

export function findTarget(id: string): HTMLElement | null {
  const el = document.querySelector<HTMLElement>(`[data-tour="${id}"]`);
  if (!el) return null;
  const check = (el as HTMLElement & { checkVisibility?: () => boolean }).checkVisibility;
  if (typeof check === 'function' && !check.call(el)) return null;
  return el;
}

export function revealTarget(el: HTMLElement): void {
  let p = el.parentElement;
  while (p && p !== document.body) {
    const oy = getComputedStyle(p).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight) {
      const pr = p.getBoundingClientRect();
      const er = el.getBoundingClientRect();
      if (er.top < pr.top + 8 || er.bottom > pr.bottom - 8) {
        p.scrollTop += (er.top + er.height / 2) - (pr.top + pr.height / 2);
      }
      return;
    }
    p = p.parentElement;
  }
}
