import { useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Copy, KeyRound, Link2, Send, ShieldAlert,
  Smartphone, Unlink, XCircle,
} from 'lucide-react';
import type { RemoteStatus } from '@shared/market';
import { Card, ConfirmDialog, Page, Section, Switch } from '../components/common';
import { Caveat } from '../components/terminal/atoms';
import { useApp } from '../state/AppStateProvider';
import { usePoll } from '../state/TerminalProvider';
import { useToast } from '../state/ToastProvider';
import { cls } from '../utils/format';

export function RemotePage() {
  const { config, refresh } = useApp();
  const toast = useToast();
  const [discordToken, setDiscordToken] = useState('');
  const [telegramToken, setTelegramToken] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [armTrading, setArmTrading] = useState(false);

  const { data, error, reload } = usePoll<RemoteStatus>(
    () => window.krypt.terminal.remoteStatus(),
    5_000,
    [],
  );

  const patch = async (p: Record<string, unknown>): Promise<void> => {
    await window.krypt.config.update(p as never);
    await refresh.state();
    reload();
  };

  const saveToken = async (which: 'discord' | 'telegram', token: string): Promise<void> => {
    setBusy(which);
    try {
      await window.krypt.terminal.remoteSetToken({ which, token });
      toast.success(token ? `${which} token saved (encrypted).` : `${which} token cleared.`);
      if (which === 'discord') setDiscordToken(''); else setTelegramToken('');
      reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const pair = async (): Promise<void> => {
    setBusy('pair');
    try {
      const { code } = await window.krypt.terminal.remotePairCode();
      toast.push(`Send "pair ${code}" to your Telegram bot within 10 minutes.`,
        'info', 15_000);
      reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const test = async (): Promise<void> => {
    setBusy('test');
    try {
      const res = await window.krypt.terminal.remoteTest();
      if (!res.sent.length) {
        toast.warn('No bot is running — switch one on first.');
      } else {
        for (const s of res.sent) {
          toast.push(
            s.ok ? `${s.which}: message sent — check your phone.`
              : `${s.which}: ${s.error ?? 'failed'}`,
            s.ok ? 'success' : 'error', 8_000);
        }
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const d = data?.discord;
  const t = data?.telegram;

  return (
    <Page
      title="Remote"
      subtitle="Leave the terminal running here; check it — or trade — from your phone."
      actions={
        <button onClick={() => void test()} disabled={busy === 'test'} className="krypt-btn-default">
          <Send className="h-4 w-4" />
          Send test message
        </button>
      }
    >
      {error && (
        <Caveat className="mb-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">
          {error}
        </Caveat>
      )}

      <Card className="mb-4">
        <div className="flex gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-krypt-warn" />
          <div className="space-y-2 text-[11px] leading-relaxed text-krypt-muted">
            <p className="text-sm font-medium text-white">
              What a remote can and cannot do
            </p>
            <p>
              The bot answers <span className="text-white">one identity</span> —
              your Discord user id, or the Telegram chat that completed a
              pairing code. Group and server channels are ignored outright: a
              bot that answers &ldquo;what are my positions&rdquo; in a shared
              channel has already failed.
            </p>
            <p>
              <span className="text-white">Reading and trading are separate
              switches.</span> Turning the bots on so you can check positions
              does not let a chat app spend money. When trading is on, no order
              fires from a single message — the bot quotes it and waits for a
              confirmation code tied to that exact order, so a typo or a message
              sent to the wrong window cannot trade. Orders run the same caps and
              checks as the desktop ticket.
            </p>
            <p className="text-krypt-warn">
              What it cannot protect: anything you ask for — balance, positions,
              orders — travels through Discord&apos;s or Telegram&apos;s servers
              in a form they can read. That is inherent to using a chat app as a
              terminal. It is named on the Privacy page, and it is why this is
              off until you switch it on.
            </p>
          </div>
        </div>
      </Card>

      <Section
        title="Discord"
        description="Create a bot at discord.com/developers, copy its token, and enable the MESSAGE CONTENT intent. Then paste your own Discord user id — the bot will answer nobody else."
      >
        <Card>
          <StatusRow
            label="Discord bot"
            connected={!!d?.connected}
            running={!!d?.running}
            name={d?.botName ?? null}
            error={d?.lastError ?? null}
          />

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <label className="block">
              <span className="krypt-label">Bot token</span>
              <div className="flex gap-2">
                <input
                  type="password"
                  value={discordToken}
                  onChange={(e) => setDiscordToken(e.target.value)}
                  placeholder={d?.hasToken ? '•••••••• saved' : 'paste the bot token'}
                  className="krypt-input font-mono"
                />
                <button
                  onClick={() => void saveToken('discord', discordToken)}
                  disabled={busy === 'discord' || !discordToken.trim()}
                  className="krypt-btn-default shrink-0"
                >
                  <KeyRound className="h-4 w-4" />
                </button>
              </div>
              <span className="krypt-hint">
                Stored encrypted beside your API keys — never in settings.json.
              </span>
            </label>

            <label className="block">
              <span className="krypt-label">Your Discord user id</span>
              <input
                value={config?.remoteDiscordUserId ?? ''}
                onChange={(e) => void patch({
                  remoteDiscordUserId: e.target.value.replace(/[^0-9]/g, ''),
                })}
                placeholder="e.g. 123456789012345678"
                className="krypt-input font-mono"
              />
              <span className="krypt-hint">
                Discord → Settings → Advanced → Developer Mode, then right-click
                your name → Copy User ID.
              </span>
            </label>
          </div>

          {d?.running && d.sawMessageContent === false && (
            <Caveat className="mt-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">
              No message text has arrived yet. If the bot seems to ignore you,
              enable the <span className="font-mono">MESSAGE CONTENT</span>{' '}
              intent for it in the Discord developer portal — without it every
              message arrives empty.
            </Caveat>
          )}

          <div className="mt-4 flex items-center gap-3">
            <Switch
              checked={!!config?.remoteDiscordEnabled}
              onChange={(v) => void patch({ remoteDiscordEnabled: v })}
              label="Enable the Discord remote"
              disabled={!d?.hasToken || !config?.remoteDiscordUserId}
            />
            {d?.hasToken && (
              <button
                onClick={() => void saveToken('discord', '')}
                className="krypt-btn-ghost ml-auto text-xs"
              >
                <Unlink className="h-3.5 w-3.5" /> Forget token
              </button>
            )}
          </div>
        </Card>
      </Section>

      <Section
        title="Telegram"
        description="Create a bot with @BotFather and paste its token. Then pair: the app shows a one-time code, you send it to the bot, and that chat is bound."
      >
        <Card>
          <StatusRow
            label="Telegram bot"
            connected={!!t?.connected}
            running={!!t?.running}
            name={t?.botName ? `@${t.botName}` : null}
            error={t?.lastError ?? null}
          />

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <label className="block">
              <span className="krypt-label">Bot token</span>
              <div className="flex gap-2">
                <input
                  type="password"
                  value={telegramToken}
                  onChange={(e) => setTelegramToken(e.target.value)}
                  placeholder={t?.hasToken ? '•••••••• saved' : '123456:ABC-DEF…'}
                  className="krypt-input font-mono"
                />
                <button
                  onClick={() => void saveToken('telegram', telegramToken)}
                  disabled={busy === 'telegram' || !telegramToken.trim()}
                  className="krypt-btn-default shrink-0"
                >
                  <KeyRound className="h-4 w-4" />
                </button>
              </div>
            </label>

            <div>
              <span className="krypt-label">Paired chat</span>
              {t?.paired ? (
                <div className="flex items-center gap-2">
                  <span className="krypt-badge !normal-case">
                    <Link2 className="h-3 w-3" /> chat {t.chatId}
                  </span>
                  <button
                    onClick={() => void window.krypt.terminal
                      .remoteUnpair({ which: 'telegram' })
                      .then(() => { toast.success('Unpaired.'); void refresh.state(); reload(); })}
                    className="krypt-btn-ghost text-xs"
                  >
                    <Unlink className="h-3.5 w-3.5" /> Unpair
                  </button>
                </div>
              ) : t?.pairCode ? (
                <div>
                  <div className="flex items-center gap-2">
                    <code className="rounded border border-krypt-purple/40 bg-krypt-purple/10 px-3 py-1.5 font-mono text-lg tracking-widest text-white">
                      {t.pairCode}
                    </code>
                    <button
                      onClick={() => {
                        void navigator.clipboard.writeText(`pair ${t.pairCode}`);
                        toast.success('Copied "pair CODE" — send it to your bot.');
                      }}
                      className="krypt-btn-ghost"
                      title="Copy the whole command"
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <span className="krypt-hint">
                    Send <span className="font-mono text-white">pair {t.pairCode}</span>{' '}
                    to your bot. Single use, expires in 10 minutes.
                  </span>
                </div>
              ) : (
                <button
                  onClick={() => void pair()}
                  disabled={!t?.hasToken || busy === 'pair'}
                  className="krypt-btn-default"
                >
                  <Smartphone className="h-4 w-4" /> Generate pairing code
                </button>
              )}
            </div>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <Switch
              checked={!!config?.remoteTelegramEnabled}
              onChange={(v) => void patch({ remoteTelegramEnabled: v })}
              label="Enable the Telegram remote"
              disabled={!t?.hasToken}
            />
            {t?.hasToken && (
              <button
                onClick={() => void saveToken('telegram', '')}
                className="krypt-btn-ghost ml-auto text-xs"
              >
                <Unlink className="h-3.5 w-3.5" /> Forget token
              </button>
            )}
          </div>
        </Card>
      </Section>

      <Section
        title="Permissions"
        description="What a paired phone is allowed to do."
      >
        <Card>
          <Switch
            checked={!!config?.remoteAlertsEnabled}
            onChange={(v) => void patch({ remoteAlertsEnabled: v })}
            label="Push alerts to my phone"
            description="Standing instructions firing — a stop loss triggering, a price alert crossing. This is the reason to have a remote at all."
          />
          <div className="mt-4 border-t border-krypt-border pt-4">
            <Switch
              checked={!!config?.remoteTradingEnabled}
              onChange={(v) => {
                if (v) setArmTrading(true);
                else void patch({ remoteTradingEnabled: false });
              }}
              label="Allow trading from chat"
              description="Off by default. Orders still need a confirmation code and still obey every cap on the desktop ticket."
            />
          </div>
          {config?.remoteTradingEnabled && (
            <Caveat className="mt-3 border-krypt-warn/40 bg-krypt-warn/5 text-krypt-warn">
              A paired phone can now place orders. It cannot place one from a
              single message — the bot quotes first and waits for a code — but
              anyone holding your unlocked phone with that chat open can send
              both messages.
            </Caveat>
          )}
        </Card>
      </Section>

      <p className="mt-4 text-[11px] leading-relaxed text-krypt-dim">
        Commands: <span className="font-mono">status, balance, positions,
        orders, quote TICKER, rules, history</span> — and, when trading is on,{' '}
        <span className="font-mono">buy, sell, cancel, confirm</span>. Send{' '}
        <span className="font-mono">help</span> to the bot for the full list.
      </p>

      <ConfirmDialog
        open={armTrading}
        title="Allow trading from a chat app?"
        danger
        confirmLabel="Allow trading"
        onClose={() => setArmTrading(false)}
        onConfirm={() => { setArmTrading(false); void patch({ remoteTradingEnabled: true }); }}
        body={
          <div className="space-y-2">
            <p>
              A message from your paired chat will be able to place real orders
              on the <span className="font-mono text-white">
                {config?.kalshiEnv ?? 'demo'}
              </span> environment.
            </p>
            <p>
              Every order is quoted first and needs a confirmation code, and all
              the caps from the desktop ticket still apply. But the practical
              security of this becomes the security of your phone and your chat
              account — including anyone who can read that chat.
            </p>
          </div>
        }
      />
    </Page>
  );
}

function StatusRow({
  label, connected, running, name, error,
}: {
  label: string;
  connected: boolean;
  running: boolean;
  name: string | null;
  error: string | null;
}) {
  const Icon = connected ? CheckCircle2 : running ? AlertTriangle : XCircle;
  const tone = connected ? 'text-krypt-win' : running ? 'text-krypt-warn' : 'text-krypt-dim';
  return (
    <div>
      <div className="flex items-center gap-2">
        <Icon className={cls('h-4 w-4', tone)} />
        <span className="text-sm text-white">{label}</span>
        <span className={cls('text-[11px]', tone)}>
          {connected ? 'connected' : running ? 'connecting…' : 'not running'}
        </span>
        {name && <span className="font-mono text-[11px] text-krypt-dim">{name}</span>}
      </div>
      {error && (
        <div className="mt-1 flex gap-1.5 text-[11px] leading-relaxed text-krypt-warn">
          <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
