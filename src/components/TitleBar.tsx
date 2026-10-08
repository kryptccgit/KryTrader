import { useEffect, useState } from 'react';
import { Info, Minus, Power, Square, Copy as Restore, X } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { cls } from '../utils/format';
import { GlassPanel } from './glass/GlassPanel';
import { GLASS_TINTS } from './glass/glassPresets';
import { useGuide } from './tour/useTour';

export function TitleBar() {
  const { backend, appVersion, config } = useApp();
  const { startTour } = useGuide();
  const [maxed, setMaxed] = useState(false);

  useEffect(() => {
    let mounted = true;
    void window.krypt.window.isMaximized().then((m) => {
      if (mounted) setMaxed(m);
    });
    const off = window.krypt.window.onMaximizeChange((m) => setMaxed(m));
    return () => {
      mounted = false;
      off();
    };
  }, []);

  const dot =
    backend.status === 'running' ? 'bg-krypt-win' :
    backend.status === 'starting' ? 'bg-krypt-warn' :
    backend.status === 'crashed' || backend.status === 'restarting' ? 'bg-krypt-loss' :
    'bg-krypt-dim';

  return (
    <GlassPanel
      preset="chrome"
      display="flex"
      tint={GLASS_TINTS.chrome}
      className="titlebar-drag relative z-30 h-9 shrink-0 select-none items-center justify-between border-b border-white/[0.06] px-3"
    >
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="h-5 w-5 rounded-md bg-krypt-glow shadow-[inset_0_1px_0_rgba(255,255,255,0.45),0_0_14px_-2px_rgba(168,85,247,0.8)]" />
          <span className="font-pixel text-[10px] uppercase tracking-[0.2em] text-white/90">
            Krypt Trader
          </span>
          {appVersion && (
            <span className="rounded-full border border-krypt-purple/30 bg-krypt-purple/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-krypt-purple shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
              v{appVersion}
            </span>
          )}
        </div>
        <div className="hidden items-center gap-2 text-[11px] text-krypt-muted lg:flex">
          <span className={cls('h-2 w-2 rounded-full', dot, backend.status === 'running' && 'shadow-[0_0_8px_currentColor]')} />
          <span className="capitalize">{backend.status}</span>
          {config?.accountMode !== 'live' ? (
            <span className="krypt-pill border-krypt-purple/40 bg-krypt-purple/10 text-krypt-purple">
              paper · no key needed
            </span>
          ) : backend.authOk ? (
            <span className="krypt-pill border-krypt-win/40 bg-krypt-win/10 text-krypt-win">
              auth ok
            </span>
          ) : (
            <span className="krypt-pill border-krypt-warn/40 bg-krypt-warn/10 text-krypt-warn">
              auth needed
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={startTour}
          data-tour="tour-info"
          aria-label="Show the app tour"
          title="Show the app tour"
          className="titlebar-no-drag -ml-1 grid h-6 w-6 place-items-center rounded-full text-krypt-muted transition-colors hover:bg-white/[0.08] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-krypt-purple/70"
        >
          <Info className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="titlebar-no-drag flex items-center">
        <button
          onClick={() => void window.krypt.app.quit?.()}
          aria-label="Quit Krypt Trader"
          title="Quit Krypt Trader — stops the app and everything it is running"
          data-testid="titlebar-quit"
          className="mr-1 flex h-9 items-center gap-1 px-2 text-[11px] text-krypt-muted transition-colors hover:bg-white/[0.07] hover:text-white"
        >
          <Power className="h-3.5 w-3.5" /> Quit
        </button>
        <button
          onClick={() => window.krypt.window.minimize()}
          aria-label="Minimize"
          className="grid h-9 w-11 place-items-center text-krypt-muted transition-colors hover:bg-white/[0.07] hover:text-white"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => window.krypt.window.maximize()}
          aria-label={maxed ? 'Restore' : 'Maximize'}
          className="grid h-9 w-11 place-items-center text-krypt-muted transition-colors hover:bg-white/[0.07] hover:text-white"
        >
          {maxed ? <Restore className="h-3 w-3" /> : <Square className="h-3 w-3" />}
        </button>
        <button
          onClick={() => window.krypt.window.close()}
          aria-label="Close to tray"
          title="Close to tray — Krypt Trader keeps running in the background. Use Quit to stop it."
          className="grid h-9 w-11 place-items-center text-krypt-muted hover:bg-krypt-loss hover:text-white"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </GlassPanel>
  );
}
