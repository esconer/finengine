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
 *   - PerformanceChart total return      → N/A, never a green "+0.00%" for "no start"
 *   - liquidity score bar                → draw NO fill, never a 0%-wide "scored 0"
 *   - concentration CSV weight + tier    → N/A in BOTH columns, never "0.00%" + "Low"
 *   - concentration cumulative weight    → withhold once any leg is unmeasured
 *   - volatility-sizing gross turnover   → N/A if any leg is unsized, never a partial sum
 *   - volatility-sizing net cash residue → uncoloured when null, never a green "healthy"
 *
 * A fifth block in this file is NOT an absent-value case: the volatility-sizing
 * weight bars must name their action as a word, because the fill colour was the
 * only carrier of buy-vs-hold-vs-sell.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import React from 'react';
import { PerformanceChart } from '@/components/charts/PerformanceChart';

const mocks = vi.hoisted(() => ({
  positions: [] as Record<string, unknown>[],
  totalValue: 0 as number | null,
  performanceData: [] as Record<string, unknown>[],
  analytics: {} as Record<string, unknown>,
  getFactorExposure: vi.fn(),
  getLiquidityMetrics: vi.fn(),
  getConcentrationMetrics: vi.fn(),
  getVolatilitySizing: vi.fn(),
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
      getConcentrationMetrics: mocks.getConcentrationMetrics,
      getVolatilitySizing: mocks.getVolatilitySizing,
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

// ---------------------------------------------------------------------------
// PerformanceChart — a ratio with no first term is not "no change".
// ---------------------------------------------------------------------------
describe('PerformanceChart — an absent starting value withholds the return', () => {
  /** The component types `portfolio_value` as `number`; the API does not. */
  const series = (values: (number | null)[]) =>
    values.map((portfolio_value, i) => ({
      date: `2026-01-${String(i + 1).padStart(2, '0')}`,
      portfolio_value,
    })) as unknown as React.ComponentProps<typeof PerformanceChart>['data'];

  it('renders the absent state, never a confident green +0.00%', () => {
    // The first reading has no portfolio value. `data[0]?.portfolio_value || 0`
    // made startValue 0, so `startValue > 0 ? … : 0` published 0 — and
    // `totalReturn >= 0` painted that 0 green. "No change" is a claim about a
    // portfolio that was never measured.
    const { container } = render(<PerformanceChart data={series([null, 1000])} />);

    const totalReturn = screen.getByText('Total Return').parentElement;
    expect(totalReturn?.textContent).toBe('Total ReturnN/A');
    // The absent state is deliberately not coloured: green would still read as
    // "no change", red as "loss".
    expect(totalReturn?.querySelector('.text-green-600')).toBeNull();
    expect(totalReturn?.querySelector('.text-red-600')).toBeNull();
    expect(container.textContent).not.toContain('+0.00%');
  });

  it('still renders a MEASURED flat window as a real, green 0.00%', () => {
    // The other half of the rule. A start and an end that are both present and
    // both 1000 IS a measured 0.00% return, and a guard written as
    // `value || 'N/A'` would erase it.
    const { container } = render(<PerformanceChart data={series([1000, 1000])} />);

    const totalReturn = screen.getByText('Total Return').parentElement;
    expect(totalReturn?.textContent).toBe('Total Return+0.00%');
    expect(totalReturn?.querySelector('.text-green-600')).not.toBeNull();
    expect(container.textContent).not.toContain('N/A');
  });

  it('still renders a measured loss as a red negative return', () => {
    // Guards against "fixing" the flat case by colouring anything non-absent
    // red, and pins that a measured zero END value is a real -100.00%.
    const { container } = render(<PerformanceChart data={series([1000, 0])} />);

    const totalReturn = screen.getByText('Total Return').parentElement;
    expect(totalReturn?.textContent).toBe('Total Return-100.00%');
    expect(totalReturn?.querySelector('.text-red-600')).not.toBeNull();
    expect(container.textContent).not.toContain('N/A');
  });
});

// ---------------------------------------------------------------------------
// liquidity — a holding the engine could not score draws NO bar.
//
// `((position.score ?? 0) / 10) * 100` gave an unscored holding a 0%-wide fill,
// which is pixel-identical to a holding the engine genuinely scored zero. The
// score label beside it said N/A while the bar said "scored zero".
// ---------------------------------------------------------------------------
describe('liquidity — an unscored holding draws no score bar', () => {
  const book = (byPosition: Record<string, unknown>) => {
    mocks.getLiquidityMetrics.mockResolvedValue({
      overall_score: 7.5,
      risk_level: 'Medium',
      liquidation_time_days: '1-2',
      by_position: byPosition,
      volume_stats: {
        avg_volume: 1,
        total_portfolio_volume: 1,
        high_volume_pct: 0,
        medium_volume_pct: 0,
        low_volume_pct: 0,
      },
    });
  };

  /** The row wrapper the score bar lives in: ticker + category + bar + score. */
  const barRow = (ticker: string) =>
    screen.getAllByText(ticker)[0].closest('div.flex.items-center.justify-between')!;

  /** The bar track, i.e. the element that HOLDS the fill when there is one. */
  const barTrack = (ticker: string) =>
    barRow(ticker).querySelector('div.w-28.bg-slate-800')!;

  it('draws no fill at all for a holding the engine could not score', async () => {
    const { default: LiquidityPage } = await import('@/app/dashboard/liquidity/page');
    mocks.positions = [{ ticker: 'UNKNOWN.NS', weight: 1 }];
    book({ 'UNKNOWN.NS': { score: null, category: null } });

    render(<LiquidityPage />);

    await waitFor(() => {
      expect(screen.getAllByText('UNKNOWN.NS').length).toBeGreaterThan(0);
    });
    // The track holds NO child. An empty track and a 0%-wide fill are the same
    // pixels, so the assertion is on the DOM, which is what actually differs.
    expect(barTrack('UNKNOWN.NS').children).toHaveLength(0);
    expect(screen.queryByTestId('liquidity-score-bar-UNKNOWN.NS')).toBeNull();
    // The label beside the track still carries the absent state.
    expect(barRow('UNKNOWN.NS').textContent).toContain('N/A');
  });

  it('still draws the empty bar for a MEASURED score of 0', async () => {
    // The other half of the rule. A score of 0 is a real measurement — the
    // engine looked and found the holding untradeable. A guard written as
    // `score || noBar` would erase it, which is the same fabrication reversed.
    const { default: LiquidityPage } = await import('@/app/dashboard/liquidity/page');
    mocks.positions = [{ ticker: 'ZERO.NS', weight: 1 }];
    book({ 'ZERO.NS': { score: 0, category: 'Low' } });

    render(<LiquidityPage />);

    const bar = await screen.findByTestId('liquidity-score-bar-ZERO.NS');
    // Present, and genuinely 0%-wide — a real zero, not a missing bar.
    expect(bar.getAttribute('style')).toContain('0%');
    expect(barRow('ZERO.NS').textContent).toContain('0.0/10');
  });
});

// ---------------------------------------------------------------------------
// concentration — an unmeasured weight is N/A everywhere, and the columns that
// used to disagree with each other now agree.
//
// `p.weight ?? 0` fed the tier while the cell beside it read `p.weight * 100`
// UNGUARDED, so one absent weight printed "0.00%" and "Low" in some builds and
// "NaN%" in others. Both are fabrications: neither is a measurement.
// ---------------------------------------------------------------------------
describe('concentration — an unmeasured weight never becomes a number or a tier', () => {
  beforeEach(() => {
    mocks.positions = [{ ticker: 'A.NS', weight: 0.6, sector: 'Energy' }];
  });

  const concentration = (byWeight: Record<string, number | null>) => {
    mocks.getConcentrationMetrics.mockResolvedValue({
      largest_position: 0.6,
      top_3: 1,
      herfindahl_index: 0.4,
      effective_positions: 2,
      diversification_ratio: 1,
      by_weight: byWeight,
      by_sector: { energy: 0.6 },
    });
  };

  /** Captures the CSV the page hands to a Blob on export. */
  const captureCsv = async () => {
    let captured = '';
    const RealBlob = globalThis.Blob;
    class CapturingBlob extends RealBlob {
      constructor(parts: BlobPart[], opts?: BlobPropertyBag) {
        super(parts, opts);
        captured = String(parts[0]);
      }
    }
    (globalThis as { Blob: unknown }).Blob = CapturingBlob;
    const realCreate = URL.createObjectURL;
    URL.createObjectURL = () => 'blob:stub';
    URL.revokeObjectURL = () => {};
    try {
      fireEvent.click(screen.getByText('CSV Export'));
    } finally {
      (globalThis as { Blob: unknown }).Blob = RealBlob;
      URL.createObjectURL = realCreate;
    }
    return captured;
  };

  /** The CSV row for one ticker, with the quoting `escapeCsvCell` adds removed. */
  const csvRow = (csv: string, ticker: string) =>
    csv.split('\n').find(line => line.includes(ticker))!.split(',')
      .slice(0, 5)
      .map(cell => cell.replace(/^"|"$/g, ''));

  it('emits N/A in BOTH the weight and the risk column, never "0.00%" + "Low"', async () => {
    const { default: ConcentrationPage } = await import('@/app/dashboard/concentration/page');
    concentration({ 'A.NS': null });

    render(<ConcentrationPage />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    const row = csvRow(await captureCsv(), 'A.NS');
    // The two columns agreed on a fabrication before. They now agree on N/A.
    expect(row).toEqual(['A.NS', 'N/A', 'N/A', 'Energy', 'N/A']);
    expect(row).not.toContain('0.00%');
    expect(row).not.toContain('NaN');
    expect(row).not.toContain('Low');
  });

  it('still emits a real "0.00%" and a real "Low" for a MEASURED weight of 0', async () => {
    // A weight of exactly 0 is a measurement the engine made. Guarding this with
    // `weight || 'N/A'` would pass the case above and break this one.
    const { default: ConcentrationPage } = await import('@/app/dashboard/concentration/page');
    concentration({ 'A.NS': 0 });

    render(<ConcentrationPage />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    const row = csvRow(await captureCsv(), 'A.NS');
    expect(row).toEqual(['A.NS', '0.00%', '0.00%', 'Energy', 'Low']);
  });

  it('shows N/A, never a green "Low", in the concentration-risk TABLE cell', async () => {
    // The table cell carried the identical `?? 0` as the CSV, so the row read
    // "N/A" weight beside a green "Low" badge — a clean bill of health for a
    // holding the engine could not size.
    const { default: ConcentrationPage } = await import('@/app/dashboard/concentration/page');
    concentration({ 'A.NS': null });

    render(<ConcentrationPage />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    const table = screen.getByRole('table');
    const tier = within(table).getByText('N/A', { selector: 'span' });
    expect(tier.textContent).toBe('N/A');
    // The absent tier is slate, not the green "Low" badge.
    expect(tier.getAttribute('class')).not.toContain('green');
    expect(within(table).queryByText('Low')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// concentration — a PARTIALLY measured book has no cumulative weight.
//
// `weight as number` plus `cumWeight += (weight as number)` turned an absent
// leg into an additive zero, so the running total kept climbing over a book it
// had only partly measured. An absent weight is not a 0% holding.
// ---------------------------------------------------------------------------
describe('concentration — a partially measured book withholds the cumulative weight', () => {
  beforeEach(() => {
    mocks.positions = [{ ticker: 'A.NS', weight: 0.5 }, { ticker: 'B.NS', weight: 0.5 }];
  });

  const concentration = (byWeight: Record<string, number | null>) => {
    mocks.getConcentrationMetrics.mockResolvedValue({
      largest_position: 0.6,
      top_3: 1,
      herfindahl_index: 0.4,
      effective_positions: 2,
      diversification_ratio: 1,
      by_weight: byWeight,
      by_sector: { energy: 0.6 },
    });
  };

  it('stops the running total at the first leg it could not measure', async () => {
    const { default: ConcentrationPage } = await import('@/app/dashboard/concentration/page');
    // Sorted descending by the page, so the 0.4 is measured and summed, and the
    // null is met second — at which point the cumulative share is withheld.
    concentration({ 'A.NS': 0.4, 'B.NS': null });

    render(<ConcentrationPage />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    const table = screen.getByRole('table');
    // The measured leg still carries a real cumulative weight…
    const aRow = within(table).getByText('A.NS').closest('tr')!;
    expect(aRow.cells[2].textContent).toBe('40.0%');
    // …and the unmeasured leg's CUMULATIVE CELL states N/A rather than
    // continuing the sum. Asserted on the cell, not the row: the weight cell
    // beside it is also N/A, so a row-level assertion passes even when the
    // cumulative wrongly keeps climbing.
    const bRow = within(table).getByText('B.NS').closest('tr')!;
    expect(bRow.cells[1].textContent).toBe('N/A');
    expect(bRow.cells[2].textContent).toBe('N/A');
    expect(bRow.cells[2].textContent).not.toContain('40.0%');
  });

  it('keeps a measured 0% holding as a real position, not a dropped one', async () => {
    // Dropping unmeasured legs from the Lorenz curve is a behaviour change ONLY
    // when a leg is unmeasured. With every leg measured nothing is dropped, and a
    // genuine 0% holding stays a row with a real 0.0% weight.
    //
    // NOT COVERED HERE: the curve's own shape. Recharts renders no axes, ticks
    // or path in jsdom (the container measures 0x0), so `lorenzCurveData` is not
    // observable from the DOM and an assertion against the chart would pass
    // whatever the curve did — the exact "test that cannot fail" trap. What IS
    // pinned is the data contract the curve depends on: a null weight stays null
    // all the way into the row, which is what makes the curve drop it.
    const { default: ConcentrationPage } = await import('@/app/dashboard/concentration/page');
    concentration({ 'A.NS': 0.5, 'B.NS': 0.0 });

    render(<ConcentrationPage />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    const bRow = within(screen.getByRole('table')).getByText('B.NS').closest('tr')!;
    expect(bRow.cells[1].textContent).toBe('0.0%');
    expect(bRow.cells[2].textContent).toBe('50.0%');
  });
});

// ---------------------------------------------------------------------------
// volatility-sizing — an unsized leg makes the whole turnover total absent.
//
// Gross turnover is a SUM over legs, so one absent leg makes the sum absent.
// `Math.abs(pos.weight_change ?? 0)` absorbed a leg the engine never sized as
// "no change" and published the partial sum as if the book were fully covered.
// ---------------------------------------------------------------------------
describe('volatility-sizing — a leg with no sizing instruction withholds the turnover', () => {
  const sizingPayload = (
    current: Record<string, number | null>,
    recommended: Record<string, number | null>
  ) => ({
    current_weights: current,
    recommended_weights: recommended,
    trades: Object.fromEntries(
      Object.keys(recommended).map(ticker => [ticker, {
        shares_delta: 10,
        amount: 5000,
        amount_currency: 'INR',
        sizing_price: 500,
        rounding_residual: 0,
        rounding_tolerance: 250,
        below_minimum_notional: false,
        status: 'executable',
        reason: null,
      }])
    ),
    target_volatility: 0.15,
    current_volatility: 0.18,
    volatilities: { 'A.NS': 0.22, 'B.NS': 0.14 },
    portfolio_value: 1000000,
    portfolio_value_currency: 'INR',
    currency: 'INR',
    sizing_price: { 'A.NS': 500, 'B.NS': 500 },
    execution: {
      normalization_rule: 'divide_all_legs_by_gross_exposure',
      normalization_mode: 'fully_funded',
      weights_normalized: false,
      gross_exposure: 1.0,
      net_cash_weight: 0.0,
      financing_required: false,
      financing_requirement: 0.0,
      financing_requirement_currency: 'INR',
      execution_eligible: true,
      block_reasons: [],
      block_reason: null,
    },
    universe_coverage: {
      requested_tickers: ['A.NS', 'B.NS'],
      available_tickers: ['A.NS', 'B.NS'],
      covered_tickers: ['A.NS', 'B.NS'],
      missing_tickers: [],
      requested_count: 2,
      available_count: 2,
      coverage_ratio: 1,
      complete: true,
      status: 'complete',
    },
    data_status: 'available',
  });

  beforeEach(() => {
    mocks.positions = [{ ticker: 'A.NS', weight: 0.5 }, { ticker: 'B.NS', weight: 0.5 }];
  });

  /** Opens the rebalance ticket, which is where the turnover tile lives. */
  const openTicket = async () => {
    fireEvent.click(await screen.findByText('Execute Rebalance'));
    return screen.getByText('Turnover Delta').parentElement!;
  };

  it('renders N/A, not the partial sum, and suppresses the rebalancing banner', async () => {
    const { default: VolatilitySizingPage } = await import('@/app/dashboard/volatility-sizing/page');
    // Only A.NS moved. The TRUE gross turnover of the measured leg is 0.2, but
    // publishing "20.0%" states the whole book's turnover from one leg.
    mocks.getVolatilitySizing.mockResolvedValue(
      sizingPayload({ 'A.NS': 0.5, 'B.NS': 0.5 }, { 'A.NS': 0.7, 'B.NS': null })
    );

    render(<VolatilitySizingPage />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    const tile = await openTicket();
    expect(tile.textContent).toBe('Turnover DeltaN/A');
    // The partial sum must not be published as the book's turnover. Scoped to
    // the tile: A.NS's OWN weight delta is a real published +20.0% and must
    // survive — it is a per-leg measurement, not a total.
    expect(tile.textContent).not.toContain('20.0%');
    // No banner may fire on a total that does not exist.
    expect(screen.queryByText('Significant Rebalancing Opportunity')).toBeNull();
  });

  it('still renders a real 0.0% for a book where every leg holds', async () => {
    // Every leg measured and none moved IS a measured zero turnover. A guard
    // written as "any null → N/A, else 0" passes the case above; a guard written
    // as `total || 'N/A'` passes this one. Both halves are needed.
    const { default: VolatilitySizingPage } = await import('@/app/dashboard/volatility-sizing/page');
    mocks.getVolatilitySizing.mockResolvedValue(
      sizingPayload({ 'A.NS': 0.5, 'B.NS': 0.5 }, { 'A.NS': 0.5, 'B.NS': 0.5 })
    );

    render(<VolatilitySizingPage />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    expect((await openTicket()).textContent).toBe('Turnover Delta0.0%');
  });
});

// ---------------------------------------------------------------------------
// volatility-sizing — an absent net cash residue is NEITHER surplus nor deficit.
//
// `(execution.netCashWeight ?? 0) < 0 ? rose : emerald` put a null through the
// `< 0` branch and painted a green N/A — a healthy cash position the engine
// never measured. The absent state takes no colour at all.
// ---------------------------------------------------------------------------
describe('volatility-sizing — an absent net cash residue is uncoloured', () => {
  const withNetCash = (netCashWeight: number | null, financingRequired = false) => ({
    current_weights: { 'A.NS': 0.5, 'B.NS': 0.5 },
    recommended_weights: { 'A.NS': 0.55, 'B.NS': 0.45 },
    trades: {
      'A.NS': {
        shares_delta: 10, amount: 5000, amount_currency: 'INR', sizing_price: 500,
        rounding_residual: 0, rounding_tolerance: 250,
        below_minimum_notional: false, status: 'executable', reason: null,
      },
      'B.NS': {
        shares_delta: -10, amount: -5000, amount_currency: 'INR', sizing_price: 500,
        rounding_residual: 0, rounding_tolerance: 250,
        below_minimum_notional: false, status: 'executable', reason: null,
      },
    },
    target_volatility: 0.15,
    current_volatility: 0.18,
    volatilities: { 'A.NS': 0.22, 'B.NS': 0.14 },
    portfolio_value: 1000000,
    portfolio_value_currency: 'INR',
    currency: 'INR',
    sizing_price: { 'A.NS': 500, 'B.NS': 500 },
    execution: {
      normalization_rule: 'divide_all_legs_by_gross_exposure',
      normalization_mode: financingRequired ? 'financed_gross_exposure_exceeds_100_percent' : 'fully_funded',
      weights_normalized: false,
      gross_exposure: financingRequired ? 1.3 : 1.0,
      net_cash_weight: netCashWeight,
      financing_required: financingRequired,
      financing_requirement: financingRequired ? 300000 : 0,
      financing_requirement_currency: 'INR',
      execution_eligible: !financingRequired,
      block_reasons: financingRequired ? ['financing_required'] : [],
      block_reason: financingRequired ? 'Gross exposure 1.3 exceeds 1.0' : null,
    },
    universe_coverage: {
      requested_tickers: ['A.NS', 'B.NS'],
      available_tickers: ['A.NS', 'B.NS'],
      covered_tickers: ['A.NS', 'B.NS'],
      missing_tickers: [],
      requested_count: 2,
      available_count: 2,
      coverage_ratio: 1,
      complete: true,
      status: 'complete',
    },
    data_status: 'available',
  });

  beforeEach(() => {
    mocks.positions = [{ ticker: 'A.NS', weight: 0.5 }, { ticker: 'B.NS', weight: 0.5 }];
  });

  /** The value span that follows the "Net cash:" label. */
  const netCashValue = async () => {
    const banner = await screen.findByTestId('exposure-banner');
    const label = Array.from(banner.querySelectorAll('span.text-slate-400'))
      .find(span => (span.textContent ?? '').startsWith('Net cash'))!;
    return label.nextElementSibling as HTMLElement;
  };

  it('leaves a null net cash uncoloured, never emerald', async () => {
    const { default: VolatilitySizingPage } = await import('@/app/dashboard/volatility-sizing/page');
    mocks.getVolatilitySizing.mockResolvedValue(withNetCash(null));

    render(<VolatilitySizingPage />);

    const value = await netCashValue();
    expect(value.textContent).toBe('N/A');
    // Green says "healthy surplus". Red says "deficit". The data supports
    // neither claim, so the absent state takes neither colour.
    expect(value.getAttribute('class')).not.toContain('emerald');
    expect(value.getAttribute('class')).not.toContain('rose');
  });

  it('still paints a MEASURED deficit rose and a MEASURED surplus emerald', async () => {
    const { default: VolatilitySizingPage } = await import('@/app/dashboard/volatility-sizing/page');

    // The measured negative: a real borrow, so red is the honest colour.
    mocks.getVolatilitySizing.mockResolvedValue(withNetCash(-0.3, true));
    const { unmount } = render(<VolatilitySizingPage />);
    const deficit = await netCashValue();
    expect(deficit.textContent).toBe('-30.00%');
    expect(deficit.getAttribute('class')).toContain('text-rose-300');
    unmount();

    // The measured positive, INCLUDING a measured 0 — 0 is not absent, so it
    // keeps the surplus colour rather than being swept up by the null rule.
    mocks.getVolatilitySizing.mockResolvedValue(withNetCash(0.0));
    render(<VolatilitySizingPage />);
    const surplus = await netCashValue();
    expect(surplus.textContent).toBe('0.00%');
    expect(surplus.getAttribute('class')).toContain('text-emerald-300');
  });
});

// ---------------------------------------------------------------------------
// volatility-sizing — the weight bars name their action as a WORD.
//
// This is the opposite defect from the ones above: nothing is absent, but the
// only carrier of buy-vs-hold-vs-sell was the fill COLOUR. A reader who cannot
// distinguish emerald from slate has no way to know what the engine instructed.
// The colour semantics are unchanged; the word is added beside them.
// ---------------------------------------------------------------------------
describe('volatility-sizing — the weight bar pair states its action as text', () => {
  beforeEach(() => {
    mocks.positions = [
      { ticker: 'A.NS', weight: 0.4 },
      { ticker: 'B.NS', weight: 0.35 },
      { ticker: 'C.NS', weight: 0.25 },
    ];
  });

  /**
   * The 3-leg payload. It is BOTH installed on the mock and returned, so a case
   * that needs one field changed can spread it rather than restate 40 lines.
   */
  const sizing = (overrides: Record<string, unknown> = {}) => {
    const payload = {
      current_weights: { 'A.NS': 0.4, 'B.NS': 0.35, 'C.NS': 0.25 },
      recommended_weights: { 'A.NS': 0.55, 'B.NS': 0.20, 'C.NS': 0.25 },
      trades: Object.fromEntries(
        ['A.NS', 'B.NS', 'C.NS'].map(ticker => [ticker, {
          shares_delta: 10, amount: 5000, amount_currency: 'INR', sizing_price: 500,
          rounding_residual: 0, rounding_tolerance: 250,
          below_minimum_notional: false, status: 'executable', reason: null,
        }])
      ),
      target_volatility: 0.15,
      current_volatility: 0.18,
      volatilities: { 'A.NS': 0.22, 'B.NS': 0.14, 'C.NS': 0.12 },
      portfolio_value: 1000000,
      portfolio_value_currency: 'INR',
      currency: 'INR',
      sizing_price: { 'A.NS': 500, 'B.NS': 500, 'C.NS': 500 },
      execution: {
        normalization_rule: 'divide_all_legs_by_gross_exposure',
        normalization_mode: 'fully_funded',
        weights_normalized: false,
        gross_exposure: 1.0,
        net_cash_weight: 0.0,
        financing_required: false,
        financing_requirement: 0.0,
        financing_requirement_currency: 'INR',
        execution_eligible: true,
        block_reasons: [],
        block_reason: null,
      },
      universe_coverage: {
        requested_tickers: ['A.NS', 'B.NS', 'C.NS'],
        available_tickers: ['A.NS', 'B.NS', 'C.NS'],
        covered_tickers: ['A.NS', 'B.NS', 'C.NS'],
        missing_tickers: [],
        requested_count: 3,
        available_count: 3,
        coverage_ratio: 1,
        complete: true,
        status: 'complete',
      },
      data_status: 'available',
      ...overrides,
    };
    mocks.getVolatilitySizing.mockResolvedValue(payload);
    return payload;
  };

  /** One card in the "Volatility-Adjusted Weights" visualisation. */
  const cardFor = (ticker: string) => {
    const card = screen.getByText('Volatility-Adjusted Weights')
      .closest('div.bg-slate-900') as HTMLElement;
    return within(card).getByText(ticker)
      .closest('div.bg-slate-800\\/40') as HTMLElement;
  };

  it('names Buy, Sell and Hold in the card, not only as fill colour', async () => {
    const { default: VolatilitySizingPage } = await import('@/app/dashboard/volatility-sizing/page');
    sizing();

    render(<VolatilitySizingPage />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    expect(cardFor('A.NS').textContent).toContain('Buy');
    expect(cardFor('B.NS').textContent).toContain('Sell');
    expect(cardFor('C.NS').textContent).toContain('Hold');
  });

  it('says "No target" for a leg with no sizing instruction', async () => {
    // The absent-direction half. A leg the engine could not size must not be
    // called Hold — that would read as "measured, and the answer is no change".
    const { default: VolatilitySizingPage } = await import('@/app/dashboard/volatility-sizing/page');
    const payload = sizing();
    mocks.getVolatilitySizing.mockResolvedValue({
      ...payload,
      recommended_weights: { 'A.NS': 0.55, 'B.NS': 0.20, 'C.NS': null },
    });

    render(<VolatilitySizingPage />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    const noTarget = cardFor('C.NS');
    expect(noTarget.textContent).toContain('No target');
    expect(noTarget.textContent).toContain('N/A');
    expect(noTarget.textContent).not.toContain('Hold');
  });
});
