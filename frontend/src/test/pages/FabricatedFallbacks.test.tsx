import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  positions: [] as any[],
  fetchPortfolio: vi.fn().mockResolvedValue(undefined),
  updateLastUpdated: vi.fn(),
  getFactorExposure: vi.fn(),
  getForecastRisk: vi.fn(),
  getVolatilitySizing: vi.fn(),
  getConcentrationMetrics: vi.fn(),
  apiGet: vi.fn(),
}));

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: mocks.positions,
    fetchPortfolio: mocks.fetchPortfolio,
    isLoading: false,
    error: null,
    totalValue: 0,
  }),
  useUIStore: Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: mocks.updateLastUpdated }),
    { getState: () => ({ updateLastUpdated: mocks.updateLastUpdated }) }
  ),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getFactorExposure: mocks.getFactorExposure,
    getForecastRisk: mocks.getForecastRisk,
    getVolatilitySizing: mocks.getVolatilitySizing,
    getConcentrationMetrics: mocks.getConcentrationMetrics,
  },
  portfolioApi: { rebalancePortfolio: vi.fn() },
  default: { get: mocks.apiGet },
}));

import FactorExposurePage from '@/app/dashboard/factor-exposure/page';
import ForecastRiskPage from '@/app/dashboard/forecast-risk/page';
import VolatilitySizingPage from '@/app/dashboard/volatility-sizing/page';
import RiskStudioPage from '@/app/dashboard/risk-studio/page';
import ConcentrationPage from '@/app/dashboard/concentration/page';

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [];
});

describe('fabricated fallbacks — factor exposure nulls render N/A', () => {
  it('null beta / r_squared / alpha render N/A, never β=1.0 or 0.679/1.083 constants', async () => {
    mocks.getFactorExposure.mockResolvedValue({
      portfolio: { market: null, alpha: null, annualized_alpha: null },
      positions: {
        'RELIANCE.NS': { market: null, alpha: null, annualized_alpha: null },
      },
      r_squared: null,
      adjusted_r_squared: null,
      lookback_days: 252,
    });

    render(<FactorExposurePage />);

    await waitFor(() => {
      expect(mocks.getFactorExposure).toHaveBeenCalled();
    });
    await waitFor(() => {
      // Position table beta cell + sensitivity badge both fall back to N/A.
      expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
    });

    // Fabricated constants must not appear anywhere.
    expect(screen.queryByText('1.083')).toBeNull();
    expect(screen.queryByText('0.679')).toBeNull();
    // No β=1.000 row for missing data.
    expect(screen.queryByText('+1.000')).toBeNull();
    expect(screen.queryByText('1.000')).toBeNull();
  });
});

describe('fabricated fallbacks — forecast error banner + guarded curve', () => {
  it('renders the backend error field as an amber warning banner', async () => {
    mocks.getForecastRisk.mockResolvedValue({
      model: 'GARCH',
      horizon: 1,
      portfolio: { volatility_forecast: null, var_forecast: null, cvar_forecast: null },
      positions: {},
      error: 'Insufficient history for forecast',
    });

    render(<ForecastRiskPage />);

    await waitFor(() => {
      expect(screen.getByTestId('forecast-error-banner')).toBeDefined();
    });
    expect(screen.getByText('Insufficient history for forecast')).toBeDefined();
  });

  it('hides the projection-curve block on null base instead of a synthetic 20% curve', async () => {
    mocks.getForecastRisk.mockResolvedValue({
      model: 'GARCH',
      horizon: 1,
      portfolio: { volatility_forecast: null, var_forecast: null, cvar_forecast: null },
      positions: {},
    });

    render(<ForecastRiskPage />);

    await waitFor(() => {
      expect(screen.getByTestId('forecast-curve-empty')).toBeDefined();
    });
    // Metric cards stay honest.
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
  });

  it('null position vol renders N/A risk level, not a 20%-derived Low', async () => {
    mocks.getForecastRisk.mockResolvedValue({
      model: 'GARCH',
      horizon: 1,
      portfolio: { volatility_forecast: 0.2, var_forecast: -0.03, cvar_forecast: -0.04 },
      positions: {
        'X.NS': { volatility_forecast: null, var_forecast: null },
      },
    });

    render(<ForecastRiskPage />);

    await waitFor(() => {
      expect(screen.getByText('X.NS')).toBeDefined();
    });
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
    // Risk level for the null-vol row is N/A, never a fabricated Low/Medium/High.
    expect(screen.queryByText('Low')).toBeNull();
  });
});

describe('fabricated fallbacks — volatility sizing null vol', () => {
  it('per-ticker null vol renders N/A, never a 20% order basis', async () => {
    mocks.positions = [{ ticker: 'X.NS', weight: 0.5 }];
    mocks.getVolatilitySizing.mockResolvedValue({
      current_weights: { 'X.NS': 0.5 },
      recommended_weights: { 'X.NS': 0.5 },
      trades: {},
      target_volatility: 0.15,
      volatilities: {},
    });

    render(<VolatilitySizingPage />);

    await waitFor(() => {
      expect(mocks.getVolatilitySizing).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getAllByText('X.NS').length).toBeGreaterThan(0);
    });
    // No fabricated 20.0% volatility for the null-vol ticker
    // (the '20.0% Preset' button carries a suffix, so an exact match is a fabrication).
    expect(screen.queryByText('20.0%', { exact: true })).toBeNull();
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
  });
});

describe('fabricated fallbacks — risk studio nulls', () => {
  it('null realized vol and null correlation render N/A, never 18.08 / 0.382 / 0.158', async () => {
    mocks.apiGet.mockImplementation((url: string) => {
      if (url.includes('risk-contribution')) {
        return Promise.resolve({ data: { positions: { volatility: {}, cvar_tail: {} } } });
      }
      if (url.includes('tail-dependence')) return Promise.resolve({ data: {} });
      if (url.includes('vol-cone')) {
        return Promise.resolve({ data: { quantiles: { '10': {} } } });
      }
      if (url.includes('correlation-stability')) return Promise.resolve({ data: {} });
      return Promise.resolve({ data: {} });
    });

    render(<RiskStudioPage />);

    await waitFor(() => {
      expect(screen.getByText('Rolling 60-Day Correlation Stability')).toBeDefined();
    });
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
    expect(screen.queryByText('18.08%')).toBeNull();
    expect(screen.queryByText('0.158')).toBeNull();
    expect(screen.queryByText('0.382')).toBeNull();
  });
});

describe('fabricated fallbacks — concentration null largest holding', () => {
  it('null largest_position renders the N/A state, never 13.9%', async () => {
    mocks.getConcentrationMetrics.mockResolvedValue({
      by_weight: {},
      by_sector: {},
    });

    render(<ConcentrationPage />);

    await waitFor(() => {
      expect(screen.getByTestId('largest-holding-na')).toBeDefined();
    });
    expect(screen.queryByText(/13\.9/)).toBeNull();
  });
});
