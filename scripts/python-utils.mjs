import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

export const __dirname = dirname(fileURLToPath(import.meta.url));
export const ROOT = dirname(__dirname);
export const PY_DIR = join(ROOT, 'python');
export const VENV = join(PY_DIR, '.venv');
export const VENV_PY = process.platform === 'win32'
  ? join(VENV, 'Scripts', 'python.exe')
  : join(VENV, 'bin', 'python');

const isWin = process.platform === 'win32';

export function run(cmd, args, opts = {}) {
  const display = `${cmd} ${args.map((a) => (a.includes(' ') ? `"${a}"` : a)).join(' ')}`;
  console.log(`> ${display}`);
  const r = spawnSync(cmd, args, {
    stdio: 'inherit',
    cwd: PY_DIR,
    shell: false,
    ...opts,
  });
  if (r.error) {
    throw new Error(`${cmd} could not be spawned: ${r.error.message}`);
  }
  if (r.status !== 0) {
    throw new Error(`${display} failed with exit code ${r.status}`);
  }
}

export function tryCmd(cmd, args) {
  try {
    const r = spawnSync(cmd, args, {
      stdio: 'ignore',
      shell: false,
      windowsHide: true,
    });
    return !r.error && r.status === 0;
  } catch {
    return false;
  }
}

let _systemPy = null;
export function findSystemPython() {
  if (_systemPy) return _systemPy;
  const candidates = isWin
    ? [
        { cmd: 'py', args: ['-3', '--version'], spawnAs: 'py' },
        { cmd: 'python', args: ['--version'], spawnAs: 'python' },
        { cmd: 'python3', args: ['--version'], spawnAs: 'python3' },
      ]
    : [
        { cmd: 'python3', args: ['--version'], spawnAs: 'python3' },
        { cmd: 'python', args: ['--version'], spawnAs: 'python' },
      ];
  for (const c of candidates) {
    if (tryCmd(c.cmd, c.args)) {
      _systemPy = c.spawnAs;
      return _systemPy;
    }
  }
  throw new Error(
    'No Python 3 interpreter found on PATH. Install Python 3.10+ from https://python.org and try again.',
  );
}

export function systemPyPrefix() {
  return findSystemPython() === 'py' ? ['-3'] : [];
}

export function ensureVenv({ force = false } = {}) {
  if (!existsSync(VENV) || force) {
    const sys = findSystemPython();
    console.log('>> Creating Python venv at python/.venv');
    run(sys, [...systemPyPrefix(), '-m', 'venv', '.venv']);
  }
  if (!existsSync(VENV_PY)) {
    throw new Error(`venv created but no interpreter at ${VENV_PY}`);
  }
  if (!force && tryCmd(VENV_PY, ['-c', 'import httpx, cryptography, websockets'])) {
    return;
  }
  console.log('>> Installing Python deps into venv (one-time, ~30s)');
  run(VENV_PY, ['-m', 'pip', 'install', '--upgrade', 'pip', 'wheel', '--disable-pip-version-check']);
  run(VENV_PY, ['-m', 'pip', 'install', '-r', 'requirements.txt', '--disable-pip-version-check']);
}
