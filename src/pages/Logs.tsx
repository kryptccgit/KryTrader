import { useEffect, useMemo, useRef, useState } from 'react';
import { ClipboardCheck, Eraser, FolderOpen } from 'lucide-react';
import { useLogs } from '../state/AppStateProvider';
import { useToast } from '../state/ToastProvider';
import { Page } from '../components/common';
import { cls, fmtTimeShort } from '../utils/format';

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: 'text-krypt-dim',
  INFO: 'text-white/80',
  WARN: 'text-krypt-warn',
  ERROR: 'text-krypt-loss',
  CRITICAL: 'text-krypt-loss',
};

export function LogsPage() {
  const logs = useLogs();
  const toast = useToast();
  const [filter, setFilter] = useState('');
  const [src, setSrc] = useState<string>('all');
  const [level, setLevel] = useState<string>('all');
  const [autoscroll, setAutoscroll] = useState(true);
  const ref = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const f = filter.toLowerCase();
    return logs.filter((l) => {
      if (src !== 'all' && l.source !== src) return false;
      if (level !== 'all' && l.level !== level) return false;
      if (f && !l.msg.toLowerCase().includes(f) && !l.source.toLowerCase().includes(f)) return false;
      return true;
    });
  }, [logs, filter, src, level]);

  useEffect(() => {
    if (autoscroll && ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  }, [filtered, autoscroll]);

  const clear = async (): Promise<void> => {
    await window.krypt.logs.clear();
    toast.info('Cleared in-memory logs');
  };

  return (
    <Page
      title="Logs"
      subtitle="Live tail from the Python backend. The full rotating log is on disk."
      actions={
        <>
          <button
            onClick={() => {
              void window.krypt.logs.diagnostics({ lines: 300 }).then((r) => {
                toast.push(r.message ?? 'Copied.', r.ok ? 'success' : 'error', 7000);
              });
            }}
            className="krypt-btn-default"
            title="Copy versions, backend state, settings and the recent log — safe to paste, with no credentials in it"
          >
            <ClipboardCheck className="h-4 w-4" /> Copy diagnostics
          </button>
          <button onClick={() => window.krypt.logs.openFolder()} className="krypt-btn-default">
            <FolderOpen className="h-4 w-4" /> Open log folder
          </button>
          <button onClick={clear} className="krypt-btn-default">
            <Eraser className="h-4 w-4" /> Clear
          </button>
        </>
      }
    >
      <div className="mb-3 grid grid-cols-1 items-center gap-2 md:grid-cols-[1fr_auto_auto_auto]">
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter logs…"
          className="krypt-input"
        />
        <select
          value={src}
          onChange={(e) => setSrc(e.target.value)}
          className="krypt-input w-32"
        >
          <option value="all">All sources</option>
          <option value="trader">Trader</option>
          <option value="whale">Whale</option>
          <option value="momentum">Momentum</option>
          <option value="backend">Backend</option>
          <option value="discord">Discord</option>
        </select>
        <select
          value={level}
          onChange={(e) => setLevel(e.target.value)}
          className="krypt-input w-28"
        >
          <option value="all">All levels</option>
          <option value="DEBUG">Debug</option>
          <option value="INFO">Info</option>
          <option value="WARN">Warn</option>
          <option value="ERROR">Error</option>
        </select>
        <label className="flex items-center gap-2 text-xs text-krypt-muted">
          <input
            type="checkbox"
            checked={autoscroll}
            onChange={(e) => setAutoscroll(e.target.checked)}
            className="h-3.5 w-3.5 accent-krypt-purple"
          />
          Auto-scroll
        </label>
      </div>

      <div
        ref={ref}
        className="h-[calc(100vh-260px)] overflow-y-auto rounded-xl border border-krypt-border bg-black/50 p-3 font-mono text-[12px] leading-relaxed"
      >
        {filtered.length === 0 ? (
          <div className="grid h-full place-items-center text-xs text-krypt-muted">
            No logs match. Backend may still be starting up.
          </div>
        ) : (
          filtered.map((l, i) => (
            <div key={i} className="flex gap-3 py-0.5">
              <span className="w-20 shrink-0 text-krypt-dim">{fmtTimeShort(l.ts)}</span>
              <span className={cls('w-14 shrink-0 uppercase', LEVEL_COLORS[l.level] ?? '')}>
                {l.level}
              </span>
              <span className="w-20 shrink-0 truncate text-krypt-purple">[{l.source}]</span>
              <span className="flex-1 whitespace-pre-wrap break-all text-white/80">{l.msg}</span>
            </div>
          ))
        )}
      </div>
    </Page>
  );
}
