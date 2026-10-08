import { useMemo } from 'react';
import { useApp } from './AppStateProvider';
import { balanceView, type BalanceView } from '../utils/balance';

export function useBalance(): BalanceView {
  const { account, config, backend, credentialsAll } = useApp();
  const prod = credentialsAll?.production;
  const hasKeys = credentialsAll ? !!prod?.hasApiKey && !!prod?.hasRsaKey : null;
  const engineRunning = backend ? backend.status === 'running' : undefined;
  return useMemo(
    () => balanceView(account, { config, authOk: !!backend?.authOk, hasKeys, engineRunning }),
    [account, config, backend?.authOk, hasKeys, engineRunning],
  );
}
