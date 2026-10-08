import { describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import type { AccountSnapshot, Crypto15mBacktest, Crypto15mRunner, SignalRow, TraderConfig } from '@shared/types';
import {
  ACTIVITY_CAP, REPLAY_WINDOW_MS, backtestEvent, createActivityBus, downsample, optimizerEvent,
  publishActivity, replayPlan, ruleEvent, agentEvent, type ActivityEvent, type ActivityRecord,
} from '../src/state/activity';
import {
  activeSlots, backtestLine, beatFor, flipLine, positionSource, scheduleFlips, signalHandoff,
} from '../src/hub/engine/jobs';
import { Director, type Stage } from '../src/hub/engine/director';
import type { Worker, Step } from '../src/hub/engine/crew';
import { Council, type CouncilHost } from '../src/hub/council/debate';


function bt(over: Partial<Crypto15mBacktest> = {}): Crypto15mBacktest {
  return {
    n: 412, wins: 300, winRate: 0.728, netEvCentsPerContract: 1.6, totalPnlUsd: 65.9, maxDrawdownUsd: 12,
    contracts: 10, windowsScanned: 2800, byAsset: {}, byHourUtc: [], byDay: [], trades: [], caveats: [],
    equity: Array.from({ length: 120 }, (_, i) => ({ at: null, value: i * 0.5 })),
    ...over,
  };
}

describe('activity bus', () => {
  it('is a bounded ring: the oldest records leave, order is kept', () => {
    const bus = createActivityBus(5);
    for (let i = 0; i < 8; i++) bus.publish({ kind: 'preset', what: 'strategy', name: `p${i}`, ok: true }, 1000 + i);
    expect(bus.size()).toBe(5);
    const names = bus.recent(1e9, 2000).map((r) => (r.ev as { name: string }).name);
    expect(names).toEqual(['p3', 'p4', 'p5', 'p6', 'p7']);
    expect(ACTIVITY_CAP).toBe(200);
  });

  it('replays only the window, oldest first, as spaced beats', () => {
    const bus = createActivityBus();
    const now = 10_000_000;
    bus.publish({ kind: 'preset', what: 'strategy', name: 'too old', ok: true }, now - REPLAY_WINDOW_MS - 1);
    bus.publish({ kind: 'preset', what: 'strategy', name: 'a', ok: true }, now - 120_000);
    bus.publish({ kind: 'preset', what: 'strategy', name: 'b', ok: true }, now - 5_000);
    const recent = bus.recent(REPLAY_WINDOW_MS, now);
    expect(recent.map((r) => (r.ev as { name: string }).name)).toEqual(['a', 'b']);
    const plan = replayPlan(recent, { beatMs: 1000, firstMs: 500 });
    expect(plan.map((p) => p.delayMs)).toEqual([500, 1500]);
    expect(plan[0].rec.at).toBeLessThan(plan[1].rec.at);
  });

  it('compresses a busy window to its newest beats', () => {
    const recs: ActivityRecord[] = Array.from({ length: 30 }, (_, i) => ({
      seq: i + 1, at: i, ev: { kind: 'preset', what: 'strategy', name: `p${i}`, ok: true },
    }));
    const plan = replayPlan(recs, { max: 4 });
    expect(plan.map((p) => (p.rec.ev as { name: string }).name)).toEqual(['p26', 'p27', 'p28', 'p29']);
  });

  it('never throws into a publisher: payload errors and listener errors are swallowed', () => {
    const bus = createActivityBus();
    const good = vi.fn();
    bus.subscribe(() => { throw new Error('bad listener'); });
    bus.subscribe(good);
    expect(() => publishActivity(() => { throw new Error('bad payload'); }, bus)).not.toThrow();
    expect(bus.size()).toBe(0);
    expect(() => publishActivity({ kind: 'preset', what: 'profile', name: 'x', ok: true }, bus)).not.toThrow();
    expect(good).toHaveBeenCalledTimes(1);
    publishActivity(() => null, bus);
    expect(bus.size()).toBe(1);
  });

  it('unsubscribes', () => {
    const bus = createActivityBus();
    const fn = vi.fn();
    const off = bus.subscribe(fn);
    off();
    bus.publish({ kind: 'preset', what: 'profile', name: 'x', ok: true });
    expect(fn).not.toHaveBeenCalled();
  });
});

describe('payload builders keep absent values absent', () => {
  it('a backtest over zero trades has no edge and no win rate', () => {
    const ev = backtestEvent('15m', 'Sniper', 30, bt({ n: 0, winRate: 0, netEvCentsPerContract: 0, totalPnlUsd: 0, equity: [] }));
    expect(ev).toMatchObject({ trades: 0, netCents: null, winRatePct: null, totalPnlUsd: null, equity: [] });
  });

  it('no result is not a run', () => {
    expect(backtestEvent('main', 'x', 7, null)).toBeNull();
    expect(optimizerEvent(null)).toBeNull();
  });

  it('carries the real numbers and a downsampled real curve', () => {
    const ev = backtestEvent('script', 'Fade', 14, { ...bt(), tStat: 2.4 });
    expect(ev).toMatchObject({ trades: 412, netCents: 1.6, t: 2.4 });
    expect((ev as { winRatePct: number }).winRatePct).toBeCloseTo(72.8);
    const eq = (ev as { equity: number[] }).equity;
    expect(eq.length).toBe(48);
    expect(eq[0]).toBe(0);
    expect(eq[47]).toBe(59.5);
    expect(downsample([1, 2, 3], 48)).toEqual([1, 2, 3]);
  });

  it('optimizer: only buckets that elected a winner become slots', () => {
    const ev = optimizerEvent({
      coin: 'BTC', granularityH: 4, sinceDays: 30, holdoutDays: 7, strategiesSwept: 40, caveat: '',
      coinWinner: { name: 'BTC 15m Settlement Sniper', score: 1, n: 0, wins: 0, winRate: null, netCents: 0, t: null, pnlUsd: 0 },
      assembled: { n: 10, wins: 6, winRate: 0.6, netCents: 1, t: 1, pnlUsd: 1 },
      schedule: [
        { bucket: '00:00', start: 0, end: 4, winner: 'Fade', config: {}, train: null, holdout: null },
        { bucket: '04:00', start: 4, end: 8, winner: null, config: null, train: null, holdout: null },
      ],
    });
    expect(ev).toMatchObject({ winner: 'BTC 15m Settlement Sniper', winnerNetCents: null, slots: [{ start: 0, end: 4, name: 'Fade' }] });
  });

  it('rule and agent pushes are read defensively', () => {
    expect(ruleEvent({ rule: { kind: 'stop', ticker: 'KXA' }, message: 'stop hit' }))
      .toEqual({ kind: 'rule', ruleKind: 'stop', ticker: 'KXA', message: 'stop hit' });
    expect(ruleEvent({ rule: null, message: 'x' })).toMatchObject({ ruleKind: null, ticker: null });
    expect(ruleEvent({ message: 3 })).toBeNull();
    expect(agentEvent({ mode: 'live', message: 'wants to BUY', approvalId: 12 }))
      .toMatchObject({ mode: 'live', approvalId: 12, decision: null });
    expect(agentEvent({ mode: 'weird', message: 'm' })).toMatchObject({ mode: 'action', approvalId: null });
  });
});

describe('event → beat mapping', () => {
  const backtest = (over: Partial<Extract<ActivityEvent, { kind: 'backtest' }>> = {}): ActivityEvent => ({
    kind: 'backtest', engine: '15m', strategy: 'Settlement Sniper', days: 30, trades: 412, netCents: 1.6,
    winRatePct: 72.8, totalPnlUsd: 65.9, t: null, equity: [0, 1, 2], ...over,
  });

  it('a backtest says its real numbers', () => {
    const b = beatFor(backtest())!;
    expect(b.room).toBe('backtest');
    expect(b.text).toContain('15m · Settlement Sniper · 30d · 412 trades · +1.6¢/ct ✓');
    expect(b.pass).toBe(true);
    expect(b.series).toEqual([0, 1, 2]);
  });

  it('a losing run fails, a zero-trade run has no verdict, a weak t is called noise', () => {
    expect(beatFor(backtest({ netCents: -0.4 }))!.pass).toBe(false);
    const zero = backtestLine(backtest({ trades: 0, netCents: null }) as Extract<ActivityEvent, { kind: 'backtest' }>);
    expect(zero.pass).toBeNull();
    expect(zero.text).toContain('0 trades');
    expect(beatFor(backtest({ t: 1.1 }))!.text).toContain('noise');
  });

  it('an AI read with no fair value says so rather than inventing one', () => {
    const ev: ActivityEvent = { kind: 'aiAnalysis', ticker: 'KXFED-25DEC', title: 'Will the Fed cut rates?', provider: 'anthropic', verdict: 'unclear', fairCents: null, confidence: 'low' };
    const b = beatFor(ev)!;
    expect(b.room).toBe('research');
    expect(b.text).toBe('🤖 Claude: Fed cut rates · no fair value · unclear');
    expect(beatFor({ ...ev, fairCents: 58, verdict: 'cheap' })!.text).toContain('fair 58¢ · cheap');
  });

  it('paper agent orders never fly to Kalshi; live ones do', () => {
    const paper = beatFor({ kind: 'agent', mode: 'paper', message: 'PAPER buy 5 YES KXA @ 42c avg', approvalId: null, decision: null })!;
    expect(paper.room).toBe('desk');
    expect(paper.capsule).toBe(false);
    const live = beatFor({ kind: 'agent', mode: 'live', message: 'LIVE buy 5 YES KXA @ 42c — Filled', approvalId: null, decision: null })!;
    expect(live.capsule).toBe(true);
  });

  it('agent approvals and Autopilot runs go to the bridge; agent script edits to the forge', () => {
    expect(beatFor({ kind: 'agent', mode: 'live', message: 'wants to BUY', approvalId: 7, decision: null })!.room).toBe('bridge');
    expect(beatFor({ kind: 'agent', mode: 'live', message: 'ok', approvalId: 7, decision: 'approved' })!.text).toContain('#7 approved');
    expect(beatFor({ kind: 'agent', mode: 'action', message: 'Autopilot run finished: 4 steps', approvalId: null, decision: null })!.room).toBe('bridge');
    expect(beatFor({ kind: 'agent', mode: 'action', message: 'saved strategy script X (disabled)', approvalId: null, decision: null })!.room).toBe('forge');
  });

  it('manual orders are labelled MANUAL and carry only what Kalshi answered', () => {
    const b = beatFor({ kind: 'manualOrder', op: 'submit', ok: true, ticker: 'KXBTC15M-X', side: 'yes', action: 'buy', status: 'executed', filled: 5, avgCents: 42, message: 'Filled 5' })!;
    expect(b.text).toContain('MANUAL BUY YES BTC · filled 5× @42¢');
    expect(b.capsule).toBe(true);
    const resting = beatFor({ kind: 'manualOrder', op: 'submit', ok: true, ticker: 'KXBTC15M-X', side: 'no', action: 'buy', status: 'resting', filled: 0, avgCents: null, message: 'resting' })!;
    expect(resting.text).toContain('resting');
    expect(resting.text).not.toContain('@');
    const refused = beatFor({ kind: 'manualOrder', op: 'submit', ok: false, ticker: 'KXA', side: 'yes', action: 'buy', status: null, filled: null, avgCents: null, message: 'over cap' })!;
    expect(refused.capsule).toBeUndefined();
  });

  it('strategy work goes to the forge; a failed apply stages nothing', () => {
    expect(beatFor({ kind: 'script', op: 'saved', name: 'Fade', id: 'a', ok: false, errors: 2, detail: null })!.text).toContain('2 errors — disabled');
    expect(beatFor({ kind: 'script', op: 'enabled', name: 'Fade', id: 'a', ok: true, errors: null, detail: null })!.deploy).toBe(true);
    expect(beatFor({ kind: 'preset', what: 'profile', name: 'Night', ok: true })!.room).toBe('forge');
    expect(beatFor({ kind: 'preset', what: 'profile', name: 'Night', ok: false })).toBeNull();
  });

  it('rules and daily stops go to risk', () => {
    const r = beatFor({ kind: 'rule', ruleKind: 'stop', ticker: 'KXA', message: 'Stop on KXA fired' })!;
    expect(r.room).toBe('vault');
    expect(r.alarm).toBe(true);
    expect(beatFor({ kind: 'halt', scope: 'daily', reason: 'down $50' })!.text).toContain('daily stop: down $50');
  });

  it('a signal handoff is the bot\'s real call, and no reason is invented', () => {
    expect(signalHandoff({ source: 'whale', traded: true }).text).toBe('WHALE → desk');
    expect(signalHandoff({ source: 'momentum', traded: false }).text).toBe('skipped');
    expect(positionSource('script:ab12cd34:whale')).toBe('SCRIPT');
    expect(positionSource('whale')).toBe('BOT');
  });
});

describe('scheduled-runner hour flips', () => {
  const runner = (over: Partial<Crypto15mRunner> = {}): Crypto15mRunner => ({
    id: 'r1', name: 'BTC optimized (1h)', coins: ['BTC'], mode: 'paper', enabled: true, config: {},
    schedule: [
      { startHour: 13, endHour: 14, name: 'BTC 15m Settlement Sniper', config: {} },
      { startHour: 14, endHour: 15, name: 'Contrarian Fade', config: {} },
    ],
    ...over,
  });

  it('reads the slot the backend would run (start ≤ hour < end; none = idle)', () => {
    expect(activeSlots([runner()], 13).get('r1')).toEqual({ runner: 'BTC', name: 'Settlement Sniper' });
    expect(activeSlots([runner()], 15).get('r1')).toEqual({ runner: 'BTC', name: null });
    expect(activeSlots([runner({ enabled: false })], 13).size).toBe(0);
  });

  it('a flip is a change for the same runner, not a runner appearing', () => {
    const a = activeSlots([runner()], 13);
    const b = activeSlots([runner()], 14);
    const flips = scheduleFlips(a, b);
    expect(flips).toEqual([{ runner: 'BTC', name: 'Contrarian Fade' }]);
    expect(flipLine(flips[0], 14)).toBe('⏰ 14:00 UTC BTC → Contrarian Fade');
    expect(scheduleFlips(new Map(), b)).toEqual([]);
  });
});


function fakeWorker(role: Worker['role'], home: string) {
  const w = {
    role, home, free: true, carrying: null as THREE.Object3D | null,
    assigned: 0,
    assign(steps: Step[]) {
      w.assigned++;
      for (const s of steps) if (s.k === 'do') s.fn(w as unknown as Worker);
    },
    pickUp(o: THREE.Object3D) { w.carrying = o; },
    drop() { const o = w.carrying; w.carrying = null; return o; },
    headWorld: (v: THREE.Vector3) => v,
  };
  return w;
}

function fakeStage() {
  const v = () => new THREE.Vector3();
  const ship = {
    ping: vi.fn(), printFlash: vi.fn(), setHoloIdle: vi.fn(), startBacktest: vi.fn(), finishBacktest: vi.fn(),
    backtestRunning: false, setOptimizing: vi.fn(), pushOrder: vi.fn(), fireTube: vi.fn(), stationHit: vi.fn(),
    hatchBlink: vi.fn(), vaultDeposit: vi.fn(), anvilHit: vi.fn(), binPuff: vi.fn(),
    tubeInside: v(), kalshiPos: v(), hatchPos: v(), station: { position: v() },
    rackSlots: [v(), v(), v(), v()], outboxSlots: [v(), v(), v()], airlockSlots: [v(), v(), v(), v()],
    mossyHop: 0, alarm: 0,
  };
  const obj = () => new THREE.Object3D();
  const crew = [
    fakeWorker('researcher', 'research.scanA'), fakeWorker('smith', 'forge.furnace'), fakeWorker('quant', 'backtest.tableB'),
    fakeWorker('trader', 'desk.termA'), fakeWorker('keeper', 'vault.idle'), fakeWorker('risk', 'vault.risk'),
    fakeWorker('engineer', 'optimizer.panel'),
  ];
  const stage = {
    ship, crew, root: new THREE.Object3D(),
    kit: { card: obj, chip: obj, tablet: obj, capsule: obj, bag: obj, setChipColor: vi.fn() },
    flights: { launch: vi.fn() }, sparks: { burst: vi.fn() },
    pile: { add: vi.fn(), top: (o: THREE.Vector3) => o },
    say: vi.fn(() => true), log: vi.fn(), activity: vi.fn(),
  };
  return { stage: stage as unknown as Stage, ship, crew, say: stage.say, log: stage.log };
}

const EMPTY = { signals: [] as SignalRow[], positions: [], account: null as AccountSnapshot | null, scannerStats: null };

function run(d: Director, seconds: number, dt = 0.05) {
  for (let t = 0; t < seconds; t += dt) d.update(dt);
}

describe('director: no timers create work', () => {
  it('with zero events it stages nothing, however long it runs', () => {
    const { stage, ship, crew, say, log } = fakeStage();
    const d = new Director(stage, { now: () => Date.UTC(2026, 9, 6, 13, 30) });
    d.ingest({ ...EMPTY, config: { crypto15mRunners: [] } as unknown as TraderConfig, library: [] });
    run(d, 600);
    expect(say).not.toHaveBeenCalled();
    expect(log).not.toHaveBeenCalled();
    expect(ship.startBacktest).not.toHaveBeenCalled();
    expect(ship.setOptimizing).not.toHaveBeenCalled();
    expect(ship.pushOrder).not.toHaveBeenCalled();
    expect(ship.fireTube).not.toHaveBeenCalled();
    expect(crew.every((w) => w.assigned === 0)).toBe(true);
    expect(ship.setHoloIdle).toHaveBeenCalledWith('BACKTEST', 'idle · no saved runs');
  });

  it('a saved library is a still readout, never a re-run', () => {
    const { stage, ship, say } = fakeStage();
    const d = new Director(stage);
    d.ingest({ ...EMPTY, library: [{ name: 'Sniper', net: 1.8, t: 2.5, n: 300 }] });
    run(d, 120);
    expect(ship.startBacktest).not.toHaveBeenCalled();
    expect(say).not.toHaveBeenCalled();
    expect(ship.setHoloIdle).toHaveBeenLastCalledWith('SAVED · BEST', 'Sniper +1.8¢ ✓');
    expect(d.backtestSign).toBe('1/1 edge');
  });

  it('a real backtest plays its real curve and says its real numbers', () => {
    const { stage, ship, say } = fakeStage();
    const d = new Director(stage);
    d.ingest(EMPTY);
    const ev = backtestEvent('15m', 'Settlement Sniper', 30, bt())!;
    d.activity({ seq: 1, at: Date.now(), ev });
    run(d, 1);
    expect(ship.startBacktest).toHaveBeenCalledTimes(1);
    expect(ship.startBacktest.mock.calls[0][0]).toEqual((ev as { equity: number[] }).equity);
    expect(ship.finishBacktest).toHaveBeenCalledWith(true, '+1.6¢/ct ✓');
    expect(say.mock.calls.some((c) => String(c[1]).includes('412 trades · +1.6¢/ct ✓'))).toBe(true);
    expect(d.backtestSign).toBe('last +1.6¢/ct ✓');
    run(d, 120);
    expect(ship.startBacktest).toHaveBeenCalledTimes(1);
  });

  it('a replayed event says how long ago it happened', () => {
    const { stage, log } = fakeStage();
    const now = 1_000_000_000;
    const d = new Director(stage, { now: () => now });
    d.ingest(EMPTY);
    d.activity({ seq: 1, at: now - 90_000, ev: { kind: 'preset', what: 'strategy', name: 'Sniper', ok: true } }, true);
    run(d, 1);
    expect(log.mock.calls.some((c) => String(c[0]).endsWith('· 2m ago'))).toBe(true);
  });

  it('a scheduled runner flipping at the top of the hour is staged once', () => {
    const { stage, ship, log } = fakeStage();
    let now = Date.UTC(2026, 9, 6, 13, 59, 58);
    const d = new Director(stage, { now: () => now });
    const config = {
      crypto15mRunners: [{
        id: 'r1', name: 'BTC', coins: ['BTC'], mode: 'paper', enabled: true, config: {},
        schedule: [
          { startHour: 13, endHour: 14, name: 'Settlement Sniper', config: {} },
          { startHour: 14, endHour: 15, name: 'Contrarian Fade', config: {} },
        ],
      }],
    } as unknown as TraderConfig;
    d.ingest({ ...EMPTY, config });
    run(d, 1.2);
    expect(log).not.toHaveBeenCalled();
    now = Date.UTC(2026, 9, 6, 14, 0, 1);
    run(d, 2);
    expect(log).toHaveBeenCalledWith('⏰ 14:00 UTC BTC → Contrarian Fade', 'opt');
    expect(ship.setOptimizing).toHaveBeenCalledWith(true);
    run(d, 60);
    expect(log).toHaveBeenCalledTimes(1);
  });

  it('a new untraded signal is "skipped", a traded one goes to the desk', () => {
    const { stage, say } = fakeStage();
    const d = new Director(stage);
    const sig = (id: number, traded: boolean): SignalRow => ({
      id, source: 'whale', ticker: 'KXNBA-LAL', eventTicker: 'KXNBA', title: 'Will the Lakers win?', category: 'Sports',
      direction: 'yes', priceCents: 40, confidence: 60, edgePts: 5, dollarValue: 22000, createdAt: '', resolved: false,
      outcomeCorrect: null, pnlEstimate: null, traded,
    });
    d.ingest(EMPTY);
    d.ingest({ ...EMPTY, signals: [sig(1, false)] });
    run(d, 0.5);
    expect(say.mock.calls.some((c) => c[1] === 'skipped')).toBe(true);
    d.ingest({ ...EMPTY, signals: [sig(2, true), sig(1, false)] });
    run(d, 0.5);
    expect(say.mock.calls.some((c) => c[1] === 'WHALE → desk')).toBe(true);
  });
});

describe('council: the Quant cites only a real AI read', () => {
  it('quotes the analysis for that ticker, and nothing for another', () => {
    const c = new Council({} as CouncilHost);
    const now = Date.UTC(2026, 9, 6, 12, 0);
    c.noteAnalysis({ kind: 'aiAnalysis', ticker: 'KXFED', title: null, provider: 'anthropic', verdict: 'cheap', fairCents: 58, confidence: 'medium' }, now - 12 * 60_000);
    expect(c.aiCite('KXFED', now)).toBe('Claude, 12m ago: fair 58¢ · cheap');
    expect(c.aiCite('KXOTHER', now)).toBeNull();
    expect(c.aiCite('KXFED', now + 2 * 24 * 3600_000)).toBeNull();
  });
});
