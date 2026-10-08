import type { Crypto15mRunner, SignalRow } from '@shared/types';
import type { ActivityEvent, AgentCallActivity } from '../../state/activity';
import { shortStrategy } from '../library';
import { subject } from '../text';
import type { RoomId } from './layout';
import type { Tone } from './overlay';


export interface Beat {
  room: RoomId;
  text: string;
  log: string;
  tone: Tone;
  pass?: boolean | null;
  series?: number[];
  holo?: string;
  stamp?: string;
  board?: { text: string; color: string };
  capsule?: boolean;
  deploy?: boolean;
  alarm?: boolean;
  agentOrder?: boolean;
}

export function cents(v: number): string {
  return `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(Math.abs(v) < 1 ? 2 : 1)}¢`;
}

function px(v: number | null): string {
  return v === null ? '' : ` @${Math.round(v)}¢`;
}

const ENGINE_LABEL = { '15m': '15m', main: 'main', script: 'script' } as const;

export function backtestLine(ev: Extract<ActivityEvent, { kind: 'backtest' }>): { text: string; pass: boolean | null } {
  const parts: string[] = [ENGINE_LABEL[ev.engine], shortStrategy(ev.strategy) || ev.strategy];
  if (ev.days !== null) parts.push(`${ev.days}d`);
  if (ev.trades === null) return { text: parts.join(' · '), pass: null };
  if (ev.trades === 0) {
    parts.push('0 trades — nothing to score');
    return { text: parts.join(' · '), pass: null };
  }
  parts.push(`${ev.trades.toLocaleString('en-US')} trade${ev.trades === 1 ? '' : 's'}`);
  if (ev.netCents === null) return { text: parts.join(' · '), pass: null };
  const pass = ev.netCents > 0;
  let edge = `${cents(ev.netCents)}/ct ${pass ? '✓' : '✗'}`;
  if (ev.t !== null && pass && ev.t < 2) edge += ` (t=${ev.t.toFixed(1)}, noise)`;
  parts.push(edge);
  return { text: parts.join(' · '), pass };
}

const AI_NAMES: Record<string, string> = {
  openai: 'GPT', anthropic: 'Claude', openrouter: 'OpenRouter', gemini: 'Gemini',
  ollama: 'Ollama', lmstudio: 'LM Studio',
};

export function aiName(provider: string): string {
  return AI_NAMES[provider] ?? (provider || 'AI');
}

export function aiLine(ev: Extract<ActivityEvent, { kind: 'aiAnalysis' }>): string {
  const subj = subject(ev.ticker, ev.title ?? ev.ticker);
  const fair = ev.fairCents !== null ? `fair ${Math.round(ev.fairCents)}¢` : 'no fair value';
  return `${aiName(ev.provider)}: ${subj} · ${fair} · ${ev.verdict}`;
}

function clip(s: string, n: number): string {
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t;
}

export function beatFor(ev: ActivityEvent): Beat | null {
  switch (ev.kind) {
    case 'aiAnalysis': {
      const l = aiLine(ev);
      return { room: 'research', text: `🤖 ${l}`, log: `🤖 ${l}`, tone: 'whale' };
    }
    case 'backtest': {
      const { text, pass } = backtestLine(ev);
      const holo = `${ENGINE_LABEL[ev.engine].toUpperCase()} · ${shortStrategy(ev.strategy) || ev.strategy}`.slice(0, 20);
      const stamp = ev.netCents === null || !ev.trades ? 'NO TRADES' : `${cents(ev.netCents)}/ct ${pass ? '✓' : '✗'}`;
      return {
        room: 'backtest', text: `🧪 ${text}`, log: `🧪 backtest: ${text}`, tone: pass === false ? 'loss' : 'test',
        pass, series: ev.equity, holo, stamp,
      };
    }
    case 'optimizer': {
      const head = `${ev.coin}${ev.granularityH !== null ? ` ${ev.granularityH}h` : ''}`;
      const best = ev.winner
        ? `best ${shortStrategy(ev.winner)}${ev.winnerNetCents !== null ? ` ${cents(ev.winnerNetCents)}` : ''}`
        : 'no whole-day winner';
      const slots = ev.slots.length ? `${ev.slots.length} slot${ev.slots.length === 1 ? '' : 's'}` : 'no slots';
      const t = `⚙️ optimized ${head} · ${slots} · ${best}`;
      return { room: 'optimizer', text: t, log: t, tone: 'opt' };
    }
    case 'script': {
      const nm = ev.name ? `"${clip(ev.name, 18)}"` : 'a script';
      switch (ev.op) {
        case 'saved':
        case 'created': {
          const verb = ev.op === 'created' ? 'new script' : 'saved';
          const t = ev.ok ? `🔨 ${verb} ${nm} ✓` : `🔨 ${verb} ${nm} · ${ev.errors ?? '?'} error${ev.errors === 1 ? '' : 's'} — disabled`;
          return { room: 'forge', text: t, log: t, tone: ev.ok ? 'forge' : 'loss' };
        }
        case 'validated': {
          const t = ev.ok ? `✔ validated ${nm}` : `✗ ${nm}: ${ev.errors ?? '?'} error${ev.errors === 1 ? '' : 's'}`;
          return { room: 'forge', text: t, log: t, tone: ev.ok ? 'forge' : 'loss' };
        }
        case 'enabled': {
          const t = `▶ enabled ${nm}`;
          return { room: 'forge', text: t, log: t, tone: 'test', deploy: true };
        }
        case 'disabled': {
          const t = `⏸ disabled ${nm}`;
          return { room: 'forge', text: t, log: t, tone: 'neutral' };
        }
        case 'autoDisabled': {
          const why = ev.detail ? `: ${clip(ev.detail, 40)}` : '';
          const t = `⛔ engine disabled ${nm}${why}`;
          return { room: 'forge', text: clip(t, 60), log: t, tone: 'loss' };
        }
      }
      return null;
    }
    case 'preset': {
      if (!ev.ok) return null;
      const t = `📋 applied ${ev.what === 'profile' ? 'profile' : 'preset'} "${clip(ev.name, 20)}"`;
      return { room: 'forge', text: t, log: t, tone: 'forge', deploy: true };
    }
    case 'manualOrder': {
      const subj = ev.ticker ? subject(ev.ticker, ev.ticker) : 'order';
      if (ev.op === 'cancel') {
        const t = ev.ok ? `✋ MANUAL cancel · ${subj}` : `MANUAL cancel refused · ${subj}`;
        return { room: 'desk', text: t, log: t, tone: ev.ok ? 'neutral' : 'loss', board: { text: `MANUAL CANCEL ${subj.slice(0, 12)}`, color: '#A1A1AA' } };
      }
      const act = (ev.action ?? (ev.op === 'close' ? 'sell' : 'buy')).toUpperCase();
      const side = ev.side ? ev.side.toUpperCase() : '';
      if (!ev.ok) {
        const t = `MANUAL ${act} refused · ${clip(ev.message, 40)}`;
        return { room: 'desk', text: t, log: t, tone: 'loss' };
      }
      const what = ev.filled !== null && ev.filled > 0
        ? `filled ${ev.filled}×${px(ev.avgCents)}`
        : ev.status ? clip(ev.status, 14) : 'sent';
      const t = `🖐 MANUAL ${act} ${side} ${subj} · ${what}`.replace(/\s+/g, ' ');
      return {
        room: 'desk', text: t, log: t, tone: 'momo', capsule: true,
        board: { text: `MANUAL ${act} ${side} ${ev.filled ? `${ev.filled}×` : ''}${px(ev.avgCents).trim()} ${subj.slice(0, 10)}`.replace(/\s+/g, ' '), color: '#FDE68A' },
      };
    }
    case 'rule': {
      const k = ev.ruleKind;
      const icon = k === 'stop' ? '🛑' : k === 'take' ? '🎯' : '🔔';
      const t = `${icon} rule fired: ${clip(ev.message, 48)}`;
      return { room: 'vault', text: t, log: `${icon} ${ev.message}`, tone: k === 'take' ? 'win' : k === 'stop' ? 'loss' : 'neutral', alarm: k === 'stop' };
    }
    case 'halt': {
      const t = ev.scope === 'daily' ? `🛑 daily stop: ${clip(ev.reason, 40)}` : `🎯 ${ev.reason}`;
      return { room: 'vault', text: t, log: t, tone: ev.scope === 'daily' ? 'loss' : 'win', alarm: ev.scope === 'daily' };
    }
    case 'agent':
      return agentBeat(ev);
  }
  return null;
}

function agentBeat(ev: Extract<ActivityEvent, { kind: 'agent' }>): Beat | null {
  const msg = clip(ev.message, 64);
  if (ev.approvalId !== null && ev.decision) {
    const t = `🛂 approval #${ev.approvalId} ${ev.decision}`;
    return { room: 'bridge', text: t, log: `${t} · ${msg}`, tone: ev.decision === 'approved' ? 'win' : 'neutral' };
  }
  if (ev.approvalId !== null) {
    const t = `🛂 agent asks approval #${ev.approvalId}`;
    return { room: 'bridge', text: t, log: `🛂 AGENT ${msg}`, tone: 'gold' };
  }
  if (ev.mode === 'paper' || ev.mode === 'live') {
    const live = ev.mode === 'live';
    const t = `🤖 AGENT ${msg}`;
    return {
      room: 'desk', text: clip(t, 52), log: t, tone: live ? 'momo' : 'neutral',
      capsule: live, agentOrder: true,
      board: { text: `AGENT ${clip(ev.message, 30)}`, color: live ? '#C4B5FD' : '#94A3B8' },
    };
  }
  if (/^Autopilot run/i.test(ev.message)) {
    const ok = !/failed/i.test(ev.message);
    return { room: 'bridge', text: `🤖 ${clip(ev.message, 48)}`, log: `🤖 ${ev.message}`, tone: ok ? 'win' : 'loss' };
  }
  if (/script|settings changed/i.test(ev.message)) {
    const t = `🤖 agent ${msg}`;
    return { room: 'forge', text: clip(t, 52), log: t, tone: /LIVE|ENABLED/.test(ev.message) ? 'gold' : 'forge' };
  }
  return { room: 'bridge', text: clip(`🤖 agent: ${msg}`, 52), log: `🤖 agent: ${msg}`, tone: 'neutral' };
}


export type AgentAnim = 'type' | 'look' | 'hammer' | 'grab' | 'cheer' | 'panic';

export interface AgentBeat {
  room: RoomId;
  anim: AgentAnim;
  text: string;
  log: string;
  tone: Tone;
  run: boolean;
  connect?: boolean;
}

const AGENT_TOOLS: Record<Exclude<RoomId, 'optimizer' | 'vault'>, readonly string[]> = {
  research: ['discover_markets', 'search_markets', 'get_market', 'get_orderbook'],
  bridge: ['record_forecast', 'get_status', 'get_scoreboard'],
  backtest: [
    'get_data_inventory', 'sample_research_rows', 'summarize_research', 'backtest_crypto15m',
    'backtest_signal_following', 'backtest_script', 'get_trade_history',
  ],
  forge: [
    'get_script_guide', 'list_scripts', 'get_script', 'validate_script', 'save_script',
    'set_script_enabled', 'get_engine_config', 'get_engine_status', 'update_engine_config',
  ],
  desk: ['place_order', 'preview_order', 'get_portfolio', 'get_order_status', 'list_orders', 'cancel_order', 'move_funds'],
};

const TOOL_ROOM = new Map<string, RoomId>(
  Object.entries(AGENT_TOOLS).flatMap(([room, tools]) => tools.map((t) => [t, room as RoomId] as const)),
);

export function agentRoom(tool: string | null, outcome: 'ok' | 'refused' | 'error'): RoomId {
  if (outcome === 'refused') return 'vault';
  if (!tool) return 'bridge';
  return TOOL_ROOM.get(tool) ?? (tool.startsWith('backtest_') ? 'backtest' : 'bridge');
}

export function shortReason(reason: string | null): string {
  const r = reason ?? '';
  if (/forecast_id|commit to a fair value|older than \d+ minutes|record a new one/i.test(r)) return 'no recent forecast';
  if (/after fees; the minimum is/i.test(r)) return 'edge below the minimum';
  if (/per-order cap/i.test(r)) return 'over the per-order cap';
  if (/daily cap|agent spend/i.test(r)) return 'over the daily spend cap';
  if (/daily loss stop/i.test(r)) return 'daily loss stop';
  if (/already holds \d+ positions/i.test(r)) return 'position cap reached';
  if (/trading is off/i.test(r)) return 'agent trading is off';
  if (/paper cash/i.test(r)) return 'not enough paper cash';
  if (/unknown or disabled tool/i.test(r)) return 'tool not enabled';
  if (/rate limit/i.test(r)) return 'rate limit';
  if (/the user's|only sell what it opened|not placed by an agent/i.test(r)) return "not the agent's to touch";
  if (/approval/i.test(r)) return 'needs your approval';
  return r ? clip(r, 44) : 'no reason given';
}

const ROOM_ICON: Partial<Record<RoomId, string>> = {
  research: '🔎', bridge: '🎯', backtest: '🧪', forge: '🔨', desk: '📡',
};
const ROOM_TONE: Partial<Record<RoomId, Tone>> = {
  research: 'whale', bridge: 'gold', backtest: 'test', forge: 'forge', desk: 'momo',
};
const ROOM_ANIM: Partial<Record<RoomId, AgentAnim>> = {
  research: 'type', bridge: 'look', backtest: 'type', forge: 'hammer', desk: 'type',
};

export function forecastLine(ev: AgentCallActivity): string {
  const fair = ev.fairCents !== null ? `${Math.round(ev.fairCents)}¢` : 'no number';
  const edge = ev.edgeCents === null
    ? 'no side offered'
    : `edge ${ev.edgeCents >= 0 ? '+' : '−'}${Math.abs(ev.edgeCents) >= 1 ? Math.round(Math.abs(ev.edgeCents)) : Math.abs(ev.edgeCents).toFixed(1)}¢${ev.side ? ` ${ev.side.toUpperCase()}` : ''}`;
  return `forecast ${fair} · ${edge}`;
}

export function agentCallBeat(ev: AgentCallActivity, label: string): AgentBeat | null {
  if (ev.call === 'connect') {
    const t = '👋 connected';
    return { room: 'bridge', anim: 'cheer', text: t, log: `👋 ${label} connected`, tone: 'gold', run: false, connect: true };
  }
  const room = agentRoom(ev.tool, ev.outcome);
  const tool = ev.tool ?? 'a tool';
  if (ev.outcome === 'refused') {
    const why = shortReason(ev.reason);
    return {
      room, anim: 'type', text: `⛔ refused: ${why}`, run: true, tone: 'loss',
      log: `⛔ ${label} · ${clip(ev.summary, 40)} refused: ${ev.reason ? clip(ev.reason, 90) : why}`,
    };
  }
  if (ev.outcome === 'error') {
    const t = `⚠ ${tool} failed`;
    return { room, anim: 'look', text: t, log: `⚠ ${label} · ${ev.reason ?? t}`, tone: 'loss', run: false };
  }
  const icon = ROOM_ICON[room] ?? '🤖';
  let text: string;
  if (ev.tool === 'record_forecast') {
    text = `${icon} ${forecastLine(ev)}`;
  } else if (room === 'desk' && ev.mode) {
    text = `${icon} ${ev.mode.toUpperCase()} ${clip(ev.summary, 44)}`;
  } else {
    text = `${icon} ${clip(ev.summary, 46)}`;
  }
  const what = ev.tool === 'record_forecast'
    ? `${ev.ticker ? `${ev.ticker} · ` : ''}${forecastLine(ev)}`
    : `${room === 'desk' && ev.mode ? `${ev.mode.toUpperCase()} ` : ''}${ev.summary}`;
  const extra = ev.suppressed > 0 ? ` (+${ev.suppressed} more calls)` : '';
  return {
    room, anim: ROOM_ANIM[room] ?? 'look', text: clip(text, 56), run: false,
    tone: ROOM_TONE[room] ?? 'neutral', log: `🤖 ${label} · ${what}${extra}`,
  };
}


export function signalHandoff(sg: Pick<SignalRow, 'source' | 'traded'>): { traded: boolean; text: string } {
  const src = sg.source === 'whale' ? 'WHALE' : sg.source === 'momentum' ? 'MOMENTUM' : sg.source.toUpperCase();
  return sg.traded ? { traded: true, text: `${src} → desk` } : { traded: false, text: 'skipped' };
}

export function positionSource(signalSource: string): 'SCRIPT' | 'BOT' {
  return signalSource.startsWith('script:') ? 'SCRIPT' : 'BOT';
}


export interface SlotNow { runner: string; name: string | null }

export function activeSlots(runners: Crypto15mRunner[] | null | undefined, utcHour: number): Map<string, SlotNow> {
  const out = new Map<string, SlotNow>();
  for (const r of runners ?? []) {
    if (!r.enabled || !r.schedule?.length) continue;
    const s = r.schedule.find((x) => x.startHour <= utcHour && utcHour < x.endHour);
    out.set(r.id || r.name, {
      runner: r.coins?.length ? r.coins.join('/') : (r.name || 'runner'),
      name: s ? shortStrategy(s.name ?? 'unnamed slot') : null,
    });
  }
  return out;
}

export function scheduleFlips(prev: Map<string, SlotNow>, next: Map<string, SlotNow>): SlotNow[] {
  const out: SlotNow[] = [];
  for (const [id, n] of next) {
    const p = prev.get(id);
    if (p && p.name !== n.name) out.push(n);
  }
  return out;
}

export function flipLine(f: SlotNow, utcHour: number): string {
  const hh = `${String(utcHour).padStart(2, '0')}:00 UTC`;
  return f.name ? `⏰ ${hh} ${f.runner} → ${f.name}` : `⏰ ${hh} ${f.runner} → idle (no slot)`;
}
