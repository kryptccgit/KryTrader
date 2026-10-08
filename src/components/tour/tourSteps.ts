import type { PageId } from '../../state/lastPage';


export type TourSide = 'right' | 'left' | 'bottom' | 'top';

export interface TourStep {
  id: string;
  group: string;
  title: string;
  body: string;
  page?: PageId;
  prefer?: TourSide[];
}

export const navTourId = (page: PageId): string => `nav-${page}`;

const nav = (page: PageId, group: string, title: string, body: string): TourStep => ({
  id: navTourId(page), group, title, body, page,
});

const HEADER_SIDES: TourSide[] = ['bottom', 'left', 'right', 'top'];

export const TOUR_STEPS: TourStep[] = [
  nav('aiAgents', 'Agents', 'AI Agents',
    'Connect the AI agent you already use (Claude Code, Cursor, Claude Desktop or Codex), or the in-app Autopilot. '
    + 'Agents start on paper, and a scoreboard checks whether their forecasts beat the market price.'),
  nav('visualizer', 'Agents', 'Agent Hub',
    'A live 3D view of what your agents and the bot are doing: tool calls, forecasts, signals and trades. '
    + 'It only shows activity; nothing on it places an order.'),

  nav('terminal', 'Manual', 'Terminal',
    'Browse every Kalshi market, read its chart and resolution rules, and trade by hand. '
    + 'A good first stop if you want to look around before automating anything.'),
  nav('terminalPortfolio', 'Manual', 'My Book',
    'Every position and resting order in the account the app is using, whoever placed it: '
    + 'the paper book in Paper mode, your real Kalshi account in Live.'),
  nav('remote', 'Manual', 'Remote',
    'Pair a Discord or Telegram bot to check on the app from your phone while it runs here. '
    + 'Trading from the phone is a separate permission, off by default, and every order needs a confirmation code.'),

  nav('dashboard', 'Automation', 'Dashboard',
    'A snapshot of the built-in bot: portfolio, recent signals and bot health. '
    + 'It is most useful once you have switched the bot on.'),
  nav('strategies', 'Automation', 'Strategies',
    'Saved snapshots of the bot\'s settings that you or your AI made, to switch between. '
    + 'None has a proven edge, so try anything new in Paper first.'),
  nav('positions', 'Automation', 'Positions',
    'The bot\'s open and recent positions, with a Cancel All button that pulls any working orders on Kalshi.'),
  nav('signals', 'Automation', 'Signals',
    'Whale and momentum signals as the scanners find them. '
    + 'A signal is a reason to look at a market, not a promise it will pay.'),
  nav('crypto15m', 'Automation', '15m Crypto',
    'Kalshi\'s 15-minute crypto markets, with their own engine and their own live switch, off by default. '
    + 'Most presets here are experimental; check one on Backtest before arming it.'),
  nav('perps', 'Automation', 'Perpetuals',
    'Kalshi perpetual futures. The one tool here farms volume for Kalshi\'s one-time perps signup reward '
    + 'on a loss budget; it is not a profit strategy.'),
  nav('scripts', 'Automation', 'Scripts',
    'Write your own strategies in Python, or have an AI draft them, then backtest them and run them sandboxed under money rails. '
    + 'Live scripts have their own switch, off by default.'),
  nav('backtest', 'Automation', 'Backtest',
    'Test a strategy against the market ticks and signals this app has recorded, with the same entry gates as live and real Kalshi fees. '
    + 'The history only grows while the app is running.'),
  nav('history', 'Automation', 'History',
    'The bot\'s session diary, one summary per run, and the full ledger of its settled trades.'),
  nav('profiles', 'Automation', 'Profiles',
    'Save, export and import snapshots of the bot\'s settings, including separate ones for 15m crypto, and switch between them.'),

  nav('settings', 'System', 'Settings',
    'Every knob the main bot has, from Paper or Live to sizing, risk and trading hours. '
    + 'Changes apply immediately, and Replay onboarding lives here too.'),
  nav('api', 'System', 'API Keys',
    'Your Kalshi API key, needed only to trade Live — Paper needs none. It stays on this computer.'),
  nav('logs', 'System', 'Logs',
    'A live tail of the backend\'s log. The first place to look when something is not doing what you expected.'),
  nav('privacy', 'System', 'Privacy',
    'Every host this app can contact, what it is for, and how often it actually has. The app reports nothing home.'),
  nav('guide', 'System', 'Guide',
    'How the app works and what each setting does, in more depth than this tour.'),
  nav('about', 'System', 'About',
    'Version, links, support and credits.'),

  {
    id: 'wallet', group: 'Status', title: 'Wallet',
    body: 'Your balance: cash plus positions. The pill says which book it is: PAPER is imaginary money on Kalshi\'s real prices, LIVE is your real Kalshi account.',
  },
  {
    id: 'engine-status', group: 'Status', title: 'What is armed',
    body: 'PAUSED when nothing trades by itself; otherwise PAPER or LIVE, followed by each armed engine. Hover it for the details.',
  },
  {
    id: 'trading-toggle', group: 'Header', title: 'Start / Pause trading',
    body: 'Starts or pauses the main bot. Pause stops that bot only: agents, scripts and 15m runners each have their own switch.',
    prefer: HEADER_SIDES,
  },
  {
    id: 'tour-info', group: 'Header', title: 'Replay this tour',
    body: 'Click this any time to take the tour again. To see the first-run setup again, use Replay onboarding in Settings.',
    prefer: HEADER_SIDES,
  },
];
