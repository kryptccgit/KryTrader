import { ReactNode, useEffect, useRef, useState } from 'react';
import { Share2 } from 'lucide-react';
import { cls } from '../utils/format';
import { shareToX, X_PROFILE } from '../utils/share';

export function NameDialog({
  open, title, label, initialValue = '', placeholder, confirmLabel = 'Save',
  onSubmit, onClose,
}: {
  open: boolean;
  title: string;
  label?: string;
  initialValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  onSubmit: (value: string) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initialValue);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setValue(initialValue);
    const t = setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 30);
    return () => clearTimeout(t);
  }, [open, initialValue]);

  if (!open) return null;

  const submit = (): void => {
    const v = value.trim();
    if (!v) return;
    onSubmit(v);
  };

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-sm rounded-xl border border-krypt-border bg-krypt-surface p-5 shadow-krypt-soft"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        {label && <p className="mt-1 text-xs text-krypt-muted">{label}</p>}
        <input
          ref={inputRef}
          value={value}
          placeholder={placeholder}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); submit(); }
            else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
          }}
          className="krypt-input mt-3 w-full"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="krypt-btn-default">Cancel</button>
          <button onClick={submit} disabled={!value.trim()} className="krypt-btn-primary">
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open, title, body, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger,
  onConfirm, onClose,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-krypt-border bg-krypt-surface p-5 shadow-krypt-soft"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        <div className="mt-2 text-xs leading-relaxed text-krypt-muted">{body}</div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="krypt-btn-default">{cancelLabel}</button>
          <button onClick={onConfirm} className={danger ? 'krypt-btn-danger' : 'krypt-btn-primary'}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Page({
  title, subtitle, actions, children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-end justify-between gap-4 px-6 py-5">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-white">{title}</h2>
          {subtitle && (
            <p className="mt-1 text-sm text-krypt-muted">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="flex-1 overflow-y-auto px-6 pb-8">{children}</div>
    </div>
  );
}

export function Card({
  className, children, header, footer,
}: {
  className?: string;
  children: ReactNode;
  header?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className={cls('krypt-card', className)}>
      {header && (
        <div className="-mx-5 -mt-5 mb-4 border-b border-krypt-border bg-krypt-surface2/60 px-5 py-3">
          {header}
        </div>
      )}
      {children}
      {footer && (
        <div className="-mx-5 -mb-5 mt-4 border-t border-krypt-border bg-krypt-surface2/60 px-5 py-3">
          {footer}
        </div>
      )}
    </div>
  );
}

export function StatCard({
  label, value, hint, accent, className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  accent?: 'good' | 'bad' | 'warn' | 'neutral';
  className?: string;
}) {
  const ring =
    accent === 'good' ? 'ring-1 ring-krypt-win/30' :
    accent === 'bad' ? 'ring-1 ring-krypt-loss/30' :
    accent === 'warn' ? 'ring-1 ring-krypt-warn/30' :
    '';
  return (
    <div className={cls('krypt-card', ring, className)}>
      <div className="text-[11px] uppercase tracking-wider text-krypt-muted">{label}</div>
      <div className="mt-1 font-mono text-2xl font-medium text-white">{value}</div>
      {hint && <div className="mt-1 text-xs text-krypt-dim">{hint}</div>}
    </div>
  );
}

export function ShareableStat({
  label, value, hint, accent, className, shareText,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  accent?: 'good' | 'bad' | 'warn' | 'neutral';
  className?: string;
  shareText: string;
}) {
  return (
    <div className={cls('relative', className)}>
      <StatCard label={label} value={value} hint={hint} accent={accent} />
      <ShareButton text={shareText} className="absolute right-3 top-3" />
    </div>
  );
}

export function ShareButton({
  text, className, size = 'sm',
}: {
  text: string;
  className?: string;
  size?: 'sm' | 'xs';
}) {
  const sz = size === 'xs' ? 'h-6 w-6' : 'h-7 w-7';
  const ic = size === 'xs' ? 'h-3 w-3' : 'h-3.5 w-3.5';
  return (
    <button
      onClick={() => void shareToX(text)}
      title={`Share to ${X_PROFILE}`}
      className={cls(
        'grid place-items-center rounded-md border border-krypt-border bg-krypt-surface2 text-krypt-muted transition-colors hover:border-krypt-purple/40 hover:bg-krypt-purple/10 hover:text-white',
        sz,
        className,
      )}
    >
      <Share2 className={ic} />
    </button>
  );
}

export function Empty({
  title, description, action,
}: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-xl border border-dashed border-krypt-border p-10 text-center">
      <div>
        <div className="text-base font-medium text-white">{title}</div>
        {description && <p className="mt-1 max-w-md text-sm text-krypt-muted">{description}</p>}
        {action && <div className="mt-4">{action}</div>}
      </div>
    </div>
  );
}

export function Switch({
  checked, onChange, label, description, disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cls(
        'flex w-full items-start justify-between gap-4 rounded-lg border border-krypt-border bg-krypt-surface2 p-3 text-left transition-colors hover:border-krypt-borderHi',
        disabled && 'opacity-50',
      )}
    >
      <div className="flex-1">
        {label && <div className="text-sm text-white">{label}</div>}
        {description && (
          <div className="mt-0.5 text-xs text-krypt-muted">{description}</div>
        )}
      </div>
      <div
        className={cls(
          'relative h-5 w-9 shrink-0 rounded-full transition-colors',
          checked ? 'bg-krypt-glow' : 'bg-krypt-border',
        )}
      >
        <div
          className={cls(
            'absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all',
            checked ? 'left-4' : 'left-0.5',
          )}
        />
      </div>
    </button>
  );
}

export function useOptimisticValue<T>(
  value: T,
  onCommit: (next: T) => void | Promise<void>,
): [T, (next: T) => void] {
  const [local, setLocal] = useState<T>(value);
  const key = JSON.stringify(value ?? null);
  useEffect(() => { setLocal(value); }, [key]);
  const apply = (next: T): void => {
    setLocal(next);
    void onCommit(next);
  };
  return [local, apply];
}

export function NumberInput({
  value, onChange, min, max, suffix, prefix, disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  prefix?: string;
  disabled?: boolean;
}) {
  const [text, setText] = useState(String(Number.isFinite(value) ? value : 0));
  useEffect(() => { setText(String(Number.isFinite(value) ? value : 0)); }, [value]);
  const commit = (): void => {
    let n = parseFloat(text);
    if (!Number.isFinite(n)) { setText(String(Number.isFinite(value) ? value : 0)); return; }
    if (min != null) n = Math.max(min, n);
    if (max != null) n = Math.min(max, n);
    if (n !== value) onChange(n);
    setText(String(n));
  };
  return (
    <div className={cls('relative', disabled && 'opacity-50')}>
      {prefix && (
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-krypt-dim">
          {prefix}
        </span>
      )}
      <input
        type="text"
        inputMode="decimal"
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
        className={cls(
          'krypt-input font-mono',
          prefix && 'pl-7',
          suffix && 'pr-12',
          disabled && 'cursor-not-allowed',
        )}
      />
      {suffix && (
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-krypt-dim">
          {suffix}
        </span>
      )}
    </div>
  );
}

export function PercentInput({
  value, onChange, step = 1, min = 0, max = 100, disabled,
}: {
  value: number;
  onChange: (fraction: number) => void;
  step?: number;
  min?: number;
  max?: number;
  disabled?: boolean;
}) {
  return (
    <NumberInput
      value={Math.round((value || 0) * 10000) / 100}
      step={step}
      min={min}
      max={max}
      suffix="%"
      disabled={disabled}
      onChange={(v) => onChange(v / 100)}
    />
  );
}

export function Section({
  title, description, children,
}: { title: string; description?: string; children: ReactNode }) {
  return (
    <div className="mb-6">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-krypt-muted">
          {title}
        </h3>
        {description && (
          <p className="ml-4 max-w-md text-right text-xs text-krypt-dim">{description}</p>
        )}
      </div>
      {children}
    </div>
  );
}
