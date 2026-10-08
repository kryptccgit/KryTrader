import { useCallback, useEffect, useState } from 'react';
import { Check, Cpu, PlugZap, Sparkles, Trash2 } from 'lucide-react';
import type { TraderConfig } from '@shared/types';
import type { AiProvider, AiProviderCheck, AiStatus } from '@shared/market';
import { Card, Section, Switch } from './common';
import { useToast } from '../state/ToastProvider';
import { cls } from '../utils/format';
import { userMessage } from '../utils/errors';


const PROVIDERS: { id: AiProvider; name: string; keyHint?: string }[] = [
  { id: 'anthropic', name: 'Claude', keyHint: 'sk-ant-…' },
  { id: 'openai', name: 'OpenAI', keyHint: 'sk-…' },
  { id: 'openrouter', name: 'OpenRouter', keyHint: 'sk-or-…' },
  { id: 'gemini', name: 'Gemini', keyHint: 'AIza…' },
  { id: 'ollama', name: 'Ollama' },
  { id: 'lmstudio', name: 'LM Studio' },
];

const LOCAL_SETUP: Partial<Record<AiProvider, string>> = {
  ollama: 'Install Ollama, start it (`ollama serve`, or open the app) and pull a model '
    + 'that can call tools, e.g. `ollama pull llama3.1:8b`.',
  lmstudio: 'In LM Studio, download a model, then open the Developer tab and start the '
    + 'local server (or run `lms server start`). Leave the model blank to use whichever '
    + 'one is loaded.',
};

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
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<AiProviderCheck | null>(null);

  const provider: AiProvider = config.aiProvider ?? 'anthropic';
  const caps = status?.capabilities?.[provider];
  const label = caps?.label ?? PROVIDERS.find((p) => p.id === provider)?.name ?? provider;
  const local = caps?.local ?? (provider === 'ollama' || provider === 'lmstudio');
  const needsKey = caps?.needsKey ?? !local;

  const load = useCallback((): void => {
    window.krypt.terminal.aiStatus().then(setStatus).catch(() => setStatus(null));
  }, []);
  useEffect(load, [load]);

  const runCheck = useCallback(async (p: AiProvider): Promise<void> => {
    setChecking(true);
    try {
      const res = await window.krypt.terminal.aiCheckProvider({ provider: p });
      setCheck(res);
      if (res.models?.length) load();
    } catch (e: any) {
      setCheck({ ok: false, provider: p, message: userMessage(e) });
    } finally {
      setChecking(false);
    }
  }, [load]);

  useEffect(() => {
    setDraft('');
    setCheck(null);
    if (provider === 'ollama' || provider === 'lmstudio') void runCheck(provider);
  }, [provider, runCheck]);

  const pickProvider = async (p: AiProvider): Promise<void> => {
    if (p === provider) return;
    await update('aiProvider', p);
    await update('aiModel', '');
    load();
  };

  const saveKey = async (key: string): Promise<void> => {
    setBusy(true);
    try {
      await window.krypt.terminal.aiSetKey({ provider, key });
      setDraft('');
      setCheck(null);
      load();
      toast.success(key ? `${label} key saved.` : `${label} key removed.`);
    } catch (e: any) {
      toast.error(userMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const [modelDraft, setModelDraft] = useState(config.aiModel ?? '');
  useEffect(() => { setModelDraft(config.aiModel ?? ''); }, [config.aiModel, provider]);
  const commitModel = async (): Promise<void> => {
    const next = modelDraft.trim();
    if (next === (config.aiModel ?? '')) return;
    await update('aiModel', next);
    load();
  };

  const hasKey = status?.keys?.[provider] ?? false;
  const models = status?.models?.[provider] ?? [];
  const curated = caps?.catalogue === 'curated';
  const modelValue = config.aiModel || (status?.provider === provider ? status.model : '');
  const toolInfo = check?.modelInfo
    ? new Map(check.modelInfo.map((m) => [m.id, m.tools]))
    : null;

  return (
    <Section
      title="AI analysis"
      description={
        'Analyse any market in the Terminal with a language model, and run Autopilot. '
        + 'Bring a key from a cloud provider — billed to you directly — or run a model '
        + 'on this machine with Ollama or LM Studio. The app has no AI and no account of its own.'
      }
    >
      <Card>
        <Row label="Provider" hint="Which account, or which program on this machine, the analysis runs on.">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {PROVIDERS.map((p) => {
              const isLocal = status?.capabilities?.[p.id]?.local
                ?? (p.id === 'ollama' || p.id === 'lmstudio');
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => void pickProvider(p.id)}
                  className={cls(
                    'flex items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition',
                    provider === p.id
                      ? 'border-krypt-purple/50 bg-krypt-purple/15 text-white'
                      : 'border-krypt-border text-krypt-dim hover:text-white',
                  )}
                >
                  {isLocal && <Cpu className="h-3.5 w-3.5" />}
                  {p.name}
                  {status?.keys?.[p.id] && <Check className="h-3.5 w-3.5 text-krypt-win" />}
                </button>
              );
            })}
          </div>
        </Row>

        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <Row
            label="Model"
            hint={curated
              ? 'Most capable first. Cost per analysis follows the same order.'
              : local
                ? 'Installed models appear here once the connection test sees them.'
                : 'Type any model id, or pick one Test connection listed.'}
          >
            {curated ? (
              <select
                value={modelValue}
                onChange={(e) => void update('aiModel', e.target.value).then(load)}
                className="w-full rounded-lg border border-krypt-border bg-krypt-surface2 px-3 py-2 text-sm text-white outline-none focus:border-krypt-purple/50"
              >
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : (
              <>
                <input
                  list={`ai-models-${provider}`}
                  value={modelDraft}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder={provider === 'lmstudio'
                    ? 'blank = the model loaded in LM Studio'
                    : `default: ${models[0] ?? '—'}`}
                  onChange={(e) => setModelDraft(e.target.value)}
                  onBlur={() => void commitModel()}
                  onKeyDown={(e) => { if (e.key === 'Enter') void commitModel(); }}
                  className="w-full rounded-lg border border-krypt-border bg-krypt-surface2 px-3 py-2 font-mono text-sm text-white outline-none placeholder:text-krypt-dim focus:border-krypt-purple/50"
                />
                <datalist id={`ai-models-${provider}`}>
                  {models.map((m) => {
                    const t = toolInfo?.get(m);
                    return (
                      <option key={m} value={m}>
                        {t === false ? 'no tool calling' : t ? 'tools' : ''}
                      </option>
                    );
                  })}
                </datalist>
              </>
            )}
          </Row>

          <Row
            label="Connection"
            hint="Uses free endpoints only (the model list) — never a billed request."
          >
            <button
              type="button"
              disabled={checking || (needsKey && !hasKey)}
              onClick={() => void runCheck(provider)}
              className={cls(
                'inline-flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition',
                checking || (needsKey && !hasKey)
                  ? 'cursor-not-allowed border-krypt-border text-krypt-dim'
                  : 'border-krypt-purple/40 bg-krypt-purple/15 text-krypt-purple hover:bg-krypt-purple/25',
              )}
            >
              <PlugZap className="h-4 w-4" />
              {checking ? 'Testing…' : 'Test connection'}
            </button>
          </Row>
        </div>

        {check && (
          <p
            className={cls(
              'mt-3 rounded-lg border px-3 py-2 text-xs leading-relaxed',
              check.ok
                ? 'border-krypt-win/30 bg-krypt-win/10 text-krypt-win'
                : 'border-krypt-warn/30 bg-krypt-warn/10 text-krypt-warn',
            )}
          >
            {check.message}
          </p>
        )}

        {needsKey ? (
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
                    : `Paste your ${label} API key (${PROVIDERS.find((p) => p.id === provider)?.keyHint ?? ''})`}
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
        ) : (
          <p className="mt-4 flex items-start gap-2 text-xs leading-relaxed text-krypt-dim">
            <Cpu className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              {label} runs on this machine: no key, no bill, and the market data never
              leaves your computer. {LOCAL_SETUP[provider]}
            </span>
          </p>
        )}

        <div className="mt-4 border-t border-krypt-border pt-4">
          <Switch
            label="Let the model search the web"
            description={caps && !caps.webSearch
              ? `${label} has no web search — a local model can only reason about the data `
                + 'it is shown. The analysis will say it did not search.'
              : 'Off by default, and worth understanding before switching on. It is the '
                + 'single biggest quality difference on "will X happen by Y" — without it '
                + 'the model can only reason about the price, not about what has actually '
                + `happened. It also costs more per analysis, and it sends the market question `
                + `to your provider's search${caps ? ` (${caps.webSearchHow})` : ''}.`}
            checked={(config.aiWebSearch ?? false) && (caps?.webSearch ?? true)}
            disabled={caps ? !caps.webSearch : false}
            onChange={(v) => void update('aiWebSearch', v)}
          />
        </div>

        {caps && (
          <p className="mt-3 text-xs leading-relaxed text-krypt-dim">
            Autopilot needs tool calling: {caps.toolsHow}. Token counts: {caps.tokens}.
          </p>
        )}

        <p className="mt-4 flex items-start gap-2 text-xs leading-relaxed text-krypt-dim">
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            An analysis runs only when you press the button on a market, never on a
            timer and never in the background{local ? '' : ', because each one is a billed request on your key'}.
            The model is shown this app&apos;s own market data with the gaps marked as
            gaps, and it is told not to recommend a trade — it has no way to place one
            regardless.
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
