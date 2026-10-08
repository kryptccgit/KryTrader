import { ReactNode, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Share2 } from 'lucide-react';
import { cls } from '../utils/format';
import { shareToX, X_PROFILE } from '../utils/share';
import { GlassPanel } from './glass/GlassPanel';
import { GlassButton } from './glass/GlassButton';
import { GlassSwitch } from './glass/GlassSwitch';
import { GLASS_TINTS } from './glass/glassPresets';

export function DialogShell({
  onClose, maxWidth, children,
}: { onClose: () => void; maxWidth: string; children: ReactNode }) {
  return createPortal(
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4"
      onMouseDown={onClose}
    >
      <GlassPanel
        preset="modal"
        tint={GLASS_TINTS.modal}
        className={cls('glass-pop w-full rounded-2xl p-5', maxWidth)}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {children}
      </GlassPanel>
    </div>,
    document.body,
  );
}

export function Modal({
  open, onClose, maxWidth = 'max-w-xl', children,
}: { open: boolean; onClose: () => void; maxWidth?: string; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent): void => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/45 p-4">
      <GlassPanel
        preset="modal"
        tint={GLASS_TINTS.modal}
        className={cls('glass-pop w-full rounded-2xl p-6', maxWidth)}
      >
        {children}
      </GlassPanel>
    </div>,
    document.body,
  );
}

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
    <DialogShell onClose={onClose} maxWidth="max-w-sm">
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
          <GlassButton onClick={onClose}>Cancel</GlassButton>
          <GlassButton variant="primary" onClick={submit} disabled={!value.trim()}>
            {confirmLabel}
          </GlassButton>
        </div>
    </DialogShell>
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
    <DialogShell onClose={onClose} maxWidth="max-w-md">
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        <div className="mt-2 text-xs leading-relaxed text-white/70">{body}</div>
        <div className="mt-4 flex justify-end gap-2">
          <GlassButton onClick={onClose}>{cancelLabel}</GlassButton>
          <GlassButton variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </GlassButton>
        </div>
    </DialogShell>
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
          <h2 className="glass-title text-2xl font-semibold tracking-tight">{title}</h2>
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
        <div className="-mx-5 -mt-5 mb-4 rounded-t-2xl border-b border-white/[0.06] bg-gradient-to-b from-white/[0.05] to-white/[0.01] px-5 py-3">
          {header}
        </div>
      )}
      {children}
      {footer && (
        <div className="-mx-5 -mb-5 mt-4 rounded-b-2xl border-t border-white/[0.06] bg-white/[0.02] px-5 py-3">
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
  return (
    <GlassPanel
      preset="card"
      tint={ACCENT_TINT[accent ?? 'neutral']}
      className={cls('rounded-2xl p-5', className)}
      style={{ boxShadow: ACCENT_GLOW[accent ?? 'neutral'] }}
    >
      <div className="text-[11px] uppercase tracking-wider text-krypt-muted">{label}</div>
      <div className="mt-1 font-mono text-2xl font-medium tabular-nums text-white [text-shadow:0_1px_12px_rgba(0,0,0,0.5)]">{value}</div>
      {hint && <div className="mt-1 text-xs text-white/50">{hint}</div>}
    </GlassPanel>
  );
}

const ACCENT_TINT: Record<'good' | 'bad' | 'warn' | 'neutral', string> = {
  neutral: GLASS_TINTS.card,
  good: 'linear-gradient(160deg, rgba(34,197,94,0.13), rgba(14,14,24,0.58) 55%)',
  bad: 'linear-gradient(160deg, rgba(239,68,68,0.13), rgba(14,14,24,0.58) 55%)',
  warn: 'linear-gradient(160deg, rgba(245,158,11,0.13), rgba(14,14,24,0.58) 55%)',
};

const ACCENT_GLOW: Record<'good' | 'bad' | 'warn' | 'neutral', string> = {
  neutral: 'var(--glass-shadow)',
  good: 'inset 0 0 0 1px rgba(34,197,94,0.32), 0 0 34px -14px rgba(34,197,94,0.55), var(--glass-shadow)',
  bad: 'inset 0 0 0 1px rgba(239,68,68,0.32), 0 0 34px -14px rgba(239,68,68,0.55), var(--glass-shadow)',
  warn: 'inset 0 0 0 1px rgba(245,158,11,0.32), 0 0 34px -14px rgba(245,158,11,0.5), var(--glass-shadow)',
};

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
        'grid place-items-center rounded-lg border border-white/10 bg-gradient-to-b from-white/[0.08] to-white/[0.02] text-krypt-muted shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] transition-all duration-200 hover:border-krypt-purple/50 hover:bg-krypt-purple/15 hover:text-white hover:shadow-[0_0_16px_-4px_rgba(168,85,247,0.7)] active:scale-90',
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
    <div className="grid place-items-center rounded-2xl border border-dashed border-white/10 bg-white/[0.015] p-10 text-center">
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
    <div
      onClick={() => { if (!disabled) onChange(!checked); }}
      className={cls(
        'flex w-full cursor-pointer select-none items-center justify-between gap-4 rounded-xl border border-white/[0.07] bg-white/[0.025] p-3 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] transition-colors hover:border-white/[0.14] hover:bg-white/[0.04]',
        disabled && 'cursor-not-allowed',
      )}
    >
      <div className={cls('flex-1', disabled && 'opacity-50')}>
        {label && <div className="text-sm text-white">{label}</div>}
        {description && (
          <div className="mt-0.5 text-xs text-krypt-muted">{description}</div>
        )}
      </div>
      <div className="shrink-0" onClick={(e) => e.stopPropagation()}>
        <GlassSwitch
          checked={checked}
          onCheckedChange={onChange}
          disabled={disabled}
          ariaLabel={label}
          width={44}
          height={24}
        />
      </div>
    </div>
  );
}

export function useOptimisticValue<T>(
  value: T,
  onCommit: (next: T) => void | Promise<void>,
): [T, (next: T) => void] {
  const [local, setLocal] = useState<T>(value);
  const key = JSON.stringify(value ?? null);
  useEffect(() => { setLocal(value); }, [key]);
  const valueRef = useRef(value);
  valueRef.current = value;
  const seq = useRef(0);
  const apply = (next: T): void => {
    setLocal(next);
    const mine = ++seq.current;
    const rollback = (): void => {
      if (mine === seq.current) setLocal(valueRef.current);
    };
    try {
      void Promise.resolve(onCommit(next)).catch(rollback);
    } catch {
      rollback();
    }
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
