import type { ReactNode } from 'react';
import { ArrowLeft, CheckCircle2, Info, TriangleAlert } from 'lucide-react';
import { cls } from '../utils/format';


export function StepDots({ count, at }: { count: number; at: number }) {
  return (
    <div className="flex items-center gap-1" aria-label={`Step ${at + 1} of ${count}`}>
      {Array.from({ length: count }, (_, i) => (
        <span
          key={i}
          className={cls(
            'h-1.5 rounded-full transition-all',
            i === at ? 'w-6 bg-krypt-purple' : i < at ? 'w-1.5 bg-krypt-purple/50' : 'w-1.5 bg-krypt-border',
          )}
        />
      ))}
    </div>
  );
}

export function StepHeader({
  step, count, title, subtitle,
}: { step: number; count: number; title: string; subtitle?: ReactNode }) {
  return (
    <div className="mb-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <StepDots count={count} at={step} />
        <span className="text-[10px] uppercase tracking-wider text-krypt-dim">
          Step {step + 1} of {count}
        </span>
      </div>
      <h3 className="text-base font-semibold text-white">{title}</h3>
      {subtitle && <p className="mt-1 text-xs leading-relaxed text-krypt-muted">{subtitle}</p>}
    </div>
  );
}

export function StepFooter({
  onBack, onSkip, skipLabel = "I'll do this later", children,
}: {
  onBack?: () => void;
  onSkip?: () => void;
  skipLabel?: string;
  children?: ReactNode;
}) {
  return (
    <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-krypt-border pt-4">
      {onBack && (
        <button type="button" onClick={onBack} className="krypt-btn-ghost">
          <ArrowLeft className="h-4 w-4" /> Back
        </button>
      )}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {onSkip && (
          <button type="button" onClick={onSkip} className="krypt-btn-ghost text-krypt-muted">
            {skipLabel}
          </button>
        )}
        {children}
      </div>
    </div>
  );
}

export function ChoiceCard({
  selected, onClick, title, badge, children, tone = 'purple', testId,
}: {
  selected: boolean;
  onClick: () => void;
  title: ReactNode;
  badge?: ReactNode;
  children?: ReactNode;
  tone?: 'purple' | 'warn' | 'loss';
  testId?: string;
}) {
  const ring = tone === 'loss'
    ? 'border-krypt-loss/60 bg-krypt-loss/10'
    : tone === 'warn'
      ? 'border-krypt-warn/60 bg-krypt-warn/10'
      : 'border-krypt-purple/70 bg-krypt-purple/15 shadow-[0_0_16px_-6px_rgba(168,85,247,0.8)]';
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      aria-pressed={selected}
      className={cls(
        'w-full rounded-xl border p-3 text-left transition',
        selected ? ring : 'border-krypt-border bg-krypt-surface2 hover:border-krypt-borderHi',
      )}
    >
      <div className="flex items-center gap-2">
        <span className={cls(
          'grid h-4 w-4 shrink-0 place-items-center rounded-full border',
          selected ? 'border-krypt-purple bg-krypt-purple' : 'border-krypt-border',
        )}>
          {selected && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
        </span>
        <span className="text-sm font-medium text-white">{title}</span>
        {badge && <span className="ml-auto">{badge}</span>}
      </div>
      {children && <div className="mt-1 pl-6 text-xs leading-relaxed text-krypt-muted">{children}</div>}
    </button>
  );
}

export function Badge({ children, tone = 'win' }: { children: ReactNode; tone?: 'win' | 'warn' | 'loss' | 'muted' }) {
  const c = {
    win: 'border-krypt-win/30 bg-krypt-win/10 text-krypt-win',
    warn: 'border-krypt-warn/30 bg-krypt-warn/10 text-krypt-warn',
    loss: 'border-krypt-loss/30 bg-krypt-loss/10 text-krypt-loss',
    muted: 'border-krypt-border bg-krypt-surface2 text-krypt-muted',
  }[tone];
  return (
    <span className={cls('rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider', c)}>
      {children}
    </span>
  );
}

export function Callout({
  tone, title, children, testId,
}: { tone: 'error' | 'ok' | 'info' | 'warn'; title?: ReactNode; children?: ReactNode; testId?: string }) {
  const c = {
    error: 'border-krypt-loss/40 bg-krypt-loss/5 text-krypt-loss',
    ok: 'border-krypt-win/30 bg-krypt-win/5 text-krypt-win',
    info: 'border-krypt-border bg-krypt-surface2 text-krypt-muted',
    warn: 'border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn',
  }[tone];
  const Icon = tone === 'ok' ? CheckCircle2 : tone === 'info' ? Info : TriangleAlert;
  return (
    <div data-testid={testId} className={cls('flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-relaxed', c)}>
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="min-w-0">
        {title && <div className="font-medium">{title}</div>}
        {children && <div className={cls(title ? 'mt-0.5 opacity-90' : '', tone === 'info' ? '' : 'text-white/80')}>{children}</div>}
      </div>
    </div>
  );
}
