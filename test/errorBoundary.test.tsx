import { Suspense, useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PageGuard, usePersistedPage } from '../src/components/PageGuard';
import { LAST_PAGE_KEY, loadLastPage, type PageId } from '../src/state/lastPage';
import { guarded } from '../src/hub/views';


function Bomb({ message = 'scene exploded' }: { message?: string }): JSX.Element {
  throw new Error(message);
}

function Shell() {
  const [page, setPage, onCrash] = usePersistedPage();
  return (
    <div>
      <div data-testid="chrome">Pause</div>
      <PageGuard page={page} setPage={setPage} onCrash={onCrash}>
        {page === 'visualizer' ? <Bomb /> : <div data-testid="page">{page}</div>}
      </PageGuard>
    </div>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  window.localStorage.clear();
});

describe('a page that crashes', () => {
  it('is contained, shows the error and leaves the chrome alive', () => {
    window.localStorage.setItem(LAST_PAGE_KEY, 'visualizer');
    render(<Shell />);
    expect(screen.getByRole('alert').textContent).toContain('This page crashed');
    expect(screen.getByRole('alert').textContent).toContain('scene exploded');
    expect(screen.getByTestId('chrome')).toBeTruthy();
  });

  it('is never remembered as the page to reopen, so the next launch cannot loop', () => {
    window.localStorage.setItem(LAST_PAGE_KEY, 'visualizer');
    render(<Shell />);
    expect(window.localStorage.getItem(LAST_PAGE_KEY)).toBeNull();
    expect(loadLastPage()).toBe('aiAgents');
  });

  it('goes to the Dashboard, which is then remembered normally', () => {
    window.localStorage.setItem(LAST_PAGE_KEY, 'visualizer');
    render(<Shell />);
    fireEvent.click(screen.getByText('Go to Dashboard'));
    expect(screen.getByTestId('page').textContent).toBe('dashboard');
    expect(window.localStorage.getItem(LAST_PAGE_KEY)).toBe('dashboard');
  });

  it('offers AI Agents instead when the Dashboard is what crashed', () => {
    function DashBomb() {
      const [page, setPage] = useState<PageId>('dashboard');
      return (
        <PageGuard page={page} setPage={setPage} onCrash={() => {}}>
          {page === 'dashboard' ? <Bomb /> : <div data-testid="page">{page}</div>}
        </PageGuard>
      );
    }
    render(<DashBomb />);
    fireEvent.click(screen.getByText('Go to AI Agents'));
    expect(screen.getByTestId('page').textContent).toBe('aiAgents');
  });

  it('a healthy page is remembered as before', () => {
    window.localStorage.setItem(LAST_PAGE_KEY, 'settings');
    render(<Shell />);
    expect(screen.getByTestId('page').textContent).toBe('settings');
    expect(window.localStorage.getItem(LAST_PAGE_KEY)).toBe('settings');
  });
});

describe('the stored page id', () => {
  it('opens the front door for an id this build does not know, and forgets it', () => {
    window.localStorage.setItem(LAST_PAGE_KEY, 'leaderboard');
    expect(loadLastPage()).toBe('aiAgents');
    expect(window.localStorage.getItem(LAST_PAGE_KEY)).toBeNull();
  });

  it('opens the front door when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(loadLastPage()).toBe('aiAgents');
  });
});

describe('a 3D scene that cannot run', () => {
  it('says "3D view unavailable" when the scene throws (WebGL refused)', async () => {
    const Scene = guarded(async () => ({ default: () => <Bomb message="WebGL context could not be created" /> }));
    render(
      <div>
        <Suspense fallback={<div>Loading…</div>}><Scene /></Suspense>
        <div data-testid="pots">pots</div>
      </div>,
    );
    await act(async () => { await Promise.resolve(); });
    expect(await screen.findByText('3D view unavailable')).toBeTruthy();
    expect(screen.getByText(/WebGL context could not be created/)).toBeTruthy();
    expect(screen.getByTestId('pots')).toBeTruthy();
  });

  it('says so when its chunk fails to load', async () => {
    const Scene = guarded(() => Promise.reject(new Error('Failed to fetch dynamically imported module')));
    render(<Suspense fallback={<div>Loading…</div>}><Scene /></Suspense>);
    expect(await screen.findByText('3D view unavailable')).toBeTruthy();
    expect(screen.getByText(/Failed to fetch/)).toBeTruthy();
  });
});
