import { useCallback, useEffect, useState } from 'react';
import { FlaskConical, KeyRound, Loader2, RotateCcw, ShieldCheck, Wallet, X } from 'lucide-react';
import type { PaperStatus } from '@shared/types';
import { Card, ConfirmDialog, DialogShell, Modal, NumberInput } from './common';
import { KalshiKeyWizard } from './KalshiKeyWizard';
import { StepRow } from './GoLivePanel';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { cls, fmtUsd } from '../utils/format';
import { isLive } from '../utils/account';
import { liveSwitchLines } from '../utils/liveEngines';
import {
  accountGoLiveChecklist, accountGoLivePatch, backToPaperAccountPatch, type KeyVerify,
} from '../utils/goLive';
import { userMessage } from '../utils/errors';

export function AccountModePanel() {
  const { config, refresh, positions } = useApp();
  const toast = useToast();
  const [paper, setPaper] = useState<PaperStatus | null>(null);
  const [goLiveOpen, setGoLiveOpen] = useState(false);
  const [askReset, setAskReset] = useState(false);
  const [askPaper, setAskPaper] = useState<{ open: number; rules: number | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const live = isLive(config);

  const loadPaper = useCallback(async (): Promise<void> => {
    try {
      setPaper(await window.krypt.paper.status());
    } catch {
      setPaper(null);
    }
  }, []);

  useEffect(() => { void loadPaper(); }, [loadPaper, config?.accountMode, config?.paperBankrollUsd]);
  useEffect(() => window.krypt.app.onDataReset(() => { void loadPaper(); }), [loadPaper]);

  const askBackToPaper = async (): Promise<void> => {
    const open = positions.filter((p) => p.kalshiEnv === 'production' && !p.resolved
      && (p.status === 'filled' || p.status === 'partial' || p.status === 'submitted')).length;
    let rules: number | null = null;
    try {
      rules = (await window.krypt.terminal.rules({ limit: 300 })).armedCount;
    } catch {
      rules = null;
    }
    setAskPaper({ open, rules });
  };

  const backToPaper = async (): Promise<void> => {
    setAskPaper(null);
    setBusy(true);
    try {
      await window.krypt.config.update(backToPaperAccountPatch());
      await Promise.allSettled([refresh.state(), refresh.account(), refresh.backend(), refresh.positions()]);
      toast.success('Back on Paper. Nothing can send a real order now; real positions stay open on Kalshi.');
    } catch (e) {
      toast.error(userMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const resetPaper = async (): Promise<void> => {
    setAskReset(false);
    setBusy(true);
    try {
      const r = await window.krypt.paper.reset();
      if (r.ok) toast.success(r.message || 'Paper account reset.');
      else toast.error(r.message || 'Reset failed.');
      await Promise.allSettled([refresh.account(), refresh.positions(), loadPaper()]);
    } finally {
      setBusy(false);
    }
  };

  if (!config) return null;

  return (
    <Card>
      <div className="grid gap-4 md:grid-cols-2" data-testid="account-mode-panel" data-mode={live ? 'live' : 'paper'}>
        <div>
          <label className="krypt-label">Account mode</label>
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="account-mode-paper"
              disabled={busy}
              onClick={() => { if (live) void askBackToPaper(); }}
              className={cls(
                'flex flex-1 items-center justify-center gap-1.5 rounded-md border px-3 py-2 text-sm transition-colors',
                !live
                  ? 'border-krypt-purple bg-krypt-purple/10 text-white'
                  : 'border-krypt-border bg-krypt-surface2 text-krypt-muted hover:border-krypt-borderHi',
              )}
            >
              <FlaskConical className="h-4 w-4" /> Paper
            </button>
            <button
              type="button"
              data-testid="account-mode-live"
              disabled={busy}
              onClick={() => { if (!live) setGoLiveOpen(true); }}
              className={cls(
                'flex flex-1 items-center justify-center gap-1.5 rounded-md border px-3 py-2 text-sm transition-colors',
                live
                  ? 'border-krypt-loss bg-krypt-loss/10 text-white'
                  : 'border-krypt-border bg-krypt-surface2 text-krypt-muted hover:border-krypt-borderHi',
              )}
            >
              <ShieldCheck className="h-4 w-4" /> {live ? 'Live' : 'Go live…'}
            </button>
          </div>
          <p className="krypt-help">
            {live
              ? 'LIVE: orders use your real Kalshi balance. Each engine still has its own live switch, and those can only narrow this one. Paper stops every real order at once (and pauses the stops that manage real positions).'
              : 'PAPER: Kalshi’s real prices, imaginary money, no Kalshi account needed. Every engine — the bot, 15m crypto, scripts, the terminal, phone orders, AI agents and Autopilot — trades the paper book.'}
          </p>
        </div>

        <div className="space-y-2">
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className="krypt-label">Paper starting balance (applies at Reset)</label>
              <NumberInput
                prefix="$"
                min={10}
                max={10_000_000}
                value={config.paperBankrollUsd ?? 1000}
                onChange={(v) => void window.krypt.config.update({ paperBankrollUsd: v }).then(() => refresh.state())}
              />
            </div>
            <button
              type="button"
              className="krypt-btn-default"
              disabled={busy}
              onClick={() => setAskReset(true)}
              data-testid="paper-reset"
            >
              <RotateCcw className="h-4 w-4" /> Reset paper
            </button>
          </div>
          <div className="flex items-center gap-2 text-xs text-krypt-muted" data-testid="paper-cash">
            <Wallet className="h-3.5 w-3.5" />
            Paper cash:{' '}
            <span className="font-mono text-white">{paper ? fmtUsd(paper.cashUsd) : '—'}</span>
            {paper && paper.restingOrders > 0 && (
              <span>· {paper.restingOrders} resting order{paper.restingOrders === 1 ? '' : 's'}</span>
            )}
          </div>
          {paper && paper.nextBankrollUsd !== undefined
            && Math.abs(paper.nextBankrollUsd - paper.bankrollUsd) >= 0.005 && (
            <p className="krypt-help text-krypt-warn" data-testid="paper-bankroll-pending">
              This book started from {fmtUsd(paper.bankrollUsd)}; {fmtUsd(paper.nextBankrollUsd)} applies
              when you Reset paper.
            </p>
          )}
          <p className="krypt-help">
            A new starting balance applies when you Reset — changing it never moves the cash of the
            book you are running. Reset empties the paper book (positions, orders, history) back to
            it. Live is never touched.
          </p>
        </div>
      </div>

      <ConfirmDialog
        open={askReset}
        title="Reset the paper account?"
        danger
        confirmLabel="Reset paper"
        onClose={() => setAskReset(false)}
        onConfirm={() => void resetPaper()}
        body={
          <p>
            Every paper position, resting order, fill and paper run is deleted, and paper cash goes
            back to {fmtUsd(config.paperBankrollUsd ?? 1000)}. Your Live account and its history are
            not touched. This cannot be undone.
          </p>
        }
      />

      <ConfirmDialog
        open={askPaper !== null}
        title="Switch back to Paper?"
        confirmLabel="Switch to Paper"
        onClose={() => setAskPaper(null)}
        onConfirm={() => void backToPaper()}
        body={
          <div className="space-y-2" data-testid="back-to-paper-confirm">
            <p>No real order can be sent from Paper — not an entry, and not an exit.</p>
            <p className="text-krypt-warn">
              That includes the exits guarding your REAL positions: standing stop-loss and
              take-profit rules, 15-minute stops and the bot&apos;s order tracking pause until you
              are Live again. The positions themselves stay open on Kalshi.
            </p>
            <p>
              Open live positions the bot tracks: {askPaper?.open ?? '—'} · armed standing rules:{' '}
              {askPaper?.rules ?? '—'}.
            </p>
          </div>
        }
      />

      {goLiveOpen && <GoLiveAccountDialog onClose={() => setGoLiveOpen(false)} />}
    </Card>
  );
}

export function GoLiveAccountDialog({ onClose }: { onClose: () => void }) {
  const { config, credentialsAll, refresh } = useApp();
  const toast = useToast();
  const [verify, setVerify] = useState<KeyVerify | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [ack, setAck] = useState(false);
  const [wizard, setWizard] = useState(false);
  const [applying, setApplying] = useState(false);
  const prod = credentialsAll?.production;
  const armed = liveSwitchLines(config);
  const list = accountGoLiveChecklist({ config, creds: credentialsAll, verify, armed, ack });

  const runVerify = async (): Promise<void> => {
    if (!prod) return;
    setVerifying(true);
    try {
      const r = await window.krypt.credentials.test();
      setVerify({
        ok: r.ok,
        message: r.ok ? 'Connected to Kalshi' : (r.message || 'auth failed'),
        fingerprint: prod.fingerprint,
        balanceUsd: r.ok ? r.data?.balanceUsd ?? null : null,
      });
    } catch (e) {
      setVerify({ ok: false, message: userMessage(e), fingerprint: prod.fingerprint });
    } finally {
      setVerifying(false);
    }
  };

  const afterWizard = async (v?: { balanceUsd: number | null }): Promise<void> => {
    await refresh.credentials();
    if (!v) return;
    try {
      const all = await window.krypt.credentials.statusAll();
      const fp = all?.production?.fingerprint;
      if (fp) setVerify({ ok: true, message: 'Connected to Kalshi', fingerprint: fp, balanceUsd: v.balanceUsd });
    } catch {}
  };

  const apply = async (): Promise<void> => {
    if (!list.ready) return;
    setApplying(true);
    try {
      await window.krypt.config.update(accountGoLivePatch());
      await Promise.allSettled([
        refresh.state(), refresh.credentials(), refresh.account(), refresh.backend(), refresh.positions(),
      ]);
      toast.warn('The app is LIVE: orders now use your real Kalshi balance.');
      onClose();
    } catch (e) {
      toast.error(`Go live failed: ${userMessage(e)}`);
    } finally {
      setApplying(false);
    }
  };

  return (
    <>
      <DialogShell onClose={onClose} maxWidth="max-w-xl">
        <div className="max-h-[82vh] overflow-y-auto pr-1" data-testid="golive-account">
          <div className="mb-3 flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-krypt-loss" />
            <div className="flex-1">
              <h3 className="text-sm font-semibold text-white">Go live — trade real money</h3>
              <p className="mt-0.5 text-[11px] text-krypt-muted">
                Switches the whole app from Paper to your real Kalshi account. Nothing changes until
                the last button, and Paper is one click away afterwards.
              </p>
            </div>
            <button onClick={onClose} className="krypt-btn-ghost p-1" aria-label="Close">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-3">
            {list.steps.map((step, i) => (
              <StepRow key={step.id} n={i + 1} step={step}>
                {step.id === 'keys' && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {prod?.hasApiKey && prod?.hasRsaKey ? (
                      <button
                        onClick={() => void runVerify()}
                        disabled={verifying}
                        className="krypt-btn-default text-xs"
                        data-testid="golive-account-verify"
                      >
                        {verifying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
                        Verify (one signed balance read)
                      </button>
                    ) : (
                      <button
                        onClick={() => setWizard(true)}
                        className="krypt-btn-default text-xs"
                        data-testid="golive-account-addkey"
                      >
                        <KeyRound className="h-3.5 w-3.5" /> Add a Kalshi key
                      </button>
                    )}
                  </div>
                )}
                {step.id === 'engines' && armed.length > 0 && (
                  <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[11px] text-krypt-loss">
                    {armed.map((a) => <li key={a}>{a}</li>)}
                  </ul>
                )}
                {step.id === 'ack' && (
                  <label className="mt-2 flex items-start gap-3 rounded-lg border border-krypt-loss/40 bg-krypt-loss/5 p-3">
                    <input
                      type="checkbox"
                      checked={ack}
                      onChange={(e) => setAck(e.target.checked)}
                      className="mt-0.5 h-4 w-4 accent-krypt-loss"
                      data-testid="golive-account-ack"
                    />
                    <span className="text-xs text-white/90">
                      I understand that in Live every order — mine, the bot&apos;s, my agents&apos; —
                      spends my real Kalshi balance, and that past paper results promise nothing.
                    </span>
                  </label>
                )}
              </StepRow>
            ))}
            <div className="flex items-center justify-end gap-2 pt-1">
              {!list.ready && (
                <span className="mr-auto text-[11px] text-krypt-loss">
                  {list.steps.filter((s) => s.state === 'block').map((s) => s.title).join(', ')} still needs you.
                </span>
              )}
              <button onClick={onClose} className="krypt-btn-default text-xs">Stay on Paper</button>
              <button
                onClick={() => void apply()}
                disabled={!list.ready || applying}
                className="krypt-btn-danger text-xs"
                data-testid="golive-account-apply"
              >
                {applying && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Switch to Live
              </button>
            </div>
          </div>
        </div>
      </DialogShell>
      <Modal open={wizard} onClose={() => setWizard(false)}>
        <KalshiKeyWizard
          onDone={(v) => { setWizard(false); void afterWizard(v); }}
          onSkip={() => setWizard(false)}
          onBackOut={() => setWizard(false)}
        />
      </Modal>
    </>
  );
}
