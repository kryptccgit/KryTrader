import { useState } from 'react';
import { AlertTriangle, Bell, ShieldAlert, Target, X } from 'lucide-react';
import type {
  MarketSummary, RuleKind, TerminalPosition, TerminalRule,
} from '@shared/market';
import { useToast } from '../../state/ToastProvider';
import { cls } from '../../utils/format';
import { Caveat, Cents, SidePill, Unknown } from './atoms';
import { userMessage } from '../../utils/errors';


const KINDS: { id: RuleKind; label: string; icon: React.ComponentType<{ className?: string }>; blurb: string }[] = [
  {
    id: 'stop', label: 'Stop loss', icon: ShieldAlert,
    blurb: 'Sell if the bid falls to or below this price.',
  },
  {
    id: 'take', label: 'Take profit', icon: Target,
    blurb: 'Sell if the bid reaches this price.',
  },
  {
    id: 'alert', label: 'Alert', icon: Bell,
    blurb: 'Just tell me. Nothing is bought or sold — the notification stays on this machine.',
  },
];

export function ArmRule({
  market, position, onArmed,
}: {
  market: MarketSummary;
  position: TerminalPosition | null;
  onArmed: () => void;
}) {
  const toast = useToast();
  const [kind, setKind] = useState<RuleKind>('stop');
  const [side, setSide] = useState<'yes' | 'no'>(position?.side ?? 'yes');
  const [threshold, setThreshold] = useState('');
  const [busy, setBusy] = useState(false);

  const meta = KINDS.find((k) => k.id === kind)!;
  const isExit = kind !== 'alert';
  const direction: 'below' | 'above' = kind === 'stop' ? 'below' : 'above';
  const n = Number(threshold);
  const valid = Number.isFinite(n) && n >= 1 && n <= 99;

  const arm = async (): Promise<void> => {
    setBusy(true);
    try {
      await window.krypt.terminal.armRule({
        kind, ticker: market.ticker, side, thresholdCents: n, direction,
      });
      toast.success(
        `${meta.label} armed on ${market.ticker} at ${n}¢. It is listed on My Book and can be cancelled there.`,
      );
      setThreshold('');
      onArmed();
    } catch (e) {
      toast.error(userMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2.5">
      <div className="flex gap-1 rounded-lg border border-krypt-border bg-krypt-surface2/50 p-1">
        {KINDS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setKind(id)}
            className={cls(
              'flex flex-1 items-center justify-center gap-1 rounded px-1.5 py-1.5 text-[11px] font-medium transition-colors',
              kind === id ? 'bg-white/10 text-white' : 'text-krypt-dim hover:text-white',
            )}
          >
            <Icon className="h-3 w-3" />
            {label}
          </button>
        ))}
      </div>

      <p className="text-[11px] leading-relaxed text-krypt-muted">{meta.blurb}</p>

      {isExit && !position && (
        <Caveat>
          You hold nothing here yet. The rule can be armed now — it will simply
          find nothing to close and retire itself if it fires while you are flat.
        </Caveat>
      )}

      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="krypt-label">Side</span>
          <div className="flex gap-1 rounded-lg border border-krypt-border bg-krypt-surface2/50 p-1">
            {(['yes', 'no'] as const).map((sv) => (
              <button
                key={sv}
                onClick={() => setSide(sv)}
                className={cls(
                  'flex-1 rounded px-2 py-1 text-[11px] font-semibold uppercase transition-colors',
                  side === sv
                    ? (sv === 'yes' ? 'bg-krypt-win/20 text-krypt-win' : 'bg-krypt-loss/20 text-krypt-loss')
                    : 'text-krypt-dim hover:text-white',
                )}
              >
                {sv}
              </button>
            ))}
          </div>
        </label>
        <label className="block">
          <span className="krypt-label">
            {kind === 'stop' ? 'Below (¢)' : 'At or above (¢)'}
          </span>
          <input
            value={threshold}
            onChange={(e) => setThreshold(e.target.value.replace(/[^0-9.]/g, ''))}
            placeholder="1–99"
            inputMode="decimal"
            className="krypt-input font-mono"
          />
        </label>
      </div>

      <button
        onClick={() => void arm()}
        disabled={!valid || busy}
        className={cls('w-full', valid ? 'krypt-btn-default' : 'krypt-btn-default')}
      >
        {busy ? 'Arming…' : `Arm ${meta.label.toLowerCase()}`}
      </button>

      <p className="text-[10px] leading-relaxed text-krypt-dim">
        Checked every few seconds against the live book. It fires the same order
        path as selling by hand, with the same caps — and it never fires on a
        price nobody could produce: if there is no bid, it stays armed and says so.
      </p>
    </div>
  );
}

export function RuleList({
  rules, onChanged, compact,
}: { rules: TerminalRule[]; onChanged: () => void; compact?: boolean }) {
  const toast = useToast();
  const [busy, setBusy] = useState<number | null>(null);

  const cancel = async (id: number): Promise<void> => {
    setBusy(id);
    try {
      const res = await window.krypt.terminal.cancelRule({ id });
      toast.push(res.message, res.ok ? 'success' : 'error');
      onChanged();
    } catch (e) {
      toast.error(userMessage(e));
    } finally {
      setBusy(null);
    }
  };

  if (rules.length === 0) {
    return (
      <div className="py-6 text-center text-[11px] text-krypt-muted">
        Nothing standing. A stop loss or alert armed from a market page appears
        here, and can be cancelled from here.
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {rules.map((r) => {
        const Icon = KINDS.find((k) => k.id === r.kind)?.icon ?? Bell;
        const armed = r.status === 'armed';
        const blind = armed && r.lastPriceCents === null && !!r.lastCheckedAt;
        return (
          <div
            key={r.id}
            className={cls(
              'rounded-lg border px-2.5 py-2 text-[11px]',
              armed ? 'border-krypt-border bg-krypt-surface2/40' : 'border-krypt-border/50 bg-transparent opacity-70',
            )}
          >
            <div className="flex items-center gap-2">
              <Icon className={cls('h-3.5 w-3.5 shrink-0',
                r.kind === 'stop' ? 'text-krypt-loss'
                  : r.kind === 'take' ? 'text-krypt-win' : 'text-krypt-warn')} />
              <SidePill side={r.side} />
              <span className="text-krypt-muted">
                {r.direction === 'below' ? '≤' : '≥'}
              </span>
              <Cents value={r.thresholdCents} className="text-white" />
              {!compact && (
                <span className="truncate text-krypt-dim">
                  {r.title ?? r.ticker}
                </span>
              )}
              <span
                className={cls(
                  'ml-auto rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider',
                  armed ? 'bg-krypt-win/15 text-krypt-win'
                    : r.status === 'firing' ? 'bg-krypt-warn/15 text-krypt-warn'
                      : r.status === 'triggered' ? 'bg-krypt-purple/15 text-krypt-purple'
                        : r.status === 'error' ? 'bg-krypt-loss/15 text-krypt-loss'
                          : 'bg-white/5 text-krypt-dim',
                )}
              >
                {r.status}
              </span>
              {armed && (
                <button
                  onClick={() => void cancel(r.id)}
                  disabled={busy === r.id}
                  title="Cancel this instruction"
                  className="grid h-5 w-5 place-items-center rounded text-krypt-dim transition-colors hover:bg-krypt-loss/10 hover:text-krypt-loss disabled:opacity-40"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>

            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-krypt-dim">
              {compact && <span className="font-mono">{r.ticker}</span>}
              <span>
                last seen{' '}
                {r.lastPriceCents === null
                  ? <Unknown why="No bid on this side at the last check, so there was no price to compare." />
                  : <Cents value={r.lastPriceCents} />}
              </span>
              {r.lastCheckedAt && (
                <span>checked {new Date(r.lastCheckedAt).toLocaleTimeString()}</span>
              )}
            </div>

            {blind && (
              <div className="mt-1.5 flex gap-1.5 text-[10px] leading-relaxed text-krypt-warn">
                <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
                <span>{r.lastError}</span>
              </div>
            )}
            {!armed && r.lastError && (
              <div className="mt-1.5 text-[10px] leading-relaxed text-krypt-muted">
                {r.lastError}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
