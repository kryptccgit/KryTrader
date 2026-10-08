import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../src/state/AppStateProvider', () => ({ useApp: () => ({ state: { acceptedDisclaimer: true }, config: {} }) }));
vi.mock('../src/state/ToastProvider', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn(), push: vi.fn() }),
}));

import { OnboardingModal } from '../src/pages/Onboarding';

describe('onboarding panel layout', () => {
  it('is a flex column, so the middle scrolls and the footer stays on screen', () => {
    render(<OnboardingModal onDone={vi.fn()} replay onClose={vi.fn()} />);
    const panel = screen.getByRole('dialog', { name: 'Onboarding (replay)' });
    expect(panel.style.display).toBe('flex');
    expect(panel.className).toContain('flex-col');
    expect(panel.className).toContain('max-h-[94vh]');
    expect(screen.getByTestId('onboarding-continue')).toBeTruthy();
  });
});
