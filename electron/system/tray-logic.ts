export type TrayTradingAction = 'pause' | 'resume' | 'open';

export function trayTradingAction(trading: boolean, live: boolean): TrayTradingAction {
  if (trading) return 'pause';
  return live ? 'open' : 'resume';
}

export function trayTradingLabel(trading: boolean, live: boolean): string {
  const a = trayTradingAction(trading, live);
  if (a === 'pause') return live ? 'Pause Trading (Live)' : 'Pause Trading (Paper)';
  if (a === 'open') return 'Resume Live Trading… (opens the app)';
  return 'Resume Trading (Paper)';
}

export const TRAY_HINT = {
  title: 'Krypt Trader is still running',
  body: 'Closing the window keeps the app (and any trading you switched on) running in the tray. '
    + 'To stop it completely, right-click the tray icon → Quit, or use Quit in the app\'s title bar.',
};
