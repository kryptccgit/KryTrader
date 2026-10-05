export const fmtUsd = (v: number | null | undefined, opts?: { sign?: boolean }): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const sign = opts?.sign && v > 0 ? '+' : '';
  return `${sign}$${Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v.toFixed(2)}`.replace(
    '$-',
    '-$',
  );
};

export const fmtPct = (v: number | null | undefined, dp = 1): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(dp)}%`;
};

export const fmtCents = (v: number | null | undefined): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${Math.round(v)}¢`;
};

export const fmtNum = (v: number | null | undefined, dp = 0): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toLocaleString(undefined, {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
};

export const fmtDateTime = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
};

export const fmtTimeShort = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(11, 19);
    return d.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return iso;
  }
};

export const fmtRelative = (iso: string | null | undefined): string => {
  if (!iso) return '—';
  try {
    const d = new Date(iso).getTime();
    if (!Number.isFinite(d)) return iso;
    const diff = Math.max(0, Date.now() - d) / 1000;
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch {
    return iso;
  }
};

export const cls = (...parts: (string | false | null | undefined)[]): string =>
  parts.filter(Boolean).join(' ');

export const titleCase = (s: string): string =>
  s
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, (c) => c.toUpperCase())
    .trim();
