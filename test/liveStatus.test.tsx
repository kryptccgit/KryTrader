import { act, render, renderHook, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TraderConfig } from '@shared/types';
import { armedEngines, liveSwitchMessage } from '../src/utils/liveEngines';


const app = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn(), push: vi.fn() }));
vi.mock('../src/state/AppStateProvider', () => ({ useApp: () => app.value }));
vi.mock('../src/state/ToastProvider', () => ({ useToast: () => toast }));

const base: Partial<TraderConfig> = {
  accountMode: 'live', enableTrading: false,
  crypto15mEnabled: false, crypto15mLive: false, crypto15mRunners: null,
  mcpEnabled: false, mcpTradeMode: 'paper', mcpLiveApproval: true, autopilotEnabled: false,
  scriptsLiveEnabled: false, scriptsPaperMode: false, perpsFarmEnabled: false,
  remoteTradingEnabled: false, remoteDiscordEnabled: false, remoteTelegramEnabled: false,
};
const cfg = (p: Partial<TraderConfig>): Partial<TraderConfig> => ({ ...base, ...p });
const ids = (c: Partial<TraderConfig>, mode?: 'paper' | 'live') => armedEngines(c, mode).map((e) => e.id);

describe('armedEngines', () => {
  it('is empty with every arm off', () => {
    expect(armedEngines(cfg({}))).toEqual([]);
    expect(armedEngines(null)).toEqual([]);
  });

  it('sees every engine that trades by itself, not just the main bot', () => {
    expect(ids(cfg({
      crypto15mEnabled: true, crypto15mLive: true,
      mcpEnabled: true, mcpTradeMode: 'live',
      scriptsLiveEnabled: true, perpsFarmEnabled: true,
    }))).toEqual(['15m', 'agents', 'scripts', 'perps']);
  });

  it('counts the live Multi-Run runners, ignoring paper and disabled ones', () => {
    const runners = [
      { id: 'a', name: 'a', coins: null, mode: 'live', enabled: true, config: {} },
      { id: 'b', name: 'b', coins: null, mode: 'paper', enabled: true, config: {} },
      { id: 'c', name: 'c', coins: null, mode: 'live', enabled: false, config: {} },
    ] as TraderConfig['crypto15mRunners'];
    expect(armedEngines(cfg({ crypto15mEnabled: true, crypto15mRunners: runners }))).toEqual([]);
    const e = armedEngines(cfg({ crypto15mEnabled: true, crypto15mLive: true, crypto15mRunners: runners }));
    expect(e.map((x) => x.label)).toEqual(['15-minute crypto: 1 live runner']);
    expect(ids(cfg({ crypto15mEnabled: true, crypto15mLive: true, crypto15mRunners: runners.slice(1, 2) }))).toEqual([]);
  });

  it('leaves out what does not place orders: scripts in Paper mode, agents on paper, the 15m in Paper', () => {
    expect(ids(cfg({ scriptsLiveEnabled: true, scriptsPaperMode: true }))).toEqual([]);
    expect(ids(cfg({ mcpEnabled: true, mcpTradeMode: 'paper' }))).toEqual([]);
    expect(ids(cfg({ accountMode: 'paper', crypto15mEnabled: true, crypto15mLive: true }))).toEqual([]);
  });

  it('counts Autopilot as an agent: it trades through the agent tools without the listener', () => {
    const e = armedEngines(cfg({ autopilotEnabled: true, mcpTradeMode: 'live', mcpLiveApproval: false }));
    expect(e.map((x) => x.id)).toEqual(['agents']);
    expect(e[0].label).toContain('approval OFF');
    expect(e[0].label).toContain('Autopilot on');
  });

  describe('named agents', () => {
    const agents = [
      { id: 'default', name: 'Default', mode: 'paper', enabled: true },
      { id: 'sam1', name: 'Sports Sam', mode: 'live', enabled: true },
      { id: 'res1', name: 'Careful Researcher', mode: 'live', enabled: false },
      { id: 'bob1', name: 'Bob', mode: 'paper', enabled: true },
    ] as unknown as TraderConfig['mcpAgents'];

    it('is live only with the global mode live AND an enabled agent set to live, and names them', () => {
      const e = armedEngines(cfg({ mcpEnabled: true, mcpTradeMode: 'live', mcpAgents: agents }));
      expect(e.map((x) => x.id)).toEqual(['agents']);
      expect(e[0].label).toMatch(/^AI agents LIVE: Sports Sam \(/);
      expect(e[0].label).not.toContain('Careful Researcher');
      expect(ids(cfg({ mcpEnabled: true, mcpTradeMode: 'paper', mcpAgents: agents }))).toEqual([]);
      const allPaper = agents!.map((a) => ({ ...a, mode: 'paper' as const }));
      expect(ids(cfg({ mcpEnabled: true, mcpTradeMode: 'live', mcpAgents: allPaper }))).toEqual([]);
    });

    it('with only Autopilot reaching the app, only Autopilot\'s agent counts', () => {
      const base2 = { mcpEnabled: false, autopilotEnabled: true, mcpTradeMode: 'live' as const, mcpAgents: agents };
      expect(ids(cfg({ ...base2, autopilotAgentId: 'bob1' }))).toEqual([]);
      const e = armedEngines(cfg({ ...base2, autopilotAgentId: 'sam1' }));
      expect(e[0].label).toContain('Sports Sam');
    });
  });
});

describe('the Paper -> Live confirm', () => {
  it('names every arm that becomes real money: 15m LIVE, scripts, agents, perps farmer, remote trading', () => {
    const msg = liveSwitchMessage(cfg({
      accountMode: 'paper',
      crypto15mEnabled: true, crypto15mLive: true,
      scriptsLiveEnabled: true,
      mcpEnabled: true, mcpTradeMode: 'live',
      perpsFarmEnabled: true,
      remoteTradingEnabled: true, remoteTelegramEnabled: true,
    }));
    expect(msg).toContain('15-minute crypto: Real orders (LIVE)');
    expect(msg).toContain('Scripts: live');
    expect(msg).toContain('AI agents LIVE: Default');
    expect(msg).toContain('Perps volume farmer');
    expect(msg).toContain('Remote trading');
    expect(msg).not.toContain('Main bot');
  });

  it('includes the main bot when it is on, and says so plainly when nothing is armed', () => {
    expect(liveSwitchMessage(cfg({ accountMode: 'paper', enableTrading: true }))).toContain('Main bot: auto-trading on');
    expect(liveSwitchMessage(cfg({ accountMode: 'paper' }))).toContain('Nothing is armed');
  });

  it('ignores remote trading permission with no chat bot switched on', () => {
    expect(liveSwitchMessage(cfg({ remoteTradingEnabled: true }))).not.toContain('Remote trading');
  });
});

describe('the app-wide status', () => {
  beforeEach(() => { app.value = {}; });

  it('says PAUSED only when nothing is armed', async () => {
    const { EngineStatus } = await import('../src/components/Sidebar');
    app.value = { config: cfg({}) };
    render(<EngineStatus />);
    expect(screen.getByText('PAUSED')).toBeTruthy();
  });

  it('says LIVE and names the engines while the main bot is paused', async () => {
    const { EngineStatus } = await import('../src/components/Sidebar');
    app.value = { config: cfg({ crypto15mEnabled: true, crypto15mLive: true, mcpEnabled: true, mcpTradeMode: 'live', scriptsLiveEnabled: true }) };
    render(<EngineStatus />);
    const el = screen.getByText('LIVE · 15m · agents · scripts');
    expect(el.getAttribute('title')).toContain('REAL money');
    expect(el.getAttribute('title')).toContain('AI agents LIVE: Default');
  });

  it('says PAPER, not LIVE, for engines trading imaginary money', async () => {
    const { EngineStatus } = await import('../src/components/Sidebar');
    app.value = { config: cfg({ accountMode: 'paper', enableTrading: true, scriptsLiveEnabled: true }) };
    render(<EngineStatus />);
    expect(screen.getByText('PAPER · bot · scripts')).toBeTruthy();
  });

  it('the top bar pill lists the real-money engines and is absent otherwise', async () => {
    const { LiveEnginesPill } = await import('../src/components/TopBar');
    const { container, rerender } = render(<LiveEnginesPill engines={[]} />);
    expect(container.textContent).toBe('');
    rerender(<LiveEnginesPill engines={armedEngines(cfg({ perpsFarmEnabled: true, enableTrading: true }))} />);
    expect(screen.getByRole('status').textContent).toBe('LIVE · bot · perps');
  });
});

describe('Scripts: leaving Paper mode', () => {
  it('asks, naming the account, when Scripts live is armed; a cancel keeps paper', async () => {
    const { confirmLeavePaperMode } = await import('../src/pages/Scripts');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    expect(confirmLeavePaperMode(cfg({ scriptsLiveEnabled: true, scriptsPaperMode: true }))).toBe(false);
    expect(confirm.mock.calls[0][0]).toContain('REAL orders on your Kalshi account');
  });

  it('does not ask in Paper: the app places no real order there', async () => {
    const { confirmLeavePaperMode } = await import('../src/pages/Scripts');
    const confirm = vi.spyOn(window, 'confirm');
    confirm.mockClear();
    expect(confirmLeavePaperMode(cfg({ accountMode: 'paper', scriptsLiveEnabled: true, scriptsPaperMode: true }))).toBe(true);
    expect(confirm).not.toHaveBeenCalled();
  });

  it('lets it through without asking when nothing is armed', async () => {
    const { confirmLeavePaperMode } = await import('../src/pages/Scripts');
    const confirm = vi.spyOn(window, 'confirm');
    expect(confirmLeavePaperMode(cfg({ scriptsLiveEnabled: false, scriptsPaperMode: true }))).toBe(true);
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe('turning the main bot on from anywhere', () => {
  const setEnabled = vi.fn();
  beforeEach(() => {
    setEnabled.mockReset();
    Object.values(toast).forEach((f) => f.mockReset());
    (window as unknown as { krypt: unknown }).krypt = { trading: { setEnabled } };
  });

  it('asks before starting Live, and does nothing when cancelled', async () => {
    const { useSetTrading } = await import('../src/components/TopBar');
    app.value = { config: cfg({}), account: null };
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { result } = renderHook(() => useSetTrading());
    await act(() => result.current(true));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(setEnabled).not.toHaveBeenCalled();
  });

  it('reports a change the backend never confirmed', async () => {
    const { useSetTrading } = await import('../src/components/TopBar');
    app.value = { config: cfg({ accountMode: 'paper' }), account: null };
    setEnabled.mockResolvedValue({ ok: false, message: 'Setting saved, but the backend did not confirm it' });
    const { result } = renderHook(() => useSetTrading());
    await act(() => result.current(true));
    expect(setEnabled).toHaveBeenCalledWith(true);
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('did not confirm'));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('pauses without a confirm', async () => {
    const { useSetTrading } = await import('../src/components/TopBar');
    app.value = { config: cfg({ enableTrading: true }), account: null };
    const confirm = vi.spyOn(window, 'confirm');
    setEnabled.mockResolvedValue({ ok: true });
    const { result } = renderHook(() => useSetTrading());
    await act(() => result.current(false));
    expect(confirm).not.toHaveBeenCalled();
    expect(setEnabled).toHaveBeenCalledWith(false);
  });
});
