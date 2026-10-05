import { useState } from 'react';
import {
  AlertTriangle, CheckCircle2, ChevronDown, CircleHelp, ExternalLink, ShieldCheck, XCircle,
} from 'lucide-react';
import type { ResolutionRisk, RiskVerdict } from '@shared/market';
import { cls } from '../../utils/format';

const ICON: Record<RiskVerdict, React.ComponentType<{ className?: string }>> = {
  pass: CheckCircle2,
  warn: AlertTriangle,
  fail: XCircle,
  unknown: CircleHelp,
};

const TONE: Record<RiskVerdict, string> = {
  pass: 'text-krypt-win',
  warn: 'text-krypt-warn',
  fail: 'text-krypt-loss',
  unknown: 'text-krypt-dim',
};

export function ResolutionRiskPanel({ risk }: { risk: ResolutionRisk }) {
  const [rulesOpen, setRulesOpen] = useState(false);
  const scoreTone =
    risk.score === null ? 'text-krypt-dim'
      : risk.score >= 85 ? 'text-krypt-win'
        : risk.score >= 60 ? 'text-krypt-warn'
          : 'text-krypt-loss';

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-4">
        <div className="shrink-0 text-center">
          <div className={cls('font-mono text-3xl font-medium', scoreTone)}>
            {risk.score === null ? '—' : risk.score}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-krypt-dim">score</div>
        </div>
        <p className="text-[11px] leading-relaxed text-krypt-muted">{risk.scoreNote}</p>
      </div>

      <div className="space-y-1.5">
        {risk.checks.map((c) => {
          const Icon = ICON[c.verdict];
          return (
            <div key={c.id} className="flex gap-2.5 rounded-lg bg-white/[0.02] px-3 py-2">
              <Icon className={cls('mt-0.5 h-3.5 w-3.5 shrink-0', TONE[c.verdict])} />
              <div className="min-w-0">
                <div className="text-[11px] font-medium text-white/90">{c.label}</div>
                <div className="text-[11px] leading-relaxed text-krypt-muted">{c.detail}</div>
              </div>
            </div>
          );
        })}
      </div>

      {risk.settlementSources && risk.settlementSources.length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-krypt-muted">
            Settles against
          </div>
          <div className="flex flex-wrap gap-1.5">
            {risk.settlementSources.map((s, i) => (
              <SourceChip key={`${s.name}-${i}`} name={s.name} url={s.url} />
            ))}
          </div>
        </div>
      )}

      {risk.rulesPrimary && (
        <div>
          <button
            onClick={() => setRulesOpen((v) => !v)}
            className="flex w-full items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-krypt-muted hover:text-white"
          >
            <ChevronDown className={cls('h-3 w-3 transition-transform', rulesOpen && 'rotate-180')} />
            Settlement rules
          </button>
          {rulesOpen && (
            <div className="mt-2 space-y-3 rounded-lg border border-krypt-border bg-krypt-surface2/40 p-3">
              <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-krypt-muted">
                {risk.rulesPrimary}
              </p>
              {risk.rulesSecondary && (
                <p className="whitespace-pre-wrap border-t border-krypt-border pt-3 text-[11px] leading-relaxed text-krypt-dim">
                  {risk.rulesSecondary}
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2.5 rounded-lg border border-krypt-indigo/25 bg-krypt-indigo/[0.06] px-3 py-2.5">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-krypt-indigo" />
        <p className="text-[11px] leading-relaxed text-krypt-muted">{risk.venueNote}</p>
      </div>
    </div>
  );
}

function SourceChip({ name, url }: { name: string; url: string | null }) {
  const body = (
    <>
      {name}
      {url && <ExternalLink className="h-2.5 w-2.5 opacity-60" />}
    </>
  );
  if (!url) {
    return <span className="krypt-badge !text-[10px] normal-case tracking-normal">{body}</span>;
  }
  return (
    <button
      onClick={() => void window.krypt.app.openExternal(url)}
      className="krypt-badge !text-[10px] normal-case tracking-normal transition-colors hover:border-krypt-purple/50 hover:text-white"
      title={url}
    >
      {body}
    </button>
  );
}
