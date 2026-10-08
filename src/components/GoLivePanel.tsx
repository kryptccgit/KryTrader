import { useMemo, useState } from 'react';
import {
  AlertTriangle, ArrowRight, CheckCircle2, CircleDot, KeyRound, Loader2, ShieldCheck, X, XCircle,
} from 'lucide-react';
import type { AgentPaperSummary, ForecastScoreboard, PaperBook } from '@shared/market';
import type { TraderConfig } from '@shared/types';
import type { PageId } from '../App';
import { ConfirmDialog, DialogShell, NumberInput, Switch } from './common';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { cls, fmtUsd } from '../utils/format';
import { liveSwitchMessage } from '../utils/liveEngines';
import {
  agentRecord, agentRecordFor, agentsLiveOnProduction, backToPaperPatch, currentCaps,
  defaultLiveSelection, goLiveAgentNames, goLiveChecklist, goLivePatch, goLiveSummary,
  liveAgents, liveCandidates, noAgentReachable, STARTER_CAPS,
  type AgentCaps, type GoLiveStep, type KeyVerify, type StepState,
} from '../utils/goLive';
import { userMessage } from '../utils/errors';


const STATE_ICON: Record<StepState, { Icon: typeof CheckCircle2; tone: string; label: string }> = {
  ok: { Icon: CheckCircle2, tone: 'text-krypt-win', label: 'Ready' },
  warn: { Icon: AlertTriangle, tone: 'text-krypt-warn', label: 'Acknowledged' },
  apply: { Icon: CircleDot, tone: 'text-krypt-purple', label: 'Applied by Go live' },
  block: { Icon: XCircle, tone: 'text-krypt-loss', label: 'Needs you' },
};

const TONE = { good: 'text-krypt-win', warn: 'text-krypt-warn', bad: 'text-krypt-loss' } as const;

export function GoLivePanel({
  board, paper, paperByAgent = null, onClose, onNav,
}: {
  board: ForecastScoreboard | null;
  paper: PaperBook | null;
  paperByAgent?: Record<string, AgentPaperSummary> | null;
  onClose: () => void;
  onNav?: (p: PageId) => void;
}) {
  const { config, credentialsAll, backend, refresh } = useApp();
  const toast = useToast();
  const [verify, setVerify] = useState<KeyVerify | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [recordAck, setRecordAck] = useState(false);
  const [caps, setCaps] = useState<AgentCaps>(() => currentCaps(config));
  const [approval, setApproval] = useState(true);
  const [approvalOffAck, setApprovalOffAck] = useState(false);
  const [askNoApproval, setAskNoApproval] = useState(false);
  const [stage, setStage] = useState<'checklist' | 'confirm' | 'done'>(
    agentsLiveOnProduction(config) ? 'done' : 'checklist');
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<Partial<TraderConfig> | null>(null);

  const [liveAgentIds, setLiveAgentIds] = useState<string[]>(() => defaultLiveSelection(config));
  const candidates = useMemo(() => liveCandidates(config), [config]);

  const record = useMemo(() => agentRecord(board, paper), [board, paper]);
  const draft = { caps, approval, approvalOffAck, liveAgentIds };
  const list = goLiveChecklist({
    config, creds: credentialsAll, verify, record, recordAck, caps, approval, approvalOffAck,
    liveAgentIds,
  });
  const patch = goLivePatch(config, draft);
  const liveNames = goLiveAgentNames(config, draft);
  const prod = credentialsAll?.production;

  const runVerify = async (): Promise<void> => {
    if (!prod) return;
    setVerifying(true);
    try {
      const r = await window.krypt.credentials.test();
      setVerify({
        ok: r.ok,
        message: r.ok ? 'Connected to Kalshi' : (r.message || 'auth failed'),
        fingerprint: prod.fingerprint,
        balanceUsd: r.ok ? r.data?.balanceUsd ?? null : null,
      });
    } catch (e) {
      setVerify({ ok: false, message: userMessage(e), fingerprint: prod.fingerprint });
    } finally {
      setVerifying(false);
    }
  };

  const apply = async (): Promise<void> => {
    if (!patch || !list.ready) return;
    setApplying(true);
    try {
      await window.krypt.config.update(patch);
      await refresh.state();
      if (patch.accountMode) {
        await refresh.credentials();
        await refresh.account();
        await refresh.backend();
      }
      setApplied(patch);
      setStage('done');
      toast.warn('Agents are LIVE on your real Kalshi account.');
    } catch (e) {
      toast.error(`Go live failed: ${userMessage(e)}`);
    } finally {
      setApplying(false);
    }
  };

  const backToPaper = async (): Promise<void> => {
    try {
      await window.krypt.config.update(backToPaperPatch());
      await refresh.state();
      toast.success('Agents are back on paper. The account mode was left as it is.');
      onClose();
    } catch (e) {
      toast.error(userMessage(e));
    }
  };

  const envMessage = config && config.accountMode !== 'live' && patch
    ? liveSwitchMessage({ ...config, ...patch })
    : null;

  return (
    <DialogShell onClose={onClose} maxWidth="max-w-2xl">
      <div className="max-h-[82vh] overflow-y-auto pr-1" data-qa="golive-panel">
        <div className="mb-3 flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-krypt-loss" />
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-white">Go live</h3>
            <p className="mt-0.5 text-[11px] text-krypt-muted">
              Everything that decides whether an agent can spend real money, with its real state.
              Nothing is changed until the last button.
            </p>
          </div>
          <button onClick={onClose} className="krypt-btn-ghost p-1" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        {stage === 'done' && (
          <DoneView
            config={config}
            applied={applied}
            authOk={backend.authOk}
            onBackToPaper={() => void backToPaper()}
            onClose={onClose}
          />
        )}

        {stage === 'checklist' && (
          <div className="space-y-3">
            {list.steps.map((step, i) => (
              <StepRow key={step.id} n={i + 1} step={step} hideDetail={step.id === 'record'}>
                {step.id === 'keys' && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {prod?.hasApiKey && prod?.hasRsaKey && (
                      <button
                        onClick={() => void runVerify()}
                        disabled={verifying}
                        className="krypt-btn-default text-xs"
                        data-qa="golive-verify"
                      >
                        {verifying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
                        Verify
                      </button>
                    )}
                    <button
                      onClick={() => { onClose(); onNav?.('api'); }}
                      className="krypt-btn-ghost text-xs"
                      data-qa="golive-apikeys"
                    >
                      Open API Keys <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
                {step.id === 'record' && (
                  <RecordBlock record={record} ack={recordAck} onAck={setRecordAck} />
                )}
                {step.id === 'agents' && (
                  <div className="mt-2 space-y-1.5" data-qa="golive-agents">
                    {candidates.map((a) => {
                      const r = agentRecordFor(board, paperByAgent?.[a.id], a.id);
                      const on = liveAgentIds.includes(a.id);
                      return (
                        <label
                          key={a.id}
                          className={cls('flex cursor-pointer items-start gap-3 rounded-lg border p-2.5',
                            on ? 'border-krypt-loss/40 bg-krypt-loss/[0.06]' : 'border-white/[0.06] bg-white/[0.02]')}
                        >
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={(e) => setLiveAgentIds((ids) => (e.target.checked
                              ? [...ids, a.id] : ids.filter((x) => x !== a.id)))}
                            className="mt-1 h-4 w-4 accent-krypt-loss"
                            data-qa={`golive-agent-${a.id}`}
                          />
                          <span className="text-base leading-none">{a.emoji}</span>
                          <span className="min-w-0 flex-1">
                            <span className="block text-xs font-medium text-white">{a.name}</span>
                            <span className="block text-[11px] text-krypt-muted">
                              {r.forecasts === null ? '—' : r.forecasts} forecasts · {r.settled}/{r.minScored} settled
                              {' '}· skill {r.skill === null ? '—' : `${(r.skill * 100).toFixed(1)}%`}
                              {' '}· paper {fmtUsd(r.paperPnlUsd, { sign: true })}
                            </span>
                            <span className={cls('block text-[11px]', TONE[r.tone])}>{r.headline}</span>
                          </span>
                        </label>
                      );
                    })}
                    {candidates.length === 0 && (
                      <p className="text-[11px] text-krypt-loss">Every agent is switched off. Switch one on first.</p>
                    )}
                    <p className="text-[11px] text-krypt-dim">
                      Unticked agents trade paper. Each live agent&apos;s own rules and caps apply on top of the caps below.
                    </p>
                  </div>
                )}
                {step.id === 'caps' && (
                  <div className="mt-2">
                    <div className="grid gap-2 sm:grid-cols-4">
                      <CapInput label="Per order" prefix="$" value={caps.mcpMaxOrderUsd} min={1}
                        onChange={(v) => setCaps({ ...caps, mcpMaxOrderUsd: v })} />
                      <CapInput label="Spend per day" prefix="$" value={caps.mcpDailySpendUsd} min={1}
                        onChange={(v) => setCaps({ ...caps, mcpDailySpendUsd: v })} />
                      <CapInput label="Open positions" value={caps.mcpMaxPositions} min={1} max={200}
                        onChange={(v) => setCaps({ ...caps, mcpMaxPositions: Math.round(v) })} />
                      <CapInput label="Daily loss stop" prefix="$" value={caps.mcpDailyLossUsd} min={1}
                        onChange={(v) => setCaps({ ...caps, mcpDailyLossUsd: v })} />
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <button
                        onClick={() => setCaps({ ...STARTER_CAPS })}
                        className="krypt-btn-default text-xs"
                        data-qa="golive-starter"
                      >
                        Use starter caps
                      </button>
                      <span className="text-[11px] text-krypt-dim">
                        $5/order, $20/day, 3 positions, $10 daily loss. Written when you press Go live.
                      </span>
                    </div>
                  </div>
                )}
                {step.id === 'approval' && (
                  <div className="mt-2">
                    <p className="mb-2 text-[11px] text-krypt-muted">
                      Each live order waits for you to approve it (here, or by phone if remote
                      trading is on), is re-checked against the market when you approve, and
                      expires after 10 minutes.
                    </p>
                    <Switch
                      checked={approval}
                      onChange={(v) => {
                        if (v) { setApproval(true); setApprovalOffAck(false); } else setAskNoApproval(true);
                      }}
                      label="Ask me before each live order"
                    />
                  </div>
                )}
                {step.id === 'env' && envMessage && (
                  <pre className="mt-2 whitespace-pre-wrap rounded-lg border border-krypt-loss/30 bg-krypt-loss/5 p-3 font-sans text-[11px] leading-relaxed text-white/80">
                    {envMessage}
                  </pre>
                )}
              </StepRow>
            ))}

            <div className="flex items-center justify-end gap-2 pt-1">
              {!list.ready && (
                <span className="mr-auto text-[11px] text-krypt-loss" data-qa="golive-blocked">
                  {list.steps.filter((s) => s.state === 'block').map((s) => s.title).join(', ')} still
                  {list.steps.filter((s) => s.state === 'block').length === 1 ? ' needs' : ' need'} you.
                </span>
              )}
              <button onClick={onClose} className="krypt-btn-default text-xs">Cancel</button>
              <button
                onClick={() => setStage('confirm')}
                disabled={!list.ready || !patch}
                className="krypt-btn-danger text-xs"
                data-qa="golive-review"
              >
                Review &amp; go live
              </button>
            </div>
          </div>
        )}

        {stage === 'confirm' && patch && (
          <div className="space-y-3 text-xs leading-relaxed text-white/80" data-qa="golive-confirm">
            <p className="rounded-lg border border-krypt-loss/40 bg-krypt-loss/10 p-3 text-sm text-white" data-qa="golive-summary">
              {goLiveSummary(draft, liveNames)}
            </p>
            <ul className="list-disc space-y-1 pl-5 text-[11px] text-krypt-muted">
              {patch.accountMode && <li>Switch the whole app from Paper to <span className="text-krypt-loss">Live</span> (real money).</li>}
              <li>Set agent trade mode to <span className="text-krypt-loss">Live</span>.</li>
              <li>
                Live: <span className="text-krypt-loss">{liveNames.join(', ')}</span>.
                {candidates.length > liveNames.length && ' Every other agent is set to paper.'}
              </li>
              {(['mcpMaxOrderUsd', 'mcpDailySpendUsd', 'mcpMaxPositions', 'mcpDailyLossUsd'] as const)
                .filter((k) => k in patch)
                .map((k) => <li key={k}>Change {CAP_LABEL[k]} to {k === 'mcpMaxPositions' ? patch[k] : fmtUsd(patch[k] ?? null)}.</li>)}
              <li>
                Approvals {patch.mcpLiveApproval
                  ? 'ON: every order waits for you.'
                  : <span className="text-krypt-loss">OFF: orders are sent without asking you.</span>}
              </li>
              <li>Nothing else: the forecast-before-buy rule, minimum edge, terminal caps and permissions stay as they are.</li>
            </ul>
            {record.needsAck && (
              <p className={cls('text-[11px]', TONE[record.tone])}>
                You acknowledged: {record.headline}
              </p>
            )}
            {envMessage && (
              <pre className="whitespace-pre-wrap rounded-lg border border-krypt-loss/30 bg-krypt-loss/5 p-3 font-sans text-[11px] leading-relaxed text-white/80">
                {envMessage}
              </pre>
            )}
            {noAgentReachable(config) && (
              <p className="text-[11px] text-krypt-warn">
                No agent can reach the app yet: the MCP server and Autopilot are both off. Live mode
                waits until you connect one, and that one will be able to spend.
              </p>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <button onClick={() => setStage('checklist')} className="krypt-btn-default text-xs" disabled={applying}>
                Back
              </button>
              <button
                onClick={() => void apply()}
                disabled={applying || !list.ready}
                className="krypt-btn-danger text-xs"
                data-qa="golive-apply"
              >
                {applying && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Go live
              </button>
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={askNoApproval}
        title="Go live without approvals?"
        danger
        confirmLabel="Turn approvals off"
        onClose={() => setAskNoApproval(false)}
        onConfirm={() => { setAskNoApproval(false); setApproval(false); setApprovalOffAck(true); }}
        body={
          <div className="space-y-2">
            <p className="text-krypt-loss">
              Connected agents and Autopilot will send real-money orders the moment they pass the
              rails, with no approval step. A prompt-injected or simply wrong agent gets no second look.
            </p>
            <p>
              The forecast gate, the per-order, daily-spend and daily-loss caps, and the terminal&apos;s
              own caps still apply. You will still be told about every order.
            </p>
          </div>
        }
      />
    </DialogShell>
  );
}

const CAP_LABEL: Record<'mcpMaxOrderUsd' | 'mcpDailySpendUsd' | 'mcpMaxPositions' | 'mcpDailyLossUsd', string> = {
  mcpMaxOrderUsd: 'max per order',
  mcpDailySpendUsd: 'max spend per day',
  mcpMaxPositions: 'max open positions',
  mcpDailyLossUsd: 'the daily loss stop',
};

export function StepRow({
  n, step, hideDetail, children,
}: { n: number; step: { id: string; state: StepState; title: string; detail: string }; hideDetail?: boolean; children?: React.ReactNode }) {
  const { Icon, tone, label } = STATE_ICON[step.state];
  return (
    <div
      className={cls(
        'rounded-xl border p-3',
        step.state === 'block' ? 'border-krypt-loss/30 bg-krypt-loss/[0.04]' : 'border-white/[0.07] bg-white/[0.025]',
      )}
      data-qa={`golive-step-${step.id}`}
      data-state={step.state}
    >
      <div className="flex items-start gap-2">
        <Icon className={cls('mt-0.5 h-4 w-4 shrink-0', tone)} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-white">{n}. {step.title}</span>
            <span className={cls('text-[10px] uppercase tracking-wider', tone)}>{label}</span>
          </div>
          {!hideDetail && <p className="mt-0.5 text-[11px] text-krypt-muted">{step.detail}</p>}
          {children}
        </div>
      </div>
    </div>
  );
}

function RecordBlock({
  record, ack, onAck,
}: { record: ReturnType<typeof agentRecord>; ack: boolean; onAck: (v: boolean) => void }) {
  const stat = (label: string, value: string, tone?: string) => (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-krypt-dim">{label}</div>
      <div className={cls('font-mono text-sm', tone ?? 'text-white')}>{value}</div>
    </div>
  );
  return (
    <div className="mt-2">
      <div className="grid gap-2 sm:grid-cols-4">
        {stat('Forecasts made', record.forecasts === null ? '—' : String(record.forecasts))}
        {stat('Settled', `${record.settled} / ${record.minScored}`)}
        {stat('Skill vs market', record.skill === null ? '—' : `${(record.skill * 100).toFixed(1)}%`,
          record.skill === null ? undefined : record.skill > 0 ? 'text-krypt-win' : 'text-krypt-loss')}
        {stat('Paper P&L', fmtUsd(record.paperPnlUsd, { sign: true }),
          record.paperPnlUsd === null ? undefined : record.paperPnlUsd < 0 ? 'text-krypt-loss' : 'text-white')}
      </div>
      <p className={cls('mt-2 text-xs font-medium', TONE[record.tone])} data-qa="golive-verdict">
        {record.headline}
      </p>
      {record.notes.map((n) => (
        <p key={n} className="mt-1 text-[11px] text-krypt-warn">{n}</p>
      ))}
      {record.needsAck && (
        <label
          className={cls(
            'mt-2 flex items-start gap-3 rounded-lg border p-3',
            record.tone === 'bad' ? 'border-krypt-loss/40 bg-krypt-loss/5' : 'border-krypt-warn/40 bg-krypt-warn/5',
          )}
        >
          <input
            type="checkbox"
            checked={ack}
            onChange={(e) => onAck(e.target.checked)}
            className="mt-0.5 h-4 w-4 accent-krypt-loss"
            data-qa="golive-record-ack"
          />
          <span className="text-xs text-white/90">
            I understand nothing here shows my agent beats the market price, and I am choosing to
            let it trade real money anyway.
          </span>
        </label>
      )}
    </div>
  );
}

function CapInput({
  label, value, onChange, prefix, min, max,
}: { label: string; value: number; onChange: (v: number) => void; prefix?: string; min?: number; max?: number }) {
  return (
    <div>
      <span className="krypt-label">{label}</span>
      <NumberInput value={value} onChange={onChange} prefix={prefix} min={min} max={max} />
    </div>
  );
}

function DoneView({
  config, applied, authOk, onBackToPaper, onClose,
}: {
  config: Partial<TraderConfig> | null;
  applied: Partial<TraderConfig> | null;
  authOk: boolean;
  onBackToPaper: () => void;
  onClose: () => void;
}) {
  const live = agentsLiveOnProduction(config);
  const caps = currentCaps(config);
  return (
    <div className="space-y-3 text-xs" data-qa="golive-done">
      <div className={cls(
        'rounded-lg border p-3',
        live ? 'border-krypt-loss/50 bg-krypt-loss/10' : 'border-krypt-warn/40 bg-krypt-warn/5',
      )}>
        <p className="text-sm font-medium text-white">
          {live ? 'Agents are LIVE on your real Kalshi account.' : 'Applied, but agents are not live on real money yet.'}
        </p>
        {live && (
          <p className="mt-1 text-[11px] text-krypt-loss">
            Live: {liveAgents(config).map((a) => a.name).join(', ')}. Every other agent trades paper.
          </p>
        )}
        <p className="mt-1 text-[11px] text-krypt-muted">
          Up to {fmtUsd(caps.mcpDailySpendUsd)}/day, {fmtUsd(caps.mcpMaxOrderUsd)} per order,{' '}
          {caps.mcpMaxPositions} open positions, buys stop after {fmtUsd(caps.mcpDailyLossUsd)} lost in a day.
          Approvals are {config?.mcpLiveApproval === false ? <span className="text-krypt-loss">OFF</span> : 'ON'}.
        </p>
        {applied?.accountMode && (
          <p className={cls('mt-1 text-[11px]', authOk ? 'text-krypt-win' : 'text-krypt-warn')}>
            {authOk
              ? 'Switched the app to Live and connected.'
              : 'Switched the app to Live, but the backend has not confirmed the key yet. Check the API Keys page.'}
          </p>
        )}
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="krypt-btn-default text-xs">Close</button>
        <button onClick={onBackToPaper} className="krypt-btn-primary text-xs" data-qa="golive-back-to-paper">
          Back to paper
        </button>
      </div>
    </div>
  );
}
