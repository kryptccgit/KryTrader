import { useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle, Brain, Coins, ListChecks, Sparkles, X } from 'lucide-react';
import type { TraderConfig } from '@shared/types';
import {
  AGENT_CATEGORIES, AGENT_COLORS, AGENT_GUIDE_MAX, effectiveCaps, type AgentCategory,
  type McpAgent,
} from '@shared/agents';
import { ConfirmDialog, Modal } from '../common';
import { GlassButton } from '../glass/GlassButton';
import { GlassSegmented } from '../glass/GlassSegmented';
import {
  agentToForm, formIsValid, formToAgent, parseField, validateAgentForm, type AgentForm,
} from '../../utils/agentForm';
import { cls, fmtUsd } from '../../utils/format';


const EMOJIS = ['🤖', '🔎', '🏀', '📈', '🔄', '⏳', '🧠', '🦉', '🎯', '⚖️', '🗳️', '🌦️'];

const GUIDE_TIPS = [
  'Say what it trades and what it skips: "NBA totals only; skip injuries you can\'t verify."',
  'Say how it decides: "Form your own number from the rules and the news before looking at the price."',
  'Say when NOT to trade: "If your edge is under a few cents, record the forecast and move on."',
  'Keep it short. Rules below are enforced by the app; the guide is how it should think.',
];

export function AgentEditor({
  agent, isNew, config, otherNames, onSave, onClose,
}: {
  agent: McpAgent;
  isNew: boolean;
  config: Partial<TraderConfig> | null;
  otherNames: string[];
  onSave: (a: McpAgent) => Promise<void> | void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<AgentForm>(() => agentToForm(agent));
  const [touched, setTouched] = useState(false);
  const [armLive, setArmLive] = useState(false);
  const [saving, setSaving] = useState(false);
  const errors = useMemo(() => validateAgentForm(form, otherNames), [form, otherNames]);
  const show = (k: keyof AgentForm): string | undefined => (touched || form[k] !== agentToForm(agent)[k] ? errors[k] : undefined);
  const set = <K extends keyof AgentForm>(k: K, v: AgentForm[K]): void => setForm((f) => ({ ...f, [k]: v }));

  const appLive = config?.accountMode === 'live';
  const globalLive = config?.mcpTradeMode === 'live' && appLive;
  const caps = useMemo(() => {
    const n = (v: string): number | null => {
      const x = parseField(v);
      return x === null || Number.isNaN(x) ? null : x;
    };
    return effectiveCaps(config, {
      ...agent.rules, maxOrderUsd: n(form.maxOrderUsd), dailySpendUsd: n(form.dailySpendUsd),
      minEdgeCents: n(form.minEdgeCents),
    });
  }, [config, agent.rules, form.maxOrderUsd, form.dailySpendUsd, form.minEdgeCents]);

  const save = async (): Promise<void> => {
    setTouched(true);
    if (!formIsValid(errors)) return;
    setSaving(true);
    try {
      await onSave(formToAgent(form, agent));
    } finally {
      setSaving(false);
    }
  };

  const toggleCat = (list: 'categoriesAllow' | 'categoriesDeny', c: AgentCategory): void => {
    setForm((f) => {
      const cur = f[list];
      const next = cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c];
      const other = list === 'categoriesAllow' ? 'categoriesDeny' : 'categoriesAllow';
      return { ...f, [list]: next, [other]: f[other].filter((x) => x !== c) };
    });
  };

  return (
    <Modal open onClose={onClose} maxWidth="max-w-3xl">
      <div className="max-h-[80vh] overflow-y-auto pr-1" data-qa="agent-editor">
        <div className="mb-4 flex items-start gap-3">
          <span
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-xl"
            style={{ background: `${form.color}26`, boxShadow: `inset 0 0 0 1px ${form.color}66` }}
          >
            {form.emoji || '🤖'}
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-white">
              {isNew ? 'New agent' : `Edit ${agent.name}`}
            </h3>
            <p className="text-[11px] text-krypt-muted">
              Your own AI trader: a personality and a way of deciding, inside rails it cannot change.
            </p>
          </div>
          <button onClick={onClose} className="krypt-btn-ghost p-1" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <Block icon={<Sparkles className="h-4 w-4 text-krypt-purple" />} title="1. Personality"
          note="Who it is and how it should think. Advice to the model: it reads this, but the app does not enforce it.">
          <div className="grid gap-3 sm:grid-cols-[1fr,auto]">
            <Field label="Name" error={show('name')}>
              <input
                value={form.name} maxLength={60} data-qa="agent-name"
                onChange={(e) => set('name', e.target.value)}
                className="krypt-input" placeholder="e.g. Sports Sam"
              />
            </Field>
            <Field label="Color">
              <div className="flex h-[38px] items-center gap-1.5">
                {AGENT_COLORS.map((c) => (
                  <button
                    key={c} type="button" aria-label={`Color ${c}`} onClick={() => set('color', c)}
                    className={cls('h-5 w-5 rounded-full ring-offset-2 ring-offset-black/40 transition',
                      form.color === c ? 'ring-2 ring-white' : 'opacity-70 hover:opacity-100')}
                    style={{ background: c }}
                  />
                ))}
              </div>
            </Field>
          </div>
          <Field label="Emoji">
            <div className="flex flex-wrap gap-1">
              {EMOJIS.map((e) => (
                <button
                  key={e} type="button" onClick={() => set('emoji', e)}
                  className={cls('grid h-8 w-8 place-items-center rounded-lg border text-base transition',
                    form.emoji === e ? 'border-krypt-purple/70 bg-krypt-purple/15' : 'border-white/[0.07] bg-white/[0.03] hover:border-white/20')}
                >
                  {e}
                </button>
              ))}
            </div>
          </Field>
          <Field
            label="Guide"
            error={show('guide')}
            hint={`${Array.from(form.guide).length} / ${AGENT_GUIDE_MAX}`}
          >
            <textarea
              value={form.guide} rows={8} data-qa="agent-guide"
              onChange={(e) => set('guide', e.target.value)}
              className="krypt-input min-h-[150px] resize-y text-xs leading-relaxed"
              placeholder={'You are a patient sports trader.\n- Only NBA games settling within two days.\n- Read the rules, form your own number, then compare with the price.\n- Record a forecast on every game you study; trade only when the edge after fees clears your minimum.'}
            />
          </Field>
          <ul className="mt-2 space-y-1 text-[11px] text-krypt-muted">
            {GUIDE_TIPS.map((t) => <li key={t}>• {t}</li>)}
          </ul>
        </Block>

        <Block icon={<ListChecks className="h-4 w-4 text-krypt-win" />} title="2. Decision rules"
          note="Enforced by the app on every buy this agent places, whatever the guide or the model says. They bind its orders only — not strategy scripts it writes or settings it changes, if you've allowed those on the AI Agents page. Leave a box empty for no rule. Selling to exit is never blocked.">
          <Field label="Only these categories" hint="None picked = any category." error={show('categoriesAllow')}>
            <Chips selected={form.categoriesAllow} onToggle={(c) => toggleCat('categoriesAllow', c)} tone="win" qa="allow" />
          </Field>
          <Field label="Never these categories" error={show('categoriesDeny')}>
            <Chips selected={form.categoriesDeny} onToggle={(c) => toggleCat('categoriesDeny', c)} tone="loss" qa="deny" />
          </Field>
          <p className="-mt-1 mb-2 text-[11px] text-krypt-dim">
            A market whose category Kalshi doesn&apos;t publish is refused while either list is set — a guess is not a category.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Entry price (¢)" error={show('minPriceCents') ?? show('maxPriceCents')} hint="1–99. What it pays for a contract.">
              <Pair>
                <Num value={form.minPriceCents} onChange={(v) => set('minPriceCents', v)} placeholder="min" qa="agent-min-price" />
                <span className="text-krypt-dim">to</span>
                <Num value={form.maxPriceCents} onChange={(v) => set('maxPriceCents', v)} placeholder="max" qa="agent-max-price" />
              </Pair>
            </Field>
            <Field label="Time to close (hours)" error={show('minHoursToClose') ?? show('maxHoursToClose')} hint="e.g. max 48 = only markets closing within two days.">
              <Pair>
                <Num value={form.minHoursToClose} onChange={(v) => set('minHoursToClose', v)} placeholder="at least" />
                <span className="text-krypt-dim">to</span>
                <Num value={form.maxHoursToClose} onChange={(v) => set('maxHoursToClose', v)} placeholder="at most" qa="agent-max-hours" />
              </Pair>
            </Field>
            <Field label="Sides it may buy">
              <GlassSegmented
                value={form.sides}
                onChange={(v) => set('sides', v)}
                options={[{ value: 'both', label: 'YES and NO' }, { value: 'yes', label: 'YES only' }, { value: 'no', label: 'NO only' }]}
              />
            </Field>
            <Field label="Minimum edge (¢)" error={show('minEdgeCents')}
              hint={`After Kalshi's fee. Used: ${caps.minEdgeCents}¢${caps.agentBinds.minEdgeCents ? ' (this agent\'s)' : ` (global — an agent value can only raise it)`}.`}>
              <Num value={form.minEdgeCents} onChange={(v) => set('minEdgeCents', v)} placeholder={`global ${caps.global.minEdgeCents}`} />
            </Field>
            <Field label="Max contracts in one market" error={show('maxContractsPerMarket')} hint="0 = it may not buy at all.">
              <Num value={form.maxContractsPerMarket} onChange={(v) => set('maxContractsPerMarket', v)} placeholder="no limit" />
            </Field>
            <Field label="Max open positions" error={show('maxOpenPositions')}
              hint={`0 = forecasts only. The global cap of ${caps.global.maxOpenPositions} across all agents still applies.`}>
              <Num value={form.maxOpenPositions} onChange={(v) => set('maxOpenPositions', v)} placeholder="no limit" qa="agent-max-positions" />
            </Field>
          </div>
        </Block>

        <Block icon={<Coins className="h-4 w-4 text-krypt-warn" />} title="3. Money"
          note="Its own caps. Each one only counts if it is stricter than the global agent cap on the AI Agents page; the global caps bind all agents together.">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Max per order ($)" error={show('maxOrderUsd')}
              hint={`Enforced: ${fmtUsd(caps.maxOrderUsd)} ${caps.agentBinds.maxOrderUsd ? '(this agent)' : `(global ${fmtUsd(caps.global.maxOrderUsd)})`}`}>
              <Num value={form.maxOrderUsd} onChange={(v) => set('maxOrderUsd', v)} placeholder={`global ${caps.global.maxOrderUsd}`} />
            </Field>
            <Field label="Max spend per day ($)" error={show('dailySpendUsd')}
              hint={`Enforced: ${fmtUsd(caps.dailySpendUsd)} ${caps.agentBinds.dailySpendUsd ? '(this agent)' : `(global ${fmtUsd(caps.global.dailySpendUsd)}, shared by all agents)`}`}>
              <Num value={form.dailySpendUsd} onChange={(v) => set('dailySpendUsd', v)} placeholder={`global ${caps.global.dailySpendUsd}`} />
            </Field>
          </div>
          <div className="mt-3">
            <span className="krypt-label">Mode</span>
            <GlassSegmented
              value={form.mode}
              onChange={(m) => { if (m === 'live' && form.mode !== 'live') setArmLive(true); else set('mode', m); }}
              options={[{ value: 'paper', label: 'Paper' }, { value: 'live', label: 'Live' }]}
            />
            <p className={cls('mt-1.5 text-[11px]', form.mode === 'live' ? 'text-krypt-loss' : 'text-krypt-muted')}>
              {form.mode === 'paper'
                ? 'Real order books, imaginary money. Its record builds without risking anything.'
                : globalLive
                  ? 'LIVE: its orders spend your real balance, inside every cap and approval.'
                  : !appLive
                    ? `Set to live, but the app is in Paper, so it trades ${config?.mcpTradeMode === 'off' ? 'nothing' : 'paper'}. It only spends real money once the app is Live (Settings → Account → Go live) and agent trading is Live.`
                    : `Set to live, but agent trading is ${config?.mcpTradeMode ?? 'paper'} right now, so it trades ${config?.mcpTradeMode === 'off' ? 'nothing' : 'paper'}. It only goes live when agent trading is Live (use Go live on the AI Agents page).`}
            </p>
          </div>
        </Block>

        {touched && !formIsValid(errors) && (
          <p className="mb-2 flex items-center gap-1.5 text-[11px] text-krypt-loss">
            <AlertTriangle className="h-3.5 w-3.5" /> Fix the fields marked in red.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <GlassButton onClick={onClose}>Cancel</GlassButton>
          <GlassButton variant="primary" onClick={() => void save()} disabled={saving} data-qa="agent-save">
            <Brain className="h-4 w-4" /> {isNew ? 'Create agent' : 'Save'}
          </GlassButton>
        </div>
      </div>

      <ConfirmDialog
        open={armLive}
        title={`Let ${form.name.trim() || 'this agent'} trade real money?`}
        danger
        confirmLabel="Set to live"
        onClose={() => setArmLive(false)}
        onConfirm={() => { setArmLive(false); set('mode', 'live'); }}
        body={
          <div className="space-y-2">
            <p>
              When agent trading is <span className="text-white">Live</span>, this agent&apos;s orders
              spend your real Kalshi balance — every one still needs a forecast that clears its
              minimum edge after fees, stays inside its caps and the global ones, and waits for your
              approval unless you turned approvals off.
            </p>
            <p className="text-krypt-warn">
              {globalLive
                ? 'Agent trading is Live right now, so this applies as soon as you save.'
                : appLive
                  ? 'Agent trading is not Live right now: nothing changes until you use Go live.'
                  : 'The app is in Paper right now: nothing changes until you switch the app to Live and use Go live.'}
            </p>
          </div>
        }
      />
    </Modal>
  );
}

function Block({ icon, title, note, children }: { icon: ReactNode; title: string; note: string; children: ReactNode }) {
  return (
    <section className="mb-4 rounded-xl border border-white/[0.07] bg-white/[0.025] p-4">
      <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-white">{icon}{title}</div>
      <p className="mb-3 text-[11px] text-krypt-muted">{note}</p>
      {children}
    </section>
  );
}

function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <div className="mb-3 block">
      <span className="krypt-label">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-[11px] text-krypt-loss" role="alert">{error}</span>
        : hint ? <span className="krypt-help block">{hint}</span> : null}
    </div>
  );
}

function Pair({ children }: { children: ReactNode }) {
  return <div className="flex items-center gap-2">{children}</div>;
}

function Num({ value, onChange, placeholder, qa }: { value: string; onChange: (v: string) => void; placeholder?: string; qa?: string }) {
  return (
    <input
      value={value} inputMode="decimal" placeholder={placeholder} data-qa={qa}
      onChange={(e) => onChange(e.target.value.replace(/[^0-9.]/g, ''))}
      className="krypt-input w-full min-w-0 font-mono"
    />
  );
}

function Chips({ selected, onToggle, tone, qa }: {
  selected: AgentCategory[]; onToggle: (c: AgentCategory) => void; tone: 'win' | 'loss'; qa: string;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {AGENT_CATEGORIES.map((c) => {
        const on = selected.includes(c.id);
        return (
          <button
            key={c.id} type="button" onClick={() => onToggle(c.id)} data-qa={`cat-${qa}-${c.id}`}
            aria-pressed={on}
            className={cls('rounded-full border px-2.5 py-1 text-[11px] transition',
              on
                ? tone === 'win' ? 'border-krypt-win/60 bg-krypt-win/15 text-white' : 'border-krypt-loss/60 bg-krypt-loss/15 text-white'
                : 'border-white/[0.08] bg-white/[0.03] text-krypt-muted hover:border-white/20 hover:text-white')}
          >
            {c.label}
          </button>
        );
      })}
    </div>
  );
}
