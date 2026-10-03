/**
 * portfolio/manage — the forecast columns and the book return are rendered at
 * the wrong SCALE, and the return ratio is published for a denominator of zero.
 *
 * Three defects, one file, all asserted on the STRING a user would see:
 *
 *  1. `volatility_forecast` / `var_forecast` are DECIMALS, not percents.
 *     `analytics_engine.py:5937` publishes `"volatility_forecast_units":
 *     "annualized"` and `:5921` `"var_units": "1_day_cumulative_return_decimal"`
 *     — both already in fraction space, exactly like the stress payload's
 *     `"portfolio_impact": "fraction_of_portfolio_value"` (`analytics_engine.py:4431`).
 *     `{position.volatility_forecast.toFixed(2)}%` therefore printed `0.42%`
 *     for a 42% forecast: under-scaled by 100×.
 *
 *  2. `getRiskLevel(volatility)` compared a fraction against percent-space
 *     thresholds (`< 20` / `< 40`). A fraction is always `< 20`, so EVERY row
 *     badged green "Low" — including a 42% forecast. The correct sibling already
 *     exists at `dashboard/forecast-risk/page.tsx:465` in fraction space
 *     (`> 0.35 ? 'High' : > 0.20 ? 'Medium' : 'Low'`); this file pins both pages
 *     to the same band so they cannot drift a third time.
 *
 *  3. `totalGainLossPct = totalCost > 0 ? … : 0` — a RATIO whose fallback fires on
 *     a zero DENOMINATOR. An empty-cost book published a green `+0.00%`, and
 *     because `totalGainLoss` was also `0`, `0 >= 0` painted the whole card green.
 *     Same shape as the one already eliminated in `PortfolioStats.tsx:299-309`.
 *     The absolute is a REDUCTION and stays; the ratio is withheld.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  positions: [] as Record<string, unknown>[],
  getPortfolio: vi.fn(),
  getForecastRisk: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/portfolio/manage',
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
    totalValue: 0,
  }),
  useUIStore: Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: vi.fn(), liveDataMode: true }),
    { getState: () => ({ updateLastUpdated: vi.fn() }) }
  ),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: { getForecastRisk: mocks.getForecastRisk },
  screenerApi: { getStrategies: vi.fn().mockResolvedValue([]) },
  portfolioApi: {
    getPortfolio: mocks.getPortfolio,
    addPosition: vi.fn(),
    rebalancePortfolio: vi.fn(),
    exportCSV: vi.fn(),
  },
  default: { get: vi.fn().mockResolvedValue({ data: {} }) },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [];
});

/**
 * A load budget, not a relaxed assertion: `portfolio/manage` pays its whole
 * module import plus a `DashboardLayout` on first render. Same budget
 * `FabricatedScaleAndZero.test.tsx` states for this route.
 */
const PAGE_TIMEOUT = 30_000;

/** One costable holding, so nothing else on the page is unmeasured. */
const holding = (over: Record<string, unknown> = {}) => ({
  id: 1,
  ticker: 'AAA.NS',
  quantity: 10,
  buy_price: 100,
  last_price: 110,
  current_value: 1100,
  market_value: 1100,
  weight: 1,
  sector: 'Tech',
  custom_name: '',
  added_on: '2025-01-01',
  updated_on: '2025-01-01',
  ...over,
});

const summaryOf = (positions: Record<string, unknown>[]) => ({
  positions,
  total_value: 1100,
  total_positions: positions.length,
  total_weight: 1,
  sectors: { Tech: 1 },
  currency: 'INR',
  base_currency: 'INR',
});

/** The portfolio table's row for a ticker (not the PortfolioStats cards). */
const tableRow = async (ticker: string) => {
  const row = (await screen.findAllByText(ticker))
    .map(el => el.closest('tr'))
    .find(tr => tr?.querySelector('td'));
  expect(row, `no portfolio table row for ${ticker}`).toBeDefined();
  return row as HTMLElement;
};

/**
 * The forecast trio by COLUMN, because the ticker also appears in the
 * PortfolioStats cards: 8 = Volatility Forecast, 9 = VaR Forecast,
 * 10 = Risk Level.
 */
const forecastCells = async (ticker: string) => {
  const cells = (await tableRow(ticker)).querySelectorAll('td');
  return {
    volatility: cells[8].textContent ?? '',
    valueAtRisk: cells[9].textContent ?? '',
    riskLevel: cells[10].textContent ?? '',
  };
};

/** The Total Gain/Loss summary card: its absolute figure and its ratio line. */
const gainLossCard = () => {
  const card = screen.getByText('Total Gain/Loss').parentElement as HTMLElement;
  const lines = Array.from(card.querySelectorAll('p')).filter(
    p => p.textContent !== 'Total Gain/Loss'
  );
  return { absolute: lines[0], ratio: lines[1] };
};

// ---------------------------------------------------------------------------
// 1 + 2 · the forecast columns, at the scale the engine declares.
// ---------------------------------------------------------------------------
describe('portfolio/manage — a decimal forecast renders as a percent', () => {
  const bookWith = async (volatility: number | null, varForecast: number | null) => {
    mocks.getPortfolio.mockResolvedValue(summaryOf([holding()]));
    mocks.getForecastRisk.mockResolvedValue({
      positions: { 'AAA.NS': { volatility_forecast: volatility, var_forecast: varForecast } },
    });
    const { default: ManagePage } = await import('@/app/portfolio/manage/page');
    render(<ManagePage />);
    await screen.findAllByText('AAA.NS');
    // The forecast arrives after first paint; wait for the skeleton to clear.
    await waitFor(async () => {
      expect((await forecastCells('AAA.NS')).volatility).not.toContain('Loading...');
    });
  };

  it('renders a 0.42 forecast volatility as 42.00%, never 0.42%', async () => {
    await bookWith(0.42, -0.031);

    const cells = await forecastCells('AAA.NS');
    // `volatility_forecast_units: "annualized"` — a DECIMAL. 0.42 is 42%.
    expect(cells.volatility).toBe('42.00%');
    // The 100x-under-scaled string must be gone.
    expect(cells.volatility).not.toContain('0.42%');
  }, PAGE_TIMEOUT);

  it('renders a -0.031 var forecast as -3.10%, never -0.03%', async () => {
    // `var_units: "1_day_cumulative_return_decimal"` — also a fraction.
    await bookWith(0.42, -0.031);

    const cells = await forecastCells('AAA.NS');
    expect(cells.valueAtRisk).toBe('-3.10%');
    expect(cells.valueAtRisk).not.toContain('0.03%');
  }, PAGE_TIMEOUT);

  it('badges a 42% forecast "High", never a green "Low"', async () => {
    // `volatility < 20` is true for EVERY fraction, so all three bands were
    // unreachable and every row badged the optimistic one.
    await bookWith(0.42, -0.031);

    expect((await forecastCells('AAA.NS')).riskLevel).toBe('High');
  }, PAGE_TIMEOUT);

  it('uses forecast-risk\'s fraction-space bands, boundaries included', async () => {
    // `dashboard/forecast-risk/page.tsx:465`:
    //   volValue > 0.35 ? 'High' : volValue > 0.20 ? 'Medium' : 'Low'
    // Both comparisons are strict, so 0.35 is Medium and 0.20 is Low. Pinning
    // the boundaries is what stops the two pages drifting apart.
    mocks.getPortfolio.mockResolvedValue(summaryOf([
      holding({ id: 1, ticker: 'LOW.NS', weight: 0.25 }),
      holding({ id: 2, ticker: 'MID.NS', weight: 0.25 }),
      holding({ id: 3, ticker: 'HI.NS', weight: 0.25 }),
      holding({ id: 4, ticker: 'EDGE20.NS', weight: 0.25 }),
      holding({ id: 5, ticker: 'EDGE35.NS', weight: 0.25 }),
    ]));
    mocks.getForecastRisk.mockResolvedValue({
      positions: {
        'LOW.NS': { volatility_forecast: 0.15, var_forecast: null },
        'MID.NS': { volatility_forecast: 0.25, var_forecast: null },
        'HI.NS': { volatility_forecast: 0.42, var_forecast: null },
        'EDGE20.NS': { volatility_forecast: 0.2, var_forecast: null },
        'EDGE35.NS': { volatility_forecast: 0.35, var_forecast: null },
      },
    });

    const { default: ManagePage } = await import('@/app/portfolio/manage/page');
    render(<ManagePage />);
    await screen.findAllByText('LOW.NS');

    expect((await forecastCells('LOW.NS')).riskLevel).toBe('Low');
    expect((await forecastCells('MID.NS')).riskLevel).toBe('Medium');
    expect((await forecastCells('HI.NS')).riskLevel).toBe('High');
    // Strict `>`: exactly at a threshold belongs to the band BELOW it.
    expect((await forecastCells('EDGE20.NS')).riskLevel).toBe('Low');
    expect((await forecastCells('EDGE35.NS')).riskLevel).toBe('Medium');
    expect((await forecastCells('LOW.NS')).volatility).toBe('15.00%');
  }, PAGE_TIMEOUT);

  it('withholds all three for a forecast the engine could not fit', async () => {
    // The other half of the rule, and the one the badge existed for: an absent
    // forecast must not borrow a band from its neighbours.
    await bookWith(null, null);

    const cells = await forecastCells('AAA.NS');
    expect(cells.volatility).toBe('N/A');
    expect(cells.valueAtRisk).toBe('N/A');
    expect(cells.riskLevel).toBe('N/A');
  }, PAGE_TIMEOUT);

  it('renders a MEASURED zero volatility as 0.00%, never N/A', async () => {
    // 0 is a measurement the engine made. A `value || 'N/A'` guard would erase
    // it — which is the same fabrication reversed.
    await bookWith(0, 0);

    const cells = await forecastCells('AAA.NS');
    expect(cells.volatility).toBe('0.00%');
    expect(cells.volatility).not.toContain('N/A');
    expect(cells.valueAtRisk).toBe('+0.00%');
  }, PAGE_TIMEOUT);
});

// ---------------------------------------------------------------------------
// The two pages that publish these numbers, cross-checked against each other.
//
// `portfolio/manage` now goes through `@/lib/forecast-risk-format`.
// `dashboard/forecast-risk` still carries its own page-local `formatPercentage`
// and inline `> 0.35 / > 0.20` band — it is not this agent's file to edit — so
// the shared module is the tool, not yet a single call site. What this block
// buys is that the drift is now OBSERVABLE: the same forecast payload is pushed
// through both routes and both must print the same strings. If either page's
// rule changes alone, this fails.
//
// `DataTableRowOriginal.test.tsx` pins forecast-risk on its own; this pins the
// AGREEMENT, which is the thing that actually broke.
// ---------------------------------------------------------------------------
describe('portfolio/manage and forecast-risk publish the same forecast strings', () => {
  it('renders 0.42 / -0.031 identically on both routes', async () => {
    const forecast = {
      volatility_forecast: 0.42,
      var_forecast: -0.031,
      is_limited_history: false,
      data_points: 210,
    };

    // --- portfolio/manage (through the shared module) ---
    mocks.getPortfolio.mockResolvedValue(summaryOf([holding()]));
    mocks.getForecastRisk.mockResolvedValue({ positions: { 'AAA.NS': forecast } });
    const { default: ManagePage } = await import('@/app/portfolio/manage/page');
    const { unmount } = render(<ManagePage />);
    await screen.findAllByText('AAA.NS');
    await waitFor(async () => {
      expect((await forecastCells('AAA.NS')).volatility).not.toContain('Loading...');
    });
    const manage = await forecastCells('AAA.NS');
    unmount();

    // --- dashboard/forecast-risk (its own page-local rule, untouched) ---
    mocks.getForecastRisk.mockResolvedValue({
      portfolio: {},
      positions: { 'AAA.NS': forecast },
      latest_observation_date: '2025-12-31',
    });
    const { default: ForecastRiskPage } = await import('@/app/dashboard/forecast-risk/page');
    render(<ForecastRiskPage />);
    await screen.findAllByText('AAA.NS');
    const riskRow = screen.getAllByText('AAA.NS').find(el => el.closest('tr'))!.closest('tr')!;
    const cells = Array.from(riskRow.querySelectorAll('td')).map(td => td.textContent ?? '');

    expect(manage.volatility).toBe('42.00%');
    expect(cells[1]).toContain('42.00%');
    expect(manage.valueAtRisk).toBe('-3.10%');
    expect(cells[2]).toContain('-3.10%');
    expect(manage.riskLevel).toBe('High');
    expect(cells[3]).toContain('High');
  }, PAGE_TIMEOUT);
});

// ---------------------------------------------------------------------------
// 3 · the book return ratio with a zero denominator.
// ---------------------------------------------------------------------------
describe('portfolio/manage — an empty-cost book withholds its return ratio', () => {
  it('renders N/A, uncoloured, for a book with no cost basis at all', async () => {
    mocks.getPortfolio.mockResolvedValue(summaryOf([]));

    const { default: ManagePage } = await import('@/app/portfolio/manage/page');
    const { container } = render(<ManagePage />);

    await waitFor(() => {
      expect(screen.getAllByText('Total Gain/Loss').length).toBeGreaterThan(0);
    });

    const { ratio } = gainLossCard();
    // `totalCost > 0 ? … : 0` published a green +0.00% for a ratio with no
    // denominator.
    expect(ratio.textContent).toBe('N/A');
    expect(ratio.textContent).not.toContain('0.00%');
    // And the withheld state takes NO colour: `null >= 0` is true, so the old
    // ternary painted the dash green, which reads as "no change".
    expect(ratio.getAttribute('class')).not.toContain('green');
    expect(ratio.getAttribute('class')).not.toContain('red');
    // Scoped to the card: PortfolioStats renders its own measured figures.
    expect(container.textContent).not.toContain('+0.00%');
  }, PAGE_TIMEOUT);

  it('still renders a MEASURED flat book as a real, green +0.00%', async () => {
    // The other half of the rule. Cost 1000, value 1000: the denominator is a
    // real 1000 and the numerator a real 0, so +0.00% IS the measurement. A
    // guard that refused every zero would pass the case above and break this.
    mocks.getPortfolio.mockResolvedValue(summaryOf([
      holding({ ticker: 'FLAT.NS', current_value: 1000, market_value: 1000, last_price: 100 }),
    ]));

    const { default: ManagePage } = await import('@/app/portfolio/manage/page');
    render(<ManagePage />);
    await waitFor(() => {
      expect(screen.getAllByText('Total Gain/Loss').length).toBeGreaterThan(0);
    });

    const { absolute, ratio } = gainLossCard();
    expect(ratio.textContent).toBe('+0.00%');
    expect(ratio.getAttribute('class')).toContain('green');
    // The ABSOLUTE is a reduction over the legs that were measured, so a
    // measured zero there is still a measured zero and keeps its sign.
    expect(absolute.textContent).toBe('+₹0.00');
  }, PAGE_TIMEOUT);

  it('still renders a real gain with its real ratio', async () => {
    mocks.getPortfolio.mockResolvedValue(summaryOf([holding()]));

    const { default: ManagePage } = await import('@/app/portfolio/manage/page');
    render(<ManagePage />);
    await waitFor(() => {
      expect(screen.getAllByText('Total Gain/Loss').length).toBeGreaterThan(0);
    });

    const { absolute, ratio } = gainLossCard();
    expect(absolute.textContent).toBe('+₹100.00');
    expect(ratio.textContent).toBe('+10.00%');
  }, PAGE_TIMEOUT);
});