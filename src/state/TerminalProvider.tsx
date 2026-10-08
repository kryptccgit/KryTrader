import {
  createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import { userMessage } from '../utils/errors';

interface TerminalApi {
  activeTicker: string | null;
  watchlist: string[];
  openMarket: (ticker: string) => void;
  closeMarket: () => void;
  toggleWatch: (ticker: string) => void;
  isWatched: (ticker: string) => boolean;
  refreshWatchlist: () => void;
}

const Ctx = createContext<TerminalApi | null>(null);

export function useTerminal(): TerminalApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useTerminal must be inside TerminalProvider');
  return ctx;
}

export function TerminalProvider({ children }: { children: ReactNode }) {
  const [activeTicker, setActiveTicker] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<string[]>([]);

  const watchRef = useRef<string[]>([]);
  watchRef.current = watchlist;

  const refreshWatchlist = useCallback((): void => {
    void window.krypt.terminal
      .watchlist()
      .then(setWatchlist)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshWatchlist();
  }, [refreshWatchlist]);

  const openMarket = useCallback((ticker: string): void => {
    const t = (ticker || '').trim().toUpperCase();
    if (t) setActiveTicker(t);
  }, []);

  const closeMarket = useCallback((): void => setActiveTicker(null), []);

  const toggleWatch = useCallback((ticker: string): void => {
    const t = (ticker || '').trim().toUpperCase();
    if (!t) return;
    const watched = !watchRef.current.includes(t);
    setWatchlist((cur) => (watched ? [t, ...cur] : cur.filter((x) => x !== t)));
    void window.krypt.terminal
      .setWatched({ ticker: t, watched })
      .then(setWatchlist)
      .catch(refreshWatchlist);
  }, [refreshWatchlist]);

  const isWatched = useCallback(
    (ticker: string): boolean => watchRef.current.includes((ticker || '').toUpperCase()),
    [],
  );

  const value = useMemo<TerminalApi>(() => ({
    activeTicker, watchlist, openMarket, closeMarket, toggleWatch, isWatched,
    refreshWatchlist,
  }), [activeTicker, watchlist, openMarket, closeMarket, toggleWatch, isWatched, refreshWatchlist]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePoll<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: unknown[],
  enabled = true,
): { data: T | null; error: string | null; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;

  const gen = useRef(0);
  const inFlight = useRef(-1);

  const run = useCallback(async (mine: number): Promise<void> => {
    if (inFlight.current === mine) return;
    inFlight.current = mine;
    try {
      const v = await fetchRef.current();
      if (mine !== gen.current) return;
      setData(v);
      setError(null);
    } catch (e) {
      if (mine !== gen.current) return;
      setError(userMessage(e));
    } finally {
      if (inFlight.current === mine) inFlight.current = -1;
      if (mine === gen.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const mine = ++gen.current;
    if (!enabled) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setData(null);
    void run(mine);
    if (intervalMs <= 0) return;
    const id = setInterval(() => {
      if (mine === gen.current) void run(mine);
    }, intervalMs);
    return () => clearInterval(id);
  }, [run, intervalMs, enabled, ...deps]);

  const reload = useCallback((): void => { void run(gen.current); }, [run]);
  return { data, error, loading, reload };
}
