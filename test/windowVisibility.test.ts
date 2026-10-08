import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  __resetWindowVisibilityForTests, isWindowVisible, onWindowVisibility,
} from '../src/state/visibility';


let fire: ((visible: boolean) => void) | null = null;
const isVisible = vi.fn();

beforeEach(() => {
  __resetWindowVisibilityForTests();
  fire = null;
  isVisible.mockReset();
  isVisible.mockResolvedValue(true);
  (window as unknown as { krypt: unknown }).krypt = {
    window: {
      isVisible,
      onVisibility: (cb: (v: boolean) => void) => { fire = cb; return () => { fire = null; }; },
    },
  };
});

afterEach(() => {
  __resetWindowVisibilityForTests();
});

const root = () => document.documentElement;

describe('window visibility', () => {
  it('reaches subscribers and pauses CSS animation while minimized or in the tray', async () => {
    const seen: boolean[] = [];
    const off = onWindowVisibility((v) => seen.push(v));
    await Promise.resolve();
    expect(isWindowVisible()).toBe(true);
    expect(root().hasAttribute('data-window-hidden')).toBe(false);

    fire!(false);
    expect(isWindowVisible()).toBe(false);
    expect(root().hasAttribute('data-window-hidden')).toBe(true);

    fire!(true);
    expect(root().hasAttribute('data-window-hidden')).toBe(false);
    expect(seen).toEqual([false, true]);

    off();
    fire!(false);
    expect(seen).toEqual([false, true]);
  });

  it('starts hidden when the app launched straight into the tray', async () => {
    isVisible.mockResolvedValue(false);
    const seen: boolean[] = [];
    onWindowVisibility((v) => seen.push(v));
    await new Promise((r) => setTimeout(r, 0));
    expect(isWindowVisible()).toBe(false);
    expect(seen).toEqual([false]);
  });

  it('repeats nothing: an unchanged state is not re-announced', () => {
    const seen: boolean[] = [];
    onWindowVisibility((v) => seen.push(v));
    fire!(true);
    fire!(true);
    expect(seen).toEqual([]);
  });

  it('survives an older preload with no visibility channel', () => {
    (window as unknown as { krypt: unknown }).krypt = { window: {} };
    expect(() => onWindowVisibility(() => {})).not.toThrow();
    expect(isWindowVisible()).toBe(true);
  });

  it('the stylesheet really pauses animations on that attribute', () => {
    const css = readFileSync(join(__dirname, '..', 'src', 'index.css'), 'utf8');
    expect(css).toMatch(/:root\[data-window-hidden\] \*[^{]*\{\s*animation-play-state: paused !important;/);
  });
});
