import { spawnSync } from 'node:child_process';
import { existsSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { ensureVenv, run, VENV_PY, PY_DIR } from './python-utils.mjs';

ensureVenv();

console.log('>> Installing PyInstaller');
run(VENV_PY, ['-m', 'pip', 'install', 'pyinstaller>=6.6,<7', '--disable-pip-version-check']);

console.log('>> Cleaning previous build');
for (const d of ['build', 'dist']) {
  const p = join(PY_DIR, d);
  if (existsSync(p)) {
    rmSync(p, { recursive: true, force: true });
  }
}

console.log('>> Running PyInstaller (this takes ~60s)');
run(VENV_PY, [
  '-m', 'PyInstaller',
  '--noconfirm',
  '--name', 'krypt-trader-backend',
  '--console',
  '--hidden-import', 'db',
  '--hidden-import', 'scanner',
  '--hidden-import', 'trader',
  '--hidden-import', 'kalshi_api',
  '--hidden-import', 'kalshi_auth',
  '--hidden-import', 'categorize',
  '--hidden-import', 'config',
  '--hidden-import', 'webhook',
  '--hidden-import', 'kalshi_ws',
  '--hidden-import', 'crypto15m',
  '--hidden-import', 'crypto15m_trader',
  '--hidden-import', 'crypto15m_record',
  '--hidden-import', 'backtest',
  '--hidden-import', 'spot_ws',
  '--hidden-import', 'cf_ws',
  '--hidden-import', 'indicators',
  '--hidden-import', 'replay',
  '--hidden-import', 'capturetrail',
  '--hidden-import', 'rules',
  '--hidden-import', 'turbine_import',
  '--hidden-import', 'turbine_backtest',
  '--hidden-import', 'crypto15m_backfill',
  '--hidden-import', 'coin_optimizer',
  '--hidden-import', 'strategy_generator',
  '--hidden-import', 'script_sandbox',
  '--hidden-import', 'script_engine',
  '--hidden-import', 'script_backtest',
  '--hidden-import', 'script_docs',
  '--hidden-import', 'statistics',
  '--add-data', `turbine_strategies.json${process.platform === 'win32' ? ';' : ':'}.`,
  '--hidden-import', 'terminal',
  '--hidden-import', 'crossvenue',
  '--hidden-import', 'polymarket_public',
  '--hidden-import', 'remote',
  '--hidden-import', 'remote_discord',
  '--hidden-import', 'remote_telegram',
  '--hidden-import', 'mcp_server',
  '--hidden-import', 'mcp_bridge',
  '--hidden-import', 'mcp_workbench',
  '--hidden-import', 'mcp_agents',
  '--hidden-import', 'autopilot',
  '--hidden-import', 'health',
  '--hidden-import', 'kalshi_key_check',
  '--hidden-import', 'forecast_ledger',
  '--hidden-import', 'paper_book',
  '--hidden-import', 'paper_exchange',
  '--hidden-import', 'shard_rail',
  '--hidden-import', 'logscrub',
  '--hidden-import', 'kalshi_perps_api',
  '--hidden-import', 'perps_ws',
  '--hidden-import', 'perps_farmer',
  '--hidden-import', 'ai_analyst',
  '--hidden-import', 'ai_providers',
  '--collect-submodules', 'anthropic',
  '--collect-submodules', 'openai',
  '--collect-submodules', 'httpx2',
  '--collect-submodules', 'httpcore2',
  '--collect-submodules', 'truststore',
  '--hidden-import', 'ws_ssl',
  '--hidden-import', 'certifi',
  '--collect-data', 'certifi',
  '--collect-submodules', 'cryptography',
  '--collect-submodules', 'httpx',
  '--collect-submodules', 'websockets',
  'service.py',
]);

const out = join(PY_DIR, 'dist', 'krypt-trader-backend');
if (!existsSync(out)) {
  console.error('!! PyInstaller did not produce', out);
  process.exit(1);
}
const exe = join(out, process.platform === 'win32'
  ? 'krypt-trader-backend.exe'
  : 'krypt-trader-backend');
console.log('>> Selftest: verifying the frozen bundle imports + has CA roots');
const st = spawnSync(exe, ['--selftest'], { stdio: 'inherit', windowsHide: true });
if (st.error) {
  console.error(`!! Could not run the frozen backend selftest: ${st.error.message}`);
  process.exit(1);
}
if (st.status !== 0) {
  console.error(
    '!! Frozen backend FAILED selftest (report above) -- refusing to ship it.\n' +
    '!! Check that the build venv has all of python/requirements.txt and that\n' +
    '!! scripts/build-python.mjs collects the failing module/data, then rebuild.\n' +
    '!! Aborting before electron-builder.',
  );
  process.exit(1);
}

console.log('>> OK — backend bundled + selftest PASSED at python/dist/krypt-trader-backend');
