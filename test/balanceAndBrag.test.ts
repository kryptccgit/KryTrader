import { describe, expect, it } from 'vitest';
import type { AccountSnapshot } from '@shared/types';
import { balanceView } from '../src/utils/balance';
import { bragText, PAPER_TAG } from '../src/utils/brag';
import { fmtTokens, hitRate, winRatePct } from '../src/utils/stats';
import { resetSummaryWords } from '../src/utils/resetSummary';
import { effectiveAgentMode } from '@shared/agents';
import { TRAY_HINT, trayTradingAction, trayTradingLabel } from '../electron/system/tray-logic';

const snap = (p: Partial<AccountSnapshot> = {}): AccountSnapshot => ({
  cashUsd: 900, portfolioUsd: 100, totalUsd: 1000, startBankrollUsd: 1000, roiPct: 0,
  realizedPnlUsd: 0, unrealizedPnlUsd: 0, openCostUsd: 0, feesUsd: 0, wins: 0, losses: 0, winRate: 0,
  pendingCount: 0, openCount: 0, resolvedCount: 0, totalOpened: 0, accountMode: 'paper',
  byEnv: { paper: { wins: 0, losses: 0, realizedPnl: 0 }, production: { wins: 0, losses: 0, realizedPnl: 0 } },
  alltimePnlUsd: 0, alltimeBaselineUsd: 1000, sessionPnlUsd: 0, sessionBaselineUsd: 1000, sessionRoiPct: 0,
  ...p,
});

describe('balanceView: an unknown balance is a dash, never $0.00', () => {
  const paper = { config: { accountMode: 'paper' as const }, authOk: false, hasKeys: false };
  const live = { config: { accountMode: 'live' as const }, authOk: false, hasKeys: false };

  it('no snapshot (engine down or starting) is unknown, with every delta', () => {
    const v = balanceView(null, paper);
    expect(v.known).toBe(false);
    expect([v.totalUsd, v.sessionPnlUsd, v.alltimePnlUsd, v.roiPct]).toEqual([null, null, null, null]);
    expect(v.why).toMatch(/starting or stopped/);
  });

  it('the QA case: Live with no key and a $0.00 placeholder makes no all-time P&L', () => {
    const v = balanceView(snap({ accountMode: 'live', cashUsd: 0, portfolioUsd: 0, totalUsd: 0, alltimePnlUsd: -1.18, alltimeBaselineUsd: 1.18 }), live);
    expect(v.known).toBe(false);
    expect(v.alltimePnlUsd).toBeNull();
    expect(v.why).toMatch(/No Kalshi key/);
  });

  it('Live with a key that did not authenticate is unknown', () => {
    expect(balanceView(snap({ accountMode: 'live' }), { ...live, hasKeys: true }).why).toMatch(/not accepted/);
  });

  it('a snapshot from the other book (mid Paper ↔ Live switch) is unknown', () => {
    expect(balanceView(snap({ accountMode: 'paper' }), { ...live, authOk: true, hasKeys: true }).known).toBe(false);
  });

  it('a snapshot kept from before the engine stopped is not the balance now', () => {
    expect(balanceView(snap(), { ...paper, engineRunning: false }).known).toBe(false);
    expect(balanceView(snap(), { ...paper, engineRunning: true }).known).toBe(true);
  });

  it('the backend can say so itself', () => {
    expect(balanceView(snap({ balanceKnown: false }), paper).known).toBe(false);
  });

  it('Paper needs no key: its balance is known', () => {
    const v = balanceView(snap({ totalUsd: 1042.1, alltimePnlUsd: 42.1 }), paper);
    expect(v.known).toBe(true);
    expect(v.totalUsd).toBe(1042.1);
    expect(v.alltimePnlUsd).toBe(42.1);
  });

  it('a delta with no baseline yet is unknown, not zero', () => {
    const v = balanceView(snap({ alltimeBaselineUsd: null, sessionBaselineUsd: 0 }), paper);
    expect(v.known).toBe(true);
    expect(v.alltimePnlUsd).toBeNull();
    expect(v.sessionPnlUsd).toBeNull();
    expect(v.sessionRoiPct).toBeNull();
  });

  it('Live, keyed and authenticated is known', () => {
    expect(balanceView(snap({ accountMode: 'live' }), { config: { accountMode: 'live' }, authOk: true, hasKeys: true }).known).toBe(true);
  });
});

describe('share text says paper', () => {
  it('tags every non-Live brag once, right after the name', () => {
    expect(bragText('Krypt Trader balance: $1,000.00.', false)).toBe(`Krypt Trader ${PAPER_TAG} balance: $1,000.00.`);
    expect(bragText('This session on Krypt Trader: +$4.00', false)).toContain(`Krypt Trader ${PAPER_TAG}`);
    expect(bragText('3 out of 4 sessions ended green', false)).toBe(`${PAPER_TAG} 3 out of 4 sessions ended green`);
    const once = bragText('Krypt Trader x', false);
    expect(bragText(once, false)).toBe(once);
  });

  it('leaves Live text alone', () => {
    expect(bragText('Krypt Trader balance: $5', true)).toBe('Krypt Trader balance: $5');
  });
});

describe('counted or dash', () => {
  it('hit rate over zero settled signals is a dash', () => {
    expect(hitRate({ resolved: 0, winRate: 0 })).toBe('—');
    expect(hitRate(null)).toBe('—');
    expect(hitRate({ resolved: 4, winRate: 75 })).toBe('75.0%');
  });

  it('win rate over zero decided trades is null', () => {
    expect(winRatePct(0, 0)).toBeNull();
    expect(winRatePct(undefined, null)).toBeNull();
    expect(winRatePct(3, 1)).toBe(75);
  });

  it('tokens: none reported is a dash; an estimate says so', () => {
    expect(fmtTokens(null, null)).toBe('—');
    expect(fmtTokens(1000, null)).toBe(`${(1000).toLocaleString()} tok`);
    expect(fmtTokens(10, 5, true)).toBe('~15 tok (estimated)');
  });
});

describe('reset summary in words', () => {
  it('names tables for what they mean, never as table names', () => {
    const s = resetSummaryWords({ bot_positions: 12, pnl_snapshots: 1, mcp_actions: 0, _errors: 3, new_thing: 2 });
    expect(s).toBe('12 bot trades, 1 balance snapshot and 2 new thing');
    expect(s).not.toMatch(/_/);
    expect(resetSummaryWords({})).toBe('nothing');
  });
});

describe('agent mode under the account mode', () => {
  const live = { mode: 'live' } as never;
  it('an agent set to live trades paper while the app is in Paper', () => {
    expect(effectiveAgentMode('live', live, 'paper')).toBe('paper');
    expect(effectiveAgentMode('live', live, 'live')).toBe('live');
    expect(effectiveAgentMode('off', live, 'live')).toBe('off');
    expect(effectiveAgentMode('live', live)).toBe('live');
  });
});

describe('tray trading item', () => {
  it('pause is always direct; resume arms Paper directly but only OPENS the app in Live', () => {
    expect(trayTradingAction(true, true)).toBe('pause');
    expect(trayTradingAction(true, false)).toBe('pause');
    expect(trayTradingAction(false, false)).toBe('resume');
    expect(trayTradingAction(false, true)).toBe('open');
    expect(trayTradingLabel(false, true)).toMatch(/opens the app/);
    expect(trayTradingLabel(false, false)).toMatch(/Paper/);
  });

  it('the close-to-tray notice says how to really quit', () => {
    expect(TRAY_HINT.body).toMatch(/Quit/);
    expect(TRAY_HINT.body).toMatch(/tray/);
  });
});
