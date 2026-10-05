import { ensureVenv } from './python-utils.mjs';

try {
  ensureVenv();
  console.log('>> Python backend ready.');
} catch (e) {
  console.error('!! Python setup failed:', e.message);
  console.error(
    'You can still run the app in renderer-only mode; the trading backend\n' +
    '   will not start until Python is available.',
  );
  process.exit(0);
}
