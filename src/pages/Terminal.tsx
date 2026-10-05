import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity, Clock, RefreshCw, Search, Sparkles, Star, TrendingUp, X,
} from 'lucide-react';
import type {
  DiscoverColumn, DiscoverFilters as Filters, DiscoverResult, MarketSummary,
} from '@shared/market';
import { Card, Empty, Page } from '../components/common';
import {
  Caveat, Cents, Count, ProbBar, Provenance, TimeToClose, Unknown,
} from '../components/terminal/atoms';
import { DiscoverFilters } from '../components/terminal/DiscoverFilters';
import { TerminalMarketPage } from './TerminalMarket';
import type { PageId } from '../App';
import { useTerminal, usePoll } from '../state/TerminalProvider';
import { cls } from '../utils/format';

const COLUMNS: {
  id: DiscoverColumn;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  blurb: string;
}[] = [
  {
    id: 'trending', label: 'Trending', icon: Activity,
    blurb: 'Ranked by what is actually printing on Kalshi’s public tape right now — not by a 24h counter that keeps yesterday’s finished events at the top.',
  },
  {
    id: 'closing', label: 'Closing soon', icon: Clock,
    blurb: 'Open, about to resolve, and actually actionable — a two-sided book, or one side with real trading behind it. A quote nobody has ever traded against is usually a market maker pricing every rung of a strike ladder, so those are left out, and no single event may fill the column.',
  },
  {
    id: 'new', label: 'Newest', icon: Sparkles,
    blurb: 'Most recently opened markets across every open event.',
  },
  {
    id: 'volume', label: 'Most traded', icon: TrendingUp,
    blurb: 'Biggest lifetime volume. Markets that have never traded are excluded — that is a fact about them, not a gap in our data.',
  },
  {
    id: 'watchlist', label: 'Watchlist', icon: Star,
    blurb: 'The markets you starred. Kept on this machine.',
  },
];

const POLL_MS: Record<DiscoverColumn, number> = {
  trending: 15_000,
  closing: 30_000,
  new: 60_000,
  volume: 120_000,
  watchlist: 15_000,
};

export function TerminalPage({ onNav }: { onNav?: (p: PageId) => void }) {
  const { activeTicker } = useTerminal();
  if (activeTicker) return <TerminalMarketPage ticker={activeTicker} onNav={onNav} />;
  return <DiscoverScreen />;
}

function DiscoverScreen() {
  const [column, setColumn] = useState<DiscoverColumn>('trending');
  const [query, setQuery] = useState('');
  const [searchRes, setSearchRes] = useState<DiscoverResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>({});
  const [appliedFilters, setAppliedFilters] = useState<Filters>({});
  const [categories, setCategories] = useState<string[]>([]);
  const searchSeq = useRef(0);

  const active = COLUMNS.find((c) => c.id === column)!;
  const pendingKey = JSON.stringify(filters);
  useEffect(() => {
    const id = setTimeout(() => setAppliedFilters(filters), 350);
    return () => clearTimeout(id);
  }, [pendingKey]);
  const filterKey = JSON.stringify(appliedFilters);
  const { data, error, loading, reload } = usePoll<DiscoverResult>(
    () => window.krypt.terminal
      .discover({ column, limit: 80, filters: appliedFilters })
      .then((r) => {
        if (r.categories?.length) setCategories(r.categories);
        return r;
      }),
    POLL_MS[column],
    [column, filterKey],
    !query,
  );

  const runSearch = useCallback(async (q: string): Promise<void> => {
    const seq = ++searchSeq.current;
    if (!q.trim()) {
      setSearchRes(null);
      setSearchErr(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    try {
      const res = await window.krypt.terminal.search({ query: q, limit: 80 });
      if (seq !== searchSeq.current) return;
      setSearchRes(res);
      setSearchErr(null);
    } catch (e) {
      if (seq !== searchSeq.current) return;
      setSearchErr(e instanceof Error ? e.message : String(e));
      setSearchRes(null);
    } finally {
      if (seq === searchSeq.current) setSearching(false);
    }
  }, []);

  useEffect(() => {
    const id = setTimeout(() => { void runSearch(query); }, 320);
    return () => clearTimeout(id);
  }, [query, runSearch]);

  const showing = query ? searchRes : data;
  const busy = query ? searching : loading;
  const err = query ? searchErr : error;

  return (
    <Page
      title="Terminal"
      subtitle="Browse every Kalshi market, read the resolution risk, and trade by hand."
      actions={
        <button
          onClick={() => {
            if (query) void runSearch(query);
            else {
              void window.krypt.terminal
                .discover({ column, limit: 80, refresh: true, filters: appliedFilters })
                .then(reload);
            }
          }}
          className="krypt-btn-default"
          title="Force a fresh sweep instead of the cached one"
        >
          <RefreshCw className={cls('h-4 w-4', busy && 'animate-spin')} />
          Refresh
        </button>
      }
    >
      <div className="relative mb-4">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-krypt-dim" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search any market — a title, a category, or an exact ticker like KXBTCD-26AUG24-T90000"
          className="krypt-input pl-9 pr-9"
        />
        {query && (
          <button
            onClick={() => setQuery('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-krypt-dim hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {!query && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {COLUMNS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setColumn(id)}
              className={cls(
                'flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors',
                column === id
                  ? 'border-krypt-purple/50 bg-krypt-purple/10 text-white'
                  : 'border-krypt-border bg-krypt-surface text-krypt-muted hover:border-krypt-borderHi hover:text-white',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
      )}

      {!query && (
        <p className="mb-3 text-[11px] leading-relaxed text-krypt-dim">{active.blurb}</p>
      )}

      {!query && column !== 'watchlist' && (
        <DiscoverFilters value={filters} onChange={setFilters} categories={categories} />
      )}

      {err && (
        <Caveat className="mb-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">
          {err}
          {showing && ' Showing the last data that loaded.'}
        </Caveat>
      )}

      {showing?.note && <Caveat className="mb-3">{showing.note}</Caveat>}

      {busy && !showing ? (
        <Card><div className="py-10 text-center text-sm text-krypt-muted">Loading markets…</div></Card>
      ) : !showing || showing.rows.length === 0 ? (
        <Empty
          title={query ? 'Nothing matched' : column === 'watchlist' ? 'No watched markets' : 'No markets'}
          description={
            query
              ? 'Try fewer words, or paste an exact ticker — a ticker resolves even for markets outside the sweep.'
              : column === 'watchlist'
                ? 'Star a market from its page and it will appear here, kept on this machine.'
                : 'Kalshi returned nothing for this column. Nothing is shown rather than a filled-in guess.'
          }
        />
      ) : (
        <MarketTable rows={showing.rows} />
      )}

      {showing && showing.rows.length > 0 && (
        <div className="mt-3 text-[11px] text-krypt-dim">
          {showing.rows.length} shown
          {showing.scanned !== null && ` · ${showing.scanned.toLocaleString()} considered`}
          {showing.ageSec !== null && showing.ageSec > 2 && ` · data ${Math.round(showing.ageSec)}s old`}
          {' · '}values nobody could produce show as “—”, never as 0
        </div>
      )}
    </Page>
  );
}

function MarketTable({ rows }: { rows: MarketSummary[] }) {
  const { openMarket, toggleWatch, watchlist } = useTerminal();
  return (
    <div className="overflow-x-auto rounded-xl border border-krypt-border">
      <table className="krypt-table min-w-[900px]">
        <thead>
          <tr>
            <th className="krypt-th w-8" />
            <th className="krypt-th">Market</th>
            <th className="krypt-th w-24 text-right">Bid</th>
            <th className="krypt-th w-24 text-right">Ask</th>
            <th className="krypt-th w-28">Implied</th>
            <th className="krypt-th w-24 text-right">Last</th>
            <th className="krypt-th w-24 text-right">Volume</th>
            <th className="krypt-th w-20 text-right">Closes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const watched = watchlist.includes(r.ticker);
            return (
              <tr
                key={r.ticker}
                onClick={() => openMarket(r.ticker)}
                className="krypt-tr-hover cursor-pointer"
              >
                <td className="krypt-td">
                  <button
                    onClick={(e) => { e.stopPropagation(); toggleWatch(r.ticker); }}
                    title={watched ? 'Remove from watchlist' : 'Add to watchlist'}
                    className={cls(
                      'grid h-6 w-6 place-items-center rounded transition-colors',
                      watched ? 'text-krypt-warn' : 'text-krypt-dim hover:text-white',
                    )}
                  >
                    <Star className={cls('h-3.5 w-3.5', watched && 'fill-current')} />
                  </button>
                </td>
                <td className="krypt-td max-w-[420px]">
                  <div className="truncate text-white/90">{r.title}</div>
                  <div className="flex items-center gap-1.5 truncate text-[11px] text-krypt-dim">
                    {r.yesSubTitle && <span className="text-krypt-muted">{r.yesSubTitle}</span>}
                    {r.category && <span className="krypt-badge !py-0 !text-[9px]">{r.category}</span>}
                    <span className="font-mono">{r.ticker}</span>
                  </div>
                </td>
                <td className="krypt-td text-right">
                  <Cents value={r.yesBid} why="Nobody is bidding for YES. That is an empty book side, not a 0¢ bid." />
                  <Provenance row={r} field="yesBid" />
                </td>
                <td className="krypt-td text-right">
                  <Cents value={r.yesAsk} why="Nobody is offering YES. That is an empty book side, not a price." />
                  <Provenance row={r} field="yesAsk" />
                </td>
                <td className="krypt-td">
                  <ProbBar value={r.midCents} />
                  <div className="mt-1 text-[10px] text-krypt-dim">
                    {r.midCents === null
                      ? <Unknown why="The book is one-sided, so there is no mid and no implied probability." />
                      : `${r.midCents.toFixed(0)}% · ${r.spreadCents?.toFixed(0)}¢ spread`}
                  </div>
                </td>
                <td className="krypt-td text-right">
                  <Cents value={r.lastPrice} why="This market has never traded." />
                </td>
                <td className="krypt-td text-right">
                  <Count value={r.volume} why="Kalshi reported no volume figure for this market." />
                </td>
                <td className="krypt-td text-right">
                  <TimeToClose minutes={r.minutesToClose} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
