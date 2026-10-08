import type { GlassOptics } from '@samasante/liquid-glass';


export const GLASS_MAP_SIZE = 64;


export type GlassPreset = 'chrome' | 'button' | 'card' | 'pill' | 'modal';

export interface PresetSpec {
  bendPx: number;
  optics: Partial<GlassOptics>;
}

export const GLASS_PRESETS: Record<GlassPreset, PresetSpec> = {
  chrome: {
    bendPx: 9,
    optics: {
      mapSize: GLASS_MAP_SIZE,
      depth: 0.22,
      curvature: 0,
      bend: 0.6,
      bendWidth: 0.1,
      dispersion: 0,
      frost: 22,
      saturate: 1.6,
      sheen: 0.32,
      sheenWidth: 2,
      sheenFalloff: 1.6,
      sheenAngle: 60,
      glow: 0.06,
      glowSpread: 0.6,
      specular: 0.9,
      brightness: 0,
    },
  },
  button: {
    bendPx: 6,
    optics: {
      mapSize: GLASS_MAP_SIZE,
      depth: 0.55,
      curvature: 0.3,
      bend: 0.55,
      bendWidth: 0.2,
      dispersion: 0,
      frost: 4,
      saturate: 1.5,
      sheen: 0.55,
      sheenWidth: 1.5,
      sheenFalloff: 1.4,
      sheenAngle: 50,
      glow: 0.16,
      glowSpread: 0.7,
      specular: 1.1,
      brightness: 0,
    },
  },
  card: {
    bendPx: 10,
    optics: {
      mapSize: GLASS_MAP_SIZE,
      depth: 0.28,
      curvature: 0.08,
      bend: 0.5,
      bendWidth: 0.12,
      dispersion: 0,
      frost: 18,
      saturate: 1.5,
      sheen: 0.38,
      sheenWidth: 2,
      sheenFalloff: 1.5,
      sheenAngle: 55,
      glow: 0.08,
      glowSpread: 0.8,
      specular: 1,
      brightness: 0,
    },
  },
  pill: {
    bendPx: 7,
    optics: {
      mapSize: GLASS_MAP_SIZE,
      depth: 0.3,
      curvature: 0,
      bend: 0.75,
      bendWidth: 0.2,
      dispersion: 0.7,
      frost: 0,
      saturate: 1.25,
      sheen: 0.7,
      sheenWidth: 1.5,
      sheenFalloff: 1.3,
      sheenAngle: 45,
      glow: 0.22,
      glowSpread: 0.6,
      glowFalloff: 0.8,
      specular: 1.15,
      brightness: 0,
    },
  },
  modal: {
    bendPx: 18,
    optics: {
      mapSize: GLASS_MAP_SIZE,
      depth: 0.2,
      curvature: 0.04,
      bend: 0.55,
      bendWidth: 0.08,
      dispersion: 0,
      frost: 12,
      saturate: 1.7,
      sheen: 0.42,
      sheenWidth: 2,
      sheenFalloff: 1.5,
      sheenAngle: 50,
      glow: 0.07,
      glowSpread: 0.6,
      specular: 1,
      brightness: 0,
    },
  },
};

export const GLASS_TINTS = {
  chrome: 'linear-gradient(180deg, rgba(16,14,26,0.74), rgba(8,8,14,0.7))',
  panel: 'linear-gradient(180deg, rgba(20,18,32,0.8), rgba(10,10,17,0.84))',
  card: 'linear-gradient(160deg, rgba(26,24,42,0.8), rgba(12,12,20,0.86))',
  button: 'linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.03))',
  pill: 'linear-gradient(135deg, rgba(99,102,241,0.20), rgba(168,85,247,0.16) 50%, rgba(236,72,153,0.18))',
  modal: 'linear-gradient(170deg, rgba(28,26,44,0.8), rgba(12,12,20,0.86))',
} as const;

let liveFlag: boolean | null = null;
export function liveGlassEnabled(): boolean {
  if (liveFlag !== null) return liveFlag;
  if (typeof ResizeObserver === 'undefined') return (liveFlag = false);
  try {
    liveFlag = localStorage.getItem('krypt.glass') !== 'frost';
  } catch {
    liveFlag = true;
  }
  return liveFlag;
}
