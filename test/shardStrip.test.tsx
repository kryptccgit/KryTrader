import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ShardStrip } from '../src/components/terminal/ShardBalances';
import { ToastProvider } from '../src/state/ToastProvider';


const shards = [
  { index: 0, name: 'general', cashUsd: 1204.5 },
  { index: 2, name: 'crypto', cashUsd: 0 },
];

const shardTransfer = vi.fn();

beforeEach(() => {
  shardTransfer.mockReset();
  shardTransfer.mockResolvedValue({ ok: true, message: 'Moved $10.00' });
  (window as unknown as { krypt: unknown }).krypt = {
    terminal: { shardTransfer },
    app: { openExternal: vi.fn() },
  };
});

const mount = (props: Partial<Parameters<typeof ShardStrip>[0]> = {}) => render(
  <ToastProvider>
    <ShardStrip
      shards={shards}
      transferUrl="https://kalshi.com/account/exchange-indexes"
      {...props}
    />
  </ToastProvider>,
);

const openPanel = () => fireEvent.click(
  screen.getByRole('button', { name: /swap cash between exchanges/i }));

describe('ShardStrip', () => {
  it('names every exchange and what it holds', () => {
    mount();
    expect(screen.getByText('general')).toBeTruthy();
    expect(screen.getByText('crypto')).toBeTruthy();
    expect(screen.getByText('$1204.50')).toBeTruthy();
    expect(screen.getAllByText("$0.00").length).toBeGreaterThan(0);
  });

  it('shows every exchange on a real four-engine account', () => {
    mount({
      shards: [
        { index: 0, name: 'general', cashUsd: 1.18 },
        { index: 1, name: 'combos', cashUsd: 0 },
        { index: 2, name: 'crypto', cashUsd: 0 },
        { index: 3, name: 'tennis & baseball', cashUsd: 0 },
      ],
    });
    for (const name of ['general', 'combos', 'crypto', 'tennis & baseball']) {
      expect(screen.getByText(name)).toBeTruthy();
    }
    expect(screen.getByText('$1.18')).toBeTruthy();
    expect(screen.getAllByText('$0.00')).toHaveLength(3);
  });

  it('renders nothing when there is only one exchange to hold cash', () => {
    const { container } = mount({ shards: [shards[0]] });
    expect(container.textContent).toBe('');
  });

  it('opens and closes the swap panel', async () => {
    mount();
    expect(screen.queryByLabelText('Amount to move')).toBeNull();
    openPanel();
    expect(screen.getByLabelText('Amount to move')).toBeTruthy();

    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByLabelText('Amount to move')).toBeNull());
  });

  it('closes on a click outside — the header\'s backdrop-blur rules out a fixed catcher', async () => {
    mount();
    openPanel();
    expect(screen.getByLabelText('Amount to move')).toBeTruthy();
    fireEvent.mouseDown(document.body);
    await waitFor(() => expect(screen.queryByLabelText('Amount to move')).toBeNull());
  });

  it('never submits a transfer straight off the Move button', () => {
    mount();
    openPanel();
    fireEvent.change(screen.getByLabelText('Amount to move'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Move' }));
    expect(shardTransfer).not.toHaveBeenCalled();
    expect(screen.getByText('Move collateral between exchanges?')).toBeTruthy();
  });

  it('submits by shard index once confirmed, and portals the dialog to <body>', async () => {
    const { container } = mount();
    openPanel();
    fireEvent.change(screen.getByLabelText('Amount to move'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Move' }));

    const dialog = screen.getByText('Move collateral between exchanges?');
    expect(container.contains(dialog)).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: /^Move \$10\.00$/ }));
    await waitFor(() => expect(shardTransfer).toHaveBeenCalledWith({
      amountUsd: 10, fromShard: 0, toShard: 2,
    }));
  });

  it('refuses to send more than the source exchange holds', () => {
    mount();
    openPanel();
    fireEvent.change(screen.getByLabelText('Amount to move'), { target: { value: '9999' } });
    expect(screen.getByRole('button', { name: 'Move' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByText(/general only holds \$1204\.50/i)).toBeTruthy();
  });

  it('refuses a transfer to the exchange it came from', () => {
    mount();
    openPanel();
    fireEvent.change(screen.getByLabelText('Move to'), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText('Amount to move'), { target: { value: '10' } });
    expect(screen.getByRole('button', { name: 'Move' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('Pick two different exchanges.')).toBeTruthy();
  });

  it('hides the Kalshi link rather than offering one that opens nothing', () => {
    mount({ transferUrl: '' });
    openPanel();
    expect(screen.queryByRole('button', { name: /on kalshi/i })).toBeNull();
  });
});
