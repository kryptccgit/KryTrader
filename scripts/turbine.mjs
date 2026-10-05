import { join } from 'node:path';
import { ensureVenv, run, VENV_PY } from './python-utils.mjs';

if (!process.env.KRYPT_TRADER_USERDATA && process.env.APPDATA) {
  process.env.KRYPT_TRADER_USERDATA = join(process.env.APPDATA, 'Krypt Trader');
}

ensureVenv();
run(VENV_PY, ['turbine_backtest.py', ...process.argv.slice(2)]);
