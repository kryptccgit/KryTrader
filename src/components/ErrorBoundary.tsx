import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback: (error: Error, reset: () => void) => ReactNode;
  onError?: (error: Error) => void;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    try { console.error('[ErrorBoundary]', error, info.componentStack); } catch {}
    try { this.props.onError?.(error); } catch {}
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    return error ? this.props.fallback(error, this.reset) : this.props.children;
  }
}

export function PageCrash({
  error, homeLabel, onHome, onRetry,
}: {
  error: Error;
  homeLabel: string;
  onHome: () => void;
  onRetry: () => void;
}) {
  return (
    <div role="alert" className="grid h-full place-items-center p-8">
      <div className="max-w-lg rounded-2xl border border-krypt-loss/40 bg-krypt-loss/[0.06] p-6 text-center">
        <AlertTriangle className="mx-auto h-8 w-8 text-krypt-loss" />
        <div className="mt-3 text-base font-semibold text-white">This page crashed</div>
        <p className="mt-1 text-sm text-krypt-muted">
          The rest of the app is still running: the top bar&apos;s Pause and every
          engine&apos;s own switch work as normal.
        </p>
        <pre className="mt-3 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/40 p-2 text-left font-mono text-[11px] text-krypt-loss">
          {error.message || String(error)}
        </pre>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <button onClick={onHome} className="krypt-btn-primary">Go to {homeLabel}</button>
          <button onClick={onRetry} className="krypt-btn-default">Try again</button>
          <button onClick={() => window.location.reload()} className="krypt-btn-default inline-flex items-center gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" /> Reload
          </button>
        </div>
      </div>
    </div>
  );
}

export function SceneCrash({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="grid h-[calc(100vh-250px)] min-h-[460px] place-items-center rounded-2xl border border-krypt-border bg-[#05030c] p-6 text-center"
    >
      <div className="max-w-md">
        <div className="text-sm font-semibold text-white">3D view unavailable</div>
        <p className="mt-1 text-xs text-krypt-muted">
          This scene couldn&apos;t start (often WebGL is off or the GPU driver refused it).
          Everything below still works.
        </p>
        <p className="mt-2 break-words font-mono text-[11px] text-krypt-dim">{error.message || String(error)}</p>
        <button onClick={onRetry} className="krypt-btn-default mt-3">Try again</button>
      </div>
    </div>
  );
}
