import { app, BrowserWindow } from 'electron';
import { spawn, spawnSync, ChildProcessWithoutNullStreams } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import type { BackendInfo, BackendStatus, LogEntry } from '../../shared/types';
import { encodeRpcError } from '../../shared/errors';


let darwinBackendPrepared = false;
function prepareDarwinBackend(base: string, exe: string): void {
  if (process.platform !== 'darwin' || darwinBackendPrepared) return;
  darwinBackendPrepared = true;
  try {
    if ((statSync(exe).mode & 0o111) === 0) chmodSync(exe, 0o755);
  } catch {
  }
  try {
    spawnSync('xattr', ['-dr', 'com.apple.quarantine', base], { timeout: 10_000 });
  } catch {
  }
}

type Pending = {
  resolve: (val: any) => void;
  reject: (err: Error) => void;
  method: string;
  startedAt: number;
};

type EventCallback = (name: string, data: any) => void;
type LogCallback = (entry: LogEntry) => void;

const STABLE_UPTIME_MS = 30_000;
const MAX_RAPID_RESTARTS = 5;
const PING_INTERVAL_MS = 60_000;
const PING_TIMEOUT_MS = 15_000;
const PING_FAILS_TO_RESTART = 3;

class PythonBackend {
  private child: ChildProcessWithoutNullStreams | null = null;
  private pending = new Map<string, Pending>();
  private buffer = '';
  private status: BackendStatus = 'stopped';
  private startedAt: string | null = null;
  private lastError: string | null = null;
  private authOk = false;
  private pythonOk = false;
  private restartTimer: NodeJS.Timeout | null = null;
  private pingTimer: NodeJS.Timeout | null = null;
  private pingFails = 0;
  private pingInFlight = false;
  private restartAttempts = 0;
  private childStartedAtMs = 0;
  private gaveUp = false;
  private nextId = 1;
  private eventHandlers: EventCallback[] = [];
  private logHandlers: LogCallback[] = [];
  private statusHandlers: ((info: BackendInfo) => void)[] = [];
  private requestedStop = false;


  async start(): Promise<void> {
    if (this.status === 'running' || this.status === 'starting') return;
    this.requestedStop = false;
    this.gaveUp = false;
    this.restartAttempts = 0;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    this.startChild();
  }

  async stop(): Promise<void> {
    this.requestedStop = true;
    this.stopPingWatchdog();
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    const c = this.child;
    if (!c) {
      this.setStatus('stopped');
      return;
    }
    try {
      this.send({ type: 'rpc', id: this.id(), method: 'shutdown', params: {} });
    } catch {
    }
    setTimeout(() => {
      if (c && !c.killed) {
        try {
          c.kill('SIGTERM');
        } catch {
        }
      }
    }, 1500);
  }

  async restart(): Promise<void> {
    this.setStatus('restarting');
    await this.stop();
    setTimeout(() => this.start(), 1500);
  }

  info(): BackendInfo {
    return {
      status: this.status,
      pid: this.child?.pid ?? null,
      startedAt: this.startedAt,
      lastError: this.lastError,
      pythonOk: this.pythonOk,
      authOk: this.authOk,
    };
  }

  isRunning(): boolean {
    return this.status === 'running';
  }

  onEvent(cb: EventCallback): () => void {
    this.eventHandlers.push(cb);
    return () => {
      this.eventHandlers = this.eventHandlers.filter((c) => c !== cb);
    };
  }

  onLog(cb: LogCallback): () => void {
    this.logHandlers.push(cb);
    return () => {
      this.logHandlers = this.logHandlers.filter((c) => c !== cb);
    };
  }

  onStatusChange(cb: (info: BackendInfo) => void): () => void {
    this.statusHandlers.push(cb);
    return () => {
      this.statusHandlers = this.statusHandlers.filter((c) => c !== cb);
    };
  }

  async request<T = any>(method: string, params: any = {}, timeoutMs = 30_000): Promise<T> {
    if (!this.child || this.status !== 'running') {
      throw new Error('Backend not running');
    }
    const id = this.id();
    const msg = { type: 'rpc', id, method, params };
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`RPC ${method} timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, {
        method,
        startedAt: Date.now(),
        resolve: (v) => {
          clearTimeout(timer);
          resolve(v);
        },
        reject: (e) => {
          clearTimeout(timer);
          reject(e);
        },
      });
      try {
        this.send(msg);
      } catch (e) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(e as Error);
      }
    });
  }

  private rejectPending(reason: string): void {
    for (const [, p] of this.pending) {
      try { p.reject(new Error(reason)); } catch {   }
    }
    this.pending.clear();
  }


  private id(): string {
    return `r${this.nextId++}`;
  }

  private resolveBackendBin(): { cmd: string; args: string[]; cwd: string } | null {
    if (app.isPackaged) {
      const base = join(process.resourcesPath, 'python');
      const exe =
        process.platform === 'win32'
          ? join(base, 'krypt-trader-backend.exe')
          : join(base, 'krypt-trader-backend');
      if (existsSync(exe)) {
        prepareDarwinBackend(base, exe);
        return { cmd: exe, args: [], cwd: base };
      }
      this.lastError = `bundled backend binary missing at ${exe}`;
      return null;
    }
    const pyDir = join(process.cwd(), 'python');
    const servicePath = join(pyDir, 'service.py');
    if (!existsSync(servicePath)) {
      this.lastError = `service.py not found at ${servicePath}`;
      return null;
    }

    const venvPy = process.platform === 'win32'
      ? join(pyDir, '.venv', 'Scripts', 'python.exe')
      : join(pyDir, '.venv', 'bin', 'python');
    if (existsSync(venvPy)) {
      return { cmd: venvPy, args: [servicePath], cwd: pyDir };
    }

    const candidates: { cmd: string; pre: string[] }[] = process.platform === 'win32'
      ? [
          { cmd: 'py', pre: ['-3'] },
          { cmd: 'python', pre: [] },
          { cmd: 'python3', pre: [] },
        ]
      : [
          { cmd: 'python3', pre: [] },
          { cmd: 'python', pre: [] },
        ];
    for (const c of candidates) {
      try {
        const probe = spawnSync(c.cmd, [...c.pre, '--version'], {
          stdio: 'ignore', shell: false, windowsHide: true,
        });
        if (!probe.error && probe.status === 0) {
          return { cmd: c.cmd, args: [...c.pre, servicePath], cwd: pyDir };
        }
      } catch {   }
    }
    this.lastError = 'No Python 3 interpreter found. Run `npm run py:setup` or install Python 3.10+ from https://python.org.';
    return null;
  }

  private startChild(): void {
    if (this.child) {
      const stale = this.child;
      this.child = null;
      try {
        stale.stdout?.removeAllListeners();
        stale.stderr?.removeAllListeners();
        stale.removeAllListeners();
        stale.kill('SIGKILL');
      } catch {
      }
    }
    this.setStatus('starting');
    const userData = app.getPath('userData');
    for (const sub of ['logs', 'data', 'credentials']) {
      const d = join(userData, sub);
      if (!existsSync(d)) mkdirSync(d, { recursive: true });
    }

    const resolved = this.resolveBackendBin();
    if (!resolved) {
      this.pythonOk = false;
      this.setStatus('crashed');
      this.requestedStop = true;
      return;
    }
    const { cmd, args, cwd } = resolved;
    let child: ChildProcessWithoutNullStreams;
    try {
      child = spawn(cmd, args, {
        cwd,
        env: {
          ...process.env,
          KRYPT_TRADER_USERDATA: userData,
          KRYPT_APP_VERSION: app.getVersion(),
          PYTHONUNBUFFERED: '1',
          PYTHONIOENCODING: 'utf-8',
        },
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      });
    } catch (e: any) {
      this.lastError = `spawn failed: ${e?.message || e}`;
      this.pythonOk = false;
      this.setStatus('crashed');
      this.scheduleRestart(true);
      return;
    }

    this.child = child;
    this.pythonOk = true;
    this.startedAt = new Date().toISOString();
    this.childStartedAtMs = Date.now();
    this.lastError = null;
    this.buffer = '';

    child.stdout.setEncoding('utf-8');
    child.stderr.setEncoding('utf-8');
    child.stdout.on('data', (chunk: string) => this.onStdout(chunk));
    child.stderr.on('data', (chunk: string) => this.onStderr(chunk));
    child.on('error', (err) => {
      if (this.child !== child) return;
      this.lastError = `child error: ${err.message}`;
      this.pythonOk = false;
    });
    child.on('exit', (code, signal) => {
      if (this.child !== child) return;
      this.child = null;
      this.stopPingWatchdog();
      this.rejectPending('backend exited');
      if (this.requestedStop) {
        this.setStatus('stopped');
        return;
      }
      const uptime = Date.now() - this.childStartedAtMs;
      this.lastError = `backend exited (code=${code} signal=${signal})`;
      this.setStatus('crashed');
      this.scheduleRestart(uptime < STABLE_UPTIME_MS);
    });

    this.startPingWatchdog(child);
  }

  private stopPingWatchdog(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    this.pingFails = 0;
    this.pingInFlight = false;
  }

  private startPingWatchdog(child: ChildProcessWithoutNullStreams): void {
    this.stopPingWatchdog();
    this.pingTimer = setInterval(() => {
      if (this.child !== child || this.status !== 'running' || this.requestedStop) return;
      if (this.pingInFlight) return;
      this.pingInFlight = true;
      this.request('ping', {}, PING_TIMEOUT_MS)
        .then(() => {
          this.pingFails = 0;
        })
        .catch(() => {
          if (this.child !== child || this.requestedStop) return;
          this.pingFails++;
          if (this.pingFails >= PING_FAILS_TO_RESTART) {
            this.lastError = `backend unresponsive (${this.pingFails} pings timed out) — force-restarting`;
            const entry: LogEntry = {
              ts: new Date().toISOString(),
              level: 'ERROR',
              source: 'backend',
              msg: this.lastError,
            };
            for (const h of this.logHandlers) h(entry);
            this.stopPingWatchdog();
            try {
              child.kill('SIGKILL');
            } catch {
            }
          }
        })
        .finally(() => {
          this.pingInFlight = false;
        });
    }, PING_INTERVAL_MS);
  }

  private scheduleRestart(quickCrash: boolean): void {
    if (this.requestedStop || this.gaveUp) return;
    if (this.restartTimer) return;

    if (quickCrash) {
      this.restartAttempts++;
    } else {
      this.restartAttempts = 0;
    }

    if (this.restartAttempts >= MAX_RAPID_RESTARTS) {
      this.gaveUp = true;
      this.requestedStop = true;
      this.lastError =
        `backend crashed ${this.restartAttempts}× on startup; not restarting. ` +
        `${this.lastError ?? ''}`.trim();
      this.setStatus('crashed');
      const entry: LogEntry = {
        ts: new Date().toISOString(),
        level: 'ERROR',
        source: 'backend',
        msg: this.lastError,
      };
      for (const h of this.logHandlers) h(entry);
      return;
    }

    const delay = Math.min(2000 * this.restartAttempts, 20_000);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (this.requestedStop || this.gaveUp || this.child) return;
      this.startChild();
    }, delay);
  }

  private send(obj: any): void {
    if (!this.child || !this.child.stdin.writable) {
      throw new Error('Backend stdin not writable');
    }
    this.child.stdin.write(JSON.stringify(obj) + '\n');
  }

  private onStdout(chunk: string): void {
    this.buffer += chunk;
    let nl: number;
    while ((nl = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, nl).trim();
      this.buffer = this.buffer.slice(nl + 1);
      if (!line) continue;
      this.handleLine(line);
    }
  }

  private onStderr(chunk: string): void {
    const text = chunk.toString().trim();
    if (text) {
      const entry: LogEntry = {
        ts: new Date().toISOString(),
        level: 'ERROR',
        source: 'backend',
        msg: text,
      };
      for (const h of this.logHandlers) h(entry);
    }
  }

  private handleLine(line: string): void {
    let obj: any;
    try {
      obj = JSON.parse(line);
    } catch {
      const entry: LogEntry = {
        ts: new Date().toISOString(),
        level: 'INFO',
        source: 'backend',
        msg: line,
      };
      for (const h of this.logHandlers) h(entry);
      return;
    }

    if (this.status === 'starting') {
      this.setStatus('running');
    }

    if (obj.type === 'rpc') {
      const p = this.pending.get(obj.id);
      if (!p) return;
      this.pending.delete(obj.id);
      if (obj.ok) {
        p.resolve(obj.result);
      } else {
        const e = obj.error;
        const message = typeof e === 'string' ? e
          : (e && typeof e === 'object' && typeof e.message === 'string') ? e.message
            : typeof obj.message === 'string' ? obj.message : 'rpc failed';
        const code = (e && typeof e === 'object' && typeof e.code === 'string') ? e.code
          : typeof obj.code === 'string' ? obj.code : null;
        p.reject(new Error(encodeRpcError(message, code)));
      }
      return;
    }
    if (obj.type === 'event') {
      const name = String(obj.name || '');
      const data = obj.data;
      if (name === 'backend:authChanged') {
        this.authOk = !!data?.authOk;
        this.emitStatus();
      }
      for (const h of this.eventHandlers) h(name, data);
      return;
    }
    if (obj.type === 'log') {
      const entry: LogEntry = {
        ts: obj.ts || new Date().toISOString(),
        level: obj.level || 'INFO',
        source: obj.source || 'backend',
        msg: obj.msg || '',
      };
      for (const h of this.logHandlers) h(entry);
      return;
    }
  }

  private setStatus(s: BackendStatus): void {
    this.status = s;
    this.emitStatus();
  }

  private emitStatus(): void {
    const info = this.info();
    for (const h of this.statusHandlers) h(info);
  }
}

export const pythonBackend = new PythonBackend();
