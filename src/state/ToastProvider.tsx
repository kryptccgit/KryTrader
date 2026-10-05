import {
  createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState,
} from 'react';
import { CheckCircle, XCircle, Info, AlertTriangle, X } from 'lucide-react';
import { cls } from '../utils/format';

export type ToastKind = 'success' | 'error' | 'info' | 'warn';

interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  ttl: number;
}

interface ToastApi {
  push: (message: string, kind?: ToastKind, ttl?: number) => void;
  success: (m: string) => void;
  error: (m: string) => void;
  info: (m: string) => void;
  warn: (m: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be inside ToastProvider');
  return ctx;
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback(
    (message: string, kind: ToastKind = 'info', ttl = 4500) => {
      const id = nextId++;
      setToasts((cur) => [...cur, { id, kind, message, ttl }]);
      setTimeout(() => {
        setToasts((cur) => cur.filter((t) => t.id !== id));
      }, ttl);
    },
    [],
  );

  const api = useMemo<ToastApi>(
    () => ({
      push,
      success: (m) => push(m, 'success'),
      error: (m) => push(m, 'error'),
      info: (m) => push(m, 'info'),
      warn: (m) => push(m, 'warn'),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed right-5 top-14 z-[60] flex w-[360px] max-w-full flex-col gap-2">
        {toasts.map((t) => (
          <ToastItem
            key={t.id}
            toast={t}
            onClose={() => setToasts((cur) => cur.filter((x) => x.id !== t.id))}
          />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onClose }: { toast: Toast; onClose: () => void }) {
  const [exit, setExit] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setExit(true), toast.ttl - 250);
    return () => clearTimeout(t);
  }, [toast.ttl]);

  const Icon =
    toast.kind === 'success' ? CheckCircle :
    toast.kind === 'error' ? XCircle :
    toast.kind === 'warn' ? AlertTriangle :
    Info;

  return (
    <div
      className={cls(
        'pointer-events-auto flex items-start gap-3 rounded-xl border bg-krypt-surface/90 p-3 backdrop-blur-md shadow-krypt-soft animate-fade-in',
        toast.kind === 'success' && 'border-krypt-win/30',
        toast.kind === 'error' && 'border-krypt-loss/40',
        toast.kind === 'warn' && 'border-krypt-warn/40',
        toast.kind === 'info' && 'border-krypt-border',
        exit && 'opacity-0 transition-opacity duration-200',
      )}
    >
      <Icon
        className={cls(
          'mt-0.5 h-5 w-5 shrink-0',
          toast.kind === 'success' && 'text-krypt-win',
          toast.kind === 'error' && 'text-krypt-loss',
          toast.kind === 'warn' && 'text-krypt-warn',
          toast.kind === 'info' && 'text-krypt-purple',
        )}
      />
      <div className="flex-1 text-sm">{toast.message}</div>
      <button
        onClick={onClose}
        className="text-krypt-muted hover:text-white"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
