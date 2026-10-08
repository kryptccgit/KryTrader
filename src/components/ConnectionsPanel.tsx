import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, ClipboardCopy, ExternalLink, Loader2, MinusCircle,
  PlugZap, XCircle,
} from 'lucide-react';
import type { HealthAction, HealthReport, HealthStatus } from '@shared/market';
import type { PageId } from '../App';
import { Card, Section } from './common';
import { Caveat } from './terminal/atoms';
import { useToast } from '../state/ToastProvider';
import { cls, fmtTimeShort } from '../utils/format';
import { userMessage } from '../utils/errors';

const ICON: Record<HealthStatus, { Icon: typeof CheckCircle2; tone: string; word: string }> = {
  ok: { Icon: CheckCircle2, tone: 'text-krypt-win', word: 'OK' },
  warn: { Icon: AlertTriangle, tone: 'text-krypt-warn', word: 'Attention' },
  fail: { Icon: XCircle, tone: 'text-krypt-loss', word: 'Broken' },
  off: { Icon: MinusCircle, tone: 'text-krypt-dim', word: 'Off' },
};

const NAV_PAGES: ReadonlySet<string> = new Set<PageId>(['api', 'settings', 'remote', 'aiAgents', 'logs']);

export function ConnectionsPanel({ onNav }: { onNav?: (p: PageId) => void }) {
  const toast = useToast();
  const [report, setReport] = useState<HealthReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (deep: boolean): Promise<void> => {
    setRunning(true);
    setError(null);
    try {
      setReport(await window.krypt.terminal.healthCheck({ deep }));
    } catch (e) {
      setError(userMessage(e));
    } finally {
      setRunning(false);
    }
  }, []);

  useEffect(() => { void run(false); }, [run]);

  const act = async (a: HealthAction): Promise<void> => {
    if (a.kind === 'nav') {
      if (onNav && NAV_PAGES.has(a.page)) onNav(a.page as PageId);
      return;
    }
    try {
      await navigator.clipboard.writeText(a.text);
      toast.success('Command copied. Paste it into a terminal.');
    } catch {
      toast.error('Could not reach the clipboard.');
    }
  };

  const attention = report?.rows.filter((r) => r.status === 'fail' || r.status === 'warn').length ?? 0;

  return (
    <Section
      title="Connections"
      description="Every connection, end to end. Opening this runs local checks only; Run checks also tests Kalshi, your AI key and the HTTP API over the network."
    >
      <Card>
        <div className="mb-3 flex items-center gap-3">
          <PlugZap className="h-4 w-4 text-krypt-muted" />
          <span className="text-[11px] text-krypt-muted">
            {report
              ? `${attention ? `${attention} need${attention === 1 ? 's' : ''} attention` : 'Nothing needs attention'} · ${
                report.deep ? 'tested' : 'local check'} ${fmtTimeShort(report.checkedAt)}`
              : running ? 'Checking…' : '—'}
          </span>
          <button
            onClick={() => void run(true)}
            disabled={running}
            className="krypt-btn-default ml-auto text-xs"
            title="Tests every connection end to end, including a signed Kalshi read"
          >
            {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlugZap className="h-3.5 w-3.5" />}
            Run checks
          </button>
        </div>
        {error && <Caveat className="mb-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">{error}</Caveat>}
        <div className="divide-y divide-white/[0.06]">
          {(report?.rows ?? []).map((r) => {
            const s = ICON[r.status] ?? ICON.off;
            return (
              <div key={r.id} className="flex items-start gap-3 py-2.5">
                <s.Icon className={cls('mt-0.5 h-4 w-4 shrink-0', s.tone)} aria-label={s.word} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-sm text-white">{r.label}</span>
                    <span className={cls('text-[10px] uppercase tracking-wider', s.tone)}>{s.word}</span>
                    {r.network && !r.tested && r.status !== 'off' && (
                      <span className="text-[10px] text-krypt-dim">not tested — Run checks</span>
                    )}
                    {r.tested && <span className="text-[10px] text-krypt-dim">tested end to end</span>}
                  </div>
                  <p className="text-[11px] leading-relaxed text-krypt-muted">{r.detail}</p>
                  {r.fix && r.status !== 'ok' && (
                    <p className="mt-0.5 text-[11px] leading-relaxed text-white/80">
                      <span className="text-krypt-dim">Fix: </span>{r.fix}
                    </p>
                  )}
                  {r.action?.kind === 'copy' && r.status !== 'ok' && (
                    <code className="mt-1 block truncate rounded bg-krypt-surface2 px-2 py-1 font-mono text-[10px] text-krypt-muted">
                      {r.action.text}
                    </code>
                  )}
                </div>
                {r.action && r.status !== 'ok' && (r.action.kind === 'copy' || (onNav && NAV_PAGES.has(r.action.page))) && (
                  <button onClick={() => void act(r.action!)} className="krypt-btn-ghost shrink-0 text-xs">
                    {r.action.kind === 'copy'
                      ? <ClipboardCopy className="h-3.5 w-3.5" />
                      : <ExternalLink className="h-3.5 w-3.5" />}
                    {r.action.label}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </Section>
  );
}
