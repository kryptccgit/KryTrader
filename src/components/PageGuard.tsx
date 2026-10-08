import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ErrorBoundary, PageCrash } from './ErrorBoundary';
import {
  FRONT_DOOR, forgetLastPage, loadLastPage, saveLastPage, type PageId,
} from '../state/lastPage';

export function usePersistedPage(): [PageId, (p: PageId) => void, (p: PageId) => void] {
  const [page, setPage] = useState<PageId>(loadLastPage);
  const crashed = useRef<PageId | null>(null);
  useEffect(() => {
    if (crashed.current === page) return;
    crashed.current = null;
    saveLastPage(page);
  }, [page]);
  const onCrash = useCallback((p: PageId) => {
    crashed.current = p;
    forgetLastPage();
  }, []);
  return [page, setPage, onCrash];
}

export function PageGuard({
  page, setPage, onCrash, children,
}: {
  page: PageId;
  setPage: (p: PageId) => void;
  onCrash: (p: PageId) => void;
  children: ReactNode;
}) {
  const home: PageId = page === 'dashboard' ? FRONT_DOOR : 'dashboard';
  return (
    <ErrorBoundary
      key={page}
      onError={() => onCrash(page)}
      fallback={(error, reset) => (
        <PageCrash
          error={error}
          homeLabel={home === 'dashboard' ? 'Dashboard' : 'AI Agents'}
          onHome={() => setPage(home)}
          onRetry={reset}
        />
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
