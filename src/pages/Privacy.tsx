import { AlertTriangle, Check, Globe, Power, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import type { NetworkReport } from '@shared/market';
import { Card, Page, StatCard } from '../components/common';
import { Caveat, Unknown } from '../components/terminal/atoms';
import { useApp } from '../state/AppStateProvider';
import { usePoll } from '../state/TerminalProvider';
import { useToast } from '../state/ToastProvider';
import { cls } from '../utils/format';

const NOT_COUNTED =
  'This host is contacted by a part of the app that does not yet count its '
  + 'calls, so there is no measurement to show — not a claim that it is idle.';

export function PrivacyPage() {
  const { backend } = useApp();
  const toast = useToast();
  const { data, error, loading, reload } = usePoll<NetworkReport>(
    () => window.krypt.terminal.hosts(),
    5_000,
    [],
    backend.status === 'running',
  );

  const stopAll = async (): Promise<void> => {
    try {
      await window.krypt.backend.stop();
      toast.success('Backend stopped. Nothing in this app is contacting anything now.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  const running = backend.status === 'running';

  return (
    <Page
      title="Privacy"
      subtitle="Every host this app can contact, what it is for, and how often it actually has."
      actions={
        <button onClick={reload} className="krypt-btn-default" disabled={!running}>
          <RefreshCw className={cls('h-4 w-4', loading && 'animate-spin')} />
          Refresh
        </button>
      }
    >
      <Card className="mb-4">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="mb-1 text-sm font-medium text-white">
              No server in the middle
            </div>
            <p className="text-[11px] leading-relaxed text-krypt-muted">
              There is no Krypt backend. Your API keys are stored on this machine
              and used to sign requests your machine makes directly to Kalshi.
              Fonts are served from disk, not from a CDN. Nothing about your
              trading is reported home — every host below is one you or the
              exchange needs. The one thing that names the app publicly is
              Discord Rich Presence, described under &ldquo;What is and is not
              here&rdquo; below.
            </p>
          </div>
          <button
            onClick={() => void stopAll()}
            disabled={!running}
            className="krypt-btn-danger shrink-0"
            title="Stops the backend process, which owns every outbound call"
          >
            <Power className="h-4 w-4" />
            Stop all outbound calls
          </button>
        </div>
        <p className="mt-3 text-[10px] leading-relaxed text-krypt-dim">
          That switch stops the backend process. It is the honest version of
          &ldquo;turn it all off&rdquo;: the backend is what makes every request,
          so stopping it stops all of them — and it also stops the bot and the
          Terminal&apos;s live data, which will say so rather than showing stale
          numbers. Start it again from Logs.
        </p>
      </Card>

      {!running ? (
        <Card>
          <div className="py-8 text-center">
            <WifiOff className="mx-auto mb-3 h-8 w-8 text-krypt-dim" />
            <div className="text-sm text-white">Backend stopped</div>
            <p className="mx-auto mt-1 max-w-md text-[11px] leading-relaxed text-krypt-muted">
              Nothing in this app is contacting anything. Live call counts are
              unavailable while it is stopped — the catalogue below still applies
              the moment you start it again.
            </p>
          </div>
        </Card>
      ) : error && !data ? (
        <Caveat className="border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">{error}</Caveat>
      ) : !data ? (
        <Card><div className="py-10 text-center text-sm text-krypt-muted">Reading…</div></Card>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              label="Hosts reachable"
              value={<span className="font-mono">{data.hosts.length}</span>}
              hint="named below, from the code"
            />
            <StatCard
              label="Calls this session"
              value={<span className="font-mono">{data.totalCalls.toLocaleString()}</span>}
              hint="resets when the backend restarts"
            />
            <StatCard
              label="Websocket"
              value={
                <span className={cls(
                  'inline-flex items-center gap-1.5 text-base',
                  data.websocket.connected ? 'text-krypt-win' : 'text-krypt-dim',
                )}>
                  {data.websocket.connected ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />}
                  {data.websocket.connected ? 'connected' : 'off'}
                </span>
              }
              hint={data.websocket.connected
                ? `${data.websocket.subscribedBooks ?? 0} book(s) subscribed`
                : 'no persistent connection'}
            />
            <StatCard
              label="Unlisted hosts"
              value={
                <span className={cls(
                  'font-mono',
                  data.unlisted.length ? 'text-krypt-loss' : 'text-krypt-win',
                )}>
                  {data.unlisted.length}
                </span>
              }
              hint={data.unlisted.length ? 'the catalogue is out of date' : 'nothing uncatalogued'}
            />
          </div>

          {data.unlisted.length > 0 && (
            <Caveat className="mb-4 border-krypt-loss/40 bg-krypt-loss/5 text-krypt-loss">
              These hosts were contacted but are not in the catalogue:{' '}
              {data.unlisted.map((u) => u.host).join(', ')}. That is a bug in this
              panel, and it is shown rather than hidden — a privacy report that
              silently misses a host is worse than none.
            </Caveat>
          )}

          <div className="space-y-2">
            {data.hosts.map((h) => (
              <div
                key={h.host}
                className={cls(
                  'rounded-xl border px-4 py-3',
                  h.calls === null || h.calls > 0
                    ? 'border-krypt-border bg-krypt-surface'
                    : 'border-krypt-border/60 bg-krypt-surface/40',
                )}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Globe className="h-3.5 w-3.5 shrink-0 text-krypt-dim" />
                  <span className="font-mono text-sm text-white">{h.host}</span>
                  <span
                    className={cls(
                      'rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider',
                      h.required
                        ? 'bg-krypt-indigo/15 text-krypt-indigo'
                        : 'bg-white/5 text-krypt-dim',
                    )}
                  >
                    {h.required ? 'required' : 'optional'}
                  </span>
                  <div className="ml-auto flex items-center gap-3 font-mono text-[11px]">
                    <span className={h.calls ? 'text-white' : 'text-krypt-dim'}>
                      {h.calls === null
                        ? <Unknown why={NOT_COUNTED} />
                        : `${h.calls.toLocaleString()} calls`}
                    </span>
                    <span className={h.errors ? 'text-krypt-loss' : 'text-krypt-dim'}>
                      {h.errors === null
                        ? <Unknown why={NOT_COUNTED} />
                        : `${h.errors} err`}
                    </span>
                    <span className="text-krypt-dim">
                      {h.avgMs === null
                        ? <Unknown why={h.calls === null
                            ? NOT_COUNTED
                            : 'Not called yet this session.'} />
                        : `${h.avgMs.toFixed(0)}ms avg`}
                    </span>
                  </div>
                </div>

                <p className="mt-1.5 text-[11px] leading-relaxed text-krypt-muted">
                  {h.purpose}
                </p>

                <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-krypt-dim">
                  <span><span className="text-krypt-muted">When:</span> {h.when}</span>
                  <span><span className="text-krypt-muted">Sends:</span> {h.sends}</span>
                  {h.optional_off && (
                    <span><span className="text-krypt-muted">Stop it:</span> {h.optional_off}</span>
                  )}
                </div>

                {h.lastError && (
                  <div className="mt-1.5 flex gap-1.5 text-[10px] text-krypt-warn">
                    <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
                    <span>last error: {h.lastError}</span>
                  </div>
                )}
              </div>
            ))}
          </div>

          <Card className="mt-4">
            <div className="flex gap-2.5">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-krypt-win" />
              <div>
                <div className="text-[11px] font-medium text-white">
                  What is and is not here
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-krypt-muted">
                  No crash reporting, no analytics SDK, no remote fonts, no
                  auto-update ping, no per-install identifier, and nothing that
                  reports your balance, positions or P&amp;L back to us.
                  Notifications are OS notifications and stay on this machine.
                </p>
                <p className="mt-2 text-[11px] leading-relaxed text-krypt-muted">
                  <span className="text-white">Discord Rich Presence</span> is
                  the exception worth naming. If the Discord desktop app is
                  running on this machine, Krypt Trader sets your status to
                  &ldquo;Auto-trading on Kalshi&rdquo; with a link back to
                  krypt.cc — that is how the app gets found, and it is always
                  on. It goes over a local pipe to your Discord client, not to
                  a Krypt server, and it carries{' '}
                  <span className="text-white">no</span> account details: no
                  balance, no positions, no P&amp;L, no ticker, not even whether
                  trading is running. Your Discord friends can see you have it
                  open; that is the whole of it. Quit Discord, or set its
                  activity privacy to off, and it stops.
                </p>
                <p className="mt-2 text-[11px] leading-relaxed text-krypt-muted">
                  <span className="text-white">AI agents (MCP)</span> are the other
                  path worth naming, and they are off until you switch them on under
                  AI Agents. The app itself still contacts no AI service for them:
                  it opens a server on this machine only (127.0.0.1, token
                  required), and the AI client <em>you</em> connect — Cursor, Claude,
                  Codex — sends what it reads to its own provider (Cursor,
                  Anthropic, OpenAI). That is market data; with live trading on it
                  includes your positions and balance; with the research permission
                  on, your collected data and trade history. Autopilot is the one
                  case where the app calls an AI provider on a timer, with your own
                  key, only while you have it switched on. Everything an agent did
                  is listed on the AI Agents page.
                </p>
              </div>
            </div>
          </Card>

          <p className="mt-4 text-[11px] leading-relaxed text-krypt-dim">{data.note}</p>
        </>
      )}
    </Page>
  );
}
