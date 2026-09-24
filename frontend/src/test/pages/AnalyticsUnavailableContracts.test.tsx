import { act, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ConcentrationPage from '@/app/dashboard/concentration/page';
import LiquidityPage from '@/app/dashboard/liquidity/page';

const mocks = vi.hoisted(() => ({
  positions: [] as any[],
  fetchPortfolio: vi.fn(),
  updateLastUpdated: vi.fn(),
  getConcentrationMetrics: vi.fn(),
  getLiquidityMetrics: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getConcentrationMetrics: mocks.getConcentrationMetrics,
    getLiquidityMetrics: mocks.getLiquidityMetrics,
  },
}));

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: mocks.positions,
    fetchPortfolio: mocks.fetchPortfolio,
  }),
  useUIStore: Object.assign(
    () => ({ lastUpdated: null }),
    { getState: () => ({ updateLastUpdated: mocks.updateLastUpdated }) },
  ),
}));

const zeroConcentration = {
  largest_position: 0,
  top_3: 0,
  top_5: 0,
  top_10: 0,
  herfindahl_index: 0,
  effective_positions: 0,
  diversification_score: 0,
  diversification_ratio: 1,
  gini_coefficient: 0,
  by_weight: {},
  by_sector: {},
  error: 'No portfolio positions found',
  zero_metrics: true,
};

const zeroLiquidity = {
  overall_score: 5,
  liquidation_time_days: '5-10',
  risk_level: 'Medium',
  by_position: {},
  volume_stats: {
    avg_volume: 0,
    total_portfolio_volume: 0,
    high_volume_pct: 0,
    medium_volume_pct: 0,
    low_volume_pct: 100,
  },
  error: 'No portfolio positions found',
  zero_metrics: true,
};

const loadedConcentration = {
  ...zeroConcentration,
  largest_position: 0.4,
  top_3: 0.8,
  top_5: 1,
  top_10: 1,
  herfindahl_index: 0.3,
  effective_positions: 3.33,
  diversification_score: 25,
  by_weight: { 'A.NS': 0.4, 'B.NS': 0.4, 'C.NS': 0.2 },
  by_sector: { Technology: 1 },
  error: undefined,
  zero_metrics: false,
};

const loadedLiquidity = {
  ...zeroLiquidity,
  overall_score: 8.2,
  liquidation_time_days: '1-2',
  risk_level: 'Low',
  by_position: {
    'A.NS': {
      score: 8.5,
      category: 'High',
      avg_volume: 1_000_000,
      avg_turnover: 100_000_000,
      market_cap: 1_000_000_000_000,
      spread: 0.0004,
      liquidation_days: '1-2',
    },
  },
  volume_stats: {
    avg_volume: 1_000_000,
    total_portfolio_volume: 1_000_000,
    high_volume_pct: 100,
    medium_volume_pct: 0,
    low_volume_pct: 0,
  },
  error: undefined,
  zero_metrics: false,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [];
  mocks.fetchPortfolio.mockResolvedValue(undefined);
  mocks.getConcentrationMetrics.mockReset();
  mocks.getLiquidityMetrics.mockReset();
});

describe('HTTP-200 unavailable analytics contracts', () => {
  it('treats concentration zero_metrics as unavailable, not a safe portfolio', async () => {
    mocks.getConcentrationMetrics.mockResolvedValue(zeroConcentration);

    render(<ConcentrationPage />);

    await waitFor(() => {
      expect(screen.getByText('No portfolio positions found')).toBeDefined();
    });

    expect(screen.getByText('N/A of 0')).toBeDefined();
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
    expect(screen.queryByText('0.0%')).toBeNull();
    expect(screen.queryByText('Well Diversified')).toBeNull();
    expect(screen.queryByText('Monitor Closely')).toBeNull();
    expect(screen.queryByText('Risk Managed')).toBeNull();
    expect(screen.queryByText('Controlled Single Position Allocation')).toBeNull();
    expect(screen.queryByText(/safely below the 15%/)).toBeNull();
    expect(mocks.updateLastUpdated).not.toHaveBeenCalled();
  });

  it('treats liquidity zero_metrics as unavailable, not a risk score or safe exit claim', async () => {
    mocks.getLiquidityMetrics.mockResolvedValue(zeroLiquidity);

    render(<LiquidityPage />);

    await waitFor(() => {
      expect(screen.getByText('No portfolio positions found')).toBeDefined();
    });

    expect(screen.getAllByText('N/A').length).toBeGreaterThanOrEqual(4);
    expect(screen.queryByText('5.0/10')).toBeNull();
    expect(screen.queryByText('5-10 days')).toBeNull();
    expect(screen.queryByText('Medium')).toBeNull();
    expect(screen.queryByText('HIGH RISK')).toBeNull();
    expect(screen.queryByText('MEDIUM RISK')).toBeNull();
    expect(screen.queryByText('0 (0.0%)')).toBeNull();
    expect(screen.queryByText(/healthy trading depth/)).toBeNull();
  });
});

describe('analytics request lifecycle', () => {
  it('coalesces duplicate concentration requests while the first is in flight', async () => {
    const request = deferred<typeof loadedConcentration>();
    mocks.positions = [{ ticker: 'A.NS', weight: 0.5, last_price: 100 }];
    mocks.getConcentrationMetrics.mockImplementation(() => request.promise);

    render(<ConcentrationPage />);
    await waitFor(() => expect(mocks.getConcentrationMetrics).toHaveBeenCalled());
    const callsWhilePending = mocks.getConcentrationMetrics.mock.calls.length;

    await act(async () => request.resolve(loadedConcentration));

    expect(callsWhilePending).toBe(1);
  });

  it('coalesces duplicate liquidity requests while the first is in flight', async () => {
    const request = deferred<typeof loadedLiquidity>();
    mocks.positions = [{ ticker: 'A.NS', weight: 1, last_price: 100 }];
    mocks.getLiquidityMetrics.mockImplementation(() => request.promise);

    render(<LiquidityPage />);
    await waitFor(() => expect(mocks.getLiquidityMetrics).toHaveBeenCalled());
    const callsWhilePending = mocks.getLiquidityMetrics.mock.calls.length;

    await act(async () => request.resolve(loadedLiquidity));

    expect(callsWhilePending).toBe(1);
  });
});
