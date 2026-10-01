/**
 * A TanStack Table cell renderer must read `row.original`, never the `row`
 * wrapper. `constructRow` (table-core/dist/core/rows/constructRow.js:30)
 * assigns `row.original = original` unconditionally from a required positional
 * parameter, and `Row.original` is a non-optional `TData`
 * (coreRowsFeature.types.d.ts:37) — the row data lives under `original` and
 * nowhere else. Reading a field off the wrapper yields `undefined` (UA-01,
 * 358fb49), which these pages then format into a published-looking figure.
 *
 * The `|| row` fallback that three of these pages carried is NOT protection: it
 * returns that same wrapper and reproduces the exact defect. These tests pin
 * the rendered numbers so the fallback cannot come back silently.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  getFactorExposure: vi.fn(),
  getForecastRisk: vi.fn(),
  runStressTest: vi.fn(),
  getStrategies: vi.fn(),
  runScreen: vi.fn(),
  getPortfolio: vi.fn(),
  addPosition: vi.fn(),
  getMarginalTradeImpact: vi.fn(),
  getRegime: vi.fn(),
  getRiskContribution: vi.fn(),
}));

// The dashboard section overview calls useRouter for its Quick Actions links.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getFactorExposure: mocks.getFactorExposure,
    getForecastRisk: mocks.getForecastRisk,
    runStressTest: mocks.runStressTest,
    getMarginalTradeImpact: mocks.getMarginalTradeImpact,
    // Supplementary dashboard widgets. The page wraps them in allSettled and
    // never blocks on them, so rejecting keeps them off screen — this case is
    // about the positions table, not the regime chips.
    getRegime: mocks.getRegime,
    getRiskContribution: mocks.getRiskContribution,
  },
  screenerApi: {
    getStrategies: mocks.getStrategies,
    runScreen: mocks.runScreen,
  },
  portfolioApi: {
    getPortfolio: mocks.getPortfolio,
    addPosition: mocks.addPosition,
  },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

// Mutable so a case can swap the book without re-mocking the module. The default
// two-leg book is what the factor-exposure / forecast-risk / stress-testing cases
// above already rely on.
const store = vi.hoisted(() => ({
  // `id` is part of the row shape the dashboard page reads but not of the
  // rendered cells, so it is declared here rather than dropped: the type is
  // inferred, and a case that swaps the book must still fit it.
  positions: [
    { id: 1, ticker: 'AAA.NS', weight: 0.6, quantity: 10, last_price: 100, market_value: 600, sector: 'Bank' },
    { id: 2, ticker: 'BBB.NS', weight: 0.4, quantity: 5, last_price: 200, market_value: 400, sector: 'Auto' },
  ] as { id: number; ticker: string; weight: number; quantity: number; last_price: number; market_value: number; market_value_base?: number | null; current_value_base?: number | null; last_price_base?: number | null; sector: string }[],
}));

vi.mock('@/lib/store', () => {
  const useUIStore = Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }),
    { getState: () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }) },
  );
  return {
    usePortfolioStore: () => ({
      positions: store.positions,
      fetchPortfolio: vi.fn().mockResolvedValue(undefined),
      isLoading: false,
      error: null,
      totalValue: 1000,
    }),
    useUIStore,
  };
});

/**
 * The cells of `positionColumns` for a given ticker, in declared column order.
 * Reading the wrapper instead of `original` leaves every one of these empty or
 * collapsed to the absent-value dash, so any assertion on real text fails.
 */
const rowCellsFor = (ticker: string): string[] => {
  const row = screen.getByText(ticker).closest('tr');
  if (!row) throw new Error(`No table row rendered for ${ticker}`);
  return Array.from(row.querySelectorAll('td')).map((td) => td.textContent ?? '');
};

describe('positionColumns cell renderers read row.original, not the row wrapper', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('factor-exposure: renders the published beta, alphas and sensitivity band', async () => {
    mocks.getFactorExposure.mockResolvedValue({
      portfolio: { alpha: 0.0004, annualized_alpha: 0.1, market: 1.05 },
      r_squared: 0.42,
      data_range: { start: '2025-01-01', end: '2025-12-31' },
      universe_coverage: { missing_tickers: [] },
      latest_observation_date: '2025-12-31',
      warnings: [],
      positions: {
        // beta 1.45 > 1.2 selects the "High Beta" sensitivity band.
        'AAA.NS': { market: 1.45, alpha: 0.0006, annualized_alpha: 0.1512, is_limited_history: false },
      },
    });

    const { default: FactorExposurePage } = await import('@/app/dashboard/factor-exposure/page');
    render(<FactorExposurePage />);

    const row = await screen.findByText('AAA.NS');
    expect(row).toBeTruthy();

    const [ticker, beta, dailyAlpha, annualAlpha, sensitivity] = rowCellsFor('AAA.NS');

    // Ticker column — the wrapper read renders nothing here.
    expect(ticker).toContain('AAA.NS');

    // Market Beta (β): formatFactor(1.45, 3) → '+1.450'
    expect(beta).toContain('+1.450');
    expect(beta).not.toContain('N/A');

    // Daily Alpha (α): 0.0006 * 100 → '+0.060% / d'
    expect(dailyAlpha).toContain('+0.060% / d');
    expect(dailyAlpha).not.toContain('N/A');

    // Annualized Alpha (α p.a.): 0.1512 * 100 → '+15.12%'
    expect(annualAlpha).toContain('+15.12%');
    expect(annualAlpha).not.toContain('N/A');

    // Sensitivity band is derived from the SAME beta the cell above published.
    expect(sensitivity).toContain('High Beta');
    expect(sensitivity).not.toContain('N/A');
  });

  it('forecast-risk: renders the published volatility, VaR and risk level', async () => {
    mocks.getForecastRisk.mockResolvedValue({
      portfolio: {},
      positions: {
        // vol 0.42 > 0.35 calibrates risk_level to "High" in the page itself.
        'AAA.NS': {
          volatility_forecast: 0.42,
          var_forecast: -0.031,
          is_limited_history: false,
          data_points: 210,
        },
      },
      latest_observation_date: '2025-12-31',
    });

    const { default: ForecastRiskPage } = await import('@/app/dashboard/forecast-risk/page');
    render(<ForecastRiskPage />);

    await screen.findByText('AAA.NS');

    const [ticker, volatility, varForecast, riskLevel] = rowCellsFor('AAA.NS');

    expect(ticker).toContain('AAA.NS');

    // Volatility Forecast: page-local formatPercentage(0.42) → '42.00%'
    expect(volatility).toContain('42.00%');
    expect(volatility).not.toContain('N/A');

    // VaR (95% Downside): formatPercentage(-0.031) → '-3.10%'
    expect(varForecast).toContain('-3.10%');
    expect(varForecast).not.toContain('N/A');

    // Risk Level: the calibrated band, not the absent dash.
    expect(riskLevel).toContain('High');
    expect(riskLevel).not.toContain('N/A');
  });

  it('stress-testing: renders the published impact and severity band', async () => {
    mocks.runStressTest.mockResolvedValue({
      scenario: 'Interest Rate Shock',
      scenario_description: 'Rates up 200bp',
      max_drawdown: -0.08,
      portfolio_impact: -0.12,
      // -0.185 must select a severity band; a wrapper read gives undefined,
      // which severityFor maps to the absent dash.
      position_impacts: { 'AAA.NS': -0.185 },
      recovery_time: 3,
      confidence_level: 0.8,
      latest_observation_date: '2025-12-31',
    });

    const { default: StressTestingPage } = await import('@/app/dashboard/stress-testing/page');
    render(<StressTestingPage />);

    // Each scenario card renders a "Run Test" button until it has a result.
    // Running one is the only path that populates the position-impact table.
    // `useEffect` at stress-testing/page.tsx:538 auto-runs every scenario when no
    // result exists yet, so the position-impact table populates on its own.
    await screen.findByText('AAA.NS');

    const [ticker, impact, severity] = rowCellsFor('AAA.NS');

    expect(ticker).toContain('AAA.NS');

    // Simulated Impact: page-local formatPercentage(-0.185, 1) → '-18.5%'
    expect(impact).toContain('-18.5%');
    expect(impact).not.toContain('N/A');

    // Severity Level is derived from the SAME impact the cell above published.
    expect(severity).not.toContain('N/A');
  });
});

/**
 * The two `DataTableColumn`-typed arrays that carry the pattern in the pages
 * this file's earlier sibling did not reach. Same contract, different reason it
 * bites: both read the row's ticker/symbol off `row.original`, and both derive a
 * published figure or an outbound link from it.
 */
describe('screener-studio positionColumns read row.original, not the row wrapper', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getStrategies.mockResolvedValue([]);
    mocks.getPortfolio.mockResolvedValue({ positions: [], total_value: 0 });
    mocks.runScreen.mockResolvedValue({
      strategy: 'coffee_can',
      name: 'Coffee Can Portfolio',
      description: 'ROCE > 15%',
      count: 1,
      stocks: [
        {
          symbol: 'TCS',
          ticker: 'TCS.NS',
          name: 'Tata Consultancy Services',
          price: 4100.0,
          market_cap_cr: 1500000.0,
          pe_ratio: 28.5,
          roce_pct: 52.0,
          roe_pct: 48.0,
          dividend_yield_pct: 1.2,
        },
      ],
    });
  });

  it('renders every published cell from the row data, and the bridge carries the suffixed ticker', async () => {
    const { default: ScreenerStudioPage } = await import('@/app/dashboard/screener-studio/page');
    render(<ScreenerStudioPage />);

    await screen.findByText('TCS');
    const [index, stock, price, marketCap, pe, roce, roe, divYield] = rowCellsFor('TCS');

    // Column 0 is the `#` index column, which reads `row.index` — a genuine
    // wrapper read, and the one place the wrapper is the correct source.
    expect(index).toBe('1');

    // Every remaining cell reads row data. A wrapper read leaves each empty.
    expect(stock).toContain('TCS');
    expect(stock).toContain('Tata Consultancy Services');
    expect(price).toContain('₹4,100.00');
    // formatCr(1500000) → '₹15.00 L Cr'
    expect(marketCap).toContain('₹15.00 L Cr');
    expect(pe).toContain('28.5x');
    expect(roce).toContain('52.0%');
    expect(roe).toContain('48.0%');
    expect(divYield).toContain('1.20%');
    for (const cell of [stock, price, marketCap, pe, roce, roe, divYield]) {
      expect(cell).not.toContain('N/A');
    }

    // The row action is the durable part: `data.ticker` is the EXCHANGE SUFFIXED
    // field, and the button's accessible name is built from it. A wrapper read
    // renders `What would undefined do...`, which analytics can never resolve.
    // Asserted on the name only — the panel's own pre-fill contract (and its
    // five tests) live in ScreenerStudio.test.tsx, where the analytics payload is
    // already shaped; mounting the panel here would duplicate that fixture.
    expect(
      screen.getByRole('button', { name: /what would TCS\.NS do to your portfolio/i })
    ).toBeTruthy();
  });
});

describe('dashboard positionColumns read row.original, not the row wrapper', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getRegime.mockRejectedValue(new Error('no regime'));
    mocks.getRiskContribution.mockRejectedValue(new Error('no risk'));
    // Restored in each case so one case's book cannot leak into the next.
    store.positions = [
      { id: 1, ticker: 'AAA.NS', weight: 0.6, quantity: 10, last_price: 100, market_value: 600, sector: 'Bank' },
      { id: 2, ticker: 'BBB.NS', weight: 0.4, quantity: 5, last_price: 200, market_value: 400, sector: 'Auto' },
    ];
  });

  it('renders ticker, weight, market value, price and sector from the row data', async () => {
    const { default: DashboardPage } = await import('@/app/dashboard/page');
    render(<DashboardPage />);

    await screen.findByText('AAA.NS');
    const [ticker, weight, marketValue, price, sector] = rowCellsFor('AAA.NS');

    expect(ticker).toContain('AAA.NS');
    expect(ticker).not.toContain('N/A');

    // The store fixture above gives totalValue 1000 with market_value 600, so the
    // Weight cell is the LIVE weight, not the stored 0.6.
    expect(weight).toContain('60.00%');
    expect(weight).not.toContain('N/A');

    // Market Value and Price are pinned on the REAL figures, not on the dash.
    // The shared store fixture publishes no base-currency fields, so these two
    // cells legitimately read N/A — and a wrapper read renders that same dash for
    // the wrong reason, having never seen the row. Asserting N/A here would
    // therefore pass either way, which is useless as a pin.
    //
    // So the NEXT case drives the dashboard with a leg that DOES carry base
    // fields, and pins the published figures there.
    store.positions = [
      {
        id: 1,
        ticker: 'AAA.NS',
        weight: 0.6,
        quantity: 5,
        last_price: 999,
        market_value: 999,
        market_value_base: 700,
        current_value_base: 700,
        last_price_base: 140,
        sector: 'Bank',
      },
    ];
    expect(marketValue).toContain('N/A');
    expect(price).toContain('N/A');
    expect(sector).toContain('Bank');
    expect(sector).not.toContain('N/A');
  });

  it('publishes the base-currency figures, not the absent-value dash, for a leg that carries them', async () => {
    store.positions = [
      {
        id: 1,
        ticker: 'AAA.NS',
        weight: 0.6,
        quantity: 5,
        last_price: 999,
        market_value: 999,
        market_value_base: 700,
        current_value_base: 700,
        last_price_base: 140,
        sector: 'Bank',
      },
    ];

    const { default: DashboardPage } = await import('@/app/dashboard/page');
    render(<DashboardPage />);

    await screen.findByText('AAA.NS');
    const [ticker, weight, marketValue, price] = rowCellsFor('AAA.NS');

    expect(ticker).toContain('AAA.NS');
    // Weight: liveWeight = market_value_base / totalValue = 700/1000. The stored
    // weight is 0.6, so this cell is unreachable without the row.
    expect(weight).toContain('70.00%');
    expect(marketValue).toContain('₹700.00');
    expect(price).toContain('₹140.00');
    expect(marketValue).not.toContain('N/A');
    expect(price).not.toContain('N/A');
  });
});