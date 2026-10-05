import { useState } from 'react';
import { ChevronRight, FlaskConical, LayoutGrid,
  Activity, BarChart3, Bitcoin, BookOpen, Bot, Briefcase, Code2, Folder, Info, KeyRound,
  LayoutDashboard, ListChecks, Orbit, Settings, Share2, ShieldCheck, Sparkles,
  Smartphone, Terminal, TrendingUp, Wallet,
} from 'lucide-react';
import { useApp } from '../state/AppStateProvider';
import { cls, fmtUsd } from '../utils/format';
import { KryptSprite } from './KryptSprite';
import { FlexStatsCard } from './FlexStatsCard';
import { MultiRunPanel } from './MultiRunPanel';
import type { PageId } from '../App';

type NavItem = {
  id: PageId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const TERMINAL_NAV: NavItem[] = [
  { id: 'terminal', label: 'Terminal', icon: Terminal },
  { id: 'terminalPortfolio', label: 'My Book', icon: Wallet },
  { id: 'remote', label: 'Remote', icon: Smartphone },
  { id: 'aiAgents', label: 'AI Agents', icon: Bot },
];

const ENGINE_NAV: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'strategies', label: 'Strategies', icon: Sparkles },
  { id: 'positions', label: 'Positions', icon: Briefcase },
  { id: 'signals', label: 'Signals', icon: Activity },
  { id: 'crypto15m', label: '15m Crypto', icon: Bitcoin },
  { id: 'perps', label: 'Perpetuals', icon: TrendingUp },
  { id: 'scripts', label: 'Scripts', icon: Code2 },
  { id: 'backtest', label: 'Backtest', icon: FlaskConical },
  { id: 'history', label: 'History', icon: BarChart3 },
  { id: 'profiles', label: 'Profiles', icon: Folder },
];

const SYSTEM_NAV: NavItem[] = [
  { id: 'settings', label: 'Settings', icon: Settings },
  { id: 'api', label: 'API Keys', icon: KeyRound },
  { id: 'logs', label: 'Logs', icon: ListChecks },
  { id: 'privacy', label: 'Privacy', icon: ShieldCheck },
  { id: 'guide', label: 'Guide', icon: BookOpen },
  { id: 'about', label: 'About', icon: Info },
];

type GroupId = 'manual' | 'engine' | 'system';

const GROUPS: { id: GroupId; label: string; items: NavItem[] }[] = [
  { id: 'manual', label: 'Manual', items: TERMINAL_NAV },
  { id: 'engine', label: 'Automation', items: ENGINE_NAV },
  { id: 'system', label: 'System', items: SYSTEM_NAV },
];

const FOLD_KEY = 'krypt.sidebar.folded';

function readFolded(): GroupId[] {
  try {
    const v = JSON.parse(localStorage.getItem(FOLD_KEY) ?? '[]');
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

interface SidebarProps {
  page: PageId;
  setPage: (p: PageId) => void;
}

export function Sidebar({ page, setPage }: SidebarProps) {
  const { config, account, backend } = useApp();
  const [showStats, setShowStats] = useState(false);
  const [showMultiRun, setShowMultiRun] = useState(false);
  const runnerCount = (config?.crypto15mRunners ?? []).filter((r) => r.enabled).length;
  const [folded, setFolded] = useState<GroupId[]>(readFolded);

  const toggle = (g: GroupId): void => {
    const next = folded.includes(g) ? folded.filter((x) => x !== g) : [...folded, g];
    setFolded(next);
    try { localStorage.setItem(FOLD_KEY, JSON.stringify(next)); } catch {  }
  };

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-krypt-border bg-krypt-void/40">
      <div className="shrink-0 px-4 py-3">
        <div className="flex items-center gap-2">
          <KryptSprite size={38} title="Krypt" />
          <div>
            <div className="font-pixel text-[10px] uppercase tracking-[0.18em] text-white/90">
              Krypt
            </div>
            <button
              onClick={() => setShowStats(true)}
              className="group flex items-center gap-1 text-xs text-krypt-muted transition-colors hover:text-white"
              title="Open your shareable stats card"
            >
              <Share2 className="h-3 w-3 text-krypt-purple opacity-80 transition-opacity group-hover:opacity-100" />
              <span className="underline-offset-2 group-hover:underline">Krypt Stats</span>
            </button>
          </div>
          <button
            onClick={() => setShowMultiRun(true)}
            title="Multi-Run — run different 15m strategies on different coins at once"
            className="relative ml-auto grid h-8 w-8 place-items-center rounded-lg border border-krypt-border bg-krypt-surface text-krypt-muted transition-colors hover:border-krypt-purple/50 hover:text-white"
          >
            <LayoutGrid className="h-4 w-4" />
            {runnerCount > 0 && (
              <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-krypt-purple px-1 text-[9px] font-bold text-white shadow">
                {runnerCount}
              </span>
            )}
          </button>
        </div>
      </div>

      <nav className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-2">
        {GROUPS.map((g, i) => {
          const open = !folded.includes(g.id);
          const items = open ? g.items : g.items.filter((it) => it.id === page);
          return (
            <div key={g.id} className={cls('flex flex-col gap-0.5', i > 0 && 'mt-2')}>
              <button
                onClick={() => toggle(g.id)}
                className="group flex items-center gap-1 px-3 pb-0.5 pt-1 text-[9px] font-semibold uppercase tracking-[0.18em] text-krypt-dim hover:text-krypt-muted"
                title={open ? `Collapse ${g.label}` : `Expand ${g.label}`}
              >
                <ChevronRight className={cls('h-3 w-3 transition-transform', open && 'rotate-90')} />
                {g.label}
                {!open && (
                  <span className="ml-auto font-mono normal-case tracking-normal">{g.items.length}</span>
                )}
              </button>
              {items.map(({ id, label, icon: Icon }) => (
                <NavButton
                  key={id} id={id} label={label} Icon={Icon}
                  active={page === id} onClick={() => setPage(id)}
                />
              ))}
            </div>
          );
        })}

        <div className="relative hidden min-h-0 flex-1 select-none items-end justify-center pb-3 pt-2 [@media(min-height:960px)]:flex">
          <div className="pointer-events-none absolute bottom-2 h-3 w-16 rounded-[100%] bg-krypt-pink/25 blur-md" />
          <KryptSprite size={72} pet title="krypt" className="relative" />
        </div>
      </nav>

      <div className="shrink-0 border-t border-krypt-border px-3 pt-2">
        <button
          onClick={() => setPage('visualizer')}
          className={cls(
            'group relative flex w-full items-center gap-2 overflow-hidden rounded-lg border px-3 py-1.5 text-sm transition-all',
            page === 'visualizer'
              ? 'border-krypt-purple/60 bg-krypt-purple/15 text-white shadow-[0_0_18px_rgba(168,85,247,0.25)]'
              : 'border-krypt-border bg-gradient-to-r from-krypt-purple/10 via-krypt-pink/5 to-transparent text-white hover:border-krypt-purple/40',
          )}
          title="Open the live trade visualizer"
        >
          <span className="relative grid h-7 w-7 place-items-center">
            <span className="absolute inset-0 rounded-full bg-krypt-purple/30 blur-md transition-opacity group-hover:opacity-80" />
            <Orbit className="relative h-4 w-4 text-krypt-purple animate-[spin_20s_linear_infinite]" />
          </span>
          <span className="text-xs font-medium uppercase tracking-wider">Live Visualizer</span>
          <span className="ml-auto h-1.5 w-1.5 rounded-full bg-krypt-purple shadow-[0_0_8px_currentColor]" />
        </button>
      </div>

      <div className="shrink-0 px-3 py-2">
        <div className="rounded-lg border border-krypt-border bg-krypt-surface px-3 py-2">
          <div className="flex items-center gap-2 text-xs text-krypt-muted">
            <Wallet className="h-3.5 w-3.5" />
            <span className="uppercase tracking-wider">Wallet</span>
            <span className={cls(
              'ml-auto rounded-full px-1.5 py-0.5 text-[10px] uppercase tracking-wider',
              config?.kalshiEnv === 'demo'
                ? 'border border-krypt-warn/40 bg-krypt-warn/10 text-krypt-warn'
                : 'border border-krypt-win/40 bg-krypt-win/10 text-krypt-win',
            )}>
              {config?.kalshiEnv ?? 'demo'}
            </span>
          </div>
          <div className="mt-0.5 font-mono text-lg leading-tight text-white">
            {fmtUsd(account?.totalUsd)}
          </div>
          <div className="text-[11px] text-krypt-dim">
            cash {fmtUsd(account?.cashUsd)} · port {fmtUsd(account?.portfolioUsd)}
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px] text-krypt-muted">
            <span>{config?.enableTrading ? (config?.kalshiEnv === 'production' ? 'LIVE' : 'DEMO') : 'PAUSED'}</span>
            <span className={cls(
              'h-1.5 w-1.5 rounded-full',
              backend.status === 'running' ? 'bg-krypt-win' : 'bg-krypt-warn',
            )} />
          </div>
        </div>
      </div>

      {showStats && <FlexStatsCard onClose={() => setShowStats(false)} />}
      {showMultiRun && <MultiRunPanel onClose={() => setShowMultiRun(false)} />}
    </aside>
  );
}

function NavButton({
  id, label, Icon, active, onClick,
}: {
  id: PageId;
  label: string;
  Icon: React.ComponentType<{ className?: string }>;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      key={id}
      onClick={onClick}
      className={cls(
        'group flex shrink-0 items-center gap-3 rounded-lg px-3 py-1.5 text-sm transition-colors',
        active
          ? 'bg-white/[0.06] text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.06)]'
          : 'text-krypt-muted hover:bg-white/[0.03] hover:text-white',
      )}
    >
      <Icon className={cls('h-4 w-4', active && 'text-krypt-purple')} />
      <span>{label}</span>
      {active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-krypt-purple shadow-[0_0_8px_currentColor]" />}
    </button>
  );
}
