import { describe, expect, it } from 'vitest';
import type { CredentialsStatusAll, TraderConfig } from '@shared/types';
import type { ForecastScore, ForecastScoreboard, PaperBook } from '@shared/market';
import {
  agentRecord, agentRecordFor, agentsLiveOnProduction, backToPaperPatch, CAP_KEYS, currentCaps,
  defaultLiveSelection, goLiveAgentNames, goLiveChecklist, goLivePatch, goLiveSummary, liveAgents,
  liveCandidates, STARTER_CAPS, starterCapsPatch,
  type AgentCaps, type GoLiveInput,
} from '../src/utils/goLive';


const score = (p: Partial<ForecastScore>): ForecastScore => ({
  n: 0, nPaired: 0, brierAi: null, brierAiPaired: null, brierMarket: null, skill: null,
  diffMean: null, diffSe: null, verdict: 'too-few', ...p,
});

const board = (mcp: Partial<ForecastScore>, agentTotal: number | null = 40): ForecastScoreboard => ({
  totalForecasts: 100, pending: 10, resolved: 90, scoredMarkets: 80, minScored: 30,
  overall: score({ n: 80, nPaired: 80, verdict: 'ai-better', skill: 0.2 }),
  bySource: [
    { source: 'panel', ...score({ n: 80, nPaired: 80, verdict: 'ai-better', skill: 0.2 }) },
    { source: 'mcp', ...score(mcp) },
  ],
  buckets: [],
  byForecaster: agentTotal === null ? undefined : [
    { source: 'mcp', client: 'claude-code', model: null, total: agentTotal, pending: 0, lastAt: null, open: [], ...score(mcp) },
    { source: 'panel', client: null, model: null, total: 999, pending: 0, lastAt: null, open: [], ...score({}) },
  ],
  recent: [],
});

const paper = (realizedUsd: number, unreal: (number | null)[] = []): PaperBook => ({
  bankrollUsd: 1000, cashUsd: 1000, realizedUsd, fills: [],
  positions: unreal.map((u, i) => ({
    ticker: `T${i}`, title: null, side: 'yes', contracts: 1, avgCostCents: 50, costUsd: 0.5,
    markCents: u === null ? null : 50, unrealizedUsd: u,
  })),
});

const creds = (hasProd: boolean, fingerprint = 'fp1'): CredentialsStatusAll => ({
  current: 'paper',
  production: { hasApiKey: hasProd, hasRsaKey: hasProd, apiKeyPreview: hasProd ? 'y' : '', fingerprint: hasProd ? fingerprint : '' },
});

const paperCfg: Partial<TraderConfig> = {
  accountMode: 'paper', mcpTradeMode: 'paper', mcpEnabled: true,
  mcpMaxOrderUsd: 25, mcpDailySpendUsd: 100, mcpMaxPositions: 10, mcpDailyLossUsd: 50, mcpLiveApproval: true,
};

describe('agentRecord: the verdict thresholds', () => {
  it('says plainly when there is no scoreboard or no agent forecast', () => {
    const none = agentRecord(null, paper(0));
    expect(none.verdict).toBe('unavailable');
    expect(none.tone).toBe('bad');
    expect(none.needsAck).toBe(true);

    const zero = agentRecord(board({}, 0), paper(0));
    expect(zero.verdict).toBe('none');
    expect(zero.forecasts).toBe(0);
    expect(zero.headline).toMatch(/not recorded a single forecast/);
    expect(zero.needsAck).toBe(true);
  });

  it('reads the agent row, not the overall score the Analyse button earned', () => {
    const r = agentRecord(board({ n: 5, nPaired: 5, verdict: 'too-few' }), paper(0));
    expect(r.verdict).toBe('too-few');
    expect(r.forecasts).toBe(40);
    expect(r.headline).toBe('Not enough settled forecasts yet to tell if it beats the market (5 of 30 needed).');
    expect(r.tone).toBe('warn');
    expect(r.needsAck).toBe(true);
  });

  it('is "too few" below 30 settled markets, even if the backend claimed a winner', () => {
    const r = agentRecord(board({ n: 29, nPaired: 29, verdict: 'ai-better', skill: 0.5 }), paper(10));
    expect(r.verdict).toBe('too-few');
    expect(r.needsAck).toBe(true);
  });

  it('calls a two-standard-error tie and a loss what they are: NOT beating the market', () => {
    const tie = agentRecord(board({ n: 40, nPaired: 40, verdict: 'indistinguishable', skill: 0.01 }), paper(5));
    expect(tie.verdict).toBe('no-edge');
    expect(tie.headline).toBe('So far it does NOT beat the market price: no measurable difference (n=40).');
    expect(tie.needsAck).toBe(true);

    const worse = agentRecord(board({ n: 40, nPaired: 40, verdict: 'market-better', skill: -0.2 }), paper(5));
    expect(worse.verdict).toBe('worse');
    expect(worse.tone).toBe('bad');
    expect(worse.headline).toMatch(/does NOT beat the market price/);
    expect(worse.needsAck).toBe(true);
  });

  it('only a real win at n>=30 with a non-losing paper book needs no acknowledgement', () => {
    const win = agentRecord(board({ n: 35, nPaired: 35, verdict: 'ai-better', skill: 0.08 }), paper(12, [3]));
    expect(win.verdict).toBe('beats');
    expect(win.headline).toBe('So far it beats the market (n=35). Past markets, not a promise.');
    expect(win.paperPnlUsd).toBe(15);
    expect(win.needsAck).toBe(false);

    const losingPaper = agentRecord(board({ n: 35, nPaired: 35, verdict: 'ai-better' }), paper(-8, [2]));
    expect(losingPaper.verdict).toBe('beats');
    expect(losingPaper.notes.join(' ')).toMatch(/DOWN \$6\.00/);
    expect(losingPaper.needsAck).toBe(true);
  });

  it('never turns an unmarked paper position into $0', () => {
    const r = agentRecord(board({ n: 35, nPaired: 35, verdict: 'ai-better' }), paper(5, [1, null]));
    expect(r.paperPnlUsd).toBeNull();
    expect(r.needsAck).toBe(true);
  });

  it('shows no invented forecast count when the backend has no breakdown', () => {
    const r = agentRecord(board({ n: 3, nPaired: 3 }, null), paper(0));
    expect(r.forecasts).toBeNull();
    expect(r.verdict).toBe('too-few');
  });
});

describe('starter caps', () => {
  it('writes exactly the four caps and nothing else', () => {
    expect(starterCapsPatch()).toEqual({
      mcpMaxOrderUsd: 5, mcpDailySpendUsd: 20, mcpMaxPositions: 3, mcpDailyLossUsd: 10,
    });
    expect(Object.keys(starterCapsPatch()).sort()).toEqual([...CAP_KEYS].sort());
  });

  it('cannot be mutated by a caller', () => {
    expect(Object.isFrozen(STARTER_CAPS)).toBe(true);
    const p = starterCapsPatch();
    p.mcpMaxOrderUsd = 999;
    expect(STARTER_CAPS.mcpMaxOrderUsd).toBe(5);
  });

  it('shows the enforced default when a cap is missing from config', () => {
    expect(currentCaps({})).toEqual({
      mcpMaxOrderUsd: 25, mcpDailySpendUsd: 100, mcpMaxPositions: 10, mcpDailyLossUsd: 50,
    });
  });
});

describe('goLiveChecklist', () => {
  const caps = currentCaps(paperCfg);
  const winning = agentRecord(board({ n: 35, nPaired: 35, verdict: 'ai-better' }), paper(5));
  const input = (p: Partial<GoLiveInput> = {}): GoLiveInput => ({
    config: paperCfg, creds: creds(true), verify: { ok: true, message: 'ok', fingerprint: 'fp1', balanceUsd: 12 },
    record: winning, recordAck: false, caps, approval: true, approvalOffAck: false,
    liveAgentIds: ['default'], ...p,
  });
  const step = (i: GoLiveInput, id: string) => goLiveChecklist(i).steps.find((s) => s.id === id)!;

  it('blocks at step 1 with no Kalshi key (the QA profile, and any no-account Paper user)', () => {
    const l = goLiveChecklist(input({ creds: creds(false), verify: null }));
    expect(l.ready).toBe(false);
    expect(l.steps[0].id).toBe('keys');
    expect(l.steps[0].state).toBe('block');
    expect(l.steps[0].detail).toMatch(/No Kalshi key saved/);
  });

  it('wants a Verify of the CURRENT key, and a passing one', () => {
    expect(step(input({ verify: null }), 'keys').state).toBe('block');
    expect(step(input({ creds: creds(true, 'fp2') }), 'keys').state).toBe('block');
    const bad = step(input({ verify: { ok: false, message: '401', fingerprint: 'fp1' } }), 'keys');
    expect(bad.state).toBe('block');
    expect(bad.detail).toMatch(/rejected.*401/);
    expect(step(input(), 'keys').state).toBe('ok');
    expect(step(input({ creds: null }), 'keys').state).toBe('block');
  });

  it('a weak record blocks until acknowledged, then reads as a warning — never ok', () => {
    const weak = agentRecord(board({ n: 2, nPaired: 2 }), paper(0));
    expect(step(input({ record: weak }), 'record').state).toBe('block');
    expect(step(input({ record: weak, recordAck: true }), 'record').state).toBe('warn');
    expect(step(input({ record: weak, recordAck: true }), 'record').detail).toBe(weak.headline);
    expect(step(input(), 'record').state).toBe('ok');
  });

  it('approval off counts only through its own confirm', () => {
    expect(step(input(), 'approval').state).toBe('ok');
    expect(step(input({ approval: false }), 'approval').state).toBe('block');
    expect(step(input({ approval: false, approvalOffAck: true }), 'approval').state).toBe('warn');
  });

  it('refuses caps the backend would silently clamp', () => {
    const bad = (c: Partial<AgentCaps>) => step(input({ caps: { ...caps, ...c } }), 'caps').state;
    expect(bad({ mcpMaxOrderUsd: 0 })).toBe('block');
    expect(bad({ mcpDailySpendUsd: Number.NaN })).toBe('block');
    expect(bad({ mcpMaxPositions: 2.5 })).toBe('block');
    expect(bad({ mcpMaxPositions: 201 })).toBe('block');
    expect(bad({ mcpDailyLossUsd: 0.5 })).toBe('block');
    expect(bad({})).toBe('ok');
  });

  it('marks the account mode as applied by Go live in Paper, done when Live', () => {
    expect(step(input(), 'env').state).toBe('apply');
    expect(step(input({ config: { ...paperCfg, accountMode: 'live' } }), 'env').state).toBe('ok');
  });

  it('is ready only when nothing blocks', () => {
    expect(goLiveChecklist(input()).ready).toBe(true);
    expect(goLiveChecklist(input({ verify: null })).ready).toBe(false);
  });
});

describe('goLivePatch: the one write', () => {
  const caps = currentCaps(paperCfg);
  const ALLOWED = new Set<string>(['accountMode', 'mcpTradeMode', 'mcpLiveApproval', 'mcpAgents', ...CAP_KEYS]);
  const D = { liveAgentIds: ['default'] };

  it('switches the account mode and trade mode with approvals ON, and writes no unchanged cap', () => {
    const p = goLivePatch(paperCfg, { caps, approval: true, approvalOffAck: false, ...D });
    const { mcpAgents, ...rest } = p!;
    expect(rest).toEqual({ accountMode: 'live', mcpTradeMode: 'live', mcpLiveApproval: true });
    expect(mcpAgents?.map((a) => [a.id, a.mode])).toEqual([['default', 'live']]);
  });

  it('never sets anything outside what the summary showed', () => {
    const armedElsewhere: Partial<TraderConfig> = {
      ...paperCfg, mcpEnabled: false, autopilotEnabled: false, enableTrading: false, mcpAllowLiveSwitches: false,
    };
    const p = goLivePatch(armedElsewhere, { caps: { ...STARTER_CAPS }, approval: true, approvalOffAck: false, ...D })!;
    for (const k of Object.keys(p)) expect(ALLOWED.has(k)).toBe(true);
    expect(p).not.toHaveProperty('mcpEnabled');
    expect(p).not.toHaveProperty('autopilotEnabled');
    expect(p).not.toHaveProperty('enableTrading');
    expect(p).not.toHaveProperty('mcpMinEdgeCents');
    expect(p).toMatchObject({ ...STARTER_CAPS });
  });

  it('keeps approvals on unless they were turned off through the confirm', () => {
    const off = { ...paperCfg, mcpLiveApproval: false };
    expect(goLivePatch(off, { caps, approval: true, approvalOffAck: false, ...D })!.mcpLiveApproval).toBe(true);
    expect(goLivePatch(paperCfg, { caps, approval: false, approvalOffAck: false, ...D })!.mcpLiveApproval).toBe(true);
    expect(goLivePatch(paperCfg, { caps, approval: false, approvalOffAck: true, ...D })!.mcpLiveApproval).toBe(false);
  });

  it('does not rewrite the account mode when already Live', () => {
    const p = goLivePatch({ ...paperCfg, accountMode: 'live' }, { caps, approval: true, approvalOffAck: false, ...D })!;
    expect(p).not.toHaveProperty('accountMode');
  });

  it('writes nothing at all with invalid caps', () => {
    expect(goLivePatch(paperCfg, { caps: { ...caps, mcpMaxOrderUsd: 0 }, approval: true, approvalOffAck: false, ...D })).toBeNull();
  });

  it('summarises the spend and the approval honestly', () => {
    expect(goLiveSummary({ caps: { ...STARTER_CAPS }, approval: true, approvalOffAck: false, ...D })).toBe(
      'Your agents can place real orders on Kalshi, up to $20.00/day ($5.00 per order, '
      + 'at most 3 open positions, buys stop after $10.00 lost in a day), each needing your approval.');
    expect(goLiveSummary({ caps, approval: false, approvalOffAck: true })).toMatch(/WITHOUT asking you per order/);
    expect(goLiveSummary({ caps, approval: false, approvalOffAck: false })).toMatch(/each needing your approval/);
  });
});


const sam = { id: 'sam1', name: 'Sports Sam', mode: 'paper', enabled: true, rules: {} };
const res = { id: 'res1', name: 'Careful Researcher', mode: 'live', enabled: true, rules: {} };
const off = { id: 'off1', name: 'Switched Off', mode: 'live', enabled: false, rules: {} };
const multiCfg = {
  ...paperCfg,
  mcpAgents: [{ id: 'default', name: 'Default', mode: 'paper' }, sam, res, off],
} as unknown as Partial<TraderConfig>;

describe('Go live: which agents go live', () => {
  const caps = currentCaps(paperCfg);
  const input = (ids: string[]): GoLiveInput => ({
    config: multiCfg, creds: creds(true), verify: { ok: true, message: 'ok', fingerprint: 'fp1' },
    record: agentRecord(board({ n: 35, nPaired: 35, verdict: 'ai-better' }), paper(5)), recordAck: false,
    caps, approval: true, approvalOffAck: false, liveAgentIds: ids,
  });
  const step = (ids: string[]) => goLiveChecklist(input(ids)).steps.find((s) => s.id === 'agents')!;

  it('blocks until at least one agent is ticked, and names the ticked ones', () => {
    expect(step([]).state).toBe('block');
    expect(goLiveChecklist(input([])).ready).toBe(false);
    const s = step(['sam1']);
    expect(s.state).toBe('ok');
    expect(s.detail).toBe('Sports Sam goes live; 2 others stay on paper.');
  });

  it('a switched-off agent cannot be ticked into live', () => {
    expect(step(['off1']).state).toBe('block');
    expect(liveCandidates(multiCfg).map((a) => a.id)).toEqual(['default', 'sam1', 'res1']);
    expect(goLivePatch(multiCfg, { caps, approval: true, approvalOffAck: false, liveAgentIds: ['off1'] })).toBeNull();
  });

  it('writes exactly the ticked agents live and every other one paper', () => {
    const p = goLivePatch(multiCfg, { caps, approval: true, approvalOffAck: false, liveAgentIds: ['sam1'] })!;
    expect(p.mcpTradeMode).toBe('live');
    expect(Object.fromEntries(p.mcpAgents!.map((a) => [a.id, a.mode]))).toEqual({
      default: 'paper', sam1: 'live', res1: 'paper', off1: 'paper',
    });
    expect(p.mcpAgents!.find((a) => a.id === 'off1')!.enabled).toBe(false);
  });

  it('opens with the agents already live, or the only agent, never all', () => {
    expect(defaultLiveSelection(multiCfg)).toEqual(['res1']);
    expect(defaultLiveSelection(paperCfg)).toEqual(['default']);
    const two = { ...paperCfg, mcpAgents: [{ id: 'default', mode: 'paper' }, sam] } as unknown as Partial<TraderConfig>;
    expect(defaultLiveSelection(two)).toEqual([]);
  });

  it('the summary names who can spend', () => {
    const d = { caps: { ...STARTER_CAPS }, approval: true, approvalOffAck: false, liveAgentIds: ['sam1', 'res1'] };
    const names = goLiveAgentNames(multiCfg, d);
    expect(names).toEqual(['Sports Sam', 'Careful Researcher']);
    expect(goLiveSummary(d, names)).toMatch(/Live: Sports Sam, Careful Researcher\. Every other agent trades on paper/);
  });

  it('the live bar needs a live agent, not just a live global mode', () => {
    const prod = { ...multiCfg, accountMode: 'live' as const, mcpTradeMode: 'live' as const };
    expect(agentsLiveOnProduction(prod)).toBe(true);
    expect(liveAgents(prod).map((a) => a.name)).toEqual(['Careful Researcher']);
    const allPaper = {
      ...prod, mcpAgents: [{ id: 'default', mode: 'paper' }, sam],
    } as unknown as Partial<TraderConfig>;
    expect(agentsLiveOnProduction(allPaper)).toBe(false);
  });

  it('each agent stands on its own record', () => {
    const b = {
      ...board({ n: 35, nPaired: 35, verdict: 'ai-better' }),
      byAgent: [
        { agentId: 'sam1', total: 50, pending: 5, lastAt: null, ...score({ n: 45, nPaired: 40, verdict: 'market-better', skill: -0.1 }) },
        { agentId: 'res1', total: 60, pending: 0, lastAt: null, ...score({ n: 60, nPaired: 60, verdict: 'ai-better', skill: 0.05 }) },
      ],
    };
    const s = agentRecordFor(b, { agentId: 'sam1', realizedUsd: -3, unrealizedUsd: 1, openPositions: 1, fills: 4 }, 'sam1');
    expect(s.verdict).toBe('worse');
    expect(s.paperPnlUsd).toBe(-2);
    expect(s.needsAck).toBe(true);
    expect(agentRecordFor(b, null, 'res1').verdict).toBe('beats');
    const none = agentRecordFor(b, null, 'default');
    expect(none.verdict).toBe('none');
    expect(agentRecordFor(b, { agentId: 'res1', realizedUsd: 2, unrealizedUsd: null, openPositions: 1, fills: 1 }, 'res1').paperPnlUsd).toBeNull();
  });
});

describe('Back to paper', () => {
  it('changes trade mode only and leaves the account mode alone', () => {
    expect(backToPaperPatch()).toEqual({ mcpTradeMode: 'paper' });
    expect(backToPaperPatch()).not.toHaveProperty('accountMode');
    const after = { ...paperCfg, accountMode: 'live' as const, mcpTradeMode: 'live' as const, ...backToPaperPatch() };
    expect(after.accountMode).toBe('live');
    expect(agentsLiveOnProduction(after)).toBe(false);
  });

  it('the live bar keys on live trade mode AND the app Live', () => {
    expect(agentsLiveOnProduction({ accountMode: 'live', mcpTradeMode: 'live' })).toBe(true);
    expect(agentsLiveOnProduction({ accountMode: 'paper', mcpTradeMode: 'live' })).toBe(false);
    expect(agentsLiveOnProduction({ accountMode: 'live', mcpTradeMode: 'paper' })).toBe(false);
    expect(agentsLiveOnProduction(null)).toBe(false);
  });
});
