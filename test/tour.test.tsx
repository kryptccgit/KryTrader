import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Tour } from '../src/components/tour/Tour';
import type { TourStep } from '../src/components/tour/tourSteps';


const STEPS: TourStep[] = [
  { id: 'a', group: 'G', title: 'Alpha', body: 'The first stop, with a page.', page: 'terminal' },
  { id: 'b', group: 'G', title: 'Bravo', body: 'The second stop.' },
  { id: 'c', group: 'H', title: 'Charlie', body: 'The last stop.' },
];

function setup(targets = ['a', 'b', 'c']) {
  const onClose = vi.fn();
  const onNavigate = vi.fn();
  const utils = render(
    <div>
      {targets.map((t) => <button key={t} data-tour={t}>{t}</button>)}
      <Tour open steps={STEPS} onClose={onClose} onNavigate={onNavigate} />
    </div>,
  );
  return { ...utils, onClose, onNavigate };
}

const title = (): string => screen.getByRole('dialog').querySelector('h2')!.textContent ?? '';
const count = (): string => screen.getByTestId('tour-count').textContent ?? '';
const key = (k: string): void => { act(() => { fireEvent.keyDown(window, { key: k }); }); };

describe('Tour', () => {
  it('opens on the first step as a labelled dialog', () => {
    setup();
    const dialog = screen.getByRole('dialog');
    expect(title()).toBe('Alpha');
    expect(count()).toBe('1 / 3');
    expect(document.getElementById(dialog.getAttribute('aria-describedby')!)!.textContent)
      .toBe('The first stop, with a page.');
    expect(document.getElementById(dialog.getAttribute('aria-labelledby')!)!.textContent).toBe('Alpha');
    expect(screen.queryByText('Back')).toBeNull();
  });

  it('moves with Next and Back', () => {
    setup();
    fireEvent.click(screen.getByTestId('tour-next'));
    expect(title()).toBe('Bravo');
    expect(count()).toBe('2 / 3');
    fireEvent.click(screen.getByText('Back'));
    expect(title()).toBe('Alpha');
  });

  it('moves with the arrow keys and Enter, and closes on Escape', () => {
    const { onClose } = setup();
    key('ArrowRight');
    expect(title()).toBe('Bravo');
    key('ArrowLeft');
    expect(title()).toBe('Alpha');
    key('ArrowLeft');
    expect(title()).toBe('Alpha');
    key('Enter');
    expect(title()).toBe('Bravo');
    expect(onClose).not.toHaveBeenCalled();
    key('Escape');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('skips a step whose target is not on screen, and counts only what it will show', () => {
    setup(['a', 'c']);
    expect(count()).toBe('1 / 2');
    key('ArrowRight');
    expect(title()).toBe('Charlie');
    expect(count()).toBe('2 / 2');
    key('ArrowLeft');
    expect(title()).toBe('Alpha');
  });

  it('starts at the first step that exists', () => {
    setup(['b', 'c']);
    expect(title()).toBe('Bravo');
  });

  it('closes when nothing it points at exists', () => {
    const { onClose } = setup([]);
    expect(onClose).toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('closes on the last step: the button says Done', () => {
    const { onClose } = setup();
    key('ArrowRight');
    key('ArrowRight');
    expect(title()).toBe('Charlie');
    expect(screen.getByTestId('tour-next').textContent).toContain('Done');
    fireEvent.click(screen.getByTestId('tour-next'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Skip tour and the close button both close it', () => {
    const first = setup();
    fireEvent.click(screen.getByText('Skip tour'));
    expect(first.onClose).toHaveBeenCalledTimes(1);
    first.unmount();
    const second = setup();
    fireEvent.click(screen.getByLabelText('Close tour'));
    expect(second.onClose).toHaveBeenCalledTimes(1);
  });

  it('"Go there" opens the page and continues to the next step', () => {
    const { onNavigate } = setup();
    fireEvent.click(screen.getByTestId('tour-go'));
    expect(onNavigate).toHaveBeenCalledWith('terminal');
    expect(title()).toBe('Bravo');
    expect(screen.queryByTestId('tour-go')).toBeNull();
  });

  it('takes focus, keeps Tab inside the card, and gives it back on close', () => {
    const outside = document.createElement('button');
    document.body.appendChild(outside);
    outside.focus();
    const onClose = vi.fn();
    const { rerender } = render(
      <div>
        <button data-tour="a">a</button>
        <Tour open steps={STEPS} onClose={onClose} onNavigate={() => {}} />
      </div>,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog.contains(document.activeElement)).toBe(true);
    for (let i = 0; i < 6; i++) key('Tab');
    expect(dialog.contains(document.activeElement)).toBe(true);
    rerender(
      <div>
        <button data-tour="a">a</button>
        <Tour open={false} steps={STEPS} onClose={onClose} onNavigate={() => {}} />
      </div>,
    );
    expect(document.activeElement).toBe(outside);
    outside.remove();
  });
});
