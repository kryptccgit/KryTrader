import type { AccountMode, TraderConfig } from '@shared/types';
import { agentsOf, DEFAULT_AGENT_ID } from '@shared/agents';
import { c15RealOrderRunners } from './c15Live';


export type EngineId = 'bot' | '15m' | 'agents' | 'scripts' | 'perps';

export interface ArmedEngine {
  id: EngineId;
  short: string;
  label: string;
}

type Cfg = Partial<TraderConfig> | null | undefined;

export function armedEngines(c: Cfg, mode: AccountMode | undefined = c?.accountMode): ArmedEngine[] {
  if (!c) return [];
  const out: ArmedEngine[] = [];
  if (c.enableTrading) {
    out.push({ id: 'bot', short: 'bot', label: 'Main bot: auto-trading on' });
  }
  const c15Live = c15RealOrderRunners({ ...c, accountMode: mode });
  if (c15Live === null) {
    out.push({ id: '15m', short: '15m', label: '15-minute crypto: Real orders (LIVE)' });
  } else if (c15Live.length) {
    const live = c15Live.length;
    out.push({
      id: '15m', short: '15m',
      label: `15-minute crypto: ${live} live runner${live === 1 ? '' : 's'}`,
    });
  }
  const live = agentsOf(c).filter((a) => a.enabled && a.mode === 'live');
  const reach = c.mcpTradeMode !== 'live' ? []
    : c.mcpEnabled ? live
      : c.autopilotEnabled ? live.filter((a) => a.id === (c.autopilotAgentId || DEFAULT_AGENT_ID))
        : [];
  if (reach.length) {
    const approval = c.mcpLiveApproval === false
      ? 'approval OFF'
      : 'each order waits for your approval';
    const names = reach.map((a) => a.name);
    const who = names.length <= 3 ? names.join(', ') : `${names.slice(0, 3).join(', ')} +${names.length - 3}`;
    out.push({
      id: 'agents', short: 'agents',
      label: `AI agents LIVE: ${who} (${approval}${c.autopilotEnabled ? ', Autopilot on' : ''})`,
    });
  }
  if (c.scriptsLiveEnabled && !c.scriptsPaperMode) {
    out.push({ id: 'scripts', short: 'scripts', label: 'Scripts: live, Paper mode off' });
  }
  if (c.perpsFarmEnabled) {
    out.push({ id: 'perps', short: 'perps', label: 'Perps volume farmer' });
  }
  return out;
}

export function remoteTradingArmed(c: Cfg): boolean {
  return !!c?.remoteTradingEnabled && !!(c.remoteDiscordEnabled || c.remoteTelegramEnabled);
}

export function isRealMoney(c: Cfg): boolean {
  return c?.accountMode === 'live';
}

export function liveSwitchLines(c: Cfg): string[] {
  const lines = armedEngines(c, 'live').map((e) => e.label);
  if (remoteTradingArmed(c)) {
    lines.push('Remote trading from Discord / Telegram (each order still needs its code)');
  }
  return lines;
}

export function liveSwitchMessage(c: Cfg): string {
  const lines = liveSwitchLines(c).map((l) => `  • ${l}`);
  const head = 'Switch to LIVE (real money)?';
  if (!lines.length) {
    return `${head}\n\nNothing is armed to trade on its own. Orders you place in Live use real funds.`;
  }
  return `${head}\n\nThese are armed and will use REAL money as soon as you switch:\n`
    + `${lines.join('\n')}\n\nCancel and turn any of them off first if that is not what you want.`;
}
