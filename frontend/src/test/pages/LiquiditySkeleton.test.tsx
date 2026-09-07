import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import LiquidityPage from '@/app/dashboard/liquidity/page';

const fetchPortfolioMock = vi.fn().mockResolvedValue(undefined);

let liquidityDeferred: {
  promise: Promise<unknown>;
  resolve: (v: unknown) => void;
  reject: (e: unknown) => void;
} | null = null;

const getLiquidityMetricsMock = vi.fn(() => {
  let resolve!: (v: unknown) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<unknown>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  liquidityDeferred = { promise, resolve, reject };
  return promise;
});

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getLiquidityMetrics: (...args: unknown[]) => getLiquidityMetricsMock(...(args as [])),
  },
}));

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({ positions: [], fetchPortfolio: fetchPortfolioMock }),
}));

const LoadedPayload = {
  overall_score: 8.2,
  liquidation_time_days: '1-2',
  risk_level: 'Low',
  by_position: {
    'RELIANCE.NS': {
      score: 8.5,
      category: 'High',
      avg_volume: 5000000,
      avg_turnover: 1000000000,
      market_cap: 1000000000000,
      spread: 0.0004,
      liquidation_days: '1-2',
    },
  },
  volume_stats: {
    avg_volume: 5000000,
    total_portfolio_volume: 5000000,
    high_volume_pct: 100,
    medium_volume_pct: 0,
    low_volume_pct: 0,
  },
};

describe('LiquidityPage — first-load skeleton (never 0.0/10)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    liquidityDeferred = null;
  });

  it('shows a loading skeleton — not "0.0/10" with a blank body — while fetching', async () => {
    render(<LiquidityPage />);

    await waitFor(() => {
      expect(getLiquidityMetricsMock).toHaveBeenCalled();
    });

    // No fabricated zero score on first load
    expect(screen.queryByText('0.0/10')).toBeNull();
    // Header badge shows a skeleton until the payload lands
    expect(screen.getByLabelText('Loading overall score')).toBeDefined();
  });

  it('renders the live score once loaded', async () => {
    render(<LiquidityPage />);

    await waitFor(() => {
      expect(liquidityDeferred).not.toBeNull();
    });
    liquidityDeferred!.resolve(LoadedPayload);

    await waitFor(() => {
      // Header badge + Overall Liquidity Score card both show the live value
      expect(screen.getAllByText('8.2/10').length).toBeGreaterThan(0);
    });
    expect(screen.queryByLabelText('Loading overall score')).toBeNull();
  });
});
