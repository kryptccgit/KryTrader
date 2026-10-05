import { useState } from 'react';
import { ChevronDown, SlidersHorizontal, X } from 'lucide-react';
import type { DiscoverFilters as Filters } from '@shared/market';
import { cls } from '../../utils/format';

export function DiscoverFilters({
  value, onChange, categories,
}: {
  value: Filters;
  onChange: (next: Filters) => void;
  categories: string[];
}) {
  const [open, setOpen] = useState(false);

  const active =
    (value.categories?.length ?? 0) +
    (value.minPriceCents !== undefined ? 1 : 0) +
    (value.maxPriceCents !== undefined ? 1 : 0) +
    (value.minVolume !== undefined ? 1 : 0) +
    (value.maxHoursToClose !== undefined ? 1 : 0);

  const setNum = (key: keyof Filters, raw: string): void => {
    const next = { ...value };
    if (!raw.trim()) delete next[key];
    else {
      const n = Number(raw);
      if (Number.isFinite(n)) (next as Record<string, number>)[key] = n;
    }
    onChange(next);
  };

  const toggleCat = (c: string): void => {
    const cur = value.categories ?? [];
    const next = cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c];
    onChange({ ...value, categories: next.length ? next : undefined });
  };

  return (
    <div className="mb-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setOpen((v) => !v)}
          className={cls(
            'flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors',
            active
              ? 'border-krypt-purple/50 bg-krypt-purple/10 text-white'
              : 'border-krypt-border bg-krypt-surface text-krypt-muted hover:text-white',
          )}
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          Filters
          {active > 0 && (
            <span className="rounded-full bg-krypt-purple px-1.5 text-[9px] font-bold text-white">
              {active}
            </span>
          )}
          <ChevronDown className={cls('h-3 w-3 transition-transform', open && 'rotate-180')} />
        </button>

        {active > 0 && (
          <button
            onClick={() => onChange({})}
            className="flex items-center gap-1 text-[11px] text-krypt-dim hover:text-white"
          >
            <X className="h-3 w-3" /> clear
          </button>
        )}
      </div>

      {open && (
        <div className="mt-2 rounded-xl border border-krypt-border bg-krypt-surface p-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Price from (¢)" hint="on the implied probability">
              <input
                value={value.minPriceCents ?? ''}
                onChange={(e) => setNum('minPriceCents', e.target.value)}
                placeholder="1"
                inputMode="numeric"
                className="krypt-input font-mono"
              />
            </Field>
            <Field label="Price to (¢)">
              <input
                value={value.maxPriceCents ?? ''}
                onChange={(e) => setNum('maxPriceCents', e.target.value)}
                placeholder="99"
                inputMode="numeric"
                className="krypt-input font-mono"
              />
            </Field>
            <Field label="Min volume" hint="contracts traded, lifetime">
              <input
                value={value.minVolume ?? ''}
                onChange={(e) => setNum('minVolume', e.target.value)}
                placeholder="any"
                inputMode="numeric"
                className="krypt-input font-mono"
              />
            </Field>
            <Field label="Closes within (h)">
              <input
                value={value.maxHoursToClose ?? ''}
                onChange={(e) => setNum('maxHoursToClose', e.target.value)}
                placeholder="any"
                inputMode="numeric"
                className="krypt-input font-mono"
              />
            </Field>
          </div>

          {categories.length > 0 && (
            <div className="mt-3">
              <div className="krypt-label">Category</div>
              <div className="flex flex-wrap gap-1.5">
                {categories.map((c) => {
                  const on = value.categories?.includes(c);
                  return (
                    <button
                      key={c}
                      onClick={() => toggleCat(c)}
                      className={cls(
                        'rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                        on
                          ? 'border-krypt-purple/50 bg-krypt-purple/15 text-white'
                          : 'border-krypt-border bg-krypt-surface2 text-krypt-muted hover:text-white',
                      )}
                    >
                      {c}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <p className="mt-3 text-[10px] leading-relaxed text-krypt-dim">
            A market whose volume or close time Kalshi has not reported is
            <em> skipped</em> by those numeric filters and counted in the note
            below the table — it is unmeasured, not low. A market with no
            category is <em>excluded</em> by a category filter, because
            &ldquo;unknown&rdquo; is not one of the categories you picked.
          </p>
        </div>
      )}
    </div>
  );
}

function Field({
  label, hint, children,
}: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="krypt-label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[10px] text-krypt-dim">{hint}</span>}
    </label>
  );
}
