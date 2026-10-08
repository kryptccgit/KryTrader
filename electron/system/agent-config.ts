import {
  copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync, writeFileSync,
} from 'node:fs';
import { dirname, join } from 'node:path';

export interface PathEnv {
  platform: NodeJS.Platform;
  home: string;
  appData?: string;
  localAppData?: string;
  codexHome?: string;
}

export const CLAUDE_DESKTOP_FILE = 'claude_desktop_config.json';

export function claudeDesktopConfigDirs(env: PathEnv): string[] {
  if (env.platform === 'darwin') {
    return [join(env.home, 'Library', 'Application Support', 'Claude')];
  }
  if (env.platform === 'win32') {
    const dirs: string[] = [];
    if (env.appData) dirs.push(join(env.appData, 'Claude'));
    if (env.localAppData) {
      const pkgs = join(env.localAppData, 'Packages');
      try {
        for (const name of readdirSync(pkgs)) {
          if (/^Claude_/i.test(name)) dirs.push(join(pkgs, name, 'LocalCache', 'Roaming', 'Claude'));
        }
      } catch {}
    }
    return dirs;
  }
  return [join(env.home, '.config', 'Claude')];
}

export function existingClaudeDesktopDirs(env: PathEnv): string[] {
  return claudeDesktopConfigDirs(env).filter((d) => {
    try { return statSync(d).isDirectory(); } catch { return false; }
  });
}

export function codexConfigDir(env: PathEnv): string {
  return env.codexHome && env.codexHome.trim() ? env.codexHome : join(env.home, '.codex');
}

export type MergeResult = { ok: true; text: string; replaced: boolean } | { ok: false; message: string };

export function mergeClaudeDesktopConfig(existing: string | null, snippetJson: string): MergeResult {
  let snippet: unknown;
  try {
    snippet = JSON.parse(snippetJson);
  } catch {
    return { ok: false, message: 'The app could not build the Claude Desktop entry. Nothing was changed.' };
  }
  const servers = (snippet as { mcpServers?: unknown })?.mcpServers;
  if (!servers || typeof servers !== 'object' || Array.isArray(servers) || !Object.keys(servers).length) {
    return { ok: false, message: 'The app could not build the Claude Desktop entry. Nothing was changed.' };
  }

  let doc: Record<string, unknown> = {};
  const raw = (existing ?? '').replace(/^﻿/, '');
  if (raw.trim()) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return {
        ok: false,
        message: 'Your Claude Desktop config file is not valid JSON, so the app left it alone rather '
          + 'than risk your other settings. Open the config folder, fix or remove the file, and try again '
          + '(or use Copy config and paste it in by hand).',
      };
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {
        ok: false,
        message: 'Your Claude Desktop config file is not in the shape Claude uses, so the app left it alone. '
          + 'Open the config folder to look at it, or use Copy config.',
      };
    }
    doc = parsed as Record<string, unknown>;
  }
  const cur = doc.mcpServers;
  if (cur !== undefined && (cur === null || typeof cur !== 'object' || Array.isArray(cur))) {
    return {
      ok: false,
      message: 'The "mcpServers" section of your Claude Desktop config is not a list of servers, so the '
        + 'app left the file alone. Open the config folder to look at it, or use Copy config.',
    };
  }
  const merged: Record<string, unknown> = { ...((cur as Record<string, unknown>) ?? {}) };
  let replaced = false;
  for (const [name, entry] of Object.entries(servers as Record<string, unknown>)) {
    if (name in merged) replaced = true;
    merged[name] = entry;
  }
  const out = { ...doc, mcpServers: merged };
  const nl = raw.includes('\r\n') ? '\r\n' : '\n';
  return { ok: true, text: JSON.stringify(out, null, 2).replace(/\n/g, nl) + nl, replaced };
}

export function codexServerName(block: string): string | null {
  const m = /^\s*\[\s*mcp_servers\.("?)([A-Za-z0-9_-]+)\1\s*\]/m.exec(block);
  return m ? m[2] : null;
}

function isOwnHeader(line: string, name: string): boolean {
  const m = /^\s*\[\s*mcp_servers\.("?)([A-Za-z0-9_-]+)\1(\.[^\]]*)?\s*\]\s*(#.*)?$/.exec(line);
  return !!m && m[2] === name;
}

export function mergeCodexToml(existing: string | null, block: string): MergeResult {
  const name = codexServerName(block);
  if (!name) return { ok: false, message: 'The app could not build the Codex entry. Nothing was changed.' };
  const raw = (existing ?? '').replace(/^﻿/, '');
  const nl = raw.includes('\r\n') ? '\r\n' : '\n';
  const lines = raw.length ? raw.split(/\r?\n/) : [];
  const kept: string[] = [];
  let inOwn = false;
  let replaced = false;
  let insertAt = -1;
  for (const line of lines) {
    if (/^\s*\[/.test(line)) {
      if (isOwnHeader(line, name)) {
        if (!inOwn && insertAt < 0) insertAt = kept.length;
        inOwn = true;
        replaced = true;
        continue;
      }
      inOwn = false;
    }
    if (!inOwn) kept.push(line);
  }
  const rest = kept.join('\n');
  const esc = name.replace(/[-]/g, '\\-');
  if (new RegExp(`mcp_servers\\s*\\.\\s*"?${esc}"?\\s*[.=]|^\\s*"?${esc}"?\\s*=`, 'm').test(rest)) {
    return {
      ok: false,
      message: `Your Codex config already defines "${name}" in a form the app can't safely edit, so it `
        + 'left the file alone. Open the config folder and remove that entry, or use Copy config.',
    };
  }
  const ours = block.replace(/\r\n/g, '\n').replace(/\n+$/, '').split('\n');
  let outLines: string[];
  if (insertAt >= 0) {
    const before = kept.slice(0, insertAt);
    const after = kept.slice(insertAt);
    while (after.length && !after[0].trim()) after.shift();
    outLines = [...before, ...ours, ...(after.length ? ['', ...after] : [])];
  } else {
    const base = [...kept];
    while (base.length && !base[base.length - 1].trim()) base.pop();
    outLines = base.length ? [...base, '', ...ours] : ours;
  }
  while (outLines.length && !outLines[outLines.length - 1].trim()) outLines.pop();
  return { ok: true, text: outLines.join(nl) + nl, replaced };
}

export function backupPath(file: string, now = new Date()): string {
  const stamp = now.toISOString().replace(/\.\d+Z$/, '').replace(/:/g, '-');
  return `${file}.${stamp}.bak`;
}

export type WriteResult = { ok: true; backup: string | null } | { ok: false; message: string };

export function writeWithBackup(file: string, text: string, now = new Date()): WriteResult {
  try {
    mkdirSync(dirname(file), { recursive: true });
    let backup: string | null = null;
    if (existsSync(file)) {
      backup = backupPath(file, now);
      copyFileSync(file, backup);
    }
    const tmp = `${file}.krypt-tmp`;
    writeFileSync(tmp, text, 'utf-8');
    renameSync(tmp, file);
    return { ok: true, backup };
  } catch (e) {
    const code = (e as NodeJS.ErrnoException)?.code;
    return {
      ok: false,
      message: code === 'EACCES' || code === 'EPERM' || code === 'EBUSY'
        ? `The app wasn't allowed to write ${file}. If that program is open, quit it and try again.`
        : `The app couldn't write ${file}. Nothing else was changed.`,
    };
  }
}

export interface InstallOutcome {
  ok: boolean;
  message: string;
  files: string[];
  backups: string[];
}

function readOrNull(file: string): string | null {
  try { return existsSync(file) ? readFileSync(file, 'utf-8') : null; } catch { return null; }
}

export function installClaudeDesktop(env: PathEnv, snippetJson: string, now = new Date()): InstallOutcome {
  const dirs = existingClaudeDesktopDirs(env);
  if (!dirs.length) {
    return {
      ok: false, files: [], backups: [],
      message: 'Claude Desktop doesn\'t seem to be installed on this computer (its settings folder '
        + 'isn\'t there). Install it, open it once, then press Add again.',
    };
  }
  const plans: { file: string; text: string }[] = [];
  for (const d of dirs) {
    const file = join(d, CLAUDE_DESKTOP_FILE);
    const m = mergeClaudeDesktopConfig(readOrNull(file), snippetJson);
    if (!m.ok) return { ok: false, files: [], backups: [], message: m.message };
    plans.push({ file, text: m.text });
  }
  const files: string[] = [];
  const backups: string[] = [];
  for (const p of plans) {
    const w = writeWithBackup(p.file, p.text, now);
    if (!w.ok) {
      return { ok: files.length > 0, files, backups, message: w.message };
    }
    files.push(p.file);
    if (w.backup) backups.push(w.backup);
  }
  return {
    ok: true, files, backups,
    message: 'Added to Claude Desktop. Now fully quit Claude Desktop (right-click its tray icon → Quit) '
      + 'and open it again — it only reads this file when it starts.',
  };
}

export function installCodex(env: PathEnv, block: string, now = new Date()): InstallOutcome {
  const file = join(codexConfigDir(env), 'config.toml');
  const m = mergeCodexToml(readOrNull(file), block);
  if (!m.ok) return { ok: false, files: [], backups: [], message: m.message };
  const w = writeWithBackup(file, m.text, now);
  if (!w.ok) return { ok: false, files: [], backups: [], message: w.message };
  return {
    ok: true, files: [file], backups: w.backup ? [w.backup] : [],
    message: `${m.replaced ? 'Updated' : 'Added'} in Codex's config. Restart Codex so it picks it up.`,
  };
}
