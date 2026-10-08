import type { TraderConfig } from '../../shared/types';
import { cleanAgents, DEFAULT_AGENT_ID, isValidAgentId } from '../../shared/agents';

export const REMOVED_PRESET_IDS: ReadonlySet<string> = new Set([
  'krypt-edge', 'krypt-sports-momentum', 'krypt-crypto-whale', 'krypt-secret',
]);

const REMOVED_CONFIG_KEYS = [
  'gamblingMode', 'gamblingTradeProbability',
  'kalshiEnv',
  'mcpPaperBankrollUsd',
] as const;

export function migrateAccountMode(src: Record<string, unknown>, live = false): void {
  if (src.accountMode !== 'live' && src.accountMode !== 'paper') {
    src.accountMode = !('accountMode' in src) && live && src.kalshiEnv === 'production'
      ? 'live' : 'paper';
  }
  if (typeof src.paperBankrollUsd !== 'number' || !Number.isFinite(src.paperBankrollUsd)) {
    const old = src.mcpPaperBankrollUsd;
    if (typeof old === 'number' && Number.isFinite(old) && old > 0) src.paperBankrollUsd = old;
    else delete src.paperBankrollUsd;
  }
}

const GAMBLING_OPENED_FLOORS = [
  'minConfidenceWhale', 'minConfidenceMomentum',
  'minEdgePtsWhale', 'minEdgePtsMomentum', 'minEntryPriceCents',
] as const;

export function normalizeActiveProfileId(id: unknown): string | null {
  if (typeof id !== 'string' || !id) return null;
  return REMOVED_PRESET_IDS.has(id) ? null : id;
}

export function migrateConfig(
  raw: unknown,
  defaults: TraderConfig,
  opts: { live?: boolean } = {},
): TraderConfig {
  const src: Record<string, unknown> =
    raw && typeof raw === 'object' ? { ...(raw as Record<string, unknown>) } : {};
  const gamblingWasOn = src.gamblingMode === true;
  migrateAccountMode(src, opts.live === true);
  for (const k of REMOVED_CONFIG_KEYS) delete src[k];
  if (gamblingWasOn) {
    const num = (v: unknown): number | null =>
      (typeof v === 'number' && Number.isFinite(v) ? v : null);
    for (const k of GAMBLING_OPENED_FLOORS) {
      const v = num(src[k]);
      src[k] = v === null ? defaults[k] : Math.max(v, defaults[k]);
    }
    const hi = num(src.maxEntryPriceCents);
    src.maxEntryPriceCents = hi === null
      ? defaults.maxEntryPriceCents : Math.min(hi, defaults.maxEntryPriceCents);
    src.contrarianOnly = src.contrarianOnly === true || defaults.contrarianOnly;
    if (opts.live) src.enableTrading = false;
  }
  const mode = typeof src.mcpTradeMode === 'string' ? src.mcpTradeMode : defaults.mcpTradeMode;
  src.mcpAgents = cleanAgents('mcpAgents' in src ? src.mcpAgents : undefined, mode);
  const apId = String(src.autopilotAgentId ?? '').trim().toLowerCase();
  src.autopilotAgentId = isValidAgentId(apId) ? apId : DEFAULT_AGENT_ID;
  return { ...defaults, ...src } as TraderConfig;
}
