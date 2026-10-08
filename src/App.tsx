import { useEffect } from 'react';
import { TitleBar } from './components/TitleBar';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { GlassBackdrop } from './components/glass/GlassBackdrop';
import { Crypto15mLiveBanner } from './components/Crypto15mLiveBanner';
import { AppStateProvider, useApp } from './state/AppStateProvider';
import { ToastProvider, useToast } from './state/ToastProvider';
import { GuideHost } from './components/tour/GuideHost';
import { autoOnboarding } from '@shared/onboarding';
import { DashboardPage } from './pages/Dashboard';
import { StrategiesPage } from './pages/Strategies';
import { SettingsPage } from './pages/Settings';
import { PositionsPage } from './pages/Positions';
import { SignalsPage } from './pages/Signals';
import { HistoryPage } from './pages/History';
import { ProfilesPage } from './pages/Profiles';
import { LogsPage } from './pages/Logs';
import { ApiKeysPage } from './pages/ApiKeys';
import { AboutPage } from './pages/About';
import { GuidePage } from './pages/Guide';
import { VisualizerPage } from './pages/Visualizer';
import { Crypto15mPage } from './pages/Crypto15m';
import { PerpsPage } from './pages/Perps';
import { BacktestPage } from './pages/Backtest';
import { ScriptsPage } from './pages/Scripts';
import { TerminalPage } from './pages/Terminal';
import { TerminalPortfolioPage } from './pages/TerminalPortfolio';
import { PrivacyPage } from './pages/Privacy';
import { RemotePage } from './pages/Remote';
import { AiAgentsPage } from './pages/AiAgents';
import { TerminalProvider } from './state/TerminalProvider';
import { agentCallEvent, agentEvent, publishActivity, ruleEvent } from './state/activity';

import { PageGuard, usePersistedPage } from './components/PageGuard';
import { useWindowVisibility } from './state/visibility';
import type { PageId } from './state/lastPage';

export type { PageId } from './state/lastPage';

export default function App() {
  return (
    <ToastProvider>
      <AppStateProvider>
        <TerminalProvider>
          <Shell />
        </TerminalProvider>
      </AppStateProvider>
    </ToastProvider>
  );
}

function Shell() {
  const [page, setPage, onPageCrash] = usePersistedPage();
  useWindowVisibility();
  const { state } = useApp();
  const toast = useToast();

  useEffect(() => window.krypt.terminal.onRule((d) => {
    const { message } = d;
    publishActivity(() => ruleEvent(d));
    toast.push(message, 'warn', 12_000);
    try {
      new Notification('Krypt Terminal', { body: message, silent: true });
    } catch {}
  }), [toast]);

  useEffect(() => window.krypt.app.onNavigate?.((p) => {
    if (p !== 'dashboard') return;
    setPage('dashboard');
    toast.push('To resume LIVE trading, press Start Trading at the top right. It asks before using real money.', 'info', 10_000);
  }), [setPage, toast]);

  useEffect(() => {
    const offAgent = window.krypt.terminal.onMcpOrder((d) => publishActivity(() => agentEvent(d)));
    const offCalls = window.krypt.terminal.onMcpToolCall?.((d) => publishActivity(() => agentCallEvent(d)));
    const offScript = window.krypt.scripts.onStatus((d) => publishActivity(() => (
      d.enabled ? null : {
        kind: 'script', op: 'autoDisabled', name: null, id: d.id, ok: false, errors: null,
        detail: d.lastError ?? null,
      })));
    return () => { offAgent(); offCalls?.(); offScript(); };
  }, []);

  const auto = autoOnboarding(state);

  return (
    <GuideHost needsOnboarding={auto === 'first'} needsUpdateOnboarding={auto === 'update'} setPage={setPage}>
    <div className="flex h-full w-full flex-col">
      <GlassBackdrop />
      <TitleBar />
      <div className="relative flex h-[calc(100%-2.25rem)] w-full">
        <Sidebar page={page} setPage={setPage} />
        <main className="relative flex flex-1 flex-col overflow-hidden">
          <TopBar />
          <Crypto15mLiveBanner />
          <div className="flex-1 overflow-hidden">
            <PageGuard page={page} setPage={setPage} onCrash={onPageCrash}>
              <PageRouter page={page} setPage={setPage} />
            </PageGuard>
          </div>
        </main>
      </div>
    </div>
    </GuideHost>
  );
}

function PageRouter({ page, setPage }: { page: PageId; setPage: (p: PageId) => void }) {
  switch (page) {
    case 'dashboard': return <DashboardPage onNav={setPage} />;
    case 'strategies': return <StrategiesPage onNav={setPage} />;
    case 'positions': return <PositionsPage />;
    case 'signals': return <SignalsPage />;
    case 'history': return <HistoryPage />;
    case 'profiles': return <ProfilesPage />;
    case 'settings': return <SettingsPage />;
    case 'api': return <ApiKeysPage />;
    case 'logs': return <LogsPage />;
    case 'guide': return <GuidePage />;
    case 'about': return <AboutPage />;
    case 'visualizer': return <VisualizerPage />;
    case 'crypto15m': return <Crypto15mPage />;
    case 'perps': return <PerpsPage />;
    case 'backtest': return <BacktestPage />;
    case 'scripts': return <ScriptsPage />;
    case 'terminal': return <TerminalPage onNav={setPage} />;
    case 'terminalPortfolio': return <TerminalPortfolioPage />;
    case 'privacy': return <PrivacyPage />;
    case 'remote': return <RemotePage />;
    case 'aiAgents': return <AiAgentsPage onNav={setPage} />;
    default: return <AiAgentsPage onNav={setPage} />;
  }
}
