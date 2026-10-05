import { ensureVenv, run, VENV_PY } from './python-utils.mjs';

ensureVenv();
run(VENV_PY, ['backtest.py', ...process.argv.slice(2)]);
