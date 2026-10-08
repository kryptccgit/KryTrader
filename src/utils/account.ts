import type { AccountMode, BookEnv, TraderConfig } from '@shared/types';


type Cfg = Partial<Pick<TraderConfig, 'accountMode'>> | null | undefined;

export function isLive(c: Cfg): boolean {
  return c?.accountMode === 'live';
}

export function accountModeOf(c: Cfg): AccountMode {
  return isLive(c) ? 'live' : 'paper';
}

export function bookEnvOf(c: Cfg): BookEnv {
  return isLive(c) ? 'production' : 'paper';
}

export const BOOK_LABEL: Record<BookEnv, string> = {
  paper: 'Paper',
  production: 'Live',
  demo: 'Kalshi demo (retired)',
};

export const MODE_LABEL: Record<AccountMode, string> = {
  paper: 'Paper',
  live: 'Live',
};
