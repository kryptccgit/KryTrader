import { AlertTriangle, ArrowLeftRight, ExternalLink, Scale } from 'lucide-react';
import type { CrossVenueMatch, CrossVenueResult } from '@shared/market';
import { usePoll } from '../../state/TerminalProvider';
import { cls } from '../../utils/format';
import { Caveat, Cents, Unknown } from './atoms';

export function CrossVenue({ ticker }: { ticker: string }) {
  const { data, error, loading } = usePoll<CrossVenueResult>(
    () => window.krypt.terminal.crossVenue({ ticker }),
    30_000,
    [ticker],
  );

  if (loading && !data) {
    return <div className="py-8 text-center text-sm text-krypt-muted">Looking on Polymarket…</div>;
  }
  if (error && !data) {
    return <div className="py-8 text-center text-sm text-krypt-muted">{error}</div>;
  }
  if (!data) return null;

  if (!data.available) {
    return (
      <div className="py-6">
        <div className="mb-2 flex items-center justify-center gap-2 text-sm text-krypt-muted">
          <AlertTriangle className="h-4 w-4 text-krypt-warn" />
          Polymarket could not be reached
        </div>
        <p className="mx-auto max-w-md text-center text-[11px] leading-relaxed text-krypt-dim">
          {data.geoblocked
            ? 'It looks region-blocked from here. That is a fact about your connection, not about whether an equivalent market exists — so nothing is shown rather than an empty comparison.'
            : data.note}
        </p>
      </div>
    );
  }

  const confident = data.matches.filter((m) => m.confident);
  const candidates = data.matches.filter((m) => !m.confident);

  return (
    <div className="space-y-3">
      {confident.length === 0 && candidates.length === 0 && (
        <div className="py-6 text-center">
          <div className="text-sm text-krypt-muted">No equivalent found on Polymarket</div>
          <p className="mx-auto mt-1 max-w-md text-[11px] leading-relaxed text-krypt-dim">
            Nothing in the {data.scanned?.toLocaleString() ?? '—'} quoted markets
            searched was close enough to be worth showing. A near-match that
            is not the same question would be worse than nothing.
          </p>
        </div>
      )}

      {confident.map((m) => (
        <MatchRow
          key={m.market.conditionId}
          match={m}
          polyAgeSec={data.polymarketAgeSec}
        />
      ))}

      {candidates.length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-krypt-muted">
            Unconfirmed candidates
          </div>
          <p className="mb-2 text-[11px] leading-relaxed text-krypt-dim">
            Close, but not close enough to price against. Read the reasons and
            decide for yourself — no comparison is computed for these.
          </p>
          {candidates.map((m) => (
            <MatchRow
              key={m.market.conditionId}
              match={m}
              polyAgeSec={data.polymarketAgeSec}
            />
          ))}
        </div>
      )}

      {data.note && <Caveat>{data.note}</Caveat>}

      <div className="flex gap-2.5 rounded-lg border border-krypt-warn/25 bg-krypt-warn/[0.05] px-3 py-2.5">
        <Scale className="mt-0.5 h-3.5 w-3.5 shrink-0 text-krypt-warn" />
        <p className="text-[11px] leading-relaxed text-krypt-muted">{data.venueNote}</p>
      </div>

      <p className="text-[10px] leading-relaxed text-krypt-dim">
        Read-only. This app does not trade on Polymarket — it has no wallet, no
        collateral and no signing keys for it, and never sends an order there.
      </p>
    </div>
  );
}

function MatchRow(
  { match, polyAgeSec }: { match: CrossVenueMatch; polyAgeSec: number | null },
) {
  const { market: p, comparison: c } = match;
  const pct = Math.round(match.confidence * 100);

  return (
    <div
      className={cls(
        'rounded-lg border px-3 py-2.5',
        match.confident
          ? 'border-krypt-border bg-krypt-surface2/40'
          : 'border-krypt-border/60 bg-transparent',
      )}
    >
      <div className="flex items-start gap-2">
        <span
          className={cls(
            'mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider',
            match.confident
              ? 'bg-krypt-win/15 text-krypt-win'
              : 'bg-krypt-warn/15 text-krypt-warn',
          )}
          title={`Match confidence ${pct}%`}
        >
          {match.confident ? `match ${pct}%` : `maybe ${pct}%`}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] leading-snug text-white/90">{p.question}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-krypt-dim">
            <span>matched on: {match.reasons.join('; ')}</span>
          </div>
        </div>
        <button
          onClick={() => void window.krypt.app.openExternal(p.url)}
          className="shrink-0 rounded p-1 text-krypt-dim transition-colors hover:text-white"
          title="Open on polymarket.com"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </button>
      </div>

      {c ? (
        <div className="mt-2.5 grid grid-cols-3 gap-2 border-t border-krypt-border pt-2.5">
          <Venue
            name="Kalshi"
            bid={c.kalshiBid}
            ask={c.kalshiAsk}
            note="CFTC-regulated"
          />
          <div className="flex flex-col items-center justify-center">
            <ArrowLeftRight className="mb-1 h-3.5 w-3.5 text-krypt-dim" />
            <div className="text-center">
              <div
                className={cls(
                  'font-mono text-sm',
                  c.differenceCents === null ? 'text-krypt-dim'
                    : Math.abs(c.differenceCents) >= 3 ? 'text-krypt-warn'
                      : 'text-white',
                )}
              >
                {c.differenceCents === null
                  ? <Unknown why="One venue has no two-sided quote, so there is nothing to compare." />
                  : `${c.differenceCents > 0 ? '+' : ''}${c.differenceCents}¢`}
              </div>
              <div className="text-[9px] leading-tight text-krypt-dim">
                mid difference
              </div>
            </div>
          </div>
          <Venue
            name="Polymarket"
            bid={c.polyBid}
            ask={c.polyAsk}
            note="UMA oracle"
          />
        </div>
      ) : (
        <div className="mt-2 border-t border-krypt-border pt-2 text-[10px] leading-relaxed text-krypt-dim">
          No prices shown: this pairing is not confident enough to compare
          against. Polymarket is quoting{' '}
          <Cents value={p.midCents} why="No two-sided quote on Polymarket." /> —
          check the question above matches before reading anything into that.
        </div>
      )}

      {c && c.cheaperToBuyYes && c.cheaperToBuyYes !== 'neither' && (
        <div className="mt-2 text-[10px] leading-relaxed text-krypt-muted">
          YES is cheaper to buy on{' '}
          <span className="text-white">
            {c.cheaperToBuyYes === 'kalshi' ? 'Kalshi' : 'Polymarket'}
          </span>{' '}
          by <span className="font-mono text-white">{c.askDifferenceCents}¢</span>{' '}
          (ask vs ask). That is a price difference between two venues that
          settle differently — not a risk-free trade.
          {polyAgeSec !== null && polyAgeSec !== undefined && (
            <>
              {' '}The Polymarket price is{' '}
              <span className="font-mono">{Math.round(polyAgeSec)}s</span> old;
              the Kalshi one was read just now.
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Venue({
  name, bid, ask, note,
}: { name: string; bid: number | null; ask: number | null; note: string }) {
  return (
    <div className="text-center">
      <div className="text-[9px] uppercase tracking-wider text-krypt-dim">{name}</div>
      <div className="font-mono text-sm text-white">
        <Cents value={bid} why="No bid on this venue." />
        <span className="text-krypt-dim"> / </span>
        <Cents value={ask} why="No offer on this venue." />
      </div>
      <div className="text-[9px] leading-tight text-krypt-dim">{note}</div>
    </div>
  );
}
