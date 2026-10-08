import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, Cpu, ExternalLink, KeyRound, Loader2, Play, PlugZap, Power } from 'lucide-react';
import type { AiProvider, AiProviderCheck, AiStatus, AutopilotStatus } from '@shared/market';
import { useApp } from '../state/AppStateProvider';
import { GlassButton } from './glass/GlassButton';
import { Badge, Callout, ChoiceCard, StepFooter, StepHeader } from './SetupSteps';
import {
  BUDGETS, LOCAL_HOWTO, MISSIONS, MISSION_MAX, PROVIDERS, buildQuickstartPatch, costLine,
  type BudgetId,
} from '../utils/autopilotQuickstart';
import { cls, fmtNum, fmtTimeShort } from '../utils/format';
import { agentsOf, DEFAULT_AGENT_ID } from '@shared/agents';
import { AgentPicker } from './agents/AgentPicker';
import { userMessage } from '../utils/errors';


const STEPS = 6;

const LOCAL = (p: AiProvider): boolean => p === 'ollama' || p === 'lmstudio';

export function AutopilotQuickstart({
  onDone, onSkip, onBackOut,
}: {
  onDone?: () => void;
  onSkip?: () => void;
  onBackOut?: () => void;
}) {
  const { config, refresh } = useApp();
  const [step, setStep] = useState(0);
  const [provider, setProvider] = useState<AiProvider>((config?.aiProvider as AiProvider) ?? 'anthropic');
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [draft, setDraft] = useState('');
  const [replacing, setReplacing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<AiProviderCheck | null>(null);
  const [model, setModel] = useState('');
  const [missionId, setMissionId] = useState(MISSIONS[0].id);
  const [mission, setMission] = useState(MISSIONS[0].text);
  const [budgetId, setBudgetId] = useState<BudgetId>('light');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ap, setAp] = useState<AutopilotStatus | null>(null);
  const [runMsg, setRunMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const agents = useMemo(() => agentsOf(config), [config]);
  const [agentId, setAgentId] = useState<string>(config?.autopilotAgentId ?? DEFAULT_AGENT_ID);

  const info = PROVIDERS.find((p) => p.id === provider)!;
  const budget = BUDGETS.find((b) => b.id === budgetId)!;
  const hasKey = status?.keys?.[provider] ?? false;

  const loadStatus = useCallback((): void => {
    window.krypt.terminal.aiStatus().then(setStatus).catch(() => setStatus(null));
  }, []);
  useEffect(loadStatus, [loadStatus]);

  const runCheck = useCallback(async (p: AiProvider): Promise<boolean> => {
    setChecking(true);
    try {
      const res = await window.krypt.terminal.aiCheckProvider({ provider: p });
      setCheck(res);
      if (res.models?.length) loadStatus();
      return res.ok;
    } catch (e) {
      setCheck({ ok: false, provider: p, message: userMessage(e) });
      return false;
    } finally {
      setChecking(false);
    }
  }, [loadStatus]);

  useEffect(() => { setCheck(null); setDraft(''); setReplacing(false); setModel(''); }, [provider]);
  useEffect(() => {
    if (step === 1 && LOCAL(provider) && !check && !checking) void runCheck(provider);
  }, [step, provider, check, checking, runCheck]);

  const saveKeyAndTest = async (): Promise<void> => {
    const key = draft.trim();
    if (!key) return;
    setBusy(true);
    try {
      await window.krypt.terminal.aiSetKey({ provider, key });
      setDraft('');
      loadStatus();
      setReplacing(!(await runCheck(provider)));
    } catch (e) {
      setCheck({ ok: false, provider, message: userMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  const models = useMemo(() => {
    const listed = check?.ok && check.models?.length ? check.models : (status?.models?.[provider] ?? []);
    const tools = new Map((check?.modelInfo ?? []).map((m) => [m.id, m.tools]));
    return listed.slice(0, 60).map((id) => ({ id, tools: tools.get(id) ?? null }));
  }, [check, status, provider]);
  const defaultModel = check?.model || status?.models?.[provider]?.[0] || '';
  const effectiveModel = model || defaultModel;

  const turnOn = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const patch = buildQuickstartPatch({ provider, model, mission, budget, agentId });
      await window.krypt.config.update(patch as never);
      await refresh.state();
      setStep(5);
    } catch (e) {
      setError(userMessage(e));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (step !== 5) return undefined;
    let alive = true;
    const read = (): void => {
      window.krypt.terminal.autopilotStatus().then((s) => { if (alive) setAp(s); }).catch(() => {});
    };
    read();
    const t = window.setInterval(read, 3000);
    return () => { alive = false; window.clearInterval(t); };
  }, [step]);

  const runNow = async (): Promise<void> => {
    setRunMsg(null);
    try {
      const r = await window.krypt.terminal.autopilotRunNow();
      setRunMsg({ ok: r.ok, text: r.message });
      setAp(await window.krypt.terminal.autopilotStatus());
    } catch (e) {
      setRunMsg({ ok: false, text: userMessage(e) });
    }
  };

  const back = (): void => { if (step === 0) onBackOut?.(); else setStep((s) => s - 1); };
  const mode = config?.mcpTradeMode ?? 'paper';
  const lastRun = ap?.runs?.[0];

  return (
    <div data-testid="autopilot-quickstart">
      {step === 0 && (
        <>
          <StepHeader
            step={0} count={STEPS}
            title="Which AI should run Autopilot?"
            subtitle="Cloud AIs need an API key and bill you per use. Local AIs run on this computer for free."
          />
          <div className="grid gap-2 sm:grid-cols-2">
            {PROVIDERS.map((p) => (
              <ChoiceCard
                key={p.id} testId={`provider-${p.id}`}
                selected={provider === p.id} onClick={() => setProvider(p.id)}
                title={<span className="inline-flex items-center gap-1.5">{p.needs === 'local' && <Cpu className="h-3.5 w-3.5" />}{p.name}</span>}
                badge={p.needs === 'local' ? <Badge>Free</Badge> : (status?.keys?.[p.id] ? <Badge>Key saved</Badge> : <Badge tone="muted">Needs key</Badge>)}
              >
                {p.blurb}
              </ChoiceCard>
            ))}
          </div>
          <StepFooter onBack={onBackOut ? back : undefined} onSkip={onSkip}>
            <GlassButton variant="primary" onClick={() => setStep(1)} data-testid="qs-next">
              Continue <ArrowRight className="h-4 w-4" />
            </GlassButton>
          </StepFooter>
        </>
      )}

      {step === 1 && (
        <>
          <StepHeader
            step={1} count={STEPS}
            title={info.needs === 'local' ? `Start ${info.name} on this computer` : `Connect your ${info.name} key`}
            subtitle={info.needs === 'local'
              ? 'No key and no bill. The market data never leaves your computer.'
              : 'Stored encrypted on this computer, never in settings, never in a log.'}
          />
          {info.needs === 'local' ? (
            <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm text-white/90">
              {(LOCAL_HOWTO[provider] ?? []).map((s) => <li key={s}>{s}</li>)}
            </ol>
          ) : (
            <div className="space-y-2">
              {hasKey && !replacing ? (
                <Callout tone="info" title={`A ${info.name} key is already saved.`}>
                  <button type="button" className="text-krypt-purple hover:underline" onClick={() => setReplacing(true)}>
                    Use a different key
                  </button>
                </Callout>
              ) : (
                <div className="flex gap-2">
                  <input
                    data-testid="ai-key-input"
                    type="password"
                    value={draft}
                    autoComplete="off"
                    spellCheck={false}
                    placeholder={`Paste your ${info.name} API key (${info.keyHint ?? ''})`}
                    onChange={(e) => setDraft(e.target.value)}
                    className="krypt-input min-w-0 flex-1 font-mono"
                  />
                  <GlassButton variant="primary" disabled={busy || !draft.trim()} onClick={() => void saveKeyAndTest()} data-testid="ai-key-save">
                    {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} Save &amp; test
                  </GlassButton>
                </div>
              )}
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" className="krypt-btn-default" onClick={() => void window.krypt.app.openExternal(info.getUrl)}>
              <ExternalLink className="h-4 w-4" /> {info.getLabel}
            </button>
            {(info.needs === 'local' || hasKey) && (
              <button type="button" className="krypt-btn-default" disabled={checking} onClick={() => void runCheck(provider)} data-testid="ai-check">
                {checking ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
                {info.needs === 'local' ? 'Check again' : 'Test connection'}
              </button>
            )}
          </div>
          {checking && <p className="mt-2 text-xs text-krypt-muted">Checking… (a free call: it lists models, it doesn&apos;t run one)</p>}
          {check && (
            <div className="mt-3">
              <Callout tone={check.ok ? 'ok' : 'error'} testId="ai-check-result"
                title={check.ok ? `${info.name} is connected.` : `${info.name} isn't ready yet.`}>
                {check.message}
              </Callout>
            </div>
          )}
          {check?.ok && models.length > 0 && (
            <div className="mt-3">
              <label className="krypt-label">Model</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="krypt-input"
              >
                <option value="">
                  {provider === 'lmstudio' ? 'Whichever model LM Studio has loaded' : `Recommended: ${defaultModel || 'provider default'}`}
                </option>
                {models.map((m) => (
                  <option key={m.id} value={m.id} disabled={m.tools === false}>
                    {m.id}{m.tools === false ? ' (cannot use tools)' : ''}
                    {status?.prices?.[m.id] ? ` · $${status.prices[m.id].inPerMTok}/$${status.prices[m.id].outPerMTok} per M tokens` : ''}
                  </option>
                ))}
              </select>
              <p className="krypt-help">Autopilot only works through tools, so the model must be able to call them.</p>
            </div>
          )}
          <StepFooter onBack={back} onSkip={onSkip}>
            <GlassButton variant="primary" disabled={!check?.ok} onClick={() => setStep(2)} data-testid="qs-next">
              Continue <ArrowRight className="h-4 w-4" />
            </GlassButton>
          </StepFooter>
        </>
      )}

      {step === 2 && (
        <>
          <StepHeader
            step={2} count={STEPS}
            title="What should it do each run?"
            subtitle="Pick a mission. You can edit the words, now or later."
          />
          <div className="grid gap-2 sm:grid-cols-2">
            {MISSIONS.map((m) => (
              <ChoiceCard
                key={m.id} testId={`mission-${m.id}`}
                selected={missionId === m.id}
                onClick={() => { setMissionId(m.id); setMission(m.text); }}
                title={m.title}
              >
                {m.blurb}
              </ChoiceCard>
            ))}
          </div>
          <label className="krypt-label mt-3">The mission, in its own words</label>
          <textarea
            data-testid="mission-text"
            value={mission}
            onChange={(e) => { setMission(e.target.value.slice(0, MISSION_MAX)); setMissionId('custom'); }}
            rows={5}
            className="krypt-input resize-y text-xs leading-relaxed"
          />
          <p className="krypt-help">
            A mission is an instruction, not a rail. What actually limits Autopilot: paper mode, no
            buy without a forecast, an edge that must clear Kalshi&apos;s fee, and your caps.
          </p>
          <StepFooter onBack={back} onSkip={onSkip}>
            <GlassButton variant="primary" disabled={!mission.trim()} onClick={() => setStep(3)} data-testid="qs-next">
              Continue <ArrowRight className="h-4 w-4" />
            </GlassButton>
          </StepFooter>
        </>
      )}

      {step === 3 && (
        <>
          <StepHeader
            step={3} count={STEPS}
            title="How much should it run?"
            subtitle="These are hard limits, checked before every call. You can change them any time."
          />
          <div className="space-y-2">
            {BUDGETS.map((b) => (
              <ChoiceCard
                key={b.id} testId={`budget-${b.id}`}
                selected={budgetId === b.id} onClick={() => setBudgetId(b.id)}
                title={b.label}
                badge={b.id === 'light' ? <Badge>Start here</Badge> : undefined}
              >
                <div>{b.blurb}</div>
                <div className="mt-0.5 text-[11px] text-krypt-dim">
                  Every {b.intervalMin >= 60 ? `${b.intervalMin / 60} h` : `${b.intervalMin} min`} · up to {b.maxRunsPerDay} runs a day
                  · {fmtNum(b.dailyTokenBudget)} tokens a day · {b.maxSteps} tool calls a run
                </div>
                <div className="mt-0.5 text-[11px] text-white/80">
                  {costLine({ provider, model: effectiveModel, budget: b, prices: status?.prices })}
                </div>
              </ChoiceCard>
            ))}
          </div>
          <StepFooter onBack={back} onSkip={onSkip}>
            <GlassButton variant="primary" onClick={() => setStep(4)} data-testid="qs-next">
              Continue <ArrowRight className="h-4 w-4" />
            </GlassButton>
          </StepFooter>
        </>
      )}

      {step === 4 && (
        <>
          <StepHeader
            step={4} count={STEPS}
            title="Turn it on, on paper"
            subtitle="Paper means real Kalshi order books and imaginary money. This never turns on live trading."
          />
          <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 rounded-xl border border-krypt-border bg-krypt-surface2 p-3 text-xs">
            <dt className="text-krypt-muted">AI</dt>
            <dd className="text-white">{info.name} · <span className="font-mono">{effectiveModel || 'default'}</span></dd>
            <dt className="text-krypt-muted">Mission</dt>
            <dd className="text-white">{MISSIONS.find((m) => m.id === missionId)?.title ?? 'Your own'}</dd>
            <dt className="text-krypt-muted">Budget</dt>
            <dd className="text-white">
              {budget.label}: up to {budget.maxRunsPerDay} runs and {fmtNum(budget.dailyTokenBudget)} tokens a day
            </dd>
            <dt className="text-krypt-muted">Cost</dt>
            <dd className="text-white">{costLine({ provider, model: effectiveModel, budget, prices: status?.prices })}</dd>
            <dt className="text-krypt-muted">Trading</dt>
            <dd className="text-white">Paper (imaginary money)</dd>
          </dl>
          {agents.length > 1 && (
            <div className="mt-3">
              <AgentPicker
                agents={agents} value={agentId} onChange={setAgentId} testId="qs-agent"
                hint="Autopilot follows this agent's guide and is held to its rules. Its forecasts count on that agent's record."
              />
            </div>
          )}
          <div className="mt-3 space-y-2">
            {mode === 'live' && (
              <Callout tone="warn" title="Agent trading is LIVE right now." testId="qs-live-warning">
                Autopilot uses the same trading mode as your connected agents, so this switches ALL
                agents back to Paper. You can switch live back on from the AI Agents page.
              </Callout>
            )}
            {mode === 'off' && (
              <Callout tone="info">Agent trading is off right now. This sets it to Paper.</Callout>
            )}
            {info.needs === 'key' && (
              <Callout tone="info">
                Each run is billed to your {info.name} account. Autopilot stops for the day when it
                reaches the budget above.
              </Callout>
            )}
            {error && <Callout tone="error">{error}</Callout>}
          </div>
          <StepFooter onBack={back} onSkip={onSkip} skipLabel="Not now">
            <GlassButton variant="primary" disabled={busy} onClick={() => void turnOn()} data-testid="qs-turn-on">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />} Turn on Autopilot (paper)
            </GlassButton>
          </StepFooter>
        </>
      )}

      {step === 5 && (
        <>
          <StepHeader step={5} count={STEPS} title="Autopilot is on" subtitle="It runs on paper, on its schedule, inside its budget." />
          <div className="space-y-2" data-testid="qs-done">
            <Callout tone="ok" title="Switched on, paper mode.">
              {ap?.running
                ? `Running now: step ${ap.step}.`
                : ap?.nextRunAt
                  ? `First scheduled run around ${fmtTimeShort(ap.nextRunAt)}. Or run it now and watch.`
                  : 'Run it now to see what it does.'}
            </Callout>
            {ap?.blockedReason && <Callout tone="warn">Next run will not start: {ap.blockedReason}</Callout>}
            {runMsg && <Callout tone={runMsg.ok ? 'info' : 'warn'}>{runMsg.text}</Callout>}
            {lastRun && (
              <div className="rounded-xl border border-krypt-border bg-krypt-surface2 p-3 text-xs">
                <div className="mb-1 flex items-center gap-2 text-krypt-muted">
                  <span className={cls('uppercase tracking-wider', lastRun.status === 'error' ? 'text-krypt-loss' : lastRun.status === 'running' ? 'text-krypt-purple' : 'text-krypt-win')}>
                    {lastRun.status}
                  </span>
                  <span>{fmtTimeShort(lastRun.startedAt)}</span>
                  <span>{lastRun.steps} tool calls</span>
                </div>
                <p className="line-clamp-6 whitespace-pre-wrap text-white/85">
                  {lastRun.error ?? (lastRun.summary || 'Working…')}
                </p>
              </div>
            )}
          </div>
          <StepFooter>
            <button type="button" className="krypt-btn-default" disabled={!!ap?.running} onClick={() => void runNow()} data-testid="qs-run-now">
              {ap?.running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Run now
            </button>
            <GlassButton variant="primary" onClick={() => onDone?.()} data-testid="qs-done-btn">
              Done <ArrowRight className="h-4 w-4" />
            </GlassButton>
          </StepFooter>
        </>
      )}
    </div>
  );
}
