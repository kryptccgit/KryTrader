import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TraderConfig } from '@shared/types';
import { GuideHost } from '../src/components/tour/GuideHost';
import { TOUR_OFFERED_KEY } from '../src/components/tour/useTour';


const app = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn(), push: vi.fn() }));
vi.mock('../src/state/AppStateProvider', () => ({ useApp: () => app.value }));
vi.mock('../src/state/ToastProvider', () => ({ useToast: () => toast }));
vi.mock('../src/components/KalshiKeyWizard', () => ({
  KalshiKeyWizard: ({ onSkip }: { onSkip?: () => void }) => (
    <button type="button" onClick={onSkip}>wizard-skip</button>
  ),
}));
vi.mock('../src/components/AutopilotQuickstart', () => ({
  AutopilotQuickstart: ({ onSkip }: { onSkip?: () => void }) => (
    <button type="button" onClick={onSkip}>quickstart-skip</button>
  ),
}));

let krypt: {
  state: { acceptDisclaimer: ReturnType<typeof vi.fn> };
  config: { update: ReturnType<typeof vi.fn> };
  terminal: Record<string, ReturnType<typeof vi.fn>>;
};

function setApp(cfg: Partial<TraderConfig>, accepted: boolean): void {
  app.value = {
    state: { acceptedDisclaimer: accepted },
    config: { accountMode: 'paper', paperBankrollUsd: 1000, ...cfg },
    backend: { status: 'running', authOk: false },
    refresh: { state: vi.fn(async () => {}) },
  };
}

beforeEach(() => {
  localStorage.clear();
  toast.success.mockClear();
  krypt = {
    state: { acceptDisclaimer: vi.fn(async () => ({ ok: true })) },
    config: { update: vi.fn(async () => ({ ok: true })) },
    terminal: {
      onMcpToolCall: vi.fn(() => () => {}),
      mcpSeen: vi.fn(async () => ({ clients: [] })),
      mcpCopyConfig: vi.fn(async () => ({ ok: true })),
    },
  };
  (window as unknown as { krypt: unknown }).krypt = krypt;
});

const cont = (): void => { fireEvent.click(screen.getByTestId('onboarding-continue')); };
const pickClaudeCode = (): void => { fireEvent.click(screen.getByRole('button', { name: 'Claude Code' })); };
const flush = async (): Promise<void> => { await act(async () => { await Promise.resolve(); }); };

async function openReplay(setPage = vi.fn()) {
  const { GettingStartedCard } = await import('../src/pages/Settings');
  const utils = render(
    <GuideHost needsOnboarding={false} setPage={setPage}>
      <GettingStartedCard />
    </GuideHost>,
  );
  fireEvent.click(screen.getByTestId('settings-replay-onboarding'));
  return { ...utils, setPage };
}

describe('Replay onboarding', () => {
  it('opens at step 1 and writes nothing: not the disclaimer, not a setting, not the page', async () => {
    setApp({ mcpEnabled: true, mcpTradeMode: 'paper' }, true);
    const { setPage } = await openReplay();
    expect(screen.getByRole('dialog', { name: 'Onboarding (replay)' })).toBeTruthy();
    expect(screen.getByText('KRYPT TRADER')).toBeTruthy();
    expect(screen.getByLabelText('Onboarding step 1 of 4')).toBeTruthy();

    cont();
    expect(screen.getByTestId('disclaimer-accepted')).toBeTruthy();
    const box = screen.getByRole('checkbox') as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(true);
    cont();
    cont();
    await flush();
    fireEvent.click(screen.getByTestId('onboarding-start-paper'));
    await flush();

    expect(screen.queryByRole('dialog', { name: 'Onboarding (replay)' })).toBeNull();
    expect(krypt.state.acceptDisclaimer).not.toHaveBeenCalled();
    expect(krypt.config.update).not.toHaveBeenCalled();
    expect(setPage).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.queryByTestId('tour-offer')).toBeNull();
  });

  it('adding a key is its own path, and skipping it writes nothing either', async () => {
    setApp({ mcpEnabled: true, mcpTradeMode: 'paper' }, true);
    await openReplay();
    cont(); cont(); cont();
    await flush();
    expect(screen.getByTestId('onboarding-start')).toBeTruthy();
    fireEvent.click(screen.getByTestId('onboarding-add-key'));
    fireEvent.click(screen.getByText('wizard-skip'));
    await flush();
    expect(krypt.config.update).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: 'Onboarding (replay)' })).toBeNull();
  });

  it('"Start on paper" on a replay while Live switches back to Paper, and only that', async () => {
    setApp({ accountMode: 'live', mcpEnabled: true, mcpTradeMode: 'paper' }, true);
    await openReplay();
    cont(); cont(); cont();
    await flush();
    fireEvent.click(screen.getByTestId('onboarding-start-paper'));
    await flush();
    expect(krypt.config.update).toHaveBeenCalledTimes(1);
    expect(krypt.config.update).toHaveBeenCalledWith({ accountMode: 'paper' });
  });

  it('closes from the close button or Escape, untouched', async () => {
    setApp({ mcpEnabled: true, mcpTradeMode: 'paper' }, true);
    await openReplay();
    fireEvent.click(screen.getByLabelText('Close onboarding'));
    expect(screen.queryByRole('dialog', { name: 'Onboarding (replay)' })).toBeNull();
    fireEvent.click(screen.getByTestId('settings-replay-onboarding'));
    expect(screen.getByRole('dialog', { name: 'Onboarding (replay)' })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Onboarding (replay)' })).toBeNull();
    expect(krypt.config.update).not.toHaveBeenCalled();
    expect(krypt.state.acceptDisclaimer).not.toHaveBeenCalled();
  });

  it('with agents LIVE, says so and copying a config does not switch them to paper', async () => {
    setApp({ mcpEnabled: true, mcpTradeMode: 'live' }, true);
    await openReplay();
    cont(); cont();
    expect(screen.getByTestId('connect-live-note').textContent).toContain('Your agents are LIVE');
    pickClaudeCode();
    fireEvent.click(screen.getByText('Copy config'));
    await flush();
    expect(krypt.terminal.mcpCopyConfig).toHaveBeenCalledTimes(1);
    expect(krypt.config.update).not.toHaveBeenCalled();
  });

  it('with agents LIVE and the server off, asks before switching it on, and never writes paper', async () => {
    setApp({ mcpEnabled: false, mcpTradeMode: 'live' }, true);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await openReplay();
    cont(); cont();
    pickClaudeCode();
    fireEvent.click(screen.getByText('Copy config'));
    await flush();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(krypt.config.update).not.toHaveBeenCalled();
    expect(krypt.terminal.mcpCopyConfig).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByText('Copy config'));
    await flush();
    expect(krypt.config.update).toHaveBeenCalledTimes(1);
    expect(krypt.config.update).toHaveBeenCalledWith({ mcpEnabled: true });
    expect(krypt.terminal.mcpCopyConfig).toHaveBeenCalledTimes(1);
  });

  it('first run is unchanged: from off, Copy config switches the server on in paper', async () => {
    setApp({ mcpEnabled: false, mcpTradeMode: 'off' }, false);
    render(<GuideHost needsOnboarding setPage={vi.fn()}><div /></GuideHost>);
    cont();
    fireEvent.click(screen.getByRole('checkbox'));
    cont();
    await flush();
    expect(krypt.state.acceptDisclaimer).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('connect-live-note')).toBeNull();
    pickClaudeCode();
    fireEvent.click(screen.getByText('Copy config'));
    await flush();
    expect(krypt.config.update).toHaveBeenCalledWith({ mcpEnabled: true, mcpTradeMode: 'paper' });
  });

  it('first run: the risks are accepted before the agent step can switch anything on', async () => {
    setApp({ mcpEnabled: false, mcpTradeMode: 'off' }, false);
    render(<GuideHost needsOnboarding setPage={vi.fn()}><div /></GuideHost>);
    cont();
    expect(screen.queryByText('Copy config')).toBeNull();
    expect(screen.queryByTestId('connect-autopilot-setup')).toBeNull();
    cont();
    await flush();
    expect(krypt.state.acceptDisclaimer).not.toHaveBeenCalled();
    expect(screen.getByRole('checkbox')).toBeTruthy();
    expect(screen.queryByText('Copy config')).toBeNull();
  });

  it('the agent step leads with In-app Autopilot, the choice that needs nothing installed', async () => {
    setApp({ mcpEnabled: true, mcpTradeMode: 'paper' }, true);
    await openReplay();
    cont(); cont();
    const first = screen.getAllByRole('button').find((b) => /In-app Autopilot|Claude Code|Cursor|Claude Desktop|Codex/.test(b.textContent ?? ''));
    expect(first?.textContent).toBe('In-app Autopilot (easiest)');
    expect(screen.getByTestId('connect-autopilot-setup')).toBeTruthy();
  });

  it('with the engine stopped, the agent buttons say why and stay disabled', async () => {
    setApp({ mcpEnabled: true, mcpTradeMode: 'paper' }, true);
    (app.value as { backend: unknown }).backend = { status: 'stopped', authOk: false };
    await openReplay();
    cont(); cont();
    expect(screen.getByTestId('connect-engine-down').textContent).toContain('Restart');
    pickClaudeCode();
    expect((screen.getByText('Copy config').closest('button') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('the first-run tour offer', () => {
  async function finishFirstRun(setPage: ReturnType<typeof vi.fn>) {
    setApp({ mcpEnabled: false, mcpTradeMode: 'paper' }, false);
    const utils = render(
      <GuideHost needsOnboarding setPage={setPage}>
        <button data-tour="nav-aiAgents">AI Agents</button>
      </GuideHost>,
    );
    cont();
    fireEvent.click(screen.getByRole('checkbox'));
    cont();
    await flush();
    fireEvent.click(screen.getByText('Skip'));
    fireEvent.click(screen.getByTestId('onboarding-start-paper'));
    await flush();
    return utils;
  }

  it('shows once after first onboarding, and never again', async () => {
    const setPage = vi.fn();
    const first = await finishFirstRun(setPage);
    expect(krypt.state.acceptDisclaimer).toHaveBeenCalledTimes(1);
    expect(setPage).toHaveBeenCalledWith('aiAgents');
    expect(screen.getByTestId('tour-offer').textContent).toContain('Take a 1-minute tour of the app?');
    expect(localStorage.getItem(TOUR_OFFERED_KEY)).toBe('1');
    fireEvent.click(screen.getByText('Not now'));
    expect(screen.queryByTestId('tour-offer')).toBeNull();
    expect(screen.queryByTestId('tour')).toBeNull();
    first.unmount();

    await finishFirstRun(vi.fn());
    expect(screen.queryByTestId('tour-offer')).toBeNull();
  });

  it('Start opens the tour', async () => {
    await finishFirstRun(vi.fn());
    fireEvent.click(screen.getByText('Start'));
    expect(screen.queryByTestId('tour-offer')).toBeNull();
    expect(screen.getByTestId('tour')).toBeTruthy();
    expect(screen.getByRole('dialog').querySelector('h2')!.textContent).toBe('AI Agents');
  });
});
