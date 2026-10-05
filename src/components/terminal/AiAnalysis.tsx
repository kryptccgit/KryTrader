import { useCallback, useEffect, useState } from 'react';
import {
  ExternalLink, Globe, KeyRound, Loader2, Sparkles, TriangleAlert,
} from 'lucide-react';
import type { AiAnalysis as AiAnalysisT, AiStatus, AiVerdict } from '@shared/market';
import type { PageId } from '../../App';
import { cls } from '../../utils/format';
import { Caveat, Cents, Unknown } from './atoms';

const VERDICT: Record<AiVerdict, { label: string; cls: string; note: string }> = {
  cheap: {
    label: 'Looks cheap',
    cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    note: 'The model puts fair value above where this is trading.',
  },
  rich: {
    label: 'Looks rich',
    cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    note: 'The model puts fair value below where this is trading.',
  },
  fair: {
    label: 'Looks fair',
    cls: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    note: 'The model lands about where the market is.',
  },
  unclear: {
    label: 'No call',
    cls: 'bg-white/5 text-krypt-muted border-krypt-border',
    note: 'The model would not commit to a fair value. That is an answer, not a gap.',
  },
};

export function AiAnalysis({
  ticker, onNav,
}: {
  ticker: string;
  onNav?: (p: PageId) => void;
}) {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [analysis, setAnalysis] = useState<AiAnalysisT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    window.krypt.terminal.aiStatus()
      .then((s) => { if (live) setStatus(s); })
      .catch(() => { if (live) setStatus(null); });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    setAnalysis(null);
    setError(null);
  }, [ticker]);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await window.krypt.terminal.aiAnalyze({ ticker });
      if (res.ok) setAnalysis(res.analysis);
      else setError(res.error);
    } catch (e: any) {
      setError(e?.message || 'The analysis failed.');
    } finally {
      setBusy(false);
    }
  }, [ticker]);

  if (status && !status.hasKey) return <NeedsKey provider={status.provider} onNav={onNav} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-krypt-muted">
          {status ? (
            <>
              <span className="font-mono text-krypt-dim">{status.model}</span>
              {status.webSearch && (
                <span className="ml-2 inline-flex items-center gap-1 text-krypt-dim">
                  <Globe className="h-3 w-3" /> web search on
                </span>
              )}
            </>
          ) : 'Checking your AI setup…'}
        </div>
        <button
          type="button"
          onClick={run}
          disabled={busy || !status}
          className={cls(
            'inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium transition',
            busy || !status
              ? 'cursor-not-allowed border-krypt-border text-krypt-dim'
              : 'border-krypt-purple/40 bg-krypt-purple/15 text-krypt-purple hover:bg-krypt-purple/25',
          )}
        >
          {busy
            ? <><Loader2 className="h-4 w-4 animate-spin" /> Analysing…</>
            : <><Sparkles className="h-4 w-4" /> {analysis ? 'Analyse again' : 'Analyse this market'}</>}
        </button>
      </div>

      {busy && (
        <p className="text-sm text-krypt-muted">
          Reading the market, the event’s other legs and the resolution rules
          {status?.webSearch ? ', and searching the web' : ''}. This usually takes
          {status?.webSearch ? ' under a minute' : ' a few seconds'}.
        </p>
      )}

      {error && !busy && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {analysis && !busy && <Result a={analysis} />}

      {!analysis && !busy && !error && (
        <p className="text-sm text-krypt-muted">
          Nothing is sent anywhere until you press the button, and each press is
          one billed request against your own key.
        </p>
      )}
    </div>
  );
}

function NeedsKey({ provider, onNav }: { provider: string; onNav?: (p: PageId) => void }) {
  const label = provider === 'openai' ? 'OpenAI' : 'Anthropic';
  return (
    <div className="flex flex-col items-start gap-3 py-6">
      <div className="flex items-center gap-2 text-sm text-krypt-muted">
        <KeyRound className="h-4 w-4 text-krypt-dim" />
        <span>Set your AI API key in Settings to analyse markets.</span>
      </div>
      <p className="text-xs text-krypt-dim">
        The app has no AI of its own and no key of its own — analysis runs on
        your {label} account, on your key, and is billed to you. The key is
        stored encrypted alongside your Kalshi credentials, never in settings.json.
      </p>
      {onNav && (
        <button
          type="button"
          onClick={() => onNav('settings')}
          className="rounded-lg border border-krypt-purple/40 bg-krypt-purple/15 px-3 py-1.5 text-sm font-medium text-krypt-purple transition hover:bg-krypt-purple/25"
        >
          Open Settings
        </button>
      )}
    </div>
  );
}

function Result({ a }: { a: AiAnalysisT }) {
  if (a.raw) {
    return (
      <div className="space-y-3">
        <Caveat>
          The model answered in prose rather than the expected shape, so this is
          its reply verbatim — nothing below has been checked or structured.
        </Caveat>
        <pre className="whitespace-pre-wrap rounded-lg border border-krypt-border bg-krypt-void/50 p-3 text-sm text-white">
          {a.raw}
        </pre>
        <Footer a={a} />
      </div>
    );
  }

  const v = VERDICT[a.verdict] ?? VERDICT.unclear;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cls('rounded-full border px-2.5 py-1 text-xs font-medium', v.cls)}
          title={v.note}
        >
          {v.label}
        </span>
        <div className="text-sm">
          <span className="text-krypt-muted">Model’s fair value </span>
          <Cents
            value={a.fairValueCents}
            why="The model declined to name a fair value for this market. That is its answer — it has not been replaced with a midpoint or a guess."
            className="text-base font-semibold text-white"
          />
          {a.fairValueLowCents !== null && a.fairValueHighCents !== null && (
            <span className="ml-2 text-krypt-dim">
              (range <Cents value={a.fairValueLowCents} />–<Cents value={a.fairValueHighCents} />)
            </span>
          )}
        </div>
        <span className="text-xs text-krypt-dim">confidence: {a.confidence}</span>
      </div>

      {a.summary && <p className="text-sm leading-relaxed text-white">{a.summary}</p>}

      {a.drivers.length > 0 && (
        <Block title="What’s driving it">
          <ul className="space-y-2">
            {a.drivers.map((d, i) => (
              <li key={i} className="text-sm">
                <span className="font-medium text-white">{d.heading}. </span>
                <span className="text-krypt-muted">{d.body}</span>
              </li>
            ))}
          </ul>
        </Block>
      )}

      {a.resolutionNotes && (
        <Block title="What the rules actually say">
          <p className="text-sm text-krypt-muted">{a.resolutionNotes}</p>
        </Block>
      )}

      {a.wouldChangeMyMind.length > 0 && (
        <Block title="What would change this read">
          <ul className="list-disc space-y-1 pl-5">
            {a.wouldChangeMyMind.map((s, i) => (
              <li key={i} className="text-sm text-krypt-muted">{s}</li>
            ))}
          </ul>
        </Block>
      )}

      {a.citations.length > 0 && (
        <Block title={`Sources it opened (${a.citations.length})`}>
          <ul className="space-y-1">
            {a.citations.map((c, i) => (
              <li key={i} className="truncate text-sm">
                <a
                  href={c.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-krypt-purple hover:underline"
                >
                  <ExternalLink className="h-3 w-3 shrink-0" />
                  <span className="truncate">{c.title}</span>
                </a>
              </li>
            ))}
          </ul>
        </Block>
      )}

      <Caveat>
        This is one language model’s reading of the data on this page, not
        research and not advice. It can be confidently wrong about a market that
        settles on wording it never saw. Check the resolution rules yourself
        before you trade it.
      </Caveat>

      <Footer a={a} />
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-krypt-dim">
        {title}
      </h4>
      {children}
    </div>
  );
}

function Footer({ a }: { a: AiAnalysisT }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-krypt-border pt-2 text-xs text-krypt-dim">
      <span className="font-mono">{a.model}</span>
      <span>{a.elapsedSec}s</span>
      {a.webSearchUsed && <span>web search</span>}
      <span>
        {a.inputTokens ?? '—'} in / {a.outputTokens ?? '—'} out
      </span>
      <span title={
        a.costUsd === null
          ? 'We do not have a published per-token price for this model, so no cost is shown. A plausible-looking guess would be worse than nothing.'
          : 'Estimated from published per-token prices — your provider’s invoice is the real number.'
      }>
        {a.costUsd === null
          ? <>cost <Unknown why="No published per-token price for this model." /></>
          : <>~${a.costUsd.toFixed(4)}</>}
      </span>
    </div>
  );
}
