
export type KeyField = 'keyId' | 'privateKey';

export type KeyIssueCode =
  | 'keyid_empty'
  | 'keyid_not_uuid'
  | 'keyid_is_private_key'
  | 'keyid_is_ai_key'
  | 'swapped'
  | 'pem_empty'
  | 'pem_is_keyid'
  | 'pem_public'
  | 'pem_encrypted'
  | 'pem_no_begin'
  | 'pem_no_end'
  | 'pem_bad_chars'
  | 'pem_truncated'
  | 'pem_wrong_type'
  | 'pem_multiple'
  | 'pem_too_big';

export interface KeyIssue {
  code: KeyIssueCode;
  field: KeyField;
  message: string;
}

export type PrivateKeyKind = 'rsa-pkcs1' | 'rsa-pkcs8' | 'ed25519';

export interface KeyIdCheck {
  value: string;
  fixes: string[];
  issue: KeyIssue | null;
}

export interface PemCheck {
  pem: string;
  kind: PrivateKeyKind | null;
  fixes: string[];
  issue: KeyIssue | null;
}

export interface KalshiKeysCheck {
  ok: boolean;
  keyId: string;
  pem: string;
  kind: PrivateKeyKind | null;
  fixes: string[];
  issues: KeyIssue[];
}

export const MAX_PEM_CHARS = 16_384;

const DASHES = '-'.repeat(5);
const PRIVATE_KEY = ['PRIVATE', 'KEY'].join(' ');
const pemLine = (edge: 'BEGIN' | 'END', label: string): string =>
  `${DASHES}${edge} ${label}${DASHES}`;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UUID_ANY = /(?<![0-9a-z])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-z])/gi;
const BEGIN_RE = /-{2,}\s*BEGIN\s+([A-Z0-9][A-Z0-9 ]*?)\s*-{2,}/gi;
const END_RE = /-{2,}\s*END\s+([A-Z0-9][A-Z0-9 ]*?)\s*-{2,}/gi;

const KEY_ID_EXAMPLE = '1a2b3c4d-1a2b-1a2b-1a2b-1a2b3c4d5e6f';

function stripWrapping(raw: string): { text: string; changed: boolean } {
  let s = raw.replace(/[​-‍﻿]/g, '').trim();
  if (/^["'`][\s\S]*["'`],$/.test(s)) s = s.slice(0, -1);
  for (;;) {
    const m = /^["'`“”‘’]([\s\S]*)["'`“”‘’]$/.exec(s);
    if (!m) break;
    s = m[1].trim();
  }
  return { text: s, changed: s !== raw.trim() };
}

function looksLikePrivateKey(s: string): boolean {
  return /BEGIN[\s\S]*KEY/i.test(s) || /PRIVATE\s+KEY/i.test(s)
    || (/^[A-Za-z0-9+/=\s]{200,}$/.test(s) && !UUID_RE.test(s.trim()));
}

export function checkKeyId(raw: unknown): KeyIdCheck {
  const fixes: string[] = [];
  const { text, changed } = stripWrapping(String(raw ?? ''));
  const issue = (code: KeyIssueCode, message: string): KeyIdCheck =>
    ({ value: text, fixes, issue: { code, field: 'keyId', message } });

  if (!text) return issue('keyid_empty', 'Paste the Key ID from Kalshi.');
  if (looksLikePrivateKey(text)) {
    return issue('keyid_is_private_key',
      'That is the private key. It goes in the private key box. The Key ID is the '
      + `short code that looks like ${KEY_ID_EXAMPLE}.`);
  }
  if (/^(sk-|AIza)/.test(text)) {
    return issue('keyid_is_ai_key',
      'That looks like an AI provider key, not a Kalshi Key ID. Kalshi Key IDs look '
      + `like ${KEY_ID_EXAMPLE}.`);
  }
  if (changed) fixes.push('Removed extra quotes or spaces around the Key ID.');
  if (UUID_RE.test(text)) return { value: text, fixes, issue: null };

  const squashed = text.replace(/\s+/g, '');
  if (UUID_RE.test(squashed)) {
    fixes.push('Removed spaces inside the Key ID.');
    return { value: squashed, fixes, issue: null };
  }
  const found: string[] = text.match(UUID_ANY) ?? [];
  if (new Set(found.map((f) => f.toLowerCase())).size === 1 && text.length <= 200) {
    fixes.push('Kept just the Key ID from what you pasted.');
    return { value: found[0] as string, fixes, issue: null };
  }
  if (/^[0-9a-f]{32}$/i.test(squashed)) {
    const v = [squashed.slice(0, 8), squashed.slice(8, 12), squashed.slice(12, 16),
      squashed.slice(16, 20), squashed.slice(20)].join('-');
    fixes.push('Put back the dashes the Key ID was missing.');
    return { value: v, fixes, issue: null };
  }
  return issue('keyid_not_uuid',
    found.length > 1
      ? 'That has more than one Key ID in it. Paste just the one you created.'
      : `That doesn't look like a Kalshi Key ID. It should be 36 characters like ${KEY_ID_EXAMPLE}. `
        + 'Copy it again from Kalshi\'s API keys page.');
}


const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function decodeBase64(b64: string): Uint8Array | null {
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(b64) || b64.length % 4 !== 0) return null;
  const clean = b64.replace(/=+$/, '');
  const out = new Uint8Array(Math.floor((clean.length * 3) / 4));
  let bits = 0;
  let acc = 0;
  let o = 0;
  for (const ch of clean) {
    acc = (acc << 6) | B64.indexOf(ch);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[o++] = (acc >> bits) & 0xff;
    }
  }
  return out.subarray(0, o);
}

function derTotalLength(b: Uint8Array): number | null {
  if (b.length < 2 || b[0] !== 0x30) return null;
  const l0 = b[1];
  if (l0 < 0x80) return 2 + l0;
  const n = l0 & 0x7f;
  if (n < 1 || n > 4 || b.length < 2 + n) return null;
  let len = 0;
  for (let i = 0; i < n; i++) len = len * 256 + b[2 + i];
  return 2 + n + len;
}

function indexOfBytes(hay: Uint8Array, needle: number[], limit: number): number {
  const end = Math.min(hay.length - needle.length, limit);
  outer: for (let i = 0; i <= end; i++) {
    for (let j = 0; j < needle.length; j++) if (hay[i + j] !== needle[j]) continue outer;
    return i;
  }
  return -1;
}

const OID_RSA = [0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01];
const OID_ED25519 = [0x06, 0x03, 0x2b, 0x65, 0x70];
const OID_EC = [0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01];

type Sniff = PrivateKeyKind | 'ec' | 'other' | 'truncated' | null;

export function sniffDer(b: Uint8Array): Sniff {
  const total = derTotalLength(b);
  if (total === null) return null;
  if (total > b.length) return 'truncated';
  const hdr = b[1] < 0x80 ? 2 : 2 + (b[1] & 0x7f);
  if (b[hdr] !== 0x02 || b[hdr + 1] !== 0x01) return 'other';
  const next = b[hdr + 3];
  if (next === 0x02) return 'rsa-pkcs1';
  if (next === 0x30) {
    if (indexOfBytes(b, OID_RSA, 40) >= 0) return 'rsa-pkcs8';
    if (indexOfBytes(b, OID_ED25519, 40) >= 0) return 'ed25519';
    if (indexOfBytes(b, OID_EC, 40) >= 0) return 'ec';
    return 'other';
  }
  if (next === 0x04) return 'ec';
  return 'other';
}

function wrap64(body: string): string {
  return (body.match(/.{1,64}/g) ?? []).join('\n');
}

function canonical(label: string, body: string): string {
  return `${pemLine('BEGIN', label)}\n${wrap64(body)}\n${pemLine('END', label)}\n`;
}

const PUBLIC_HINT =
  'That is a PUBLIC key. Kalshi needs the PRIVATE key: the file Kalshi gave you when you '
  + 'created the key (it says "PRIVATE KEY" on its first line). If you no longer have it, '
  + 'create a new API key; Kalshi only shows the private key once.';

const ENCRYPTED_HINT =
  'This private key is password-protected, and the app needs one without a password. '
  + 'Use the key file exactly as Kalshi gave it to you. If you encrypted it yourself, '
  + 'decrypt it first (openssl pkey -in key.pem -out key-plain.pem).';

const WRONG_TYPE_HINT =
  'That is a private key, but not a kind Kalshi uses. Kalshi API keys are Ed25519 or RSA. '
  + 'Use the file Kalshi gave you when you created the API key.';

export function checkPrivateKey(raw: unknown): PemCheck {
  const fixes: string[] = [];
  const src = String(raw ?? '');
  const fail = (code: KeyIssueCode, message: string): PemCheck =>
    ({ pem: '', kind: null, fixes, issue: { code, field: 'privateKey', message } });

  if (src.length > MAX_PEM_CHARS * 4) {
    return fail('pem_too_big', 'That is far too big to be a key file. Pick the key file Kalshi gave you.');
  }
  const { text, changed } = stripWrapping(src);
  if (!text) return fail('pem_empty', 'Add the private key: drop the key file here, or paste its contents.');
  if (text.length > MAX_PEM_CHARS) {
    return fail('pem_too_big', 'That is too big to be a key file. Pick the key file Kalshi gave you.');
  }
  if (changed) fixes.push('Removed extra quotes or spaces around the key.');

  if (UUID_RE.test(text) || (text.length < 80 && (text.match(UUID_ANY) ?? []).length === 1)) {
    return fail('pem_is_keyid',
      'That is the Key ID. It goes in the Key ID box above. This box needs the private key: '
      + 'the long block in the file Kalshi gave you.');
  }
  if (/^(ssh-(rsa|ed25519|dss)|ecdsa-sha2-)\s/.test(text)) return fail('pem_public', PUBLIC_HINT);

  let t = text;
  if (/\r/.test(t)) t = t.replace(/\r\n?/g, '\n');
  if (!/\n/.test(t) && /\\n/.test(t)) {
    t = t.replace(/(?:\\r)?\\n/g, '\n');
    fixes.push('Turned "\\n" escapes back into line breaks.');
  }

  const begins = [...t.matchAll(BEGIN_RE)];
  const ends = [...t.matchAll(END_RE)];
  const norm = (l: string): string => l.toUpperCase().replace(/\s+/g, ' ').trim();

  if (begins.length === 0) {
    if (ends.length > 0) {
      return fail('pem_no_begin',
        'The first line of the key is missing (the one that says BEGIN). Copy the whole '
        + 'file, or drop the key file here instead.');
    }
    if (/Proc-Type:\s*4,ENCRYPTED/i.test(t)) return fail('pem_encrypted', ENCRYPTED_HINT);
    const body = t.replace(/\s+/g, '');
    const der = decodeBase64(body);
    const kind = der ? sniffDer(der) : null;
    if (der && (kind === 'rsa-pkcs1' || kind === 'rsa-pkcs8' || kind === 'ed25519')) {
      fixes.push('Added the missing BEGIN and END lines.');
      const label = kind === 'rsa-pkcs1' ? `RSA ${PRIVATE_KEY}` : PRIVATE_KEY;
      return { pem: canonical(label, body), kind, fixes, issue: null };
    }
    if (kind === 'truncated') {
      return fail('pem_truncated', 'The key looks cut off. Copy the whole file, or drop the key file here instead.');
    }
    return fail('pem_no_begin',
      "That doesn't look like a private key. It should start with a line like "
      + `"${pemLine('BEGIN', PRIVATE_KEY)}". Drop the key file Kalshi gave you here instead.`);
  }

  const privIdx = begins.filter((m) => /PRIVATE KEY/.test(norm(m[1])));
  if (privIdx.length > 1) {
    return fail('pem_multiple', 'That has more than one private key in it. Paste just one.');
  }
  const chosen = privIdx[0] ?? begins[0];
  const label = norm(chosen[1]);

  if (/PUBLIC KEY|CERTIFICATE/.test(label)) return fail('pem_public', PUBLIC_HINT);
  if (label === `ENCRYPTED ${PRIVATE_KEY}`) return fail('pem_encrypted', ENCRYPTED_HINT);
  if (label !== PRIVATE_KEY && label !== `RSA ${PRIVATE_KEY}`) {
    return fail('pem_wrong_type', WRONG_TYPE_HINT);
  }

  const start = (chosen.index ?? 0) + chosen[0].length;
  const endMatch = ends.find((m) => (m.index ?? 0) >= start && norm(m[1]) === label);
  if (!endMatch) {
    return fail('pem_no_end',
      'The key looks cut off: its last line (the one that says END) is missing. Copy the '
      + 'whole file, or drop the key file here instead.');
  }
  const inner = t.slice(start, endMatch.index);
  if (/Proc-Type:\s*4,ENCRYPTED|DEK-Info:/i.test(inner)) return fail('pem_encrypted', ENCRYPTED_HINT);

  const body = inner.replace(/\s+/g, '');
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(body)) {
    return fail('pem_bad_chars',
      'The key has characters in it that a key never has, so the copy was changed '
      + 'somewhere along the way. Drop the original key file here instead.');
  }
  const der = decodeBase64(body);
  const kind = der ? sniffDer(der) : null;
  if (!der || kind === 'truncated' || kind === null) {
    return fail('pem_truncated',
      'The key looks cut off or damaged. Copy the whole file, or drop the key file here instead.');
  }
  if (derTotalLength(der) !== der.length) {
    return fail('pem_truncated',
      'The key has extra characters at the end. Copy the file again, or drop it here instead.');
  }
  if (kind === 'ec' || kind === 'other') return fail('pem_wrong_type', WRONG_TYPE_HINT);
  if (label === `RSA ${PRIVATE_KEY}` && kind !== 'rsa-pkcs1') return fail('pem_wrong_type', WRONG_TYPE_HINT);
  if (label === PRIVATE_KEY && kind === 'rsa-pkcs1') return fail('pem_wrong_type', WRONG_TYPE_HINT);

  const pem = canonical(label, body);
  const original = text.replace(/\r\n?/g, '\n').trim();
  if (pem.trim() !== original && !fixes.some((f) => f.includes('escapes'))) {
    fixes.push('Tidied the line breaks and spacing in the key.');
  }
  return { pem, kind, fixes, issue: null };
}

export function checkKalshiKeys(input: { keyId: unknown; pem: unknown }): KalshiKeysCheck {
  const id = checkKeyId(input.keyId);
  const pk = checkPrivateKey(input.pem);
  if (id.issue?.code === 'keyid_is_private_key' && pk.issue?.code === 'pem_is_keyid') {
    const issue: KeyIssue = {
      code: 'swapped', field: 'keyId',
      message: 'These two are swapped: the Key ID is the short code, and the private key is '
        + 'the long block. Use "Swap them" to fix it.',
    };
    return { ok: false, keyId: '', pem: '', kind: null, fixes: [], issues: [issue] };
  }
  const issues = [id.issue, pk.issue].filter((x): x is KeyIssue => x !== null);
  return {
    ok: issues.length === 0,
    keyId: id.issue ? '' : id.value,
    pem: pk.issue ? '' : pk.pem,
    kind: pk.kind,
    fixes: [...id.fixes, ...pk.fixes],
    issues,
  };
}

export function kindLabel(kind: PrivateKeyKind | null): string {
  if (kind === 'ed25519') return 'Ed25519';
  if (kind === 'rsa-pkcs1' || kind === 'rsa-pkcs8') return 'RSA';
  return 'private key';
}
