import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Compass } from 'lucide-react';
import type { PageId } from '../../state/lastPage';
import { OnboardingModal } from '../../pages/Onboarding';
import { GlassPanel } from '../glass/GlassPanel';
import { GlassButton } from '../glass/GlassButton';
import { GLASS_TINTS } from '../glass/glassPresets';
import { Tour } from './Tour';
import { ErrorBoundary } from '../ErrorBoundary';
import { GuideContext, markTourOffered, wasTourOffered, type GuideApi } from './useTour';

export function GuideHost({
  needsOnboarding, needsUpdateOnboarding = false, setPage, children,
}: {
  needsOnboarding: boolean;
  needsUpdateOnboarding?: boolean;
  setPage: (p: PageId) => void;
  children: ReactNode;
}) {
  const [onboarding, setOnboarding] = useState<'first' | 'update' | 'replay' | null>(null);
  const [tourOpen, setTourOpen] = useState(false);
  const [offer, setOffer] = useState(false);
  const autoOpened = useRef(false);

  useEffect(() => {
    if (needsOnboarding) { autoOpened.current = true; setOnboarding('first'); return; }
    if (needsUpdateOnboarding && !autoOpened.current) {
      autoOpened.current = true;
      setOnboarding((m) => m ?? 'update');
    }
  }, [needsOnboarding, needsUpdateOnboarding]);

  const markSeen = (): void => {
    void window.krypt.state.markOnboardingSeen?.().catch(() => {});
  };
  const closeOnboarding = (): void => { markSeen(); setOnboarding(null); };

  const startTour = useCallback((): void => {
    setOffer(false);
    setTourOpen(true);
  }, []);
  const replayOnboarding = useCallback((): void => {
    setTourOpen(false);
    setOffer(false);
    setOnboarding((m) => m ?? 'replay');
  }, []);
  const api = useMemo<GuideApi>(() => ({ startTour, replayOnboarding }), [startTour, replayOnboarding]);

  const onboardingDone = (page: PageId): void => {
    const mode = onboarding;
    closeOnboarding();
    if (mode === 'replay') return;
    if (mode === 'first') setPage(page);
    if (!wasTourOffered()) {
      markTourOffered();
      setOffer(true);
    }
  };

  return (
    <GuideContext.Provider value={api}>
      {children}
      {onboarding && (
        <ErrorBoundary
          fallback={() => (
            <SetupCrash
              firstRun={onboarding === 'first'}
              onSkip={closeOnboarding}
            />
          )}
        >
          <OnboardingModal
            replay={onboarding !== 'first'}
            updated={onboarding === 'update'}
            onDone={onboardingDone}
            onClose={closeOnboarding}
          />
        </ErrorBoundary>
      )}
      {offer && !tourOpen && !onboarding && (
        <TourOffer onStart={startTour} onDismiss={() => setOffer(false)} />
      )}
      <ErrorBoundary
        key={tourOpen ? 'tour-open' : 'tour-closed'}
        fallback={() => null}
        onError={() => setTourOpen(false)}
      >
        <Tour open={tourOpen} onClose={() => setTourOpen(false)} onNavigate={setPage} />
      </ErrorBoundary>
    </GuideContext.Provider>
  );
}

export function SetupCrash({ firstRun, onSkip }: { firstRun: boolean; onSkip: () => void }) {
  const [busy, setBusy] = useState(false);
  const skip = async (): Promise<void> => {
    setBusy(true);
    try {
      if (firstRun) await window.krypt.state.acceptDisclaimer();
    } catch {}
    onSkip();
  };
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" data-testid="setup-crash">
      <div role="alertdialog" aria-labelledby="setup-crash-title"
        className="w-[460px] max-w-full rounded-2xl border border-krypt-border bg-krypt-panel p-5 text-sm">
        <h2 id="setup-crash-title" className="text-base font-semibold text-white">Setup hit a problem</h2>
        <p className="mt-2 text-xs leading-relaxed text-krypt-muted">
          The setup screens couldn&apos;t open. You can skip them: the app starts on Paper (real
          prices, imaginary money) with all trading off, and you can replay setup later from
          Settings → Getting started.
        </p>
        {firstRun && (
          <p className="mt-2 text-xs leading-relaxed text-krypt-warn">
            By continuing you accept the disclaimer: Krypt Trader is provided as-is; trading involves
            risk, all profit and loss is your own, and you are responsible for following Kalshi&apos;s
            terms and your local law.
          </p>
        )}
        <div className="mt-4 flex justify-end">
          <button type="button" className="krypt-btn-primary" disabled={busy} onClick={() => void skip()}
            data-testid="setup-crash-skip">
            {firstRun ? 'Accept and skip setup' : 'Skip setup'}
          </button>
        </div>
      </div>
    </div>
  );
}

function TourOffer({ onStart, onDismiss }: { onStart: () => void; onDismiss: () => void }) {
  return (
    <div
      role="dialog"
      aria-labelledby="tour-offer-title"
      aria-describedby="tour-offer-body"
      data-testid="tour-offer"
      className="fixed bottom-5 right-5 z-[60] w-[300px] max-w-[calc(100vw-24px)]"
    >
      <GlassPanel
        preset="card"
        tint={GLASS_TINTS.modal}
        className="glass-pop rounded-2xl border border-white/[0.08] p-4 motion-reduce:[animation:none]"
        style={{ boxShadow: '0 0 60px -18px rgba(168,85,247,0.6), var(--glass-shadow)' }}
      >
        <div className="flex items-start gap-3">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-krypt-glow shadow-krypt-soft">
            <Compass className="h-4 w-4 text-white" />
          </div>
          <div>
            <h2 id="tour-offer-title" className="text-sm font-semibold text-white">
              Take a 1-minute tour of the app?
            </h2>
            <p id="tour-offer-body" className="mt-0.5 text-xs leading-relaxed text-krypt-muted">
              It points at each tab and says what it is for. You can start it later from the ⓘ
              next to the auth pill at the top.
            </p>
          </div>
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <button type="button" onClick={onDismiss} className="krypt-btn-ghost px-2.5 text-xs">
            Not now
          </button>
          <GlassButton variant="primary" onClick={onStart} className="px-3 py-1.5 text-xs" autoFocus>
            Start
          </GlassButton>
        </div>
      </GlassPanel>
    </div>
  );
}
