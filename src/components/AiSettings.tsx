import { useEffect, useState } from 'react';
import { Check, Sparkles, Trash2 } from 'lucide-react';
import type { TraderConfig } from '@shared/types';
import type { AiProvider, AiStatus } from '@shared/market';
import { Card, Section, Switch } from './common';
import { useToast } from '../state/ToastProvider';
import { cls } from '../utils/format';

export function AiSettings({
  config, update,
}: {
  config: TraderConfig;
  update: <K extends keyof TraderConfig>(k: K, v: TraderConfig[K]) => Promise<void>;
}) {
  const toast = useToast();
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  const provider: AiProvider = config.aiProvider ?? 'anthropic';
  const label = provider === 'openai' ? 'OpenAI' : 'Anthropic';

  const load = (): void => {
    window.krypt.terminal.aiStatus().then(setStatus).catch(() => setStatus(null));
  };
  useEffect(load, []);
  useEffect(() => { setDraft(''); }, [provider]);

  const saveKey = async (key: string): Promise<void> => {
    setBusy(true);
    try {
      await window.krypt.terminal.aiSetKey({ provider, key });
      setDraft('');
      load();
      toast.success(key ? `${label} key saved.` : `${label} key removed.`);
    } catch (e: any) {
      toast.error(`${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  const hasKey = status?.keys?.[provider] ?? false;
  const models = status?.models?.[provider] ?? [];

  return (
    <Section
      title="AI analysis"
      description={
        'Analyse any market in the Terminal with a language model. You bring the '
        + 'key and the provider bills you directly — the app has no AI of its own '
        + 'and no account of its own.'
      }
    >
      <Card>
        <div className="grid gap-4 md:grid-cols-2">
          <Row label="Provider" hint="Which account the analysis runs on.">
            <div className="flex gap-2">
              {(['anthropic', 'openai'] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => void update('aiProvider', p)}
                  className={cls(
                    'flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition',
                    provider === p
                      ? 'border-krypt-purple/50 bg-krypt-purple/15 text-white'
                      : 'border-krypt-border text-krypt-dim hover:text-white',
                  )}
                >
                  {p === 'anthropic' ? 'Claude' : 'OpenAI'}
                  {status?.keys?.[p] && (
                    <Check className="ml-1.5 inline h-3.5 w-3.5 text-krypt-win" />
                  )}
                </button>
              ))}
            </div>
          </Row>

          <Row
            label="Model"
            hint="Most capable first. Cost per analysis follows the same order."
          >
            <select
              value={config.aiModel ?? ''}
              onChange={(e) => void update('aiModel', e.target.value)}
              className="w-full rounded-lg border border-krypt-border bg-krypt-surface2 px-3 py-2 text-sm text-white outline-none focus:border-krypt-purple/50"
            >
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </Row>
        </div>

        <div className="mt-4">
          <Row
            label={`${label} API key`}
            hint="Stored encrypted with your Kalshi credentials — never in settings.json, and never written to a log."
          >
            <div className="flex gap-2">
              <input
                type="password"
                value={draft}
                autoComplete="off"
                spellCheck={false}
                placeholder={hasKey
                  ? 'A key is saved. Type a new one to replace it.'
                  : `Paste your ${label} API key`}
                onChange={(e) => setDraft(e.target.value)}
                className="min-w-0 flex-1 rounded-lg border border-krypt-border bg-krypt-surface2 px-3 py-2 font-mono text-sm text-white outline-none placeholder:text-krypt-dim focus:border-krypt-purple/50"
              />
              <button
                type="button"
                disabled={busy || !draft.trim()}
                onClick={() => void saveKey(draft.trim())}
                className={cls(
                  'rounded-lg border px-3 py-2 text-sm font-medium transition',
                  busy || !draft.trim()
                    ? 'cursor-not-allowed border-krypt-border text-krypt-dim'
                    : 'border-krypt-purple/40 bg-krypt-purple/15 text-krypt-purple hover:bg-krypt-purple/25',
                )}
              >
                Save
              </button>
              {hasKey && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void saveKey('')}
                  title={`Remove the saved ${label} key`}
                  className="rounded-lg border border-krypt-border px-3 py-2 text-krypt-dim transition hover:border-krypt-loss/40 hover:text-krypt-loss"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          </Row>
          <p className="mt-2 text-xs text-krypt-dim">
            {hasKey
              ? `A ${label} key is saved. It cannot be read back here — replace it or remove it.`
              : `No ${label} key yet. Markets will say so instead of offering an analysis.`}
          </p>
        </div>

        <div className="mt-4 border-t border-krypt-border pt-4">
          <Switch
            label="Let the model search the web"
            description={
              'Off by default, and worth understanding before switching on. It is the '
              + 'single biggest quality difference on "will X happen by Y" — without it '
              + 'the model can only reason about the price, not about what has actually '
              + 'happened. It also costs meaningfully more per analysis, and it sends '
              + 'the market question to your provider search.'
            }
            checked={config.aiWebSearch ?? false}
            onChange={(v) => void update('aiWebSearch', v)}
          />
        </div>

        <p className="mt-4 flex items-start gap-2 text-xs leading-relaxed text-krypt-dim">
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            An analysis runs only when you press the button on a market, never on a
            timer and never in the background, because each one is a billed request
            on your key. The model is shown this app&apos;s own market data with the
            gaps marked as gaps, and it is told not to recommend a trade — it has no
            way to place one regardless.
          </span>
        </p>
      </Card>
    </Section>
  );
}

function Row({
  label, hint, children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-white">{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-krypt-dim">{hint}</p>}
    </div>
  );
}
