import { createElement, lazy, type ComponentType } from 'react';
import { Gavel, Orbit, Rocket } from 'lucide-react';
import { ErrorBoundary, SceneCrash } from '../components/ErrorBoundary';


export type HubViewId = 'spaceship' | 'council' | 'orbital';

export interface HubView {
  id: HubViewId;
  label: string;
  icon: ComponentType<{ className?: string }>;
  blurb: string;
  scene: ComponentType;
}

export function guarded(load: () => Promise<{ default: ComponentType }>): ComponentType {
  const Scene = lazy(load);
  return function GuardedScene() {
    return createElement(ErrorBoundary, {
      fallback: (error: Error, reset: () => void) => createElement(SceneCrash, { error, onRetry: reset }),
      children: createElement(Scene),
    });
  };
}

export const HUB_VIEWS: HubView[] = [
  {
    id: 'spaceship', label: 'Spaceship', icon: Rocket, scene: guarded(() => import('./SpaceshipView')),
    blurb: 'What really happens, staged live: each AI agent you connect walks to the room of every real tool call it makes, beside the bot crew’s signals, backtests, orders and wins. Idle when nothing is.',
  },
  {
    id: 'council', label: 'The Council', icon: Gavel, scene: guarded(() => import('./CouncilView')),
    blurb: 'Your real forecasters take the seats: their own fair values on each market they called, scored against the price. Under two, six trading emotions argue the bot’s signals instead.',
  },
  {
    id: 'orbital', label: 'Orbital', icon: Orbit, scene: guarded(() => import('./OrbitalView')),
    blurb: 'Every signal the bot sees arrives as a comet; every trade it takes orbits on its price lane until it settles.',
  },
];

const KEY = 'krypt.agentHub.view';

export function loadHubView(): HubViewId {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v && HUB_VIEWS.some((x) => x.id === v)) return v as HubViewId;
  } catch {}
  return 'spaceship';
}

export function saveHubView(id: HubViewId): void {
  try { window.localStorage.setItem(KEY, id); } catch {}
}
