import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, renderHook, act } from '@testing-library/react';
import React from 'react';
import RouteError from '@/app/error';
import NotFound from '@/app/not-found';
import { useNotifications } from '@/hooks/useRealTime';

// eslint-disable-next-line @next/next/no-html-link-for-pages
vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

describe('Route error boundaries', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('error.tsx shows the error message and calls reset on Try again', () => {
    const reset = vi.fn();
    render(<RouteError error={new Error('boom')} reset={reset} />);
    expect(screen.getByText('boom')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Try again'));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it('error.tsx falls back to a generic message when error has no message', () => {
    const reset = vi.fn();
    render(<RouteError error={{ message: '' } as Error} reset={reset} />);
    expect(
      screen.getByText('An unexpected error occurred while loading this page.')
    ).toBeInTheDocument();
  });

  it('not-found.tsx renders a 404 heading and a link back to the dashboard', () => {
    render(<NotFound />);
    expect(screen.getByText(/404/)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /back to dashboard/i });
    expect(link).toHaveAttribute('href', '/dashboard');
  });
});

describe('useNotifications error channel (06-B3 handoff)', () => {
  afterEach(() => {
    const { result } = renderHook(() => useNotifications());
    act(() => {
      result.current.clearAll();
    });
  });

  it('addNotification("error", ...) surfaces in the store for pages to use', () => {
    const { result } = renderHook(() => useNotifications());
    act(() => {
      result.current.addNotification(
        'error',
        'Fetch failed',
        'Backend unreachable',
        false
      );
    });
    expect(result.current.notifications).toContainEqual(
      expect.objectContaining({
        type: 'error',
        title: 'Fetch failed',
        message: 'Backend unreachable',
      })
    );
  });
});
