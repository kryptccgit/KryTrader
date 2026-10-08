import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AccountSnapshot, BotPosition, TraderConfig } from '@shared/types';
import { defaultAgent } from '@shared/agents';


const app = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn(), push: vi.fn() }));
vi.mock('../src/state/AppStateProvider', () => ({ useApp: () => app.value }));
vi.mock('../src/state/ToastProvider', () => ({ useToast: () => toast }));

const flush = async (): Promise<void> => { await act(async () => { await Promise.resolve(); await Promise.resolve(); }); };

const snap = (p: Partial<AccountSnapshot> = {}): AccountSnapshot => ({
  cashUsd: 0, portfolioUsd: 0, totalUsd: 0, startBankrollUsd: 1.18, roiPct: -100,
  realizedPnlUsd: 0, unrealizedPnlUsd: 0, openCostUsd: 0, feesUsd: 0, wins: 0, losses: 0, winRate: 0,
  pendingCount: 0, openCount: 0, resolvedCount: 0, totalOpened: 0, accountMode: 'live',
  byEnv: { paper: { wins: 0, losses: 0, realizedPnl: 0 }, production: { wins: 0, losses: 0, realizedPnl: 0 } },
  alltimePnlUsd: -1.18, alltimeBaselineUsd: 1.18, sessionPnlUsd: -1.18, sessionBaselineUsd: 1.18, sessionRoiPct: -100,
  ...p,
});

const pos = (p: Partial<BotPosition>): BotPosition => ({
  id: 1, signalSource: 'whale', signalId: 1, ticker: 'KXA-1', eventTicker: 'KXA', title: 'A market',
  category: 'x', direction: 'yes', action: 'buy', targetContracts: 1, limitPriceCents: 50, filledContracts: 1,
  avgFillPriceCents: 50, costUsd: 0.5, feesUsd: 0, clientOrderId: 'c', kalshiOrderId: null, status: 'filled',
  confidence: 60, edgePts: 6, signalPriceCents: 50, resolved: false, outcomeCorrect: null, settlementUsd: null,
  pnlUsd: null, markPriceCents: null, livePnlUsd: null, balanceBeforeUsd: null, kalshiEnv: 'paper',
  createdAt: new Date().toISOString(), lastUpdated: new Date().toISOString(), resolvedAt: null, error: null,
  ...p,
});

beforeAll(() => {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  HTMLCanvasElement.prototype.getContext = (() => null) as never;
  const g = globalThis as unknown as { CSS?: { escape?: (s: string) => string } };
  g.CSS = { ...(g.CSS ?? {}), escape: (s: string) => s.replace(/[^\w-]/g, (c) => `\\${c}`) };
});

beforeEach(() => {
  for (const f of Object.values(toast)) f.mockClear();
  (window as unknown as { krypt: unknown }).krypt = {
    data: {
      pnlSeries: vi.fn(async () => []),
      positions: vi.fn(async () => { throw new Error('backend down'); }),
    },
    backend: { runOnce: vi.fn() },
    trading: { cancelAllOpen: vi.fn() },
    terminal: {
      onMcpToolCall: vi.fn(() => () => {}),
      mcpSeen: vi.fn(async () => ({ clients: [] })),
      mcpCopyConfig: vi.fn(async () => ({ ok: true })),
      mcpInstallConfig: vi.fn(async () => ({ ok: true, message: 'Added to Claude Desktop. Now fully quit Claude Desktop.', files: ['x'], backups: [] })),
      mcpOpenConfigFolder: vi.fn(async () => ({ ok: true })),
      agentsClosePaper: vi.fn(async () => ({ closed: 2 })),
      preview: vi.fn(async () => ({ blockers: [], warnings: [], costUsd: 0.5, feeUsd: 0.01, totalUsd: 0.51, maxPayoutUsd: 1, breakevenProb: 0.5, maxProfitUsd: null, restingBestCents: null, marketableNow: false })),
      submit: vi.fn(),
    },
    config: { update: vi.fn(async () => ({})) },
    state: { acceptDisclaimer: vi.fn(async () => ({ ok: true })) },
    app: { openExternal: vi.fn() },
  };
});
afterEach(() => { vi.useRealTimers(); });

describe('an unknown balance is a dash (QA: "All-time P&L −$1.18" with no key)', () => {
  it('Dashboard: Live with no key shows no balance and computes no P&L from it', async () => {
    app.value = {
      account: snap(), scannerStats: { whales: { total: 3, sent: 0, resolved: 0, winRate: 0 }, momentum: { total: 0, sent: 0, resolved: 0, winRate: 0 }, marketsTracked: 0, lastWhaleScanAt: null, lastMomentumScanAt: null, lastTradeScanAt: null },
      signals: [], positions: [], backend: { status: 'running', authOk: false },
      credentialsAll: { current: 'paper', production: { env: 'production', hasApiKey: false, hasRsaKey: false, apiKeyPreview: '', fingerprint: '' } },
      config: { accountMode: 'live', enableTrading: false, maxOpenPositions: 25 },
    };
    const { DashboardPage } = await import('../src/pages/Dashboard');
    render(<DashboardPage onNav={vi.fn()} />);
    await flush();
    const text = document.body.textContent ?? '';
    expect(text).not.toContain('-$1.18');
    expect(text).not.toContain('$0.00');
    expect(text).toMatch(/No Kalshi key saved/);
    expect(screen.getByText('Whales hit').nextSibling?.textContent).toBe('—');
  }, 30_000);

  it('Sidebar wallet and top bar say unknown while the engine is down', async () => {
    app.value = {
      account: null, config: { accountMode: 'paper' }, backend: { status: 'stopped', authOk: false },
      credentialsAll: null, refresh: { account: vi.fn(), backend: vi.fn() },
    };
    const { TopBar } = await import('../src/components/TopBar');
    render(<TopBar />);
    expect(document.body.textContent).not.toContain('$0.00');
    expect(screen.getByText('Balance').nextSibling?.textContent).toBe('—');
  });
});

describe('Positions: one book at a time, every row says which', () => {
  it('defaults to the current book and badges rows; All books shows both, labelled', async () => {
    app.value = {
      positions: [
        pos({ id: 1, kalshiEnv: 'paper', title: 'Paper thing' }),
        pos({ id: 2, kalshiEnv: 'production', title: 'Real thing' }),
      ],
      refresh: { positions: vi.fn(), account: vi.fn() },
      config: { accountMode: 'paper' },
    };
    const { PositionsPage } = await import('../src/pages/Positions');
    render(<PositionsPage />);
    await flush();
    expect(screen.queryByText('Real thing')).toBeNull();
    expect(screen.getByText('Paper thing')).toBeTruthy();
    expect(screen.getAllByTestId('position-book').map((b) => b.textContent)).toEqual(['PAPER']);
    const row = screen.getByText('Paper thing').closest('tr')!;
    expect(within(row).queryByText('live')).toBeNull();
    expect(within(row).getByText('open')).toBeTruthy();

    fireEvent.click(screen.getByTestId('positions-book-all'));
    await flush();
    expect(screen.getAllByTestId('position-book').map((b) => b.textContent).sort()).toEqual(['LIVE', 'PAPER']);
    expect(screen.getByText('Manual')).toBeTruthy();
  });
});

describe('agents', () => {
  const sam = { ...defaultAgent('paper'), id: 'sam', name: 'Sports Sam' };

  it('deleting the agent Autopilot runs as turns Autopilot off, and can close its paper positions', async () => {
    const patch = vi.fn(async () => {});
    const config = {
      accountMode: 'paper', mcpTradeMode: 'paper', mcpAgents: [defaultAgent('paper'), sam],
      autopilotAgentId: 'sam', autopilotEnabled: true,
    } as Partial<TraderConfig>;
    const { AgentsSection } = await import('../src/components/agents/AgentsSection');
    render(<AgentsSection config={config} status={null} board={null}
      activity={{ paperByAgent: { sam: { agentId: 'sam', realizedUsd: 0, unrealizedUsd: 0, openPositions: 2, fills: 3 } }, orders: [] } as never}
      patch={patch} />);
    const card = document.querySelector('[data-qa="agent-card-sam"]') as HTMLElement;
    expect(within(card).getByText('Forecasts').nextSibling?.textContent).toBe('—');

    fireEvent.click(document.querySelector('[data-qa="agent-delete-sam"]')!);
    expect(screen.getByText(/Autopilot will be switched off/)).toBeTruthy();
    fireEvent.click(within(document.querySelector('[data-qa="agent-close-paper"]') as HTMLElement).getByRole('checkbox'));
    const dialog = screen.getByText(/Autopilot will be switched off/).closest('[role="dialog"]') as HTMLElement ?? document.body;
    const del = within(dialog).getAllByRole('button', { name: 'Delete' });
    fireEvent.click(del[del.length - 1]);
    await flush();
    const k = (window as unknown as { krypt: { terminal: Record<string, ReturnType<typeof vi.fn>> } }).krypt;
    expect(k.terminal.agentsClosePaper).toHaveBeenCalledWith({ agentId: 'sam' });
    expect(patch).toHaveBeenCalledTimes(1);
    const sent = (patch.mock.calls[0] as unknown[])[0] as Record<string, unknown>;
    expect(sent.autopilotEnabled).toBe(false);
    expect((sent.mcpAgents as { id: string }[]).map((a) => a.id)).toEqual(['default']);
  });

  it('an agent set to live shows Paper while the app is in Paper', async () => {
    const liveSam = { ...sam, mode: 'live' as const };
    const config = { accountMode: 'paper', mcpTradeMode: 'live', mcpAgents: [defaultAgent('paper'), liveSam] } as Partial<TraderConfig>;
    const { AgentsSection } = await import('../src/components/agents/AgentsSection');
    render(<AgentsSection config={config} status={null} board={null} activity={null} patch={vi.fn()} />);
    const card = document.querySelector('[data-qa="agent-card-sam"]') as HTMLElement;
    expect(within(card).queryByText('Live')).toBeNull();
    expect(within(card).getByTitle(/trades paper until the app is Live/).textContent).toMatch(/^Paper/);
  });
});

describe('Connect: one click for Claude Desktop, and a hint when nothing calls back', () => {
  it('Add to Claude Desktop goes through main (no config text in the renderer), then hints after a minute', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    app.value = {
      config: { mcpEnabled: true, mcpTradeMode: 'paper', accountMode: 'paper' },
      backend: { status: 'running', authOk: false }, refresh: { state: vi.fn(async () => {}) },
    };
    const { ConnectAgent } = await import('../src/components/ConnectAgent');
    render(<ConnectAgent onAutopilot={vi.fn()} hideAutopilot />);
    fireEvent.click(screen.getByRole('button', { name: 'Claude Desktop' }));
    fireEvent.click(screen.getByTestId('connect-install'));
    await flush();
    const k = (window as unknown as { krypt: { terminal: Record<string, ReturnType<typeof vi.fn>> } }).krypt;
    expect(k.terminal.mcpInstallConfig).toHaveBeenCalledWith({ client: 'claude-desktop', agentId: 'default' });
    expect(screen.getByText('Open config folder')).toBeTruthy();
    expect(screen.queryByTestId('connect-wait-hint')).toBeNull();
    await act(async () => { vi.advanceTimersByTime(61_000); });
    expect(screen.getByTestId('connect-wait-hint').textContent).toMatch(/Restart Claude Desktop after adding/);
  });
});

describe('TradeTicket sends the mode it was priced under', () => {
  it('expectMode rides on preview and submit; a mismatch says the app switched', async () => {
    app.value = { config: { accountMode: 'paper' } };
    const k = (window as unknown as { krypt: { terminal: Record<string, ReturnType<typeof vi.fn>> } }).krypt;
    k.terminal.submit.mockRejectedValueOnce(new Error("Error invoking remote method 'terminal:submit': Error: [mode_mismatch] The app is Live now."));
    const { TradeTicket } = await import('../src/components/terminal/TradeTicket');
    render(<TradeTicket
      market={{ ticker: 'KXA-1', title: 'A' } as never}
      book={{ yesAsk: 40, yesBid: 38 } as never}
      position={null} onDone={vi.fn()} />);
    await act(async () => { await new Promise((r) => setTimeout(r, 300)); });
    expect(k.terminal.preview).toHaveBeenCalled();
    expect(k.terminal.preview.mock.calls.at(-1)?.[0]).toMatchObject({ ticker: 'KXA-1', expectMode: 'paper' });
    fireEvent.click(screen.getByRole('button', { name: /Buy 1 YES/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await flush();
    expect(k.terminal.submit.mock.calls[0][0]).toMatchObject({ expectMode: 'paper' });
    expect(toast.push).toHaveBeenCalledWith('The app switched to Paper — check the ticket again.', 'warn', 9000);
    expect(toast.error).not.toHaveBeenCalled();
  });
});

describe('setup that crashes still lets you in', () => {
  it('first run: "Accept and skip setup" records the disclaimer and closes', async () => {
    vi.doMock('../src/pages/Onboarding', () => ({
      OnboardingModal: () => { throw new Error('boom'); },
    }));
    vi.resetModules();
    const { GuideHost } = await import('../src/components/tour/GuideHost');
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<GuideHost needsOnboarding setPage={vi.fn()}><div>app</div></GuideHost>);
    expect(screen.getByTestId('setup-crash')).toBeTruthy();
    expect(screen.getByText('app')).toBeTruthy();
    fireEvent.click(screen.getByTestId('setup-crash-skip'));
    await flush();
    const k = (window as unknown as { krypt: { state: { acceptDisclaimer: ReturnType<typeof vi.fn> } } }).krypt;
    expect(k.state.acceptDisclaimer).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('setup-crash')).toBeNull();
    err.mockRestore();
    vi.doUnmock('../src/pages/Onboarding');
  });
});
