import { useCallback, useEffect, useMemo, useState } from 'react';
import { Ban, RefreshCw } from 'lucide-react';
import type { BookEnv, BotPosition } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Empty, Page } from '../components/common';
import { GlassSegmented } from '../components/glass/GlassSegmented';
import { TickerLink } from '../components/KalshiTicker';
import { cls, fmtCents, fmtRelative, fmtUsd } from '../utils/format';
import { BOOK_LABEL, bookEnvOf } from '../utils/account';
import { userMessage } from '../utils/errors';

const STATUS_COLORS: Record<string, string> = {
  submitted: 'bg-krypt-warn/15 text-krypt-warn border-krypt-warn/30',
  partial: 'bg-krypt-warn/15 text-krypt-warn border-krypt-warn/30',
  filled: 'bg-krypt-indigo/15 text-krypt-indigo border-krypt-indigo/30',
  canceled: 'bg-krypt-dim/15 text-krypt-muted border-krypt-border',
  expired: 'bg-krypt-dim/15 text-krypt-muted border-krypt-border',
  gone: 'bg-krypt-dim/15 text-krypt-muted border-krypt-border',
  error: 'bg-krypt-loss/15 text-krypt-loss border-krypt-loss/30',
  dry_run: 'bg-krypt-purple/15 text-krypt-purple border-krypt-purple/30',
};

type Tab = 'open' | 'pending' | 'won' | 'lost' | 'errors' | 'all';

export const BOOK_BADGE: Record<BookEnv, { text: string; title: string; cls: string }> = {
  paper: {
    text: 'PAPER', title: 'Paper: imaginary money on real Kalshi prices.',
    cls: 'border-krypt-purple/40 bg-krypt-purple/10 text-krypt-purple',
  },
  production: {
    text: 'LIVE', title: 'Live: real money on your Kalshi account.',
    cls: 'border-krypt-loss/40 bg-krypt-loss/10 text-krypt-loss',
  },
  demo: {
    text: 'DEMO (retired)', title: "Kalshi's demo exchange, which the app no longer uses. History only.",
    cls: 'border-krypt-border bg-krypt-surface2 text-krypt-muted',
  },
};

export function rowsOfBook<T extends { kalshiEnv: BookEnv }>(rows: T[], book: BookEnv | 'all'): T[] {
  return book === 'all' ? rows : rows.filter((r) => r.kalshiEnv === book);
}

export function PositionsPage() {
  const { positions: allBooks, refresh, config } = useApp();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>('open');
  const [bookPick, setBookPick] = useState<BookEnv | 'all' | null>(null);
  const book: BookEnv | 'all' = bookPick ?? bookEnvOf(config);
  const hasRetired = allBooks.some((p) => p.kalshiEnv === 'demo');
  const books: (BookEnv | 'all')[] = hasRetired
    ? ['paper', 'production', 'demo', 'all'] : ['paper', 'production', 'all'];
  const [own, setOwn] = useState<{ book: BookEnv | 'all'; rows: BotPosition[] } | null>(null);
  const loadOwn = useCallback(async (): Promise<void> => {
    try {
      const rows = await window.krypt.data.positions({ limit: 500, env: book });
      setOwn({ book, rows });
    } catch {}
  }, [book]);
  useEffect(() => {
    setOwn(null);
    void loadOwn();
    const i = window.setInterval(() => void loadOwn(), 12_000);
    return () => window.clearInterval(i);
  }, [loadOwn]);
  const positions = useMemo(
    () => rowsOfBook(own && own.book === book ? own.rows : allBooks, book),
    [own, book, allBooks],
  );
  const [src, setSrc] = useState<'all' | 'whale' | 'momentum' | 'manual' | 'external'>('all');
  const [busy, setBusy] = useState<string | null>(null);

  const filtered = useMemo(() => {
    return positions.filter((p) => {
      if (src !== 'all' && p.signalSource !== src) return false;
      switch (tab) {
        case 'open':
          return !p.resolved && (p.status === 'filled' || p.status === 'partial');
        case 'pending':
          return !p.resolved && p.status === 'submitted';
        case 'won':
          return p.resolved && p.outcomeCorrect === 1;
        case 'lost':
          return p.resolved && p.outcomeCorrect === 0;
        case 'errors':
          return p.status === 'error';
        case 'all':
        default:
          return true;
      }
    });
  }, [positions, tab, src]);

  const counts = useMemo(() => {
    let open = 0, pending = 0, won = 0, lost = 0, errors = 0;
    for (const p of positions) {
      if (!p.resolved && (p.status === 'filled' || p.status === 'partial')) open++;
      if (!p.resolved && p.status === 'submitted') pending++;
      if (p.resolved && p.outcomeCorrect === 1) won++;
      if (p.resolved && p.outcomeCorrect === 0) lost++;
      if (p.status === 'error') errors++;
    }
    return { open, pending, won, lost, errors, all: positions.length };
  }, [positions]);

  const nonBotOpen = useMemo(
    () => positions.filter(
      (p) => !p.resolved
        && (p.status === 'filled' || p.status === 'partial' || p.status === 'submitted')
        && (p.signalSource === 'external' || (config != null && p.kalshiEnv !== bookEnvOf(config))),
    ).length,
    [positions, config],
  );

  const cancelAll = async (): Promise<void> => {
    if (!window.confirm(config?.accountMode === 'live'
      ? 'Cancel ALL open (unfilled) orders on your real Kalshi account?'
      : 'Cancel ALL open (unfilled) paper orders?')) return;
    setBusy('cancel');
    try {
      const r = await window.krypt.trading.cancelAllOpen();
      if (r.ok) toast.success(r.message || 'All open orders canceled');
      else toast.error(r.message || 'Failed');
    } finally {
      setBusy(null);
    }
  };

  const refreshNow = async (): Promise<void> => {
    setBusy('refresh');
    try {
      await window.krypt.backend.runOnce('pollOrders');
      await window.krypt.backend.runOnce('reconcilePositions');
      await Promise.all([refresh.positions(), refresh.account(), loadOwn()]);
      toast.success('Synced open & pending orders');
    } catch (e) {
      toast.error(`Sync failed: ${userMessage(e)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Page
      title="Positions"
      subtitle="The bot's open and recent positions, one book at a time. Cancel All withdraws every order that hasn't filled yet."
      actions={
        <div className="flex items-center gap-2">
          <button onClick={refreshNow} disabled={!!busy} className="krypt-btn-default" title="Sync open & pending orders with Kalshi">
            <RefreshCw className={cls('h-4 w-4', busy === 'refresh' && 'animate-spin')} /> Refresh
          </button>
          <button onClick={cancelAll} disabled={!!busy} className="krypt-btn-danger">
            <Ban className="h-4 w-4" /> Cancel All
          </button>
        </div>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs" data-testid="positions-book">
        <span className="text-krypt-muted">Book:</span>
        {books.map((b) => (
          <button
            key={b}
            type="button"
            onClick={() => setBookPick(b)}
            data-testid={`positions-book-${b}`}
            className={cls(
              'rounded-md border px-2.5 py-1 transition-colors',
              book === b
                ? b === 'production' ? 'border-krypt-loss/50 bg-krypt-loss/10 text-white'
                  : 'border-krypt-purple/50 bg-krypt-purple/10 text-white'
                : 'border-krypt-border text-krypt-muted hover:text-white',
            )}
          >
            {b === 'all' ? 'All books' : BOOK_LABEL[b]}
          </button>
        ))}
        {book === 'all' && (
          <span className="text-krypt-dim">Paper and Live together — each row says which.</span>
        )}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Tabs value={tab} onChange={setTab}
          options={[
            { value: 'open', label: `Open (${counts.open})` },
            { value: 'pending', label: `Pending (${counts.pending})` },
            { value: 'won', label: `Won (${counts.won})` },
            { value: 'lost', label: `Lost (${counts.lost})` },
            { value: 'errors', label: `Errors (${counts.errors})` },
            { value: 'all', label: `All (${counts.all})` },
          ]}
        />
        <div className="ml-auto flex gap-1">
          <Tabs value={src} onChange={setSrc}
            options={[
              { value: 'all', label: 'All' },
              { value: 'whale', label: 'Whales' },
              { value: 'momentum', label: 'Momentum' },
              { value: 'manual', label: 'Manual' },
              { value: 'external', label: 'Imported' },
            ]}
          />
        </div>
      </div>

      {nonBotOpen > 0 && (
        <p className="-mt-2 mb-3 text-[11px] text-krypt-dim">
          Open/Pending include {nonBotOpen} imported or other-book position{nonBotOpen === 1 ? '' : 's'} the
          bot doesn&apos;t count against its max-open cap.
        </p>
      )}

      {filtered.length === 0 ? (
        <Empty
          title="No positions match"
          description="Switch tabs or wait for the trader to open something."
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-krypt-border">
          <table className="krypt-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Book</th>
                <th>Source</th>
                <th>Ticker</th>
                <th>Title</th>
                <th>Side</th>
                <th>Filled</th>
                <th>Cost</th>
                <th>Status</th>
                <th>Outcome</th>
                <th>Edge</th>
                <th>P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => <PositionRow key={p.id} p={p} />)}
            </tbody>
          </table>
        </div>
      )}
    </Page>
  );
}

function Tabs<T extends string>({
  value, onChange, options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return <GlassSegmented value={value} onChange={onChange} options={options} />;
}

function PositionRow({ p }: { p: BotPosition }) {
  const realized = p.resolved;
  const pnl = realized ? p.pnlUsd : p.livePnlUsd;
  return (
    <tr>
      <td className="text-xs text-krypt-muted">{fmtRelative(p.createdAt)}</td>
      <td>
        <span
          data-testid="position-book"
          title={(BOOK_BADGE[p.kalshiEnv] ?? BOOK_BADGE.demo).title}
          className={cls(
            'inline-flex whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase',
            (BOOK_BADGE[p.kalshiEnv] ?? BOOK_BADGE.demo).cls,
          )}
        >
          {(BOOK_BADGE[p.kalshiEnv] ?? BOOK_BADGE.demo).text}
        </span>
      </td>
      <td>
        <span
          className={cls(
            'inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] uppercase',
            p.signalSource === 'whale'
              ? 'bg-krypt-purple/15 text-krypt-purple'
              : p.signalSource === 'external'
                ? 'bg-krypt-dim/15 text-krypt-muted'
                : p.signalSource === 'manual'
                  ? 'bg-krypt-indigo/15 text-krypt-indigo'
                  : 'bg-krypt-pink/15 text-krypt-pink',
          )}
        >
          {p.signalSource === 'external' ? 'imported' : p.signalSource}
        </span>
      </td>
      <td><TickerLink ticker={p.ticker} eventTicker={p.eventTicker} env={p.kalshiEnv} /></td>
      <td className="max-w-[280px] truncate text-xs text-krypt-muted">{p.title}</td>
      <td>
        <span
          className={cls(
            'rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase',
            p.direction === 'yes'
              ? 'bg-krypt-win/10 text-krypt-win'
              : 'bg-krypt-loss/10 text-krypt-loss',
          )}
        >
          {p.direction}
        </span>
      </td>
      <td className="font-mono text-xs">
        {p.filledContracts}/{p.targetContracts}
        <span className="ml-2 text-krypt-dim">
          @ {fmtCents(p.avgFillPriceCents ?? p.limitPriceCents)}
        </span>
      </td>
      <td className="font-mono text-xs">{fmtUsd(p.costUsd)}</td>
      <td>
        <span
          className={cls(
            'inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase',
            STATUS_COLORS[p.status] ?? 'border-krypt-border bg-krypt-surface2 text-krypt-muted',
          )}
        >
          {p.status}
        </span>
      </td>
      <td>
        {!p.resolved ? (
          <span className="text-[10px] uppercase tracking-wider text-krypt-dim">open</span>
        ) : p.outcomeCorrect === 1 ? (
          <span className="krypt-pill border-krypt-win/40 bg-krypt-win/10 text-krypt-win">won</span>
        ) : p.outcomeCorrect === 0 ? (
          <span className="krypt-pill border-krypt-loss/40 bg-krypt-loss/10 text-krypt-loss">lost</span>
        ) : (
          <span className="krypt-pill text-krypt-muted">closed</span>
        )}
      </td>
      <td className="font-mono text-xs text-krypt-purple">
        {p.edgePts === null || p.edgePts === undefined
          ? <span className="text-krypt-dim" title={p.signalSource === 'external'
            ? 'Imported from Kalshi — no entry signal' : 'No signal behind this trade, so no edge was claimed'}>—</span>
          : `+${p.edgePts.toFixed(1)}`}
      </td>
      <td
        className={cls(
          'font-mono text-xs',
          pnl == null ? 'text-krypt-dim' : pnl >= 0 ? 'text-krypt-win' : 'text-krypt-loss',
        )}
      >
        {pnl == null ? (
          '—'
        ) : (
          <span
            title={
              realized
                ? 'Realized P&L'
                : `Unrealized P&L at ${p.markPriceCents != null ? `${Math.round(p.markPriceCents)}¢` : 'current price'}`
            }
          >
            {fmtUsd(pnl, { sign: true })}
            {!realized && (
              <span className="ml-1 text-[9px] uppercase tracking-wide text-krypt-dim" title="Not settled yet: this moves with the price.">open</span>
            )}
          </span>
        )}
      </td>
    </tr>
  );
}
