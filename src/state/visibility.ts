import { useEffect, useState } from 'react';


type Listener = (visible: boolean) => void;

let mainVisible = true;
let current = true;
let wired = false;
const listeners = new Set<Listener>();

function docHidden(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden';
}

function recompute(): void {
  const next = mainVisible && !docHidden();
  if (next === current) return;
  current = next;
  try { document.documentElement.toggleAttribute('data-window-hidden', !next); } catch {}
  listeners.forEach((l) => { try { l(next); } catch {} });
}

function wire(): void {
  if (wired || typeof window === 'undefined') return;
  wired = true;
  document.addEventListener('visibilitychange', recompute);
  const w = window.krypt?.window;
  w?.onVisibility?.((v) => { mainVisible = !!v; recompute(); });
  void w?.isVisible?.().then((v) => { mainVisible = !!v; recompute(); }).catch(() => {});
  recompute();
}

export function isWindowVisible(): boolean {
  return current;
}

export function onWindowVisibility(cb: Listener): () => void {
  wire();
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

export function useWindowVisibility(): boolean {
  const [visible, setVisible] = useState(current);
  useEffect(() => {
    const off = onWindowVisibility(setVisible);
    setVisible(current);
    return off;
  }, []);
  return visible;
}

export function __resetWindowVisibilityForTests(): void {
  mainVisible = true;
  current = true;
  wired = false;
  listeners.clear();
  try { document.documentElement.removeAttribute('data-window-hidden'); } catch {}
}
