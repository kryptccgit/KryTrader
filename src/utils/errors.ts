import { parseErrorText } from '@shared/errors';


const CODE_WORDS: Record<string, string | ((msg: string) => string)> = {
  backend_down: (m) => m || "The trading engine isn't running. Press Restart in the top bar.",
  mode_mismatch: (m) => m || 'The app switched between Paper and Live while this was open. Check it again.',
  account_mode_mismatch: (m) => m || 'The app switched between Paper and Live while this was open. Check it again.',
  no_credentials: 'No Kalshi key is saved. Add one on the API Keys page — Paper mode needs none.',
  auth_failed: 'Kalshi did not accept your saved key. Re-test it on the API Keys page.',
  unauthorized: 'Kalshi did not accept your saved key. Re-test it on the API Keys page.',
  rate_limited: 'Kalshi is rate-limiting requests right now. Wait a few seconds and try again.',
  timeout: 'That took too long to answer. The engine may still be busy — try again in a moment.',
  market_closed: 'That market is closed for trading.',
  insufficient_funds: 'Not enough cash in the account for that order.',
  cap_exceeded: (m) => m || 'That is over one of your caps (Settings → Manual trading, or the agent caps).',
  not_found: (m) => m || "That isn't there any more. Refresh and try again.",
  unsupported: (m) => m || "This version of the trading engine can't do that yet.",
};

export function errorCode(e: unknown): string | null {
  return parseErrorText(rawText(e)).code;
}

function rawText(e: unknown): string {
  if (e instanceof Error) return e.message;
  if (typeof e === 'string') return e;
  if (e && typeof e === 'object') {
    const o = e as { message?: unknown; error?: unknown };
    if (typeof o.message === 'string') return o.message;
    if (typeof o.error === 'string') return o.error;
  }
  return e === undefined || e === null ? '' : String(e);
}

export function userMessage(e: unknown, fallback = 'Something went wrong. Try again.'): string {
  const { code, message } = parseErrorText(rawText(e));
  if (code && code in CODE_WORDS) {
    const w = CODE_WORDS[code];
    return typeof w === 'function' ? w(message) : w;
  }
  if (/^RPC \w+ timed out after \d+ms$/i.test(message)) {
    return 'That took too long to answer. The engine may still be busy — try again in a moment.';
  }
  if (/^backend exited$/i.test(message) || /^Backend not running$/i.test(message)) {
    return "The trading engine stopped while doing that. Press Restart in the top bar, then try again.";
  }
  if (/^unknown method:/i.test(message)) {
    return "This version of the trading engine can't do that yet.";
  }
  return message || fallback;
}

export function isModeMismatch(e: unknown): boolean {
  if (e && typeof e === 'object' && !(e instanceof Error)) {
    const c = (e as { code?: unknown }).code;
    if (c === 'mode_mismatch' || c === 'account_mode_mismatch') return true;
  }
  const code = errorCode(e);
  if (code === 'mode_mismatch' || code === 'account_mode_mismatch') return true;
  return MODE_MISMATCH_RE.test(parseErrorText(rawText(e)).message);
}

export const MODE_MISMATCH_RE = /filled in on (PAPER|LIVE), but the app is now on (PAPER|LIVE)/i;
