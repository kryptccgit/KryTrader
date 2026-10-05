import { useEffect, useRef } from 'react';
import type { CSSProperties } from 'react';
import spriteUrl from '../assets/mossy.png';

const FRAMES = 8;
const DURATION = 900;

interface KryptSpriteProps {
  size?: number;
  pet?: boolean;
  className?: string;
  style?: CSSProperties;
  title?: string;
}

export function KryptSprite({ size = 48, pet = false, className, style, title }: KryptSpriteProps) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof el.animate !== 'function') return;
    const anim = el.animate(
      [
        { backgroundPositionX: '0px' },
        { backgroundPositionX: `${-FRAMES * size}px` },
      ],
      { duration: DURATION, iterations: Infinity, easing: `steps(${FRAMES})` },
    );
    return () => anim.cancel();
  }, [size]);

  return (
    <span
      ref={ref}
      role="img"
      aria-label={title ?? 'Krypt mascot'}
      title={title}
      className={`krypt-sprite${pet ? ' krypt-pet' : ''}${className ? ` ${className}` : ''}`}
      style={{
        width: size,
        height: size,
        backgroundImage: `url(${spriteUrl})`,
        backgroundRepeat: 'no-repeat',
        backgroundSize: `${FRAMES * size}px ${size}px`,
        ...style,
      }}
    />
  );
}
