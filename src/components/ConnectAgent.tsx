import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Bot, CheckCircle2, Copy, FolderOpen, Loader2, Wand2 } from 'lucide-react';
import type { McpClient, McpToolCallEvent } from '@shared/market';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { PICKER_KIND, agentIdentity, kindOf } from '../utils/agents';
import { cls } from '../utils/format';
import { DEFAULT_AGENT_ID } from '@shared/agents';
import { Modal } from './common';
import { AutopilotQuickstart } from './AutopilotQuickstart';
import { userMessage } from '../utils/errors';


export const AGENT_CLIENTS: { id: McpClient; name: string; where: string; oneClick?: boolean }[] = [
  {
    id: 'claude-code', name: 'Claude Code',
    where: 'Paste the copied command into a terminal. It registers the server for your user account, in every project.',
  },
  {
    id: 'cursor', name: 'Cursor',
    where: 'Cursor Settings → MCP → Add new MCP server, or merge into ~/.cursor/mcp.json.',
  },
  {
    id: 'claude-desktop', name: 'Claude Desktop', oneClick: true,
    where: 'Press Add to Claude Desktop (the app edits its config for you, keeping a backup), then fully quit Claude Desktop — right-click its tray icon → Quit — and open it again. Or copy the config and merge it in by hand via Settings → Developer → Edit Config.',
  },
  {
    id: 'codex', name: 'Codex', oneClick: true,
    where: 'Press Add to Codex (it replaces an older krypt-trader entry instead of adding a second, and keeps a backup), then restart Codex. Pasting by hand into ~/.codex/config.toml? Replace any earlier [mcp_servers.krypt-trader] block — two copies break the file.',
  },
];

export const WAIT_HINT_MS = 60_000;

export type Pick = McpClient | 'autopilot';

const SEEN_FALLBACK_MS = 5_000;

export function ConnectAgent({
  paperDefault, onAutopilot, autopilotSetup = 'modal', className, agentId, hideAutopilot, serverName,
}: {
  serverName?: string;
  paperDefault?: boolean;
  agentId?: string;
  hideAutopilot?: boolean;
  onAutopilot: () => void;
  autopilotSetup?: 'modal' | 'callback';
  className?: string;
}) {
  const { config, refresh, backend } = useApp();
  const toast = useToast();
  const [quick, setQuick] = useState(false);
  const [pick, setPick] = useState<Pick>(hideAutopilot ? 'claude-code' : 'autopilot');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<McpClient | null>(null);
  const [copiedAt, setCopiedAt] = useState<number | null>(null);
  const engineDown = backend?.status !== 'running';
  const [seen, setSeen] = useState<{ label: string; what: string } | null>(null);
  const [other, setOther] = useState<string | null>(null);
  const pickRef = useRef(pick);
  pickRef.current = pick;

  const want = pick === 'autopilot' ? null : PICKER_KIND[pick];
  const liveNow = config?.mcpTradeMode === 'live';

  useEffect(() => {
    setSeen(null);
    setOther(null);
    if (!want) return;
    const off = window.krypt.terminal.onMcpToolCall?.((d: McpToolCallEvent) => {
      const k = kindOf(d?.client, d?.transport);
      const id = agentIdentity({ client: d?.client, model: d?.model, transport: d?.transport });
      if (agentId && d?.agentId && d.agentId !== agentId) return;
      if (k === want) {
        setSeen({ label: id.label, what: d.kind === 'connect' ? 'connected' : `called ${d.tool ?? 'a tool'}` });
      } else if (k !== 'autopilot') {
        setOther(id.label);
      }
    });
    return () => { off?.(); };
  }, [want, agentId]);

  useEffect(() => {
    if (!want || seen) return;
    let alive = true;
    const read = async () => {
      try {
        const s = await window.krypt.terminal.mcpSeen?.();
        if (!alive || !s) return;
        const hit = s.clients.find((c) => kindOf(c.client) === want
          && (!agentId || !c.agentId || c.agentId === agentId));
        if (hit) {
          const id = agentIdentity({ client: hit.client, model: hit.model });
          setSeen({ label: id.label, what: hit.calls ? `${hit.calls} call${hit.calls === 1 ? '' : 's'}` : 'connected' });
        }
      } catch {}
    };
    void read();
    const i = window.setInterval(read, SEEN_FALLBACK_MS);
    return () => { alive = false; window.clearInterval(i); };
  }, [want, seen, agentId]);

  const ensureServer = async (): Promise<boolean> => {
    const p: Record<string, unknown> = {};
    if (!config?.mcpEnabled) {
      if (paperDefault && liveNow && !window.confirm(
        'Agent trading is set to LIVE and the agent server is off.\n\n'
        + 'Switching the server on lets a connected agent place REAL-money orders '
        + '(your approval and caps still apply). Switch it on?\n\n'
        + 'Cancel changes nothing. To use paper instead, switch to it on the AI Agents page.',
      )) return false;
      p.mcpEnabled = true;
    }
    if (paperDefault && !liveNow && config?.mcpTradeMode !== 'paper') p.mcpTradeMode = 'paper';
    if (Object.keys(p).length) {
      await window.krypt.config.update(p as never);
      await refresh.state();
    }
    return true;
  };

  const install = async (client: 'claude-desktop' | 'codex', name: string): Promise<void> => {
    if (!window.krypt.terminal.mcpInstallConfig) return;
    setBusy(true);
    try {
      if (!(await ensureServer())) return;
      const r = await window.krypt.terminal.mcpInstallConfig({ client, agentId: agentId ?? DEFAULT_AGENT_ID });
      if (r.ok) {
        setCopied(client);
        setCopiedAt(Date.now());
        toast.push(r.message, 'success', 12_000);
      } else {
        toast.push(r.message || `Couldn't add it to ${name}.`, 'error', 12_000);
      }
    } catch (e) {
      toast.error(userMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const openFolder = async (client: 'claude-desktop' | 'codex'): Promise<void> => {
    try {
      const r = await window.krypt.terminal.mcpOpenConfigFolder?.({ client });
      if (r && !r.ok && r.message) toast.warn(r.message);
    } catch (e) {
      toast.error(userMessage(e));
    }
  };

  const copy = async (client: McpClient, name: string): Promise<void> => {
    setBusy(true);
    try {
      if (!(await ensureServer())) return;
      await window.krypt.terminal.mcpCopyConfig({ client, agentId: agentId ?? DEFAULT_AGENT_ID });
      setCopied(client);
      setCopiedAt(Date.now());
      toast.success(`${name} config copied. It contains your agent token — treat it like a password.`);
    } catch (e) {
      toast.error(userMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const chosen = AGENT_CLIENTS.find((c) => c.id === pick);
  return (
    <div className={cls('space-y-3', className)}>
      {paperDefault && liveNow && (
        <div
          role="note"
          data-testid="connect-live-note"
          className="rounded-lg border border-krypt-loss/40 bg-krypt-loss/10 px-3 py-2 text-[11px] leading-relaxed text-krypt-loss"
        >
          <span className="font-semibold">Your agents are LIVE.</span> Copying a config won&apos;t
          change that: it does not switch them to paper. Do that on the AI Agents page if you want to.
        </div>
      )}
      {engineDown && (
        <div role="note" data-testid="connect-engine-down"
          className="rounded-lg border border-krypt-warn/40 bg-krypt-warn/10 px-3 py-2 text-[11px] leading-relaxed text-krypt-warn">
          The trading engine isn&apos;t running, so there is no agent server to connect to yet. Press
          Restart in the top bar; these buttons wake up when it&apos;s running.
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {[...(hideAutopilot ? [] : [{ id: 'autopilot' as Pick, name: 'In-app Autopilot (easiest)' }]),
          ...AGENT_CLIENTS.map((c) => ({ id: c.id as Pick, name: c.name }))].map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => setPick(c.id)}
            className={cls(
              'rounded-lg border px-2 py-2 text-xs font-medium transition',
              pick === c.id
                ? 'border-krypt-purple/70 bg-krypt-purple/15 text-white shadow-[0_0_16px_-6px_rgba(168,85,247,0.8)]'
                : 'border-krypt-border bg-krypt-surface2 text-krypt-muted hover:border-krypt-borderHi hover:text-white',
            )}
          >
            {c.name}
          </button>
        ))}
      </div>

      {chosen ? (
        <div className="rounded-lg border border-krypt-border bg-krypt-surface2 p-3">
          <div className="flex items-start gap-3">
            <div className="flex-1 text-[11px] leading-relaxed text-krypt-muted">
              {chosen.oneClick ? (
                <>
                  <span className="text-white">1.</span> {chosen.where}{' '}
                  <span className="text-white">2.</span> Ask it to use <span className="font-mono text-white">{serverName ?? 'krypt-trader'}</span>.
                </>
              ) : (
                <>
                  <span className="text-white">1.</span> Copy the config.{' '}
                  <span className="text-white">2.</span> {chosen.where}{' '}
                  <span className="text-white">3.</span> Ask it to use <span className="font-mono text-white">{serverName ?? 'krypt-trader'}</span>.
                </>
              )}
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1.5">
              {chosen.oneClick && window.krypt.terminal.mcpInstallConfig && (
                <button
                  type="button"
                  onClick={() => void install(chosen.id as 'claude-desktop' | 'codex', chosen.name)}
                  disabled={busy || engineDown}
                  className="krypt-btn-primary"
                  data-testid="connect-install"
                  title="Writes the entry into that app's own config file for you. A dated backup of the old file is kept beside it."
                >
                  <Wand2 className="h-4 w-4" /> Add to {chosen.name}
                </button>
              )}
              <button
                type="button"
                onClick={() => void copy(chosen.id, chosen.name)}
                disabled={busy || engineDown}
                className={chosen.oneClick ? 'krypt-btn-default' : 'krypt-btn-primary'}
                title="Puts the config on your clipboard. The app never shows the token on screen."
              >
                <Copy className="h-4 w-4" /> Copy config
              </button>
              {chosen.oneClick && window.krypt.terminal.mcpOpenConfigFolder && (
                <button
                  type="button"
                  onClick={() => void openFolder(chosen.id as 'claude-desktop' | 'codex')}
                  className="text-[11px] text-krypt-muted hover:text-white"
                >
                  <FolderOpen className="mr-1 inline h-3 w-3" />Open config folder
                </button>
              )}
            </div>
          </div>
          <WaitingLine
            copied={copied === chosen.id} copiedAt={copied === chosen.id ? copiedAt : null}
            seen={seen} other={other} name={chosen.name}
          />
        </div>
      ) : (
        <div className="flex items-start gap-3 rounded-lg border border-krypt-border bg-krypt-surface2 p-3">
          <Bot className="mt-0.5 h-4 w-4 shrink-0 text-krypt-purple" />
          <div className="flex-1 text-[11px] leading-relaxed text-krypt-muted">
            Nothing to install: the app runs the agent itself, on a schedule, with an AI you choose.
            A cloud key (Claude, OpenAI, OpenRouter, Gemini; billed to <span className="text-white">you</span>)
            or a free model on this computer (Ollama, LM Studio). It starts on paper, with daily run,
            token and tool-call budgets, and stays off until you switch it on.
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <button
              type="button"
              data-testid="connect-autopilot-setup"
              onClick={() => (autopilotSetup === 'callback' ? onAutopilot() : setQuick(true))}
              disabled={engineDown}
              className="krypt-btn-primary"
            >
              Set up Autopilot <ArrowRight className="h-4 w-4" />
            </button>
            {autopilotSetup === 'modal' && (
              <button type="button" onClick={onAutopilot} className="text-[11px] text-krypt-muted hover:text-white">
                AI settings
              </button>
            )}
          </div>
        </div>
      )}
      {autopilotSetup === 'modal' && (
        <Modal open={quick} onClose={() => setQuick(false)} maxWidth="max-w-2xl">
          <AutopilotQuickstart onDone={() => setQuick(false)} onSkip={() => setQuick(false)} />
        </Modal>
      )}
    </div>
  );
}

function WaitingLine({ copied, copiedAt, seen, other, name }: {
  copied: boolean; copiedAt: number | null; seen: { label: string; what: string } | null;
  other: string | null; name: string;
}) {
  const [late, setLate] = useState(false);
  useEffect(() => {
    setLate(false);
    if (!copied || !copiedAt || seen) return undefined;
    const t = window.setTimeout(() => setLate(true), Math.max(0, copiedAt + WAIT_HINT_MS - Date.now()));
    return () => window.clearTimeout(t);
  }, [copied, copiedAt, seen]);
  if (seen) {
    return (
      <div className="mt-2 flex items-center gap-2 text-xs text-krypt-win" role="status">
        <CheckCircle2 className="h-4 w-4" />
        <span><span className="font-medium">{seen.label}</span> {seen.what}. It&apos;s connected.</span>
      </div>
    );
  }
  return (
    <div className="mt-2 flex items-center gap-2 text-xs text-krypt-muted" role="status">
      {copied ? <Loader2 className="h-3.5 w-3.5 animate-spin text-krypt-purple" /> : <span className="h-2 w-2 rounded-full bg-krypt-dim" />}
      <span>
        {copied ? `Waiting for ${name}'s first call…` : `Waiting for ${name}…`}
        {other && <span className="text-krypt-dim"> (saw {other} — a different client; it works too)</span>}
        {late && (
          <span className="mt-0.5 block text-krypt-warn" data-testid="connect-wait-hint">
            Still nothing? {waitHint(name)}
          </span>
        )}
      </span>
    </div>
  );
}

export function waitHint(name: string): string {
  if (name === 'Claude Desktop') {
    return 'Restart Claude Desktop after adding — fully quit it (right-click its tray icon → Quit), open it again, then ask it to use krypt-trader.';
  }
  if (name === 'Codex') return 'Restart Codex after adding, then ask it to use krypt-trader.';
  if (name === 'Cursor') return 'Check Cursor Settings → MCP shows it switched on and green, then ask it to use krypt-trader.';
  return `Restart ${name} after adding, then ask it to use krypt-trader.`;
}
