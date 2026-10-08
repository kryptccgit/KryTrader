import { afterEach, describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import type { AccountSnapshot, SignalRow, TraderConfig } from '@shared/types';
import { defaultAgent, type McpAgent } from '@shared/agents';
import type { ForecastScoreboard, ForecasterScore } from '@shared/market';
import {
  agentCallEvent, backtestEvent, createActivityBus, type AgentCallActivity,
} from '../src/state/activity';
import { agentCallBeat, agentRoom, beatFor, forecastLine, shortReason } from '../src/hub/engine/jobs';
import { Director, type Stage } from '../src/hub/engine/director';
import type { Step, Worker } from '../src/hub/engine/crew';
import { NAV_NODES } from '../src/hub/engine/layout';
import {
  HUB_NAME_MAX, agentIdentity, guideMotto, hubAgentIdentity, hubName, kindOf, shortModel, tagLabel,
} from '../src/utils/agents';
import {
  MIN_REAL_FORECASTERS, agentScoreView, assignSeats, councilMode, forecastersFrom, noteLiveForecast,
  plateText, recentTickers, seatLine, seatValue, seatVote,
} from '../src/hub/council/seats';
import { Council, type CouncilHost } from '../src/hub/council/debate';
import { MEMBER_IDS } from '../src/hub/council/roster';


function call(over: Partial<AgentCallActivity> = {}): AgentCallActivity {
  return {
    kind: 'agentCall', call: 'call', client: 'claude-code 2.1', transport: null, model: 'opus',
    tool: 'get_market', outcome: 'ok', reason: null, summary: 'get_market KXFED-26DEC-T4.25',
    ticker: 'KXFED-26DEC-T4.25', fairCents: null, edgeCents: null, midCents: null, side: null, mode: null,
    durationMs: 120, suppressed: 0, ...over,
  };
}

describe('tool → room', () => {
  it('maps every tool to the room its work belongs to', () => {
    const table: [string, string][] = [
      ['discover_markets', 'research'], ['search_markets', 'research'], ['get_market', 'research'],
      ['get_orderbook', 'research'],
      ['record_forecast', 'bridge'], ['get_status', 'bridge'], ['get_scoreboard', 'bridge'],
      ['backtest_crypto15m', 'backtest'], ['backtest_signal_following', 'backtest'], ['backtest_script', 'backtest'],
      ['get_data_inventory', 'backtest'], ['sample_research_rows', 'backtest'], ['summarize_research', 'backtest'],
      ['get_trade_history', 'backtest'],
      ['save_script', 'forge'], ['validate_script', 'forge'], ['set_script_enabled', 'forge'],
      ['get_script_guide', 'forge'], ['list_scripts', 'forge'], ['get_script', 'forge'],
      ['update_engine_config', 'forge'], ['get_engine_config', 'forge'], ['get_engine_status', 'forge'],
      ['place_order', 'desk'], ['preview_order', 'desk'], ['get_portfolio', 'desk'], ['cancel_order', 'desk'],
      ['list_orders', 'desk'], ['get_order_status', 'desk'], ['move_funds', 'desk'],
    ];
    for (const [tool, room] of table) expect([tool, agentRoom(tool, 'ok')]).toEqual([tool, room]);
  });

  it('a refusal goes to Risk whatever the tool; an unknown tool reports to the bridge', () => {
    expect(agentRoom('place_order', 'refused')).toBe('vault');
    expect(agentRoom('get_market', 'refused')).toBe('vault');
    expect(agentRoom('some_future_tool', 'ok')).toBe('bridge');
    expect(agentRoom('backtest_anything_new', 'ok')).toBe('backtest');
    expect(agentRoom('get_market', 'error')).toBe('research');
  });

  it('every agent station the director can name exists on the walk graph', () => {
    const ids = new Set(NAV_NODES.map((n) => n.id));
    for (const room of ['research', 'bridge', 'backtest', 'forge', 'desk', 'vault']) {
      expect(ids.has(`${room}.agentA`)).toBe(true);
      expect(ids.has(`${room}.agentB`)).toBe(true);
    }
  });
});

describe('what an agent says', () => {
  it('a forecast quotes its number and its edge', () => {
    const ev = call({ tool: 'record_forecast', fairCents: 61, edgeCents: 4.2, side: 'yes', summary: 'forecast KXFED 61¢ · edge +4¢ YES' });
    const b = agentCallBeat(ev, 'Claude Code · opus')!;
    expect(b.room).toBe('bridge');
    expect(b.text).toBe('🎯 forecast 61¢ · edge +4¢ YES');
    expect(b.log).toContain('Claude Code · opus');
    expect(forecastLine({ ...ev, edgeCents: null })).toBe('forecast 61¢ · no side offered');
    expect(forecastLine({ ...ev, fairCents: null, edgeCents: null })).toBe('forecast no number · no side offered');
  });

  it('a refusal quotes the rail, briefly, and hurries to Risk', () => {
    const b = agentCallBeat(call({
      tool: 'place_order', outcome: 'refused', summary: 'buy 2 YES KXA @54¢', mode: 'paper',
      reason: 'A buy needs forecast_id from record_forecast on this market. Commit to a fair value first.',
    }), 'Cursor')!;
    expect(b.room).toBe('vault');
    expect(b.run).toBe(true);
    expect(b.text).toBe('⛔ refused: no recent forecast');
    expect(b.log).toContain('A buy needs forecast_id');
    expect(shortReason('Forecast 3 is older than 30 minutes. Re-read the market and record a new one.')).toBe('no recent forecast');
    expect(shortReason('Your forecast (55c YES) gives -1.20c per contract on YES at 54c after fees; the minimum is 3c. No trade.')).toBe('edge below the minimum');
    expect(shortReason('Daily loss stop: the agent is down $50.00 today')).toBe('daily loss stop');
    expect(shortReason(null)).toBe('no reason given');
    expect(shortReason('Kalshi said something new')).toBe('Kalshi said something new');
  });

  it('desk calls always say PAPER or LIVE', () => {
    expect(agentCallBeat(call({ tool: 'place_order', mode: 'paper', summary: 'buy 2 YES KXA @54¢ · filled 2 @54¢' }), 'x')!.text)
      .toBe('📡 PAPER buy 2 YES KXA @54¢ · filled 2 @54¢');
    expect(agentCallBeat(call({ tool: 'place_order', mode: 'live', summary: 'buy 1 NO KXB @40¢ · awaiting approval #3' }), 'x')!.text)
      .toContain('LIVE buy 1 NO KXB');
  });

  it('a connect waves from its dock; the throttle\'s drops are said', () => {
    const b = agentCallBeat(call({ call: 'connect', tool: null, summary: 'connected' }), 'Codex')!;
    expect(b.connect).toBe(true);
    expect(agentCallBeat(call({ suppressed: 9 }), 'x')!.log).toContain('+9 more calls');
  });

  it('the bus-level beat mapper leaves agent calls to the crew', () => {
    expect(beatFor(call())).toBeNull();
  });
});

describe('the push, re-read defensively', () => {
  it('keeps types, drops what is wrong, never coerces to a number', () => {
    const ev = agentCallEvent({
      v: 1, kind: 'call', at: 1, client: 'cursor 1.7', transport: null, model: null, tool: 'record_forecast',
      outcome: 'ok', reason: null, durationMs: 5, summary: 'forecast KXA 0¢', ticker: 'KXA',
      fairCents: 0, edgeCents: null, midCents: 150, side: 'maybe', mode: 'demo', suppressed: -3,
    })!;
    expect(ev.fairCents).toBeNull();
    expect(ev.midCents).toBeNull();
    expect(ev.side).toBeNull();
    expect(ev.mode).toBeNull();
    expect(ev.suppressed).toBe(0);
    expect(agentCallEvent({ client: 'x', summary: 'y', outcome: 'maybe' })).toBeNull();
    expect(agentCallEvent(null)).toBeNull();
    expect(agentCallEvent({ client: 7, summary: 'y', outcome: 'ok' })).toBeNull();
  });

  it('a chatty agent cannot push other events out of the hub catch-up', () => {
    const bus = createActivityBus(10, 5);
    const now = 1_000_000;
    bus.publish(backtestEvent('15m', 'Sniper', 30, { n: 0 } as never)!, now - 1000);
    for (let i = 0; i < 200; i++) bus.publish(call(), now);
    const kinds = bus.recent(60_000, now).map((r) => r.ev.kind);
    expect(kinds.filter((k) => k === 'agentCall')).toHaveLength(5);
    expect(kinds[0]).toBe('backtest');
  });
});

describe('agent identity', () => {
  it('names each client and its model', () => {
    expect(agentIdentity({ client: 'claude-code 2.1', model: 'claude-opus-4-1' }).label).toBe('Claude Code · opus');
    expect(agentIdentity({ client: 'cursor-vscode 1.0' }).label).toBe('Cursor');
    expect(agentIdentity({ client: 'claude-ai 0.9' }).name).toBe('Claude Desktop');
    expect(agentIdentity({ client: 'codex-mcp-client 0.4', model: 'gpt-5' }).label).toBe('Codex · gpt-5');
    expect(agentIdentity({ client: 'autopilot (claude-sonnet-4-5)' }).label).toBe('Autopilot · sonnet');
    expect(agentIdentity({ source: 'panel', model: 'claude-sonnet-4-5' }).label).toBe('Analyse · Claude');
    expect(agentIdentity({ source: 'panel', model: 'gpt-5' }).label).toBe('Analyse · GPT');
    expect(agentIdentity({ client: 'my-bot 0.1', transport: 'http' }).kind).toBe('http');
    expect(agentIdentity({ source: 'mcp', client: null, model: 'claude-code 2.0' }).label).toBe('Claude Code');
    expect(agentIdentity({ client: 'unknown' }).name).toBe('Agent');
    expect(kindOf('Cursor')).toBe('cursor');
    expect(shortModel(null)).toBeNull();
  });

  it('one crew member per client, one seat per client and model', () => {
    const a = agentIdentity({ client: 'claude-code 2.1', model: 'opus' });
    const b = agentIdentity({ client: 'claude-code 2.2', model: 'sonnet' });
    expect(a.id).toBe(b.id);
    expect(a.seatId).not.toBe(b.seatId);
  });
});


function fakeWorker(role: Worker['role'], home: string, id = 0) {
  const w = {
    id, role, home, free: true, carrying: null as THREE.Object3D | null, tag: null as unknown,
    assigned: 0, steps: [] as Step[],
    assign(steps: Step[]) {
      w.assigned++;
      w.steps.push(...steps);
      for (const s of steps) if (s.k === 'do') s.fn(w as unknown as Worker);
    },
    pickUp(o: THREE.Object3D) { w.carrying = o; },
    drop() { const o = w.carrying; w.carrying = null; return o; },
    headWorld: (v: THREE.Vector3) => v,
  };
  return w;
}

function stage() {
  const v = () => new THREE.Vector3();
  const ship = {
    ping: vi.fn(), printFlash: vi.fn(), setHoloIdle: vi.fn(), startBacktest: vi.fn(), finishBacktest: vi.fn(),
    backtestRunning: false, setOptimizing: vi.fn(), pushOrder: vi.fn(), fireTube: vi.fn(), stationHit: vi.fn(),
    hatchBlink: vi.fn(), vaultDeposit: vi.fn(), anvilHit: vi.fn(),
    tubeInside: v(), kalshiPos: v(), hatchPos: v(), station: { position: v() },
    rackSlots: [v()], outboxSlots: [v()], airlockSlots: [v()], mossyHop: 0, alarm: 0,
  };
  const obj = () => new THREE.Object3D();
  const crew = [fakeWorker('trader', 'desk.termA'), fakeWorker('risk', 'vault.risk')];
  const aboard = new Map<string, ReturnType<typeof fakeWorker>>();
  const agent = vi.fn((who: { id: string }) => {
    let w = aboard.get(who.id);
    if (!w) { w = fakeWorker('agent', `bridge.dock${aboard.size}`, aboard.size); aboard.set(who.id, w); }
    return w as unknown as Worker;
  });
  const s = {
    ship, crew, root: new THREE.Object3D(),
    kit: { card: obj, chip: obj, tablet: obj, capsule: obj, bag: obj },
    flights: { launch: vi.fn() }, sparks: { burst: vi.fn() },
    pile: { add: vi.fn(), top: (o: THREE.Vector3) => o },
    say: vi.fn(() => true), log: vi.fn(), activity: vi.fn(), agent,
  };
  return { s: s as unknown as Stage, ship, crew, say: s.say, log: s.log, agent, aboard };
}

const EMPTY = { signals: [] as SignalRow[], positions: [], account: null as AccountSnapshot | null, scannerStats: null };

function run(d: Director, seconds: number, dt = 0.05) {
  for (let t = 0; t < seconds; t += dt) d.update(dt);
}

describe('director: the user\'s agents', () => {
  it('no call, no agent: nothing comes aboard on a timer', () => {
    const { s, agent, say } = stage();
    const d = new Director(s);
    d.ingest(EMPTY);
    run(d, 300);
    expect(agent).not.toHaveBeenCalled();
    expect(say).not.toHaveBeenCalled();
  });

  it('a real call brings its agent aboard, walks it to the room and quotes the call', () => {
    const { s, say, aboard } = stage();
    const now = 5_000_000;
    const d = new Director(s, { now: () => now });
    d.ingest(EMPTY);
    d.activity({ seq: 1, at: now, ev: call({ tool: 'record_forecast', fairCents: 61, edgeCents: 4, side: 'yes', summary: 'forecast KXFED 61¢ · edge +4¢ YES' }) });
    run(d, 0.2);
    const w = [...aboard.values()][0];
    expect(w.steps.some((x) => x.k === 'go' && x.to === 'bridge.agentA')).toBe(true);
    expect(say.mock.calls.some((c) => c[1] === '🎯 forecast 61¢ · edge +4¢ YES')).toBe(true);
    expect((w.tag as { label: string }).label).toBe('Claude Code · opus');
    expect(d.bridgeSign).toBe('1 agent aboard');
    expect(d.agentCalls).toBe(1);
  });

  it('a refused order runs to Risk with the reason', () => {
    const { s, say, aboard } = stage();
    const d = new Director(s);
    d.ingest(EMPTY);
    d.activity({ seq: 1, at: Date.now(), ev: call({ tool: 'place_order', outcome: 'refused', mode: 'paper', reason: 'A buy needs forecast_id from record_forecast on this market.' }) });
    run(d, 0.2);
    const w = [...aboard.values()][0];
    expect(w.steps.some((x) => x.k === 'go' && x.to.startsWith('vault.agent') && x.run)).toBe(true);
    expect(say.mock.calls.some((c) => c[1] === '⛔ refused: no recent forecast')).toBe(true);
  });

  it('an agent order is quoted once: by the agent, not again by the desk', () => {
    const { s, say, ship } = stage();
    const now = 9_000_000;
    const d = new Director(s, { now: () => now });
    d.ingest(EMPTY);
    d.activity({ seq: 1, at: now, ev: { kind: 'agent', mode: 'paper', message: 'PAPER buy 2 YES KXA @ 54c avg, fee $0.02', approvalId: null, decision: null } });
    d.activity({ seq: 2, at: now, ev: call({ tool: 'place_order', mode: 'paper', summary: 'buy 2 YES KXA @54¢ · filled 2 @54¢' }) });
    run(d, 3);
    const lines = say.mock.calls.map((c) => String(c[1]));
    expect(lines.filter((l) => l.includes('KXA'))).toEqual(['📡 PAPER buy 2 YES KXA @54¢ · filled 2 @54¢']);
    expect(ship.pushOrder).toHaveBeenCalledTimes(1);
    expect(ship.fireTube).not.toHaveBeenCalled();
  });

  it('an agent calling faster than it can walk drops routine reads, never the refusal or the order', () => {
    const { s, say, aboard } = stage();
    const d = new Director(s);
    d.ingest(EMPTY);
    d.activity({ seq: 1, at: Date.now(), ev: call() });
    run(d, 0.1);
    const w = [...aboard.values()][0];
    w.free = false;
    const evs = [
      call({ tool: 'place_order', outcome: 'refused', mode: 'paper', reason: 'A buy needs forecast_id from record_forecast.' }),
      call({ tool: 'place_order', mode: 'paper', summary: 'buy 2 YES KXA @54¢ · filled 2 @54¢' }),
      call({ summary: 'get_market KXB' }), call({ summary: 'get_market KXC' }), call({ summary: 'get_market KXD' }),
    ];
    evs.forEach((ev, i) => d.activity({ seq: 2 + i, at: Date.now(), ev }));
    for (let i = 0; i < 3; i++) { w.free = true; run(d, 0.05); w.free = false; }
    const lines = say.mock.calls.map((c) => String(c[1]));
    expect(lines).toContain('⛔ refused: no recent forecast');
    expect(lines).toContain('📡 PAPER buy 2 YES KXA @54¢ · filled 2 @54¢');
    expect(lines.filter((l) => /get_market KX[BCD]/.test(l))).toEqual(['🔎 get_market KXD']);
  });

  it('two agents are two crew members', () => {
    const { s, aboard } = stage();
    const d = new Director(s);
    d.ingest(EMPTY);
    d.activity({ seq: 1, at: Date.now(), ev: call() });
    d.activity({ seq: 2, at: Date.now(), ev: call({ client: 'cursor 1.7', model: null }) });
    run(d, 0.2);
    expect(aboard.size).toBe(2);
    expect(d.bridgeSign).toBe('2 agents aboard');
  });
});


function fRow(over: Partial<ForecasterScore>): ForecasterScore {
  return {
    source: 'mcp', client: 'claude-code 2.1', model: 'opus', total: 3, pending: 3, lastAt: '2026-10-06 12:00:00',
    n: 0, nPaired: 0, brierAi: null, brierAiPaired: null, brierMarket: null, skill: null, diffMean: null, diffSe: null,
    verdict: 'too-few', open: [], ...over,
  };
}

function board(rows: ForecasterScore[]): ForecastScoreboard {
  return {
    totalForecasts: 0, pending: 0, resolved: 0, scoredMarkets: 0, minScored: 30,
    overall: { n: 0, nPaired: 0, brierAi: null, brierAiPaired: null, brierMarket: null, skill: null, diffMean: null, diffSe: null, verdict: 'too-few' },
    bySource: [], buckets: [], byForecaster: rows, recent: [],
  };
}

const B2 = board([
  fRow({ open: [{ ticker: 'KXFED', fairValueCents: 61, marketMidCents: 52, createdAt: '2026-10-06 12:00:00' }] }),
  fRow({
    client: 'cursor 1.7', model: null, lastAt: '2026-10-06 11:00:00',
    n: 40, nPaired: 38, brierAi: 0.18, brierAiPaired: 0.18, brierMarket: 0.2, skill: 0.1, verdict: 'indistinguishable',
    open: [{ ticker: 'KXOTHER', fairValueCents: 30, marketMidCents: null, createdAt: '2026-10-06 11:00:00' }],
  }),
  fRow({ source: 'panel', client: null, model: 'claude-sonnet-4-5', lastAt: '2026-10-06 10:00:00', open: [] }),
]);

describe('council seats from real forecasts', () => {
  afterEach(() => vi.restoreAllMocks());

  it('each distinct client/model takes a seat, labelled, busiest in the middle', () => {
    const seats = assignSeats(forecastersFrom(B2));
    expect(seats.map((x) => x.label)).toEqual(['Claude Code · opus', 'Cursor', 'Analyse · Claude']);
    expect(seats.map((x) => x.member)).toEqual([MEMBER_IDS[2], MEMBER_IDS[3], MEMBER_IDS[1]]);
  });

  it('a seat with no forecast on the market shows a dash, never a number', () => {
    const [cc, cursor, panel] = assignSeats(forecastersFrom(B2));
    expect(plateText(cc, 'KXFED')).toBe('Claude Code · opus · 61¢');
    expect(plateText(cursor, 'KXFED')).toBe('Cursor · —');
    expect(plateText(panel, 'KXFED')).toBe('Analyse · Claude · —');
    expect(seatValue(cursor, 'KXFED')).toBeNull();
    expect(seatLine(cursor, 'KXFED')).toBeNull();
    expect(seatLine(cc, 'KXFED')).toBe('fair 61¢ · mid was 52¢');
    expect(seatVote(cc, 'KXFED')).toBe(true);
    expect(seatVote(cursor, 'KXOTHER')).toBeNull();
  });

  it('the personas sit under two real forecasters, and on request', () => {
    expect(MIN_REAL_FORECASTERS).toBe(2);
    expect(councilMode(null, 0)).toBe('personas');
    expect(councilMode('agents', 1)).toBe('personas');
    expect(councilMode(null, 2)).toBe('agents');
    expect(councilMode('personas', 5)).toBe('personas');
    expect(assignSeats(forecastersFrom(board([fRow({})])))).toHaveLength(1);
    expect(assignSeats(forecastersFrom(null))).toHaveLength(0);
    expect(assignSeats(forecastersFrom({ ...B2, byForecaster: undefined }))).toHaveLength(0);
  });

  it('WHO CALLED IT? shows real skill, coloured by the verdict; nothing scored is a dash', () => {
    const v = agentScoreView(assignSeats(forecastersFrom(B2)));
    expect(v.lines[0]).toMatchObject({ name: 'Cursor', value: '+10%', tone: 'neutral' });
    expect(v.lines[0].sub).toBe('Brier 0.180 vs mkt 0.200 · 38 settled');
    const cc = v.lines.find((l) => l.name === 'Claude Code · opus')!;
    expect(cc).toMatchObject({ value: '—', bar: null, tone: 'none' });
    expect(cc.sub).toBe('nothing settled yet · 1 open');
  });

  it('a live forecast joins the roster at once; a read with no number does not', () => {
    const roster = forecastersFrom(board([]));
    const at = Date.UTC(2026, 9, 6, 12);
    expect(noteLiveForecast(roster, call({ tool: 'record_forecast', fairCents: 58, midCents: 50, ticker: 'KXA' }), at))
      .toEqual({ ticker: 'KXA', seatId: 'claude-code||opus' });
    expect(noteLiveForecast(roster, { kind: 'aiAnalysis', ticker: 'KXA', title: null, provider: 'anthropic', verdict: 'unclear', fairCents: null, confidence: 'low' }, at)).toBeNull();
    expect(noteLiveForecast(roster, call({ tool: 'record_forecast', outcome: 'refused', fairCents: 58, ticker: 'KXA' }), at)).toBeNull();
    expect(noteLiveForecast(roster, call({ tool: 'get_market' }), at)).toBeNull();
    noteLiveForecast(roster, { kind: 'aiAnalysis', ticker: 'KXA', title: null, provider: 'openai', verdict: 'rich', fairCents: 44, confidence: 'low' }, at + 1);
    const seats = assignSeats(roster);
    expect(seats.map((x) => x.label)).toEqual(['Analyse · GPT', 'Claude Code · opus']);
    expect(seats.map((x) => seatVote(x, 'KXA'))).toEqual([null, true]);
    expect(recentTickers(seats)).toEqual(['KXA']);
  });
});

describe('council: the real forecasters debate real calls only', () => {
  it('only seats with a call on the market speak, and only their own numbers', () => {
    vi.spyOn(window, 'setTimeout');
    const member = () => ({ pose: 'idle', talking: 0, set(p: string) { this.pose = p; }, climbTable() {} });
    const said: [string, string][] = [];
    const votes: (boolean | null)[] = [];
    const host = {
      members: Object.fromEntries(MEMBER_IDS.map((id) => [id, member()])),
      bunker: {
        holoPulse: 0, holoColor: { set() {} }, tableShake: { v: 0 },
        feed() {}, setVote(_i: number, v: boolean | null) { votes.push(v); }, setMood() {}, bangGavel() {}, setScore() {},
      },
      say: (who: string, text: string) => { said.push([who, text]); return true; },
      log() {}, speaking() {}, coins() {},
    } as unknown as CouncilHost;
    const c = new Council(host);
    const seats = assignSeats(forecastersFrom(B2));
    c.setSeats(seats);
    expect(c.mode).toBe('agents');
    c.ingest({ signals: [{ id: 1, source: 'whale', ticker: 'KXNBA', eventTicker: 'KXNBA', title: 't', category: '', direction: 'yes', priceCents: 40, confidence: 60, edgePts: 5, dollarValue: 9000, createdAt: '', resolved: false, outcomeCorrect: null, pnlEstimate: null, traded: true }], positions: [], account: null, scannerStats: null });
    for (let i = 0; i < 40; i++) c.update(0.1);
    expect(c.debate).toBeNull();
    c.noteAgenda('KXFED');
    for (let i = 0; i < 120; i++) c.update(0.1);
    const lines = said.filter(([who]) => who !== 'chair');
    expect(lines).toEqual([[seats[0].member, 'fair 61¢ · mid was 52¢']]);
    expect(said.some(([who, t]) => who === 'chair' && t === 'THE FORECASTS ARE IN.')).toBe(true);
    expect(votes.filter((v) => v !== null)).toEqual([true]);
    said.length = 0;
    for (let i = 0; i < 300; i++) c.update(0.1);
    expect(said).toEqual([]);
  });

  it('switching back to personas ends the real item and clears the agenda', () => {
    const member = () => ({ pose: 'idle', talking: 0, set(p: string) { this.pose = p; }, climbTable() {} });
    const host = {
      members: Object.fromEntries(MEMBER_IDS.map((id) => [id, member()])),
      bunker: { holoPulse: 0, holoColor: { set() {} }, tableShake: { v: 0 }, feed() {}, setVote() {}, setMood() {}, bangGavel() {}, setScore() {} },
      say: () => true, log() {}, speaking() {}, coins() {},
    } as unknown as CouncilHost;
    const c = new Council(host);
    c.setSeats(assignSeats(forecastersFrom(B2)));
    c.noteAgenda('KXFED');
    c.update(1.5);
    expect(c.currentTicker).toBe('KXFED');
    c.setSeats(null);
    expect(c.mode).toBe('personas');
    expect(c.debate).toBeNull();
  });
});


function named(id: string, name: string, over: Partial<McpAgent> = {}): McpAgent {
  return { ...defaultAgent('paper'), id, name, ...over };
}

const SAM = named('sam1', 'Sam', {
  emoji: '🦊', color: '#F472B6', guide: 'You are a patient researcher. Buy under 30c only.',
});
const RES = named('res1', 'Researcher', { emoji: '🔎', color: '#38BDF8' });
const QUIET = named('quiet1', 'Quiet One', { emoji: '🤫', color: '#22C55E' });
const AGENTS: McpAgent[] = [defaultAgent('paper'), SAM, RES, QUIET];
const CFG = { mcpAgents: AGENTS } as unknown as TraderConfig;
const ch = (c: number) => String.fromCharCode(c);
const UNSAFE = new RegExp(`[${ch(0)}-${ch(0x1f)}${ch(0x202a)}-${ch(0x202e)}]`);

describe('named agents: identity by agent id', () => {
  it('a named agent is its config name, emoji and colour, one crew member whatever drives it', () => {
    const a = hubAgentIdentity({ agentId: 'sam1', agentName: 'Sam (old name)', client: 'claude-code 2.1', model: 'opus' }, AGENTS);
    expect(a).toMatchObject({ id: 'agent|sam1', seatId: 'agent|sam1|opus', name: 'Sam', label: 'Sam · opus', color: '#F472B6', emoji: '🦊' });
    expect(tagLabel(a)).toBe('🦊 Sam · opus');
    const b = hubAgentIdentity({ agentId: 'sam1', client: 'cursor 1.7', model: 'gpt-5' }, AGENTS);
    expect(b.id).toBe(a.id);
    expect(b.seatId).not.toBe(a.seatId);
  });

  it('falls back to the client/model identity for events without an agent id', () => {
    const src = { client: 'claude-code 2.1', model: 'opus' };
    expect(hubAgentIdentity(src, AGENTS)).toEqual(agentIdentity(src));
    expect(hubAgentIdentity({ ...src, agentId: '../x' }, AGENTS)).toEqual(agentIdentity(src));
    expect(hubAgentIdentity({ source: 'panel', model: 'gpt-5', agentId: 'sam1' }, AGENTS).label).toBe('Analyse · GPT');
    expect(hubAgentIdentity({ ...src, agentId: 'sam1' }, null).label).toBe('Claude Code · opus');
  });

  it('the Default agent keeps its identity unless the user renamed it', () => {
    const src = { client: 'claude-code 2.1', model: 'opus', agentId: 'default', agentName: 'Default' };
    expect(hubAgentIdentity(src, AGENTS).label).toBe('Claude Code · opus');
    const renamed = [named('default', 'Mossy', { emoji: '🐸', color: '#22C55E' })];
    expect(tagLabel(hubAgentIdentity(src, renamed))).toBe('🐸 Mossy · opus');
  });

  it('an id the config does not know: the event\'s name, else "Deleted agent", never another agent', () => {
    const fresh = hubAgentIdentity({ agentId: 'new1', agentName: 'Newbie', client: 'cursor 1.7' }, AGENTS);
    expect(fresh).toMatchObject({ id: 'agent|new1', name: 'Newbie' });
    expect(fresh.color).toMatch(/^#[0-9A-F]{6}$/i);
    expect(hubAgentIdentity({ agentId: 'gone1', client: 'cursor 1.7' }, AGENTS).name).toBe('Deleted agent');
  });

  it('names are cleaned and capped, wherever they came from', () => {
    const nasty = `Sam${ch(0x202e)}${ch(7)}\nthe fox who trades all day long`;
    const who = hubAgentIdentity({ agentId: 'x1', agentName: nasty }, [named('x1', nasty)]);
    expect(Array.from(who.name).length).toBeLessThanOrEqual(HUB_NAME_MAX);
    expect(who.name.endsWith('…')).toBe(true);
    expect(UNSAFE.test(who.name)).toBe(false);
    expect(hubName('  ')).toBe('Agent');
    const ev = agentCallEvent({ client: 'cursor 1.7', summary: 's', outcome: 'ok', agentId: 'Sam/../1', agentName: nasty })!;
    expect(ev.agentId).toBeNull();
    expect(UNSAFE.test(ev.agentName!)).toBe(false);
    expect(agentCallEvent({ client: 'cursor 1.7', summary: 's', outcome: 'ok', agentId: 'sam1' })!.agentId).toBe('sam1');
  });

  it('a guide gives a few of the user\'s words, never a number', () => {
    expect(guideMotto(SAM.guide)).toBe("I'm a patient researcher");
    expect(guideMotto('Buy under 30c. You only work sports markets that settle within two days.')).toBe('I only work sports markets that…');
    expect(guideMotto('Edge 5c. Size 2.')).toBeNull();
    expect(guideMotto('')).toBeNull();
  });
});

describe('named agents on the Spaceship', () => {
  it('configured but silent agents never come aboard', () => {
    const { s, agent, say } = stage();
    const d = new Director(s);
    d.ingest({ ...EMPTY, config: CFG });
    run(d, 300);
    expect(agent).not.toHaveBeenCalled();
    expect(say).not.toHaveBeenCalled();
  });

  it('a named agent\'s real call brings it aboard as itself, in its colour, to that call\'s room', () => {
    const { s, aboard, say } = stage();
    const d = new Director(s);
    d.ingest({ ...EMPTY, config: CFG });
    d.activity({ seq: 1, at: Date.now(), ev: call({ agentId: 'sam1', agentName: 'Sam', tool: 'backtest_crypto15m', summary: 'backtest BTC 30d' }) });
    run(d, 0.2);
    d.activity({ seq: 2, at: Date.now(), ev: call({ agentId: 'sam1', client: 'cursor 1.7', model: null, tool: 'get_market' }) });
    run(d, 0.2);
    expect([...aboard.keys()]).toEqual(['agent|sam1']);
    const w = [...aboard.values()][0];
    expect(w.tag).toEqual({ label: '🦊 Sam · opus', color: '#F472B6' });
    expect(w.steps.some((x) => x.k === 'go' && x.to.startsWith('backtest.agent'))).toBe(true);
    expect(say).toHaveBeenCalled();
    expect(d.bridgeSign).toBe('1 agent aboard');
  });

  it('an old event with no agent id keeps its client crew member beside a named one', () => {
    const { s, aboard } = stage();
    const d = new Director(s);
    d.ingest({ ...EMPTY, config: CFG });
    d.activity({ seq: 1, at: Date.now(), ev: call() });
    d.activity({ seq: 2, at: Date.now(), ev: call({ agentId: 'res1' }) });
    run(d, 0.2);
    expect([...aboard.keys()].sort()).toEqual(['agent|res1', 'claude-code|']);
    expect([...aboard.values()].map((w) => (w.tag as { label: string }).label).sort())
      .toEqual(['Claude Code · opus', '🔎 Researcher · opus']);
  });
});

describe('named agents at the Council', () => {
  const NB = board([
    fRow({ agentId: 'sam1', open: [{ ticker: 'KXFED', fairValueCents: 61, marketMidCents: 52, createdAt: '2026-10-06 12:00:00' }] }),
    fRow({ agentId: 'res1', lastAt: '2026-10-06 11:00:00', open: [{ ticker: 'KXOTHER', fairValueCents: 30, marketMidCents: null, createdAt: '2026-10-06 11:00:00' }] }),
    fRow({ agentId: 'default', lastAt: '2026-10-06 10:00:00', open: [{ ticker: 'KXFED', fairValueCents: 58, marketMidCents: 52, createdAt: '2026-10-06 10:00:00' }] }),
  ]);

  it('each named agent with real forecasts sits as itself; the silent one has no seat', () => {
    const seats = assignSeats(forecastersFrom(NB, AGENTS));
    expect(seats.map((x) => x.label)).toEqual(['Sam · opus', 'Researcher · opus', 'Claude Code · opus']);
    expect(seats.map((x) => x.f.who.color)).toEqual(['#F472B6', '#38BDF8', agentIdentity({ client: 'claude-code' }).color]);
    expect(seats.some((x) => x.f.who.name === 'Quiet One')).toBe(false);
    expect(assignSeats(forecastersFrom(NB, null)).map((x) => x.label)).toEqual(['Claude Code · opus']);
  });

  it('a seat shows ITS forecast on the market, or a dash, never a number it did not make', () => {
    const [sam, res, def] = assignSeats(forecastersFrom(NB, AGENTS));
    expect(plateText(sam, 'KXFED')).toBe('🦊 Sam · opus · 61¢');
    expect(plateText(res, 'KXFED')).toBe('🔎 Researcher · opus · —');
    expect(plateText(def, 'KXFED')).toBe('Claude Code · opus · 58¢');
    expect(seatValue(res, 'KXFED')).toBeNull();
    expect(seatLine(res, 'KXFED')).toBeNull();
    const line = seatLine(sam, 'KXFED')!;
    expect(line).toBe('fair 61¢ · mid was 52¢ · “I\'m a patient researcher”');
    expect(line.match(/\d+/g)).toEqual(['61', '52']);
  });

  it('a live record_forecast by a named agent lands on that agent\'s seat', () => {
    const roster = forecastersFrom(board([]), AGENTS);
    const at = Date.UTC(2026, 9, 6, 12);
    expect(noteLiveForecast(roster, call({ agentId: 'res1', tool: 'record_forecast', fairCents: 44, midCents: 50, ticker: 'KXA' }), at, AGENTS))
      .toEqual({ ticker: 'KXA', seatId: 'agent|res1|opus' });
    expect(noteLiveForecast(roster, call({ tool: 'record_forecast', fairCents: 58, midCents: 50, ticker: 'KXA' }), at, AGENTS))
      .toEqual({ ticker: 'KXA', seatId: 'claude-code||opus' });
    expect(noteLiveForecast(roster, call({ agentId: 'quiet1', tool: 'get_market' }), at, AGENTS)).toBeNull();
    expect(assignSeats(roster).map((x) => x.label).sort()).toEqual(['Claude Code · opus', 'Researcher · opus']);
  });
});
