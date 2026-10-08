import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GuideVideoButton, GuideVideoCard } from '../src/components/GuideVideo';

describe('AI agents video guide', () => {
  it('opens a local video from the onboarding card', () => {
    render(<GuideVideoCard />);
    expect(document.querySelector('video')).toBeNull();
    fireEvent.click(screen.getByText(/Watch the .* guide/));
    const video = document.querySelector('video');
    expect(video).not.toBeNull();
    const src = video!.getAttribute('src') ?? '';
    expect(src).toMatch(/ai-agents-guide.*\.mp4$/);
    expect(src).not.toMatch(/^https?:/);
    expect(video!.hasAttribute('controls')).toBe(true);
  });

  it('Escape closes the video without reaching a window listener behind it', () => {
    const behind = vi.fn();
    window.addEventListener('keydown', behind);
    try {
      render(<GuideVideoButton />);
      fireEvent.click(screen.getByText('Video guide'));
      expect(screen.getByRole('dialog', { name: 'AI agents video guide' })).toBeTruthy();
      fireEvent.keyDown(document.body, { key: 'Escape' });
      expect(screen.queryByRole('dialog', { name: 'AI agents video guide' })).toBeNull();
      expect(behind).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener('keydown', behind);
    }
  });

  it('renders on <body>, not inside the panel that opened it', () => {
    const { container } = render(<GuideVideoCard />);
    fireEvent.click(screen.getByText(/Watch the .* guide/));
    const dialog = screen.getByRole('dialog', { name: 'AI agents video guide' });
    expect(container.contains(dialog)).toBe(false);
    expect(dialog.parentElement).toBe(document.body);
  });

  it('a click outside the video closes it; a click on it does not', () => {
    render(<GuideVideoButton />);
    fireEvent.click(screen.getByText('Video guide'));
    fireEvent.click(document.querySelector('video')!);
    expect(screen.queryByRole('dialog', { name: 'AI agents video guide' })).not.toBeNull();
    fireEvent.click(screen.getByRole('dialog', { name: 'AI agents video guide' }));
    expect(screen.queryByRole('dialog', { name: 'AI agents video guide' })).toBeNull();
  });
});
