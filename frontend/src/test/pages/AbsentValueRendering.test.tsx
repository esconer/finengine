/**
 * An absent value renders as a dash or N/A — never as 0.
 *
 * Two halves, and both are defects:
 *   1. null rendered as 0          → a fabricated measurement
 *   2. a MEASURED 0 rendered as N/A → a real measurement erased
 *
 * The correct treatment differs per site, so each site gets its own case:
 *   - dashboard total value / weight drift → the whole figure is unmeasured
 *   - factor-exposure bars               → draw NO bar, the N/A label carries it
 *   - liquidity counts                   → state the scored denominator
 *   - optimize trade table               → N/A, never an implied full-size buy
 *   - realized-risk drawdown series      → a gap, not a series seeded with 0
 *   - risk-contribution divergence       → no all-clear when nothing is comparable
 *   - risk-studio Euler vol share        → N/A, never a fabricated 0% position
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  positions: [] as Record<string, unknown>[],
  totalValue: 0 as number | null,
  performanceData: [] as Record<string, unknown>[],
  analytics: {} as Record<string, unknown>,
  getFactorExposure: vi.fn(),
  getLiquidityMetrics: vi.fn(),
  getRiskContribution: vi.fn(),
  runOptimization: vi.fn(),
  apiGet: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: mocks.positions,
    fetchPortfolio: vi.fn().mockResolvedValue(undefined),
    setPortfolioSnapshot: vi.fn(),
    setPositionCount: vi.fn(),
    isLoading: false,
    error: null,
    totalValue: mocks.totalValue,
  }),
  useUIStore: Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: vi.fn(), liveDataMode: true }),
    { getState: () => ({ updateLastUpdated: vi.fn() }) }
  ),
}));

vi.mock('@/hooks/useAnalytics', () => ({
  usePortfolioAnalytics: () => ({
    data: mocks.analytics,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
  usePerformanceData: () => ({ performanceData: mocks.performanceData, loading: false }),
  useSectorAllocation: () => [],
}));

vi.mock('@/lib/api', () => {
  // The dashboard hero calls getRegime + getRiskContribution on mount, so the
  // mock answers every analytics method rather than only the ones under test.
  const known = [
    'getRegime', 'getFactorExposure', 'getLiquidityMetrics', 'getRiskContribution',
    'getConcentrationMetrics', 'getForecastRisk', 'getVolatilitySizing', 'runStressTest',
  ];
  const analyticsApi: Record<string, ReturnType<typeof vi.fn>> = {};
  for (const name of known) analyticsApi[name] = vi.fn().mockResolvedValue(undefined);
  return {
    analyticsApi: Object.assign(analyticsApi, {
      getFactorExposure: mocks.getFactorExposure,
      getLiquidityMetrics: mocks.getLiquidityMetrics,
      getRiskContribution: mocks.getRiskContribution,
      runOptimization: mocks.runOptimization,
    }),
    portfolioApi: { rebalancePortfolio: vi.fn(), exportCSV: vi.fn(), getPortfolio: vi.fn() },
    default: { get: mocks.apiGet },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [];
  mocks.totalValue = 0;
  mocks.performanceData = [];
  mocks.analytics = {};
  mocks.apiGet.mockResolvedValue({ data: {} });
});

// ---------------------------------------------------------------------------
// dashboard — an empty or unpriced book is UNMEASURED, not worth ₹0.00.
//
// The dashboard is by far the heaviest route in the app (four charts, two
// modals, a store and a hook). Its first render in a file pays the whole module
// import, so under full-suite parallel load it can exceed vitest's 5s default
// even though the assertions are instant. Every case below carries an explicit
// timeout for that reason — this is a load budget, not a relaxed assertion.
// ---------------------------------------------------------------------------
const DASHBOARD_TIMEOUT = 30_000;

describe('dashboard — absent portfolio totals', () => {
  it('renders ₹0.00 for an empty book — zero holdings really are worth zero', async () => {
    const { default: DashboardPage } = await import('@/app/dashboard/page');
    // NOT a fabrication. The store types totalValue as `number` and seeds it to
    // 0, so an empty book is a MEASURED zero and must keep rendering ₹0.00.
    // Guarding against "correcting" this into N/A is the point of the case.
    mocks.positions = [];
    mocks.totalValue = 0;

    const { container } = render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getAllByText('Total Portfolio Value').length).toBeGreaterThan(0);
    });
    expect(container.textContent).toContain('₹0.00');
    expect(container.textContent).toContain('+₹0.00');
  }, DASHBOARD_TIMEOUT);

  it('withholds the return % for a book with no cost basis, never 0.00%', async () => {
    const { default: DashboardPage } = await import('@/app/dashboard/page');
    // Holdings that carry a market value but no usable cost basis. The P&L is a
    // real +₹1,000, but the RETURN is undefined — `totalCost > 0 ? … : 0`
    // published a confident "0.00%" for a ratio it could not compute.
    mocks.positions = [
      { id: 1, ticker: 'A.NS', weight: 1, quantity: 0, total_cost_base: null, buy_price_base: null },
    ];
    mocks.totalValue = 1000;

    const { container } = render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getAllByText('Unrealized P&L').length).toBeGreaterThan(0);
    });
    // The absolute gain is still reported…
    expect(container.textContent).toContain('+₹1,000.00');
    // …but no fabricated return badge rides with it. Scoped to the P&L card:
    // the Diversification and Weight-Drift cards legitimately read 0.0% here.
    const pnlCard = screen.getAllByText('Unrealized P&L')[0].closest('div')?.parentElement;
    expect(pnlCard?.textContent).toContain('+₹1,000.00');
    expect(pnlCard?.textContent).not.toContain('0.00%');
  }, DASHBOARD_TIMEOUT);

  it('renders N/A for weight drift when a leg has no weight, never -50.0%', async () => {
    const { default: DashboardPage } = await import('@/app/dashboard/page');
    // A present but unweighted leg. `sum + pos.weight` absorbed the null as 0,
    // so this two-leg book totalled 0.5 and drift read a confident -50.0% — a
    // claim about a book the page never actually weighed.
    mocks.positions = [
      { id: 1, ticker: 'A.NS', weight: null, quantity: 10, total_cost_base: 800 },
      { id: 2, ticker: 'B.NS', weight: 0.5, quantity: 10, total_cost_base: 800 },
    ];
    mocks.totalValue = 1000;

    const { container } = render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getAllByText('Weight Drift').length).toBeGreaterThan(0);
    });
    expect(container.textContent).not.toContain('-50.0%');
  }, DASHBOARD_TIMEOUT);

  it('still renders a measured, fully-weighted book honestly', async () => {
    const { default: DashboardPage } = await import('@/app/dashboard/page');
    // The other half of the rule: complete, measured data must not be erased.
    mocks.positions = [
      { id: 1, ticker: 'A.NS', weight: 0.5, quantity: 10, total_cost_base: 800 },
      { id: 2, ticker: 'B.NS', weight: 0.5, quantity: 10, total_cost_base: 800 },
    ];
    mocks.totalValue = 1000;

    const { container } = render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getAllByText('Weight Drift').length).toBeGreaterThan(0);
    });
    // Weights total 1.0 → zero drift, rendered as a real 0.0%.
    expect(screen.getByText('0.0%')).toBeDefined();
    expect(container.textContent).toContain('₹1,000.00');
  }, DASHBOARD_TIMEOUT);
});

// ---------------------------------------------------------------------------
// RiskMetricsDisplay — the opposite error: a MEASURED 0 forecast volatility.
// ---------------------------------------------------------------------------
describe('RiskMetricsDisplay — a measured zero is not an absent value', () => {
  it('renders 0.00% for a measured 0.0 forecast volatility, never N/A', async () => {
    const { RiskMetricsDisplay } = await import('@/components/charts/RiskMetricsDisplay');

    const { container } = render(
      <RiskMetricsDisplay
        data={{
          risk_score: 10,
          risk_level: 'Low',
          annual_volatility: 0.1,
          sharpe_ratio: 1,
          max_drawdown: -0.1,
          var_95: 0,
          cvar_95: 0,
          forecast_volatility: 0,
          forecast_var: 0,
        }}
      />
    );

    // `metrics.forecast_volatility ? ... : 'N/A'` rendered N/A here.
    expect(container.textContent).toContain('0.00%');
    const volCard = screen.getByText('Volatility Forecast').closest('div')?.parentElement;
    expect(volCard?.textContent).toContain('0.00%');
    expect(volCard?.textContent).not.toContain('N/A');
  });

  it('still renders N/A for a genuinely absent forecast volatility', async () => {
    const { RiskMetricsDisplay } = await import('@/components/charts/RiskMetricsDisplay');

    const { container } = render(
      <RiskMetricsDisplay
        data={{
          risk_score: 10,
          risk_level: 'Low',
          annual_volatility: 0.1,
          sharpe_ratio: 1,
          max_drawdown: -0.1,
          var_95: null,
          cvar_95: null,
          forecast_volatility: null,
          forecast_var: null,
        }}
      />
    );

    expect(container.textContent).toContain('N/A');
    expect(container.textContent).not.toContain('0.00%');
  });
});

// ---------------------------------------------------------------------------
// factor-exposure — a bar width wants NOTHING RENDERED plus the existing note.
// ---------------------------------------------------------------------------
describe('factor-exposure — unmeasured variance decomposition draws no bars', () => {
  const nullR2 = () => {
    mocks.positions = [{ ticker: 'A.NS', weight: 1 }];
    mocks.getFactorExposure.mockResolvedValue({
      portfolio: { market: null, alpha: null, annualized_alpha: null },
      positions: {},
      r_squared: null,
      adjusted_r_squared: null,
      lookback_days: 252,
    });
  };

  it('renders no fill for any of the three shares when R² is absent', async () => {
    const { default: FactorExposurePage } = await import('@/app/dashboard/factor-exposure/page');
    nullR2();

    render(<FactorExposurePage />);

    await waitFor(() => {
      expect(screen.getByText(/Variance Decomposition vs NIFTY 50/)).toBeDefined();
    });
    // `?? 0` produced three 0%-wide fills — visually identical to a measured
    // "0% systematic risk" decomposition.
    expect(screen.queryByTestId('variance-bar-corr')).toBeNull();
    expect(screen.queryByTestId('variance-bar-systematic')).toBeNull();
    expect(screen.queryByTestId('variance-bar-idiosyncratic')).toBeNull();
    // The N/A labels still carry the absent state.
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
  });

  it('still draws all three bars when R² is measured', async () => {
    const { default: FactorExposurePage } = await import('@/app/dashboard/factor-exposure/page');
    mocks.positions = [{ ticker: 'A.NS', weight: 1 }];
    mocks.getFactorExposure.mockResolvedValue({
      portfolio: { market: 0.4, alpha: 0.01, annualized_alpha: 0.05 },
      positions: {},
      r_squared: 0.64,
      adjusted_r_squared: 0.6,
      lookback_days: 252,
    });

    render(<FactorExposurePage />);

    await waitFor(() => {
      expect(screen.getByTestId('variance-bar-systematic')).toBeDefined();
    });
    expect(screen.getByTestId('variance-bar-corr')).toBeDefined();
    expect(screen.getByTestId('variance-bar-idiosyncratic')).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// liquidity — a COUNT wants the denominator stated, not silently shrunk.
// ---------------------------------------------------------------------------
describe('liquidity — the high-liquidity share uses the scored denominator', () => {
  const book = (byPosition: Record<string, unknown>) => {
    mocks.getLiquidityMetrics.mockResolvedValue({
      overall_score: 7.5,
      risk_level: 'Medium',
      by_position: byPosition,
    });
  };

  it('states the unscored remainder instead of counting it against the share', async () => {
    const { default: LiquidityPage } = await import('@/app/dashboard/liquidity/page');
    // One high-liquidity holding, one the engine could not score at all.
    // `highVolumeCount / positionData.length` reported "1 (50.0%)" — a 50%
    // high-liquidity book, when 100% of everything classifiable was high.
    book({ 'HIGH.NS': { score: 9.1 }, 'UNKNOWN.NS': { score: null } });

    render(<LiquidityPage />);

    await waitFor(() => {
      expect(screen.getAllByText('High Liquidity Positions').length).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(screen.getAllByText(/unscored/).length).toBeGreaterThan(0);
    });
    // The share is over the scored set, and the remainder is stated.
    expect(screen.getAllByText('1 (100.0%) — 1 of 2 unscored').length).toBeGreaterThan(0);
    // The old, wrong 50.0% must be gone.
    expect(screen.queryByText(/1 \(50\.0%\)/)).toBeNull();
  });

  it('renders N/A for the share when nothing at all is scored', async () => {
    const { default: LiquidityPage } = await import('@/app/dashboard/liquidity/page');
    // Every bucket count is legitimately 0 here, but 0.0% of nothing is not a
    // measurement — it is a share with no denominator.
    book({ 'A.NS': { score: null }, 'B.NS': { score: null } });

    render(<LiquidityPage />);

    await waitFor(() => {
      expect(screen.getAllByText('High Liquidity Positions').length).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
    });
    expect(screen.queryByText('0 (0.0%)')).toBeNull();
  });

  it('is unchanged when every holding is scored', async () => {
    const { default: LiquidityPage } = await import('@/app/dashboard/liquidity/page');
    book({ 'A.NS': { score: 9.1 }, 'B.NS': { score: 6.5 } });

    render(<LiquidityPage />);

    await waitFor(() => {
      expect(screen.getAllByText(/1 positions \(50\.0%\)/).length).toBeGreaterThan(0);
    });
    // No disclosure when there is nothing unscored to disclose.
    expect(screen.queryByText(/unscored/)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// optimize — a ticker absent from a weight map is unmeasured, not 0%.
// ---------------------------------------------------------------------------
describe('optimize — an omitted weight is not a 0% position', () => {
  it('renders N/A instead of implying a full-size buy for an unreported leg', async () => {
    const { default: OptimizePage } = await import('@/app/dashboard/optimize/page');
    // 'B.NS' is in the universe but in neither weight map. `?? 0` made the row
    // read "0.0% current → 40.0% recommended → +40.0% BUY" for a holding the
    // optimizer said nothing about.
    mocks.runOptimization.mockResolvedValue({
      strategy: 'hrp',
      weights: { 'A.NS': 0.6, 'B.NS': 0.4 },
      expected_annual_return: 0.1,
      expected_annual_volatility: 0.15,
      expected_sharpe: 0.8,
      solver: 'test',
      universe: ['A.NS', 'B.NS'],
      current_weights: { 'A.NS': 0.5 },
      trades_required: {},
      disclaimer: 'For illustration only.',
    });

    render(<OptimizePage />);
    fireEvent.click(screen.getByRole('button', { name: /Run/i }));

    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    const bRow = screen.getAllByText('B.NS').find((el) => el.closest('tr')?.querySelector('td'));
    const cells = bRow?.closest('tr')?.querySelectorAll('td');
    expect(cells).toBeDefined();
    // Cell 1 is Current, cell 2 Recommended, cell 3 the change badge.
    expect(cells?.[1].textContent).toBe('N/A');
    expect(cells?.[2].textContent).toBe('40.0%');
    // No fabricated "0.0%" current weight and no fabricated buy delta.
    expect(cells?.[1].textContent).not.toContain('0.0%');
    expect(cells?.[3].textContent).toBe('N/A');
  });

  it('still renders a measured 0.0% leg and its real delta', async () => {
    const { default: OptimizePage } = await import('@/app/dashboard/optimize/page');
    mocks.runOptimization.mockResolvedValue({
      strategy: 'hrp',
      weights: { 'A.NS': 0.6, 'B.NS': 0.4 },
      expected_annual_return: 0.1,
      expected_annual_volatility: 0.15,
      expected_sharpe: 0.8,
      solver: 'test',
      universe: ['A.NS', 'B.NS'],
      current_weights: { 'A.NS': 0.5, 'B.NS': 0 },
      trades_required: {},
      disclaimer: 'For illustration only.',
    });

    render(<OptimizePage />);
    fireEvent.click(screen.getByRole('button', { name: /Run/i }));

    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    const bRow = screen.getAllByText('B.NS').find((el) => el.closest('tr')?.querySelector('td'));
    const cells = bRow?.closest('tr')?.querySelectorAll('td');
    // A measured 0 stays a real 0 with a real +40.0% delta.
    expect(cells?.[1].textContent).toBe('0.0%');
    expect(cells?.[2].textContent).toBe('40.0%');
    expect(cells?.[3].textContent).toBe('+40.0%');
  });
});

// ---------------------------------------------------------------------------
// realized-risk — a chart series wants a GAP, not a fabricated seed point.
// ---------------------------------------------------------------------------
describe('realized-risk — an incomplete window yields a gap, not a flat 0% line', () => {
  const window = (values: (number | null)[]) =>
    values.map((portfolio_value, i) => ({
      date: `2026-01-${String(i + 1).padStart(2, '0')}`,
      portfolio_value,
    }));

  const baseAnalytics = () => ({
    realizedRisk: {
      portfolio: {},
      positions: {},
      warnings: [],
      history_coverage: {},
      methodology: 'test',
    },
  });

  it('draws no drawdown series when any observation has no portfolio value', async () => {
    const { default: RealizedRiskPage } = await import('@/app/dashboard/realized-risk/page');
    mocks.analytics = baseAnalytics();
    mocks.positions = [{ ticker: 'A.NS' }];
    // The first observation is absent. `p.portfolio_value || 0` made it 0, which
    // also became `peak`, flattening every later real value to a 0.00% drawdown.
    mocks.performanceData = window([null, 1000, 900, 1100]);

    const { container } = render(<RealizedRiskPage />);

    await waitFor(() => {
      expect(screen.getByTestId('drawdown-empty')).toBeDefined();
    });
    // The series is not charted from a fabricated seed. Recharts draws nothing
    // when it receives no series data.
    expect(container.querySelector('.recharts-surface')).toBeNull();
  });

  it('still charts the drawdown series on a complete window', async () => {
    const { default: RealizedRiskPage } = await import('@/app/dashboard/realized-risk/page');
    mocks.analytics = baseAnalytics();
    mocks.positions = [{ ticker: 'A.NS' }];
    mocks.performanceData = window([1000, 900, 1100]);

    render(<RealizedRiskPage />);

    await waitFor(() => {
      expect(screen.queryByTestId('drawdown-empty')).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// risk-contribution — an absent tail share must not read as "no tail risk".
// ---------------------------------------------------------------------------
describe('risk-contribution — no all-clear when no leg is comparable', () => {
  it('withholds the divergence insight instead of declaring symmetry', async () => {
    const { default: RiskContributionPage } = await import('@/app/dashboard/risk-contribution/page');
    mocks.getRiskContribution.mockResolvedValue({
      window: { start: '2025-01-01', end: '2026-01-01' },
      positions: {
        // A and B have vol shares but no tail share; C is in the tail map
        // alone, so the insight block IS rendered (both models non-empty) yet
        // no leg is comparable across the two models.
        volatility: { A: 0.6, B: 0.4 },
        cvar_tail: { C: 0.3 },
      },
      sector_rollup: { volatility: { Tech: 1.0 }, cvar_tail: { Tech: 1.0 } },
      portfolio_volatility_annualized: 0.18,
      portfolio_var_95_daily: -0.02,
      portfolio_cvar_95_daily: -0.03,
      methodology: 'Euler decomposition',
    });

    render(<RiskContributionPage />);

    await waitFor(() => {
      expect(screen.getAllByText('Diagnostic Risk Insight').length).toBeGreaterThan(0);
    });
    // `cvar_tail[t] ?? 0` read every absent tail share as 0% tail risk, drove
    // every diff negative, and printed a confident "Symmetric" all-clear.
    expect(screen.queryByText(/Symmetric Risk Distribution/)).toBeNull();
    expect(screen.queryByText(/more to your tail losses/)).toBeNull();
  });

  it('still reports the insight when both models cover every leg', async () => {
    const { default: RiskContributionPage } = await import('@/app/dashboard/risk-contribution/page');
    mocks.getRiskContribution.mockResolvedValue({
      window: { start: '2025-01-01', end: '2026-01-01' },
      positions: { volatility: { A: 0.6, B: 0.4 }, cvar_tail: { A: 0.4, B: 0.3 } },
      sector_rollup: { volatility: { Tech: 1.0 }, cvar_tail: { Tech: 1.0 } },
      portfolio_volatility_annualized: 0.18,
      portfolio_var_95_daily: -0.02,
      portfolio_cvar_95_daily: -0.03,
      methodology: 'Euler decomposition',
    });

    render(<RiskContributionPage />);

    await waitFor(() => {
      expect(screen.getByText(/Symmetric Risk Distribution/)).toBeDefined();
    });
  });
});

// ---------------------------------------------------------------------------
// risk-studio — an absent vol share must not become a 0%-risk position.
// ---------------------------------------------------------------------------
describe('risk-studio — an absent Euler vol share exports N/A, never 0%', () => {
  it('writes N/A into the CSV for a leg with no measured vol share', async () => {
    const { default: RiskStudioPage } = await import('@/app/dashboard/risk-studio/page');
    mocks.apiGet.mockImplementation((url: string) => {
      if (url.includes('risk-contribution')) {
        return Promise.resolve({
          data: {
            window: { start: '2025-01-01', end: '2026-01-01' },
            positions: { volatility: { 'A.NS': null, 'B.NS': 0.4 }, cvar_tail: { 'B.NS': 0.3 } },
            sector_rollup: { volatility: {}, cvar_tail: {} },
            portfolio_volatility_annualized: 0.18,
            methodology: 'Euler decomposition',
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const clicked: HTMLAnchorElement[] = [];
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this);
      });

    try {
      render(<RiskStudioPage />);
      const exportBtn = await screen.findByText('Export CSV');
      // Ticker names here only appear in a hover tooltip, so gate on the
      // export control being enabled rather than on a rendered label.
      await waitFor(() => {
        expect((exportBtn as HTMLButtonElement).disabled).toBe(false);
      });
      fireEvent.click(exportBtn);

      expect(clicked).toHaveLength(1);
      const csv = decodeURIComponent(clicked[0].getAttribute('href')!);
      // `(volShare || 0) * 100` published "A.NS,0%" — a fabricated claim that
      // this holding carries no portfolio risk.
      expect(csv).toContain('"A.NS",N/A,');
      expect(csv).not.toContain('"A.NS",0%,');
    } finally {
      clickSpy.mockRestore();
    }
  });
});
