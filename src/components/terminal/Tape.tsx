import type { TapeResult } from '@shared/market';
import { usePoll } from '../../state/TerminalProvider';
import { cls } from '../../utils/format';
import { Caveat, Cents, Count, SidePill, Unknown, Usd } from './atoms';

export function Tape({ ticker }: { ticker: string }) {
  const { data, error, loading } = usePoll<TapeResult>(
    () => window.krypt.terminal.tape({ ticker, limit: 60 }),
    4_000,
    [ticker],
  );

  const live = data?.source === 'kalshi-ws';

  if (loading && !data) {
    return <div className="py-8 text-center text-sm text-krypt-muted">Loading tape…</div>;
  }
  if (error && !data) {
    return <div className="py-8 text-center text-sm text-krypt-muted">{error}</div>;
  }
  if (!data || data.trades.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-krypt-muted">
        No prints. This market has not traded — that is a fact about the market,
        not a gap in the feed.
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-[10px]">
        <span
          className={cls(
            'rounded px-1.5 py-0.5 font-medium uppercase tracking-wider',
            live ? 'bg-krypt-purple/20 text-krypt-purple' : 'bg-white/5 text-krypt-dim',
          )}
        >
          {live ? 'our own feed' : 'REST'}
        </span>
        <span className="text-krypt-dim">{data.trades.length} prints</span>
      </div>

      <div className="max-h-72 overflow-y-auto">
        <table className="krypt-table">
          <thead className="sticky top-0 bg-krypt-surface">
            <tr>
              <th className="krypt-th">Time</th>
              {live && (
                <th className="krypt-th" title="When THIS machine received the print — not when Kalshi stamped it.">
                  Seen
                </th>
              )}
              <th className="krypt-th">Taker</th>
              <th className="krypt-th text-right">Size</th>
              <th className="krypt-th text-right">YES</th>
              <th className="krypt-th text-right">Notional</th>
            </tr>
          </thead>
          <tbody>
            {data.trades.map((t, i) => (
              <tr key={t.tradeId || i}>
                <td className="krypt-td font-mono text-[11px] text-krypt-muted">
                  {t.createdAt
                    ? new Date(t.createdAt).toLocaleTimeString()
                    : <Unknown why="Kalshi sent no timestamp with this print." />}
                </td>
                {live && (
                  <td className="krypt-td font-mono text-[11px] text-krypt-purple">
                    {t.observedAt
                      ? new Date(t.observedAt).toLocaleTimeString(undefined, {
                        hour: '2-digit', minute: '2-digit', second: '2-digit',
                      })
                      : <Unknown why="This print came from REST, so we have no local arrival time for it." />}
                  </td>
                )}
                <td className="krypt-td">
                  <span className="flex items-center gap-1.5">
                    {t.takerSide
                      ? <SidePill side={t.takerSide} />
                      : <Unknown why="Kalshi did not say which side lifted." />}
                    {t.isBlockTrade && (
                      <span
                        className="rounded border border-krypt-line px-1 text-[9px] uppercase tracking-wide text-krypt-dim"
                        title="Privately negotiated away from the public book, then printed. A real trade, but nobody lifted a resting offer — so it is not the same signal as the other prints here."
                      >
                        block
                      </span>
                    )}
                  </span>
                </td>
                <td className="krypt-td text-right"><Count value={t.contracts} /></td>
                <td className="krypt-td text-right"><Cents value={t.yesPrice} /></td>
                <td className="krypt-td text-right text-krypt-muted">
                  <Usd value={t.notionalUsd} why="Size or price was unreadable, so the notional is unknown." />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.note && <Caveat className="mt-2">{data.note}</Caveat>}
    </div>
  );
}
