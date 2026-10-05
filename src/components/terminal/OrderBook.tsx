import type { BookLevel, OrderBookSnapshot } from '@shared/market';
import { cls } from '../../utils/format';
import { Caveat, Cents, Count, Unknown } from './atoms';

export function OrderBook({
  book, onPick,
}: {
  book: OrderBookSnapshot;
  onPick?: (side: 'yes' | 'no', priceCents: number) => void;
}) {
  const maxCum = Math.max(
    book.yes[book.yes.length - 1]?.cumulative ?? 0,
    book.no[book.no.length - 1]?.cumulative ?? 0,
    1,
  );

  return (
    <div>
      <div className="mb-3 grid grid-cols-3 gap-2 text-center">
        <Stat label="YES bid" value={<Cents value={book.yesBid} why="No resting YES bids." />} />
        <Stat
          label="Spread"
          value={
            book.spreadCents === null
              ? <Unknown why="One side of the book is empty, so there is no spread — an unknown one, not a zero one." />
              : <Cents value={book.spreadCents} className={book.spreadCents >= 10 ? 'text-krypt-warn' : undefined} />
          }
        />
        <Stat label="YES ask" value={<Cents value={book.yesAsk} why="No resting YES offers — nothing to buy." />} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Ladder
          title="YES bids" levels={book.yes} maxCum={maxCum} tone="win"
          depth={book.yesDepthContracts}
          onPick={onPick ? (p) => onPick('yes', p) : undefined}
        />
        <Ladder
          title="NO bids" levels={book.no} maxCum={maxCum} tone="loss"
          depth={book.noDepthContracts}
          onPick={onPick ? (p) => onPick('no', p) : undefined}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-krypt-dim">
        <span
          className={cls(
            'rounded px-1.5 py-0.5 font-medium uppercase tracking-wider',
            book.source === 'kalshi-ws'
              ? 'bg-krypt-purple/20 text-krypt-purple'
              : 'bg-white/5 text-krypt-dim',
          )}
          title={
            book.source === 'kalshi-ws'
              ? 'Our own websocket book, maintained locally from snapshot + deltas.'
              : 'A REST snapshot. The websocket book takes over once this market is subscribed.'
          }
        >
          {book.source === 'kalshi-ws' ? 'live book' : 'REST snapshot'}
        </span>
        <span>observed {new Date(book.observedAt).toLocaleTimeString()}</span>
      </div>

      {book.note && <Caveat className="mt-2">{book.note}</Caveat>}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-krypt-border bg-krypt-surface2/50 px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-krypt-dim">{label}</div>
      <div className="text-sm text-white">{value}</div>
    </div>
  );
}

function Ladder({
  title, levels, maxCum, tone, depth, onPick,
}: {
  title: string;
  levels: BookLevel[];
  maxCum: number;
  tone: 'win' | 'loss';
  depth: number | null;
  onPick?: (priceCents: number) => void;
}) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-krypt-muted">
          {title}
        </span>
        <span className="text-[10px] text-krypt-dim">
          {depth === null
            ? <Unknown why="No resting orders on this side." />
            : <>{depth.toLocaleString()} total</>}
        </span>
      </div>
      {levels.length === 0 ? (
        <div className="rounded-lg border border-dashed border-krypt-border px-3 py-6 text-center text-[11px] text-krypt-dim">
          Nothing resting on this side
        </div>
      ) : (
        <div className="space-y-px">
          {levels.map((lv) => (
            <button
              key={lv.priceCents}
              onClick={onPick ? () => onPick(lv.priceCents) : undefined}
              disabled={!onPick}
              title={onPick ? `Load ${lv.priceCents}¢ into the ticket` : undefined}
              className={cls(
                'relative flex w-full items-center justify-between overflow-hidden rounded px-2 py-1 text-[11px]',
                onPick && 'cursor-pointer hover:ring-1 hover:ring-krypt-borderHi',
              )}
            >
              <span
                className={cls(
                  'absolute inset-y-0 left-0',
                  tone === 'win' ? 'bg-krypt-win/10' : 'bg-krypt-loss/10',
                )}
                style={{ width: `${(lv.cumulative / maxCum) * 100}%` }}
              />
              <span className={cls('relative font-mono', tone === 'win' ? 'text-krypt-win' : 'text-krypt-loss')}>
                {lv.priceCents.toFixed(lv.priceCents % 1 ? 1 : 0)}¢
              </span>
              <span className="relative font-mono text-white/80">
                <Count value={lv.contracts} />
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
