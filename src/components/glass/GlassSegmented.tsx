import { useRef, type ReactNode } from 'react';
import { cls } from '../../utils/format';
import { GlassPanel } from './GlassPanel';
import { GLASS_TINTS } from './glassPresets';
import { useGlideLens } from './useGlideLens';

export function GlassLens({
  lensRef, className, tint = GLASS_TINTS.pill, radius,
}: {
  lensRef: React.MutableRefObject<HTMLDivElement | null>;
  className?: string;
  tint?: string;
  radius?: number;
}) {
  return (
    <GlassPanel
      ref={lensRef}
      preset="pill"
      tint={tint}
      aria-hidden
      className={cls('glass-lens pointer-events-none', className)}
      style={{
        position: 'absolute', left: 0, top: 0, zIndex: 2, opacity: 0,
        transformOrigin: '50% 50%', willChange: 'transform',
        borderRadius: radius ?? 10,
      }}
    />
  );
}

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
  title?: string;
}

export function GlassSegmented<T extends string>({
  value, onChange, options, size = 'sm', className, wrap, lensTint,
}: {
  value: T;
  onChange: (v: T) => void;
  options: SegmentOption<T>[];
  size?: 'xs' | 'sm';
  className?: string;
  wrap?: boolean;
  lensTint?: string;
}) {
  const track = useRef<HTMLDivElement>(null);
  const lens = useRef<HTMLDivElement | null>(null);
  useGlideLens(track, lens, value, 'x', [options.length]);
  return (
    <div
      ref={track}
      role="tablist"
      className={cls(
        'glass-track relative inline-flex items-center gap-0.5 rounded-xl p-[3px]',
        wrap && 'flex-wrap',
        className,
      )}
    >
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={on}
            data-glass-key={o.value}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={cls(
              'relative z-[1] flex items-center gap-1.5 whitespace-nowrap rounded-[10px] font-medium transition-colors duration-200',
              size === 'xs' ? 'px-2.5 py-1 text-[11px]' : 'px-3 py-1.5 text-xs',
              on ? 'text-white' : 'text-krypt-muted hover:bg-white/[0.04] hover:text-white',
            )}
          >
            {o.icon}
            {o.label}
          </button>
        );
      })}
      <GlassLens lensRef={lens} tint={lensTint} />
    </div>
  );
}
