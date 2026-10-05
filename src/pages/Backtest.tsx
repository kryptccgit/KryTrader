import { useEffect, useState } from 'react';
import { FlaskConical, Play } from 'lucide-react';
import {
  Area, AreaChart, Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import type { CollectionStats, Crypto15mBacktest, TraderConfig } from '@shared/types';
import { Card, Page, Switch } from '../components/common';
import { useApp } from '../state/AppStateProvider';
import { cls, fmtUsd } from '../utils/format';

type Engine = 'crypto15m' | 'main';

const C15_STRATS: { id: string; name: string; patch: Partial<TraderConfig> }[] = [
  { id: 'current', name: 'My current settings', patch: {} },
  {
    id: 'sniper', name: 'Settlement Sniper',
    patch: {
      crypto15mDirectionMode: 'model', crypto15mUseRules: false,
      crypto15mModelMinProb: 0.97, crypto15mModelMinEdgeCents: 2,
      crypto15mModelFinalMinute: true, crypto15mTimeDelayMin: 5, crypto15mEntryMax: 0.97,
    },
  },
  {
    id: 'favorite', name: 'Deep Favorite',
    patch: {
      crypto15mDirectionMode: 'favorite', crypto15mUseRules: false,
      crypto15mEntryThreshold: 0.95, crypto15mEntryMax: 0.98, crypto15mTimeDelayMin: 6,
    },
  },
  {
    id: 'contrarian', name: 'Contrarian fade',
    patch: {
      crypto15mDirectionMode: 'contrarian', crypto15mUseRules: false,
      crypto15mEntryThreshold: 0.90, crypto15mTimeDelayMin: 8,
    },
  },
];

const WINDOWS = [7, 14, 30, 60];

export function BacktestPage() {
  const [engine, setEngine] = useState<Engine>('crypto15m');
  const [stratSel, setStratSel] = useState('current');
  const [mainSel, setMainSel] = useState('current');
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Crypto15mBacktest | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { config, state } = useApp();
  const profiles = state?.customProfiles ?? [];
  const [coll, setColl] = useState<CollectionStats | null>(null);
  const [showData, setShowData] = useState(false);

  const loadCollection = async () => {
    try {
      setColl(await window.krypt.trading.collection());
    } catch {  }
  };
  useEffect(() => { void loadCollection(); }, []);

  const toggleC15Collection = async (on: boolean) => {
    await window.krypt.config.update({ crypto15mRecordSignals: on });
    void loadCollection();
  };

  const toggleMainCollection = async (on: boolean) => {
    await window.krypt.config.update({ mainRecordSignals: on });
    void loadCollection();
  };

  const [exporting, setExporting] = useState(false);
  const exportData = async () => {
    setExporting(true);
    try {
      await window.krypt.trading.exportData();
    } finally {
      setExporting(false);
    }
  };

  const sliceProfile = (cfg: TraderConfig, kind: 'crypto15m' | 'main'): Partial<TraderConfig> => {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(cfg)) {
      const is15m = k.startsWith('crypto15m');
      if ((kind === 'crypto15m') === is15m) out[k] = v;
    }
    delete out.enableTrading;
    delete out.crypto15mLive;
    return out as Partial<TraderConfig>;
  };

  const resolvePatch = (): Partial<TraderConfig> => {
    const sel = engine === 'crypto15m' ? stratSel : mainSel;
    if (sel.startsWith('profile:')) {
      const prof = profiles.find((pr) => pr.id === sel.slice(8));
      return prof ? sliceProfile(prof.config, engine) : {};
    }
    if (engine === 'crypto15m' && sel.startsWith('preset:')) {
      return C15_STRATS.find((st) => st.id === sel.slice(7))?.patch ?? {};
    }
    return {};
  };

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const patch = resolvePatch();
      const r = engine === 'crypto15m'
        ? await window.krypt.crypto15m.backtest({ sinceDays: days, config: patch })
        : await window.krypt.crypto15m.backtestMain({ sinceDays: days, config: patch });
      setRes(r);
      if (!r) setErr('Engine not running — start the app backend first.');
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page
      title="Backtest"
      subtitle="While the bot runs it records every 15m market tick and every whale/momentum signal it sees, with outcomes. Test any strategy against that collected history — same entry gates as live, real Kalshi fees — and see WHEN the profit happens, not just how much."
    >
      <Card header={<div className="text-xs uppercase tracking-wider text-krypt-muted">Setup</div>}>
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Engine">
            <Chips
              options={[['crypto15m', '15m Crypto'], ['main', 'Main engine (whales + momentum)']]}
              value={engine}
              onPick={(v) => setEngine(v as Engine)}
            />
          </Field>
          {engine === 'crypto15m' && (
            <Field label="Strategy / profile">
              <select
                value={stratSel}
                onChange={(e) => setStratSel(e.target.value)}
                className="rounded-md border border-krypt-border bg-krypt-surface2 px-2.5 py-1.5 text-xs text-white outline-none focus:border-krypt-purple/60"
              >
                <option value="current">Current settings</option>
                <optgroup label="Presets">
                  {C15_STRATS.filter((st) => st.id !== 'current').map((st) => (
                    <option key={st.id} value={`preset:${st.id}`}>{st.name}</option>
                  ))}
                </optgroup>
                {profiles.some((pr) => pr.kind === 'crypto15m') && (
                  <optgroup label="My profiles">
                    {profiles.filter((pr) => pr.kind === 'crypto15m').map((pr) => (
                      <option key={pr.id} value={`profile:${pr.id}`}>{pr.name}</option>
                    ))}
                  </optgroup>
                )}
              </select>
            </Field>
          )}
          {engine === 'main' && (
            <Field label="Strategy / profile">
              <select
                value={mainSel}
                onChange={(e) => setMainSel(e.target.value)}
                className="rounded-md border border-krypt-border bg-krypt-surface2 px-2.5 py-1.5 text-xs text-white outline-none focus:border-krypt-purple/60"
              >
                <option value="current">Current settings (Strategies-page gates)</option>
                {profiles.some((pr) => pr.kind === 'main') && (
                  <optgroup label="My profiles">
                    {profiles.filter((pr) => pr.kind === 'main').map((pr) => (
                      <option key={pr.id} value={`profile:${pr.id}`}>{pr.name}</option>
                    ))}
                  </optgroup>
                )}
              </select>
            </Field>
          )}
          <Field label="Window">
            <Chips
              options={WINDOWS.map((d) => [String(d), `${d}d`] as [string, string])}
              value={String(days)}
              onPick={(v) => setDays(Number(v))}
            />
          </Field>
          <button
            onClick={() => void run()}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-md border border-krypt-purple/40 bg-krypt-purple/10 px-4 py-2 text-xs font-semibold text-krypt-purple transition-colors hover:bg-krypt-purple/20 disabled:opacity-50"
          >
            {busy ? <FlaskConical className="h-3.5 w-3.5 animate-pulse" /> : <Play className="h-3.5 w-3.5" />}
            {busy ? 'Replaying…' : 'Run backtest'}
          </button>
        </div>
        {err && <p className="mt-2 text-xs text-krypt-loss">{err}</p>}
      </Card>

      <div className="mt-4">
        <Card header={<div className="text-xs uppercase tracking-wider text-krypt-muted">Data collection</div>}>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg bg-krypt-surface2/50 p-3">
              <Switch
                checked={config?.crypto15mRecordSignals ?? true}
                onChange={(v) => void toggleC15Collection(v)}
                label="Collect 15m crypto data"
                description="Records every 15-minute market's ticks and outcome while the app is open — no trading, no orders, works with the 15m executor fully off. This is the dataset 15m backtests run on."
              />
              <p className="mt-1.5 text-[11px] text-krypt-dim">
                {coll ? `${coll.c15.windows.toLocaleString()} windows · ${coll.c15.ticks.toLocaleString()} ticks` : '…'}
                {coll?.c15.lastAt ? ` · last ${coll.c15.lastAt.slice(5, 16)} UTC` : ''}
              </p>
            </div>
            <div className="rounded-lg bg-krypt-surface2/50 p-3">
              <Switch
                checked={config?.mainRecordSignals ?? true}
                onChange={(v) => void toggleMainCollection(v)}
                label="Collect whale + momentum signals"
                description="Records whale prints and momentum clusters while the app is open — nothing is bought. Note: if Start Trading is ON, scanning stays on regardless (the engine can't follow signals it never sees)."
              />
              <p className="mt-1.5 text-[11px] text-krypt-dim">
                {coll ? `${coll.main.whales.toLocaleString()} whale signals · ${coll.main.alerts.toLocaleString()} momentum` : '…'}
                {coll?.main.lastAt ? ` · last ${coll.main.lastAt.slice(5, 16)} UTC` : ''}
              </p>
            </div>
          </div>
          <button
            onClick={() => void exportData()}
            disabled={exporting}
            className="mr-2 mt-3 rounded-md border border-krypt-border bg-krypt-surface2 px-3 py-1.5 text-xs text-krypt-dim transition-colors hover:text-white disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Export CSV (all collected data)'}
          </button>
          <button
            onClick={() => setShowData((v) => !v)}
            className="mt-3 rounded-md border border-krypt-border bg-krypt-surface2 px-3 py-1.5 text-xs text-krypt-dim transition-colors hover:text-white"
          >
            {showData ? 'Hide collected data' : 'View collected data'}
          </button>
          {showData && coll && (
            <div className="mt-3 grid gap-4 lg:grid-cols-2">
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-wide text-krypt-dim">Latest 15m windows</div>
                <table className="w-full text-[11px]">
                  <thead><tr className="text-left text-krypt-dim">
                    <th className="py-0.5 pr-2 font-normal">Asset</th>
                    <th className="py-0.5 pr-2 font-normal">Closes</th>
                    <th className="py-0.5 pr-2 font-normal">Favorite</th>
                    <th className="py-0.5 font-normal">Result</th>
                  </tr></thead>
                  <tbody>
                    {coll.c15.recent.map((r) => (
                      <tr key={r.ticker} className="border-t border-krypt-border/50">
                        <td className="py-1 pr-2 font-mono text-white">{r.asset}</td>
                        <td className="py-1 pr-2 text-krypt-dim">{r.close_time?.slice(5, 16)}</td>
                        <td className="py-1 pr-2 text-krypt-dim">
                          {r.favorite ?? '—'}{r.favorite_price != null ? ` @ ${Math.round(r.favorite_price * 100)}¢` : ''}
                        </td>
                        <td className="py-1">
                          {!r.resolved ? <span className="text-krypt-dim">open</span>
                            : r.up_won ? <span className="text-krypt-win">UP won</span>
                              : <span className="text-krypt-loss">DOWN won</span>}
                        </td>
                      </tr>
                    ))}
                    {coll.c15.recent.length === 0 && (
                      <tr><td colSpan={4} className="py-2 text-krypt-dim">Nothing yet — leave the app open with collection on.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-wide text-krypt-dim">Latest whale signals</div>
                <table className="w-full text-[11px]">
                  <thead><tr className="text-left text-krypt-dim">
                    <th className="py-0.5 pr-2 font-normal">Category</th>
                    <th className="py-0.5 pr-2 font-normal">Side</th>
                    <th className="py-0.5 pr-2 font-normal">Price</th>
                    <th className="py-0.5 pr-2 font-normal">Size</th>
                    <th className="py-0.5 font-normal">Result</th>
                  </tr></thead>
                  <tbody>
                    {coll.main.recent.map((r, i) => (
                      <tr key={`${r.ticker}-${i}`} className="border-t border-krypt-border/50">
                        <td className="py-1 pr-2 text-white">{r.category}</td>
                        <td className="py-1 pr-2 font-mono text-krypt-dim">{r.taker_side}</td>
                        <td className="py-1 pr-2 text-krypt-dim">{Math.round((r.price ?? 0) * 100)}¢</td>
                        <td className="py-1 pr-2 text-krypt-dim">${Math.round(r.dollar_value ?? 0).toLocaleString()}</td>
                        <td className="py-1">
                          {!r.resolved ? <span className="text-krypt-dim">open</span>
                            : r.outcome_correct ? <span className="text-krypt-win">won</span>
                              : <span className="text-krypt-loss">lost</span>}
                        </td>
                      </tr>
                    ))}
                    {coll.main.recent.length === 0 && (
                      <tr><td colSpan={5} className="py-2 text-krypt-dim">Nothing yet — signals record while the app is open.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>
      </div>

      {res && res.windowsScanned === 0 && (
        <Card className="mt-4">
          <div className="py-4 text-center">
            <div className="text-sm font-semibold text-white">No collected data yet</div>
            <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-krypt-dim">
              This backtest runs on history YOUR bot collects while it runs. Leave the app open
              (monitor mode is enough — no live trading needed) and it records every
              {engine === 'crypto15m'
                ? ' 15-minute market with its outcome. Make sure the 15m Crypto toggle is on and the environment is Live/production (demo 15m markets are frozen).'
                : ' whale and momentum signal it sees, with outcomes. Data starts accruing immediately.'}
              {' '}Check back after a few hours; the charts get sharper every day it runs.
            </p>
          </div>
        </Card>
      )}
      {res && res.windowsScanned > 0 && res.n === 0 && (
        <Card className="mt-4">
          <div className="text-xs leading-relaxed text-krypt-muted">
            <span className="font-semibold text-krypt-warn">
              0 trades over {res.windowsScanned.toLocaleString()} {engine === 'crypto15m' ? 'windows' : 'bars'} scanned.
            </span>{' '}
            No entries triggered in this window — loosen the entry gates or widen the date range.
          </div>
        </Card>
      )}
      {res && res.windowsScanned > 0 && (
        <>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-6">
            <Stat label="Trades" value={`${res.n}`} sub={`${res.windowsScanned} ${engine === 'crypto15m' ? 'windows' : 'signals'} scanned`} />
            <Stat label="Win rate" value={res.n ? `${(res.winRate * 100).toFixed(1)}%` : '—'} />
            <Stat label="Edge / contract" value={`${res.netEvCentsPerContract.toFixed(2)}¢`} tone={res.netEvCentsPerContract >= 0 ? 'good' : 'bad'} />
            <Stat label="Total P&L" value={fmtUsd(res.totalPnlUsd, { sign: true })} tone={res.totalPnlUsd >= 0 ? 'good' : 'bad'} />
            <Stat label="Max drawdown" value={fmtUsd(res.maxDrawdownUsd)} tone="bad" />
            <Stat label="Days traded" value={`${res.byDay.length}`} />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card header={<ChartHead title="Equity over time" hint="Cumulative P&L in trade order — a healthy strategy climbs steadily; one big lucky step means one event carried it." />}>
              <div className="h-48">
                <ResponsiveContainer>
                  <AreaChart data={res.equity.map((e, i) => ({ i, at: e.at ? e.at.slice(5, 16) : String(i), value: e.value }))}>
                    <XAxis dataKey="at" tick={{ fontSize: 9 }} minTickGap={40} stroke="#555" />
                    <YAxis tick={{ fontSize: 9 }} width={40} stroke="#555" />
                    <Tooltip labelStyle={{ color: '#A1A1AA' }} itemStyle={{ color: '#FFFFFF' }} contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 11 }} formatter={(v: number) => fmtUsd(v, { sign: true })} />
                    <Area dataKey="value" stroke="#a78bfa" fill="#a78bfa22" strokeWidth={1.5} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card header={<ChartHead title="P&L by hour of day (UTC)" hint="The 'first 12 hours print, last 12 lose' check — green bars earn, red bars bleed. Thin bars (low n) are noise, not signal." />}>
              <div className="h-48">
                <ResponsiveContainer>
                  <BarChart data={res.byHourUtc}>
                    <XAxis dataKey="hour" tick={{ fontSize: 9 }} stroke="#555" />
                    <YAxis tick={{ fontSize: 9 }} width={40} stroke="#555" />
                    <Tooltip
                      labelStyle={{ color: '#A1A1AA' }} itemStyle={{ color: '#FFFFFF' }} contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 11 }}
                      formatter={(v: number, _n, item: any) => [`${fmtUsd(v, { sign: true })} (${item?.payload?.wins}/${item?.payload?.n})`, 'P&L']}
                    />
                    <Bar dataKey="pnlUsd">
                      {res.byHourUtc.map((b) => (
                        <Cell key={b.hour} fill={b.pnlUsd >= 0 ? '#34d399' : '#f87171'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          <div className="mt-4">
            <Card header={<ChartHead title="P&L by day" hint="The 'prints one day, sucks the next' check — consistency across days matters more than the total." />}>
              <div className="h-40">
                <ResponsiveContainer>
                  <BarChart data={res.byDay.map((d) => ({ ...d, label: d.day.slice(5) }))}>
                    <XAxis dataKey="label" tick={{ fontSize: 9 }} stroke="#555" />
                    <YAxis tick={{ fontSize: 9 }} width={40} stroke="#555" />
                    <Tooltip
                      labelStyle={{ color: '#A1A1AA' }} itemStyle={{ color: '#FFFFFF' }} contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 11 }}
                      formatter={(v: number, _n, item: any) => [`${fmtUsd(v, { sign: true })} (${item?.payload?.wins}/${item?.payload?.n})`, 'P&L']}
                    />
                    <Bar dataKey="pnlUsd">
                      {res.byDay.map((d) => (
                        <Cell key={d.day} fill={d.pnlUsd >= 0 ? '#34d399' : '#f87171'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          {Object.keys(res.byAsset).length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {Object.entries(res.byAsset).map(([a, st]) => (
                <span key={a} className="rounded bg-krypt-surface2 px-1.5 py-0.5 font-mono text-[10px] text-krypt-dim">
                  {a} {st.wins}/{st.n} <span className={st.pnlUsd >= 0 ? 'text-krypt-win' : 'text-krypt-loss'}>{fmtUsd(st.pnlUsd, { sign: true })}</span>
                </span>
              ))}
            </div>
          )}

          <ul className="mt-3 space-y-0.5">
            {res.caveats.map((c, i) => (
              <li key={i} className="text-[10px] leading-relaxed text-krypt-warn/80">⚠ {c}</li>
            ))}
          </ul>
        </>
      )}
    </Page>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[10px] uppercase tracking-wide text-krypt-dim">{label}</div>
      {children}
    </div>
  );
}

function Chips({ options, value, onPick }: {
  options: [string, string][]; value: string; onPick: (v: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map(([v, label]) => (
        <button
          key={v}
          onClick={() => onPick(v)}
          className={cls(
            'rounded-md border px-2.5 py-1 text-xs transition-colors',
            v === value
              ? 'border-krypt-purple/60 bg-krypt-purple/15 text-krypt-purple'
              : 'border-krypt-border bg-krypt-surface2 text-krypt-dim hover:text-white',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'good' | 'bad' }) {
  return (
    <div className="rounded-lg bg-krypt-surface2/60 p-2">
      <div className="text-[10px] uppercase tracking-wide text-krypt-dim">{label}</div>
      <div className={cls('font-mono text-sm', tone === 'good' ? 'text-krypt-win' : tone === 'bad' ? 'text-krypt-loss' : 'text-white')}>{value}</div>
      {sub && <div className="text-[10px] text-krypt-dim">{sub}</div>}
    </div>
  );
}

function ChartHead({ title, hint }: { title: string; hint: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-krypt-muted">{title}</div>
      <div className="mt-0.5 text-[10px] normal-case tracking-normal text-krypt-dim">{hint}</div>
    </div>
  );
}
