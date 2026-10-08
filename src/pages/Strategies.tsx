import { useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Bot, Check, Code2, Download, FolderOpen, Pencil, Save, SlidersHorizontal, Trash2, Upload,
} from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { NameDialog, Page } from '../components/common';
import { cls, fmtDateTime, fmtUsd } from '../utils/format';
import type { Profile } from '@shared/types';
import type { PageId } from '../App';
import { publishActivity } from '../state/activity';
import { userMessage } from '../utils/errors';

export function StrategiesPage({ onNav }: { onNav: (p: PageId) => void }) {
  const { state, refresh } = useApp();
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Profile | null>(null);

  const saveCurrent = async (name: string): Promise<void> => {
    setSaveOpen(false);
    const r = await window.krypt.profiles.save(name);
    if (r.ok) {
      toast.success(r.message || `Saved "${name}"`);
      await refresh.state();
    } else toast.error(r.message || 'Could not save strategy');
  };

  const applyProfile = async (p: Profile): Promise<void> => {
    setBusyId(p.id);
    try {
      const r = await window.krypt.profiles.apply(p.id);
      publishActivity(() => (r.ok ? { kind: 'preset', what: 'profile', name: p.name, ok: true } : null));
      if (r.ok) {
        toast.success(r.message || `Applied "${p.name}"`);
        await refresh.state();
      } else toast.error(r.message || 'Failed');
    } finally {
      setBusyId(null);
    }
  };

  const renameProfile = async (name: string): Promise<void> => {
    const target = renameTarget;
    setRenameTarget(null);
    if (!target || name === target.name) return;
    const r = await window.krypt.profiles.rename(target.id, name);
    if (r.ok) {
      toast.success('Renamed');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const deleteProfile = async (p: Profile): Promise<void> => {
    if (!window.confirm(`Delete your strategy "${p.name}"?`)) return;
    const r = await window.krypt.profiles.delete(p.id);
    if (r.ok) {
      toast.success('Deleted');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const updateProfile = async (p: Profile): Promise<void> => {
    const r = await window.krypt.profiles.update(p.id);
    if (r.ok) {
      toast.success(`Updated "${p.name}" to your current settings`);
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const shareProfile = async (p: Profile): Promise<void> => {
    const r = await window.krypt.profiles.export(p.id);
    if (!r.ok || !r.data) {
      toast.error(r.message || 'Export failed');
      return;
    }
    const blob = new Blob([r.data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${p.name.replace(/[^a-z0-9-_]+/gi, '_')}.kryptprofile.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast.success(`Exported "${p.name}" — share the .json file`);
  };

  const importHandler = async (e: React.ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const r = await window.krypt.profiles.import(await file.text());
      if (r.ok) {
        toast.success(r.data ? `Imported "${r.data.name}" — Apply it when you're ready` : (r.message || 'Imported'));
        await refresh.state();
      } else toast.error(r.message || 'Import failed');
    } catch (err: any) {
      toast.error(userMessage(err, 'Read failed'));
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const profiles = state?.customProfiles ?? [];
  const isActive = (p: Profile): boolean => (p.kind === 'crypto15m'
    ? state?.activeCrypto15mProfileId === p.id
    : state?.activeProfileId === p.id);

  return (
    <Page
      title="Strategies"
      subtitle="Strategies here are ones you or your AI made: saved snapshots of the engine's settings you can switch between. Code strategies live on Scripts, and an agent with “Change strategy settings” on (AI Agents) can tune these settings for you. None of them has a proven edge — run anything new in Paper first."
      actions={
        <>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => void importHandler(e)}
          />
          <button onClick={() => fileInputRef.current?.click()} className="krypt-btn-default">
            <Upload className="h-4 w-4" /> Import
          </button>
          <button onClick={() => setSaveOpen(true)} className="krypt-btn-primary">
            <Save className="h-4 w-4" /> Save current as strategy
          </button>
        </>
      }
    >
      {profiles.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.015] p-6">
          <div className="text-base font-medium text-white">No strategies yet</div>
          <p className="mt-1 max-w-2xl text-sm text-krypt-muted">
            A strategy is a named snapshot of how the bot decides what to trade. There are three ways to
            make your first one:
          </p>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            <WayCard
              icon={<SlidersHorizontal className="h-4 w-4" />}
              title="Tune it yourself"
              body="Set signal gates, categories and sizing in Settings, then come back and save them here as a strategy."
              action={
                <>
                  <button onClick={() => onNav('settings')} className="krypt-btn-default text-xs">
                    Open Settings
                  </button>
                  <button onClick={() => setSaveOpen(true)} className="krypt-btn-primary text-xs">
                    <Save className="h-3.5 w-3.5" /> Save current
                  </button>
                </>
              }
            />
            <WayCard
              icon={<Code2 className="h-4 w-4" />}
              title="Write it as code"
              body="Write a Python strategy — or have your AI generate one — backtest it on your recorded data, and run it sandboxed under the script caps."
              action={
                <button onClick={() => onNav('scripts')} className="krypt-btn-default text-xs">
                  Open Scripts
                </button>
              }
            />
            <WayCard
              icon={<Bot className="h-4 w-4" />}
              title="Let your AI tune it"
              body="Connect an agent and switch on “Change strategy settings”. It can adjust the engine's gates for you; save what it lands on here."
              action={
                <button onClick={() => onNav('aiAgents')} className="krypt-btn-default text-xs">
                  Open AI Agents
                </button>
              }
            />
          </div>
          <p className="mt-4 text-xs text-krypt-dim">
            Have a <span className="font-mono">.kryptprofile.json</span> someone shared? Use Import above.
          </p>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {profiles.map((p) => {
            const active = isActive(p);
            return (
              <div
                key={p.id}
                className={cls(
                  'rounded-xl border bg-krypt-surface p-4 transition-colors',
                  active
                    ? 'border-krypt-purple shadow-krypt-soft'
                    : 'border-krypt-border hover:border-krypt-borderHi',
                )}
              >
                <div className="flex items-start gap-3">
                  <div className={cls(
                    'grid h-10 w-10 place-items-center rounded-lg',
                    active ? 'bg-krypt-glow text-white' : 'bg-krypt-surface2 text-krypt-muted',
                  )}>
                    <FolderOpen className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-white">{p.name}</div>
                    <div className="text-xs text-krypt-muted">
                      {p.kind === 'crypto15m' ? '15m crypto · ' : ''}Updated {fmtDateTime(p.updatedAt)}
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                  <Stat label="cap" value={fmtUsd(p.config.hardMaxPositionUsd)} />
                  <Stat label="open" value={`${p.config.maxOpenPositions}`} />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  {active ? (
                    <span className="krypt-pill border-krypt-purple/40 bg-krypt-purple/10 text-krypt-purple">
                      <Check className="h-3 w-3" /> Active
                    </span>
                  ) : (
                    <button
                      onClick={() => applyProfile(p)}
                      disabled={busyId === p.id}
                      className="krypt-btn-primary text-xs"
                    >
                      Apply
                    </button>
                  )}
                  <button onClick={() => setRenameTarget(p)} className="krypt-btn-ghost text-xs">
                    <Pencil className="h-3.5 w-3.5" /> Rename
                  </button>
                  <button
                    onClick={() => void updateProfile(p)}
                    className="krypt-btn-ghost text-xs"
                    title="Overwrite this strategy with your current settings"
                  >
                    <Save className="h-3.5 w-3.5" /> Update
                  </button>
                  <button
                    onClick={() => void shareProfile(p)}
                    className="krypt-btn-ghost text-xs"
                    title="Export to a .json file you can share or import elsewhere"
                  >
                    <Download className="h-3.5 w-3.5" /> Share
                  </button>
                  <button
                    onClick={() => deleteProfile(p)}
                    className="krypt-btn-ghost text-xs text-krypt-loss/80 hover:text-krypt-loss"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Delete
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <NameDialog
        open={saveOpen}
        title="Save current settings as a strategy"
        label="Give this snapshot of your settings a name."
        placeholder="e.g. My small-balance sports config"
        confirmLabel="Save"
        onSubmit={(name) => void saveCurrent(name)}
        onClose={() => setSaveOpen(false)}
      />
      <NameDialog
        open={renameTarget !== null}
        title="Rename strategy"
        initialValue={renameTarget?.name ?? ''}
        confirmLabel="Rename"
        onSubmit={(name) => void renameProfile(name)}
        onClose={() => setRenameTarget(null)}
      />
    </Page>
  );
}

function WayCard({
  icon, title, body, action,
}: { icon: ReactNode; title: string; body: string; action: ReactNode }) {
  return (
    <div className="flex flex-col rounded-xl border border-krypt-border bg-krypt-surface p-4">
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-krypt-purple/15 text-krypt-purple">{icon}</span>
        <span className="text-sm font-semibold text-white">{title}</span>
      </div>
      <p className="mt-2 flex-1 text-xs leading-relaxed text-krypt-muted">{body}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">{action}</div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1">
      <div className="text-[9px] uppercase tracking-wider text-krypt-dim">{label}</div>
      <div className="font-mono text-[11px] text-white">{value}</div>
    </div>
  );
}
