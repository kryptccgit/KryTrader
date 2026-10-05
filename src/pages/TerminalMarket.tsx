import { useState } from 'react';
import {
  ArrowLeft, ExternalLink, RefreshCw, Star, X,
} from 'lucide-react';
import type {
  MarketDetail, MarketSummary, RestingOrder, RuleList as RuleListT,
} from '@shared/market';
import type { PageId } from '../App';
import { Card, ConfirmDialog, Page } from '../components/common';
import {
  Caveat, Cents, Count, Pnl, ProbBar, Provenance, SidePill, TimeToClose, Unknown, Usd,
} from '../components/terminal/atoms';
import { OrderBook } from '../components/terminal/OrderBook';
import { ProbabilityChart } from '../components/terminal/ProbabilityChart';
import { ResolutionRiskPanel } from '../components/terminal/ResolutionRiskPanel';
import { CrossVenue } from '../components/terminal/CrossVenue';
import { AiAnalysis } from '../components/terminal/AiAnalysis';
import { MicrostructurePanel } from '../components/terminal/MicrostructurePanel';
import { ArmRule, RuleList } from '../components/terminal/StandingRules';
import { Tape } from '../components/terminal/Tape';
import { TradeTicket } from '../components/terminal/TradeTicket';
import { useTerminal, usePoll } from '../state/TerminalProvider';
import { useToast } from '../state/ToastProvider';
import { cls } from '../utils/format';

export function TerminalMarketPage({
  ticker, onNav,
}: {
  ticker: string;
  onNav?: (p: PageId) => void;
}) {
  const { closeMarket, toggleWatch, watchlist } = useTerminal();
  const [tab, setTab] = useState<
    'book' | 'tape' | 'micro' | 'siblings' | 'venues' | 'ai'
  >('book');
  const [closing, setClosing] = useState(false);
  const [closeBusy, setCloseBusy] = useState(false);
  const toast = useToast();

  const { data, error, loading, reload } = usePoll<MarketDetail>(
    () => window.krypt.terminal.market({ ticker }),
    8_000,
    [ticker],
  );

  const watched = watchlist.includes(ticker);
  const m: MarketSummary | null = data?.market ?? null;

  const rules = usePoll<RuleListT>(
    () => window.krypt.terminal.rules({ limit: 200 }),
    10_000,
    [],
  );
  const myRules = (rules.data?.rules ?? []).filter(
    (r) => r.ticker === ticker && r.status === 'armed',
  );

  const position = data?.position ?? null;
  const exitBid = position
    ? (position.side === 'yes'
      ? data?.book?.yesBid ?? null
      : (data?.book?.yesAsk != null ? 100 - data.book.yesAsk : null))
    : null;

  const closeNow = async (): Promise<void> => {
    if (!position || exitBid === null) return;
    setClosing(false);
    setCloseBusy(true);
    try {
      const res = await window.krypt.terminal.submit({
        ticker,
        side: position.side,
        action: 'sell',
        count: position.contracts,
        priceCents: Math.max(1, exitBid - 1),
      });
      toast.push(res.message, res.ok ? 'success' : 'error', 9000);
      if (res.ok) reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setCloseBusy(false);
    }
  };

  if (loading && !data) {
    return (
      <Page title="Loading market…" subtitle={ticker}>
        <Card><div className="py-16 text-center text-sm text-krypt-muted">Assembling…</div></Card>
      </Page>
    );
  }

  if (!data || !m) {
    return (
      <Page
        title="Market unavailable"
        subtitle={ticker}
        actions={<button onClick={closeMarket} className="krypt-btn-default"><ArrowLeft className="h-4 w-4" />Back</button>}
      >
        <Card>
          <p className="text-sm text-krypt-muted">
            {error || 'Kalshi returned nothing for this ticker.'}
          </p>
          <p className="mt-2 text-xs text-krypt-dim">
            No page is invented for a market that does not exist.
          </p>
        </Card>
      </Page>
    );
  }

  return (
    <Page
      title={m.title}
      subtitle={[m.yesSubTitle, m.category, m.ticker].filter(Boolean).join(' · ')}
      actions={
        <>
          <button onClick={closeMarket} className="krypt-btn-ghost" title="Back to Discover">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <button
            onClick={() => toggleWatch(ticker)}
            className={cls('krypt-btn-default', watched && 'text-krypt-warn')}
            title={watched ? 'Remove from watchlist' : 'Add to watchlist'}
          >
            <Star className={cls('h-4 w-4', watched && 'fill-current')} />
          </button>
          <button
            onClick={() => {
              void window.krypt.kalshi
                .marketUrl({ ticker: m.ticker, eventTicker: m.eventTicker ?? undefined })
                .then((r) => {
                  if (r.url) void window.krypt.app.openExternal(r.url);
                  else toast.warn('Kalshi has no public page for this market.');
                })
                .catch(() => toast.error('Could not resolve the Kalshi page for this market.'));
            }}
            className="krypt-btn-default"
            title="Open on kalshi.com"
          >
            <ExternalLink className="h-4 w-4" />
          </button>
          <button onClick={reload} className="krypt-btn-default">
            <RefreshCw className={cls('h-4 w-4', loading && 'animate-spin')} />
          </button>
        </>
      }
    >
      {error && (
        <Caveat className="mb-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">
          {error} Showing the last data that loaded.
        </Caveat>
      )}

      {data.errors.length > 0 && (
        <Caveat className="mb-3">
          {data.errors.map((e) => `The ${e.panel} panel failed: ${e.message}`).join(' ')}
          {' '}Everything else on this page loaded normally.
        </Caveat>
      )}

      {data.quoteDriftCents !== null && data.quoteDriftCents >= 3 && (
        <Caveat className="mb-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">
          This market moved {data.quoteDriftCents}¢ between the two reads that
          built this page — it is trading faster than the page refreshes. The
          quotes above and the ticket are priced off the order book, which is the
          fresher of the two; treat anything on screen as a moment old and use a
          limit price you are happy to rest at.
        </Caveat>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Quote label="YES bid" value={<Cents value={m.yesBid} why="Nobody is bidding for YES — an empty book side, not a 0¢ bid." />} row={m} field="yesBid" />
        <Quote label="YES ask" value={<Cents value={m.yesAsk} why="Nobody is offering YES — there is nothing to buy." />} row={m} field="yesAsk" />
        <Quote label="Last" value={<Cents value={m.lastPrice} why="This market has never traded." />} row={m} field="lastPrice" />
        <Quote label="Volume" value={<Count value={m.volume} />} row={m} field="volume" />
        <Quote label="Open interest" value={<Count value={m.openInterest} />} row={m} field="openInterest" />
        <Quote label="Closes" value={<TimeToClose minutes={m.minutesToClose} />} row={m} field="status" />
      </div>

      <div className="mb-4">
        <div className="mb-1 flex items-baseline justify-between text-[11px]">
          <span className="text-krypt-muted">Implied probability</span>
          <span className="font-mono text-white">
            {m.midCents === null
              ? <Unknown why="The book is one-sided, so there is no mid — and no implied probability to state." />
              : `${m.midCents.toFixed(1)}%`}
          </span>
        </div>
        <ProbBar value={m.midCents} className="h-1.5" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card header={<SectionTitle>Probability over time</SectionTitle>}>
            <ProbabilityChart ticker={ticker} market={m} />
          </Card>

          <Card
            header={
              <div className="flex items-center gap-1">
                {(['book', 'tape', 'micro', 'siblings', 'venues', 'ai'] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setTab(t)}
                    className={cls(
                      'rounded px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider transition-colors',
                      tab === t ? 'bg-white/10 text-white' : 'text-krypt-dim hover:text-white',
                    )}
                  >
                    {t === 'book' ? 'Order book'
                      : t === 'tape' ? 'Trades'
                        : t === 'micro' ? 'Our feed'
                          : t === 'siblings' ? 'Same event'
                            : t === 'venues' ? 'Other venues'
                              : 'AI read'}
                  </button>
                ))}
              </div>
            }
          >
            {tab === 'book' && (
              data.book
                ? <OrderBook book={data.book} />
                : <p className="py-8 text-center text-sm text-krypt-muted">
                    The order book could not be read. Nothing is drawn rather than an empty ladder.
                  </p>
            )}
            {tab === 'tape' && <Tape ticker={ticker} />}
            {tab === 'micro' && <MicrostructurePanel ticker={ticker} />}
            {tab === 'venues' && <CrossVenue ticker={ticker} />}
            {tab === 'siblings' && <Siblings detail={data} />}
            {tab === 'ai' && <AiAnalysis ticker={ticker} onNav={onNav} />}
          </Card>
        </div>

        <div className="space-y-4">
          <Card header={<SectionTitle>Trade</SectionTitle>}>
            <TradeTicket
              market={m}
              book={data.book}
              position={data.position}
              onDone={reload}
            />
          </Card>

          {data.position && (
            <PositionCard
              detail={data}
              exitBid={exitBid}
              busy={closeBusy}
              onClose={() => setClosing(true)}
            />
          )}

          <Card header={<SectionTitle>Standing instructions</SectionTitle>}>
            <ArmRule market={m} position={data.position} onArmed={rules.reload} />
            {myRules.length > 0 && (
              <div className="mt-4 border-t border-krypt-border pt-3">
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-krypt-muted">
                  Armed on this market
                </div>
                <RuleList rules={myRules} onChanged={rules.reload} compact />
              </div>
            )}
          </Card>

          {data.restingOrders.length > 0 && (
            <Card header={<SectionTitle>Your resting orders</SectionTitle>}>
              <RestingOrders orders={data.restingOrders} onChanged={reload} />
            </Card>
          )}

          <Card header={<SectionTitle>Resolution risk</SectionTitle>}>
            <ResolutionRiskPanel risk={data.risk} />
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={closing}
        title="Close this position?"
        danger
        confirmLabel="Sell now"
        onClose={() => setClosing(false)}
        onConfirm={() => void closeNow()}
        body={
          <div className="space-y-2">
            <p>
              Sell all{' '}
              <span className="font-mono text-white">{position?.contracts}</span>{' '}
              <span className="font-mono text-white">{position?.side.toUpperCase()}</span>{' '}
              on <span className="font-mono text-white">{ticker}</span>, crossing
              into the {exitBid}¢ bid.
            </p>
            <p className="text-krypt-muted">
              This is a market-ish exit: it is priced a cent through the bid so it
              actually trades rather than resting. What it finally fills at comes
              back from Kalshi&apos;s ledger.
            </p>
          </div>
        }
      />
    </Page>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-krypt-muted">
      {children}
    </span>
  );
}

function Quote({
  label, value, row, field,
}: {
  label: string;
  value: React.ReactNode;
  row: MarketSummary;
  field: Parameters<typeof Provenance>[0]['field'];
}) {
  return (
    <div className="rounded-lg border border-krypt-border bg-krypt-surface px-3 py-2">
      <div className="flex items-center text-[10px] uppercase tracking-wider text-krypt-dim">
        {label}
        <Provenance row={row} field={field} />
      </div>
      <div className="mt-0.5 text-lg text-white">{value}</div>
    </div>
  );
}

function PositionCard({
  detail, exitBid, busy, onClose,
}: {
  detail: MarketDetail;
  exitBid: number | null;
  busy: boolean;
  onClose: () => void;
}) {
  const p = detail.position!;
  return (
    <Card header={<SectionTitle>Your position</SectionTitle>}>
      <div className="space-y-1.5 text-[11px]">
        <Row label="Side" value={<SidePill side={p.side} />} />
        <Row label="Contracts" value={<Count value={p.contracts} />} />
        <Row
          label="Average cost"
          value={<Cents value={p.avgCostCents} why={p.reconcileNote ?? undefined} />}
        />
        <Row label="Cost basis" value={<Usd value={p.costBasisUsd} why={p.reconcileNote ?? undefined} />} />
        <Row label="Fees paid" value={<Usd value={p.feesPaidUsd} />} />
        <Row label="Mark" value={<Cents value={p.markCents} why="This market has no two-sided quote and no print, so it cannot be marked." />} />
        <Row label="Market value" value={<Usd value={p.marketValueUsd} />} />
        <Row label="Unrealised" value={<Pnl value={p.unrealizedUsd} />} />
        <Row label="Realised" value={<Pnl value={p.realizedUsd} />} />
      </div>
      <button
        onClick={onClose}
        disabled={busy || exitBid === null}
        className="krypt-btn-default mt-3 w-full"
        title={exitBid === null
          ? 'Nobody is bidding for this side, so there is nothing to sell into.'
          : `Sell all ${p.contracts} into the ${exitBid}¢ bid`}
      >
        {busy ? 'Closing…'
          : exitBid === null ? 'No bid to close into'
            : `Close all ${p.contracts} at ~${exitBid}¢`}
      </button>

      {p.reconcileNote
        ? <Caveat className="mt-3">{p.reconcileNote}</Caveat>
        : (
          <p className="mt-3 text-[10px] leading-relaxed text-krypt-dim">
            Cost basis is read from Kalshi’s own ledger, not from what the app
            asked to pay — fees and partial fills are already in it. It is an
            AVERAGE cost, not FIFO.
          </p>
        )}
    </Card>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-krypt-muted">{label}</span>
      <span>{value}</span>
    </div>
  );
}

function RestingOrders({
  orders, onChanged,
}: { orders: RestingOrder[]; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  const cancel = async (id: string): Promise<void> => {
    setBusy(id);
    try {
      const res = await window.krypt.terminal.cancel({ orderId: id });
      toast.push(res.message, res.ok ? 'success' : 'error');
      if (res.ok) onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-1.5">
      {orders.map((o) => (
        <div
          key={o.orderId}
          className="flex items-center gap-2 rounded-lg border border-krypt-border bg-krypt-surface2/40 px-2.5 py-2 text-[11px]"
        >
          <SidePill side={o.side} />
          <span className="text-krypt-muted">{o.action}</span>
          <span className="font-mono text-white">
            {o.remaining ?? o.count ?? <Unknown />}
          </span>
          <span className="text-krypt-dim">@</span>
          <Cents value={o.priceCents} className="text-white" />
          {!o.manual && (
            <span
              className="krypt-badge !py-0 !text-[9px]"
              title="Placed by the bot or on kalshi.com — not from this terminal. It is listed, not hidden."
            >
              not manual
            </span>
          )}
          <button
            onClick={() => void cancel(o.orderId)}
            disabled={busy === o.orderId}
            className="ml-auto grid h-6 w-6 place-items-center rounded text-krypt-dim transition-colors hover:bg-krypt-loss/10 hover:text-krypt-loss disabled:opacity-40"
            title="Cancel this order"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}

function Siblings({ detail }: { detail: MarketDetail }) {
  const { openMarket } = useTerminal();
  const siblings = detail.event?.siblings ?? [];
  if (!detail.event) {
    return (
      <p className="py-8 text-center text-sm text-krypt-muted">
        The parent event could not be read, so the other legs of this question
        are unknown.
      </p>
    );
  }
  if (siblings.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-krypt-muted">
        This event has no other legs — it is a single yes/no question.
      </p>
    );
  }
  return (
    <div>
      <p className="mb-2 text-[11px] text-krypt-muted">
        {detail.event.title ?? detail.event.eventTicker} — the other legs of the
        same question. Seeing the whole distribution is how you tell a mispriced
        leg from a mispriced view.
      </p>
      <table className="krypt-table">
        <thead>
          <tr>
            <th className="krypt-th">Outcome</th>
            <th className="krypt-th w-24 text-right">Bid</th>
            <th className="krypt-th w-24 text-right">Ask</th>
            <th className="krypt-th w-24">Implied</th>
          </tr>
        </thead>
        <tbody>
          {siblings.map((s) => (
            <tr
              key={s.ticker}
              onClick={() => openMarket(s.ticker)}
              className="krypt-tr-hover cursor-pointer"
            >
              <td className="krypt-td">
                <div className="truncate text-white/90">{s.yesSubTitle ?? s.title}</div>
                <div className="font-mono text-[10px] text-krypt-dim">{s.ticker}</div>
              </td>
              <td className="krypt-td text-right"><Cents value={s.yesBid} /></td>
              <td className="krypt-td text-right"><Cents value={s.yesAsk} /></td>
              <td className="krypt-td">
                <ProbBar value={s.midCents} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
