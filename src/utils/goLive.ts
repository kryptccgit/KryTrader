import type { CredentialsStatusAll, TraderConfig } from '@shared/types';
import type { AgentPaperSummary, ForecastScoreboard, PaperBook } from '@shared/market';
import { agentsOf, type McpAgent } from '@shared/agents';


type Cfg = Partial<TraderConfig> | null | undefined;


export interface AgentCaps {
  mcpMaxOrderUsd: number;
  mcpDailySpendUsd: number;
  mcpMaxPositions: number;
  mcpDailyLossUsd: number;
}

export const CAP_KEYS = [
  'mcpMaxOrderUsd', 'mcpDailySpendUsd', 'mcpMaxPositions', 'mcpDailyLossUsd',
] as const satisfies readonly (keyof AgentCaps)[];

export const STARTER_CAPS: Readonly<AgentCaps> = Object.freeze({
  mcpMaxOrderUsd: 5,
  mcpDailySpendUsd: 20,
  mcpMaxPositions: 3,
  mcpDailyLossUsd: 10,
});

const CAP_DEFAULTS: Readonly<AgentCaps> = {
  mcpMaxOrderUsd: 25, mcpDailySpendUsd: 100, mcpMaxPositions: 10, mcpDailyLossUsd: 50,
};

export function currentCaps(c: Cfg): AgentCaps {
  return {
    mcpMaxOrderUsd: c?.mcpMaxOrderUsd ?? CAP_DEFAULTS.mcpMaxOrderUsd,
    mcpDailySpendUsd: c?.mcpDailySpendUsd ?? CAP_DEFAULTS.mcpDailySpendUsd,
    mcpMaxPositions: c?.mcpMaxPositions ?? CAP_DEFAULTS.mcpMaxPositions,
    mcpDailyLossUsd: c?.mcpDailyLossUsd ?? CAP_DEFAULTS.mcpDailyLossUsd,
  };
}

export function starterCapsPatch(): Partial<TraderConfig> {
  return { ...STARTER_CAPS };
}

export function capsProblem(caps: AgentCaps): string | null {
  const money = (v: number): boolean => Number.isFinite(v) && v >= 1;
  if (!money(caps.mcpMaxOrderUsd)) return 'Max per order must be at least $1.';
  if (!money(caps.mcpDailySpendUsd)) return 'Max spend per day must be at least $1.';
  if (!money(caps.mcpDailyLossUsd)) return 'Daily loss stop must be at least $1.';
  if (!Number.isInteger(caps.mcpMaxPositions) || caps.mcpMaxPositions < 1 || caps.mcpMaxPositions > 200) {
    return 'Max open positions must be a whole number from 1 to 200.';
  }
  return null;
}


export type RecordVerdict = 'unavailable' | 'none' | 'too-few' | 'no-edge' | 'worse' | 'beats';

export interface AgentRecord {
  verdict: RecordVerdict;
  forecasts: number | null;
  settled: number;
  minScored: number;
  skill: number | null;
  paperPnlUsd: number | null;
  tone: 'good' | 'warn' | 'bad';
  headline: string;
  notes: string[];
  needsAck: boolean;
}

const usd = (v: number): string => `$${Math.abs(v).toFixed(2)}`;

export function agentRecord(board: ForecastScoreboard | null, paper: PaperBook | null): AgentRecord {
  const paperPnlUsd = paperPnl(paper);
  const notes: string[] = [];
  if (paper === null) notes.push('Paper book not loaded, so paper P&L is unknown.');
  else if (paperPnlUsd === null) notes.push('Paper P&L unknown: a paper position has no bid to mark it at.');
  else if (paperPnlUsd < 0) notes.push(`The paper book is DOWN ${usd(paperPnlUsd)} (realised + open, net of fees).`);

  const minScored = board?.minScored ?? 30;
  const base = { minScored, paperPnlUsd, notes };
  if (!board) {
    return {
      ...base, verdict: 'unavailable', forecasts: null, settled: 0, skill: null, tone: 'bad',
      headline: 'The scoreboard is unavailable, so there is no evidence your agent beats the market.',
      needsAck: true,
    };
  }
  const row = board.bySource.find((r) => r.source === 'mcp') ?? null;
  const forecasts = board.byForecaster
    ? board.byForecaster.filter((f) => f.source === 'mcp').reduce((a, f) => a + f.total, 0)
    : null;
  const settled = row?.nPaired ?? 0;
  const skill = row?.skill ?? null;
  const rest = { ...base, forecasts, settled, skill };

  if (forecasts === 0) {
    return {
      ...rest, verdict: 'none', tone: 'bad', needsAck: true,
      headline: 'Your agents have not recorded a single forecast yet. There is no evidence they beat the market.',
    };
  }
  const v = row?.verdict ?? 'too-few';
  if (v === 'too-few' || settled < minScored) {
    return {
      ...rest, verdict: 'too-few', tone: 'warn', needsAck: true,
      headline: `Not enough settled forecasts yet to tell if it beats the market (${settled} of ${minScored} needed).`,
    };
  }
  if (v === 'market-better') {
    return {
      ...rest, verdict: 'worse', tone: 'bad', needsAck: true,
      headline: `So far it does NOT beat the market price: the market was more accurate (n=${settled}).`,
    };
  }
  if (v === 'indistinguishable') {
    return {
      ...rest, verdict: 'no-edge', tone: 'warn', needsAck: true,
      headline: `So far it does NOT beat the market price: no measurable difference (n=${settled}).`,
    };
  }
  const losing = paperPnlUsd !== null && paperPnlUsd < 0;
  return {
    ...rest, verdict: 'beats', tone: losing ? 'warn' : 'good', needsAck: losing || paper === null || paperPnlUsd === null,
    headline: `So far it beats the market (n=${settled}). Past markets, not a promise.`,
  };
}

export function agentRecordFor(
  board: ForecastScoreboard | null, paper: AgentPaperSummary | null | undefined, agentId: string,
): AgentRecord {
  const traded = !!paper && paper.fills > 0;
  const paperPnlUsd = traded && paper.unrealizedUsd !== null
    ? paper.realizedUsd + paper.unrealizedUsd : null;
  const notes: string[] = [];
  if (!traded) notes.push('No paper trades yet.');
  else if (paperPnlUsd === null) notes.push('Paper P&L unknown: a position has no bid to mark it at.');
  else if (paperPnlUsd < 0) notes.push(`Paper is DOWN ${usd(paperPnlUsd)} (realised + open, net of fees).`);
  const minScored = board?.minScored ?? 30;
  const base = { minScored, paperPnlUsd, notes };
  if (!board || !board.byAgent) {
    return {
      ...base, verdict: 'unavailable', forecasts: null, settled: 0, skill: null, tone: 'bad',
      headline: 'No scoreboard for this agent.', needsAck: true,
    };
  }
  const row = board.byAgent.find((r) => r.agentId === agentId) ?? null;
  const forecasts = row?.total ?? 0;
  const settled = row?.nPaired ?? 0;
  const skill = row?.skill ?? null;
  const rest = { ...base, forecasts, settled, skill };
  if (!row || forecasts === 0) {
    return { ...rest, verdict: 'none', tone: 'bad', needsAck: true, headline: 'No forecasts yet.' };
  }
  if (row.verdict === 'too-few' || settled < minScored) {
    return { ...rest, verdict: 'too-few', tone: 'warn', needsAck: true, headline: `Too few settled (${settled} of ${minScored}).` };
  }
  if (row.verdict === 'market-better') {
    return { ...rest, verdict: 'worse', tone: 'bad', needsAck: true, headline: `The market beat it (n=${settled}).` };
  }
  if (row.verdict === 'indistinguishable') {
    return { ...rest, verdict: 'no-edge', tone: 'warn', needsAck: true, headline: `No measurable edge (n=${settled}).` };
  }
  const losing = paperPnlUsd !== null && paperPnlUsd < 0;
  return {
    ...rest, verdict: 'beats', tone: losing ? 'warn' : 'good', needsAck: losing,
    headline: `Beat the market so far (n=${settled}). Not a promise.`,
  };
}

function paperPnl(paper: PaperBook | null): number | null {
  if (!paper) return null;
  let unreal = 0;
  for (const p of paper.positions) {
    if (p.unrealizedUsd === null) return null;
    unreal += p.unrealizedUsd;
  }
  return paper.realizedUsd + unreal;
}


export interface KeyVerify {
  ok: boolean;
  message: string;
  fingerprint: string;
  balanceUsd?: number | null;
}


export type StepState = 'ok' | 'warn' | 'apply' | 'block';
export type StepId = 'keys' | 'record' | 'agents' | 'caps' | 'approval' | 'env';
export type AccountStepId = 'keys' | 'engines' | 'ack';

export interface GoLiveStep {
  id: StepId;
  state: StepState;
  title: string;
  detail: string;
}

export interface GoLiveInput {
  config: Cfg;
  creds: CredentialsStatusAll | null;
  verify: KeyVerify | null;
  record: AgentRecord;
  recordAck: boolean;
  caps: AgentCaps;
  approval: boolean;
  approvalOffAck: boolean;
  liveAgentIds: string[];
}

export interface GoLiveChecklist {
  steps: GoLiveStep[];
  ready: boolean;
}

export function goLiveChecklist(i: GoLiveInput): GoLiveChecklist {
  const steps: GoLiveStep[] = [
    keysStep(i), recordStep(i), agentsStep(i), capsStep(i), approvalStep(i), envStep(i),
  ];
  return { steps, ready: steps.every((s) => s.state !== 'block') };
}

export function liveCandidates(c: Cfg): McpAgent[] {
  return agentsOf(c).filter((a) => a.enabled);
}

export function defaultLiveSelection(c: Cfg): string[] {
  const cands = liveCandidates(c);
  const already = cands.filter((a) => a.mode === 'live').map((a) => a.id);
  if (already.length) return already;
  return cands.length === 1 ? [cands[0].id] : [];
}

function selectedAgents(c: Cfg, ids: string[]): McpAgent[] {
  return liveCandidates(c).filter((a) => ids.includes(a.id));
}

function agentsStep({ config, liveAgentIds }: GoLiveInput): GoLiveStep {
  const base = { id: 'agents' as const, title: 'Which agents go live' };
  const sel = selectedAgents(config, liveAgentIds);
  if (!sel.length) {
    return { ...base, state: 'block', detail: 'Tick at least one agent. Unticked agents keep trading on paper.' };
  }
  const rest = liveCandidates(config).length - sel.length;
  return {
    ...base, state: 'ok',
    detail: `${sel.map((a) => a.name).join(', ')} ${sel.length === 1 ? 'goes' : 'go'} live`
      + (rest ? `; ${rest} other${rest === 1 ? '' : 's'} stay${rest === 1 ? 's' : ''} on paper.` : '.'),
  };
}

function keysStep({ creds, verify }: GoLiveInput): GoLiveStep {
  return keyState(creds, verify);
}

function keyState(creds: CredentialsStatusAll | null, verify: KeyVerify | null): GoLiveStep {
  const base = { id: 'keys' as const, title: 'Kalshi API key' };
  if (!creds) {
    return { ...base, state: 'block', detail: 'Key status is unavailable (is the backend running?).' };
  }
  const p = creds.production;
  if (!p?.hasApiKey || !p?.hasRsaKey) {
    return { ...base, state: 'block', detail: 'No Kalshi key saved. Add a key from kalshi.com on the API Keys page — Paper never needed one, Live does.' };
  }
  if (!verify || verify.fingerprint !== p.fingerprint) {
    return { ...base, state: 'block', detail: 'Saved, not verified yet. Verify makes one signed balance read on your Kalshi account.' };
  }
  if (!verify.ok) {
    return { ...base, state: 'block', detail: `Kalshi rejected this key: ${verify.message}` };
  }
  const bal = typeof verify.balanceUsd === 'number' ? ` · balance ${usd(verify.balanceUsd)}` : '';
  return { ...base, state: 'ok', detail: `Verified with Kalshi${bal}.` };
}

function recordStep({ record, recordAck }: GoLiveInput): GoLiveStep {
  const base = { id: 'record' as const, title: "Your agent's record", detail: record.headline };
  if (!record.needsAck) return { ...base, state: 'ok' };
  return { ...base, state: recordAck ? 'warn' : 'block' };
}

function capsStep({ caps }: GoLiveInput): GoLiveStep {
  const problem = capsProblem(caps);
  const base = { id: 'caps' as const, title: 'Caps' };
  if (problem) return { ...base, state: 'block', detail: problem };
  return {
    ...base, state: 'ok',
    detail: `${usd(caps.mcpMaxOrderUsd)}/order · ${usd(caps.mcpDailySpendUsd)}/day · ${caps.mcpMaxPositions} positions · stop after ${usd(caps.mcpDailyLossUsd)} lost in a day`,
  };
}

function approvalStep({ approval, approvalOffAck }: GoLiveInput): GoLiveStep {
  const base = { id: 'approval' as const, title: 'Approvals' };
  if (approval) return { ...base, state: 'ok', detail: 'Every live order waits for your approval.' };
  if (approvalOffAck) {
    return { ...base, state: 'warn', detail: 'OFF: orders that pass the rails are sent without asking you.' };
  }
  return { ...base, state: 'block', detail: 'Turning approvals off needs its own confirmation.' };
}

function envStep({ config }: GoLiveInput): GoLiveStep {
  const base = { id: 'env' as const, title: 'Account mode' };
  if (config?.accountMode === 'live') {
    return { ...base, state: 'ok', detail: 'The app is already Live.' };
  }
  return { ...base, state: 'apply', detail: 'In Paper. Go live switches the whole app to Live — every armed engine listed below becomes real money.' };
}


export interface AccountGoLiveInput {
  config: Cfg;
  creds: CredentialsStatusAll | null;
  verify: KeyVerify | null;
  armed: string[];
  ack: boolean;
}

export interface AccountGoLiveStep {
  id: AccountStepId;
  state: StepState;
  title: string;
  detail: string;
}

export function accountGoLiveChecklist(i: AccountGoLiveInput): { steps: AccountGoLiveStep[]; ready: boolean } {
  const keys = keyState(i.creds, i.verify);
  const engines: AccountGoLiveStep = i.armed.length
    ? { id: 'engines', state: 'warn', title: 'What starts using real money',
      detail: `${i.armed.length} armed: ${i.armed.join(' · ')}` }
    : { id: 'engines', state: 'ok', title: 'What starts using real money',
      detail: 'Nothing is armed to trade on its own. Orders you place yourself will use real funds.' };
  const ack: AccountGoLiveStep = i.ack
    ? { id: 'ack', state: 'ok', title: 'Real money', detail: 'You confirmed that Live orders spend your real Kalshi balance.' }
    : { id: 'ack', state: 'block', title: 'Real money', detail: 'Tick the box to confirm Live orders spend your real Kalshi balance.' };
  const steps: AccountGoLiveStep[] = [{ ...keys, id: 'keys' }, engines, ack];
  return { steps, ready: steps.every((s) => s.state !== 'block') };
}

export function accountGoLivePatch(): Partial<TraderConfig> {
  return { accountMode: 'live' };
}

export function backToPaperAccountPatch(): Partial<TraderConfig> {
  return { accountMode: 'paper' };
}


export interface GoLiveDraft {
  caps: AgentCaps;
  approval: boolean;
  approvalOffAck: boolean;
  liveAgentIds: string[];
}

export function goLivePatch(config: Cfg, draft: GoLiveDraft): Partial<TraderConfig> | null {
  if (capsProblem(draft.caps)) return null;
  const live = new Set(selectedAgents(config, draft.liveAgentIds).map((a) => a.id));
  if (!live.size) return null;
  const patch: Partial<TraderConfig> = { mcpTradeMode: 'live' };
  if (config?.accountMode !== 'live') patch.accountMode = 'live';
  const cur = currentCaps(config);
  for (const k of CAP_KEYS) {
    if (draft.caps[k] !== cur[k]) patch[k] = draft.caps[k];
  }
  patch.mcpLiveApproval = !(draft.approval === false && draft.approvalOffAck);
  patch.mcpAgents = agentsOf(config).map((a) => ({ ...a, mode: live.has(a.id) ? 'live' : 'paper' }));
  return patch;
}

export function goLiveAgentNames(config: Cfg, draft: Pick<GoLiveDraft, 'liveAgentIds'>): string[] {
  return selectedAgents(config, draft.liveAgentIds).map((a) => a.name);
}

export function backToPaperPatch(): Partial<TraderConfig> {
  return { mcpTradeMode: 'paper' };
}

export function goLiveSummary(draft: Omit<GoLiveDraft, 'liveAgentIds'> & { liveAgentIds?: string[] },
  agentNames: string[] = []): string {
  const ask = draft.approval || !draft.approvalOffAck
    ? 'each needing your approval'
    : 'WITHOUT asking you per order';
  const head = `Your agents can place real orders on Kalshi, up to ${usd(draft.caps.mcpDailySpendUsd)}/day `
    + `(${usd(draft.caps.mcpMaxOrderUsd)} per order, at most ${draft.caps.mcpMaxPositions} open positions, `
    + `buys stop after ${usd(draft.caps.mcpDailyLossUsd)} lost in a day), ${ask}.`;
  if (!agentNames.length) return head;
  return `${head} Live: ${agentNames.join(', ')}. Every other agent trades on paper, and each live `
    + 'agent\'s own rules and caps still apply on top.';
}

export function liveAgents(c: Cfg): McpAgent[] {
  if (c?.mcpTradeMode !== 'live') return [];
  return agentsOf(c).filter((a) => a.enabled && a.mode === 'live');
}

export function agentsLiveOnProduction(c: Cfg): boolean {
  return c?.accountMode === 'live' && liveAgents(c).length > 0;
}

export function noAgentReachable(c: Cfg): boolean {
  return !c?.mcpEnabled && !c?.autopilotEnabled;
}
