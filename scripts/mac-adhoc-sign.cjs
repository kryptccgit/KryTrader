const { execFileSync, spawnSync } = require('node:child_process');
const { readdirSync, statSync } = require('node:fs');
const { join } = require('node:path');

const CODESIGN_ARGS = ['--force', '--sign', '-', '--timestamp=none'];

function isMachO(file) {
  const out = spawnSync('file', ['--brief', file], { encoding: 'utf8' });
  return out.status === 0 && /Mach-O/.test(out.stdout || '');
}

function* walk(dir) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const e of entries) {
    const p = join(dir, e.name);
    if (e.isSymbolicLink()) continue;
    if (e.isDirectory()) yield* walk(p);
    else if (e.isFile()) yield p;
  }
}

function hasRealIdentity(context) {
  if (process.env.CSC_LINK || process.env.CSC_NAME) return true;
  if (typeof context.packager.platformSpecificBuildOptions.identity === 'string') return true;
  if (process.env.CSC_IDENTITY_AUTO_DISCOVERY === 'false') return false;
  const found = spawnSync('security', ['find-identity', '-v', '-p', 'codesigning'], {
    encoding: 'utf8',
  });
  return found.status === 0 && /Developer ID Application/.test(found.stdout || '');
}

exports.default = async function macAdhocSign(context) {
  if (context.electronPlatformName !== 'darwin') return;

  if (hasRealIdentity(context)) {
    console.log('>> mac-adhoc-sign: real signing identity available, skipping ad-hoc pass');
    return;
  }

  const appName = `${context.packager.appInfo.productFilename}.app`;
  const appPath = join(context.appOutDir, appName);
  statSync(appPath);

  const nested = [...walk(join(appPath, 'Contents', 'Resources', 'python'))].filter(isMachO);
  console.log(`>> mac-adhoc-sign: ${nested.length} nested Mach-O file(s) in Resources/python`);
  for (const f of nested) {
    execFileSync('codesign', [...CODESIGN_ARGS, f], { stdio: 'inherit' });
  }

  execFileSync('codesign', [...CODESIGN_ARGS, '--deep', appPath], { stdio: 'inherit' });

  execFileSync('codesign', ['--verify', '--strict', '--verbose=2', appPath], { stdio: 'inherit' });
  console.log(`>> mac-adhoc-sign: OK — ${appName} carries a valid ad-hoc signature`);
};
