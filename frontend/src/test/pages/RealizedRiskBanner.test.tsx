import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import RealizedRiskPage from '@/app/dashboard/realized-risk/page';

const updateLastUpdatedMock = vi.fn();

const realizedRisk = {
  portfolio: { max_drawdown: -0.02, var_95: -0.01, cvar_95: -0.015, hit_ratio: 0.5 },
  positions: {},
  instrument_risk: {
    portfolio: { annual_return: 0.1, annual_volatility: 0.2, sharpe_ratio: 0.5, sortino_ratio: 0.6 },
    positions: {},
  },
  warnings: [
    {
      ticker: 'OLD.NS',
      data_points: 24,
      message:
        'OLD.NS realized P&L covers 25 trading days since 2026-08-04; OLD.NS held since 2020-01-01; instrument risk uses full 252 trading days of exchange history.',
    },
    {
      ticker: 'NEW.NS',
      data_points: 24,
      message:
        'NEW.NS realized P&L covers only 24 trading days (held since 2026-08-04); instrument risk metrics use the full 252 trading days of exchange history.',
    },
  ],
  data_range: { start: '2025-01-01', end: '2026-09-07' },
  history_coverage: {
    requested_start: '2025-01-01',
    effective_start: '2026-08-04',
    intersection_start: '2026-08-04',
    oldest_holding: '2020-01-01',
    covered_days: 25,
    truncated: true,
    full_history_days: 252,
    full_history_start: '2025-06-01',
    tickers: {
      'OLD.NS': { effective_start: '2020-01-01', raw_days: 300, masked_days: 25 },
      'NEW.NS': { effective_start: '2026-08-04', raw_days: 300, masked_days: 25 },
    },
  },
  methodology: 'test',
};

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: [{ ticker: 'OLD.NS' }, { ticker: 'NEW.NS' }],
    fetchPortfolio: vi.fn().mockResolvedValue(undefined),
    isLoading: false,
    error: null,
    totalValue: 0,
  }),
  useUIStore: () => ({ lastUpdated: null, updateLastUpdated: updateLastUpdatedMock }),
}));

vi.mock('@/hooks/useAnalytics', () => ({
  usePortfolioAnalytics: () => ({
    data: { realizedRisk },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
  usePerformanceData: () => ({ performanceData: [], loading: false }),
}));

describe('RealizedRiskPage — Phase 2 intersection banner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows ONE summary banner with the intersection copy, detail hidden until expanded', async () => {
    render(<RealizedRiskPage />);

    const banner = await screen.findByTestId('coverage-banner');
    expect(banner.textContent).toMatch(/Realized P&L covers 25 trading days since 2026-08-04/);
    expect(banner.textContent).toMatch(/1 of 2 positions held longer/);
    expect(banner.textContent).toMatch(/instrument risk uses full 252d/);
    expect(screen.getByTestId('coverage-caption').textContent).toBe('{2026-08-04 · 252d raw}');

    // Bullet wall collapsed: per-ticker messages not visible yet.
    expect(screen.queryByTestId('coverage-details')).toBeNull();
    expect(screen.queryByText(/held since 2020-01-01/)).toBeNull();

    fireEvent.click(screen.getByTestId('coverage-details-toggle'));

    await waitFor(() => {
      expect(screen.getByTestId('coverage-details')).toBeDefined();
    });
    expect(screen.getByText(/held since 2020-01-01/)).toBeDefined();
  });
});
