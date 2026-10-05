import { Children, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Bitcoin, Check, Copy, Download, FolderOpen, FolderPlus, Pencil, Trash2, Upload,
} from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Empty, NameDialog, Page } from '../components/common';
import { cls, fmtDateTime } from '../utils/format';
import type { Profile } from '@shared/types';

export function ProfilesPage() {
  const { state, refresh } = useApp();
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Profile | null>(null);

  const profiles = state?.customProfiles ?? [];
  const activeId = state?.activeProfileId ?? null;
  const cryptoActiveId = state?.activeCrypto15mProfileId ?? null;
  const mainProfiles = profiles.filter((p) => p.kind !== 'crypto15m');
  const cryptoProfiles = profiles.filter((p) => p.kind === 'crypto15m');

  const create = async (name: string): Promise<void> => {
    setCreateOpen(false);
    const r = await window.krypt.profiles.save(name);
    if (r.ok) {
      toast.success(r.message || 'Saved');
      await refresh.state();
    } else toast.error(r.message || 'Failed to save');
  };

  const rename = async (name: string): Promise<void> => {
    const target = renameTarget;
    setRenameTarget(null);
    if (!target || name === target.name) return;
    const r = await window.krypt.profiles.rename(target.id, name);
    if (r.ok) {
      toast.success('Renamed');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const remove = async (id: string, name: string): Promise<void> => {
    if (!window.confirm(`Delete profile "${name}"?`)) return;
    const r = await window.krypt.profiles.delete(id);
    if (r.ok) {
      toast.success('Deleted');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const duplicate = async (id: string): Promise<void> => {
    const r = await window.krypt.profiles.duplicate(id);
    if (r.ok) {
      toast.success(`Duplicated`);
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const apply = async (id: string): Promise<void> => {
    const r = await window.krypt.profiles.apply(id);
    if (r.ok) {
      toast.success(r.message || 'Applied');
      await refresh.state();
    } else toast.error(r.message || 'Failed');
  };

  const exportProfile = async (id: string, name: string): Promise<void> => {
    const r = await window.krypt.profiles.export(id);
    if (!r.ok || !r.data) {
      toast.error(r.message || 'Export failed');
      return;
    }
    const blob = new Blob([r.data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name.replace(/[^a-z0-9-_]+/gi, '_')}.kryptprofile.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const importClick = (): void => fileInputRef.current?.click();

  const importHandler = async (e: React.ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const r = await window.krypt.profiles.import(text);
      if (r.ok && r.data) {
        const applied = await window.krypt.profiles.apply(r.data.id);
        toast.success(applied?.ok ? `Imported & applied "${r.data.name}"` : (r.message || 'Imported'));
        await refresh.state();
      } else if (r.ok) {
        toast.success(r.message || 'Imported');
        await refresh.state();
      } else toast.error(r.message || 'Import failed');
    } catch (err: any) {
      toast.error(err?.message || 'Read failed');
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <Page
      title="Profiles"
      subtitle="Save snapshots of your trader config and switch between them."
      actions={
        <>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => void importHandler(e)}
          />
          <button onClick={importClick} className="krypt-btn-default">
            <Upload className="h-4 w-4" /> Import
          </button>
          <button onClick={() => setCreateOpen(true)} className="krypt-btn-primary">
            <FolderPlus className="h-4 w-4" /> New from current settings
          </button>
        </>
      }
    >
      {profiles.length === 0 ? (
        <Empty
          title="No profiles yet"
          description="Save the current settings as a profile, or save a 15m crypto strategy from the Crypto tab."
          action={
            <button onClick={() => setCreateOpen(true)} className="krypt-btn-primary">
              <FolderPlus className="h-4 w-4" /> Save current as profile
            </button>
          }
        />
      ) : (
        <div className="flex flex-col gap-7">
          <Section
            title="Main engine"
            subtitle="Whale + momentum trader settings. Saved with “New from current settings”."
            emptyHint="No main-engine profiles yet."
          >
            {mainProfiles.map((p) => (
              <ProfileCard
                key={p.id} p={p} active={activeId === p.id}
                onApply={apply} onRename={setRenameTarget} onDuplicate={duplicate}
                onExport={exportProfile} onDelete={remove}
              />
            ))}
          </Section>
          <Section
            title="15m crypto"
            subtitle="The short-term crypto executor's strategy. Save one from the Crypto tab."
            emptyHint="No 15m crypto profiles yet — open the Crypto tab and tap “Save as profile”."
          >
            {cryptoProfiles.map((p) => (
              <ProfileCard
                key={p.id} p={p} active={cryptoActiveId === p.id}
                onApply={apply} onRename={setRenameTarget} onDuplicate={duplicate}
                onExport={exportProfile} onDelete={remove}
              />
            ))}
          </Section>
        </div>
      )}

      <NameDialog
        open={createOpen}
        title="New profile from current settings"
        label="Saves a snapshot of your current trader config."
        placeholder="Profile name"
        confirmLabel="Save"
        onSubmit={(name) => void create(name)}
        onClose={() => setCreateOpen(false)}
      />
      <NameDialog
        open={renameTarget !== null}
        title="Rename profile"
        initialValue={renameTarget?.name ?? ''}
        confirmLabel="Rename"
        onSubmit={(name) => void rename(name)}
        onClose={() => setRenameTarget(null)}
      />
    </Page>
  );
}

function Section({
  title, subtitle, emptyHint, children,
}: {
  title: string;
  subtitle: string;
  emptyHint: string;
  children: ReactNode;
}) {
  const items = Children.toArray(children);
  return (
    <section>
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        <p className="text-xs text-krypt-muted">{subtitle}</p>
      </div>
      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-krypt-border bg-krypt-surface/40 px-4 py-6 text-center text-xs text-krypt-dim">
          {emptyHint}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{children}</div>
      )}
    </section>
  );
}

function ProfileCard({
  p, active, onApply, onRename, onDuplicate, onExport, onDelete,
}: {
  p: Profile;
  active: boolean;
  onApply: (id: string) => void;
  onRename: (p: Profile) => void;
  onDuplicate: (id: string) => void;
  onExport: (id: string, name: string) => void;
  onDelete: (id: string, name: string) => void;
}) {
  const crypto = p.kind === 'crypto15m';
  return (
    <div
      className={cls(
        'rounded-xl border bg-krypt-surface p-4 transition-colors',
        active ? 'border-krypt-purple shadow-krypt-soft' : 'border-krypt-border hover:border-krypt-borderHi',
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cls(
          'grid h-10 w-10 place-items-center rounded-lg',
          active ? 'bg-krypt-glow text-white' : 'bg-krypt-surface2 text-krypt-muted',
        )}>
          {crypto ? <Bitcoin className="h-4 w-4" /> : <FolderOpen className="h-4 w-4" />}
        </div>
        <div className="flex-1">
          <div className="text-sm font-medium text-white">{p.name}</div>
          <div className="text-xs text-krypt-muted">Updated {fmtDateTime(p.updatedAt)}</div>
          {p.description && <p className="mt-1 text-xs text-krypt-dim">{p.description}</p>}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
        {crypto ? (
          <>
            <Mini label="mode" value={p.config.crypto15mUseRules ? 'rules' : (p.config.crypto15mDirectionMode ?? 'favorite')} />
            <Mini label="entry≥" value={`${Math.round((p.config.crypto15mEntryThreshold ?? 0) * 100)}¢`} />
            <Mini label="stop" value={`${Math.round((p.config.crypto15mExitThreshold ?? 0) * 100)}¢`} />
          </>
        ) : (
          <>
            <Mini label="env" value={p.config.kalshiEnv} />
            <Mini label="cap" value={`$${p.config.hardMaxPositionUsd}`} />
            <Mini label="open" value={`${p.config.maxOpenPositions}`} />
          </>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {!active && (
          <button onClick={() => onApply(p.id)} className="krypt-btn-primary text-xs">Apply</button>
        )}
        {active && (
          <span className="krypt-pill border-krypt-purple/40 bg-krypt-purple/10 text-krypt-purple">
            <Check className="h-3 w-3" /> Active
          </span>
        )}
        <button onClick={() => onRename(p)} className="krypt-btn-ghost text-xs">
          <Pencil className="h-3.5 w-3.5" /> Rename
        </button>
        <button onClick={() => onDuplicate(p.id)} className="krypt-btn-ghost text-xs">
          <Copy className="h-3.5 w-3.5" /> Duplicate
        </button>
        <button onClick={() => onExport(p.id, p.name)} className="krypt-btn-ghost text-xs">
          <Download className="h-3.5 w-3.5" /> Export
        </button>
        <button onClick={() => onDelete(p.id, p.name)} className="krypt-btn-ghost text-xs text-krypt-loss/80 hover:text-krypt-loss">
          <Trash2 className="h-3.5 w-3.5" /> Delete
        </button>
      </div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-krypt-border bg-krypt-surface2 px-2 py-1">
      <div className="text-[9px] uppercase tracking-wider text-krypt-dim">{label}</div>
      <div className="font-mono text-[11px] text-white">{value}</div>
    </div>
  );
}
