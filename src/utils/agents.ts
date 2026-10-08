
import {
  AGENT_COLORS, DEFAULT_AGENT_COLOR, DEFAULT_AGENT_ID, agentsOf, cleanAgentName, isValidAgentId,
  type McpAgent,
} from '@shared/agents';

export type AgentKind =
  | 'claude-code' | 'cursor' | 'claude-desktop' | 'codex' | 'autopilot' | 'http' | 'analyse' | 'other';

export interface AgentIdentity {
  id: string;
  seatId: string;
  kind: AgentKind;
  name: string;
  model: string | null;
  label: string;
  color: string;
  emoji?: string;
  motto?: string | null;
}

const NAME: Record<AgentKind, string> = {
  'claude-code': 'Claude Code', cursor: 'Cursor', 'claude-desktop': 'Claude Desktop', codex: 'Codex',
  autopilot: 'Autopilot', http: 'HTTP agent', analyse: 'Analyse', other: 'Agent',
};

export const AGENT_COLOR: Record<AgentKind, string> = {
  'claude-code': '#E07A50',
  cursor: '#E2E8F0',
  'claude-desktop': '#F2C46D',
  codex: '#34D399',
  autopilot: '#C084FC',
  http: '#38BDF8',
  analyse: '#FDE047',
  other: '#94A3B8',
};

const OTHER_PALETTE = ['#94A3B8', '#F472B6', '#A3E635', '#FB923C', '#67E8F9', '#FCA5A5'];

export function kindOf(client: string | null | undefined, transport?: string | null): AgentKind {
  const c = (client ?? '').toLowerCase();
  if (c.startsWith('autopilot')) return 'autopilot';
  if (c.includes('claude-code') || c.includes('claude code')) return 'claude-code';
  if (c.includes('cursor')) return 'cursor';
  if (c.includes('claude-ai') || c.includes('claude desktop') || c.includes('claude-desktop')) return 'claude-desktop';
  if (c.includes('codex')) return 'codex';
  if (transport && transport !== 'mcp') return 'http';
  return 'other';
}

export function shortModel(m: string | null | undefined): string | null {
  const raw = (m ?? '').trim();
  if (!raw) return null;
  const s = raw.toLowerCase().split('/').pop() ?? raw.toLowerCase();
  for (const fam of ['opus', 'sonnet', 'haiku']) if (s.includes(fam)) return fam;
  return s.length > 16 ? `${s.slice(0, 15)}…` : s;
}

export function modelFamily(m: string | null | undefined): string | null {
  const s = (m ?? '').toLowerCase();
  if (!s) return null;
  if (s.includes('claude') || /opus|sonnet|haiku/.test(s)) return 'Claude';
  if (s.includes('gpt') || /(^|\/)o\d/.test(s)) return 'GPT';
  if (s.includes('gemini')) return 'Gemini';
  return shortModel(m);
}

function hashIdx(s: string, n: number): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h) % n;
}

function bareName(client: string): string {
  const first = client.trim().split(/\s+/)[0] ?? '';
  if (!first || first === 'unknown') return 'Agent';
  return first.length > 18 ? `${first.slice(0, 17)}…` : first;
}

export function agentIdentity(src: {
  client?: string | null; model?: string | null; source?: 'panel' | 'mcp' | null; transport?: string | null;
}): AgentIdentity {
  if (src.source === 'panel') {
    const fam = modelFamily(src.model);
    const label = `Analyse · ${fam ?? 'AI'}`;
    return {
      id: 'analyse', seatId: `analyse|${fam ?? ''}`, kind: 'analyse', name: 'Analyse',
      model: fam, label, color: AGENT_COLOR.analyse,
    };
  }
  let client = (src.client ?? '').trim();
  let model = src.model ?? null;
  if (!client && model && kindOf(model) !== 'other') {
    client = model;
    model = null;
  }
  const kind = kindOf(client, src.transport);
  if (kind === 'autopilot' && !model) {
    const m = /\(([^)]+)\)/.exec(client);
    model = m ? m[1] : null;
  }
  const short = shortModel(model);
  const name = kind === 'other' || kind === 'http' ? bareName(client) : NAME[kind];
  const id = `${kind}|${kind === 'other' || kind === 'http' ? name : ''}`;
  const color = kind === 'other' ? OTHER_PALETTE[hashIdx(name, OTHER_PALETTE.length)] : AGENT_COLOR[kind];
  return {
    id, seatId: `${id}|${short ?? ''}`, kind, name, model: short,
    label: short ? `${name} · ${short}` : name, color,
  };
}


export const HUB_NAME_MAX = 20;
export const MOTTO_MAX = 32;
const COLOR_RE = /^#[0-9A-Fa-f]{6}$/;
const CTRL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029\u200e\u200f\u202a-\u202e\u2066-\u2069]/g;

export function hubName(raw: unknown, fallback = 'Agent'): string {
  const s = cleanAgentName(raw, fallback);
  const cps = Array.from(s);
  return cps.length > HUB_NAME_MAX ? `${cps.slice(0, HUB_NAME_MAX - 1).join('').trimEnd()}…` : s;
}

function hubEmoji(raw: unknown): string | undefined {
  const s = Array.from(String(raw ?? '').replace(CTRL, '').trim()).slice(0, 8).join('');
  return s || undefined;
}

export function guideMotto(guide: unknown): string | null {
  const text = String(guide ?? '').replace(CTRL, '\n');
  for (const part of text.split(/[\n.!?;:]+/).slice(0, 4)) {
    let p = part.replace(/^[\s\-*•>#]+/, '').replace(/["“”‘’`*_]/g, '').replace(/\s+/g, ' ').trim();
    if (Array.from(p).length < 4 || /\d/.test(p)) continue;
    p = p.replace(/^you are\b/i, "I'm").replace(/^you're\b/i, "I'm").replace(/^you\b/i, 'I');
    let out = '';
    for (const w of p.split(' ')) {
      const next = out ? `${out} ${w}` : w;
      if (Array.from(next).length > MOTTO_MAX) break;
      out = next;
    }
    if (!out) continue;
    return out.length < p.length ? `${out.replace(/[,\s]+$/, '')}…` : out;
  }
  return null;
}

export function namedAgentIdentity(
  agent: { id: string; name: string; color: string; emoji?: string; guide?: string },
  model?: string | null,
): AgentIdentity {
  const short = shortModel(model);
  const name = hubName(agent.name);
  return {
    id: `agent|${agent.id}`,
    seatId: `agent|${agent.id}|${short ?? ''}`,
    kind: 'other',
    name,
    model: short,
    label: short ? `${name} · ${short}` : name,
    color: COLOR_RE.test(agent.color) ? agent.color : AGENT_COLORS[hashIdx(agent.id, AGENT_COLORS.length)],
    emoji: hubEmoji(agent.emoji),
    motto: guideMotto(agent.guide),
  };
}

const DELETED_AGENT = { name: 'Deleted agent', color: '#64748B' };

export function configuredAgents(config: Parameters<typeof agentsOf>[0]): McpAgent[] | null {
  return config ? agentsOf(config) : null;
}

export function hubAgentIdentity(
  src: {
    agentId?: string | null; agentName?: string | null;
    client?: string | null; model?: string | null; source?: 'panel' | 'mcp' | null; transport?: string | null;
  },
  agents: readonly McpAgent[] | null | undefined,
): AgentIdentity {
  const aid = src.source !== 'panel' && isValidAgentId(src.agentId) ? src.agentId : null;
  if (!aid) return agentIdentity(src);
  const a = agents?.find((x) => x.id === aid) ?? null;
  if (aid === DEFAULT_AGENT_ID) {
    const name = a ? a.name : (src.agentName ?? null);
    if (!name || name === 'Default') return agentIdentity(src);
    return namedAgentIdentity({
      id: aid, name, color: a?.color ?? DEFAULT_AGENT_COLOR, emoji: a?.emoji, guide: a?.guide,
    }, src.model);
  }
  if (a) return namedAgentIdentity(a, src.model);
  if (src.agentName) return namedAgentIdentity({ id: aid, name: src.agentName, color: '' }, src.model);
  if (agents) return namedAgentIdentity({ id: aid, ...DELETED_AGENT }, src.model);
  return agentIdentity(src);
}

export function tagLabel(who: AgentIdentity): string {
  return who.emoji ? `${who.emoji} ${who.label}` : who.label;
}

export const PICKER_KIND = {
  'claude-code': 'claude-code', cursor: 'cursor', 'claude-desktop': 'claude-desktop', codex: 'codex',
} as const satisfies Record<string, AgentKind>;
