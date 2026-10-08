import { useState } from 'react';
import { Gem, Play, X, AlertTriangle, CalendarClock, Check } from 'lucide-react';
import { cls } from '../utils/format';
import { optimizerEvent, publishActivity } from '../state/activity';
import type { CoinOptimizeResult, CoinOptimizeAgg, Crypto15mRunner, Crypto15mScheduleSlot } from '@shared/types';
import { userMessage } from '../utils/errors';

const COINS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'HYPE', 'BNB'];
const BUCKETS = [1, 2, 3, 4, 6, 8, 12, 24];
const WINDOWS = [7, 14, 30, 60];

function edge(a: CoinOptimizeAgg | null): string {
  if (!a || !a.n) return '';
  const wr = a.winRate != null ? `${Math.round(a.winRate * 100)}%` : '—';
  return `${a.netCents >= 0 ? '+' : ''}${a.netCents.toFixed(1)}¢ · t${a.t ?? '—'} · n${a.n} · ${wr}`;
}

function newId(): string {
  try { return crypto.randomUUID().slice(0, 8); } catch { return Math.random().toString(36).slice(2, 10); }
}

export function CoinOptimizer({ onClose, onSaveRunner }: {
  onClose: () => void;
  onSaveRunner?: (runner: Crypto15mRunner) => void;
}) {
  const [coin, setCoin] = useState('BTC');
  const [gran, setGran] = useState(4);
  const [days, setDays] = useState(30);
  const [running, setRunning] = useState(false);
  const [res, setRes] = useState<CoinOptimizeResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const EXEC_KEYS = new Set([
    'crypto15m_order_size', 'crypto15m_sizing_mode', 'crypto15m_balance_pct',
    'crypto15m_max_loss_pct', 'crypto15m_stop_loss_pct', 'crypto15m_take_profit_cents',
    'crypto15m_max_concurrent', 'crypto15m_entry_style',
  ]);
  const stripExec = (c: Record<string, unknown>) =>
    Object.fromEntries(Object.entries(c).filter(([k]) => !EXEC_KEYS.has(k)));

  const saveRunner = () => {
    if (!res || !onSaveRunner) return;
    const schedule: Crypto15mScheduleSlot[] = res.schedule
      .filter((s) => s.winner && s.config)
      .map((s) => ({ startHour: s.start, endHour: s.end, name: s.winner!, config: stripExec(s.config as Record<string, unknown>) }));
    if (!schedule.length) return;
    onSaveRunner({
      id: newId(), name: `${res.coin} optimized (${res.granularityH}h)`,
      coins: [res.coin], mode: 'paper', enabled: false, config: {}, schedule,
    });
    setSaved(true);
  };

  const runOpt = async () => {
    setRunning(true); setErr(null);
    try {
      const r = await window.krypt?.turbine?.optimize({ coin, granularityH: gran, sinceDays: days });
      if (r) setRes(r);
      else setErr('Backend not running — start the app to run the optimizer.');
      publishActivity(() => optimizerEvent(r));
    } catch (e) {
      setErr(userMessage(e).slice(0, 160));
    } finally {
      setRunning(false);
    }
  };

  const Chip = ({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) => (
    <button onClick={onClick} className={cls(
      'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
      on ? 'bg-krypt-purple/25 text-white ring-1 ring-krypt-purple/50' : 'bg-krypt-surface2 text-krypt-muted hover:text-white',
    )}>{children}</button>
  );

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-6 backdrop-blur-sm" onClick={onClose}>
      <div className="my-4 w-full max-w-3xl rounded-2xl border border-krypt-border bg-krypt-void shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-krypt-border px-5 py-4">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-krypt-purple/15 text-krypt-purple"><Gem className="h-5 w-5" /></span>
          <div className="flex-1">
            <div className="font-pixel text-[11px] uppercase tracking-[0.16em] text-white">Coin Optimizer</div>
            <div className="text-xs text-krypt-muted">Sweeps every strategy per hour-bucket for one coin, then assembles the best 24h schedule — winners elected on train, scored on a held-out recent split.</div>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-krypt-muted hover:bg-white/5 hover:text-white"><X className="h-5 w-5" /></button>
        </div>

        <div className="space-y-3 px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-16 text-[11px] uppercase tracking-wide text-krypt-dim">Coin</span>
            {COINS.map((c) => <Chip key={c} on={coin === c} onClick={() => setCoin(c)}>{c}</Chip>)}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-16 text-[11px] uppercase tracking-wide text-krypt-dim">Buckets</span>
            {BUCKETS.map((b) => <Chip key={b} on={gran === b} onClick={() => setGran(b)}>{b}h</Chip>)}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-16 text-[11px] uppercase tracking-wide text-krypt-dim">Window</span>
            {WINDOWS.map((w) => <Chip key={w} on={days === w} onClick={() => setDays(w)}>{w}d</Chip>)}
            <button onClick={runOpt} disabled={running} className={cls(
              'ml-auto flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              running ? 'bg-krypt-surface2 text-krypt-muted' : 'bg-krypt-purple text-white hover:bg-krypt-purple/90',
            )}>
              <Play className="h-3.5 w-3.5" /> {running ? 'Sweeping… (~15s)' : `Run optimizer (${coin})`}
            </button>
          </div>

          {err && <div className="rounded-lg border border-krypt-loss/40 bg-krypt-loss/10 px-3 py-2 text-xs text-krypt-loss">{err}</div>}

          {res && (
            <div className="space-y-3 border-t border-krypt-border pt-3">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-krypt-muted">
                <span>Swept <b className="text-white">{res.strategiesSwept}</b> strategies</span>
                <span>{res.granularityH}h buckets</span>
                <span>{res.holdoutDays > 0 ? `holdout ${res.holdoutDays}d` : 'no holdout'}</span>
                {res.coinWinner && (
                  <span>coin winner: <b className="text-white">{res.coinWinner.name}</b>{' '}
                    <span className={res.coinWinner.netCents >= 0 ? 'text-krypt-win' : 'text-krypt-loss'}>{edge(res.coinWinner)}</span>
                  </span>
                )}
              </div>

              <div>
                <div className="mb-1.5 text-[11px] uppercase tracking-wide text-krypt-dim">Assembled 24h schedule — winning strategy per bucket</div>
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                  {res.schedule.map((s) => {
                    const shown = s.holdout && s.holdout.n ? s.holdout : s.train;
                    return (
                      <div key={s.bucket} className={cls(
                        'rounded-lg border px-2.5 py-1.5',
                        s.winner ? 'border-krypt-border bg-krypt-surface/50' : 'border-dashed border-krypt-border/60',
                      )}>
                        <div className="font-mono text-[11px] text-krypt-dim">{s.bucket}–{String(s.end).padStart(2, '0')}:00</div>
                        <div className="truncate text-xs text-white" title={s.winner || ''}>{s.winner || '— none'}</div>
                        {shown && shown.n > 0 && (
                          <div className={cls('font-mono text-[10px]', shown.netCents >= 0 ? 'text-krypt-win' : 'text-krypt-loss')}>
                            {edge(shown)}{s.holdout && s.holdout.n ? ' · OOS' : ''}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3 rounded-lg border border-krypt-border bg-krypt-surface/40 px-3 py-2 text-xs">
                <span className="uppercase tracking-wide text-krypt-dim">Assembled edge</span>
                <span className={cls('font-mono', res.assembled.netCents >= 0 ? 'text-krypt-win' : 'text-krypt-loss')}>{edge(res.assembled)}</span>
                <span className="text-krypt-dim">{res.holdoutDays > 0 ? '(out-of-sample)' : '(in-sample)'}</span>
                {onSaveRunner && res.schedule.some((s) => s.winner) && (
                  saved ? (
                    <span className="ml-auto flex items-center gap-1 text-krypt-win"><Check className="h-3.5 w-3.5" /> Saved as scheduled runner</span>
                  ) : (
                    <button onClick={saveRunner} className="ml-auto flex items-center gap-1.5 rounded-lg bg-krypt-purple px-3 py-1.5 text-xs font-medium text-white hover:bg-krypt-purple/90">
                      <CalendarClock className="h-3.5 w-3.5" /> Save as scheduled runner
                    </button>
                  )
                )}
              </div>

              <div className="flex items-start gap-2 text-[11px] text-krypt-warn">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {res.caveat} Buckets that elected nobody didn't clear the min-trade floor — feed more data (run <span className="font-mono">npm run py:backfill --loop</span>) and re-run.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
