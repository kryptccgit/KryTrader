import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { ensureVenv, run, tryCmd, VENV_PY, PY_DIR } from './python-utils.mjs';

ensureVenv();

if (!tryCmd(VENV_PY, ['-c', 'import pytest'])) {
  console.log('>> Installing dev test deps into venv (one-time)');
  const devReq = join(PY_DIR, 'requirements-dev.txt');
  run(
    VENV_PY,
    existsSync(devReq)
      ? ['-m', 'pip', 'install', '-r', 'requirements-dev.txt', '--disable-pip-version-check']
      : ['-m', 'pip', 'install', 'pytest', '--disable-pip-version-check'],
  );
}

const extra = process.argv.slice(2);
run(VENV_PY, ['-m', 'pytest', ...extra]);
