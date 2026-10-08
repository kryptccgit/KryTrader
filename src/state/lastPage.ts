
export type PageId =
  | 'dashboard' | 'strategies' | 'positions' | 'signals' | 'history'
  | 'profiles' | 'settings' | 'api' | 'logs' | 'guide' | 'about'
  | 'visualizer' | 'crypto15m' | 'perps' | 'backtest' | 'scripts'
  | 'terminal' | 'terminalPortfolio' | 'privacy' | 'remote' | 'aiAgents';

export const PAGE_IDS: readonly PageId[] = [
  'dashboard', 'strategies', 'positions', 'signals', 'history', 'profiles', 'settings', 'api', 'logs',
  'guide', 'about', 'visualizer', 'crypto15m', 'perps', 'backtest', 'scripts', 'terminal',
  'terminalPortfolio', 'privacy', 'remote', 'aiAgents',
];

export const LAST_PAGE_KEY = 'krypt.lastPage';

export const FRONT_DOOR: PageId = 'aiAgents';

export function isPageId(v: unknown): v is PageId {
  return typeof v === 'string' && (PAGE_IDS as readonly string[]).includes(v);
}

export function loadLastPage(): PageId {
  try {
    const v = window.localStorage.getItem(LAST_PAGE_KEY);
    if (isPageId(v)) return v;
    if (v !== null) window.localStorage.removeItem(LAST_PAGE_KEY);
  } catch {}
  return FRONT_DOOR;
}

export function saveLastPage(p: PageId): void {
  try { window.localStorage.setItem(LAST_PAGE_KEY, p); } catch {}
}

export function forgetLastPage(): void {
  try { window.localStorage.removeItem(LAST_PAGE_KEY); } catch {}
}
