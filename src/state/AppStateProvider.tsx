import {
  createContext, ReactNode, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import type {
  AccountSnapshot, AppState, BackendInfo, BotPosition, CredentialsState,
  CredentialsStatusAll,
  LogEntry, ScannerStats, SignalRow, StrategyPreset, TraderConfig,
} from '@shared/types';

interface AppStateApi {
  state: AppState | null;
  config: TraderConfig | null;
  backend: BackendInfo;
  account: AccountSnapshot | null;
  scannerStats: ScannerStats | null;
  positions: BotPosition[];
  signals: SignalRow[];
  credentials: CredentialsState | null;
  credentialsAll: CredentialsStatusAll | null;
  strategies: StrategyPreset[];
  appVersion: string;
  refresh: {
    state: () => Promise<void>;
    account: () => Promise<void>;
    positions: () => Promise<void>;
    signals: () => Promise<void>;
    scannerStats: () => Promise<void>;
    credentials: () => Promise<void>;
    backend: () => Promise<void>;
  };
}

const AppCtx = createContext<AppStateApi | null>(null);

export function useApp(): AppStateApi {
  const ctx = useContext(AppCtx);
  if (!ctx) throw new Error('useApp must be inside AppStateProvider');
  return ctx;
}

const LogsCtx = createContext<LogEntry[]>([]);

export function useLogs(): LogEntry[] {
  return useContext(LogsCtx);
}

const DEFAULT_BACKEND: BackendInfo = {
  status: 'stopped',
  pid: null,
  startedAt: null,
  lastError: null,
  pythonOk: false,
  authOk: false,
};

function notify(title: string, body: string): void {
  try {
    new Notification(title, { body, silent: true });
  } catch {  }
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState | null>(null);
  const [backend, setBackend] = useState<BackendInfo>(DEFAULT_BACKEND);
  const [account, setAccount] = useState<AccountSnapshot | null>(null);
  const [scannerStats, setScannerStats] = useState<ScannerStats | null>(null);
  const [positions, setPositions] = useState<BotPosition[]>([]);
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [credentials, setCredentials] = useState<CredentialsState | null>(null);
  const [credentialsAll, setCredentialsAll] = useState<CredentialsStatusAll | null>(null);
  const [strategies, setStrategies] = useState<StrategyPreset[]>([]);
  const [appVersion, setAppVersion] = useState('3.0.0');

  const positionsByIdRef = useRef<Map<number, BotPosition>>(new Map());
  const signalsByKeyRef = useRef<Map<string, SignalRow>>(new Map());

  const flushPositions = (): void => {
    const arr = Array.from(positionsByIdRef.current.values());
    const ts = (p: BotPosition): number => {
      for (const c of [p.lastUpdated, p.resolvedAt, p.createdAt]) {
        if (!c) continue;
        const t = new Date(c).getTime();
        if (Number.isFinite(t)) return t;
      }
      return 0;
    };
    arr.sort((a, b) => ts(b) - ts(a));
    setPositions(arr.slice(0, 500));
  };

  const flushSignals = (): void => {
    const arr = Array.from(signalsByKeyRef.current.values());
    arr.sort((a, b) => {
      const ta = new Date(a.createdAt).getTime();
      const tb = new Date(b.createdAt).getTime();
      return (Number.isFinite(tb) ? tb : 0) - (Number.isFinite(ta) ? ta : 0);
    });
    setSignals(arr.slice(0, 300));
  };

  const refreshState = async (): Promise<void> => {
    try {
      const s = await window.krypt.state.get();
      setState(s);
    } catch {   }
  };

  const refreshAccount = async (): Promise<void> => {
    try {
      const a = await window.krypt.data.account();
      setAccount(a);
    } catch {   }
  };

  const refreshPositions = async (): Promise<void> => {
    try {
      const rows = await window.krypt.data.positions({ limit: 500 });
      const map = new Map<number, BotPosition>();
      for (const r of rows) map.set(r.id, r);
      positionsByIdRef.current = map;
      flushPositions();
    } catch {   }
  };

  const refreshSignals = async (): Promise<void> => {
    try {
      const rows = await window.krypt.data.signals({ limit: 300 });
      const map = new Map<string, SignalRow>();
      for (const r of rows) map.set(`${r.source}:${r.id}`, r);
      signalsByKeyRef.current = map;
      flushSignals();
    } catch {   }
  };

  const refreshScannerStats = async (): Promise<void> => {
    try {
      const s = await window.krypt.data.scannerStats();
      setScannerStats(s);
    } catch {   }
  };

  const refreshCredentials = async (): Promise<void> => {
    try {
      const [c, all] = await Promise.all([
        window.krypt.credentials.status(),
        window.krypt.credentials.statusAll().catch(() => null),
      ]);
      setCredentials(c);
      setCredentialsAll(all);
    } catch {   }
  };

  const refreshBackend = async (): Promise<void> => {
    try {
      const b = await window.krypt.backend.info();
      setBackend(b);
    } catch {   }
  };

  useEffect(() => {
    let mounted = true;
    const init = async () => {
      const [s, b, a, c, ss, pos, sig, ls, ver, strat] = await Promise.all([
        window.krypt.state.get(),
        window.krypt.backend.info(),
        window.krypt.data.account(),
        window.krypt.credentials.status().catch(() => null),
        window.krypt.data.scannerStats(),
        window.krypt.data.positions({ limit: 500 }),
        window.krypt.data.signals({ limit: 300 }),
        window.krypt.logs.tail(500),
        window.krypt.app.version(),
        window.krypt.config.listStrategies(),
      ]);
      if (!mounted) return;
      setState(s);
      setBackend(b);
      setAccount(a);
      setCredentials(c);
      void window.krypt.credentials.statusAll().then(setCredentialsAll).catch(() => null);
      setScannerStats(ss);
      const pmap = new Map<number, BotPosition>();
      for (const r of pos) pmap.set(r.id, r);
      positionsByIdRef.current = pmap;
      flushPositions();
      const smap = new Map<string, SignalRow>();
      for (const r of sig) smap.set(`${r.source}:${r.id}`, r);
      signalsByKeyRef.current = smap;
      flushSignals();
      setLogs(ls);
      setAppVersion(ver);
      setStrategies(strat);
    };
    void init();

    const offState = window.krypt.state.onChange((s) => setState(s));
    const offBackend = window.krypt.backend.onInfo((b) => setBackend(b));
    const offAccount = window.krypt.data.onAccount((a) => setAccount(a));
    const offPos = window.krypt.data.onPosition((p) => {
      const prev = positionsByIdRef.current.get(p.id);
      if (prev && prev.status !== p.status) {
        const name = p.title || p.ticker;
        if (p.status === 'filled' && prev.status !== 'filled') {
          notify(`Filled: ${name}`, `${p.filledContracts} @ ${p.avgFillPriceCents ?? '?'}¢`);
        } else if (p.resolved && !prev.resolved && typeof p.pnlUsd === 'number') {
          const won = p.pnlUsd >= 0;
          notify(`${won ? 'Won' : 'Lost'} $${Math.abs(p.pnlUsd).toFixed(2)} — ${name}`, p.status ?? '');
        }
      }
      positionsByIdRef.current.set(p.id, p);
      flushPositions();
    });
    const offSig = window.krypt.data.onSignal((s) => {
      signalsByKeyRef.current.set(`${s.source}:${s.id}`, s);
      flushSignals();
    });
    const offLog = window.krypt.logs.onAppend((entry) => {
      setLogs((cur) => {
        const next = [...cur, entry];
        if (next.length > 1000) next.splice(0, next.length - 1000);
        return next;
      });
    });
    const offCreds = window.krypt.credentials.onChanged(() => {
      void refreshCredentials();
    });
    const offReset = window.krypt.app.onDataReset(() => {
      positionsByIdRef.current = new Map();
      signalsByKeyRef.current = new Map();
      setPositions([]);
      setSignals([]);
      void Promise.all([
        refreshAccount(),
        refreshPositions(),
        refreshSignals(),
        refreshScannerStats(),
      ]);
    });

    const intervals: number[] = [];
    intervals.push(window.setInterval(() => void refreshCredentials(), 6000));
    intervals.push(window.setInterval(() => void refreshScannerStats(), 8000));
    intervals.push(window.setInterval(() => void refreshSignals(), 12000));
    intervals.push(window.setInterval(() => void refreshPositions(), 12000));

    return () => {
      mounted = false;
      offState();
      offBackend();
      offAccount();
      offPos();
      offSig();
      offLog();
      offCreds();
      offReset();
      for (const i of intervals) window.clearInterval(i);
    };
  }, []);

  const config = state?.config ?? null;

  const api = useMemo<AppStateApi>(
    () => ({
      state,
      config,
      backend,
      account,
      scannerStats,
      positions,
      signals,
      credentials,
      credentialsAll,
      strategies,
      appVersion,
      refresh: {
        state: refreshState,
        account: refreshAccount,
        positions: refreshPositions,
        signals: refreshSignals,
        scannerStats: refreshScannerStats,
        credentials: refreshCredentials,
        backend: refreshBackend,
      },
    }),
    [
      state, config, backend, account, scannerStats, positions, signals,
      credentials, credentialsAll, strategies, appVersion,
    ],
  );

  return (
    <AppCtx.Provider value={api}>
      <LogsCtx.Provider value={logs}>{children}</LogsCtx.Provider>
    </AppCtx.Provider>
  );
}
