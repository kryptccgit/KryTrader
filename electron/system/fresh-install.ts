import { app } from 'electron';
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { appendLog } from '../ipc';

const APP_EXE = 'Krypt Trader.exe';
const BACKEND_EXE = 'krypt-trader-backend.exe';

function enabled(): boolean {
  return app.isPackaged || process.env.KRYPT_FRESH_INSTALL_FORCE === '1';
}

function log(level: 'INFO' | 'WARNING' | 'ERROR', msg: string): void {
  const entry = { ts: new Date().toISOString(), level, source: 'app', msg };
  try { appendLog(entry); } catch {   }
  console.log(`[fresh-install] ${level} ${msg}`);
}

export function sleepSync(ms: number): void {
  if (ms <= 0) return;
  try {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
  } catch {   }
}

interface ProcRow { ProcessId: number; ExecutablePath: string | null }

function findOtherInstancePids(): number[] {
  const ourDir = dirname(process.execPath).toLowerCase();
  const ps =
    "$ErrorActionPreference='SilentlyContinue';" +
    `Get-CimInstance Win32_Process -Filter "Name='${APP_EXE}' OR Name='${BACKEND_EXE}'"` +
    ' | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress';
  const encoded = Buffer.from(ps, 'utf16le').toString('base64');
  let out: string;
  try {
    const r = spawnSync(
      'powershell',
      ['-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
      { timeout: 5000, windowsHide: true, encoding: 'utf-8' },
    );
    if (r.status !== 0 || !r.stdout) return [];
    out = r.stdout.trim();
  } catch {
    return [];
  }
  if (!out) return [];
  let parsed: ProcRow | ProcRow[];
  try {
    parsed = JSON.parse(out);
  } catch {
    return [];
  }
  const rows = Array.isArray(parsed) ? parsed : [parsed];
  const pids: number[] = [];
  for (const row of rows) {
    const pid = Number(row?.ProcessId);
    const exe = row?.ExecutablePath;
    if (!Number.isInteger(pid) || pid <= 0 || pid === process.pid) continue;
    if (!exe) continue;
    if (exe.toLowerCase().startsWith(ourDir + '\\') || exe.toLowerCase() === process.execPath.toLowerCase()) {
      continue;
    }
    pids.push(pid);
  }
  return pids;
}

function killPid(pid: number): void {
  try {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], {
      timeout: 5000, windowsHide: true,
    });
  } catch {   }
}

export function takeOverOtherInstances(): number {
  if (!enabled() || process.platform !== 'win32') return 0;
  let killed = 0;
  try {
    const pids = findOtherInstancePids();
    for (const pid of pids) {
      killPid(pid);
      killed++;
    }
    if (killed > 0) {
      log('INFO', `took over from ${killed} stale Krypt Trader process(es) from another install`);
    }
  } catch (e: any) {
    log('WARNING', `instance takeover failed (non-fatal): ${e?.message || e}`);
  }
  return killed;
}

function readPrevVersion(statePath: string): string | null {
  try {
    const raw = JSON.parse(readFileSync(statePath, 'utf-8'));
    return typeof raw?.version === 'string' ? raw.version : null;
  } catch {
    return null;
  }
}

function writeVersion(statePath: string, version: string): void {
  try {
    const tmp = `${statePath}.tmp`;
    writeFileSync(
      tmp,
      JSON.stringify({ version, updatedAt: new Date().toISOString() }, null, 2),
      'utf-8',
    );
    renameSync(tmp, statePath);
  } catch (e: any) {
    log('WARNING', `could not write install-state.json: ${e?.message || e}`);
  }
}

function pruneBackupsExcept(backupsRoot: string, keep: string): void {
  let entries: string[] = [];
  try { entries = readdirSync(backupsRoot); } catch { return; }
  for (const e of entries) {
    if (e === keep) continue;
    if (existsSync(join(backupsRoot, e, 'data'))) continue;
    try { rmSync(join(backupsRoot, e), { recursive: true, force: true }); } catch {   }
  }
}

function snapshotFile(src: string, backupDir: string, name: string): boolean {
  if (!existsSync(src)) return true;
  try {
    mkdirSync(backupDir, { recursive: true });
    copyFileSync(src, join(backupDir, name));
    return true;
  } catch (e: any) {
    log('WARNING', `rollback snapshot of ${name} failed: ${e?.message || e}`);
    return false;
  }
}

export function runVersionMaintenance(): void {
  if (!enabled()) return;

  const userData = app.getPath('userData');
  try { mkdirSync(userData, { recursive: true }); } catch {   }

  const statePath = join(userData, 'install-state.json');
  const settingsPath = join(userData, 'settings.json');
  const dataDir = join(userData, 'data');
  const logsDir = join(userData, 'logs');
  const dbPath = join(dataDir, 'krypt-trader.db');

  const current = app.getVersion();
  const prev = readPrevVersion(statePath);

  if (prev === current) return;

  if (prev === null) {
    writeVersion(statePath, current);
    return;
  }

  const tag = prev.replace(/[^\w.\-]/g, '_');
  const backupsRoot = join(userData, 'backups');
  const backupDir = join(backupsRoot, `v${tag}`);
  try { rmSync(backupDir, { recursive: true, force: true }); } catch {   }

  let snapshotOk = snapshotFile(settingsPath, backupDir, 'settings.json');
  for (const suffix of ['', '-wal', '-shm']) {
    snapshotOk = snapshotFile(`${dbPath}${suffix}`, backupDir, `krypt-trader.db${suffix}`) && snapshotOk;
  }

  try { rmSync(logsDir, { recursive: true, force: true }); } catch {   }

  if (snapshotOk) pruneBackupsExcept(backupsRoot, `v${tag}`);
  writeVersion(statePath, current);
  log(
    'INFO',
    `version change ${prev} -> ${current}: settings + data preserved` +
    (snapshotOk ? ` (rollback snapshot at backups/v${tag})` : ' (snapshot incomplete — older backups kept)'),
  );
}
