import { useEffect, useState } from 'react';
import { ChevronDown, Loader2, Play, Sparkles } from 'lucide-react';
import type { AutopilotRun, AutopilotStatus } from '@shared/market';
import { Card, ConfirmDialog, Modal, NumberInput, Section, Switch } from './common';
import { AutopilotQuickstart } from './AutopilotQuickstart';
import { Caveat } from './terminal/atoms';
import { useApp } from '../state/AppStateProvider';
import { usePoll } from '../state/TerminalProvider';
import { useToast } from '../state/ToastProvider';
import { cls, fmtNum, fmtTimeShort, fmtUsd } from '../utils/format';
import { fmtTokens } from '../utils/stats';
import { agentsOf, DEFAULT_AGENT_ID } from '@shared/agents';
import { AgentPicker } from './agents/AgentPicker';
import { userMessage } from '../utils/errors';

const PLACEHOLDER =
  'e.g. Look through markets closing in the next few days. Read the rules, record honest '
  + 'forecasts, and trade only where the edge after fees clears the minimum. Keep sizes small.';

const STATUS_TONE: Record<AutopilotRun['status'], string> = {
  running: 'text-krypt-purple',
  ok: 'text-krypt-win',
  steps: 'text-krypt-muted',
  budget: 'text-krypt-warn',
  context: 'text-krypt-warn',
  stopped: 'text-krypt-muted',
  error: 'text-krypt-loss',
};

export function AutopilotPanel() {
  const { config, refresh } = useApp();
  const toast = useToast();
  const [arm, setArm] = useState(false);
  const [quick, setQuick] = useState(false);
  const [mission, setMission] = useState(config?.autopilotMission ?? '');
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { setMission(config?.autopilotMission ?? ''); }, [config?.autopilotMission]);

  const st = usePoll<AutopilotStatus>(() => window.krypt.terminal.autopilotStatus(), 5_000, []);
  const a = st.data;

  const patch = async (p: Record<string, unknown>): Promise<void> => {
    await window.krypt.config.update(p as never);
    await refresh.state();
    st.reload();
  };

  const runNow = async (): Promise<void> => {
    try {
      const res = await window.krypt.terminal.autopilotRunNow();
      if (res.ok) toast.success(res.message); else toast.warn(res.message);
      st.reload();
    } catch (e) {
      toast.error(userMessage(e));
    }
  };

  const lim = a?.limits;
  return (
    <Section
      title="Autopilot"
      description="The app runs an agent on a schedule with your AI analysis key. It gets exactly the tools and rails a connected client would."
    >
      {!config?.autopilotEnabled && (
        <div className="mb-3 flex flex-col items-start gap-3 rounded-xl border border-krypt-purple/40 bg-gradient-to-r from-krypt-indigo/10 via-krypt-purple/10 to-krypt-pink/10 p-4 md:flex-row md:items-center">
          <Sparkles className="h-5 w-5 shrink-0 text-krypt-purple" />
          <div className="flex-1 text-sm">
            <div className="font-medium text-white">New to Autopilot? Set it up in a few steps.</div>
            <div className="mt-0.5 text-xs text-krypt-muted">
              Pick an AI, add its key (or use a free local one), choose a mission and a budget.
              It starts on paper: real order books, imaginary money.
            </div>
          </div>
          <button type="button" className="krypt-btn-primary" onClick={() => setQuick(true)} data-testid="autopilot-quickstart-open">
            <Sparkles className="h-4 w-4" /> Quick setup
          </button>
        </div>
      )}
      <Card>
        <div className="grid gap-3 md:grid-cols-2">
          <Switch
            checked={!!config?.autopilotEnabled}
            onChange={(v) => { if (v) setArm(true); else void patch({ autopilotEnabled: false }); }}
            label="Run Autopilot on a schedule"
            description="Off by default. Switching it off also stops a run in progress at its next step."
          />
          <div className="flex items-center justify-end gap-3">
            <div className="text-right text-[11px] text-krypt-muted">
              <div>
                Model: <span className="font-mono text-white">{a?.model ?? '—'}</span>
                {' '}({a?.providerLabel ?? a?.provider ?? '—'}, from AI analysis settings)
              </div>
              <div>
                {a?.running
                  ? <span className="text-krypt-purple">Running — step {a.step}</span>
                  : a?.enabled && a.nextRunAt
                    ? `Next run ${fmtTimeShort(a.nextRunAt)}`
                    : 'Not scheduled'}
                {a && ` · ${a.toolCount} tools available`}
              </div>
            </div>
            <button onClick={() => void runNow()} disabled={!!a?.running} className="krypt-btn-default shrink-0 whitespace-nowrap">
              {a?.running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Run now
            </button>
            {config?.autopilotEnabled && (
              <button onClick={() => setQuick(true)} className="krypt-btn-ghost shrink-0 whitespace-nowrap" title="Walk through provider, mission and budget again">
                <Sparkles className="h-4 w-4" /> Quick setup
              </button>
            )}
          </div>
        </div>

        {a?.blockedReason && config?.autopilotEnabled && (
          <Caveat className="mt-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">
            Next run will not start: {a.blockedReason}
          </Caveat>
        )}
        {a?.lastError && (
          <Caveat className="mt-3 border-krypt-loss/40 bg-krypt-loss/5 text-krypt-loss">
            Last run failed: {a.lastError}
          </Caveat>
        )}

        <div className="mt-4 max-w-sm">
          <AgentPicker
            agents={agentsOf(config)}
            value={config?.autopilotAgentId ?? DEFAULT_AGENT_ID}
            onChange={(id) => void patch({ autopilotAgentId: id })}
            testId="autopilot-agent"
            hint="Its guide shapes each run and its rules bind every order, exactly as when it is connected from Cursor or Claude."
          />
        </div>

        <div className="mt-4">
          <span className="krypt-label">Mission</span>
          <textarea
            value={mission}
            onChange={(e) => setMission(e.target.value.slice(0, 2000))}
            onBlur={() => { if (mission !== (config?.autopilotMission ?? '')) void patch({ autopilotMission: mission }); }}
            rows={3}
            placeholder={PLACEHOLDER}
            className="krypt-input min-h-[72px] resize-y text-xs leading-relaxed"
          />
          <span className="krypt-hint">
            Standing instructions for every run. Saved when you click away. Blank uses the default above.
          </span>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <div>
            <span className="krypt-label">Every</span>
            <NumberInput suffix="min" value={config?.autopilotIntervalMin ?? 60} min={15} max={1440}
              onChange={(v) => void patch({ autopilotIntervalMin: Math.round(v) })} />
          </div>
          <div>
            <span className="krypt-label">Runs per day</span>
            <NumberInput value={config?.autopilotMaxRunsPerDay ?? 12} min={1} max={96}
              onChange={(v) => void patch({ autopilotMaxRunsPerDay: Math.round(v) })} />
            <span className="krypt-hint">{a ? `${a.today.runs} today` : ''}</span>
          </div>
          <div>
            <span className="krypt-label">Token budget / day</span>
            <NumberInput value={config?.autopilotDailyTokenBudget ?? 1_500_000} min={50_000} max={50_000_000}
              onChange={(v) => void patch({ autopilotDailyTokenBudget: Math.round(v) })} />
            <span className="krypt-hint">
              {a ? `${fmtNum(a.today.tokens)} used today` : ''}
              {a && ` · ${a.today.costUsd === null ? 'cost unknown (no published price)' : fmtUsd(a.today.costUsd)}`}
            </span>
          </div>
          <div>
            <span className="krypt-label">Tool calls per run</span>
            <NumberInput value={config?.autopilotMaxSteps ?? 15} min={3} max={40}
              onChange={(v) => void patch({ autopilotMaxSteps: Math.round(v) })} />
          </div>
        </div>
      </Card>

      {a && a.runs.length > 0 && (
        <Card className="mt-3" header={<span className="text-xs font-medium text-white">Runs</span>}>
          <div className="divide-y divide-krypt-border">
            {a.runs.map((r) => (
              <div key={r.id} className="py-2">
                <button
                  onClick={() => setOpen(open === r.id ? null : r.id)}
                  className="flex w-full items-center gap-3 text-left text-[11px]"
                >
                  <ChevronDown className={cls('h-3.5 w-3.5 text-krypt-dim transition-transform', open !== r.id && '-rotate-90')} />
                  <span className="w-20 text-krypt-muted">{fmtTimeShort(r.startedAt)}</span>
                  <span className={cls('w-16 uppercase tracking-wider', STATUS_TONE[r.status])}>{r.status}</span>
                  <span className="w-20 text-krypt-muted">{r.trigger}</span>
                  <span className="font-mono text-krypt-muted">{r.steps} steps</span>
                  <span className="font-mono text-krypt-muted" title={r.inputTokens === null && r.outputTokens === null
                    ? 'This provider reported no token usage for the run.' : undefined}>
                    {fmtTokens(r.inputTokens, r.outputTokens, r.tokensEstimated)}
                  </span>
                  <span className="font-mono text-krypt-muted">{fmtUsd(r.costUsd)}</span>
                  <span className="ml-2 truncate text-white/80">
                    {r.error ?? r.summary.split('\n')[0]}
                  </span>
                </button>
                {open === r.id && (
                  <div className="mt-2 space-y-2 pl-6 text-[11px] leading-relaxed">
                    {r.summary && <p className="whitespace-pre-wrap text-krypt-muted">{r.summary}</p>}
                    {r.tools.length > 0 && (
                      <ol className="space-y-0.5 font-mono text-[10px]">
                        {r.tools.map((t, i) => (
                          <li key={i} className={t.ok ? 'text-krypt-dim' : 'text-krypt-warn'}>
                            {i + 1}. {t.tool} — {t.brief.replace(/\s+/g, ' ').slice(0, 120)}
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Modal open={quick} onClose={() => setQuick(false)} maxWidth="max-w-2xl">
        <AutopilotQuickstart
          onDone={() => { setQuick(false); st.reload(); }}
          onSkip={() => setQuick(false)}
        />
      </Modal>

      <ConfirmDialog
        open={arm}
        title="Run an AI agent on a schedule?"
        confirmLabel="Turn on Autopilot"
        onClose={() => setArm(false)}
        onConfirm={() => { setArm(false); void patch({ autopilotEnabled: true }); }}
        body={
          <div className="space-y-2">
            <p>
              Every {lim?.intervalMin ?? config?.autopilotIntervalMin ?? 60} minutes the app will
              call {a?.model ?? 'your AI model'} with your own key, and you are billed for every
              run — up to {lim?.maxRunsPerDay ?? 12} runs and {fmtNum(lim?.dailyTokenBudget ?? 1_500_000)}{' '}
              tokens a day.
            </p>
            <p>
              It can do exactly what your AI Agents settings allow a connected client to do: the
              trading mode, caps, loss stop and permissions above all apply, and live orders still
              wait for your approval unless you turned that off.
            </p>
            <p>
              It runs as <span className="text-white">{a?.agentName ?? 'the agent you picked'}</span>:
              that agent&apos;s guide and rules apply to every run.
            </p>
          </div>
        }
      />
    </Section>
  );
}
