import { useEffect, useState } from 'react';
import { Minus, Square, Copy as Restore, X } from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { cls } from '../utils/format';

export function TitleBar() {
  const { backend, appVersion } = useApp();
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
    <div className="titlebar-drag relative z-30 flex h-9 select-none items-center justify-between border-b border-krypt-border bg-krypt-void/95 px-3 backdrop-blur">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="h-5 w-5 rounded-md bg-krypt-glow" />
          <span className="font-pixel text-[10px] uppercase tracking-[0.2em] text-white/90">
            Krypt Trader
          </span>
          <span className="rounded bg-krypt-purple/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-krypt-purple">
            v{appVersion || '3.0.0'}
          </span>
        </div>
        <div className="hidden items-center gap-2 text-[11px] text-krypt-muted lg:flex">
          <span className={cls('h-2 w-2 rounded-full', dot, backend.status === 'running' && 'shadow-[0_0_8px_currentColor]')} />
          <span className="capitalize">{backend.status}</span>
          {backend.authOk ? (
            <span className="krypt-pill border-krypt-win/40 bg-krypt-win/10 text-krypt-win">
              auth ok
            </span>
          ) : (
            <span className="krypt-pill border-krypt-warn/40 bg-krypt-warn/10 text-krypt-warn">
              auth needed
            </span>
          )}
        </div>
      </div>

      <div className="titlebar-no-drag flex items-center">
        <button
          onClick={() => window.krypt.window.minimize()}
          aria-label="Minimize"
          className="grid h-9 w-11 place-items-center text-krypt-muted hover:bg-white/5 hover:text-white"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => window.krypt.window.maximize()}
          aria-label={maxed ? 'Restore' : 'Maximize'}
          className="grid h-9 w-11 place-items-center text-krypt-muted hover:bg-white/5 hover:text-white"
        >
          {maxed ? <Restore className="h-3 w-3" /> : <Square className="h-3 w-3" />}
        </button>
        <button
          onClick={() => window.krypt.window.close()}
          aria-label="Close"
          className="grid h-9 w-11 place-items-center text-krypt-muted hover:bg-krypt-loss hover:text-white"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
