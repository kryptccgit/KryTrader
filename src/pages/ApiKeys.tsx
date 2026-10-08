import React, { useEffect, useState } from 'react';
import {
  ExternalLink, Eye, EyeOff, FlaskConical, Gift, KeyRound, RefreshCcw,
  Save, ShieldCheck, Sparkles, Trash2, Wifi, WifiOff,
} from 'lucide-react';
import type { CredentialsState, CredentialsStatusAll } from '@shared/types';
import { checkKalshiKeys } from '@shared/kalshiKeys';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Card, Modal, Page, Section, Switch } from '../components/common';
import { KalshiKeyWizard } from '../components/KalshiKeyWizard';
import { cls } from '../utils/format';
import { KALSHI_API_KEYS_URL, openKalshiReferral } from '../utils/links';
import { isLive } from '../utils/account';

export function ApiKeysPage() {
  const { backend, refresh, config, account } = useApp();
  const toast = useToast();
  const [statusAll, setStatusAll] = useState<CredentialsStatusAll | null>(null);
  const [wizard, setWizard] = useState(false);
  const [dataDir, setDataDir] = useState<string | null>(null);
  useEffect(() => {
    void window.krypt.app.getUserDataPath().then(setDataDir).catch(() => setDataDir(null));
  }, []);
  const sep = dataDir?.includes('\\') ? '\\' : '/';
  const credDir = dataDir ? `${dataDir}${sep}credentials` : null;
  const [inline, setInline] = useState<boolean | null>(null);
  useEffect(() => {
    if (statusAll && inline === null) {
      setInline(!statusAll.production.hasApiKey);
    }
  }, [statusAll, inline]);

  const reload = async (): Promise<void> => {
    try {
      const all = await window.krypt.credentials.statusAll();
      setStatusAll(all);
    } catch {
      setInline((cur) => (cur === null ? false : cur));
    }
  };

  useEffect(() => {
    void reload();
  }, [backend.authOk]);

  const live = isLive(config);

  return (
    <Page
      title="API Keys"
      subtitle={`Your Kalshi API key, for trading Live. Paper mode needs none. Stored encrypted on this computer${credDir ? ` (${credDir})` : ''} and never sent anywhere but Kalshi.`}
      actions={
        <button onClick={() => void reload()} className="krypt-btn-default" title="Re-read credential status from disk">
          <RefreshCcw className="h-4 w-4" /> Refresh
        </button>
      }
    >
      {!statusAll?.production.hasApiKey && (
        <ReferralBanner />
      )}

      {inline ? (
        <Section title="Add a Kalshi key, step by step">
          <Card>
            <KalshiKeyWizard onDone={() => { setInline(false); void reload(); }} />
          </Card>
        </Section>
      ) : (
        <div className="mb-4 flex justify-end">
          <button type="button" className="krypt-btn-default" onClick={() => setWizard(true)} data-testid="kalshi-wizard-open">
            <Sparkles className="h-4 w-4" /> Add a key step by step
          </button>
        </div>
      )}
      <Modal open={wizard} onClose={() => setWizard(false)}>
        <KalshiKeyWizard
          onDone={() => { setWizard(false); void reload(); }}
          onSkip={() => setWizard(false)}
          onBackOut={() => setWizard(false)}
        />
      </Modal>

      <Section title="Account mode">
        <Card>
          <div className="flex flex-col items-start gap-4 md:flex-row md:items-center" data-testid="apikeys-mode">
            <div className={cls(
              'grid h-10 w-10 shrink-0 place-items-center rounded-lg',
              !live ? 'bg-krypt-purple/10 text-krypt-purple'
                : backend.authOk ? 'bg-krypt-win/10 text-krypt-win' : 'bg-krypt-loss/10 text-krypt-loss',
            )}>
              {!live ? <FlaskConical className="h-5 w-5" /> : backend.authOk ? <Wifi className="h-5 w-5" /> : <WifiOff className="h-5 w-5" />}
            </div>
            <div className="flex-1">
              <div className="text-sm text-white">
                {!live ? 'Paper — nothing is signed with your key'
                  : backend.authOk ? 'Live · authenticated' : 'Live · not authenticated'}
              </div>
              <div className="mt-0.5 text-xs text-krypt-muted">
                {!live
                  ? 'Paper trades Kalshi’s real prices with imaginary money and never uses a key. A key saved here is used only once you choose Go live (Settings → Account), and by the Test button.'
                  : 'Live orders, balance and positions are signed with the key below.'}
              </div>
            </div>
          </div>
        </Card>
      </Section>

      <Section title="API access level">
        <Card>
          <div className="mb-3 flex items-center gap-3">
            <div className={cls(
              'rounded-md px-2 py-1 text-xs font-semibold uppercase tracking-wide',
              account?.apiTier && account.apiTier !== 'basic'
                ? 'bg-krypt-win/15 text-krypt-win' : 'bg-krypt-surface2 text-krypt-muted',
            )}>
              {account?.apiTier ?? '—'}
            </div>
            <div className="text-xs text-krypt-muted">
              {account?.apiTier && account.apiTier !== 'basic'
                ? 'Advanced+ — 3× order throughput. Faster stop-loss chases and multi-runner placement.'
                : 'Basic — auto-upgrades to Advanced (free, 3× order throughput) once the bot has placed one order.'}
            </div>
          </div>
          <Switch
            checked={config?.autoUpgradeApiLevel ?? true}
            onChange={(v) => void window.krypt.config.update({ autoUpgradeApiLevel: v })}
            label="Auto-upgrade to Advanced API level"
            description="Requests Kalshi's free Advanced usage tier (100→300 orders/sec) once eligible. Purely a rate-limit grant — no cost, no change to trading behavior."
          />
        </Card>
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <CredentialSlot
          title="Kalshi key"
          status={statusAll?.production}
          onSaved={async () => { await reload(); await refresh.credentials(); await refresh.backend(); }}
        />
      </div>

      <Section title="Security notes">
        <Card>
          <ul className="list-disc space-y-1.5 pl-5 text-xs text-krypt-muted">
            <li>
              The key is written to{' '}
              <span className="break-all font-mono text-white">{credDir ? `${credDir}${sep}apikey.production.txt` : 'the app\'s data folder'}</span>,
              encrypted, with user-only permissions.
            </li>
            <li>The Python backend signs requests locally (Ed25519, or RSA-PSS for an RSA key); nothing is sent to any server other than Kalshi&apos;s.</li>
            <li>In Paper mode nothing is signed with it at all — only the Test button you click.</li>
            <li>Click Delete before uninstalling if you want it gone.</li>
          </ul>
        </Card>
      </Section>
    </Page>
  );
}

function ReferralBanner() {
  return (
    <div className="mb-4 flex flex-col items-start gap-3 rounded-xl border border-krypt-purple/40 bg-gradient-to-r from-krypt-indigo/10 via-krypt-purple/10 to-krypt-pink/10 p-4 md:flex-row md:items-center">
      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-krypt-glow shadow-krypt-soft">
        <Gift className="h-5 w-5 text-white" />
      </div>
      <div className="flex-1 text-sm">
        <div className="font-medium text-white">No Kalshi account yet?</div>
        <div className="mt-0.5 text-xs text-krypt-muted">
          Sign up through our referral and Kalshi gives you{' '}
          <span className="text-white">$25 free</span> after your first deposit.
        </div>
      </div>
      <button
        onClick={() => void openKalshiReferral()}
        className="krypt-btn-primary"
      >
        <Gift className="h-4 w-4" /> Sign up + claim $25 <ExternalLink className="h-3 w-3" />
      </button>
    </div>
  );
}

interface SlotProps {
  title: string;
  status?: CredentialsState;
  onSaved: () => Promise<void>;
}

function CredentialSlot({ title, status, onSaved }: SlotProps) {
  const toast = useToast();
  const [apiKey, setApiKey] = useState('');
  const [rsaPem, setRsaPem] = useState('');
  const [showPem, setShowPem] = useState(false);
  const [busy, setBusy] = useState(false);

  const has = !!status?.hasApiKey && !!status?.hasRsaKey;
  const accentClasses = 'border-krypt-purple/30 bg-krypt-purple/5 text-krypt-purple';

  const save = async (): Promise<void> => {
    if (!apiKey.trim() && !rsaPem.trim() && has) {
      toast.error(`${title} already has keys saved. Paste new values to replace, or click Delete to remove them.`);
      return;
    }
    const chk = checkKalshiKeys({ keyId: apiKey, pem: rsaPem });
    if (!chk.ok) {
      toast.error(`${title}: ${chk.issues.map((i) => i.message).join(' ')}`);
      return;
    }
    if (chk.fixes.length) toast.info(`${title}: ${chk.fixes.join(' ')}`);
    setBusy(true);
    try {
      const r = await window.krypt.credentials.save({
        apiKey: chk.keyId, rsaPem: chk.pem,
      });
      if (!r.ok) { toast.error(r.message || 'Save failed'); return; }
      toast.success(`${title}: keys saved. Verifying…`);
      const t = await window.krypt.credentials.test();
      if (t.ok) {
        toast.success(`${title}: verified · balance $${t.data?.balanceUsd.toFixed(2)}`);
      } else {
        toast.error(t.message || 'Could not authenticate');
      }
      setApiKey('');
      setRsaPem('');
      await onSaved();
    } finally {
      setBusy(false);
    }
  };

  const test = async (): Promise<void> => {
    setBusy(true);
    try {
      const r = await window.krypt.credentials.test();
      if (r.ok) {
        toast.success(`${title}: $${r.data?.balanceUsd.toFixed(2)}`);
      } else {
        toast.error(r.message || 'Test failed');
      }
    } finally {
      setBusy(false);
    }
  };

  const clear = async (): Promise<void> => {
    if (!window.confirm(`Delete saved ${title} credentials from disk?`)) return;
    setBusy(true);
    try {
      const r = await window.krypt.credentials.clear();
      if (r.ok) { toast.success(`${title}: cleared`); await onSaved(); }
      else toast.error(r.message || 'Failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <span className={cls(
          'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
          accentClasses,
        )}>
          <KeyRound className="h-3 w-3" />
          kalshi.com
        </span>
        <div className="text-sm font-semibold text-white">{title}</div>
        <span className={cls(
          'ml-auto rounded-md px-2 py-0.5 text-[10px] uppercase tracking-wider',
          has
            ? 'border border-krypt-win/30 bg-krypt-win/10 text-krypt-win'
            : 'border border-krypt-border bg-krypt-surface2 text-krypt-muted',
        )}>
          {has ? 'configured' : 'empty'}
        </span>
      </div>

      {has && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-krypt-border bg-krypt-surface2 px-3 py-2 text-xs text-krypt-muted">
          <KeyRound className="h-3.5 w-3.5 text-krypt-win" />
          <div className="flex-1">
            <div>
              API key …<span className="font-mono text-white">{status?.apiKeyPreview || '????'}</span>
              <span className="mx-2 text-krypt-dim">·</span>
              {status?.keyType === 'ed25519' ? 'Ed25519' : 'RSA'} fp <span className="font-mono text-white">{status?.fingerprint || '—'}</span>
            </div>
            <div className="text-[10px] text-krypt-dim">
              To replace these, paste new values below and hit Save. To remove them, click Delete.
            </div>
          </div>
        </div>
      )}

      <label className="krypt-label">
        Kalshi API key (UUID)
        {has && <span className="ml-2 text-[10px] uppercase tracking-wider text-krypt-dim">(paste here to replace)</span>}
      </label>
      <input
        type="text"
        className="krypt-input font-mono"
        placeholder={has ? 'paste a new UUID to replace the saved key' : 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'}
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        autoComplete="off"
        spellCheck={false}
      />
      <p className="krypt-help">
        Generate one in your Kalshi account (Account → API keys) →{' '}
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            void window.krypt.app.openExternal(KALSHI_API_KEYS_URL);
          }}
          className="text-krypt-purple hover:underline"
        >
          open kalshi.com
          <ExternalLink className="ml-0.5 inline h-3 w-3" />
        </a>
      </p>

      <label className="krypt-label mt-3 flex items-center justify-between">
        Private key (the file Kalshi gave you)
        <button
          type="button"
          onClick={() => setShowPem((v) => !v)}
          className="text-xs text-krypt-muted hover:text-white"
        >
          {showPem ? <><EyeOff className="mr-1 inline h-3 w-3" />hide</> : <><Eye className="mr-1 inline h-3 w-3" />show</>}
        </button>
      </label>
      <textarea
        className="krypt-input min-h-[140px] font-mono text-[11px]"
        placeholder="Paste the whole key, including its BEGIN and END lines"
        value={rsaPem}
        onChange={(e) => setRsaPem(e.target.value)}
        spellCheck={false}
        style={
          !showPem && rsaPem
            ? ({ WebkitTextSecurity: 'disc' } as React.CSSProperties)
            : undefined
        }
      />
      <p className="krypt-help">Ed25519 (Kalshi&apos;s default) or RSA, without a password.</p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button onClick={save} disabled={busy} className="krypt-btn-primary">
          <Save className="h-4 w-4" /> Save &amp; verify
        </button>
        <button onClick={test} disabled={busy || !has} className="krypt-btn-default">
          <ShieldCheck className="h-4 w-4" /> Test
        </button>
        {has && (
          <button onClick={clear} disabled={busy} className="krypt-btn-danger ml-auto">
            <Trash2 className="h-4 w-4" /> Delete
          </button>
        )}
      </div>
    </Card>
  );
}
