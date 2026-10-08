import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, BookOpen, Bot, CheckCircle2, ClipboardCopy, Code2, FileDown,
  FlaskConical, Play, Plus, ShieldAlert, ShieldCheck, Trash2, X,
} from 'lucide-react';
import type { ScriptApiDocs, ScriptBacktest, TraderConfig, UserScript } from '@shared/types';
import { Page, Card } from '../components/common';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { cls, fmtUsd } from '../utils/format';
import { backtestEvent, publishActivity } from '../state/activity';
import { userMessage } from '../utils/errors';

const ScriptEditor = lazy(() =>
  import('../components/ScriptEditor').then((m) => ({ default: m.ScriptEditor })));

const NEW_SCRIPT_TEMPLATE = `# krypt-script v1
# name: My Strategy
# description: Describe what this strategy does.

def decide(ctx):
    ml = ctx["minsLeft"]
    if ml is None or ml > 3.0:
        return None
    fav = ctx["favorite"]
    if fav not in ("up", "down"):
        return None
    ask = ctx["upAsk"] if fav == "up" else ctx["downAsk"]
    if ask is None:
        return None  # no real order book this tick - never trade a phantom quote
    if 0.80 <= ask <= 0.95:
        return {"side": fav, "price": "ask", "reason": "late favorite"}
    return None
`;

const BT_WINDOWS = [7, 14, 30, 60];

type PanelTab = 'backtest' | 'log' | 'docs' | 'ai';

export function ScriptsPage() {
  const { config } = useApp();
  const toast = useToast();
  const [scripts, setScripts] = useState<UserScript[]>([]);
  const [selId, setSelId] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [dirty, setDirty] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<PanelTab>('backtest');
  const [btDays, setBtDays] = useState(30);
  const [btRes, setBtRes] = useState<ScriptBacktest | null>(null);
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [trustModal, setTrustModal] = useState(false);
  const [packText, setPackText] = useState<string | null>(null);
  const [showPack, setShowPack] = useState(false);
  const [docs, setDocs] = useState<ScriptApiDocs | null>(null);
  const [pasteText, setPasteText] = useState('');
  const codeRef = useRef(code);
  codeRef.current = code;

  const sel = useMemo(
    () => scripts.find((s) => s.id === selId) ?? null,
    [scripts, selId],
  );

  const refresh = async (keepSel = true) => {
    try {
      const r = await window.krypt.scripts.list();
      setScripts(r.scripts);
      if (!keepSel || !r.scripts.some((s) => s.id === selId)) {
        setSelId(r.scripts[0]?.id ?? null);
      }
    } catch {
    }
  };

  useEffect(() => { void refresh(false); }, []);

  useEffect(() => {
    const offStatus = window.krypt.scripts.onStatus((d) => {
      setScripts((cur) => cur.map((s) => (
        s.id === d.id ? { ...s, enabled: d.enabled, lastError: d.lastError ?? s.lastError } : s
      )));
      if (!d.enabled && d.lastError) toast.warn(`Script disabled: ${d.lastError.slice(0, 140)}`);
    });
    const offLog = window.krypt.scripts.onLog((d) => {
      setLogs((cur) => {
        const next = [...(cur[d.id] ?? []), ...d.lines].slice(-200);
        return { ...cur, [d.id]: next };
      });
    });
    return () => { offStatus(); offLog(); };
  }, [toast]);

  useEffect(() => {
    if (sel) {
      setCode(sel.code);
      setDirty(false);
      setErrors([]);
      setWarnings([]);
      setBtRes(null);
      setConfirmDelete(false);
    }
  }, [selId]);

  const save = async (): Promise<UserScript | null> => {
    if (!sel) return null;
    setBusy('save');
    try {
      const r = await window.krypt.scripts.save({ id: sel.id, code: codeRef.current });
      publishActivity(() => ({
        kind: 'script', op: 'saved', name: r.script?.name ?? sel.name, id: sel.id,
        ok: r.errors.length === 0, errors: r.errors.length, detail: null,
      }));
      setErrors(r.errors);
      setWarnings(r.warnings);
      setDirty(false);
      await refresh();
      if (r.errors.length) toast.warn('Saved, but the script does not validate — it was disabled.');
      else toast.success('Script saved.');
      return r.script;
    } catch (e: any) {
      toast.error(userMessage(e));
      return null;
    } finally {
      setBusy(null);
    }
  };

  const createScript = async (initialCode: string, name?: string) => {
    setBusy('create');
    try {
      const r = await window.krypt.scripts.save({ code: initialCode, name });
      publishActivity(() => ({
        kind: 'script', op: 'created', name: r.script?.name ?? name ?? null, id: r.script?.id ?? null,
        ok: r.errors.length === 0, errors: r.errors.length, detail: null,
      }));
      await refresh(false);
      setSelId(r.script.id);
      setErrors(r.errors);
      setWarnings(r.warnings);
      if (r.errors.length) toast.warn('Imported with validation errors — fix before enabling.');
    } catch (e: any) {
      toast.error(userMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const validate = async () => {
    setBusy('validate');
    try {
      const r = await window.krypt.scripts.validate(codeRef.current, sel?.trusted);
      publishActivity(() => ({
        kind: 'script', op: 'validated', name: r.name || sel?.name || null, id: sel?.id ?? null,
        ok: r.ok, errors: r.errors.length, detail: null,
      }));
      setErrors(r.errors);
      setWarnings(r.warnings);
      if (r.ok) toast.success('Script is valid.');
    } catch (e: any) {
      toast.error(userMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const runBacktest = async () => {
    if (!sel) return;
    setBusy('backtest');
    setTab('backtest');
    try {
      if (dirty) await save();
      const r = await window.krypt.scripts.backtest({ id: sel.id, sinceDays: btDays });
      setBtRes(r);
      publishActivity(() => backtestEvent('script', sel.name, btDays, r));
      if (!r) toast.error('Engine not running — start the backend first.');
    } catch (e: any) {
      toast.error(userMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const setEnabled = async (s: UserScript, enabled: boolean) => {
    try {
      const r = await window.krypt.scripts.setEnabled(s.id, enabled);
      publishActivity(() => ({
        kind: 'script', op: r.script.enabled ? 'enabled' : 'disabled', name: r.script.name, id: s.id,
        ok: r.script.enabled === enabled, errors: null, detail: null,
      }));
      setScripts((cur) => cur.map((x) => (x.id === s.id ? r.script : x)));
      if (enabled && !config?.scriptsLiveEnabled) {
        toast.info('Script enabled — flip the master "Scripts live" switch to let it trade.');
      }
    } catch (e: any) {
      toast.error(userMessage(e));
    }
  };

  const applyTrusted = async (trusted: boolean) => {
    if (!sel) return;
    try {
      const r = await window.krypt.scripts.setTrusted(sel.id, trusted);
      setScripts((cur) => cur.map((x) => (x.id === sel.id ? r.script : x)));
      setTrustModal(false);
      toast.info(trusted
        ? 'Trusted mode ON. The script was disabled — re-enable it consciously.'
        : 'Back to sandboxed mode.');
    } catch (e: any) {
      toast.error(userMessage(e));
    }
  };

  const doDelete = async () => {
    if (!sel) return;
    try {
      await window.krypt.scripts.delete(sel.id);
      setConfirmDelete(false);
      await refresh(false);
      toast.success('Script deleted.');
    } catch (e: any) {
      toast.error(userMessage(e));
    }
  };

  const openPack = async () => {
    setShowPack(true);
    if (!packText) {
      try {
        const r = await window.krypt.scripts.contextPack();
        setPackText(r.text);
      } catch (e: any) {
        toast.error(userMessage(e));
      }
    }
  };

  const copyPack = async () => {
    if (!packText) return;
    await navigator.clipboard.writeText(packText);
    toast.success('Context pack copied — paste it into any AI chat.');
  };

  const importPaste = async () => {
    const m = pasteText.match(/```(?:python)?\s*([\s\S]*?)```/);
    const extracted = (m ? m[1] : pasteText).trim();
    if (!extracted) return;
    await createScript(extracted + '\n');
    setPasteText('');
    setShowPack(false);
    setTab('backtest');
  };

  const selLogs = sel ? (logs[sel.id] ?? []) : [];

  return (
    <Page
      title="Scripts"
      subtitle="Write (or AI-generate) your own strategies, backtest them on your recorded data, then let them trade under hard safety rails."
      actions={(
        <>
          <button onClick={() => void openPack()} className="krypt-btn-default inline-flex items-center gap-2">
            <Bot className="h-4 w-4" /> AI Context Pack
          </button>
          <button
            onClick={() => void createScript(NEW_SCRIPT_TEMPLATE)}
            className="krypt-btn-primary inline-flex items-center gap-2"
          >
            <Plus className="h-4 w-4" /> New script
          </button>
        </>
      )}
    >
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <div className="flex items-center gap-3">
            <Toggle
              checked={!!config?.scriptsLiveEnabled}
              onChange={(v) => {
                if (v && !config?.scriptsPaperMode && config?.accountMode === 'live' && !window.confirm(
                  'Arm scripts? Every ENABLED script will start placing REAL orders on your '
                  + 'Kalshi account (turn on Paper mode first to simulate instead).',
                )) return;
                void window.krypt.config.update({ scriptsLiveEnabled: v });
              }}
            />
            <div>
              <div className="text-sm font-semibold text-white">Scripts live</div>
              <div className="text-[11px] text-krypt-dim">
                Master switch — off = no script places orders; on = enabled scripts place real orders (unless Paper mode)
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Toggle
              checked={!!config?.scriptsPaperMode}
              onChange={(v) => {
                if (!v && !confirmLeavePaperMode(config)) return;
                void window.krypt.config.update({ scriptsPaperMode: v });
              }}
            />
            <div>
              <div className="text-sm font-semibold text-white">Paper mode</div>
              <div className="text-[11px] text-krypt-dim">Simulate entries against live quotes — no real orders</div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-[11px] text-krypt-muted">
            <Rail label="Max entry" suffix="¢" value={config?.scriptMaxEntryCents ?? 97} onCommit={(v) => void window.krypt.config.update({ scriptMaxEntryCents: v })} />
            <Rail label="Max size" suffix=" lots" value={config?.scriptMaxContracts ?? 20} onCommit={(v) => void window.krypt.config.update({ scriptMaxContracts: v })} />
            <Rail label="Max open/script" value={config?.scriptMaxOpen ?? 2} onCommit={(v) => void window.krypt.config.update({ scriptMaxOpen: v })} />
            <Rail label="Daily loss stop $" value={config?.scriptDailyLossUsd ?? 25} onCommit={(v) => void window.krypt.config.update({ scriptDailyLossUsd: v })} />
            <span className="text-krypt-dim">(rails apply to every script — trusted included)</span>
          </div>
        </div>
      </Card>

      <div className="flex min-h-[560px] gap-4">
        <div className="w-64 shrink-0 space-y-2">
          {scripts.length === 0 && (
            <div className="rounded-xl border border-dashed border-krypt-border p-4 text-xs leading-relaxed text-krypt-dim">
              No scripts yet. Create one, or open the <b className="text-white">AI Context Pack</b>,
              paste it into ChatGPT/Claude/any AI, describe a strategy, and paste the result back.
            </div>
          )}
          {scripts.map((s) => (
            <button
              key={s.id}
              onClick={() => setSelId(s.id)}
              className={cls(
                'w-full rounded-xl border p-3 text-left transition-colors',
                s.id === selId
                  ? 'border-krypt-purple/60 bg-krypt-purple/10'
                  : 'border-krypt-border bg-krypt-surface hover:border-krypt-purple/30',
              )}
            >
              <div className="flex items-center gap-2">
                <Code2 className="h-3.5 w-3.5 shrink-0 text-krypt-purple" />
                <span className="truncate text-sm text-white">{s.name}</span>
                {s.trusted && <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-krypt-warn" />}
                {s.lastError && <span className="ml-auto h-2 w-2 shrink-0 rounded-full bg-krypt-loss shadow-[0_0_6px_currentColor]" />}
              </div>
              <div className="mt-1 flex items-center justify-between text-[11px]">
                <span className={s.enabled ? 'text-krypt-win' : 'text-krypt-dim'}>
                  {s.enabled ? 'ENABLED' : 'off'}
                </span>
                {s.stats && (
                  <span className="font-mono text-krypt-dim">
                    {s.stats.wins}W/{s.stats.losses}L{' '}
                    <span className={s.stats.pnlUsd >= 0 ? 'text-krypt-win' : 'text-krypt-loss'}>
                      {fmtUsd(s.stats.pnlUsd, { sign: true })}
                    </span>
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {sel ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <div className="mr-auto min-w-0">
                  <div className="truncate text-sm font-semibold text-white">
                    {sel.name}{dirty && <span className="text-krypt-warn"> •</span>}
                  </div>
                  {sel.description && (
                    <div className="truncate text-[11px] text-krypt-dim">{sel.description}</div>
                  )}
                </div>
                <label className="flex items-center gap-1.5 text-[11px] text-krypt-muted">
                  <Toggle checked={sel.enabled} onChange={(v) => void setEnabled(sel, v)} />
                  Enabled
                </label>
                <button
                  onClick={() => (sel.trusted ? void applyTrusted(false) : setTrustModal(true))}
                  className={cls(
                    'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs transition-colors',
                    sel.trusted
                      ? 'border-krypt-warn/50 bg-krypt-warn/10 text-krypt-warn'
                      : 'border-krypt-border text-krypt-muted hover:text-white',
                  )}
                  title={sel.trusted ? 'Full Python — click to return to the sandbox' : 'Sandboxed — click to unlock full Python (dangerous)'}
                >
                  {sel.trusted ? <ShieldAlert className="h-3.5 w-3.5" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                  {sel.trusted ? 'Trusted' : 'Sandboxed'}
                </button>
                <button onClick={() => void validate()} disabled={busy !== null} className="krypt-btn-default text-xs">
                  Validate
                </button>
                <button onClick={() => void save()} disabled={busy !== null || !dirty} className="krypt-btn-primary text-xs">
                  {busy === 'save' ? 'Saving…' : 'Save'}
                </button>
                {confirmDelete ? (
                  <button onClick={() => void doDelete()} className="inline-flex items-center gap-1 rounded-md border border-krypt-loss/60 bg-krypt-loss/10 px-2.5 py-1.5 text-xs text-krypt-loss">
                    <Trash2 className="h-3.5 w-3.5" /> Confirm delete
                  </button>
                ) : (
                  <button onClick={() => setConfirmDelete(true)} className="rounded-md border border-krypt-border p-1.5 text-krypt-dim hover:text-krypt-loss" title="Delete script">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              {sel.lastError && (
                <div className="flex items-start gap-2 rounded-lg border border-krypt-loss/40 bg-krypt-loss/10 px-3 py-2 text-[11px] text-krypt-loss">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 break-words">Last error: {sel.lastError}</span>
                </div>
              )}
              {errors.map((e, i) => (
                <div key={i} className="rounded-lg border border-krypt-loss/40 bg-krypt-loss/10 px-3 py-1.5 text-[11px] text-krypt-loss">{e}</div>
              ))}
              {warnings.map((w, i) => (
                <div key={i} className="rounded-lg border border-krypt-warn/40 bg-krypt-warn/10 px-3 py-1.5 text-[11px] text-krypt-warn">{w}</div>
              ))}

              <div className="h-[340px]">
                <Suspense fallback={<div className="grid h-full place-items-center text-xs text-krypt-dim">Loading editor…</div>}>
                  <ScriptEditor
                    value={code}
                    onChange={(c) => { setCode(c); setDirty(true); }}
                  />
                </Suspense>
              </div>

              <div className="flex items-center gap-1.5">
                {(['backtest', 'log', 'docs', 'ai'] as PanelTab[]).map((t) => (
                  <button
                    key={t}
                    onClick={() => {
                      if (t === 'ai') { void openPack(); return; }
                      setTab(t);
                      if (t === 'docs' && !docs) {
                        window.krypt.scripts.docs().then(setDocs).catch(() => {});
                      }
                    }}
                    className={cls(
                      'rounded-md px-3 py-1.5 text-xs transition-colors',
                      tab === t ? 'bg-white/[0.08] text-white' : 'text-krypt-muted hover:text-white',
                    )}
                  >
                    {t === 'backtest' ? 'Backtest'
                      : t === 'log' ? `Script log${selLogs.length ? ` (${selLogs.length})` : ''}`
                        : t === 'docs' ? 'API Reference' : 'AI Context Pack'}
                  </button>
                ))}
                {tab === 'backtest' && (
                  <div className="ml-auto flex items-center gap-1.5">
                    {BT_WINDOWS.map((d) => (
                      <button
                        key={d}
                        onClick={() => setBtDays(d)}
                        className={cls(
                          'rounded px-2 py-1 text-[11px]',
                          btDays === d ? 'bg-krypt-purple/20 text-krypt-purple' : 'text-krypt-dim hover:text-white',
                        )}
                      >
                        {d}d
                      </button>
                    ))}
                    <button
                      onClick={() => void runBacktest()}
                      disabled={busy !== null}
                      className="inline-flex items-center gap-1.5 rounded-md border border-krypt-purple/40 bg-krypt-purple/10 px-3 py-1.5 text-xs text-krypt-purple hover:bg-krypt-purple/20 disabled:opacity-50"
                    >
                      <FlaskConical className="h-3.5 w-3.5" />
                      {busy === 'backtest' ? 'Replaying…' : 'Run backtest'}
                    </button>
                  </div>
                )}
              </div>

              {tab === 'backtest' && <BacktestResult res={btRes} busy={busy === 'backtest'} />}
              {tab === 'docs' && <DocsPanel docs={docs} />}
              {tab === 'log' && (
                <div className="max-h-56 overflow-y-auto rounded-lg border border-krypt-border bg-krypt-void/50 p-3 font-mono text-[11px] leading-relaxed text-krypt-muted">
                  {selLogs.length === 0
                    ? <span className="text-krypt-dim">No log lines yet — call log("…") in your script; lines appear here while it runs live.</span>
                    : selLogs.map((l, i) => <div key={i}>{l}</div>)}
                </div>
              )}
            </>
          ) : (
            <div className="grid flex-1 place-items-center rounded-xl border border-dashed border-krypt-border text-sm text-krypt-dim">
              Select or create a script
            </div>
          )}
        </div>
      </div>

      {trustModal && sel && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onMouseDown={() => setTrustModal(false)}>
          <div className="w-full max-w-md rounded-xl border border-krypt-warn/50 bg-krypt-surface p-5" onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 text-krypt-warn">
              <ShieldAlert className="h-5 w-5" />
              <h3 className="text-sm font-semibold">Unlock full Python for “{sel.name}”?</h3>
            </div>
            <div className="mt-3 space-y-2 text-xs leading-relaxed text-krypt-muted">
              <p>
                Trusted mode removes the sandbox <b className="text-white">entirely</b>. The script can then
                import anything, touch your files and network, and it runs inside the same process
                that holds your <b className="text-krypt-warn">decrypted Kalshi API key</b>. A malicious or
                AI-hallucinated script could place arbitrary orders or damage your system.
              </p>
              <p>
                The sandbox itself is a guardrail, not a guarantee — but trusted mode is
                <b className="text-white"> zero</b> guardrails. Only flip this for code you wrote or fully
                read and understood. Money rails (price/size/daily-loss caps) still apply.
              </p>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setTrustModal(false)} className="krypt-btn-default">Cancel</button>
              <button
                onClick={() => void applyTrusted(true)}
                className="rounded-md border border-krypt-warn/60 bg-krypt-warn/15 px-3 py-1.5 text-xs font-semibold text-krypt-warn"
              >
                I understand the risk — unlock
              </button>
            </div>
          </div>
        </div>
      )}

      {showPack && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4" onMouseDown={() => setShowPack(false)}>
          <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl border border-krypt-border bg-krypt-surface p-5" onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Bot className="h-4 w-4 text-krypt-purple" />
                <h3 className="text-sm font-semibold text-white">AI Context Pack</h3>
              </div>
              <button onClick={() => setShowPack(false)} className="text-krypt-dim hover:text-white"><X className="h-4 w-4" /></button>
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-krypt-dim">
              1. Copy the pack. 2. Paste it into <b className="text-white">any</b> AI chat (ChatGPT, Claude, Gemini…)
              and describe the strategy you want. 3. Paste the AI's reply below — the script is imported,
              validated, and ready to backtest. It includes your live script API, field docs, safety rails,
              and your actual recorded-data inventory.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={() => void copyPack()}
                disabled={!packText}
                className="krypt-btn-primary inline-flex items-center gap-2 text-xs disabled:opacity-50"
              >
                <ClipboardCopy className="h-3.5 w-3.5" />
                {packText ? 'Copy context pack' : 'Generating…'}
              </button>
              <button
                onClick={() => {
                  void window.krypt.scripts.exportPack().then((r) => {
                    if (r.ok) toast.success('Saved — the file window should pop up.');
                    else if (r.message !== 'canceled') toast.error(r.message || 'Export failed');
                  });
                }}
                disabled={!packText}
                className="krypt-btn-default inline-flex items-center gap-2 text-xs disabled:opacity-50"
                title="Save the full pack as a .txt (handy for AI apps that take file uploads)"
              >
                <FileDown className="h-3.5 w-3.5" /> Export .txt
              </button>
              {packText && (
                <span className="inline-flex items-center gap-1 text-[11px] text-krypt-win">
                  <CheckCircle2 className="h-3.5 w-3.5" /> {Math.round(packText.length / 1000)}k chars, built from your live config + data
                </span>
              )}
            </div>
            <div className="mt-3 min-h-0 flex-1 overflow-y-auto rounded-lg border border-krypt-border bg-krypt-void/50 p-3 font-mono text-[10px] leading-relaxed text-krypt-dim whitespace-pre-wrap">
              {packText ? `${packText.slice(0, 2500)}\n…` : 'Building the pack from your config, sandbox and recorded data…'}
            </div>
            <div className="mt-3">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-krypt-muted">Paste the AI's reply</div>
              <textarea
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                placeholder={'Paste the AI response here (the ```python block is extracted automatically)…'}
                className="krypt-input mt-1.5 h-24 w-full resize-none font-mono text-[11px]"
              />
              <div className="mt-2 flex justify-end">
                <button
                  onClick={() => void importPaste()}
                  disabled={!pasteText.trim() || busy !== null}
                  className="krypt-btn-primary inline-flex items-center gap-2 text-xs disabled:opacity-50"
                >
                  <Play className="h-3.5 w-3.5" /> Import as script
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </Page>
  );
}

function BacktestResult({ res, busy }: { res: ScriptBacktest | null; busy: boolean }) {
  if (busy) {
    return <div className="rounded-lg border border-krypt-border p-6 text-center text-xs text-krypt-dim">Replaying your script over every recorded window…</div>;
  }
  if (!res) {
    return (
      <div className="rounded-lg border border-dashed border-krypt-border p-6 text-center text-xs leading-relaxed text-krypt-dim">
        Run a backtest to replay this script over the app's recorded ticks —
        taker fills at the recorded ask, Kalshi fees included, same safety rails as live.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {res.scriptError && (
        <div className="rounded-lg border border-krypt-loss/40 bg-krypt-loss/10 px-3 py-2 text-[11px] text-krypt-loss">
          Script died mid-run: {res.scriptError}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-6">
        <Stat label="Trades" value={`${res.n}`} sub={`${res.windowsScanned} windows`} />
        <Stat label="Win rate" value={res.n ? `${(res.winRate * 100).toFixed(1)}%` : '—'} />
        <Stat label="Edge / contract" value={`${res.netEvCentsPerContract.toFixed(2)}¢`} tone={res.netEvCentsPerContract >= 0 ? 'good' : 'bad'} />
        <Stat label="Total P&L" value={fmtUsd(res.totalPnlUsd, { sign: true })} tone={res.totalPnlUsd >= 0 ? 'good' : 'bad'} />
        <Stat label="t-stat" value={res.tStat != null ? res.tStat.toFixed(2) : '—'} sub={res.tStat != null && Math.abs(res.tStat) >= 2 ? 'significant-ish' : 'noise-level'} />
        <Stat label="Max drawdown" value={fmtUsd(res.maxDrawdownUsd)} tone="bad" />
      </div>
      {Object.keys(res.byAsset).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(res.byAsset).map(([a, st]) => (
            <span key={a} className="rounded bg-krypt-surface2 px-1.5 py-0.5 font-mono text-[10px] text-krypt-dim">
              {a} {st.wins}/{st.n}{' '}
              <span className={st.pnlUsd >= 0 ? 'text-krypt-win' : 'text-krypt-loss'}>{fmtUsd(st.pnlUsd, { sign: true })}</span>
            </span>
          ))}
        </div>
      )}
      {res.signalResult && (
        <div className="rounded-lg border border-krypt-border/70 bg-krypt-surface2/30 p-2">
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-krypt-muted">
            Whale / momentum signal replay (decide_signal)
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
            <Stat label="Follows" value={`${res.signalResult.n}`} sub={`${res.signalResult.windowsScanned} signals scanned`} />
            <Stat label="Win rate" value={res.signalResult.n ? `${(res.signalResult.winRate * 100).toFixed(1)}%` : '—'} />
            <Stat label="Edge / contract" value={`${res.signalResult.netEvCentsPerContract.toFixed(2)}¢`} tone={res.signalResult.netEvCentsPerContract >= 0 ? 'good' : 'bad'} />
            <Stat label="Total P&L" value={fmtUsd(res.signalResult.totalPnlUsd, { sign: true })} tone={res.signalResult.totalPnlUsd >= 0 ? 'good' : 'bad'} />
            <Stat label="t-stat" value={res.signalResult.tStat != null ? res.signalResult.tStat.toFixed(2) : '—'} />
          </div>
          <ul className="mt-1.5 space-y-0.5">
            {(res.signalResult.caveats ?? []).map((c, i) => (
              <li key={i} className="text-[10px] leading-relaxed text-krypt-warn/70">⚠ {c}</li>
            ))}
          </ul>
        </div>
      )}
      {(res.scriptLogs?.length ?? 0) > 0 && (
        <div className="max-h-32 overflow-y-auto rounded-lg border border-krypt-border bg-krypt-void/50 p-2 font-mono text-[10px] text-krypt-muted">
          {res.scriptLogs!.map((l, i) => <div key={i}>{l}</div>)}
        </div>
      )}
      <ul className="space-y-0.5">
        {res.caveats.map((c, i) => (
          <li key={i} className="text-[10px] leading-relaxed text-krypt-warn/80">⚠ {c}</li>
        ))}
      </ul>
    </div>
  );
}

function DocsPanel({ docs }: { docs: ScriptApiDocs | null }) {
  const [showExamples, setShowExamples] = useState(false);
  if (!docs) {
    return <div className="rounded-lg border border-krypt-border p-6 text-center text-xs text-krypt-dim">Loading the API reference…</div>;
  }
  return (
    <div className="max-h-[420px] space-y-3 overflow-y-auto rounded-lg border border-krypt-border bg-krypt-void/40 p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-white">
        <BookOpen className="h-4 w-4 text-krypt-purple" /> Script API
        <span className="text-[10px] font-normal text-krypt-dim">
          — generated live from the engine; always current
        </span>
      </div>
      <pre className="whitespace-pre-wrap rounded-lg bg-krypt-surface2/50 p-3 font-mono text-[10.5px] leading-relaxed text-krypt-muted">
        {docs.contract}
      </pre>

      <div className="text-xs font-semibold uppercase tracking-wide text-krypt-muted">
        ctx fields ({docs.fields.length})
      </div>
      <table className="w-full text-left text-[11px]">
        <tbody>
          {docs.fields.map((f) => (
            <tr key={f.name} className="border-t border-krypt-border/50 align-top">
              <td className="whitespace-nowrap py-1 pr-3 font-mono text-krypt-purple">ctx["{f.name}"]</td>
              <td className="py-1 pr-3 text-krypt-muted">{f.doc}</td>
              <td className="py-1">
                {f.backtestable
                  ? <span className="rounded bg-krypt-win/10 px-1.5 py-0.5 text-[9px] uppercase text-krypt-win">backtestable</span>
                  : <span className="rounded bg-krypt-warn/10 px-1.5 py-0.5 text-[9px] uppercase text-krypt-warn">live-only</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="text-xs font-semibold uppercase tracking-wide text-krypt-muted">Allowed builtins (sandboxed)</div>
      <div className="flex flex-wrap gap-1">
        {docs.builtins.map((b) => (
          <span key={b} className="rounded bg-krypt-surface2 px-1.5 py-0.5 font-mono text-[10px] text-krypt-dim">{b}</span>
        ))}
      </div>

      <div className="text-xs font-semibold uppercase tracking-wide text-krypt-muted">Safety rails (current values)</div>
      <div className="text-[11px] text-krypt-muted">
        Max entry <b className="text-white">{docs.rails.maxEntryCents}¢</b> · max order{' '}
        <b className="text-white">{docs.rails.maxContracts}</b> contracts · max open/script{' '}
        <b className="text-white">{docs.rails.maxOpen}</b> · daily loss stop{' '}
        <b className="text-white">${docs.rails.dailyLossUsd}</b> · default size{' '}
        <b className="text-white">{docs.rails.defaultOrderSize}</b> contracts.
        Rails apply to every script, trusted included.
      </div>

      <button onClick={() => setShowExamples(!showExamples)} className="text-[11px] text-krypt-purple underline-offset-2 hover:underline">
        {showExamples ? 'Hide' : 'Show'} example scripts ({docs.examples.length})
      </button>
      {showExamples && docs.examples.map((ex) => (
        <div key={ex.name}>
          <div className="mb-1 text-[11px] font-semibold text-white">{ex.name}</div>
          <pre className="overflow-x-auto rounded-lg bg-krypt-surface2/50 p-3 font-mono text-[10.5px] leading-relaxed text-krypt-muted">{ex.code}</pre>
        </div>
      ))}
    </div>
  );
}

function Rail({ label, value, suffix, onCommit }: {
  label: string; value: number; suffix?: string; onCommit: (v: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => { setDraft(String(value)); }, [value]);
  const commit = () => {
    const v = Math.max(0, Number(draft));
    if (Number.isFinite(v) && v !== value) { onCommit(v); setDraft(String(v)); }
    else setDraft(String(value));
  };
  return (
    <label className="flex items-center gap-1">
      <span>{label}</span>
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
        className="w-14 rounded border border-krypt-border bg-krypt-void/60 px-1.5 py-0.5 text-center font-mono text-[11px] text-white outline-none focus:border-krypt-purple/60"
      />
      {suffix && <span>{suffix}</span>}
    </label>
  );
}

export function confirmLeavePaperMode(config: Partial<TraderConfig> | null | undefined): boolean {
  if (!config?.scriptsLiveEnabled) return true;
  if (config.accountMode !== 'live') return true;
  return window.confirm(
    'Leave Paper mode? Scripts live is ON: every ENABLED script will start placing REAL orders on your '
    + 'Kalshi account.',
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cls(
        'relative h-5 w-9 shrink-0 rounded-full border transition-colors',
        checked ? 'border-krypt-purple/60 bg-krypt-purple/40' : 'border-krypt-border bg-krypt-surface2',
      )}
    >
      <span
        className={cls(
          'absolute top-0.5 h-3.5 w-3.5 rounded-full bg-white transition-all',
          checked ? 'left-[18px]' : 'left-0.5',
        )}
      />
    </button>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'good' | 'bad' }) {
  return (
    <div className="rounded-lg bg-krypt-surface2/60 p-2">
      <div className="text-[10px] uppercase tracking-wide text-krypt-dim">{label}</div>
      <div className={cls('font-mono text-sm', tone === 'good' ? 'text-krypt-win' : tone === 'bad' ? 'text-krypt-loss' : 'text-white')}>{value}</div>
      {sub && <div className="text-[10px] text-krypt-dim">{sub}</div>}
    </div>
  );
}
