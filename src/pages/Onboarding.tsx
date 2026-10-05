import { useState } from 'react';
import { ArrowRight, ExternalLink, Gift, ShieldAlert } from 'lucide-react';
import { useToast } from '../state/ToastProvider';
import { openKalshiReferral } from '../utils/links';

export function OnboardingModal({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [accepted, setAccepted] = useState(false);
  const toast = useToast();

  const finish = async (): Promise<void> => {
    if (!accepted) {
      toast.warn('Please tick the disclaimer to continue');
      return;
    }
    await window.krypt.state.acceptDisclaimer();
    toast.success('Welcome to Krypt Trader');
    onDone();
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 backdrop-blur">
      <div className="w-[640px] max-w-[92vw] overflow-hidden rounded-2xl border border-krypt-borderHi bg-krypt-surface shadow-krypt-strong">
        <div className="bg-krypt-glow p-1">
          <div className="rounded-t-xl bg-krypt-surface px-8 py-6 text-center">
            <div className="mx-auto mb-3 grid h-16 w-16 place-items-center rounded-2xl bg-krypt-glow shadow-krypt-strong">
              <span className="font-pixel text-xs">K</span>
            </div>
            <h2 className="font-pixel text-base tracking-wider">KRYPT TRADER</h2>
            <p className="mt-1 text-xs text-krypt-muted">
              The free Kalshi auto-trader.
            </p>
          </div>
        </div>

        <div className="px-8 py-6">
          {step === 0 && (
            <div className="space-y-4 text-sm text-white/90">
              <p>
                Krypt Trader is two things in one window. The{' '}
                <span className="text-white">Terminal</span> is the manual side:
                browse every Kalshi market, read its resolution risk, and place
                orders by hand. The <span className="text-white">automation</span>{' '}
                is the original bot — it watches whale flow and momentum signals,
                scores them, and (optionally) places contrarian bets on the
                highest-edge setups. Everything runs locally on your machine —
                your API keys never leave it.
              </p>
              <ul className="grid grid-cols-2 gap-3 text-xs">
                <Feature title="Terminal" body="Every market, charted and priced. Trade by hand." />
                <Feature title="Resolution risk" body="Who settles it, on what source, how vague the wording." />
                <Feature title="Whale tracker" body="$2.5k+ taker orders, scored." />
                <Feature title="Momentum scanner" body="Trade-cluster contrarian fades." />
                <Feature title="Auto-trader" body="Limit-cross orders, sized 2-6%." />
                <Feature title="Strategy scripts" body="Write your own — sandboxed, with money rails." />
                <Feature title="Daily P&L gate" body="Stop-loss / take-profit safety." />
                <Feature title="Local SQLite" body="Full trade history, exportable." />
                <Feature title="Tray + autostart" body="Runs in the background between sessions." />
              </ul>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4 text-sm text-white/90">
              <h3 className="text-base font-semibold">Quick start</h3>
              <ol className="list-decimal space-y-2 pl-4 text-sm text-krypt-muted">
                <li>Open the <span className="text-white">Terminal</span> and look around — browsing markets, charts and resolution rules needs no key at all.</li>
                <li>Create a Kalshi API key + RSA private key in your account settings.</li>
                <li>Paste both into the API Keys page (we&apos;ll send you there).</li>
                <li>Start on the <span className="text-white">demo</span> environment and paper-test a strategy before risking money.</li>
                <li>Verify the connection &amp; balance, then unpause trading.</li>
                <li>Tweak knobs in Settings — everything is live-editable.</li>
              </ol>
              <button
                type="button"
                onClick={() => void openKalshiReferral()}
                className="flex w-full items-center gap-3 rounded-lg border border-krypt-purple/40 bg-gradient-to-r from-krypt-indigo/10 via-krypt-purple/10 to-krypt-pink/10 p-3 text-left transition-colors hover:border-krypt-purple"
              >
                <Gift className="h-5 w-5 shrink-0 text-krypt-purple" />
                <div className="flex-1">
                  <div className="text-sm text-white">No Kalshi account yet?</div>
                  <div className="text-xs text-krypt-muted">
                    Sign up via our referral and Kalshi gives you{' '}
                    <span className="text-white">$25 free</span> after your first deposit.
                  </div>
                </div>
                <ExternalLink className="h-4 w-4 text-krypt-muted" />
              </button>
              <div className="rounded-lg border border-krypt-warn/40 bg-krypt-warn/5 p-3 text-xs text-krypt-warn">
                You start on the <strong>DEMO</strong> environment — the bot trades Kalshi&apos;s
                play-money sandbox until you switch to <strong>Production</strong> in Settings.
                Fund at least <strong>$25</strong> before going live: on smaller balances the
                default 2–6% sizing falls under the <strong>$1-per-order minimum</strong> and the
                bot won&apos;t place anything. (The 15-minute crypto tab and the Scripts tab each
                have their own <strong>LIVE</strong> switch and only trade for real on a Production
                account — leave them off unless you mean it.)
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4 text-sm">
              <div className="flex items-start gap-3 rounded-lg border border-krypt-loss/30 bg-krypt-loss/5 p-3 text-krypt-loss">
                <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" />
                <div className="text-xs leading-relaxed">
                  <strong>Disclaimer.</strong> Krypt Trader is provided as-is, free.
                  Auto-trading involves risk; all P&amp;L is your own. We make no
                  guarantee of profitability. You are solely responsible for
                  compliance with Kalshi&apos;s terms of service and applicable
                  law in your jurisdiction. Always use the demo environment
                  before going live.
                </div>
              </div>
              <label className="flex items-start gap-3 rounded-lg border border-krypt-border bg-krypt-surface2 p-3">
                <input
                  type="checkbox"
                  checked={accepted}
                  onChange={(e) => setAccepted(e.target.checked)}
                  className="mt-0.5 h-4 w-4 accent-krypt-purple"
                />
                <span className="text-xs text-white/90">
                  I&apos;ve read the disclaimer and accept the risks of auto-trading.
                </span>
              </label>
              <button
                type="button"
                onClick={() => void openKalshiReferral()}
                className="flex w-full items-center gap-3 rounded-lg border border-krypt-purple/40 bg-gradient-to-r from-krypt-indigo/10 via-krypt-purple/10 to-krypt-pink/10 p-3 text-left transition-colors hover:border-krypt-purple"
              >
                <Gift className="h-5 w-5 shrink-0 text-krypt-purple" />
                <div className="flex-1 text-xs">
                  <div className="text-white">No Kalshi account yet?</div>
                  <div className="text-krypt-muted">
                    Sign up with our referral — Kalshi gives you{' '}
                    <span className="text-white">$25 free</span> after your first deposit.
                  </div>
                </div>
                <ExternalLink className="h-4 w-4 text-krypt-muted" />
              </button>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-krypt-border bg-krypt-surface2/50 px-8 py-4">
          <div className="flex gap-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className={
                  i === step
                    ? 'h-1.5 w-6 rounded-full bg-krypt-purple'
                    : 'h-1.5 w-1.5 rounded-full bg-krypt-border'
                }
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            {step > 0 && (
              <button onClick={() => setStep((s) => s - 1)} className="krypt-btn-ghost">
                Back
              </button>
            )}
            {step < 2 ? (
              <button
                onClick={() => setStep((s) => s + 1)}
                className="krypt-btn-primary"
              >
                Continue <ArrowRight className="h-4 w-4" />
              </button>
            ) : (
              <button onClick={finish} className="krypt-btn-primary">
                Get started <ArrowRight className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-krypt-border bg-krypt-surface2 p-3">
      <div className="text-xs font-semibold text-white">{title}</div>
      <div className="mt-0.5 text-[11px] text-krypt-muted">{body}</div>
    </div>
  );
}
