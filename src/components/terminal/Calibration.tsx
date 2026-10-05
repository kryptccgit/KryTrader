import type { ManualHistory } from '@shared/market';
import { cls } from '../../utils/format';
import { Caveat, Unknown } from './atoms';

export function Calibration({ history }: { history: ManualHistory }) {
  const buckets = history.buckets.filter((b) => b.trades > 0);

  if (buckets.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-krypt-muted">
        {history.note ?? 'No settled hand-placed trades yet.'}
      </div>
    );
  }

  const scored = buckets.filter((b) => b.hitRate !== null);

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <p className="text-[11px] leading-relaxed text-krypt-muted">
          Each bar is a price band you bought into. The bar is how often that
          side actually won; the tick is what the market said the odds were.
          Bars above the tick mean you were buying underpriced; below, over.
        </p>
      </div>

      <div className="flex items-end gap-1.5">
        {history.buckets.map((b) => {
          const h = b.hitRate;
          const implied = b.impliedRate;
          const edge = h !== null && implied !== null ? h - implied : null;
          return (
            <div key={b.loCents} className="flex flex-1 flex-col items-center gap-1">
              <div
                className="relative h-28 w-full rounded bg-white/[0.03]"
                title={
                  b.trades === 0
                    ? `${b.loCents}–${b.hiCents}¢: no trades`
                    : h === null
                      ? `${b.loCents}–${b.hiCents}¢: ${b.trades} trade(s). ${b.note}`
                      : `${b.loCents}–${b.hiCents}¢: won ${b.wins} of ${b.trades} `
                        + `(${(h * 100).toFixed(0)}%), market implied `
                        + `${((implied ?? 0) * 100).toFixed(0)}%`
                }
              >
                {h !== null && (
                  <div
                    className={cls(
                      'absolute inset-x-0 bottom-0 rounded',
                      edge !== null && edge >= 0
                        ? 'bg-gradient-to-t from-krypt-win/70 to-krypt-win/30'
                        : 'bg-gradient-to-t from-krypt-loss/70 to-krypt-loss/30',
                    )}
                    style={{ height: `${Math.max(2, h * 100)}%` }}
                  />
                )}
                {implied !== null && (
                  <div
                    className="absolute inset-x-0 border-t border-dashed border-white/50"
                    style={{ bottom: `${Math.max(0, Math.min(100, implied * 100))}%` }}
                    title={`market implied ${(implied * 100).toFixed(0)}%`}
                  />
                )}
                {b.trades > 0 && h === null && (
                  <div className="absolute inset-x-0 bottom-0 grid h-full place-items-center">
                    <span className="text-[9px] leading-tight text-krypt-dim">
                      {b.trades}/{history.minTradesPerBucket}
                    </span>
                  </div>
                )}
              </div>
              <div className="text-[9px] tabular-nums text-krypt-dim">{b.loCents}</div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 space-y-2">
        <div className="text-[11px] text-krypt-dim">
          {history.calibratableCount} settled trade(s) scored across{' '}
          {scored.length} band(s) with enough data.
          {buckets.length > scored.length && (
            <> {buckets.length - scored.length} band(s) show their sample count
              instead of a rate — under {history.minTradesPerBucket} trades a hit
              rate is noise wearing a number&apos;s clothes.</>
          )}
        </div>
        {scored.length === 0 && (
          <Caveat>
            No band has {history.minTradesPerBucket} settled trades yet, so no
            hit rate is shown. This fills in as you trade — it is the most
            useful thing on this page once it does.
          </Caveat>
        )}
      </div>
    </div>
  );
}

export function ManualScorecard({ history }: { history: ManualHistory }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile
        label="Settled trades"
        value={<span className="font-mono">{history.closedCount}</span>}
        hint={`${history.openCount} still open`}
      />
      <Tile
        label="Hit rate"
        value={
          history.winRate === null
            ? <Unknown why="No settled hand-placed trades yet." />
            : <span className="font-mono">{(history.winRate * 100).toFixed(0)}%</span>
        }
        hint={`${history.wins}W / ${history.losses}L`}
      />
      <Tile
        label="Realised"
        value={
          history.realizedUsd === null
            ? <Unknown why="Nothing has settled yet, so there is no realised P&L — that is not the same as zero." />
            : (
              <span className={cls(
                'font-mono',
                history.realizedUsd > 0 ? 'text-krypt-win'
                  : history.realizedUsd < 0 ? 'text-krypt-loss' : 'text-white',
              )}>
                {history.realizedUsd > 0 ? '+' : history.realizedUsd < 0 ? '−' : ''}
                ${Math.abs(history.realizedUsd).toFixed(2)}
              </span>
            )
        }
        hint="exact — these settle to 0 or 1"
      />
      <Tile
        label="Fees paid"
        value={
          history.feesUsd === null
            ? <Unknown />
            : <span className="font-mono">${history.feesUsd.toFixed(2)}</span>
        }
        hint="already inside the P&L"
      />
    </div>
  );
}

function Tile({
  label, value, hint,
}: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-krypt-border bg-krypt-surface px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-krypt-dim">{label}</div>
      <div className="mt-0.5 text-xl text-white">{value}</div>
      {hint && <div className="text-[10px] text-krypt-dim">{hint}</div>}
    </div>
  );
}
