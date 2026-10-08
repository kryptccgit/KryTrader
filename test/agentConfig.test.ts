import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  backupPath, claudeDesktopConfigDirs, codexServerName, installClaudeDesktop, installCodex,
  mergeClaudeDesktopConfig, mergeCodexToml, writeWithBackup, type PathEnv,
} from '../electron/system/agent-config';


const SNIPPET = JSON.stringify({
  mcpServers: { 'krypt-trader': { command: 'C:\\app\\backend.exe', args: ['--mcp-stdio'], env: { KRYPT_MCP_TOKEN: 'tok-123' } } },
}, null, 2);

const CODEX = "[mcp_servers.krypt-trader]\nurl = 'http://127.0.0.1:47821/mcp'\nhttp_headers = { Authorization = 'Bearer tok-123' }\n";

let root = '';
beforeEach(() => { root = mkdtempSync(join(tmpdir(), 'krypt-agentcfg-')); });
afterEach(() => rmSync(root, { recursive: true, force: true }));

function winEnv(): PathEnv {
  return { platform: 'win32', home: join(root, 'home'), appData: join(root, 'Roaming'), localAppData: join(root, 'Local') };
}

describe('mergeClaudeDesktopConfig', () => {
  it('creates the file shape from nothing', () => {
    const r = mergeClaudeDesktopConfig(null, SNIPPET);
    expect(r.ok).toBe(true);
    if (r.ok) expect(JSON.parse(r.text).mcpServers['krypt-trader'].env.KRYPT_MCP_TOKEN).toBe('tok-123');
  });

  it('keeps every other server and every other setting, and replaces only its own entry', () => {
    const existing = JSON.stringify({
      globalShortcut: 'Ctrl+Space',
      mcpServers: { filesystem: { command: 'npx', args: ['fs'] }, 'krypt-trader': { command: 'old' } },
    });
    const r = mergeClaudeDesktopConfig(existing, SNIPPET);
    expect(r.ok && r.replaced).toBe(true);
    if (!r.ok) return;
    const doc = JSON.parse(r.text);
    expect(doc.globalShortcut).toBe('Ctrl+Space');
    expect(doc.mcpServers.filesystem).toEqual({ command: 'npx', args: ['fs'] });
    expect(doc.mcpServers['krypt-trader'].command).toBe('C:\\app\\backend.exe');
    expect(Object.keys(doc.mcpServers)).toHaveLength(2);
  });

  it('refuses a file that is not valid JSON, with a plain message', () => {
    const r = mergeClaudeDesktopConfig('{ "mcpServers": { , }', SNIPPET);
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.message).toMatch(/not valid JSON/);
      expect(r.message).not.toMatch(/SyntaxError|Unexpected token/);
    }
  });

  it('refuses a non-object document or a non-object mcpServers', () => {
    expect(mergeClaudeDesktopConfig('[1,2]', SNIPPET).ok).toBe(false);
    expect(mergeClaudeDesktopConfig('{"mcpServers": []}', SNIPPET).ok).toBe(false);
    expect(mergeClaudeDesktopConfig('{"mcpServers": "x"}', SNIPPET).ok).toBe(false);
  });

  it('tolerates a BOM and keeps CRLF if the file used it', () => {
    const r = mergeClaudeDesktopConfig('\uFEFF{\r\n  "a": 1\r\n}\r\n', SNIPPET);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.text.includes('\r\n')).toBe(true);
      expect(JSON.parse(r.text).a).toBe(1);
    }
  });
});

describe('Claude Desktop folders', () => {
  it('Windows: the normal install AND every Microsoft Store package', () => {
    const env = winEnv();
    mkdirSync(join(env.localAppData!, 'Packages', 'Claude_pzs8sxrjxfjjc'), { recursive: true });
    mkdirSync(join(env.localAppData!, 'Packages', 'Other_123'), { recursive: true });
    const dirs = claudeDesktopConfigDirs(env);
    expect(dirs[0]).toBe(join(env.appData!, 'Claude'));
    expect(dirs).toContain(join(env.localAppData!, 'Packages', 'Claude_pzs8sxrjxfjjc', 'LocalCache', 'Roaming', 'Claude'));
    expect(dirs.some((d) => d.includes('Other_123'))).toBe(false);
  });

  it('macOS: Application Support', () => {
    expect(claudeDesktopConfigDirs({ platform: 'darwin', home: '/Users/me' }))
      .toEqual([join('/Users/me', 'Library', 'Application Support', 'Claude')]);
  });
});

describe('installClaudeDesktop', () => {
  it('says Claude Desktop is not installed when no folder exists, and writes nothing', () => {
    const env = winEnv();
    const r = installClaudeDesktop(env, SNIPPET);
    expect(r.ok).toBe(false);
    expect(r.message).toMatch(/isn't there|installed/);
    expect(existsSync(join(env.appData!, 'Claude'))).toBe(false);
  });

  it('writes both installs, backing each existing file up first', () => {
    const env = winEnv();
    const normal = join(env.appData!, 'Claude');
    const store = join(env.localAppData!, 'Packages', 'Claude_abc', 'LocalCache', 'Roaming', 'Claude');
    mkdirSync(normal, { recursive: true });
    mkdirSync(store, { recursive: true });
    const before = JSON.stringify({ mcpServers: { other: { command: 'x' } } });
    writeFileSync(join(normal, 'claude_desktop_config.json'), before);

    const r = installClaudeDesktop(env, SNIPPET, new Date('2026-10-07T12:30:05.123Z'));
    expect(r.ok).toBe(true);
    expect(r.files).toHaveLength(2);
    expect(r.backups).toEqual([join(normal, 'claude_desktop_config.json.2026-10-07T12-30-05.bak')]);
    expect(readFileSync(r.backups[0], 'utf-8')).toBe(before);
    const merged = JSON.parse(readFileSync(join(normal, 'claude_desktop_config.json'), 'utf-8'));
    expect(Object.keys(merged.mcpServers).sort()).toEqual(['krypt-trader', 'other']);
    expect(JSON.parse(readFileSync(join(store, 'claude_desktop_config.json'), 'utf-8')).mcpServers['krypt-trader']).toBeTruthy();
    expect(r.message).toMatch(/quit Claude Desktop/i);
  });

  it('writes NOTHING anywhere if any one existing file is unreadable', () => {
    const env = winEnv();
    const normal = join(env.appData!, 'Claude');
    const store = join(env.localAppData!, 'Packages', 'Claude_abc', 'LocalCache', 'Roaming', 'Claude');
    mkdirSync(normal, { recursive: true });
    mkdirSync(store, { recursive: true });
    writeFileSync(join(store, 'claude_desktop_config.json'), '{ broken');
    const r = installClaudeDesktop(env, SNIPPET);
    expect(r.ok).toBe(false);
    expect(existsSync(join(normal, 'claude_desktop_config.json'))).toBe(false);
    expect(readFileSync(join(store, 'claude_desktop_config.json'), 'utf-8')).toBe('{ broken');
    expect(readdirSync(store).filter((f) => f.endsWith('.bak'))).toEqual([]);
  });
});

describe('Codex TOML', () => {
  it('names the server from the block', () => {
    expect(codexServerName(CODEX)).toBe('krypt-trader');
    expect(codexServerName('[mcp_servers."krypt-trader-sam"]\n')).toBe('krypt-trader-sam');
    expect(codexServerName('nope')).toBeNull();
  });

  it('appends to a file without it, keeping everything else', () => {
    const existing = 'model = "o4"\n\n[mcp_servers.other]\ncommand = "x"\n';
    const r = mergeCodexToml(existing, CODEX);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.replaced).toBe(false);
    expect(r.text.startsWith('model = "o4"\n\n[mcp_servers.other]\ncommand = "x"\n\n[mcp_servers.krypt-trader]')).toBe(true);
  });

  it('replaces an earlier copy (and its sub-tables) instead of adding a second, in place', () => {
    const existing = [
      'model = "o4"',
      '',
      '[mcp_servers.krypt-trader]',
      "url = 'http://old'",
      '[mcp_servers.krypt-trader.env]',
      'X = "1"',
      '',
      '[mcp_servers.krypt-trader-sam]',
      "url = 'keep-me'",
      '',
      '[profiles.fast]',
      'model = "x"',
      '',
    ].join('\n');
    const r = mergeCodexToml(existing, CODEX);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.replaced).toBe(true);
    expect(r.text.match(/\[mcp_servers\.krypt-trader\]/g)).toHaveLength(1);
    expect(r.text).not.toContain('http://old');
    expect(r.text).not.toContain('X = "1"');
    expect(r.text).toContain("[mcp_servers.krypt-trader-sam]\nurl = 'keep-me'");
    expect(r.text).toContain('[profiles.fast]');
    expect(r.text.indexOf('[mcp_servers.krypt-trader]')).toBeLessThan(r.text.indexOf('[mcp_servers.krypt-trader-sam]'));
  });

  it('refuses a dotted-key definition it cannot safely remove', () => {
    const r = mergeCodexToml('[mcp_servers]\nkrypt-trader = { url = "x" }\n', CODEX);
    expect(r.ok).toBe(false);
    const r2 = mergeCodexToml('mcp_servers.krypt-trader.url = "x"\n', CODEX);
    expect(r2.ok).toBe(false);
  });

  it('keeps CRLF files CRLF', () => {
    const r = mergeCodexToml('model = "o4"\r\n', CODEX);
    expect(r.ok && r.text.includes('\r\n[mcp_servers.krypt-trader]\r\n')).toBe(true);
  });

  it('installCodex honours CODEX_HOME and backs up', () => {
    const env: PathEnv = { platform: 'linux', home: join(root, 'h'), codexHome: join(root, 'cx') };
    mkdirSync(env.codexHome!, { recursive: true });
    writeFileSync(join(env.codexHome!, 'config.toml'), CODEX.replace('tok-123', 'old'));
    const r = installCodex(env, CODEX);
    expect(r.ok).toBe(true);
    expect(r.message).toMatch(/Updated/);
    expect(r.backups).toHaveLength(1);
    expect(readFileSync(join(env.codexHome!, 'config.toml'), 'utf-8')).toContain('tok-123');
  });
});

describe('writeWithBackup', () => {
  it('names backups with a timestamp beside the file', () => {
    expect(backupPath('/x/c.json', new Date('2026-01-02T03:04:05.000Z'))).toBe('/x/c.json.2026-01-02T03-04-05.bak');
  });

  it('a new file gets no backup', () => {
    const f = join(root, 'new', 'c.json');
    const w = writeWithBackup(f, '{}');
    expect(w).toEqual({ ok: true, backup: null });
    expect(readFileSync(f, 'utf-8')).toBe('{}');
  });
});
