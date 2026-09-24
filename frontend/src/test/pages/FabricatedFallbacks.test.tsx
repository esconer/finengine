import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  positions: [] as any[],
  fetchPortfolio: vi.fn().mockResolvedValue(undefined),
  setPortfolioSnapshot: vi.fn(),
  setPositionCount: vi.fn(),
  updateLastUpdated: vi.fn(),
  getFactorExposure: vi.fn(),
  getForecastRisk: vi.fn(),
  getVolatilitySizing: vi.fn(),
  getConcentrationMetrics: vi.fn(),
  getRegime: vi.fn(),
  getRiskContribution: vi.fn(),
  runOptimization: vi.fn(),
  runStressTest: vi.fn(),
  apiGet: vi.fn(),
  getPortfolio: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/portfolio/manage',
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: mocks.positions,
    fetchPortfolio: mocks.fetchPortfolio,
    setPortfolioSnapshot: mocks.setPortfolioSnapshot,
    setPositionCount: mocks.setPositionCount,
    isLoading: false,
    error: null,
    totalValue: 0,
  }),
  useUIStore: Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: mocks.updateLastUpdated, liveDataMode: true }),
    { getState: () => ({ updateLastUpdated: mocks.updateLastUpdated }) }
  ),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getFactorExposure: mocks.getFactorExposure,
    getForecastRisk: mocks.getForecastRisk,
    getVolatilitySizing: mocks.getVolatilitySizing,
    getConcentrationMetrics: mocks.getConcentrationMetrics,
    getRegime: mocks.getRegime,
    getRiskContribution: mocks.getRiskContribution,
    runOptimization: mocks.runOptimization,
    runStressTest: mocks.runStressTest,
  },
  portfolioApi: { rebalancePortfolio: vi.fn(), exportCSV: vi.fn(), getPortfolio: mocks.getPortfolio },
  default: { get: mocks.apiGet },
}));

import FactorExposurePage from '@/app/dashboard/factor-exposure/page';
import ForecastRiskPage from '@/app/dashboard/forecast-risk/page';
import VolatilitySizingPage from '@/app/dashboard/volatility-sizing/page';
import RiskStudioPage from '@/app/dashboard/risk-studio/page';
import ConcentrationPage from '@/app/dashboard/concentration/page';
import PortfolioManagePage from '@/app/portfolio/manage/page';

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [];
});

describe('fabricated fallbacks — factor exposure nulls render N/A', () => {
  it('null beta / r_squared / alpha render N/A, never β=1.0 or 0.679/1.083 constants', async () => {
    // Page skips regression with an empty ticker list — needs live positions to fetch.
    mocks.positions = [{ ticker: 'RELIANCE.NS' }];
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

  it('fetch failure clears stale headline forecast data and surfaces a fetch error banner', async () => {
    mocks.getForecastRisk
      .mockResolvedValueOnce({
        model: 'GARCH',
        horizon: 1,
        portfolio: { volatility_forecast: 0.2, var_forecast: -0.03, cvar_forecast: -0.04 },
        positions: {},
      })
      .mockRejectedValueOnce(new Error('network down'));

    render(<ForecastRiskPage />);

    // First (successful) fetch renders the headline forecast.
    await waitFor(() => {
      expect(screen.getAllByText('20.00%').length).toBeGreaterThan(0);
    });

    // Changing horizon triggers the next fetch, which fails.
    fireEvent.click(screen.getByRole('button', { name: /5\s*days/i }));

    await waitFor(() => {
      expect(screen.getByTestId('forecast-fetch-error')).toBeDefined();
    });
    expect(screen.getByText('network down')).toBeDefined();
    // Stale headline data was cleared, not left showing the previous success.
    expect(screen.queryByText('20.00%')).toBeNull();
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

  it('failed rebalance surfaces an in-page error banner, not a native alert', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const { portfolioApi } = await import('@/lib/api');
    (portfolioApi.rebalancePortfolio as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('db locked')
    );
    mocks.positions = [{ ticker: 'X.NS', weight: 0.5 }];
    mocks.getVolatilitySizing.mockResolvedValue({
      current_weights: { 'X.NS': 0.5 },
      recommended_weights: { 'X.NS': 0.55 },
      trades: { 'X.NS': { shares_delta: 2, amount: 100 } },
      target_volatility: 0.15,
      volatilities: { 'X.NS': 0.18 },
    });

    render(<VolatilitySizingPage />);

    await waitFor(() => {
      expect(screen.getAllByText('X.NS').length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByText('Execute Rebalance'));
    fireEvent.click(screen.getByText('🧪 Run Simulation Test'));

    await waitFor(() => {
      expect(screen.getByTestId('rebalance-error')).toBeDefined();
    });
    expect(screen.getByText('Simulation failed: db locked')).toBeDefined();
    expect(alertSpy).not.toHaveBeenCalled();
    alertSpy.mockRestore();
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
    // B2/B3: no fabricated NORMAL regime when alert_level / is_regime_break are absent.
    expect(screen.queryByText('NORMAL')).toBeNull();
    expect(screen.queryByText('Diversified Regime')).toBeNull();
    // B5: no fabricated zero-filled vol cone when windows are missing.
    expect(screen.getByTestId('vol-cone-empty')).toBeDefined();
    // B8: unknown fat-tail conclusion renders an em dash, never a coerced Yes/No.
    const fatTailedRow = screen.getByText(/Fat Tailed:/);
    expect(fatTailedRow.textContent).toContain('—');
    expect(fatTailedRow.textContent).not.toContain('Yes');
    expect(fatTailedRow.textContent).not.toContain('No');
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

  it('null API data with live positions renders N/A hero, never 1.0 / HHI 0.09 / fabricated 0.0% divScore', async () => {
    mocks.positions = [
      { ticker: 'A.NS', weight: 0.5 },
      { ticker: 'B.NS', weight: 0.5 },
    ];
    mocks.getConcentrationMetrics.mockResolvedValue({
      by_weight: {},
      by_sector: {},
    });

    render(<ConcentrationPage />);

    await waitFor(() => {
      expect(screen.getByTestId('largest-holding-na')).toBeDefined();
    });
    // B6: hero Effective Positions never fabricates 1.0; B5: no hardcoded HHI 0.09;
    // B7: divScore with N>1 and no data is N/A, not a measured 0.0%.
    expect(screen.getByText('N/A of 2')).toBeDefined();
    expect(screen.queryByText('1.0 of 2')).toBeNull();
    expect(screen.queryByText(/0\.09/)).toBeNull();
    expect(screen.queryByText(/Diversification Score: 0\.0%/)).toBeNull();
    expect(screen.getByText(/HHI = N\/A/)).toBeDefined();
    // B19: no "Well Diversified" claim built from coerced zeros.
    expect(screen.queryByText('Well Diversified')).toBeNull();
  });

  it('fetch failure surfaces an error banner and clears fabricated success claims', async () => {
    mocks.getConcentrationMetrics.mockRejectedValue(new Error('boom'));

    render(<ConcentrationPage />);

    await waitFor(() => {
      expect(screen.getByText('boom')).toBeDefined();
    });
    expect(screen.queryByText('Well Diversified')).toBeNull();
    expect(screen.queryByText(/0\.09/)).toBeNull();
    expect(screen.queryByText('Risk Managed')).toBeNull();
  });
});

describe('mock-200 remainder — stress nulls render N/A, never hardcoded shocks', () => {
  it('empty results show N/A summary, never -41.9%/-17.3%/-27.9%', async () => {
    const { default: StressTestingPage } = await import('@/app/dashboard/stress-testing/page');

    render(<StressTestingPage />);

    await waitFor(() => {
      expect(screen.getByText('Stress Testing & Scenario Analysis')).toBeDefined();
    });
    // No scenario has run: summary cards must not show fabricated shocks.
    expect(screen.queryByText(/-41\.9/)).toBeNull();
    expect(screen.queryByText(/-17\.3/)).toBeNull();
    expect(screen.queryByText(/-27\.9/)).toBeNull();
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
    // B10: empty recovery never prints a confident 0.0-month average.
    expect(screen.queryByText(/0\.0 months/)).toBeNull();
    expect(screen.getByText(/No recovery data yet/)).toBeDefined();
    // B9: worst-case insight never hardcodes "Market Crash" with no data.
    expect(screen.getByText(/No scenario results yet/)).toBeDefined();
    expect(screen.queryByText(/under the Market Crash scenario/)).toBeNull();
  });

  it('missing confidence_level renders N/A, never a fabricated 95%', async () => {
    mocks.positions = [{ ticker: 'A.NS' }];
    mocks.runStressTest.mockResolvedValue({
      scenario: 'Market Crash',
      max_drawdown: -0.2,
      portfolio_impact: -0.18,
      position_impacts: { 'A.NS': -0.2 },
      recovery_time: 10,
    });

    const { default: StressTestingPage } = await import('@/app/dashboard/stress-testing/page');
    render(<StressTestingPage />);

    await waitFor(() => {
      expect(mocks.runStressTest).toHaveBeenCalledTimes(4);
    });
    await waitFor(() => {
      // Confidence rows on the four scenario cards: N/A, not 95%.
      expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
    });
    expect(screen.queryByText('95%')).toBeNull();
  });

  it('run failures surface a runError banner instead of failing silently', async () => {
    mocks.positions = [{ ticker: 'A.NS' }];
    mocks.runStressTest.mockRejectedValue(new Error('engine down'));

    const { default: StressTestingPage } = await import('@/app/dashboard/stress-testing/page');
    render(<StressTestingPage />);

    await waitFor(() => {
      expect(screen.getByText(/4 of 4 scenarios failed/)).toBeDefined();
    });
  });
});

describe('mock-200 remainder — null risk score renders N/A, never 0', () => {
  it('RiskMetricsDisplay with null risk_score shows N/A and no elevated alert', async () => {
    const { RiskMetricsDisplay } = await import('@/components/charts/RiskMetricsDisplay');

    const { container } = render(
      <RiskMetricsDisplay
        data={{
          risk_score: null,
          risk_level: 'Unknown',
          annual_volatility: null,
          sharpe_ratio: null,
          max_drawdown: 0,
          var_95: 0,
          cvar_95: 0,
        }}
      />
    );

    expect(container.textContent).toMatch(/N\/A/);
    expect(screen.queryByText('Risk Alert')).toBeNull();
  });
});

describe('fabricated fallbacks — portfolio manage null forecast', () => {
  it('null forecast renders N/A risk cells + surfaces backend error, never Low/Medium/High', async () => {
    mocks.getPortfolio.mockResolvedValue({
      positions: [
        {
          id: 1,
          ticker: 'X.NS',
          quantity: 10,
          buy_price: 100,
          last_price: 105,
          current_value: 1050,
          weight: 0.5,
          sector: 'Tech',
        },
      ],
      total_value: 1050,
      total_positions: 1,
      total_weight: 0.5,
      sectors: [],
    });
    mocks.getForecastRisk.mockResolvedValue({
      model: 'GARCH',
      horizon: 1,
      positions: { 'X.NS': { volatility_forecast: null, var_forecast: null } },
      error: 'Insufficient history for forecast',
    });

    render(<PortfolioManagePage />);

    await waitFor(() => {
      expect(screen.getAllByText('X.NS').length).toBeGreaterThan(0);
    });
    // Backend error contract is surfaced, never swallowed into a fake OK.
    await waitFor(() => {
      expect(screen.getByText('Insufficient history for forecast')).toBeDefined();
    });
    // Vol / VaR / risk cells fall back to N/A once the forecast settles.
    await waitFor(() => {
      expect(screen.getAllByText('N/A').length).toBeGreaterThanOrEqual(3);
    });
    // No fabricated risk classification for null volatility.
    expect(screen.queryByText('Low')).toBeNull();
    expect(screen.queryByText('Medium')).toBeNull();
    expect(screen.queryByText('High')).toBeNull();
    // Weight column renders the real weight.
    expect(screen.getByText('50.00%')).toBeDefined();
  });
});

describe('portfolio manage — base-currency values', () => {
  it('uses converted row values when the USD view is selected', async () => {
    mocks.getPortfolio.mockImplementation(async ({ currency }: { currency: 'INR' | 'USD' }) => ({
      positions: [{
        id: 1,
        ticker: 'AAPL',
        quantity: 1,
        buy_price: 90,
        last_price: 100,
        market_value: 100,
        current_value: 100,
        total_cost: 90,
        unrealized_gain_loss: 10,
        unrealized_gain_loss_pct: 11.111,
        weight: 1,
        sector: 'Technology',
        native_currency: 'USD',
        value_currency: currency,
        buy_price_base: currency === 'USD' ? 90 : 7200,
        last_price_base: currency === 'USD' ? 100 : 8000,
        market_value_base: currency === 'USD' ? 100 : 8000,
        current_value_base: currency === 'USD' ? 100 : 8000,
        total_cost_base: currency === 'USD' ? 90 : 7200,
        unrealized_gain_loss_base: currency === 'USD' ? 10 : 800,
        unrealized_gain_loss_pct_base: 11.111,
      }],
      total_value: currency === 'USD' ? 100 : 8000,
      total_positions: 1,
      total_weight: 1,
      sectors: { Technology: 1 },
      currency,
      base_currency: currency,
    }));
    mocks.getForecastRisk.mockResolvedValue({ positions: {} });

    render(<PortfolioManagePage />);
    await waitFor(() => expect(screen.getAllByText('AAPL').length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole('button', { name: /USD/ }));
    await waitFor(() => expect(mocks.getPortfolio).toHaveBeenCalledWith({ currency: 'USD' }));
    await waitFor(() => expect(screen.getAllByText('$100.00').length).toBeGreaterThan(0));
    expect(screen.getAllByText('$90.00').length).toBeGreaterThan(0);
    expect(screen.getAllByText('+$10.00').length).toBeGreaterThan(0);
    expect(screen.queryByText('₹8,000.00')).toBeNull();
    expect(mocks.setPositionCount).toHaveBeenLastCalledWith(1);
    expect(mocks.setPortfolioSnapshot).not.toHaveBeenCalledWith(
      expect.objectContaining({ total_value: 100 })
    );
  });
});

describe('fabricated fallbacks — RiskMetricsDisplay null VaR path', () => {
  it('null var_95 renders N/A with no Low/High risk label, never 0.00% Low Risk', async () => {
    const { RiskMetricsDisplay } = await import('@/components/charts/RiskMetricsDisplay');

    const { container } = render(
      <RiskMetricsDisplay
        data={{
          risk_score: null,
          risk_level: 'Unknown',
          annual_volatility: null,
          sharpe_ratio: null,
          max_drawdown: 0,
          var_95: null,
          cvar_95: null,
        }}
      />
    );

    expect(container.textContent).toContain('N/A');
    expect(screen.queryByText('Low Risk')).toBeNull();
    expect(screen.queryByText('Medium Risk')).toBeNull();
    expect(screen.queryByText('High Risk')).toBeNull();
    expect(container.textContent).not.toContain('0.00%');
  });
});

describe('fabricated fallbacks — factor exposure backend error payload', () => {
  it('error payload with r_squared 0.0 shows banner + N/A, never Weak / 0.000', async () => {
    mocks.positions = [{ ticker: 'X.NS', weight: 1 }];
    mocks.getFactorExposure.mockResolvedValue({
      portfolio: { market: null, alpha: null, annualized_alpha: null },
      positions: {},
      r_squared: 0.0,
      adjusted_r_squared: 0.0,
      lookback_days: 252,
      error: 'Insufficient history for factor regression',
    });

    render(<FactorExposurePage />);

    await waitFor(() => {
      expect(screen.getByTestId('factor-error-banner')).toBeDefined();
    });
    expect(screen.getByText(/Insufficient history for factor regression/)).toBeDefined();
    // B9: the 0.0 filler must not render as a measured fit.
    expect(screen.queryByText('0.000')).toBeNull();
    expect(screen.queryByText('Weak')).toBeNull();
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
  });
});

describe('fabricated fallbacks — optimize null expected risk/return', () => {
  it('shows frontier-empty instead of a fabricated 21-point curve', async () => {
    const { default: OptimizePage } = await import('@/app/dashboard/optimize/page');
    mocks.runOptimization.mockResolvedValue({
      strategy: 'hrp',
      weights: {},
      expected_annual_return: null,
      expected_annual_volatility: null,
      expected_sharpe: null,
      solver: 'test-solver',
      universe: [],
      current_weights: {},
      trades_required: {},
      disclaimer: 'For illustration only.',
    });

    render(<OptimizePage />);
    fireEvent.click(screen.getByRole('button', { name: /Run HRP/ }));

    await waitFor(() => {
      expect(screen.getByTestId('frontier-empty')).toBeDefined();
    });
    expect(screen.queryByText(/Frontier Portfolio/)).toBeNull();
    expect(screen.queryByText(/Current Portfolio \(Pre-Rebalance\)/)).toBeNull();
    expect(screen.queryByText(/Markowitz Efficient Frontier/)).toBeNull();
    // Null expected return/vol render N/A metric cards, never coerced zeros.
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
  });
});

describe('fabricated fallbacks — regime state_N probabilities', () => {
  it('renders real posterior values, never fabricated 0% buckets for missing calm/bull/crisis', async () => {
    const { default: RegimePage } = await import('@/app/dashboard/regime/page');
    mocks.getRegime.mockResolvedValue({
      as_of: '2026-01-02',
      current_regime: 'state_0',
      stability_pct: 71.2,
      regime_probabilities: { state_0: 62.5, state_1: 37.5 },
      states: [
        { regime: 'state_0', ann_ret: 0.05, ann_vol: 0.1, historical_days_pct: 60 },
        { regime: 'state_1', ann_ret: -0.02, ann_vol: 0.2, historical_days_pct: 40 },
      ],
      recent_history: [],
      observations: 100,
    });

    render(<RegimePage />);

    await waitFor(() => {
      expect(screen.getByText('62.5%')).toBeDefined();
    });
    expect(screen.getByText('37.5%')).toBeDefined();
    const body = document.body.textContent || '';
    expect(body).toContain('State_0');
    // No fabricated calm/bull/crisis zero buckets for absent keys.
    expect(body).not.toContain('Calm: 0%');
    expect(body).not.toContain('Bull Rally: 0%');
    expect(body).not.toContain('Crisis: 0%');
  });
});

describe('fabricated fallbacks — risk contribution all-negative divergence', () => {
  it('all-negative CVaR−vol diffs show Symmetric message, never "more to your tail losses"', async () => {
    const { default: RiskContributionPage } = await import('@/app/dashboard/risk-contribution/page');
    mocks.getRiskContribution.mockResolvedValue({
      window: { start: '2025-01-01', end: '2026-01-01' },
      positions: {
        volatility: { A: 0.6, B: 0.4 },
        cvar_tail: { A: 0.4, B: 0.3 },
      },
      sector_rollup: { volatility: { Tech: 1.0 }, cvar: { Tech: 1.0 } },
      portfolio_volatility_annualized: 0.18,
      portfolio_var_95_daily: -0.02,
      portfolio_cvar_95_daily: -0.03,
      methodology: 'Euler decomposition',
    });

    render(<RiskContributionPage />);

    await waitFor(() => {
      expect(screen.getByText(/Symmetric Risk Distribution/)).toBeDefined();
    });
    expect(screen.queryByText(/more to your tail losses/)).toBeNull();
  });
});
