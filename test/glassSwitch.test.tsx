import { StrictMode, useState } from 'react';
import { act, fireEvent, render } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { Switch, useOptimisticValue } from '../src/components/common';


beforeAll(() => {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  const ctx = {
    createImageData: (w: number, h: number) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }),
    putImageData: () => {},
  };
  (HTMLCanvasElement.prototype as unknown as { getContext: () => unknown }).getContext = () => ctx;
  (HTMLCanvasElement.prototype as unknown as { toDataURL: () => string }).toDataURL = () => 'data:,';
  const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
  proto.setPointerCapture ??= () => {};
  proto.releasePointerCapture ??= () => {};
  if (!('PointerEvent' in window)) {
    class PointerEventPolyfill extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 0;
      }
    }
    (window as unknown as { PointerEvent: unknown }).PointerEvent = PointerEventPolyfill;
  }
});

async function wait(ms: number): Promise<void> {
  for (let t = 0; t < ms; t += 40) {
    await act(() => new Promise<void>((r) => { setTimeout(r, Math.min(40, ms - t)); }));
  }
}
const SETTLED = 720;

function parts(container: HTMLElement) {
  const label = container.querySelector('label') as HTMLLabelElement;
  const input = container.querySelector('input[role="switch"]') as HTMLInputElement;
  const thumb = Array.from(label.querySelectorAll('div'))
    .find((d) => (d as HTMLElement).style.touchAction === 'none') as HTMLElement;
  const progress = () => Number(label.style.getPropertyValue('--switch-progress') || '0');
  return { label, input, thumb, progress };
}

async function press(thumb: HTMLElement, holdMs: number, dx = 0) {
  fireEvent.pointerDown(thumb, { pointerId: 1, clientX: 10 });
  await wait(holdMs);
  if (dx) {
    fireEvent.pointerMove(thumb, { pointerId: 1, clientX: 14 });
    fireEvent.pointerMove(thumb, { pointerId: 1, clientX: 14 + dx });
  }
  fireEvent.pointerUp(thumb, { pointerId: 1, clientX: 10 + dx });
  fireEvent.click(thumb);
}

function Host({ decide, calls }: {
  decide: (next: boolean, set: (v: boolean) => void) => void;
  calls: boolean[];
}) {
  const [on, setOn] = useState(false);
  return (
    <Switch
      label="Real orders (LIVE)"
      checked={on}
      onChange={(v) => { calls.push(v); decide(v, setOn); }}
    />
  );
}

describe('Switch always shows the value it is given', () => {
  it('stays OFF after a cancelled confirm, and the next click still asks to turn it ON', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const calls: boolean[] = [];
    const { container } = render(
      <Host calls={calls} decide={(v, set) => { if (v && !window.confirm('Go LIVE?')) return; set(v); }} />,
    );
    const { input, thumb, progress } = parts(container);

    fireEvent.click(input);
    await wait(SETTLED);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(input.checked).toBe(false);
    expect(progress()).toBe(0);

    await press(thumb, 40);
    await wait(SETTLED);
    expect(progress()).toBe(0);
    expect(calls).toEqual([true, true]);

    confirm.mockReturnValue(true);
    fireEvent.click(input);
    await wait(SETTLED);
    expect(input.checked).toBe(true);
    expect(progress()).toBe(1);
  });

  it('rolls back when the backend refuses the change after accepting it', async () => {
    const calls: boolean[] = [];
    const { container } = render(
      <Host
        calls={calls}
        decide={(v, set) => { set(v); setTimeout(() => set(!v), 60); }}
      />,
    );
    const { input, progress } = parts(container);
    fireEvent.click(input);
    await wait(SETTLED);
    expect(calls).toEqual([true]);
    expect(input.checked).toBe(false);
    expect(progress()).toBe(0);
  });

  it('rolls back a useOptimisticValue switch whose commit rejects', async () => {
    const commit = vi.fn(() => Promise.reject(new Error('refused')));
    function OptimisticHost() {
      const [local, apply] = useOptimisticValue(false, commit);
      return <Switch label="Paper mode" checked={local} onChange={apply} />;
    }
    const { container } = render(<OptimisticHost />);
    const { input, progress } = parts(container);
    fireEvent.click(input);
    await wait(SETTLED);
    expect(commit).toHaveBeenCalledWith(true);
    expect(input.checked).toBe(false);
    expect(progress()).toBe(0);
  });

  it('follows a controlled prop flip it did not cause', async () => {
    const { container, rerender } = render(<Switch label="x" checked={false} onChange={() => {}} />);
    const { progress } = parts(container);
    expect(progress()).toBe(0);
    rerender(<Switch label="x" checked onChange={() => {}} />);
    await wait(SETTLED);
    expect(progress()).toBe(1);
    rerender(<Switch label="x" checked={false} onChange={() => {}} />);
    await wait(SETTLED);
    expect(progress()).toBe(0);
  });

  it('still follows the prop under StrictMode (the dev double mount)', async () => {
    const calls: boolean[] = [];
    const { container } = render(
      <StrictMode><Host calls={calls} decide={(v, set) => set(v)} /></StrictMode>,
    );
    const { input, progress } = parts(container);
    fireEvent.click(input);
    await wait(SETTLED);
    expect(progress()).toBe(1);
    fireEvent.click(input);
    await wait(SETTLED);
    expect(progress()).toBe(0);
  });

  it('ignores a click it asked for while the parent is still deciding (async confirm)', async () => {
    const calls: boolean[] = [];
    let answer: ((ok: boolean) => void) | null = null;
    const { container } = render(
      <Host calls={calls} decide={(v, set) => { answer = (ok) => { if (ok) set(v); }; }} />,
    );
    const { input, progress } = parts(container);
    fireEvent.click(input);
    await wait(SETTLED);
    expect(progress()).toBe(0);
    act(() => answer!(true));
    await wait(SETTLED);
    expect(progress()).toBe(1);
  });
});

describe('every press-release that is not a drag toggles', () => {
  for (const holdMs of [30, 250, 600]) {
    it(`a ${holdMs}ms press on the thumb toggles exactly once`, async () => {
      const calls: boolean[] = [];
      const { container } = render(<Host calls={calls} decide={(v, set) => set(v)} />);
      const { thumb, progress } = parts(container);
      await press(thumb, holdMs);
      await wait(SETTLED);
      expect(calls).toEqual([true]);
      expect(progress()).toBe(1);
    });
  }

  it('a drag decides by the side it is dropped on, and snaps back if refused', async () => {
    const calls: boolean[] = [];
    const { container } = render(<Host calls={calls} decide={() => {}} />);
    const { thumb, progress } = parts(container);
    await press(thumb, 30, 40);
    expect(calls).toEqual([true]);
    await wait(SETTLED);
    expect(progress()).toBe(0);
  });

  it('a drag that ends where it started asks for nothing', async () => {
    const calls: boolean[] = [];
    const { container } = render(<Host calls={calls} decide={(v, set) => set(v)} />);
    const { thumb } = parts(container);
    await press(thumb, 30, -20);
    await wait(SETTLED);
    expect(calls).toEqual([]);
  });

  it('Enter and Space (a native click on the focused input) both toggle', async () => {
    const calls: boolean[] = [];
    const { container } = render(<Host calls={calls} decide={(v, set) => set(v)} />);
    const { input, progress } = parts(container);
    fireEvent.keyDown(input, { key: 'Enter' });
    await wait(SETTLED);
    expect(progress()).toBe(1);
    input.click();
    await wait(SETTLED);
    expect(calls).toEqual([true, false]);
    expect(progress()).toBe(0);
  });

  it('a disabled switch asks for nothing, by pointer, click or key', async () => {
    const onChange = vi.fn();
    const { container } = render(<Switch label="x" checked={false} disabled onChange={onChange} />);
    const { input, thumb, label } = parts(container);
    await press(thumb, 30);
    await press(thumb, 250);
    fireEvent.click(input);
    fireEvent.click(label);
    fireEvent.keyDown(input, { key: 'Enter' });
    await wait(50);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('a click on the row text still toggles once', async () => {
    const calls: boolean[] = [];
    const { getByText } = render(<Host calls={calls} decide={(v, set) => set(v)} />);
    fireEvent.click(getByText('Real orders (LIVE)'));
    await wait(50);
    expect(calls).toEqual([true]);
  });
});
