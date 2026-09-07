import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import SettingsPage from '@/app/dashboard/settings/page';

const updateConfigMock = vi.fn().mockResolvedValue({
  primary_source: 'bfinance',
  cache_ttl_minutes: 60,
  enable_cache: true,
});
const clearCacheMock = vi.fn().mockResolvedValue({
  cleared: { stock_timeseries: 1520, analytics_cache: 12, fetch_logs: 40 },
  total_rows_cleared: 1572,
  portfolio_preserved: true,
});
const getConfigMock = vi.fn().mockResolvedValue({
  primary_source: 'bfinance',
  cache_ttl_minutes: 60,
  enable_cache: true,
});

vi.mock('@/lib/api', () => ({
  dataApi: {
    getConfig: (...args: unknown[]) => getConfigMock(...(args as [])),
    updateConfig: (...args: unknown[]) => updateConfigMock(...(args as [])),
    clearCache: (...args: unknown[]) => clearCacheMock(...(args as [])),
  },
}));

vi.mock('@/lib/store', () => ({
  useUIStore: () => ({ darkMode: true, toggleDarkMode: vi.fn() }),
  usePortfolioStore: () => ({ fetchPortfolio: vi.fn().mockResolvedValue(undefined) }),
}));

describe('SettingsPage — data source preference & cache purge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.confirm = vi.fn(() => true);
  });

  it('loads persisted primary source and renders the fallback chain', async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(getConfigMock).toHaveBeenCalled();
    });

    // Default (persisted) source is bfinance -> chain explainer reflects it
    await waitFor(() => {
      expect(screen.getByText(/bfinance → yfinance → Alpha Vantage/)).toBeDefined();
    });
    expect(screen.getByText('Clear Market Data Cache')).toBeDefined();
    expect(screen.getByText(/Portfolio holdings \(tickers, quantities, avg buy prices\) are never touched/)).toBeDefined();
  });

  it('persists yfinance as primary on save', async () => {
    render(<SettingsPage />);

    // Switch primary source to yfinance (second source card)
    const yfCard = await waitFor(() => screen.getByText('yfinance'));
    fireEvent.click(yfCard);

    await waitFor(() => {
      expect(screen.getByText(/yfinance → bfinance → Alpha Vantage/)).toBeDefined();
    });

    fireEvent.click(screen.getByText('Save Preferences'));

    await waitFor(() => {
      expect(updateConfigMock).toHaveBeenCalledWith({ primary_source: 'yfinance' });
    });
  });

  it('purges cache on confirm and reports counts with holdings preserved', async () => {
    render(<SettingsPage />);

    fireEvent.click(await screen.findByText('Clear Market Data Cache'));

    await waitFor(() => {
      expect(clearCacheMock).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(screen.getByText(/Cleared 1,572 cached rows/)).toBeDefined();
    });
    expect(screen.getByText(/Portfolio holdings preserved/)).toBeDefined();
    expect(screen.getByText(/stock_timeseries: 1,520/)).toBeDefined();
  });

  it('does not purge when the confirm dialog is dismissed', async () => {
    window.confirm = vi.fn(() => false);
    render(<SettingsPage />);

    fireEvent.click(await screen.findByText('Clear Market Data Cache'));

    expect(clearCacheMock).not.toHaveBeenCalled();
  });
});
