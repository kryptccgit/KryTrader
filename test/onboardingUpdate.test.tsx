import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { autoOnboarding, ONBOARDING_REVISION } from '@shared/onboarding';
import { GuideHost } from '../src/components/tour/GuideHost';


let userData = '';
vi.mock('electron', () => ({ app: { getPath: () => userData } }));

const app = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn(), push: vi.fn() }));
vi.mock('../src/state/AppStateProvider', () => ({ useApp: () => app.value }));
vi.mock('../src/state/ToastProvider', () => ({ useToast: () => toast }));
vi.mock('../src/components/KalshiKeyWizard', () => ({
  KalshiKeyWizard: ({ onSkip }: { onSkip?: () => void }) => <button type="button" onClick={onSkip}>wizard-skip</button>,
}));
vi.mock('../src/components/AutopilotQuickstart', () => ({
  AutopilotQuickstart: ({ onSkip }: { onSkip?: () => void }) => <button type="button" onClick={onSkip}>quickstart-skip</button>,
}));

describe('autoOnboarding', () => {
  it('first run, after an update, or nothing', () => {
    expect(autoOnboarding(null)).toBeNull();
    expect(autoOnboarding({ acceptedDisclaimer: false })).toBe('first');
    expect(autoOnboarding({ acceptedDisclaimer: false, onboardingSeen: ONBOARDING_REVISION })).toBe('first');
    expect(autoOnboarding({ acceptedDisclaimer: true })).toBe('update');
    expect(autoOnboarding({ acceptedDisclaimer: true, onboardingSeen: ONBOARDING_REVISION - 1 })).toBe('update');
    expect(autoOnboarding({ acceptedDisclaimer: true, onboardingSeen: ONBOARDING_REVISION })).toBeNull();
  });
});

describe('the saved revision', () => {
  beforeEach(() => { userData = mkdtempSync(join(tmpdir(), 'krypt-onb-')); });
  afterEach(() => rmSync(userData, { recursive: true, force: true }));
  const freshStore = async () => { vi.resetModules(); return import('../electron/system/settings-store'); };

  it('an upgraded settings.json reads as unseen; a saved revision survives a reload', async () => {
    writeFileSync(join(userData, 'settings.json'), JSON.stringify({ acceptedDisclaimer: true, config: {} }));
    let store = await freshStore();
    expect(store.load().onboardingSeen).toBe(0);
    expect(autoOnboarding(store.load())).toBe('update');
    store.save({ ...store.get(), onboardingSeen: ONBOARDING_REVISION });
    store = await freshStore();
    expect(store.load().onboardingSeen).toBe(ONBOARDING_REVISION);
    expect(autoOnboarding(store.load())).toBeNull();
  });

  it('a hand-edited value is coerced, never trusted as a string or a negative', async () => {
    writeFileSync(join(userData, 'settings.json'),
      JSON.stringify({ acceptedDisclaimer: true, onboardingSeen: '99', config: {} }));
    expect((await freshStore()).load().onboardingSeen).toBe(0);
    writeFileSync(join(userData, 'settings.json'),
      JSON.stringify({ acceptedDisclaimer: true, onboardingSeen: -3, config: {} }));
    expect((await freshStore()).load().onboardingSeen).toBe(0);
  });
});

describe('GuideHost after an update', () => {
  let krypt: {
    state: { acceptDisclaimer: ReturnType<typeof vi.fn>; markOnboardingSeen: ReturnType<typeof vi.fn> };
    config: { update: ReturnType<typeof vi.fn> };
    terminal: Record<string, ReturnType<typeof vi.fn>>;
  };
  beforeEach(() => {
    localStorage.clear();
    app.value = {
      state: { acceptedDisclaimer: true },
      config: { accountMode: 'paper', paperBankrollUsd: 1000, mcpTradeMode: 'paper' },
      backend: { status: 'running', authOk: false },
      refresh: { state: vi.fn(async () => {}) },
    };
    krypt = {
      state: { acceptDisclaimer: vi.fn(async () => ({ ok: true })), markOnboardingSeen: vi.fn(async () => ({ ok: true })) },
      config: { update: vi.fn(async () => ({ ok: true })) },
      terminal: {
        onMcpToolCall: vi.fn(() => () => {}),
        mcpSeen: vi.fn(async () => ({ clients: [] })),
        mcpCopyConfig: vi.fn(async () => ({ ok: true })),
      },
    };
    (window as unknown as { krypt: unknown }).krypt = krypt;
  });
  const flush = async (): Promise<void> => { await act(async () => { await Promise.resolve(); }); };
  const host = (setPage = vi.fn(), update = true) => (
    <GuideHost needsOnboarding={false} needsUpdateOnboarding={update} setPage={setPage}><div>app</div></GuideHost>
  );

  it('opens by itself as a replay that says why, and closing it marks it seen and writes nothing else', async () => {
    const { rerender } = render(host());
    expect(screen.getByRole('dialog', { name: 'Onboarding (replay)' })).toBeTruthy();
    expect(screen.getByText(/New in this version/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Close onboarding'));
    await flush();
    expect(screen.queryByRole('dialog', { name: 'Onboarding (replay)' })).toBeNull();
    expect(krypt.state.markOnboardingSeen).toHaveBeenCalledTimes(1);
    expect(krypt.state.acceptDisclaimer).not.toHaveBeenCalled();
    expect(krypt.config.update).not.toHaveBeenCalled();
    rerender(host());
    expect(screen.queryByRole('dialog', { name: 'Onboarding (replay)' })).toBeNull();
  });

  it('finishing it keeps the user on their page and offers the (new) tour once', async () => {
    const setPage = vi.fn();
    render(host(setPage));
    fireEvent.click(screen.getByTestId('onboarding-continue'));
    fireEvent.click(screen.getByTestId('onboarding-continue'));
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));
    fireEvent.click(screen.getByTestId('onboarding-start-paper'));
    await flush();
    expect(screen.queryByRole('dialog', { name: 'Onboarding (replay)' })).toBeNull();
    expect(setPage).not.toHaveBeenCalled();
    expect(krypt.state.markOnboardingSeen).toHaveBeenCalled();
    expect(krypt.state.acceptDisclaimer).not.toHaveBeenCalled();
    expect(krypt.config.update).not.toHaveBeenCalled();
    expect(screen.getByTestId('tour-offer')).toBeTruthy();
  });

  it('nothing opens once the revision is seen', () => {
    render(host(vi.fn(), false));
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
