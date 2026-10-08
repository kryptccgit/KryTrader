import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle, ArrowLeftRight, ArrowRight, ExternalLink, Wallet,
} from 'lucide-react';
import { ConfirmDialog, NumberInput } from '../common';
import { useToast } from '../../state/ToastProvider';
import { useApp } from '../../state/AppStateProvider';
import { cls } from '../../utils/format';
import { userMessage } from '../../utils/errors';

export interface ShardCash {
  index: number;
  name: string;
  cashUsd: number;
}

function useShardTransfer(shards: ShardCash[], onDone?: () => void) {
  const toast = useToast();
  const sorted = useMemo(
    () => [...shards].sort((a, b) => a.index - b.index), [shards]);

  const richest = useMemo(
    () => [...sorted].sort((a, b) => b.cashUsd - a.cashUsd)[0], [sorted]);
  const poorest = useMemo(
    () => [...sorted].sort((a, b) => a.cashUsd - b.cashUsd)[0], [sorted]);

  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [amount, setAmount] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const src = sorted.find((s) => s.index === (from ?? richest?.index));
  const dst = sorted.find((s) => s.index === (to ?? poorest?.index));
  const parsed = Number(amount);
  const available = src?.cashUsd ?? 0;
  const valid = !!src && !!dst && src.index !== dst.index
    && Number.isFinite(parsed) && parsed > 0 && parsed <= available;

  async function run(): Promise<void> {
    if (!src || !dst) return;
    setConfirming(false);
    setBusy(true);
    try {
      const res = await window.krypt.terminal.shardTransfer({
        amountUsd: parsed, fromShard: src.index, toShard: dst.index,
      });
      if (res.ok) {
        toast.success(res.message);
        setAmount('');
      } else {
        toast.error(res.message);
      }
      onDone?.();
    } catch (e) {
      toast.error(userMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return {
    sorted, src, dst, parsed, available, valid, busy,
    amount, setAmount, setFrom, setTo,
    confirming, setConfirming, run,
  };
}

type Transfer = ReturnType<typeof useShardTransfer>;

function TransferControls({ t, transferUrl }: { t: Transfer; transferUrl: string }) {
  const { sorted, src, dst, parsed, available, valid, busy } = t;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] text-krypt-muted">Move</span>
      <span className="flex items-center rounded border border-krypt-border bg-krypt-surface2 px-1.5">
        <span className="text-[10px] opacity-70">$</span>
        <input
          value={t.amount}
          onChange={(e) => t.setAmount(e.target.value)}
          inputMode="decimal"
          placeholder="0.00"
          aria-label="Amount to move"
          className="w-20 bg-transparent px-1 py-0.5 text-[11px] outline-none"
        />
      </span>

      <select
        value={src?.index ?? ''}
        onChange={(e) => t.setFrom(Number(e.target.value))}
        aria-label="Move from"
        className="rounded border border-krypt-border bg-krypt-surface2 px-1.5 py-0.5 text-[11px]"
      >
        {sorted.map((s) => (
          <option key={s.index} value={s.index}>
            {s.name} (${s.cashUsd.toFixed(2)})
          </option>
        ))}
      </select>

      <ArrowRight className="h-3 w-3 text-krypt-dim" />

      <select
        value={dst?.index ?? ''}
        onChange={(e) => t.setTo(Number(e.target.value))}
        aria-label="Move to"
        className="rounded border border-krypt-border bg-krypt-surface2 px-1.5 py-0.5 text-[11px]"
      >
        {sorted.map((s) => (
          <option key={s.index} value={s.index}>{s.name}</option>
        ))}
      </select>

      <button
        disabled={!valid || busy}
        onClick={() => t.setConfirming(true)}
        className="rounded border border-krypt-border px-2 py-0.5 text-[10px] font-medium hover:bg-krypt-surface2 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? 'Moving…' : 'Move'}
      </button>

      {!!transferUrl && (
        <button
          onClick={() => void window.krypt.app.openExternal(transferUrl)}
          className="inline-flex items-center gap-1 rounded border border-krypt-border px-2 py-0.5 text-[10px] hover:bg-krypt-surface2"
          title="Do it on Kalshi instead"
        >
          On Kalshi
          <ExternalLink className="h-3 w-3" />
        </button>
      )}

      {src && dst && src.index === dst.index && (
        <span className="text-[10px] text-krypt-muted">
          Pick two different exchanges.
        </span>
      )}
      {Number.isFinite(parsed) && parsed > available && (
        <span className="text-[10px] text-krypt-muted">
          {src?.name} only holds ${available.toFixed(2)}.
        </span>
      )}
    </div>
  );
}

function TransferConfirm({ t }: { t: Transfer }) {
  const { src, dst, parsed } = t;
  if (!t.confirming) return null;
  return createPortal((
    <div data-shard-modal>
    <ConfirmDialog
      open={t.confirming}
      danger
      title="Move collateral between exchanges?"
      confirmLabel={`Move $${Number.isFinite(parsed) ? parsed.toFixed(2) : '0.00'}`}
      onClose={() => t.setConfirming(false)}
      onConfirm={() => void t.run()}
      body={(
        <div className="space-y-2">
          <p>
            This moves{' '}
            <span className="font-medium text-white">
              ${Number.isFinite(parsed) ? parsed.toFixed(2) : '0.00'}
            </span>{' '}
            of real collateral from{' '}
            <span className="font-medium text-white">{src?.name}</span> to{' '}
            <span className="font-medium text-white">{dst?.name}</span>.
          </p>
          <p className="flex items-start gap-1.5 text-krypt-warn">
            <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
            <span>
              Money on {dst?.name} can only back orders on {dst?.name}.
              Kalshi does not move it back on its own — you would return it
              the same way.
            </span>
          </p>
        </div>
      )}
    />
    </div>
  ), document.body);
}

function AutoMoveRow() {
  const { config, refresh } = useApp();
  if (!config) return null;
  const on = config.shardAutoMove !== false;
  const cap = config.shardAutoMoveMaxUsdDay ?? 1000;
  const save = (patch: Partial<typeof config>) =>
    void window.krypt.config.update(patch as never).then(() => refresh.state());
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-krypt-border pt-2 text-[11px]">
      <label className="flex cursor-pointer items-center gap-2">
        <input type="checkbox" checked={on} onChange={(e) => save({ shardAutoMove: e.target.checked })} />
        <span className="text-white">Move funds for live orders automatically</span>
      </label>
      {on && (
        <span className="flex items-center gap-1.5 text-krypt-dim">
          up to
          <span className="w-24">
            <NumberInput prefix="$" min={1} max={10_000_000} value={cap}
              onChange={(v) => save({ shardAutoMoveMaxUsdDay: v })} />
          </span>
          a day, with your AI agents' moves
        </span>
      )}
      <span className="basis-full text-[10px] leading-relaxed text-krypt-muted">
        {on
          ? "Before a live buy, if its market's exchange can't cover it, the app moves just the shortfall from the exchange with the most cash. The money stays in your account."
          : 'Off: an order on an exchange without enough cash is refused by Kalshi until you move funds yourself.'}
      </span>
    </div>
  );
}

export function ShardBalances({
  shards, transferUrl, onDone, className,
}: {
  shards: ShardCash[];
  transferUrl: string;
  onDone?: () => void;
  className?: string;
}) {
  const { config } = useApp();
  const autoMoveOn = config?.shardAutoMove !== false;
  const t = useShardTransfer(shards, onDone);
  const [open, setOpen] = useState(false);
  const { sorted } = t;

  if (sorted.length < 2) return null;

  const anyEmpty = sorted.some((s) => s.cashUsd <= 0);
  const auto = autoMoveOn;

  return (
    <div className={cls('rounded-xl border border-krypt-border bg-krypt-surface px-3 py-2', className)}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-krypt-muted">
          <Wallet className="h-3.5 w-3.5" />
          Cash by exchange
        </span>

        {sorted.map((s) => (
          <span key={s.index} className="flex items-baseline gap-1.5 font-mono text-[11px]">
            <span className="text-krypt-dim">{s.name}</span>
            <span className={s.cashUsd > 0 ? 'text-white' : 'text-krypt-loss'}>
              ${s.cashUsd.toFixed(2)}
            </span>
          </span>
        ))}

        <button
          onClick={() => setOpen((v) => !v)}
          className="ml-auto rounded border border-krypt-border px-2 py-0.5 text-[10px] hover:bg-krypt-surface2"
        >
          {open ? 'Close' : 'Move funds'}
        </button>
      </div>

      {anyEmpty && !open && !auto && (
        <div className="mt-1.5 flex items-start gap-1.5 text-[10px] leading-relaxed text-krypt-muted">
          <AlertTriangle className="mt-px h-3 w-3 shrink-0 text-krypt-warn" />
          <span>
            An exchange holding $0.00 cannot back an order on the markets it
            hosts, whatever your total says — Kalshi allocates collateral per
            exchange and does not move it for you.
          </span>
        </div>
      )}

      <AutoMoveRow />

      {open && (
        <div className="mt-2 border-t border-krypt-border pt-2">
          <TransferControls t={t} transferUrl={transferUrl} />
        </div>
      )}

      <TransferConfirm t={t} />
    </div>
  );
}

export function ShardStrip({
  shards, transferUrl, onDone, className,
}: {
  shards: ShardCash[];
  transferUrl: string;
  onDone?: () => void;
  className?: string;
}) {
  const t = useShardTransfer(shards, onDone);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const { sorted } = t;

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const onDown = (e: MouseEvent) => {
      const el = wrapRef.current;
      if (el && !el.contains(e.target as Node)
          && !(e.target as Element | null)?.closest?.('[data-shard-modal]')) {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [open]);

  if (sorted.length < 2) return null;

  return (
    <div ref={wrapRef} className={cls('relative flex items-center gap-2', className)}>
      <div className="hidden items-center gap-2.5 lg:flex">
        {sorted.map((s) => (
          <span
            key={s.index}
            title={`${s.name}: $${s.cashUsd.toFixed(2)}`}
            className="flex items-baseline gap-1 whitespace-nowrap font-mono text-[11px]"
          >
            <span className="max-w-[4.5rem] truncate text-krypt-dim">{s.name}</span>
            <span className={s.cashUsd > 0 ? 'text-white' : 'text-krypt-muted'}>
              ${s.cashUsd.toFixed(2)}
            </span>
          </span>
        ))}
      </div>

      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="Swap cash between exchanges"
        title="Swap cash between exchanges"
        className={cls(
          'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition-colors',
          open
            ? 'border-krypt-borderHi bg-white/5 text-white'
            : 'border-krypt-border text-krypt-muted hover:border-krypt-borderHi hover:bg-white/5 hover:text-white',
        )}
      >
        <ArrowLeftRight className="h-3.5 w-3.5" />
        Swap
      </button>

      {open && (
        <div className="absolute right-0 top-full z-40 mt-2 w-[26rem] rounded-2xl border border-white/10 bg-[rgba(17,16,28,0.96)] p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_24px_48px_-20px_rgba(0,0,0,0.9)]">
          <div className="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-krypt-muted">
            <Wallet className="h-3.5 w-3.5" />
            Move cash between exchanges
          </div>
          <TransferControls t={t} transferUrl={transferUrl} />
          <p className="mt-2 text-[10px] leading-relaxed text-krypt-muted">
            Kalshi holds collateral per exchange and never moves it for you, so
            an order fills only against the exchange hosting its market — your
            total is not what any one order can spend.
          </p>
        </div>
      )}

      <TransferConfirm t={t} />
    </div>
  );
}
