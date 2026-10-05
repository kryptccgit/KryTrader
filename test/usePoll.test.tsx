import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePoll } from '../src/state/TerminalProvider';

function Probe({ ticker, fetcher, interval = 0, enabled = true }: {
  ticker: string;
  fetcher: (t: string) => Promise<string>;
  interval?: number;
  enabled?: boolean;
}) {
  const { data, error, loading } = usePoll<string>(
    () => fetcher(ticker), interval, [ticker], enabled,
  );
  return (
    <div>
      <span data-testid="data">{data ?? 'null'}</span>
      <span data-testid="error">{error ?? 'none'}</span>
      <span data-testid="loading">{String(loading)}</span>
    </div>
  );
}

const deferred = () => {
  let resolve!: (v: string) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<string>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

describe('usePoll', () => {
  it('loads and shows data', async () => {
    const { rerender } = render(
      <Probe ticker="A" fetcher={async (t) => `data:${t}`} />,
    );
    await waitFor(() => expect(screen.getByTestId('data').textContent).toBe('data:A'));
    expect(screen.getByTestId('loading').textContent).toBe('false');
    rerender(<Probe ticker="A" fetcher={async (t) => `data:${t}`} />);
  });

  it('does NOT commit a slow response for the previous entity', async () => {
    const a = deferred();
    const b = deferred();
    const fetcher = vi.fn((t: string) => (t === 'A' ? a.promise : b.promise));

    const { rerender } = render(<Probe ticker="A" fetcher={fetcher} />);
    rerender(<Probe ticker="B" fetcher={fetcher} />);

    await act(async () => { a.resolve('data:A'); });
    expect(screen.getByTestId('data').textContent).not.toBe('data:A');

    await act(async () => { b.resolve('data:B'); });
    await waitFor(() => expect(screen.getByTestId('data').textContent).toBe('data:B'));
  });

  it('fetches the new entity immediately, not after a full interval', async () => {
    const a = deferred();
    const fetcher = vi.fn((t: string) => (t === 'A' ? a.promise : Promise.resolve(`data:${t}`)));

    const { rerender } = render(<Probe ticker="A" fetcher={fetcher} interval={60_000} />);
    expect(fetcher).toHaveBeenCalledTimes(1);

    rerender(<Probe ticker="B" fetcher={fetcher} interval={60_000} />);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenLastCalledWith('B');
  });

  it('clears the previous entity\'s data while the new one loads', async () => {
    const b = deferred();
    const fetcher = (t: string) => (t === 'A' ? Promise.resolve('data:A') : b.promise);

    const { rerender } = render(<Probe ticker="A" fetcher={fetcher} />);
    await waitFor(() => expect(screen.getByTestId('data').textContent).toBe('data:A'));

    rerender(<Probe ticker="B" fetcher={fetcher} />);
    expect(screen.getByTestId('data').textContent).toBe('null');
    await act(async () => { b.resolve('data:B'); });
  });

  it('keeps the last good data when a poll fails, and says so', async () => {
    let call = 0;
    const fetcher = async () => {
      call += 1;
      if (call === 1) return 'good';
      throw new Error('provider parked');
    };
    render(<Probe ticker="A" fetcher={fetcher} interval={1000} />);
    await waitFor(() => expect(screen.getByTestId('data').textContent).toBe('good'));

    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('provider parked'));
    expect(screen.getByTestId('data').textContent).toBe('good');
  });

  it('clears a previous error once a poll succeeds again', async () => {
    let call = 0;
    const fetcher = async () => {
      call += 1;
      if (call === 1) throw new Error('boom');
      return 'recovered';
    };
    render(<Probe ticker="A" fetcher={fetcher} interval={1000} />);
    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('boom'));
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('none'));
  });

  it('polls on the interval', async () => {
    const fetcher = vi.fn(async (t: string) => `data:${t}`);
    render(<Probe ticker="A" fetcher={fetcher} interval={1000} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(4);
  });

  it('stops polling after unmount', async () => {
    const fetcher = vi.fn(async (t: string) => `data:${t}`);
    const { unmount } = render(<Probe ticker="A" fetcher={fetcher} interval={500} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    unmount();
    const seen = fetcher.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(fetcher.mock.calls.length).toBe(seen);
  });

  it('does not fetch at all when disabled', async () => {
    const fetcher = vi.fn(async () => 'x');
    render(<Probe ticker="A" fetcher={fetcher} interval={500} enabled={false} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByTestId('loading').textContent).toBe('false');
  });

  it('does not stack requests when the interval is shorter than the fetch', async () => {
    const pending: Array<(v: string) => void> = [];
    const fetcher = vi.fn(() => new Promise<string>((res) => pending.push(res)));
    render(<Probe ticker="A" fetcher={fetcher} interval={100} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(fetcher.mock.calls.length).toBeLessThanOrEqual(2);
  });
});
