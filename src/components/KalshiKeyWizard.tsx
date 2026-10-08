import { useMemo, useRef, useState, type CSSProperties, type DragEvent } from 'react';
import {
  ArrowRight, ExternalLink, Eye, EyeOff, FileKey2, Gift, KeyRound, Loader2, RefreshCcw,
  ShieldCheck, Upload, Wallet,
} from 'lucide-react';
import type { CredentialDiagnosis } from '@shared/types';
import { checkKalshiKeys, checkKeyId, checkPrivateKey, kindLabel } from '@shared/kalshiKeys';
import { useApp } from '../state/AppStateProvider';
import { GlassButton } from './glass/GlassButton';
import { Callout, StepFooter, StepHeader } from './SetupSteps';
import { KALSHI_API_KEYS_URL, openKalshiReferral } from '../utils/links';
import { isLive } from '../utils/account';
import { cls } from '../utils/format';
import { userMessage } from '../utils/errors';


const MAX_FILE_BYTES = 64 * 1024;

const STEPS = 4;

type Phase = 'idle' | 'saving' | 'testing' | 'ok' | 'fail';

export function KalshiKeyWizard({
  onDone, onSkip, onBackOut,
}: {
  onDone?: (verified?: { balanceUsd: number | null }) => void;
  onSkip?: () => void;
  onBackOut?: () => void;
}) {
  const { config, credentialsAll, refresh } = useApp();
  const [step, setStep] = useState(0);
  const [keyId, setKeyId] = useState('');
  const [pem, setPem] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [showPem, setShowPem] = useState(false);
  const [touchedId, setTouchedId] = useState(false);
  const [phase, setPhase] = useState<Phase>('idle');
  const [balance, setBalance] = useState<number | null>(null);
  const [diag, setDiag] = useState<CredentialDiagnosis | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedKind, setSavedKind] = useState<string>('');
  const fileInput = useRef<HTMLInputElement | null>(null);

  const idCheck = useMemo(() => checkKeyId(keyId), [keyId]);
  const pemCheck = useMemo(() => checkPrivateKey(pem), [pem]);
  const both = useMemo(() => checkKalshiKeys({ keyId, pem }), [keyId, pem]);
  const existing = credentialsAll?.production;
  const replacing = !!existing?.hasApiKey && !!existing?.hasRsaKey;
  const live = isLive(config);

  const back = (): void => {
    if (step === 0) onBackOut?.();
    else setStep((s) => s - 1);
  };

  const readFile = async (f: File | undefined | null): Promise<void> => {
    setFileError(null);
    if (!f) return;
    if (f.size > MAX_FILE_BYTES) {
      setFileError(`${f.name} is too big to be a key file. Pick the file Kalshi gave you.`);
      return;
    }
    try {
      const text = await f.text();
      setPem(text);
      setFileName(f.name);
      setShowPem(false);
    } catch {
      setFileError(`Couldn't read ${f.name}. Try pasting its contents instead.`);
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>): void => {
    e.preventDefault();
    void readFile(e.dataTransfer.files?.[0]);
  };

  const finishOk = async (usd: number): Promise<void> => {
    setBalance(usd);
    setPhase('ok');
    setKeyId('');
    setPem('');
    setFileName(null);
    await Promise.allSettled([refresh.credentials(), refresh.backend(), refresh.account()]);
  };

  const test = async (): Promise<void> => {
    setPhase('testing');
    setDiag(null);
    const t = await window.krypt.credentials.test();
    if (t.ok && t.data) {
      await finishOk(t.data.balanceUsd);
      return;
    }
    setDiag(t.diagnosis ?? { code: 'unknown', title: 'Kalshi didn\'t accept the test.', fix: t.message ?? '' });
    setPhase('fail');
    await Promise.allSettled([refresh.credentials(), refresh.backend()]);
  };

  const saveAndTest = async (): Promise<void> => {
    if (!both.ok) return;
    setStep(3);
    setSaveError(null);
    setDiag(null);
    setPhase('saving');
    setSavedKind(kindLabel(both.kind));
    try {
      const r = await window.krypt.credentials.save({ apiKey: both.keyId, rsaPem: both.pem });
      if (!r.ok) {
        setSaveError(r.message || 'Saving failed.');
        setPhase('fail');
        return;
      }
    } catch (e) {
      setSaveError(userMessage(e));
      setPhase('fail');
      return;
    }
    await test();
  };

  return (
    <div data-testid="kalshi-wizard">
      {step === 0 && (
        <>
          <StepHeader
            step={0} count={STEPS}
            title="Create an API key on Kalshi"
            subtitle="Only needed to trade Live. Paper mode works without any Kalshi account. It takes about a minute; keep that Kalshi page open until you finish here."
          />
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-white/90">
            <li>Open Kalshi&apos;s API key page on kalshi.com and log in.</li>
            <li>Under <span className="text-white">API Keys</span>, click <span className="text-white">Create New API Key</span>. Any name works.</li>
            <li>Either key type works: <span className="text-white">Ed25519</span> (Kalshi&apos;s default) or RSA.</li>
            <li>Kalshi shows a <span className="text-white">Key ID</span> and a <span className="text-white">private key</span>, and downloads the key as a file.</li>
          </ol>
          <div className="mt-3">
            <Callout tone="warn">
              Kalshi shows the private key only once. Keep the downloaded file; if you lose it, just
              create a new key.
            </Callout>
          </div>
          <div className="mt-4">
            <GlassButton
              variant="default"
              data-testid="open-kalshi-keys"
              onClick={() => void window.krypt.app.openExternal(KALSHI_API_KEYS_URL)}
            >
              <ExternalLink className="h-4 w-4" /> Open Kalshi&apos;s API key page
            </GlassButton>
            <p className="mt-1.5 text-[11px] text-krypt-dim">Opens kalshi.com in your browser.</p>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-krypt-muted">
            <span>No Kalshi account yet?</span>
            <button type="button" className="text-krypt-purple hover:underline"
              onClick={() => void openKalshiReferral()}>
              <Gift className="mr-1 inline h-3 w-3" />Sign up for Kalshi ($25 bonus after your first deposit)
              <ExternalLink className="ml-0.5 inline h-3 w-3" />
            </button>
          </div>
          <StepFooter onBack={onBackOut ? back : undefined} onSkip={onSkip}>
            <GlassButton variant="primary" onClick={() => setStep(1)} data-testid="wizard-next">
              I have my key <ArrowRight className="h-4 w-4" />
            </GlassButton>
          </StepFooter>
        </>
      )}

      {step === 1 && (
        <>
          <StepHeader
            step={1} count={STEPS}
            title="Paste the Key ID"
            subtitle="The short code Kalshi showed next to your new key. It looks like 1a2b3c4d-1a2b-1a2b-1a2b-1a2b3c4d5e6f."
          />
          <input
            data-testid="key-id-input"
            type="text"
            className="krypt-input font-mono"
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            value={keyId}
            onChange={(e) => setKeyId(e.target.value)}
            onBlur={() => setTouchedId(true)}
            autoComplete="off"
            spellCheck={false}
            autoFocus
          />
          <div className="mt-2 space-y-2">
            {keyId && idCheck.issue && (touchedId || keyId.length >= 36 || idCheck.issue.code !== 'keyid_not_uuid') && (
              <Callout tone="error" testId="key-id-issue">{idCheck.issue.message}</Callout>
            )}
            {keyId && idCheck.issue?.code === 'keyid_is_private_key' && (
              <button
                type="button" className="krypt-btn-default"
                onClick={() => { setPem(keyId); setKeyId(''); setFileName(null); }}
              >
                Use it as the private key instead
              </button>
            )}
            {!idCheck.issue && idCheck.fixes.length > 0 && (
              <Callout tone="ok">{idCheck.fixes.join(' ')}</Callout>
            )}
            {!idCheck.issue && (
              <Callout tone="ok" testId="key-id-ok">
                Looks right: <span className="font-mono">…{idCheck.value.slice(-4)}</span>
              </Callout>
            )}
          </div>
          <StepFooter onBack={back} onSkip={onSkip}>
            <GlassButton variant="primary" disabled={!!idCheck.issue} onClick={() => setStep(2)} data-testid="wizard-next">
              Continue <ArrowRight className="h-4 w-4" />
            </GlassButton>
          </StepFooter>
        </>
      )}

      {step === 2 && (
        <>
          <StepHeader
            step={2} count={STEPS}
            title="Add the private key"
            subtitle="Drop the file Kalshi downloaded, or paste what's inside it. It stays on this computer, encrypted."
          />
          <div
            data-testid="pem-drop"
            onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }}
            onDrop={onDrop}
            className={cls(
              'flex flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-5 text-center',
              pem && !pemCheck.issue ? 'border-krypt-win/50 bg-krypt-win/5' : 'border-krypt-borderHi bg-krypt-surface2',
            )}
          >
            {fileName && !pemCheck.issue ? (
              <>
                <FileKey2 className="h-6 w-6 text-krypt-win" />
                <div className="text-sm text-white">{fileName}</div>
                <div className="text-xs text-krypt-win">{kindLabel(pemCheck.kind)} private key, ready</div>
              </>
            ) : (
              <>
                <Upload className="h-6 w-6 text-krypt-muted" />
                <div className="text-sm text-white">Drop the key file here</div>
                <div className="text-xs text-krypt-muted">It&apos;s usually in Downloads, named after your key (.txt, .pem or .key).</div>
              </>
            )}
            <button type="button" className="krypt-btn-default" onClick={() => fileInput.current?.click()}>
              Choose file…
            </button>
            <input
              ref={fileInput}
              data-testid="pem-file"
              type="file"
              accept=".pem,.key,.txt,text/plain"
              className="hidden"
              onChange={(e) => { void readFile(e.target.files?.[0]); e.target.value = ''; }}
            />
          </div>

          <label className="krypt-label mt-3 flex items-center justify-between">
            <span>Or paste it</span>
            <button type="button" onClick={() => setShowPem((v) => !v)} className="text-xs text-krypt-muted hover:text-white">
              {showPem ? <><EyeOff className="mr-1 inline h-3 w-3" />hide</> : <><Eye className="mr-1 inline h-3 w-3" />show</>}
            </button>
          </label>
          <textarea
            data-testid="pem-input"
            className="krypt-input min-h-[96px] font-mono text-[11px]"
            placeholder="Paste the whole key, including its first and last lines"
            value={pem}
            onChange={(e) => { setPem(e.target.value); setFileName(null); }}
            spellCheck={false}
            style={!showPem && pem ? ({ WebkitTextSecurity: 'disc' } as CSSProperties) : undefined}
          />

          <div className="mt-2 space-y-2">
            {fileError && <Callout tone="error">{fileError}</Callout>}
            {pem && pemCheck.issue && (
              <Callout tone="error" testId="pem-issue">{pemCheck.issue.message}</Callout>
            )}
            {pem && !pemCheck.issue && pemCheck.fixes.length > 0 && (
              <Callout tone="ok">{pemCheck.fixes.join(' ')}</Callout>
            )}
            {pem && !pemCheck.issue && !fileName && (
              <Callout tone="ok" testId="pem-ok">{kindLabel(pemCheck.kind)} private key, ready.</Callout>
            )}
            {replacing && (
              <Callout tone="info">
                This replaces the Kalshi key you saved before
                (…{existing?.apiKeyPreview || '????'}).
              </Callout>
            )}
          </div>
          <StepFooter onBack={back} onSkip={onSkip}>
            <GlassButton
              variant="primary"
              disabled={!both.ok}
              onClick={() => void saveAndTest()}
              data-testid="wizard-save"
            >
              <ShieldCheck className="h-4 w-4" /> Save &amp; connect
            </GlassButton>
          </StepFooter>
        </>
      )}

      {step === 3 && (
        <>
          <StepHeader step={3} count={STEPS} title={
            phase === 'ok' ? 'Connected' : phase === 'fail' ? 'Not connected yet' : 'Connecting to Kalshi…'
          } />

          {(phase === 'saving' || phase === 'testing') && (
            <div className="flex items-center gap-3 rounded-xl border border-krypt-border bg-krypt-surface2 p-4 text-sm text-white">
              <Loader2 className="h-5 w-5 animate-spin text-krypt-purple" />
              {phase === 'saving' ? 'Saving your key (encrypted, on this computer)…' : 'Checking with Kalshi…'}
            </div>
          )}

          {phase === 'ok' && (
            <div className="space-y-3" data-testid="wizard-success">
              <div className="flex items-center gap-3 rounded-xl border border-krypt-win/40 bg-krypt-win/10 p-4">
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-krypt-win/20 text-krypt-win">
                  <Wallet className="h-5 w-5" />
                </div>
                <div>
                  <div className="text-sm font-medium text-white">
                    Connected to Kalshi · balance ${balance?.toFixed(2) ?? '—'}
                  </div>
                  <div className="text-xs text-krypt-muted">
                    {savedKind} key saved, encrypted on this computer.
                  </div>
                </div>
              </div>
              {balance !== null && balance < 25 && (
                <Callout tone="warn">
                  Fund at least $25 before you trade Live: on a smaller balance most orders
                  fall under Kalshi&apos;s $1 minimum.
                </Callout>
              )}
              {!live && (
                <Callout tone="info" title="The app is still in Paper mode." testId="wizard-still-paper">
                  Saving a key changes nothing about what trades. When you are ready for real money,
                  use <span className="text-white">Go live</span> in Settings → Account; until then every
                  order stays on paper.
                </Callout>
              )}
            </div>
          )}

          {phase === 'fail' && (
            <div className="space-y-3" data-testid="wizard-failure">
              {saveError ? (
                <Callout tone="error" title="Couldn't save the key.">{saveError}</Callout>
              ) : diag ? (
                <Callout tone="error" title={diag.title} testId="wizard-diagnosis">{diag.fix}</Callout>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {(diag?.code === 'key_not_found' || diag?.code === 'bad_key_id') && (
                  <button type="button" className="krypt-btn-default" onClick={() => { setPhase('idle'); setStep(1); }}>
                    <KeyRound className="h-4 w-4" /> Fix the Key ID
                  </button>
                )}
                {(saveError || diag?.code === 'bad_signature' || diag?.code === 'bad_key_file') && (
                  <button type="button" className="krypt-btn-default" onClick={() => { setPhase('idle'); setStep(2); }}>
                    <FileKey2 className="h-4 w-4" /> Pick the right key file
                  </button>
                )}
                {diag && ['clock_skew', 'network', 'kalshi_down', 'rate_limited', 'forbidden', 'unknown'].includes(diag.code) && (
                  <button type="button" className="krypt-btn-default" onClick={() => void test()}>
                    <RefreshCcw className="h-4 w-4" /> Test again
                  </button>
                )}
              </div>
            </div>
          )}

          <StepFooter
            onBack={phase === 'fail' ? () => { setPhase('idle'); setStep(2); } : undefined}
            onSkip={phase === 'ok' ? undefined : onSkip}
          >
            {phase === 'ok' && (
              <GlassButton variant="primary" onClick={() => onDone?.({ balanceUsd: balance ?? null })} data-testid="wizard-done">
                Done <ArrowRight className="h-4 w-4" />
              </GlassButton>
            )}
          </StepFooter>
        </>
      )}
    </div>
  );
}
