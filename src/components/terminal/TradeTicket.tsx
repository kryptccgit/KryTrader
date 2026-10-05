import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, Loader2, ShieldAlert } from 'lucide-react';
import type {
  MarketSummary, OrderBookSnapshot, TerminalPosition, TicketPreview, TicketResult,
} from '@shared/market';
import { ConfirmDialog } from '../common';
import { useApp } from '../../state/AppStateProvider';
import { useToast } from '../../state/ToastProvider';
import { cls } from '../../utils/format';
import { Cents, Unknown, Usd } from './atoms';

export function TradeTicket({
  market, book, position, onDone,
}: {
  market: MarketSummary;
  book: OrderBookSnapshot | null;
  position: TerminalPosition | null;
  onDone: () => void;
}) {
  const { config } = useApp();
  const toast = useToast();
  const [side, setSide] = useState<'yes' | 'no'>('yes');
  const [action, setAction] = useState<'buy' | 'sell'>('buy');
  const [count, setCount] = useState('1');
  const [price, setPrice] = useState('');
  const [preview, setPreview] = useState<TicketPreview | null>(null);
  const [pricing, setPricing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<TicketResult | null>(null);
  const seq = useRef(0);

  const live = config?.kalshiEnv === 'production';

  const bookRef = useRef(book);
  bookRef.current = book;
  const seeded = useRef(false);

  useEffect(() => { seeded.current = false; }, [market.ticker, side, action]);

  useEffect(() => {
    if (seeded.current) return;
    const b = bookRef.current;
    if (!b) return;
    const best = action === 'buy'
      ? (side === 'yes' ? b.yesAsk : (b.yesBid !== null ? 100 - b.yesBid : null))
      : (side === 'yes' ? b.yesBid : (b.yesAsk !== null ? 100 - b.yesAsk : null));
    seeded.current = true;
    setPrice(best !== null && best !== undefined ? String(best) : '');
  }, [market.ticker, side, action, book]);

  const countN = Number(count);
  const priceN = Number(price);

  const runPreview = useCallback(async (): Promise<void> => {
    const mine = ++seq.current;
    if (!Number.isFinite(countN) || !Number.isFinite(priceN) || !price) {
      setPreview(null);
      return;
    }
    setPricing(true);
    try {
      const pv = await window.krypt.terminal.preview({
        ticker: market.ticker, side, action, count: countN, priceCents: priceN,
      });
      if (mine === seq.current) setPreview(pv);
    } catch (e) {
      if (mine === seq.current) {
        setPreview(null);
        toast.error(
          `Could not price this order: ${e instanceof Error ? e.message : String(e)}`,
        );
      }
    } finally {
      if (mine === seq.current) setPricing(false);
    }
  }, [market.ticker, side, action, countN, priceN, price, toast]);

  useEffect(() => {
    const id = setTimeout(() => { void runPreview(); }, 220);
    return () => clearTimeout(id);
  }, [runPreview]);

  const blocked = !preview || preview.blockers.length > 0;

  const submit = async (): Promise<void> => {
    setConfirming(false);
    setSubmitting(true);
    try {
      const res = await window.krypt.terminal.submit({
        ticker: market.ticker, side, action, count: countN, priceCents: priceN,
      });
      setResult(res);
      toast.push(res.message, res.ok ? 'success' : 'error', 9000);
      if (res.ok) onDone();
    } catch (e) {
      toast.error(`Order failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-krypt-muted">
          Manual order
        </span>
        <span
          className={cls(
            'rounded-full border px-1.5 py-0.5 text-[10px] uppercase tracking-wider',
            live
              ? 'border-krypt-loss/40 bg-krypt-loss/10 text-krypt-loss'
              : 'border-krypt-warn/40 bg-krypt-warn/10 text-krypt-warn',
          )}
          title={live
            ? 'Production: orders here spend real money.'
            : 'Demo: orders here use Kalshi’s paper environment.'}
        >
          {live ? 'live money' : 'demo'}
        </span>
      </div>

      <Segmented
        options={[{ id: 'yes', label: 'YES' }, { id: 'no', label: 'NO' }]}
        value={side}
        onChange={(v) => setSide(v as 'yes' | 'no')}
        tone
      />
      <Segmented
        options={[{ id: 'buy', label: 'Buy' }, { id: 'sell', label: 'Sell' }]}
        value={action}
        onChange={(v) => setAction(v as 'buy' | 'sell')}
      />

      <div className="grid grid-cols-2 gap-2">
        <Field label="Contracts">
          <input
            value={count}
            onChange={(e) => setCount(e.target.value.replace(/[^0-9]/g, ''))}
            inputMode="numeric"
            className="krypt-input font-mono"
          />
        </Field>
        <Field label="Limit price (¢)">
          <input
            value={price}
            onChange={(e) => setPrice(e.target.value.replace(/[^0-9.]/g, ''))}
            inputMode="decimal"
            placeholder="1–99"
            className="krypt-input font-mono"
          />
        </Field>
      </div>

      {position && (
        <div className="rounded-lg border border-krypt-border bg-krypt-surface2/40 px-3 py-2 text-[11px]">
          <div className="text-krypt-muted">
            You hold <span className="font-mono text-white">{position.contracts}</span>{' '}
            {position.side.toUpperCase()} here at{' '}
            {position.avgCostCents === null
              ? <Unknown why="Kalshi's ledger reported no cost basis for this position." />
              : <Cents value={position.avgCostCents} className="text-white" />}{' '}
            average.
          </div>
        </div>
      )}

      <div className="rounded-lg border border-krypt-border bg-krypt-surface2/40 p-3 text-[11px]">
        {pricing && !preview ? (
          <div className="flex items-center gap-2 text-krypt-muted">
            <Loader2 className="h-3 w-3 animate-spin" /> Pricing…
          </div>
        ) : !preview ? (
          <div className="text-krypt-dim">Enter a size and a limit price.</div>
        ) : (
          <div className="space-y-1">
            <Line label={action === 'buy' ? 'Cost' : 'Proceeds'} value={<Usd value={preview.costUsd} />} />
            <Line label="Kalshi fee" value={<Usd value={preview.feeUsd} />} />
            <Line
              label={action === 'buy' ? 'Total out' : 'Net in'}
              value={<Usd value={preview.totalUsd} className="text-white" />}
              strong
            />
            {action === 'buy' ? (
              <>
                <Line label="Max payout" value={<Usd value={preview.maxPayoutUsd} />} />
                <Line
                  label="Breakeven"
                  value={preview.breakevenProb === null
                    ? <Unknown />
                    : <span className="font-mono text-white">
                      {(preview.breakevenProb * 100).toFixed(1)}%
                    </span>}
                  hint="The win rate at which this trade makes nothing, after fees. Below it you lose money even when you are right more often than not."
                />
              </>
            ) : (
              <Line
                label="Realised P&L"
                value={preview.maxProfitUsd === null
                  ? <Unknown why="No reconciled cost basis, so the P&L of this sale is unknown — not zero." />
                  : <Usd value={preview.maxProfitUsd} sign />}
              />
            )}
            {preview.restingBestCents !== null && (
              <Line
                label="Best available"
                value={<Cents value={preview.restingBestCents} />}
                hint={preview.marketableNow
                  ? 'This order should fill immediately.'
                  : 'This order will rest in the book until someone crosses to it.'}
              />
            )}
          </div>
        )}
      </div>

      {preview?.blockers.map((b) => (
        <div key={b} className="flex gap-2 rounded-lg border border-krypt-loss/40 bg-krypt-loss/[0.07] px-3 py-2 text-[11px] leading-relaxed text-krypt-loss">
          <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0" />
          <span>{b}</span>
        </div>
      ))}
      {preview?.warnings.map((w) => (
        <div key={w} className="flex gap-2 rounded-lg border border-krypt-warn/30 bg-krypt-warn/[0.06] px-3 py-2 text-[11px] leading-relaxed text-krypt-warn">
          <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
          <span>{w}</span>
        </div>
      ))}

      <button
        onClick={() => setConfirming(true)}
        disabled={blocked || submitting}
        className={cls('w-full', blocked ? 'krypt-btn-default' : 'krypt-btn-primary')}
      >
        {submitting
          ? <><Loader2 className="h-4 w-4 animate-spin" /> Sending…</>
          : `${action === 'buy' ? 'Buy' : 'Sell'} ${countN || 0} ${side.toUpperCase()}`}
      </button>

      {result && (
        <div
          className={cls(
            'flex gap-2 rounded-lg border px-3 py-2 text-[11px] leading-relaxed',
            result.reconciled
              ? 'border-krypt-win/30 bg-krypt-win/[0.06] text-krypt-muted'
              : 'border-krypt-warn/30 bg-krypt-warn/[0.06] text-krypt-warn',
          )}
        >
          {result.reconciled
            ? <Check className="mt-px h-3.5 w-3.5 shrink-0 text-krypt-win" />
            : <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />}
          <span>{result.message}</span>
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        title={live ? 'Send a REAL order?' : 'Send this demo order?'}
        danger={live}
        confirmLabel={live ? 'Send real order' : 'Send'}
        onClose={() => setConfirming(false)}
        onConfirm={() => void submit()}
        body={
          <div className="space-y-2">
            <p>
              {action === 'buy' ? 'Buy' : 'Sell'}{' '}
              <span className="font-mono text-white">{countN}</span>{' '}
              <span className="font-mono text-white">{side.toUpperCase()}</span> at{' '}
              <span className="font-mono text-white">{priceN}¢</span> on{' '}
              <span className="font-mono text-white">{market.ticker}</span>.
            </p>
            <p className="text-white/90">{market.title}</p>
            {preview?.totalUsd !== null && preview?.totalUsd !== undefined && (
              <p>
                {action === 'buy' ? 'Total out' : 'Net in'}:{' '}
                <Usd value={preview.totalUsd} className="text-white" /> including fees.
              </p>
            )}
            {live && (
              <p className="text-krypt-loss">
                This is the production environment. Real money leaves your Kalshi
                account.
              </p>
            )}
          </div>
        }
      />
    </div>
  );
}

function Segmented({
  options, value, onChange, tone,
}: {
  options: { id: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
  tone?: boolean;
}) {
  return (
    <div className="flex gap-1 rounded-lg border border-krypt-border bg-krypt-surface2/50 p-1">
      {options.map((o) => {
        const on = o.id === value;
        const colour = !tone ? 'bg-white/10 text-white'
          : o.id === 'yes' ? 'bg-krypt-win/20 text-krypt-win'
            : 'bg-krypt-loss/20 text-krypt-loss';
        return (
          <button
            key={o.id}
            onClick={() => onChange(o.id)}
            className={cls(
              'flex-1 rounded px-2 py-1.5 text-xs font-medium transition-colors',
              on ? colour : 'text-krypt-dim hover:text-white',
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="krypt-label">{label}</span>
      {children}
    </label>
  );
}

function Line({
  label, value, strong, hint,
}: { label: string; value: React.ReactNode; strong?: boolean; hint?: string }) {
  return (
    <div
      className={cls('flex items-baseline justify-between gap-3', strong && 'border-t border-krypt-border pt-1')}
      title={hint}
    >
      <span className={cls(hint && 'cursor-help border-b border-dotted border-krypt-border', 'text-krypt-muted')}>
        {label}
      </span>
      <span>{value}</span>
    </div>
  );
}
