/**
 * A missing value must never render as a number.
 *
 * Four families, each with a rendered-string assertion so a green test means the
 * STRING on screen changed, not that a helper returned the right thing:
 *
 *   1. portfolio/manage `% Return`  — the `N/A` branch was unreachable, because
 *      its guard read `Number.isFinite(monetaryValue(…))` and `monetaryValue` is
 *      typed `(…): number` with a terminal `return 0`. An uncostable holding
 *      therefore rendered a green `+0.00%` and the N/A cell never appeared.
 *   2. PortfolioStats concentration  — `Math.max(…positions.map(p => p.weight *
 *      100))` with no zero-guard: one absent weight makes the max `NaN`, and
 *      the card printed `NaN%`.
 *   3. screener-studio add-to-book    — `stock.price || 0` wrote a fabricated
 *      `buy_price: 0`. The backend rejects it
 *      (`schemas.py:17 buy_price: float = Field(..., gt=0)`), so nothing was
 *      saved and the user saw `buy_price: Input should be greater than 0` for a
 *      row rendering `Rs undefined`. The add is refused with the reason instead.
 *   4. store snapshot totals          — `total_value || 0` and a
 *      `snapshot.positions.length` read of the RAW field on the line after its
 *      own `|| []` substitution: an absent total became a confident `₹0.00`
 *      app-wide, and an absent `positions` threw.
 *
 * Plus the scale-sniffing formatter: `Math.abs(value) <= 1.0 && value !== 0 ?
 * value * 100 : value` guesses the unit from the magnitude, so a legitimate
 * value in (-1, 1] is silently multiplied by 100. Every field these pages
 * publish in that window is a FRACTION (`portfolio_impact:
 * "fraction_of_portfolio_value"`, `position_impacts:
 * "fraction_of_position_value"`, weights and volatilities as fractions), so the
 * contract is one scale, applied once, at the call site that knows it.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  positions: [] as Record<string, unknown>[],
  getPortfolio: vi.fn(),
  addPosition: vi.fn(),
  runScreen: vi.fn(),
  getStrategies: vi.fn(),
  getMarginalTradeImpact: vi.fn(),
  getVolatilitySizing: vi.fn(),
  runStressTest: vi.fn(),
  getLiquidityMetrics: vi.fn(),
  getFactorExposure: vi.fn(),
  getConcentrationMetrics: vi.fn(),
  getRiskContribution: vi.fn(),
  getForecastRisk: vi.fn(),
  getRegime: vi.fn(),
  runOptimization: vi.fn(),
  rebalancePortfolio: vi.fn(),
  apiGet: vi.fn(),
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

vi.mock('@/lib/api', () => {
  const analyticsApi: Record<string, ReturnType<typeof vi.fn>> = {
    getMarginalTradeImpact: mocks.getMarginalTradeImpact,
    getVolatilitySizing: mocks.getVolatilitySizing,
    runStressTest: mocks.runStressTest,
    getLiquidityMetrics: mocks.getLiquidityMetrics,
    getFactorExposure: mocks.getFactorExposure,
    getConcentrationMetrics: mocks.getConcentrationMetrics,
    getRiskContribution: mocks.getRiskContribution,
    getForecastRisk: mocks.getForecastRisk,
    getRegime: mocks.getRegime,
    runOptimization: mocks.runOptimization,
  };
  return {
    analyticsApi,
    screenerApi: {
      getStrategies: mocks.getStrategies,
      runScreen: mocks.runScreen,
      runCustomScreen: vi.fn().mockResolvedValue({ stocks: [] }),
    },
    portfolioApi: {
      getPortfolio: mocks.getPortfolio,
      addPosition: mocks.addPosition,
      rebalancePortfolio: mocks.rebalancePortfolio,
      exportCSV: vi.fn(),
    },
    default: { get: mocks.apiGet },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [];
  mocks.getStrategies.mockResolvedValue([]);
  mocks.getPortfolio.mockResolvedValue({ positions: [], total_value: 0 });
  mocks.addPosition.mockResolvedValue({ status: 'success' });
  mocks.getForecastRisk.mockResolvedValue({ positions: {} });
  mocks.apiGet.mockResolvedValue({ data: {} });
});

// ---------------------------------------------------------------------------
// A load budget, not a relaxed assertion.
//
// Every case here mounts a full dashboard route (manage, screener-studio,
// stress-testing, liquidity, volatility-sizing), each paying its whole module
// import plus a DashboardLayout on first render. Under full-suite parallel load
// that can exceed vitest's 5s default even where the assertions are instant —
// the same budget `AbsentValueRendering.test.tsx` states for the dashboard route.
// The assertions themselves are unchanged; only the ceiling moves.
// ---------------------------------------------------------------------------
const PAGE_TIMEOUT = 30_000;

// ---------------------------------------------------------------------------
// 1 · portfolio/manage — the `% Return` N/A cell was unreachable.
// ---------------------------------------------------------------------------
describe('portfolio/manage — an uncostable holding withholds its % Return', () => {
  /**
   * One holding the engine could not cost. `total_cost_base` and
   * `buy_price_base` are absent AND `quantity * buy_price` is 0, so the native
   * cost basis is 0 and every derived ratio is `NaN`.
   */
  const uncostableHolding = () => {
    mocks.getPortfolio.mockResolvedValue({
      positions: [
        {
          id: 1,
          ticker: 'X.NS',
          quantity: 0,
          // buy_price absent: nativeCost = 0 * undefined = NaN.
          last_price: 105,
          current_value: null,
          market_value: null,
          weight: 0.5,
          sector: 'Tech',
          custom_name: '',
        },
      ],
      total_value: 0,
      total_positions: 1,
      total_weight: 0.5,
      sectors: { Tech: 1 },
      currency: 'INR',
      base_currency: 'INR',
    });
  };

  /**
   * The `% Return` cell. The ticker also appears in the PortfolioStats cards
   * above the table, so this takes the row that actually has <td>s — the
   * portfolio table's row — rather than the first text match.
   */
  const returnCell = async (ticker: string) => {
    const row = (await screen.findAllByText(ticker))
      .map(el => el.closest('tr'))
      .find(tr => tr?.querySelector('td'));
    expect(row, `no portfolio table row for ${ticker}`).toBeDefined();
    // Cell 7 is `% Return`: symbol, quantity, buy price, buy date, weight,
    // current value, gain/loss, then % return.
    return row!.querySelectorAll('td')[7].textContent ?? '';
  };

  it('renders N/A for a holding the engine could not cost, never a green +0.00%', async () => {
    const { default: ManagePage } = await import('@/app/portfolio/manage/page');
    uncostableHolding();

    render(<ManagePage />);
    await screen.findAllByText('X.NS');

    // `Number.isFinite(monetaryValue(…))` was ALWAYS true — `monetaryValue` is
    // typed `(…): number` and its terminal `return 0` absorbs the NaN — so the
    // N/A branch at the call site could not be reached and this cell read
    // "+0.00%" in green.
    const cell = await returnCell('X.NS');
    expect(cell).toContain('N/A');
    expect(cell).not.toContain('0.00%');
    expect(cell).not.toContain('+0.00%');
  }, PAGE_TIMEOUT);

  it('still renders the measured return for a costable holding, unchanged', async () => {
    // The other half of the rule: a real measurement must not be erased by the
    // guard. A guard written as `value || 'N/A'` would pass the case above and
    // fail this one.
    const { default: ManagePage } = await import('@/app/portfolio/manage/page');
    mocks.getPortfolio.mockResolvedValue({
      positions: [
        {
          id: 1,
          ticker: 'A.NS',
          quantity: 10,
          buy_price: 100,
          last_price: 110,
          current_value: 1100,
          market_value: 1100,
          weight: 1,
          sector: 'Tech',
          custom_name: '',
        },
      ],
      total_value: 1100,
      total_positions: 1,
      total_weight: 1,
      sectors: { Tech: 1 },
      currency: 'INR',
      base_currency: 'INR',
    });

    render(<ManagePage />);
    await screen.findAllByText('A.NS');

    // 1000 cost → 1100 value = +10.00%. Unchanged by the fix.
    expect(await returnCell('A.NS')).toBe('+10.00%');
  }, PAGE_TIMEOUT);

  it('still renders a MEASURED 0.00% return, never N/A', async () => {
    // Flat holding: cost 1000, value 1000. 0 is a measurement the engine made.
    const { default: ManagePage } = await import('@/app/portfolio/manage/page');
    mocks.getPortfolio.mockResolvedValue({
      positions: [
        {
          id: 1,
          ticker: 'F.NS',
          quantity: 10,
          buy_price: 100,
          last_price: 100,
          current_value: 1000,
          market_value: 1000,
          weight: 1,
          sector: 'Tech',
          custom_name: '',
        },
      ],
      total_value: 1000,
      total_positions: 1,
      total_weight: 1,
      sectors: { Tech: 1 },
      currency: 'INR',
      base_currency: 'INR',
    });

    render(<ManagePage />);
    await screen.findAllByText('F.NS');

    const cell = await returnCell('F.NS');
    expect(cell).toBe('+0.00%');
    expect(cell).not.toContain('N/A');
  }, PAGE_TIMEOUT);
});

// ---------------------------------------------------------------------------
// 2 · PortfolioStats — an absent weight must not make the max `NaN`.
// ---------------------------------------------------------------------------
describe('PortfolioStats — concentration is withheld when no weight is measured', () => {
  const position = (over: Record<string, unknown>) =>
    ({
      id: 1,
      ticker: 'A.NS',
      quantity: 10,
      buy_price: 100,
      last_price: 110,
      current_value: 1100,
      total_cost: 1000,
      unrealized_gain_loss: 100,
      unrealized_gain_loss_pct: 10,
      sector: 'Tech',
      added_on: '2025-01-01',
      updated_on: '2025-01-01',
      ...over,
    }) as never;

  it('withholds the Largest Position card instead of printing NaN%', async () => {
    // One holding with no measured weight. `Math.max(…[NaN])` is NaN, and
    // `NaN.toFixed(1)` is the literal string "NaN" → "NaN%".
    const { PortfolioStats } = await import('@/components/portfolio/PortfolioStats');
    const { container } = render(
      <PortfolioStats positions={[position({ weight: null })]} currency="INR" />
    );

    expect(container.textContent).not.toContain('NaN');
    expect(container.textContent).not.toContain('NaN%');
    // Nothing is measured, so the card is withheld outright — the sibling
    // "Winners / Losers" card at :179 is protected by an early return, so the
    // file reads as guarded and it isn't.
    expect(screen.queryByText('Largest Position')).toBeNull();
    expect(screen.queryByText('Concentration Risk')).toBeNull();
  });

  it('still renders a measured largest weight from the legs that have one', async () => {
    // The fix must not withhold the card whenever ANY leg is unweighted — only
    // when NOTHING is measured. Dropping unmeasured legs would also be a
    // fabrication: it understates a real concentration.
    const { PortfolioStats } = await import('@/components/portfolio/PortfolioStats');
    render(
      <PortfolioStats
        positions={[
          position({ id: 1, ticker: 'A.NS', weight: 0.6 }),
          position({ id: 2, ticker: 'B.NS', weight: null }),
        ]}
        currency="INR"
      />
    );

    expect(screen.getByText('Largest Position')).toBeDefined();
    expect(screen.getByText('60.0%')).toBeDefined();
    expect(screen.getAllByText('Largest Position').length).toBe(1);
  }, PAGE_TIMEOUT);

  it('still renders a MEASURED 0.0% largest weight rather than withholding it', async () => {
    // 0 is a weight the engine measured. Withholding the card here would be the
    // same fabrication reversed.
    const { PortfolioStats } = await import('@/components/portfolio/PortfolioStats');
    render(<PortfolioStats positions={[position({ weight: 0 })]} currency="INR" />);

    expect(screen.getByText('Largest Position')).toBeDefined();
    expect(screen.getByText('0.0%')).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// The same sweep through the per-holding percentage accessors.
//
// `monetaryValue` was applied to `unrealized_gain_loss_pct` as well, so a leg
// with no measured return scored an absent 0. That 0 then did two things: it
// could WIN "Best Performer" by beating a real loser, and it was summed into
// "Average Return" as if it were a reading.
//
// The average is the mean over EVERY leg, so one unmeasured leg withholds it.
// Averaging only the measured subset would be the quieter fabrication — an
// average of a book the card describes while silently dropping a holding.
// ---------------------------------------------------------------------------
describe('PortfolioStats — an unmeasured return is never a scored zero', () => {
  const leg = (ticker: string, over: Record<string, unknown>) =>
    ({
      id: ticker.length,
      ticker,
      quantity: 10,
      buy_price: 100,
      last_price: 110,
      current_value: 1100,
      total_cost: 1000,
      unrealized_gain_loss: 100,
      unrealized_gain_loss_pct: 10,
      weight: 0.5,
      sector: 'Tech',
      added_on: '2025-01-01',
      updated_on: '2025-01-01',
      ...over,
    }) as never;

  it('never lets an unmeasured leg win Best Performer by scoring an absent 0', async () => {
    // A is the only measured leg, and it is a LOSS. B scored nothing. `0 > -10`
    // handed Best Performer to B, which had published no return at all.
    const { PortfolioStats } = await import('@/components/portfolio/PortfolioStats');
    const { container } = render(
      <PortfolioStats
        positions={[
          leg('A.NS', { unrealized_gain_loss_pct: -10 }),
          leg('B.NS', { unrealized_gain_loss_pct: null, unrealized_gain_loss: null }),
        ]}
        currency="INR"
      />
    );

    const bestCard = screen.getByText('Best Performer').closest('div.bg-green-50')!;
    // A is the only leg with a return, so it is the best performer — even
    // though its return is negative.
    expect(bestCard.textContent).toContain('A.NS');
    expect(bestCard.textContent).toContain('-10.00%');
    // The worst performer is the same leg: there is only one measurement.
    const worstCard = screen.getByText('Worst Performer').closest('div.bg-red-50')!;
    expect(worstCard.textContent).toContain('A.NS');
    // And no leg claims a fabricated 0.00% anywhere.
    expect(container.textContent).not.toContain('+0.00%');
  });

  it('withholds Average Return when one leg has no measured return', async () => {
    // The old sum absorbed the absent leg as 0 and published the mean of the
    // other one as if it described the whole book.
    const { PortfolioStats } = await import('@/components/portfolio/PortfolioStats');
    const { container } = render(
      <PortfolioStats
        positions={[
          leg('A.NS', { unrealized_gain_loss_pct: 10 }),
          leg('B.NS', { unrealized_gain_loss_pct: null }),
        ]}
        currency="INR"
      />
    );

    const avgCard = screen.getByText('Average Return').parentElement!;
    // The file's own absent marker for this card is an em dash.
    expect(avgCard.textContent).toBe('Average Return—');
    // And the withheld state takes NO colour: `null >= 0` is true, so the old
    // ternary painted a dash green, which reads as "no change".
    expect(avgCard.querySelector('.text-green-600')).toBeNull();
    expect(avgCard.querySelector('.text-red-600')).toBeNull();
    // The measured legs' own figures are untouched.
    expect(container.textContent).toContain('+10.00%');
  });

  it('still renders a measured Average Return when every leg has one', async () => {
    const { PortfolioStats } = await import('@/components/portfolio/PortfolioStats');
    render(
      <PortfolioStats
        positions={[
          leg('A.NS', { unrealized_gain_loss_pct: 10 }),
          leg('B.NS', { unrealized_gain_loss_pct: 20 }),
        ]}
        currency="INR"
      />
    );

    const avgCard = screen.getByText('Average Return').parentElement!;
    expect(avgCard.textContent).toBe('Average Return+15.00%');
    expect(avgCard.querySelector('.text-green-600')).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 3 · screener-studio — refuse the add rather than post a buy_price of 0.
// ---------------------------------------------------------------------------
describe('screener-studio — an unpriced screen row cannot be added to the book', () => {
  const screenWith = async (price: unknown) => {
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
          price,
          market_cap_cr: 1500000.0,
          pe_ratio: 28.5,
          roce_pct: 52.0,
          roe_pct: 48.0,
          dividend_yield_pct: 1.2,
        },
      ],
    });
    const { default: Page } = await import('@/app/dashboard/screener-studio/page');
    render(<Page />);
    await screen.findByText('TCS');
  };

  it('refuses the add and says why, never posting buy_price 0', async () => {
    // The screener published no price for this row — the Price cell renders
    // "₹undefined". `stock.price || 0` then posted a fabricated 0, which
    // `backend/app/models/schemas.py:17` rejects (`gt=0`): nothing persisted,
    // and the surfaced message was "buy_price: Input should be greater than 0",
    // which says nothing about the real cause.
    await screenWith(undefined);

    fireEvent.click(screen.getByText('Portfolio'));

    // The refusal is visible and names the missing price.
    expect(await screen.findByText(/no price/i)).toBeDefined();
    // And nothing was written.
    expect(mocks.addPosition).not.toHaveBeenCalled();
  }, PAGE_TIMEOUT);

  it('still adds a priced row with its real buy price, unchanged', async () => {
    await screenWith(4100.0);

    fireEvent.click(screen.getByText('Portfolio'));

    await waitFor(() => {
      expect(mocks.addPosition).toHaveBeenCalledWith(
        expect.objectContaining({ ticker: 'TCS.NS', quantity: 1, buy_price: 4100.0, weight: 1 })
      );
    });
    await screen.findByText('Added');
  });
});

// ---------------------------------------------------------------------------
// 4 · the scale-sniffing formatter — one declared scale, applied once.
// ---------------------------------------------------------------------------
describe('percent formatters apply one scale, they do not sniff the magnitude', () => {
  /**
   * The backend declares every one of these fields a FRACTION:
   *   `analytics_engine.py:4431` `"portfolio_impact": "fraction_of_portfolio_value"`
   *   `analytics_engine.py:4432` `"position_impacts": "fraction_of_position_value"`
   * Volatility-sizing weights and volatilities are fractions too (`formatWeight`
   * in the same file already multiplies them by 100 unconditionally).
   *
   * The sniff `Math.abs(value) <= 1.0 && value !== 0 ? value * 100 : value`
   * therefore multiplied exactly the legitimate values and left the ones a
   * leveraged book can actually produce (a 1.29 gross exposure, a -1.5 stress
   * impact) unscaled. The `!== 0` clause shows the sniff was narrowed once and
   * not removed; a measured 0 renders as "0.0%" either way, so it bought
   * nothing.
   */
  const STRESS_PAYLOAD = {
    scenario: 'Market Crash',
    scenario_description: 'Systemic crash',
    max_drawdown: -0.08,
    // -1.5 = a 150% loss. `Math.abs(-1.5) <= 1.0` is FALSE, so the sniff left
    // it unscaled and the page printed "-1.5%" for a 150% loss.
    portfolio_impact: -1.5,
    position_impacts: { 'AAA.NS': -1.5 },
    recovery_time: 3,
    confidence_level: 0.8,
    latest_observation_date: '2025-12-31',
  };

  it('stress-testing scales a >100% impact as a percent, never as a bare fraction', async () => {
    mocks.positions = [{ ticker: 'AAA.NS', weight: 1 }];
    mocks.runStressTest.mockResolvedValue(STRESS_PAYLOAD);

    const { default: Page } = await import('@/app/dashboard/stress-testing/page');
    render(<Page />);
    await screen.findByText('AAA.NS');

    const row = screen.getAllByText('AAA.NS').find(el => el.closest('tr'))!;
    const cells = row.closest('tr')!.querySelectorAll('td');
    const impact = cells[1].textContent ?? '';
    // A 150% loss is -150.0%, not "-1.5%".
    expect(impact).toContain('-150.0%');
    expect(impact).not.toBe('-1.5%');
  }, PAGE_TIMEOUT);

  it('stress-testing leaves an in-window fraction scaled exactly as before', async () => {
    // The no-figure-changed half: -0.185 is a fraction, ×100 is correct, and the
    // fix must render it byte-identically.
    mocks.positions = [{ ticker: 'AAA.NS', weight: 1 }];
    mocks.runStressTest.mockResolvedValue({
      ...STRESS_PAYLOAD,
      portfolio_impact: -0.185,
      position_impacts: { 'AAA.NS': -0.185 },
    });

    const { default: Page } = await import('@/app/dashboard/stress-testing/page');
    render(<Page />);
    await screen.findByText('AAA.NS');

    const row = screen.getAllByText('AAA.NS').find(el => el.closest('tr'))!;
    const cells = row.closest('tr')!.querySelectorAll('td');
    expect(cells[1].textContent ?? '').toContain('-18.5%');
  }, PAGE_TIMEOUT);

  it('liquidity scales a >100% share as a percent, never as a bare fraction', async () => {
    // `bid_ask_spread` is a fraction of price; a 1.5 spread is 150%. The sniff
    // left it at "1.5%".
    mocks.positions = [{ ticker: 'A.NS', weight: 1 }];
    mocks.getLiquidityMetrics.mockResolvedValue({
      overall_score: 7.5,
      risk_level: 'Medium',
      by_position: { 'A.NS': { score: 9.1, category: 'High', spread: 1.5 } },
    });

    const { default: Page } = await import('@/app/dashboard/liquidity/page');
    const { container } = render(<Page />);

    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });
    expect(container.textContent).toContain('150.00%');
    expect(container.textContent).not.toContain('1.50%');
  }, PAGE_TIMEOUT);

  it('volatility-sizing scales a >100% weight as a percent, never as a bare fraction', async () => {
    // A 129% gross target is a real output of the leveraged branch this page
    // renders; the sniff printed its weight as "1.3%" instead of "130.0%".
    mocks.positions = [{ ticker: 'A.NS', weight: 1 }];
    mocks.getVolatilitySizing.mockResolvedValue({
      current_weights: { 'A.NS': 1 },
      recommended_weights: { 'A.NS': 1.3 },
      trades: {},
      target_volatility: 0.15,
      current_volatility: 0.18,
      volatilities: { 'A.NS': 0.22 },
      portfolio_value: 1000000,
      portfolio_value_currency: 'INR',
      currency: 'INR',
      sizing_price: { 'A.NS': 500 },
      execution: {
        normalization_rule: 'divide_all_legs_by_gross_exposure',
        normalization_mode: 'financed_gross_exposure_exceeds_100_percent',
        weights_normalized: false,
        gross_exposure: 1.3,
        net_cash_weight: -0.3,
        financing_required: true,
        financing_requirement: 300000,
        financing_requirement_currency: 'INR',
        execution_eligible: false,
        block_reasons: ['financing_required'],
        block_reason: 'Gross exposure 1.3 exceeds 1.0',
      },
      universe_coverage: {
        requested_tickers: ['A.NS'],
        available_tickers: ['A.NS'],
        covered_tickers: ['A.NS'],
        missing_tickers: [],
        requested_count: 1,
        available_count: 1,
        coverage_ratio: 1,
        complete: true,
        status: 'complete',
      },
      data_status: 'available',
    });

    const { default: Page } = await import('@/app/dashboard/volatility-sizing/page');
    render(<Page />);
    await waitFor(() => {
      expect(screen.getAllByText('A.NS').length).toBeGreaterThan(0);
    });

    // The recommended weight of 1.3 is 130.0%, not "1.3%". Rendered in both the
    // allocation table and the weight-bar card, hence getAllByText.
    expect(screen.getAllByText('130.0%').length).toBeGreaterThan(0);
    expect(screen.queryByText('1.3%')).toBeNull();
  }, PAGE_TIMEOUT);
});
