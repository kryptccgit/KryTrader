import { useEffect, useLayoutEffect, useMemo, useRef, type RefObject } from 'react';
import {
  animateGlassValue, cubicBezier, glassValue, useLensWobble, type GlassAnimation,
} from '@samasante/liquid-glass';

const GLIDE = cubicBezier(0.34, 1.36, 0.42, 1);
const GLIDE_S = 0.5;

export function useGlideLens(
  container: RefObject<HTMLElement>,
  lens: RefObject<HTMLElement | null>,
  activeKey: string | null,
  axis: 'x' | 'y',
  deps: unknown[] = [],
): void {
  const mv = useMemo(() => ({
    x: glassValue(0), y: glassValue(0), w: glassValue(0), h: glassValue(0),
    stretch: glassValue(0),
    travel: glassValue(0),
  }), []);
  const layout = useRef({ w: 0, h: 0, shown: false });
  const anims = useRef<GlassAnimation[]>([]);
  const holdRef = useRef(0);
  const kickRef = useRef<() => void>(() => {});
  const composeRef = useRef<() => void>(() => {});
  useLensWobble(mv.travel, mv.stretch, holdRef, kickRef);

  useEffect(() => {
    const compose = (): void => {
      const el = lens.current;
      const L = layout.current;
      if (!el || !L.w || !L.h) return;
      const s = mv.stretch.get();
      const w = mv.w.get();
      const h = mv.h.get();
      const along = 1 + 0.3 * s;
      const across = 1 - 0.22 * s;
      const sx = (w / L.w) * (axis === 'x' ? along : across);
      const sy = (h / L.h) * (axis === 'y' ? along : across);
      const tx = mv.x.get() + (w - L.w) / 2;
      const ty = mv.y.get() + (h - L.h) / 2;
      el.style.transform = `translate3d(${tx}px, ${ty}px, 0) scale(${sx}, ${sy})`;
    };
    composeRef.current = compose;
    compose();
    const offs = [mv.x, mv.y, mv.w, mv.h, mv.stretch].map((v) => v.on('change', compose));
    return () => offs.forEach((off) => off());
  }, [lens, mv, axis]);

  useLayoutEffect(() => {
    const root = container.current;
    const el = lens.current;
    if (!root || !el || typeof ResizeObserver === 'undefined') return;

    const place = (animate: boolean): void => {
      const target = activeKey == null
        ? null
        : root.querySelector<HTMLElement>(`[data-glass-key="${CSS.escape(activeKey)}"]`);
      const L = layout.current;
      if (!target || !target.offsetWidth) {
        el.style.opacity = '0';
        L.shown = false;
        return;
      }
      const x = target.offsetLeft;
      const y = target.offsetTop;
      const w = target.offsetWidth;
      const h = target.offsetHeight;
      anims.current.forEach((a) => a.stop());
      anims.current = [];
      const commitSize = (): void => {
        if (L.w === w && L.h === h) return;
        L.w = w; L.h = h;
        el.style.width = `${w}px`;
        el.style.height = `${h}px`;
        composeRef.current();
      };
      if (!animate || !L.shown) {
        commitSize();
        mv.x.set(x); mv.y.set(y); mv.w.set(w); mv.h.set(h);
        mv.travel.set(axis === 'x' ? x : y);
        composeRef.current();
        el.style.opacity = '1';
        L.shown = true;
        return;
      }
      const opts = { duration: GLIDE_S, ease: GLIDE };
      anims.current = [
        animateGlassValue(mv.x, x, opts),
        animateGlassValue(mv.y, y, opts),
        animateGlassValue(mv.w, w, opts),
        animateGlassValue(mv.h, h, { ...opts, onComplete: commitSize }),
        animateGlassValue(mv.travel, axis === 'x' ? x : y, opts),
      ];
    };

    place(true);
    const seen = new Map<Element, string>();
    const ro = new ResizeObserver((entries) => {
      let changed = false;
      for (const e of entries) {
        const k = `${Math.round(e.contentRect.width)}x${Math.round(e.contentRect.height)}`;
        if (seen.has(e.target) && seen.get(e.target) !== k) changed = true;
        seen.set(e.target, k);
      }
      if (changed) place(false);
    });
    ro.observe(root);
    const target = activeKey == null ? null
      : root.querySelector<HTMLElement>(`[data-glass-key="${CSS.escape(activeKey)}"]`);
    if (target) ro.observe(target);
    return () => ro.disconnect();
  }, [activeKey, axis, ...deps]);

  useEffect(() => () => anims.current.forEach((a) => a.stop()), []);
}
