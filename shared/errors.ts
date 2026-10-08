
const CODE_RE = /^\[([a-z][a-z0-9_.-]{0,63})\]\s*/i;

export function encodeRpcError(message: string, code?: string | null): string {
  const m = String(message ?? '').trim() || 'The backend refused that.';
  const c = typeof code === 'string' ? code.trim() : '';
  return c && /^[a-z][a-z0-9_.-]{0,63}$/i.test(c) ? `[${c}] ${m}` : m;
}

export function parseErrorText(raw: string): { code: string | null; message: string } {
  let s = String(raw ?? '').trim();
  s = s.replace(/^Error invoking remote method '[^']*':\s*/i, '');
  let code: string | null = null;
  for (let i = 0; i < 6; i++) {
    const before = s;
    s = s.replace(/^(?:[A-Z][A-Za-z0-9_]*(?:Error|Exception|Exit)|Error):\s*/, '');
    const m = CODE_RE.exec(s);
    if (m) {
      code = code ?? m[1].toLowerCase();
      s = s.slice(m[0].length);
    }
    if (s === before) break;
  }
  return { code, message: s.trim() };
}
