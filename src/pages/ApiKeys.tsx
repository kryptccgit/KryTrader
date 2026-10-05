import React, { useEffect, useState } from 'react';
import {
  ArrowLeftRight, ExternalLink, Eye, EyeOff, Gift, KeyRound, RefreshCcw,
  Save, ShieldCheck, Trash2, Wifi, WifiOff,
} from 'lucide-react';
import type { CredentialsState, CredentialsStatusAll, KalshiEnv } from '@shared/types';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Card, Page, Section, Switch } from '../components/common';
import { cls } from '../utils/format';
import { openKalshiReferral } from '../utils/links';

const ENV_LABEL: Record<KalshiEnv, string> = {
  demo: 'Demo',
  production: 'Live',
};

const ENV_PROFILE_URL: Record<KalshiEnv, string> = {
  demo: 'https://demo.kalshi.co/account/profile',
  production: 'https://kalshi.com/account/profile',
};

export function ApiKeysPage() {
  const { backend, refresh, config, account } = useApp();
  const toast = useToast();
  const [statusAll, setStatusAll] = useState<CredentialsStatusAll | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = async (): Promise<void> => {
    try {
      const all = await window.krypt.credentials.statusAll();
      setStatusAll(all);
    } catch {   }
  };

  useEffect(() => {
    void reload();
  }, [backend.authOk]);

  const switchEnv = async (env: KalshiEnv): Promise<void> => {
    if (config?.kalshiEnv === env) return;
    if (env === 'production' && !window.confirm(
      config?.enableTrading
        ? 'Switch active session to PRODUCTION (real money)?\n\nAuto-trading is ON — the bot may place REAL-money orders right away.'
        : 'Switch active session to PRODUCTION (real money)?\n\nThis environment trades real funds.',
    )) return;
    setBusy(true);
    try {
      await window.krypt.config.update({ kalshiEnv: env });
      toast.success(`Switched active session to ${ENV_LABEL[env]}`);
      await refresh.credentials();
      await refresh.account();
      await refresh.backend();
      await reload();
    } catch (e: any) {
      toast.error(`Switch failed: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  const activeEnv: KalshiEnv = (config?.kalshiEnv as KalshiEnv) ?? 'demo';

  return (
    <Page
      title="API Keys"
      subtitle="Save Kalshi credentials for both Demo and Live accounts. Stored locally under %APPDATA%/Krypt Trader/credentials and never sent off-machine."
      actions={
        <button onClick={() => void reload()} className="krypt-btn-default" title="Re-read credential status from disk">
          <RefreshCcw className="h-4 w-4" /> Refresh
        </button>
      }
    >
      {!statusAll?.demo.hasApiKey && !statusAll?.production.hasApiKey && (
        <ReferralBanner />
      )}

      <Section title="Active session">
        <Card>
          <div className="flex flex-col items-start gap-4 md:flex-row md:items-center">
            <div className={cls(
              'grid h-10 w-10 shrink-0 place-items-center rounded-lg',
              backend.authOk ? 'bg-krypt-win/10 text-krypt-win' : 'bg-krypt-loss/10 text-krypt-loss',
            )}>
              {backend.authOk ? <Wifi className="h-5 w-5" /> : <WifiOff className="h-5 w-5" />}
            </div>
            <div className="flex-1">
              <div className="text-sm text-white">
                {backend.authOk
                  ? `Authenticated · ${ENV_LABEL[activeEnv]}`
                  : 'Not authenticated'}
              </div>
              <div className="mt-0.5 text-xs text-krypt-muted">
                The bot signs all requests using the active session's keys.
                Switch envs with one click — both keypairs stay saved.
              </div>
            </div>
            <div className="inline-flex shrink-0 rounded-md border border-krypt-border bg-krypt-surface2 p-0.5">
              {(['demo', 'production'] as KalshiEnv[]).map((e) => {
                const active = activeEnv === e;
                const has = statusAll?.[e]?.hasApiKey && statusAll?.[e]?.hasRsaKey;
                return (
                  <button
                    key={e}
                    onClick={() => void switchEnv(e)}
                    disabled={busy}
                    className={cls(
                      'flex items-center gap-1.5 rounded-[6px] px-3 py-1.5 text-xs font-medium uppercase tracking-wider transition-colors',
                      active
                        ? e === 'production'
                          ? 'bg-krypt-loss/15 text-krypt-loss'
                          : 'bg-krypt-warn/15 text-krypt-warn'
                        : 'text-krypt-muted hover:text-white',
                    )}
                    title={has ? `Switch to ${ENV_LABEL[e]}` : `${ENV_LABEL[e]} keys not saved yet`}
                  >
                    {ENV_LABEL[e]}
                    {!has && <span className="text-[10px] opacity-60">(empty)</span>}
                    {active && <ArrowLeftRight className="h-3 w-3 opacity-60" />}
                  </button>
                );
              })}
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
          env="demo"
          title="Demo session"
          accent="warn"
          status={statusAll?.demo}
          onSaved={async () => { await reload(); await refresh.credentials(); await refresh.backend(); }}
        />
        <CredentialSlot
          env="production"
          title="Live session"
          accent="loss"
          status={statusAll?.production}
          onSaved={async () => { await reload(); await refresh.credentials(); await refresh.backend(); }}
        />
      </div>

      <Section title="Security notes">
        <Card>
          <ul className="list-disc space-y-1.5 pl-5 text-xs text-krypt-muted">
            <li>Keys are written per-env to <span className="font-mono text-white">%APPDATA%/Krypt Trader/credentials/apikey.&lt;env&gt;.txt</span> with default user-only permissions.</li>
            <li>The Python backend signs requests locally with RSA-PSS; nothing is sent to any server other than Kalshi&apos;s.</li>
            <li>You can save Demo and Live credentials at the same time and flip between them with the Active session toggle.</li>
            <li>Click &quot;Delete saved keys&quot; on a slot before uninstalling if you want them gone.</li>
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
  env: KalshiEnv;
  title: string;
  accent: 'warn' | 'loss';
  status?: CredentialsState;
  onSaved: () => Promise<void>;
}

function CredentialSlot({ env, title, accent, status, onSaved }: SlotProps) {
  const toast = useToast();
  const [apiKey, setApiKey] = useState('');
  const [rsaPem, setRsaPem] = useState('');
  const [showPem, setShowPem] = useState(false);
  const [busy, setBusy] = useState(false);

  const has = !!status?.hasApiKey && !!status?.hasRsaKey;
  const accentClasses =
    accent === 'loss'
      ? 'border-krypt-loss/30 bg-krypt-loss/5 text-krypt-loss'
      : 'border-krypt-warn/30 bg-krypt-warn/5 text-krypt-warn';

  const save = async (): Promise<void> => {
    if (!apiKey.trim() && !rsaPem.trim() && has) {
      toast.error(`${title} already has keys saved. Paste new values to replace, or click Delete to remove them.`);
      return;
    }
    if (!apiKey.trim()) { toast.error(`${title}: paste your Kalshi API key (UUID) above`); return; }
    if (!rsaPem.trim() || !rsaPem.includes('-----BEGIN')) {
      toast.error(`${title}: paste your RSA private key (PEM) above`); return;
    }
    setBusy(true);
    try {
      const r = await window.krypt.credentials.save({
        apiKey: apiKey.trim(), rsaPem, env,
      });
      if (!r.ok) { toast.error(r.message || 'Save failed'); return; }
      toast.success(`${title}: keys saved. Verifying…`);
      const t = await window.krypt.credentials.test(env);
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
      const r = await window.krypt.credentials.test(env);
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
      const r = await window.krypt.credentials.clear(env);
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
          {ENV_LABEL[env]}
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
              RSA fp <span className="font-mono text-white">{status?.fingerprint || '—'}</span>
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
        Generate one in your Kalshi {ENV_LABEL[env]} account →{' '}
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            void window.krypt.app.openExternal(ENV_PROFILE_URL[env]);
          }}
          className="text-krypt-purple hover:underline"
        >
          open {env === 'production' ? 'kalshi.com' : 'demo.kalshi.co'}
          <ExternalLink className="ml-0.5 inline h-3 w-3" />
        </a>
      </p>

      <label className="krypt-label mt-3 flex items-center justify-between">
        RSA private key (PEM)
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
        placeholder={'-----BEGIN RSA PRIVATE KEY-----\n…\n-----END RSA PRIVATE KEY-----'}
        value={rsaPem}
        onChange={(e) => setRsaPem(e.target.value)}
        spellCheck={false}
        style={
          !showPem && rsaPem
            ? ({ WebkitTextSecurity: 'disc' } as React.CSSProperties)
            : undefined
        }
      />
      <p className="krypt-help">PKCS#1 or PKCS#8, password-less.</p>

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
