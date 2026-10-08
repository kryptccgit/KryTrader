import { useEffect, useState } from 'react';
import { AlertTriangle, Tractor } from 'lucide-react';
import type { PerpsStatus, PerpsWallet } from '@shared/types';
import { Card, Page, Switch } from '../components/common';
import { useApp } from '../state/AppStateProvider';
import { fmtUsd } from '../utils/format';

export function PerpsPage() {
  const [st, setSt] = useState<PerpsStatus | null>(null);

  const load = async () => {
    try {
      setSt(await window.krypt.perps.status());
    } catch {}
  };

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, []);

  return (
    <Page
      title="Perpetuals"
      subtitle="Kalshi perpetual futures. One tool lives here: a maker-only volume farmer for claiming Kalshi's one-time perps signup reward at minimal cost. It is a volume engine with a loss budget — not a profit strategy."
    >
      <div className="mb-4 rounded-lg border border-krypt-loss/40 bg-krypt-loss/5 p-3">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-krypt-loss" />
          <div className="text-[11px] leading-relaxed text-krypt-muted">
            <span className="font-semibold text-krypt-loss">Perpetual futures are leveraged derivatives and can lose more than you put in.</span>{' '}
            We audited 11 perps trading strategies on real recorded Kalshi data (adversarially
            verified) and found <span className="font-semibold text-white">zero profitable configurations</span> —
            the books are professionally index-pegged and the fees exceed every edge we could measure.
            That's why there is no strategy panel here. The farmer below exists for exactly one
            positive-EV action: Kalshi's one-time signup reward for trading $50 of volume, which the
            farmer earns for a few cents in maker fees. Farming beyond that loses money and the
            farmer will halt itself. Nothing here is financial advice.
          </div>
        </div>
      </div>

      <div className="mb-4">
        <WalletCard w={st?.wallet ?? null} />
      </div>

      <FarmerCard st={st} onChanged={() => void load()} />
    </Page>
  );
}

function FarmerCard({ st, onChanged }: { st: PerpsStatus | null; onChanged: () => void }) {
  const { config } = useApp();
  const f = st?.farmer;
  const [flattening, setFlattening] = useState(false);

  const toggle = async (on: boolean) => {
    await window.krypt.config.update({ perpsFarmEnabled: on });
    onChanged();
  };

  const flatten = async () => {
    setFlattening(true);
    try {
      await window.krypt.perps.farmFlatten();
      onChanged();
    } finally {
      setFlattening(false);
    }
  };

  const setNum = (key: 'perpsFarmClipContracts' | 'perpsFarmMaxInventoryContracts' | 'perpsFarmDailyLossUsd' | 'perpsFarmDailyVolumeUsd' | 'perpsFarmMaxFeeBps') =>
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = Number(e.target.value);
      if (Number.isFinite(v)) void window.krypt.config.update({ [key]: v });
    };

  return (
    <Card header={
      <div className="flex items-center gap-2">
        <Tractor className="h-3.5 w-3.5 text-krypt-purple" />
        <div className="text-xs uppercase tracking-wider text-krypt-muted">Volume farmer</div>
        {f?.halted && (
          <span className="rounded-full border border-krypt-warn/40 bg-krypt-warn/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-krypt-warn">
            halted today
          </span>
        )}
      </div>
    }>
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <Switch
            checked={config?.perpsFarmEnabled ?? false}
            onChange={(v) => void toggle(v)}
            label="Farm perps volume (maker-only)"
            description="Rests one small buy and one small sell at the best bid/ask and lets the market trade through them — real two-sided liquidity, never taker, never self-matching. Use it to earn Kalshi's one-time perps signup reward (trade $50 of volume) for a few cents in maker fees, then turn it off. Auto-halts for the day if the measured cost per $ of volume exceeds the cap, or at the daily loss cap. Needs funds in the perps wallet."
          />
          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="text-[11px] text-krypt-dim">
              Clip (contracts)
              <input type="number" min={1} max={100} defaultValue={config?.perpsFarmClipContracts ?? 1}
                onBlur={setNum('perpsFarmClipContracts')}
                className="mt-1 w-full rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1 text-xs text-white outline-none focus:border-krypt-purple/60" />
            </label>
            <label className="text-[11px] text-krypt-dim">
              Max inventory (contracts)
              <input type="number" min={1} max={1000} defaultValue={config?.perpsFarmMaxInventoryContracts ?? 3}
                onBlur={setNum('perpsFarmMaxInventoryContracts')}
                className="mt-1 w-full rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1 text-xs text-white outline-none focus:border-krypt-purple/60" />
            </label>
            <label className="text-[11px] text-krypt-dim">
              Daily loss cap ($)
              <input type="number" min={0.1} step={0.5} defaultValue={config?.perpsFarmDailyLossUsd ?? 2}
                onBlur={setNum('perpsFarmDailyLossUsd')}
                className="mt-1 w-full rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1 text-xs text-white outline-none focus:border-krypt-purple/60" />
            </label>
            <label className="text-[11px] text-krypt-dim">
              Daily volume target ($, 0 = off)
              <input type="number" min={0} step={1000} defaultValue={config?.perpsFarmDailyVolumeUsd ?? 0}
                onBlur={setNum('perpsFarmDailyVolumeUsd')}
                className="mt-1 w-full rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1 text-xs text-white outline-none focus:border-krypt-purple/60" />
            </label>
            <label className="col-span-2 text-[11px] text-krypt-dim">
              Only farm when maker fee ≤ (bps, 0 = off)
              <input type="number" min={0} max={100} step={0.1} defaultValue={config?.perpsFarmMaxFeeBps ?? 0}
                onBlur={setNum('perpsFarmMaxFeeBps')}
                className="mt-1 w-full rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1 text-xs text-white outline-none focus:border-krypt-purple/60" />
              <span className="mt-1 block text-[10px] leading-snug text-krypt-dim">
                Farming cost ≈ the maker fee (5 bps at Tier-0 as of Jul 2026) minus captured spread.
                For a one-time $50-volume reward that's pennies. For anything beyond it, farming is a
                slow bleed — set a cap and the farmer stays idle until fees actually make volume free.
                0 = farm regardless of fee.
              </span>
            </label>
          </div>
        </div>
        <div>
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Volume today" value={f ? `$${f.today.volumeUsd.toLocaleString()}` : '…'} />
            <Stat label="Fees today" value={f ? fmtUsd(-f.today.feesUsd, { sign: true }) : '…'} />
            <Stat label="Net today" value={f ? fmtUsd(f.today.netUsd, { sign: true }) : '…'} />
            <Stat label="Cost / volume" value={f ? `${f.today.costBps.toFixed(1)} bp` : '…'} />
            <Stat label="Fills" value={f ? String(f.today.fills) : '…'} />
            <Stat label="Inventory" value={f ? `${f.inventoryContracts} ct` : '…'} />
            <Stat
              label="Maker fee"
              value={f ? (f.makerFeeBps != null ? `${f.makerFeeBps.toFixed(1)} bp` : '~5 bp*') : '…'}
            />
            <Stat label="Fee cap" value={f && f.maxFeeBps > 0 ? `${f.maxFeeBps} bp` : 'off'} />
          </div>
          <div className="mt-2 space-y-1 text-[11px] text-krypt-dim">
            {f?.liveOrders.map((o) => (
              <div key={o.side} className="font-mono">
                resting {o.side === 'bid' ? 'BUY' : 'SELL'} {o.contracts} @ ${o.price.toFixed(4)}
              </div>
            ))}
            {f?.halted && <div className="text-krypt-warn">⚠ {f.haltReason}</div>}
            {!f?.halted && f?.lastError && <div className="text-krypt-warn">⚠ {f.lastError}</div>}
            {f?.maintenanceWindow && <div className="text-krypt-warn">⚠ Kalshi maintenance window — standing down</div>}
            {f && f.makerFeeBps == null && f.maxFeeBps > 0 && (
              <div>* maker fee assumed at Tier-0 (5 bp) until real fills measure it</div>
            )}
          </div>
          <button
            onClick={() => void flatten()}
            disabled={flattening || !f || (f.inventoryContracts === 0 && f.liveOrders.length === 0)}
            className="mt-3 rounded-md border border-krypt-border bg-krypt-surface2 px-3 py-1.5 text-xs text-krypt-dim transition-colors hover:text-white disabled:opacity-50"
          >
            {flattening ? 'Flattening…' : 'Cancel quotes + flatten inventory'}
          </button>
          <p className="mt-2 text-[10px] leading-relaxed text-krypt-dim">
            The math: maker fee is 5 bps of notional per side (Kalshi's advertised tiered cuts had
            not reached retail accounts as of mid-Jul 2026 — the farmer measures the REAL fee from
            its own fills) minus ~1–3 bps captured spread. $50 of volume for the signup reward costs
            a few cents; there is no ongoing volume reward for retail perps, so farming past the
            coupon only burns fees. The farmer measures its real cost live and stops the moment it
            exceeds the cap. The perps wallet is separate from your event balance: transfer funds on
            Kalshi before arming.
          </p>
        </div>
      </div>
    </Card>
  );
}

function WalletCard({ w }: { w: PerpsWallet | null }) {
  return (
    <Card
      header={
        <div className="flex flex-wrap items-center justify-between gap-1">
          <div className="text-xs uppercase tracking-wider text-krypt-muted">Perpetuals wallet</div>
          <div className="text-[10px] text-krypt-dim">
            {w?.env ? `${w.env} · ` : ''}separate wallet from your main Kalshi cash
          </div>
        </div>
      }
    >
      {w ? (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="Balance" value={fmtUsd(w.settledUsd)} />
            <Stat label="Available to trade" value={fmtUsd(w.availableUsd)} />
            <Stat label="Open positions" value={fmtUsd(w.positionValueUsd)} />
            <Stat label="In resting orders" value={fmtUsd(w.restingMarginUsd)} />
          </div>
          <div className="mt-2 text-[11px] text-krypt-dim">
            Fund this wallet by transferring cash to Perpetuals on Kalshi — money in your main event-market
            balance can’t be traded here, and vice versa.
          </div>
        </>
      ) : (
        <div className="text-xs leading-relaxed text-krypt-dim">
          Perps wallet unavailable — this needs API keys on an account with margin (perpetuals) enabled.
          Once enabled, transfer funds into your Perpetuals wallet on Kalshi and the balance shows here.
        </div>
      )}
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-krypt-surface2/60 p-2">
      <div className="text-[10px] uppercase tracking-wide text-krypt-dim">{label}</div>
      <div className="font-mono text-sm text-white">{value}</div>
    </div>
  );
}
