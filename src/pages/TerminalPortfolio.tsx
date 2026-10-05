import { useState } from 'react';
import { AlertTriangle, ExternalLink, RefreshCw, X } from 'lucide-react';
import type {
  ManualHistory, RestingOrder, RuleList as RuleListT, TerminalPortfolio,
} from '@shared/market';
import { Card, Empty, Page, StatCard } from '../components/common';
import { Caveat, Cents, Count, Pnl, SidePill, Unknown, Usd } from '../components/terminal/atoms';
import { Calibration, ManualScorecard } from '../components/terminal/Calibration';
import { ShardBalances } from '../components/terminal/ShardBalances';
import { RuleList } from '../components/terminal/StandingRules';
import { useTerminal, usePoll } from '../state/TerminalProvider';
import { useToast } from '../state/ToastProvider';
import { cls } from '../utils/format';

export function TerminalPortfolioPage() {
  const { openMarket } = useTerminal();
  const toast = useToast();
  const [cancelling, setCancelling] = useState<string | null>(null);

  const pf = usePoll<TerminalPortfolio>(
    () => window.krypt.terminal.portfolio(),
    10_000,
    [],
  );
  const orders = usePoll<{ orders: RestingOrder[]; note: string | null }>(
    () => window.krypt.terminal.orders(),
    10_000,
    [],
  );
  const rules = usePoll<RuleListT>(
    () => window.krypt.terminal.rules({ limit: 300 }),
    8_000,
    [],
  );
  const hist = usePoll<ManualHistory>(
    () => window.krypt.terminal.history({ limit: 400 }),
    60_000,
    [],
  );

  const data = pf.data;
  const starvedShard = Object.values(data?.shardCash ?? {})
    .some((sh) => sh.cashUsd <= 0);

  const cancel = async (id: string): Promise<void> => {
    setCancelling(id);
    try {
      const res = await window.krypt.terminal.cancel({ orderId: id });
      toast.push(res.message, res.ok ? 'success' : 'error');
      if (res.ok) orders.reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setCancelling(null);
    }
  };

  return (
    <Page
      title="Terminal portfolio"
      subtitle="Every position in the connected Kalshi account, priced off its own ledger."
      actions={
        <button
          onClick={() => { pf.reload(); orders.reload(); hist.reload(); rules.reload(); }}
          className="krypt-btn-default"
        >
          <RefreshCw className={cls('h-4 w-4', (pf.loading || orders.loading) && 'animate-spin')} />
          Refresh
        </button>
      }
    >
      {pf.error && (
        <Caveat className="mb-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">
          {pf.error}
        </Caveat>
      )}

      {data && Object.keys(data.shardCash ?? {}).length > 1 && (
        <ShardBalances
          className="mb-3"
          shards={Object.entries(data.shardCash).map(([idx, sh]) => ({
            index: Number(idx), name: sh.name, cashUsd: sh.cashUsd,
          }))}
          transferUrl={data.shardTransferUrl}
          onDone={() => void pf.reload()}
        />
      )}

      {data?.note && (
        <div className="mb-3 flex items-start gap-2 rounded-lg border border-krypt-warn/40 bg-krypt-warn/[0.06] px-3 py-2 text-[11px] leading-relaxed text-krypt-warn">
          <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
          <span>
            {data.note}
            {starvedShard && data.shardTransferUrl && (
              <button
                onClick={() => void window.krypt.app.openExternal(data.shardTransferUrl)}
                className="ml-2 inline-flex items-center gap-1 rounded border border-krypt-warn/50 px-1.5 py-0.5 align-middle text-[10px] font-medium hover:bg-krypt-warn/10"
              >
                Move funds between exchanges
                <ExternalLink className="h-3 w-3" />
              </button>
            )}
          </span>
        </div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatCard
          label="Cash"
          value={<Usd value={data?.cashUsd} why="Kalshi's balance endpoint did not answer." />}
          hint={
            data && Object.keys(data.shardCash ?? {}).length > 1
              ? Object.values(data.shardCash)
                .map((sh) => `${sh.name} $${sh.cashUsd.toFixed(0)}`)
                .join(' · ')
              : data ? `${data.env} environment` : undefined
          }
        />
        <StatCard
          label="Cost basis"
          value={<Usd value={data?.totalCostBasisUsd ?? null} />}
          hint="average cost, not FIFO"
        />
        <StatCard
          label="Market value"
          value={<Usd value={data?.totalMarketValueUsd ?? null} />}
          hint="unquoted markets excluded"
        />
        <StatCard
          label="Unrealised"
          value={<Pnl value={data?.totalUnrealizedUsd ?? null} />}
          accent={
            (data?.totalUnrealizedUsd ?? 0) > 0 ? 'good'
              : (data?.totalUnrealizedUsd ?? 0) < 0 ? 'bad' : 'neutral'
          }
        />
        <StatCard
          label="Realised"
          value={<Pnl value={data?.totalRealizedUsd ?? null} />}
          hint="settled and closed, per Kalshi"
        />
      </div>

      <Card
        className="mb-4"
        header={
          <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-krypt-muted">
            Positions
          </span>
        }
      >
        {pf.loading && !data ? (
          <div className="py-10 text-center text-sm text-krypt-muted">Loading positions…</div>
        ) : !data || data.positions.length === 0 ? (
          <Empty
            title="No open positions"
            description={
              data?.note
                ?? 'Nothing is held in this environment. Open a market from the Terminal and trade it by hand.'
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="krypt-table min-w-[820px]">
              <thead>
                <tr>
                  <th className="krypt-th">Market</th>
                  <th className="krypt-th w-16">Side</th>
                  <th className="krypt-th w-20 text-right">Size</th>
                  <th className="krypt-th w-24 text-right">Avg cost</th>
                  <th className="krypt-th w-24 text-right">Mark</th>
                  <th className="krypt-th w-28 text-right">Value</th>
                  <th className="krypt-th w-28 text-right">Unrealised</th>
                </tr>
              </thead>
              <tbody>
                {data.positions.map((p) => (
                  <tr
                    key={`${p.ticker}-${p.side}`}
                    onClick={() => openMarket(p.ticker)}
                    className={cls(
                      'krypt-tr-hover cursor-pointer',
                      !p.reconciled && 'opacity-70',
                    )}
                  >
                    <td className="krypt-td max-w-[340px]">
                      <div className="truncate text-white/90">{p.title ?? p.ticker}</div>
                      <div className="flex items-center gap-1.5 font-mono text-[10px] text-krypt-dim">
                        {p.ticker}
                        {!p.reconciled && (
                          <span
                            className="rounded bg-krypt-warn/15 px-1 py-px text-[9px] uppercase tracking-wider text-krypt-warn"
                            title={p.reconcileNote ?? undefined}
                          >
                            unreconciled
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="krypt-td"><SidePill side={p.side} /></td>
                    <td className="krypt-td text-right"><Count value={p.contracts} /></td>
                    <td className="krypt-td text-right">
                      <Cents value={p.avgCostCents} why={p.reconcileNote ?? undefined} />
                    </td>
                    <td className="krypt-td text-right">
                      <Cents value={p.markCents} why="No two-sided quote and no print, so this position cannot be marked." />
                    </td>
                    <td className="krypt-td text-right"><Usd value={p.marketValueUsd} /></td>
                    <td className="krypt-td text-right"><Pnl value={p.unrealizedUsd} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        className="mb-4"
        header={
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-krypt-muted">
              Standing instructions
            </span>
            <span className="text-[10px] text-krypt-dim">
              {rules.data
                ? `${rules.data.armedCount} armed`
                : 'loading…'}
            </span>
          </div>
        }
      >
        {rules.error ? (
          <p className="py-6 text-center text-sm text-krypt-muted">{rules.error}</p>
        ) : (
          <>
            <RuleList rules={rules.data?.rules ?? []} onChanged={rules.reload} />
            <p className="mt-3 text-[10px] leading-relaxed text-krypt-dim">
              These are the only things in the app that can act without another
              click, and every one of them is a sentence you typed. They run the
              same order path and the same caps as trading by hand, and a rule
              that cannot be priced does nothing and says so rather than firing
              on a guess.
            </p>
          </>
        )}
      </Card>

      <Card
        header={
          <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-krypt-muted">
            Resting orders
          </span>
        }
      >
        {orders.error ? (
          <p className="py-6 text-center text-sm text-krypt-muted">{orders.error}</p>
        ) : orders.loading && !orders.data ? (
          <div className="py-8 text-center text-sm text-krypt-muted">Loading orders…</div>
        ) : !orders.data || orders.data.orders.length === 0 ? (
          <Empty
            title="Nothing resting"
            description="Every working order in this account appears here — placed by hand, by the bot, or on kalshi.com. One page, one cancel button."
          />
        ) : (
          <>
            {orders.data.note && <Caveat className="mb-3">{orders.data.note}</Caveat>}
            <table className="krypt-table">
              <thead>
                <tr>
                  <th className="krypt-th">Market</th>
                  <th className="krypt-th w-16">Side</th>
                  <th className="krypt-th w-16">Action</th>
                  <th className="krypt-th w-20 text-right">Left</th>
                  <th className="krypt-th w-20 text-right">Price</th>
                  <th className="krypt-th w-24">Source</th>
                  <th className="krypt-th w-10" />
                </tr>
              </thead>
              <tbody>
                {orders.data.orders.map((o) => (
                  <tr key={o.orderId}>
                    <td className="krypt-td">
                      <button
                        onClick={() => openMarket(o.ticker)}
                        className="font-mono text-[11px] text-white/90 underline-offset-2 hover:underline"
                      >
                        {o.ticker}
                      </button>
                    </td>
                    <td className="krypt-td"><SidePill side={o.side} /></td>
                    <td className="krypt-td text-krypt-muted">{o.action ?? <Unknown />}</td>
                    <td className="krypt-td text-right">
                      {o.remaining ?? o.count ?? <Unknown why="Kalshi reported no remaining count for this order." />}
                    </td>
                    <td className="krypt-td text-right"><Cents value={o.priceCents} /></td>
                    <td className="krypt-td">
                      <span
                        className="text-[10px] uppercase tracking-wider text-krypt-dim"
                        title={o.manual
                          ? 'Placed from this terminal.'
                          : 'Placed by the bot or on kalshi.com. Listed, not hidden — it is your money either way.'}
                      >
                        {o.manual ? 'manual' : 'bot / web'}
                      </span>
                    </td>
                    <td className="krypt-td">
                      <button
                        onClick={() => void cancel(o.orderId)}
                        disabled={cancelling === o.orderId}
                        className="grid h-6 w-6 place-items-center rounded text-krypt-dim transition-colors hover:bg-krypt-loss/10 hover:text-krypt-loss disabled:opacity-40"
                        title="Cancel this order"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>

      {hist.data && (
        <>
          <Card
            className="mt-4"
            header={
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-krypt-muted">
                  How you have done — by hand
                </span>
                <span className="text-[10px] text-krypt-dim">
                  hand-placed trades only; the bot&apos;s record is on History
                </span>
              </div>
            }
          >
            <ManualScorecard history={hist.data} />
            <div className="mt-5 border-t border-krypt-border pt-4">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-krypt-muted">
                Calibration
              </div>
              <Calibration history={hist.data} />
            </div>
          </Card>

          {hist.data.trades.some((t) => t.resolved) && (
            <Card
              className="mt-4"
              header={
                <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-krypt-muted">
                  Settled trades
                </span>
              }
            >
              <div className="max-h-96 overflow-y-auto">
                <table className="krypt-table">
                  <thead className="sticky top-0 bg-krypt-surface">
                    <tr>
                      <th className="krypt-th">Market</th>
                      <th className="krypt-th w-16">Side</th>
                      <th className="krypt-th w-16 text-right">Size</th>
                      <th className="krypt-th w-20 text-right">Paid</th>
                      <th className="krypt-th w-20">Outcome</th>
                      <th className="krypt-th w-24 text-right">P&amp;L</th>
                      <th className="krypt-th w-28 text-right">Settled</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hist.data.trades.filter((t) => t.resolved).map((t) => (
                      <tr
                        key={t.id}
                        onClick={() => openMarket(t.ticker)}
                        className="krypt-tr-hover cursor-pointer"
                      >
                        <td className="krypt-td max-w-[300px]">
                          <div className="truncate text-white/90">{t.title ?? t.ticker}</div>
                          <div className="font-mono text-[10px] text-krypt-dim">{t.ticker}</div>
                        </td>
                        <td className="krypt-td"><SidePill side={t.side} /></td>
                        <td className="krypt-td text-right"><Count value={t.contracts} /></td>
                        <td className="krypt-td text-right"><Cents value={t.avgCostCents} /></td>
                        <td className="krypt-td">
                          {t.closedEarly ? (
                            <span
                              className="text-[10px] uppercase tracking-wider text-krypt-muted"
                              title="Sold before settlement — it has a P&L but no yes/no outcome, so it is excluded from calibration."
                            >
                              sold out
                            </span>
                          ) : t.outcomeCorrect === null ? (
                            <Unknown why="Settled, but Kalshi reported no outcome for this row." />
                          ) : (
                            <span className={cls(
                              'text-[10px] font-semibold uppercase tracking-wider',
                              t.outcomeCorrect ? 'text-krypt-win' : 'text-krypt-loss',
                            )}>
                              {t.outcomeCorrect ? 'won' : 'lost'}
                            </span>
                          )}
                        </td>
                        <td className="krypt-td text-right"><Pnl value={t.pnlUsd} /></td>
                        <td className="krypt-td text-right text-[10px] text-krypt-dim">
                          {t.resolvedAt
                            ? new Date(t.resolvedAt).toLocaleDateString()
                            : <Unknown />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}

      <p className="mt-4 text-[11px] leading-relaxed text-krypt-dim">
        Cash is summed across Kalshi’s exchange shards. Since August 2026 Kalshi
        runs several matching engines — crypto and sports live on their own —
        and collateral is held per shard, so a funded account can still be
        unable to trade a market whose shard holds nothing. Orders are routed to
        the right engine automatically.{' '}
        Cost basis and realised P&amp;L are read from Kalshi’s own ledger, so fees
        and partial fills are already included. Rows Kalshi could not price are
        marked unreconciled and left out of the totals above — never counted as
        break-even. Hand-placed trades are kept separate from the bot&apos;s
        record: they do not count toward its win rate and they cannot trip its
        daily stop-loss, so a bad afternoon of your own trading never silently
        halts the automation.
      </p>
    </Page>
  );
}
