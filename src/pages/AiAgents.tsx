import { useEffect, useState } from 'react';
import {
  AlertTriangle, Bot, CheckCircle2, Copy, Lock, RefreshCw, RotateCcw, ShieldAlert,
  XCircle,
} from 'lucide-react';
import type {
  ForecastScore, ForecastScoreboard, McpActivity, McpClient, McpStatus,
  McpTradeMode,
} from '@shared/market';
import type { TraderConfig } from '@shared/types';
import {
  Card, ConfirmDialog, Empty, NumberInput, Page, Section, StatCard, Switch,
} from '../components/common';
import { Caveat } from '../components/terminal/atoms';
import { AutopilotPanel } from '../components/AutopilotPanel';
import { useApp } from '../state/AppStateProvider';
import { usePoll } from '../state/TerminalProvider';
import { useToast } from '../state/ToastProvider';
import { cls, fmtCents, fmtNum, fmtTimeShort, fmtUsd } from '../utils/format';

const CLIENTS: { id: McpClient; name: string; where: string }[] = [
  {
    id: 'cursor', name: 'Cursor',
    where: 'Cursor Settings → MCP → Add new MCP server, or merge into ~/.cursor/mcp.json.',
  },
  {
    id: 'claude-code', name: 'Claude Code',
    where: 'Paste the copied command into a terminal. It registers the server for your user account, in every project.',
  },
  {
    id: 'claude-desktop', name: 'Claude Desktop',
    where: 'Settings → Developer → Edit Config, merge into claude_desktop_config.json, then fully quit and restart Claude. (Microsoft Store installs read a different copy of that file, under %LOCALAPPDATA%\\Packages\\Claude_…)',
  },
  {
    id: 'codex', name: 'Codex',
    where: 'Append to ~/.codex/config.toml (once — a second copy is a parse error), then restart Codex.',
  },
];

const PERMS: {
  key: keyof TraderConfig; label: string; description: string; danger?: string;
}[] = [
  {
    key: 'mcpAllowResearch',
    label: 'Read collected data & run backtests',
    description: 'Recorded 15m signals and ticks, whale trades, momentum alerts, your trade history; the same backtesters as the Backtest page. Read-only — nothing is saved or traded.',
  },
  {
    key: 'mcpAllowScripts',
    label: 'Write & backtest strategy scripts',
    description: 'Read the script guide, write scripts, validate and backtest them, save them. Always sandboxed, always saved switched off.',
  },
  {
    key: 'mcpAllowScriptRun',
    label: 'Switch its own scripts on and off',
    description: 'Only scripts the agent wrote. Whether an enabled script places paper or live orders is still decided by the Scripts page switches.',
    danger: 'An agent will be able to start strategy scripts it wrote. If Scripts are set to live on the Scripts page, those scripts place real orders within the script caps.',
  },
  {
    key: 'mcpAllowConfig',
    label: 'Change strategy settings',
    description: 'Entry thresholds, categories, 15m direction mode, order style and the like. Not on/off switches, not risk limits.',
  },
  {
    key: 'mcpAllowLiveSwitches',
    label: 'Engine switches, live mode & risk limits',
    description: 'Full control: turn engines on/off, switch 15m crypto / Scripts / perps to live, change sizing, stop-losses and exposure limits.',
    danger: 'An agent will be able to turn trading engines on, switch them to live, and loosen your risk limits — without asking you per change. Every change is logged and pushed to your phone if remote alerts are on.',
  },
];

const VERDICT: Record<ForecastScore['verdict'], { text: string; tone: string }> = {
  'too-few': {
    text: 'Not enough settled markets to say anything yet. Keep forecasting — and do not size a position off this.',
    tone: 'text-krypt-muted',
  },
  indistinguishable: {
    text: 'No measurable difference from the market price. The AI’s "edges" are not distinguishable from noise.',
    tone: 'text-krypt-warn',
  },
  'ai-better': {
    text: 'The AI beat the market price on settled markets, by more than two standard errors. Past markets, not a promise.',
    tone: 'text-krypt-win',
  },
  'market-better': {
    text: 'The market price beat the AI. When they disagreed, the market was usually right — its edges were not edges.',
    tone: 'text-krypt-loss',
  },
};

export function AiAgentsPage() {
  const { config, refresh } = useApp();
  const toast = useToast();
  const [armLive, setArmLive] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [armPerm, setArmPerm] = useState<(typeof PERMS)[number] | null>(null);
  const [confirmNoApproval, setConfirmNoApproval] = useState(false);
  const [deciding, setDeciding] = useState<number | null>(null);

  const decide = async (id: number, approve: boolean): Promise<void> => {
    setDeciding(id);
    try {
      const res = await window.krypt.terminal.mcpDecide({ id, approve });
      if (res.ok) toast.success(res.message); else toast.warn(res.message);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setDeciding(null);
      status.reload();
      activity.reload();
    }
  };
  const [busy, setBusy] = useState<string | null>(null);

  const status = usePoll<McpStatus>(() => window.krypt.terminal.mcpStatus(), 5_000, []);
  const activity = usePoll<McpActivity>(
    () => window.krypt.terminal.mcpActivity({ limit: 100 }), 10_000, []);
  const board = usePoll<ForecastScoreboard>(
    () => window.krypt.terminal.aiScoreboard(), 30_000, []);

  useEffect(() => window.krypt.terminal.onMcpOrder((d) => {
    toast.push(`AI agent — ${d.message}`,
      d.mode === 'live' || /LIVE|ENABLED/.test(d.message) ? 'warn' : 'info', 8_000);
    activity.reload();
    status.reload();
  }), []);

  const patch = async (p: Record<string, unknown>): Promise<void> => {
    await window.krypt.config.update(p as never);
    await refresh.state();
    status.reload();
  };

  const copy = async (client: McpClient, name: string): Promise<void> => {
    setBusy(client);
    try {
      await window.krypt.terminal.mcpCopyConfig({ client });
      toast.success(`${name} config copied. It contains your agent token — treat it like a password.`);
      status.reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const s = status.data;
  const mode: McpTradeMode = (config?.mcpTradeMode ?? 'paper') as McpTradeMode;
  const env = s?.env ?? config?.kalshiEnv ?? 'demo';

  return (
    <Page
      title="AI Agents"
      subtitle="Let Cursor, Claude or Codex read Kalshi, forecast, and trade — on paper first, inside rails."
      actions={
        <button
          onClick={() => { status.reload(); activity.reload(); board.reload(); }}
          className="krypt-btn-default"
        >
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      }
    >
      <Card className="mb-4">
        <div className="flex gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-krypt-warn" />
          <div className="space-y-2 text-[11px] leading-relaxed text-krypt-muted">
            <p className="text-sm font-medium text-white">Read this before letting an AI trade</p>
            <p>
              An agent connects over MCP to a server on <span className="text-white">this
              machine only</span> and needs a token you copy into it. It must{' '}
              <span className="text-white">record a forecast before every buy</span>, and the
              order is refused unless that forecast beats the price by your minimum edge{' '}
              <span className="text-white">after Kalshi&apos;s fee</span>. It has its own
              per-order, daily and position caps on top of the terminal&apos;s, and it can
              only sell or cancel what it opened.
            </p>
            <p>
              <span className="text-white">Paper</span> fills against the real order book with
              imaginary money. <span className="text-white">Live</span> spends your balance.
              On a liquid market the price is already a strong forecast, and most AI
              &ldquo;edges&rdquo; are the model being wrong. The scoreboard below is the
              evidence — run paper until it says otherwise.
            </p>
            <p className="text-krypt-warn">
              Whatever the agent reads — market data, and in live mode your positions — goes
              to the AI provider behind the client (Anthropic, OpenAI, Cursor). That is how an
              agent works.
            </p>
          </div>
        </div>
      </Card>

      {s && s.pending.length > 0 && (
        <Card className="mb-4 ring-1 ring-krypt-warn/40">
          <div className="mb-2 text-sm font-medium text-white">
            Live orders waiting for you ({s.pending.length})
          </div>
          <p className="mb-3 text-[11px] text-krypt-muted">
            Approving re-checks the order against the market as it is now — price, caps and
            today&apos;s loss — before anything is sent. Unanswered orders expire after 10 minutes.
          </p>
          <div className="space-y-2">
            {s.pending.map((o) => (
              <div key={o.id} className="flex items-center gap-3 rounded-lg border border-krypt-border bg-krypt-surface2 px-3 py-2">
                <span className="font-mono text-[11px] text-krypt-dim">#{o.id}</span>
                <span className="font-mono text-xs text-white">
                  {o.action.toUpperCase()} {o.count} {o.side.toUpperCase()} {o.ticker} @ {fmtCents(o.priceCents)}
                </span>
                <span className="text-[11px] text-krypt-muted">
                  {fmtUsd(o.committedUsd)} · {o.client ?? 'agent'} · {fmtTimeShort(o.at)}
                </span>
                <div className="ml-auto flex gap-2">
                  <button
                    onClick={() => void decide(o.id, false)}
                    disabled={deciding === o.id}
                    className="krypt-btn-default text-xs"
                  >
                    Reject
                  </button>
                  <button
                    onClick={() => void decide(o.id, true)}
                    disabled={deciding === o.id}
                    className="krypt-btn-danger text-xs"
                  >
                    Approve &amp; send
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Section title="Connection" description="A loopback MCP server inside the app. Nothing outside this computer can reach it.">
        <Card>
          <ServerRow status={s} error={status.error} />
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <Switch
              checked={!!config?.mcpEnabled}
              onChange={(v) => void patch({ mcpEnabled: v })}
              label="Enable the MCP server"
              description="Off by default. Switching it off closes the port immediately."
            />
            <div>
              <span className="krypt-label">Port</span>
              <NumberInput
                value={config?.mcpPort ?? 47821}
                min={1024}
                max={65535}
                onChange={(v) => void patch({ mcpPort: Math.round(v) })}
              />
              <span className="krypt-hint">
                Change it if another program owns 47821. Re-copy client configs afterwards.
              </span>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3 text-[11px] text-krypt-muted">
            <span>
              Token: {s?.hasToken ? 'set (encrypted)' : 'created on first enable'}
            </span>
            {s?.hasToken && (
              <button onClick={() => setConfirmRotate(true)} className="krypt-btn-ghost text-xs">
                <RotateCcw className="h-3.5 w-3.5" /> Rotate token
              </button>
            )}
            <span className="ml-auto">
              {s?.clients.length ? `Seen: ${s.clients.join(', ')}` : 'No client has connected yet.'}
              {s?.lastCallAt && ` · last call ${fmtTimeShort(s.lastCallAt)} (${s.lastTool})`}
            </span>
          </div>
        </Card>
      </Section>

      <Section title="Connect a client" description="Copies a ready config to your clipboard. The app never shows the token on screen.">
        <div className="grid gap-3 md:grid-cols-2">
          {CLIENTS.map((c) => (
            <Card key={c.id}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-white">{c.name}</div>
                  <p className="mt-1 text-[11px] leading-relaxed text-krypt-muted">{c.where}</p>
                </div>
                <button
                  onClick={() => void copy(c.id, c.name)}
                  disabled={!config?.mcpEnabled || busy === c.id}
                  className="krypt-btn-default shrink-0"
                  title={config?.mcpEnabled ? 'Copy config' : 'Enable the server first'}
                >
                  <Copy className="h-4 w-4" /> Copy
                </button>
              </div>
            </Card>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-krypt-dim">
          Then ask the agent something like: &ldquo;Use krypt-trader. Check get_status, look
          through closing markets, read the rules, and record honest forecasts. Only trade
          where your edge clears the minimum.&rdquo;
        </p>
      </Section>

      <Section title="Trading" description="What a connected agent may do with orders.">
        <Card>
          <div className="flex gap-2">
            {(['off', 'paper', 'live'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  if (m === 'live' && mode !== 'live') setArmLive(true);
                  else void patch({ mcpTradeMode: m });
                }}
                className={cls(
                  'flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition',
                  mode === m
                    ? m === 'live'
                      ? 'border-krypt-loss/60 bg-krypt-loss/10 text-white'
                      : 'border-krypt-glow/60 bg-krypt-glow/10 text-white'
                    : 'border-krypt-border bg-krypt-surface2 text-krypt-muted hover:border-krypt-borderHi',
                )}
              >
                {m === 'off' ? 'Read only' : m === 'paper' ? 'Paper' : 'Live'}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-krypt-muted">
            {mode === 'off' && 'Agents can read markets and record forecasts. No order tools are offered.'}
            {mode === 'paper' && 'Orders fill immediate-or-cancel against the real book, with imaginary money, and settle on the real outcome.'}
            {mode === 'live' && (
              <span className="text-krypt-loss">
                Orders spend your real balance on the <span className="font-mono">{env}</span>{' '}
                environment, through the same path as the desktop ticket.
              </span>
            )}
          </p>
          {mode === 'live' && (
            <div className="mt-3">
              <Switch
                checked={config?.mcpLiveApproval !== false}
                onChange={(v) => {
                  if (v) void patch({ mcpLiveApproval: true });
                  else setConfirmNoApproval(true);
                }}
                label="Ask me before each live order"
                description="On by default. Each live order waits here (and on your phone, if remote alerts are on) until you approve it."
              />
            </div>
          )}

          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <Rail label="Max per order" hint="Fees included.">
              <NumberInput prefix="$" value={config?.mcpMaxOrderUsd ?? 25} min={1}
                onChange={(v) => void patch({ mcpMaxOrderUsd: v })} />
            </Rail>
            <Rail label="Max spend per day (UTC)"
              hint={s ? `${fmtUsd(s.spentTodayUsd)} used today in ${mode}.` : undefined}>
              <NumberInput prefix="$" value={config?.mcpDailySpendUsd ?? 100} min={1}
                onChange={(v) => void patch({ mcpDailySpendUsd: v })} />
            </Rail>
            <Rail label="Max open positions">
              <NumberInput value={config?.mcpMaxPositions ?? 10} min={1} max={200}
                onChange={(v) => void patch({ mcpMaxPositions: Math.round(v) })} />
            </Rail>
            <Rail label="Minimum edge" hint="Per contract, after Kalshi's fee, vs the agent's own forecast.">
              <NumberInput suffix="¢" value={config?.mcpMinEdgeCents ?? 3} min={0} max={50}
                onChange={(v) => void patch({ mcpMinEdgeCents: v })} />
            </Rail>
            <Rail label="Daily loss stop"
              hint={s?.lossToday ? `Down ${fmtUsd(s.lossToday.lossUsd)} today (realised + open losses). Buys stop at the limit; exits never do.` : 'Realised + open losses, per UTC day. Buys stop at the limit; exits never do.'}>
              <NumberInput prefix="$" value={config?.mcpDailyLossUsd ?? 50} min={1}
                onChange={(v) => void patch({ mcpDailyLossUsd: v })} />
            </Rail>
            <Rail label="Paper bankroll" hint="Starting cash for the paper book.">
              <NumberInput prefix="$" value={config?.mcpPaperBankrollUsd ?? 1000} min={10}
                onChange={(v) => void patch({ mcpPaperBankrollUsd: v })} />
            </Rail>
          </div>
        </Card>
      </Section>

      <Section
        title="Permissions"
        description="Everything beyond single-market trading is a separate switch. All off by default. Reconnect your client after changing these so it sees the new tools."
      >
        <Card>
          <div className="grid gap-3 md:grid-cols-2">
            {PERMS.map((perm) => (
              <Switch
                key={perm.key}
                checked={!!config?.[perm.key]}
                onChange={(v) => {
                  if (v && perm.danger) setArmPerm(perm);
                  else void patch({ [perm.key]: v });
                }}
                label={perm.label}
                description={perm.description}
                disabled={!config?.mcpEnabled}
              />
            ))}
          </div>
          {s && (
            <p className="mt-3 text-[11px] text-krypt-dim">
              A connected client currently sees {s.toolCount} tools.
            </p>
          )}
          <div className="mt-4 flex gap-2 rounded-lg border border-krypt-border bg-krypt-surface2 p-3 text-[11px] leading-relaxed text-krypt-muted">
            <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-krypt-dim" />
            <div>
              <span className="text-white">Never available to an agent, whatever is switched on:</span>{' '}
              changing demo ↔ production; your API keys, bot tokens and webhooks; its own
              permissions and caps; trusted (un-sandboxed) scripts — an agent reads text other
              people wrote, and a prompt injection that reached &ldquo;run this as trusted&rdquo;
              would be code running next to your Kalshi key; the terminal&apos;s ticket caps; and
              the data recorders its own backtests are judged on.
            </div>
          </div>
        </Card>
      </Section>

      <AutopilotPanel />

      <Scoreboard board={board.data} error={board.error} />

      <PaperAndOrders
        data={activity.data}
        error={activity.error}
        onReset={() => setConfirmReset(true)}
      />

      <ConfirmDialog
        open={armLive}
        title="Let an AI agent spend real money?"
        danger
        confirmLabel="Allow live trading"
        onClose={() => setArmLive(false)}
        onConfirm={() => { setArmLive(false); void patch({ mcpTradeMode: 'live' }); }}
        body={
          <div className="space-y-2">
            <p>
              Connected agents will be able to place real orders on the{' '}
              <span className="font-mono text-white">{env}</span> environment without asking
              you per order — unless your MCP client asks you to approve each tool call.
            </p>
            <p>
              Every buy still needs a forecast that clears your minimum edge after fees, and
              stays inside {fmtUsd(config?.mcpMaxOrderUsd ?? 25)} per order and{' '}
              {fmtUsd(config?.mcpDailySpendUsd ?? 100)} per day. The terminal&apos;s own caps and
              the backend pause still apply.
            </p>
            <p className="text-krypt-warn">
              Scoreboard right now: {board.data
                ? VERDICT[board.data.overall.verdict].text
                : 'unavailable.'}
            </p>
          </div>
        }
      />
      <ConfirmDialog
        open={armPerm !== null}
        title={`Allow: ${armPerm?.label ?? ''}?`}
        danger
        confirmLabel="Allow"
        onClose={() => setArmPerm(null)}
        onConfirm={() => {
          if (armPerm) void patch({ [armPerm.key]: true });
          setArmPerm(null);
        }}
        body={
          <div className="space-y-2">
            <p>{armPerm?.danger}</p>
            <p>
              Environment right now: <span className="font-mono text-white">{env}</span>. You can
              switch this off at any time; the agent cannot switch it back on.
            </p>
          </div>
        }
      />
      <ConfirmDialog
        open={confirmNoApproval}
        title="Let agents place live orders without asking?"
        danger
        confirmLabel="Stop asking"
        onClose={() => setConfirmNoApproval(false)}
        onConfirm={() => { setConfirmNoApproval(false); void patch({ mcpLiveApproval: false }); }}
        body={
          <div className="space-y-2">
            <p>
              Connected agents and Autopilot will send live orders on the{' '}
              <span className="font-mono text-white">{env}</span> environment the moment they pass
              the rails — no approval step.
            </p>
            <p>
              The forecast gate, the per-order, daily-spend and daily-loss caps, and the terminal&apos;s
              own caps still apply. You will still be told about every order.
            </p>
          </div>
        }
      />
      <ConfirmDialog
        open={confirmReset}
        title="Reset the paper book?"
        danger
        confirmLabel="Reset"
        onClose={() => setConfirmReset(false)}
        onConfirm={() => {
          setConfirmReset(false);
          void window.krypt.terminal.mcpPaperReset().then((r) => {
            toast.success(`Paper book reset (${r.removed} fills removed). Forecasts are kept.`);
            activity.reload();
          });
        }}
        body={<p>All paper positions and fills are removed and cash returns to the bankroll. The forecast scoreboard is not touched.</p>}
      />
      <ConfirmDialog
        open={confirmRotate}
        title="Rotate the agent token?"
        confirmLabel="Rotate"
        onClose={() => setConfirmRotate(false)}
        onConfirm={() => {
          setConfirmRotate(false);
          void window.krypt.terminal.mcpRotateToken().then(() => {
            toast.success('New token. Re-copy the config into every client you use.');
            status.reload();
          });
        }}
        body={<p>Every client configured with the current token stops working until you copy the new config into it. Do this if a config file may have leaked.</p>}
      />
    </Page>
  );
}

function ServerRow({ status, error }: { status: McpStatus | null; error: string | null }) {
  const running = !!status?.running;
  const enabled = !!status?.enabled;
  const Icon = running ? CheckCircle2 : status?.lastError ? AlertTriangle : XCircle;
  const tone = running ? 'text-krypt-win' : status?.lastError ? 'text-krypt-warn' : 'text-krypt-dim';
  return (
    <div>
      <div className="flex items-center gap-2">
        <Icon className={cls('h-4 w-4', tone)} />
        <Bot className="h-4 w-4 text-krypt-muted" />
        <span className="text-sm text-white">MCP server</span>
        <span className={cls('text-[11px]', tone)}>
          {running ? `listening on 127.0.0.1:${status?.port}` : enabled ? 'not listening' : 'off'}
        </span>
        {status && running && (
          <span className="ml-auto font-mono text-[11px] text-krypt-dim">
            {fmtNum(status.calls)} tool call{status.calls === 1 ? '' : 's'} this session
          </span>
        )}
      </div>
      {(status?.lastError || error) && (
        <div className="mt-1 flex gap-1.5 text-[11px] leading-relaxed text-krypt-warn">
          <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
          <span>{status?.lastError ?? error}</span>
        </div>
      )}
    </div>
  );
}

function Rail({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="krypt-label">{label}</span>
      {children}
      {hint && <span className="krypt-hint">{hint}</span>}
    </div>
  );
}

const brier = (v: number | null): string => (v === null ? '—' : v.toFixed(4));

function Scoreboard({ board, error }: { board: ForecastScoreboard | null; error: string | null }) {
  const o = board?.overall;
  return (
    <Section
      title="Does the AI beat the market?"
      description="Every AI fair value — from the Terminal's Analyse button and from agents — scored against the market price at that moment, once the market settles. Brier score: lower is better."
    >
      {error && <Caveat className="mb-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">{error}</Caveat>}
      {!board || !o ? (
        <Card><div className="py-6 text-center text-sm text-krypt-muted">Loading…</div></Card>
      ) : board.totalForecasts === 0 ? (
        <Empty
          title="No forecasts yet"
          description="Run Analyse on a market in the Terminal, or let an agent call record_forecast. Each one is scored when its market settles."
        />
      ) : (
        <>
          <Card className="mb-3">
            <p className={cls('text-sm', VERDICT[o.verdict].tone)}>{VERDICT[o.verdict].text}</p>
            <p className="mt-1 text-[11px] text-krypt-dim">
              {o.nPaired} of {board.minScored} settled markets needed for a verdict
              {o.diffSe !== null && o.diffMean !== null && (
                <> · AI − market Brier {o.diffMean >= 0 ? '+' : ''}{o.diffMean.toFixed(4)} ± {(2 * o.diffSe).toFixed(4)} (2 s.e.)</>
              )}
            </p>
          </Card>
          <div className="mb-3 grid gap-3 md:grid-cols-4">
            <StatCard label="AI Brier" value={brier(o.brierAiPaired ?? o.brierAi)}
              hint="On markets that had a two-sided quote" />
            <StatCard label="Market Brier" value={brier(o.brierMarket)}
              hint="The mid at the moment of each forecast" />
            <StatCard
              label="Skill vs market"
              value={o.skill === null ? '—' : `${(o.skill * 100).toFixed(1)}%`}
              accent={o.verdict === 'ai-better' ? 'good' : o.verdict === 'market-better' ? 'bad' : 'neutral'}
              hint=">0 means the AI's error was smaller"
            />
            <StatCard label="Settled / pending"
              value={`${board.scoredMarkets} / ${board.pending}`}
              hint={`${board.totalForecasts} forecasts recorded`} />
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card header={<span className="text-xs font-medium text-white">By source</span>}>
              <table className="krypt-table">
                <thead>
                  <tr>
                    <th className="krypt-th">Source</th>
                    <th className="krypt-th text-right">Markets</th>
                    <th className="krypt-th text-right">AI</th>
                    <th className="krypt-th text-right">Market</th>
                    <th className="krypt-th">Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {board.bySource.map((r) => (
                    <tr key={r.source}>
                      <td className="krypt-td">{r.source === 'panel' ? 'Analyse button' : 'MCP agents'}</td>
                      <td className="krypt-td text-right font-mono">{r.nPaired}/{r.n}</td>
                      <td className="krypt-td text-right font-mono">{brier(r.brierAiPaired ?? r.brierAi)}</td>
                      <td className="krypt-td text-right font-mono">{brier(r.brierMarket)}</td>
                      <td className={cls('krypt-td text-[11px]', VERDICT[r.verdict].tone)}>{r.verdict}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card header={<span className="text-xs font-medium text-white">Calibration — when it said X%, how often was it YES?</span>}>
              {board.buckets.length === 0 ? (
                <p className="py-4 text-center text-xs text-krypt-muted">Nothing settled yet.</p>
              ) : (
                <table className="krypt-table">
                  <thead>
                    <tr>
                      <th className="krypt-th">Said</th>
                      <th className="krypt-th text-right">n</th>
                      <th className="krypt-th text-right">Avg forecast</th>
                      <th className="krypt-th text-right">Happened</th>
                    </tr>
                  </thead>
                  <tbody>
                    {board.buckets.map((b) => (
                      <tr key={b.lo}>
                        <td className="krypt-td font-mono">{Math.round(b.lo * 100)}–{Math.round(b.hi * 100)}%</td>
                        <td className="krypt-td text-right font-mono">{b.n}</td>
                        <td className="krypt-td text-right font-mono">{(b.meanForecast * 100).toFixed(0)}%</td>
                        <td className="krypt-td text-right font-mono">{(b.hitRate * 100).toFixed(0)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>

          <Card className="mt-3" header={<span className="text-xs font-medium text-white">Recent forecasts</span>}>
            <table className="krypt-table">
              <thead>
                <tr>
                  <th className="krypt-th w-20">When</th>
                  <th className="krypt-th">Market</th>
                  <th className="krypt-th w-28">By</th>
                  <th className="krypt-th w-16 text-right">AI</th>
                  <th className="krypt-th w-16 text-right">Mid</th>
                  <th className="krypt-th w-20 text-right">Result</th>
                </tr>
              </thead>
              <tbody>
                {board.recent.map((r) => (
                  <tr key={r.id}>
                    <td className="krypt-td text-krypt-muted">{fmtTimeShort(r.createdAt)}</td>
                    <td className="krypt-td">
                      <div className="font-mono text-[11px] text-white/90">{r.ticker}</div>
                      {r.title && <div className="truncate text-[11px] text-krypt-dim">{r.title}</div>}
                    </td>
                    <td className="krypt-td text-[11px] text-krypt-muted">{r.model ?? r.source}</td>
                    <td className="krypt-td text-right font-mono">{fmtCents(r.fairValueCents)}</td>
                    <td className="krypt-td text-right font-mono">{fmtCents(r.marketMidCents)}</td>
                    <td className="krypt-td text-right font-mono">
                      {r.outcome === null ? <span className="text-krypt-dim">pending</span>
                        : r.outcome === 1 ? 'YES' : r.outcome === 0 ? 'NO' : `${(r.outcome * 100).toFixed(0)}¢`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </Section>
  );
}

function PaperAndOrders({
  data, error, onReset,
}: { data: McpActivity | null; error: string | null; onReset: () => void }) {
  const paper = data?.paper;
  const unreal = paper?.positions.reduce<number | null>(
    (acc, p) => (acc === null || p.unrealizedUsd === null ? null : acc + p.unrealizedUsd), 0) ?? null;
  return (
    <Section title="Agent activity" description="Every order, script and settings change an agent attempted — refused ones too.">
      {error && <Caveat className="mb-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">{error}</Caveat>}
      {paper && (
        <div className="mb-3 grid gap-3 md:grid-cols-4">
          <StatCard label="Paper cash" value={fmtUsd(paper.cashUsd)} hint={`of ${fmtUsd(paper.bankrollUsd)} bankroll`} />
          <StatCard
            label="Paper realised"
            value={fmtUsd(paper.realizedUsd, { sign: true })}
            accent={paper.realizedUsd > 0 ? 'good' : paper.realizedUsd < 0 ? 'bad' : 'neutral'}
            hint="Net of fees, at the real outcome"
          />
          <StatCard
            label="Paper unrealised"
            value={fmtUsd(unreal, { sign: true })}
            hint={unreal === null && paper.positions.length ? 'A held side has no bid to mark at' : `${paper.positions.length} open`}
          />
          <div className="krypt-card flex items-center justify-center">
            <button onClick={onReset} className="krypt-btn-ghost text-xs">
              <RotateCcw className="h-3.5 w-3.5" /> Reset paper book
            </button>
          </div>
        </div>
      )}
      {paper && paper.positions.length > 0 && (
        <Card className="mb-3" header={<span className="text-xs font-medium text-white">Paper positions</span>}>
          <table className="krypt-table">
            <thead>
              <tr>
                <th className="krypt-th">Market</th>
                <th className="krypt-th w-16">Side</th>
                <th className="krypt-th w-20 text-right">Held</th>
                <th className="krypt-th w-20 text-right">Avg</th>
                <th className="krypt-th w-20 text-right">Bid</th>
                <th className="krypt-th w-24 text-right">Unrealised</th>
              </tr>
            </thead>
            <tbody>
              {paper.positions.map((p) => (
                <tr key={`${p.ticker}-${p.side}`}>
                  <td className="krypt-td">
                    <div className="font-mono text-[11px] text-white/90">{p.ticker}</div>
                    {p.title && <div className="truncate text-[11px] text-krypt-dim">{p.title}</div>}
                  </td>
                  <td className="krypt-td uppercase">{p.side}</td>
                  <td className="krypt-td text-right font-mono">{p.contracts}</td>
                  <td className="krypt-td text-right font-mono">{fmtCents(p.avgCostCents)}</td>
                  <td className="krypt-td text-right font-mono">{fmtCents(p.markCents)}</td>
                  <td className="krypt-td text-right font-mono">{fmtUsd(p.unrealizedUsd, { sign: true })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {data && data.actions.length > 0 && (
        <Card className="mb-3" header={<span className="text-xs font-medium text-white">Scripts & settings changes</span>}>
          <table className="krypt-table">
            <thead>
              <tr>
                <th className="krypt-th w-20">When</th>
                <th className="krypt-th w-40">Action</th>
                <th className="krypt-th">Detail</th>
              </tr>
            </thead>
            <tbody>
              {data.actions.map((a) => (
                <tr key={a.id}>
                  <td className="krypt-td text-krypt-muted">{fmtTimeShort(a.at)}</td>
                  <td className="krypt-td font-mono text-[11px] text-white/90">
                    {a.tool}
                    {a.client && <div className="font-sans text-[10px] text-krypt-dim">{a.client}</div>}
                  </td>
                  <td className={cls('krypt-td text-[11px]', a.ok ? 'text-krypt-muted' : 'text-krypt-warn')}>
                    {a.ok ? '' : 'Refused: '}{a.summary}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {!data || data.orders.length === 0 ? (
        <Empty title="No agent orders yet" description="Orders an agent places or attempts show up here, with the reason for every refusal." />
      ) : (
        <Card>
          <table className="krypt-table">
            <thead>
              <tr>
                <th className="krypt-th w-20">When</th>
                <th className="krypt-th w-14">Mode</th>
                <th className="krypt-th">Order</th>
                <th className="krypt-th">Result</th>
              </tr>
            </thead>
            <tbody>
              {data.orders.map((o) => (
                <tr key={o.id}>
                  <td className="krypt-td text-krypt-muted">{fmtTimeShort(o.at)}</td>
                  <td className={cls('krypt-td text-[10px] uppercase tracking-wider',
                    o.mode === 'live' ? 'text-krypt-loss' : 'text-krypt-muted')}>{o.mode}</td>
                  <td className="krypt-td">
                    <span className="font-mono text-[11px] text-white/90">
                      {o.action} {o.count} {o.side.toUpperCase()} {o.ticker} @ {fmtCents(o.priceCents)}
                    </span>
                    {o.client && <div className="text-[10px] text-krypt-dim">{o.client}</div>}
                  </td>
                  <td className={cls('krypt-td text-[11px]', o.ok ? 'text-krypt-win' : o.status === 'pending' ? 'text-krypt-purple' : 'text-krypt-warn')}>
                    {o.status && o.status !== 'approved' && (
                      <span className="mr-1 uppercase tracking-wider">[{o.status}]</span>
                    )}
                    {o.message}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </Section>
  );
}
