import {
  forwardRef, useCallback, useLayoutEffect, useMemo, useRef, useState,
  type CSSProperties, type HTMLAttributes, type ReactNode,
} from 'react';
import { Glass, type GlassOptics } from '@samasante/liquid-glass';
import { cls } from '../../utils/format';
import { GLASS_PRESETS, liveGlassEnabled, type GlassPreset } from './glassPresets';

export interface GlassPanelProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  preset?: GlassPreset;
  live?: boolean;
  tint?: string;
  optics?: Partial<GlassOptics>;
  bendPx?: number;
  display?: CSSProperties['display'];
  children?: ReactNode;
}

export const GlassPanel = forwardRef<HTMLDivElement, GlassPanelProps>(function GlassPanel({
  preset = 'card', live = true, tint, optics, bendPx, display = 'block',
  className, style, children, ...rest
}, ref) {
  const spec = GLASS_PRESETS[preset];
  const useLive = live && liveGlassEnabled();
  const [strength, setStrength] = useState(0.02);
  const probe = useRef<HTMLSpanElement>(null);
  const setRef = useCallback((el: HTMLDivElement | null) => {
    if (typeof ref === 'function') ref(el);
    else if (ref) ref.current = el;
  }, [ref]);

  useLayoutEffect(() => {
    if (!useLive) return;
    const host = probe.current?.parentElement as HTMLDivElement | null;
    if (!host) return;
    setRef(host);
    const px = bendPx ?? spec.bendPx;
    const measure = (): void => {
      const w = host.offsetWidth;
      const h = host.offsetHeight;
      if (!w || !h) return;
      const norm = Math.sqrt((w * w + h * h) / 2);
      const s = Math.round((px / norm) * 2000) / 2000;
      setStrength((prev) => (prev === s ? prev : s));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(host);
    return () => { ro.disconnect(); setRef(null); };
  }, [useLive, bendPx, spec.bendPx, setRef]);

  const merged = useMemo(
    () => ({ ...spec.optics, ...optics, strength }),
    [spec, optics, strength],
  );

  if (!useLive) {
    return (
      <div
        ref={setRef}
        className={cls('glass-frost', className)}
        style={{ display, ...(tint ? { background: tint } : null), ...style }}
        {...rest}
      >
        {children}
      </div>
    );
  }

  return (
    <Glass
      optics={merged}
      className={cls('glass-live', className)}
      style={{ display, ...(tint ? { background: tint } : null), ...style }}
      {...rest}
    >
      {children}
      <span ref={probe} aria-hidden data-lg-layer="" style={{ display: 'none' }} />
    </Glass>
  );
});
