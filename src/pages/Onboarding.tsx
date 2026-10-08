import { useEffect, useState } from 'react';
import { ArrowRight, ExternalLink, FlaskConical, Gift, KeyRound, ShieldAlert, X } from 'lucide-react';
import type { PageId } from '../App';
import { ConnectAgent } from '../components/ConnectAgent';
import { KalshiKeyWizard } from '../components/KalshiKeyWizard';
import { AutopilotQuickstart } from '../components/AutopilotQuickstart';
import { GuideVideoCard } from '../components/GuideVideo';
import { Badge, ChoiceCard } from '../components/SetupSteps';
import { useToast } from '../state/ToastProvider';
import { useApp } from '../state/AppStateProvider';
import { openKalshiReferral } from '../utils/links';
import { GlassPanel } from '../components/glass/GlassPanel';
import { GlassButton } from '../components/glass/GlassButton';
import { GLASS_TINTS } from '../components/glass/glassPresets';

type Step = 'welcome' | 'disclaimer' | 'agent' | 'kalshi' | 'autopilot';

export function OnboardingModal({ onDone, replay = false, updated = false, onClose }: {
  onDone: (page: PageId) => void;
  replay?: boolean;
  updated?: boolean;
  onClose?: () => void;
}) {
  const [step, setStep] = useState(0);
  const [accepted, setAccepted] = useState(false);
  const [wantAutopilot, setWantAutopilot] = useState(false);
  const [keyFlow, setKeyFlow] = useState(false);
  const toast = useToast();
  const { state, config } = useApp();
  const alreadyAccepted = replay && !!state?.acceptedDisclaimer;
  const agentsLive = config?.mcpTradeMode === 'live';
  const steps: Step[] = ['welcome', 'disclaimer', 'agent', 'kalshi', ...(wantAutopilot ? ['autopilot' as const] : [])];
  const at = steps[step];
  const last = steps.length - 1;
  const next = (): void => setStep((s) => Math.min(s + 1, last));
  const back = (): void => setStep((s) => Math.max(0, s - 1));

  const acceptAndContinue = async (): Promise<void> => {
    if (alreadyAccepted) { next(); return; }
    if (!accepted) {
      toast.warn('Please tick the disclaimer to continue');
      return;
    }
    await window.krypt.state.acceptDisclaimer();
    next();
  };

  const finish = (): void => {
    if (!replay) toast.success('Welcome to Krypt Trader');
    onDone('aiAgents');
  };

  const advanceOrFinish = (): void => { if (step >= last) finish(); else next(); };
  const embedded = at === 'kalshi' || at === 'autopilot';

  const startOnPaper = async (): Promise<void> => {
    if (config?.accountMode === 'live') {
      await window.krypt.config.update({ accountMode: 'paper' });
      toast.success('Back on Paper. Nothing can send a real order now.');
    }
    advanceOrFinish();
  };

  useEffect(() => {
    if (!replay || !onClose) return undefined;
    const onKey = (e: KeyboardEvent): void => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [replay, onClose]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/55">
      <GlassPanel
        preset="modal"
        tint={GLASS_TINTS.modal}
        display="flex"
        className="glass-pop relative max-h-[94vh] w-[680px] max-w-[94vw] flex-col overflow-hidden rounded-3xl"
        style={{ boxShadow: '0 0 80px -20px rgba(168,85,247,0.55), var(--glass-shadow)' }}
        role="dialog"
        aria-modal="true"
        aria-label={replay ? 'Onboarding (replay)' : 'Onboarding'}
      >
        {replay && onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close onboarding"
            title="Close (nothing changes)"
            className="absolute right-3 top-3 z-10 grid h-7 w-7 place-items-center rounded-lg text-krypt-muted transition-colors hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        )}
        <div className="shrink-0 bg-gradient-to-r from-krypt-indigo/70 via-krypt-purple/70 to-krypt-pink/70 pb-px">
          {at === 'welcome' ? (
            <div className="bg-[linear-gradient(180deg,rgba(40,30,70,0.85),rgba(16,14,28,0.9))] px-8 py-6 text-center">
              <div className="mx-auto mb-3 grid h-16 w-16 place-items-center rounded-2xl bg-krypt-glow shadow-krypt-strong">
                <span className="font-pixel text-xs">K</span>
              </div>
              <h2 className="font-pixel text-base tracking-wider">KRYPT TRADER</h2>
              <p className="mt-1 text-xs text-krypt-muted">
                Your AI agent on Kalshi: inside rails, scored against the market.
              </p>
              {replay && (
                <p className="mx-auto mt-2 w-fit rounded-full border border-krypt-purple/40 bg-krypt-purple/10 px-2.5 py-0.5 text-[10px] uppercase tracking-wider text-krypt-purple">
                  {updated ? 'New in this version' : 'Replay'} · nothing changes unless you act in a step
                </p>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-3 bg-[linear-gradient(180deg,rgba(40,30,70,0.85),rgba(16,14,28,0.9))] px-8 py-3">
              <div className="grid h-8 w-8 place-items-center rounded-lg bg-krypt-glow shadow-krypt-soft">
                <span className="font-pixel text-[9px]">K</span>
              </div>
              <h2 className="font-pixel text-xs tracking-wider">KRYPT TRADER</h2>
              {replay && (
                <span className="rounded-full border border-krypt-purple/40 bg-krypt-purple/10 px-2 py-0.5 text-[9px] uppercase tracking-wider text-krypt-purple">
                  {updated ? 'New' : 'Replay'}
                </span>
              )}
              <span className={replay ? 'ml-auto mr-8 text-[11px] text-krypt-muted' : 'ml-auto text-[11px] text-krypt-muted'}>
                {at === 'agent' ? 'Your AI agent' : at === 'disclaimer' ? 'Before you trade'
                  : at === 'kalshi' ? 'Paper or Live' : 'Autopilot'}
              </span>
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
          {at === 'welcome' && (
            <div className="space-y-4 text-sm text-white/90">
              <p>
                Connect the AI agent you already use —{' '}
                <span className="text-white">Claude Code, Cursor, Claude Desktop or Codex</span> —
                and it can read every Kalshi market, commit to a forecast, and trade{' '}
                <span className="text-white">on paper</span> against the real order book. Every
                forecast is scored against the market price once it settles, so you find out
                whether it beats the market before a dollar is at risk.
              </p>
              <GuideVideoCard />
              <p className="text-krypt-muted">
                The <span className="text-white">Terminal</span> is the manual side, and the
                original <span className="text-white">automation</span> is still here. Everything
                runs on your machine; your keys never leave it.
              </p>
              <ul className="grid grid-cols-2 gap-3 text-xs">
                <Feature title="AI agents (MCP)" body="Your agent, on a local server only it can reach." />
                <Feature title="Forecast first" body="No buy without a forecast that beats the price after fees." />
                <Feature title="Paper by default" body="Real books, imaginary money. Live is its own switch." />
                <Feature title="Forecast scoreboard" body="Brier vs the market, per agent. Does it beat the price?" />
                <Feature title="Terminal" body="Every market, charted and priced. Trade by hand." />
                <Feature title="Resolution risk" body="Who settles it, on what source, how vague the wording." />
                <Feature title="Whale tracker" body="$2.5k+ taker orders, scored." />
                <Feature title="Momentum scanner" body="Trade-cluster contrarian fades." />
                <Feature title="Auto-trader" body="Limit-cross orders, sized 2-6%." />
                <Feature title="Strategy scripts" body="Write your own — sandboxed, with money rails." />
              </ul>
            </div>
          )}

          {at === 'agent' && (
            <div className="space-y-3 text-sm text-white/90">
              <h3 className="text-base font-semibold">Connect your AI agent</h3>
              <p className="text-xs leading-relaxed text-white/80">
                Don&apos;t use Claude Code, Cursor or Codex? Pick{' '}
                <span className="text-white">In-app Autopilot</span>: nothing to install — the app runs
                the agent itself with an AI you choose (including free ones on your own computer).
              </p>
              {agentsLive ? (
                <p className="text-xs leading-relaxed text-krypt-muted">
                  Pick the one you use. Copying its config makes sure the local agent server is on.
                  Your agent trading is set to <span className="text-krypt-loss">LIVE</span>, and
                  this step leaves it that way: switch back to paper on the AI Agents page.
                </p>
              ) : (
                <p className="text-xs leading-relaxed text-krypt-muted">
                  Pick the one you use. Copying its config switches on the local agent server and
                  sets agent trading to <span className="text-white">paper</span>: real order books,
                  imaginary money. Nothing here can turn on live trading; that is its own deliberate
                  switch on the AI Agents page.
                </p>
              )}
              <ConnectAgent
                paperDefault
                autopilotSetup="callback"
                onAutopilot={() => { setWantAutopilot(true); next(); }}
              />
              <p className="text-[11px] text-krypt-dim">
                Then ask it something like: &ldquo;Use krypt-trader. Check get_status, look through
                closing markets, read the rules, and record honest forecasts.&rdquo; Not using an AI
                agent? Skip this: nothing is switched on unless you copy a config.
              </p>
            </div>
          )}

          {at === 'disclaimer' && (
            <div className="space-y-4 text-sm">
              <div className="flex items-start gap-3 rounded-lg border border-krypt-loss/30 bg-krypt-loss/5 p-3 text-krypt-loss">
                <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" />
                <div className="text-xs leading-relaxed">
                  <strong>Disclaimer.</strong> Krypt Trader is provided as-is, free.
                  Auto-trading involves risk; all P&amp;L is your own. We make no
                  guarantee of profitability. You are solely responsible for
                  compliance with Kalshi&apos;s terms of service and applicable
                  law in your jurisdiction. Always trade in Paper mode
                  before going live.
                </div>
              </div>
              <label className="flex items-start gap-3 rounded-lg border border-krypt-border bg-krypt-surface2 p-3">
                <input
                  type="checkbox"
                  checked={alreadyAccepted || accepted}
                  disabled={alreadyAccepted}
                  onChange={(e) => setAccepted(e.target.checked)}
                  className="mt-0.5 h-4 w-4 accent-krypt-purple"
                />
                <span className="text-xs text-white/90">
                  I&apos;ve read the disclaimer and accept the risks of auto-trading.
                  {alreadyAccepted && (
                    <span className="mt-0.5 block text-krypt-muted" data-testid="disclaimer-accepted">
                      You accepted this when you set up the app. It stays accepted; it is here to re-read.
                    </span>
                  )}
                </span>
              </label>
              <div className="rounded-lg border border-krypt-warn/40 bg-krypt-warn/5 p-3 text-xs text-krypt-warn">
                You start in <strong>PAPER</strong> mode — Kalshi&apos;s real prices, imaginary money,
                no Kalshi account needed — with every kind of trading off. Real money needs a Kalshi
                key AND the Go live checklist. Fund at least{' '}
                <strong>$25</strong> before going live: smaller orders fall under Kalshi&apos;s{' '}
                <strong>$1 minimum</strong>.
              </div>
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

          {at === 'kalshi' && !keyFlow && (
            <div className="space-y-3 text-sm text-white/90" data-testid="onboarding-start">
              <h3 className="text-base font-semibold">How do you want to start?</h3>
              <ChoiceCard
                testId="start-paper-card" selected onClick={() => undefined}
                title={<><FlaskConical className="mr-1 inline h-4 w-4" />Start on paper (no Kalshi account needed)</>}
                badge={<Badge>Recommended</Badge>}
              >
                Kalshi&apos;s real markets and prices with imaginary money — $
                {(config?.paperBankrollUsd ?? 1000).toLocaleString()} to start. The bot, 15-minute
                crypto, scripts, the Terminal and your AI agents all work, and none of them can spend
                real money.
              </ChoiceCard>
              <ChoiceCard
                testId="add-key-card" selected={false} onClick={() => setKeyFlow(true)}
                title={<><KeyRound className="mr-1 inline h-4 w-4" />I have a Kalshi account — add my key</>}
              >
                Saves your key and checks it. The app still starts on Paper; going Live is its own
                checklist in Settings → Account whenever you are ready.
              </ChoiceCard>
              <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                <button onClick={back} className="krypt-btn-ghost">Back</button>
                <div className="flex gap-2">
                  <button onClick={() => setKeyFlow(true)} className="krypt-btn-default" data-testid="onboarding-add-key">
                    Add a Kalshi key
                  </button>
                  <GlassButton variant="primary" onClick={() => void startOnPaper()} data-testid="onboarding-start-paper">
                    Start on paper <ArrowRight className="h-4 w-4" />
                  </GlassButton>
                </div>
              </div>
            </div>
          )}

          {at === 'kalshi' && keyFlow && (
            <div className="text-sm text-white/90">
              <p className="mb-4 text-xs leading-relaxed text-krypt-muted">
                Add the key you will trade Live with. Saving it changes nothing about what trades:
                the app stays in Paper until you choose Go live. Not ready? Skip it — Paper needs no
                key at all.
              </p>
              <KalshiKeyWizard
                onDone={advanceOrFinish}
                onSkip={advanceOrFinish}
                onBackOut={() => setKeyFlow(false)}
              />
            </div>
          )}

          {at === 'autopilot' && (
            <AutopilotQuickstart
              onDone={finish}
              onSkip={finish}
              onBackOut={back}
            />
          )}
        </div>

        <div className="flex shrink-0 items-center justify-between border-t border-krypt-border bg-krypt-surface2/50 px-8 py-4">
          <div className="flex gap-1" aria-label={`Onboarding step ${step + 1} of ${steps.length}`}>
            {steps.map((_, i) => (
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
          {embedded ? (
            <span className="text-[11px] text-krypt-dim">
              {at === 'kalshi' ? 'Paper or Live' : 'Autopilot setup'}
            </span>
          ) : (
            <div className="flex items-center gap-2">
              {step > 0 && (
                <button onClick={back} className="krypt-btn-ghost">
                  Back
                </button>
              )}
              {at === 'agent' && (
                <button onClick={next} className="krypt-btn-ghost">
                  Skip
                </button>
              )}
              <GlassButton
                variant="primary"
                data-testid="onboarding-continue"
                onClick={() => { if (at === 'disclaimer') void acceptAndContinue(); else next(); }}
              >
                Continue <ArrowRight className="h-4 w-4" />
              </GlassButton>
            </div>
          )}
        </div>
      </GlassPanel>
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
