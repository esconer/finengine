/**
 * Ticket 03 (frontend half): a volatility-sizing target is only executable when
 * the engine says so, and nothing it cannot measure is ever rendered as a zero.
 *
 * These regressions pin the user-visible contract:
 *
 *  - a leveraged analytical target (gross > 100 %) blocks BOTH rebalance
 *    buttons, states the financing it needs, and never reaches
 *    `portfolioApi.rebalancePortfolio` (which now rejects it with HTTP 400);
 *  - a material notional that rounds below one whole share shows that notional
 *    and says it is below the minimum lot — not a fabricated "0 shares";
 *  - a leg with no sizing price shows N/A, never 0;
 *  - rows follow `coverage.requested_tickers`, so a dropped leg stays visible
 *    as an explicit row with no target weight;
 *  - the sizing basis (model, window, observations, price date, currency) and
 *    the gross/financing exposure are on the page.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  positions: [] as any[],
  fetchPortfolio: vi.fn().mockResolvedValue(undefined),
  getVolatilitySizing: vi.fn(),
  rebalancePortfolio: vi.fn(),
}));

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: mocks.positions,
    fetchPortfolio: mocks.fetchPortfolio,
    isLoading: false,
    error: null,
    totalValue: 0,
  }),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: { getVolatilitySizing: mocks.getVolatilitySizing },
  portfolioApi: { rebalancePortfolio: mocks.rebalancePortfolio },
}));

import VolatilitySizingPage from '@/app/dashboard/volatility-sizing/page';

const PRICED_HISTORY = {
  model: 'EWMA',
  window_start: '2025-01-02',
  window_end: '2026-09-07',
  price_window_start: '2025-01-01',
  price_window_end: '2026-09-07',
  return_observations: 299,
  per_ticker_return_observations: { 'A.NS': 299, 'B.NS': 299 },
  min_return_observations: 299,
  max_return_observations: 299,
  latest_observation: '2026-09-07',
  minimum_observations_required: 252,
  meets_minimum_sample: true,
  minimum_sample_status: 'sufficient',
  tickers_below_minimum_sample: [],
};

/** A fully funded 100% target: executable as a normal rebalance. */
const fundedPayload = {
  current_weights: { 'A.NS': 0.5, 'B.NS': 0.5 },
  recommended_weights: { 'A.NS': 0.55, 'B.NS': 0.45 },
  trades: {
    'A.NS': {
      shares_delta: 100,
      amount: 50000.0,
      amount_currency: 'INR',
      sizing_price: 500.0,
      rounding_residual: 0.0,
      rounding_tolerance: 250.0,
      below_minimum_notional: false,
      status: 'executable',
      reason: null,
    },
    'B.NS': {
      shares_delta: -100,
      amount: -50000.0,
      amount_currency: 'INR',
      sizing_price: 500.0,
      rounding_residual: 0.0,
      rounding_tolerance: 250.0,
      below_minimum_notional: false,
      status: 'executable',
      reason: null,
    },
  },
  target_volatility: 0.15,
  current_volatility: 0.18,
  volatilities: { 'A.NS': 0.22, 'B.NS': 0.14 },
  portfolio_value: 1000000,
  portfolio_value_currency: 'INR',
  currency: 'INR',
  sizing_price: { 'A.NS': 500.0, 'B.NS': 500.0 },
  sizing_price_as_of: '2026-09-07',
  sizing_price_currency: 'INR',
  sizing_price_provenance: 'measured',
  price_currency_provenance: 'measured',
  sizing_history: PRICED_HISTORY,
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
  trade_instructions_status: 'reconciled',
  trade_reconciliation: {
    rule: 'shares_delta == half_up(amount / sizing_price)',
    share_rounding_rule: 'half_up_away_from_zero_to_whole_shares',
    amount_decimals: 2,
    amount_rounding_quantum: 0.005,
    notional_floor: 1000.0,
    notional_floor_currency: 'INR',
    sizing_price_as_of: '2026-09-07',
    sizing_price_provenance: 'measured',
    reconciled: true,
    priced_trades: 2,
    max_abs_rounding_residual: 0.0,
    max_rounding_tolerance: 250.0,
    below_minimum_notional_tickers: [],
    immaterial_no_op_tickers: [],
    unavailable_tickers: [],
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
};

/** The v3 shape: 129% gross, quantified financing, not a normal rebalance. */
const leveragedPayload = {
  ...fundedPayload,
  recommended_weights: { 'A.NS': 0.7095, 'B.NS': 0.580541 },
  cash_weight: -0.290041,
  leveraged: true,
  scale_factor: 1.290041,
  execution: {
    normalization_rule: 'divide_all_legs_by_gross_exposure',
    normalization_mode: 'financed_gross_exposure_exceeds_100_percent',
    weights_normalized: false,
    gross_exposure: 1.290041,
    net_cash_weight: -0.290041,
    financing_required: true,
    financing_requirement: 290041.0,
    financing_requirement_currency: 'INR',
    execution_eligible: false,
    block_reasons: ['financing_required'],
    block_reason:
      'Gross exposure 1.290041 exceeds 1.0; the target borrows 0.290041 of the portfolio value and is not a normal rebalance',
  },
  exposure: {
    gross_exposure: 1.290041,
    net_exposure: 1.290041,
    cash_weight: -0.290041,
    financing_weight: 0.290041,
    financing_amount: 290041.0,
    currency: 'INR',
    portfolio_value: 1000000,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.fetchPortfolio.mockResolvedValue(undefined);
  mocks.rebalancePortfolio.mockResolvedValue({
    success: true,
    dry_run: true,
    message: 'ok',
    total_portfolio_value: 1000000,
  });
  mocks.positions = [{ ticker: 'A.NS', weight: 0.5 }, { ticker: 'B.NS', weight: 0.5 }];
});

describe('volatility sizing — leveraged target is not a rebalance', () => {
  it('disables both rebalance buttons, states the financing, and never calls the API', async () => {
    mocks.getVolatilitySizing.mockResolvedValue(leveragedPayload);

    render(<VolatilitySizingPage />);

    const blocked = await screen.findByTestId('execution-blocked');
    // The block reason names the financing that a rebalance cannot create.
    expect(blocked.textContent).toContain('₹2,90,041.00');
    expect(blocked.textContent).toContain('a normal rebalance cannot express gross > 100%');
    expect(blocked.textContent).toContain('not a normal rebalance');
    expect(blocked.textContent).toContain('divide_all_legs_by_gross_exposure');

    const execute = screen.getByText('Execute Rebalance').closest('button')!;
    expect(execute).toBeDisabled();

    // A disabled button cannot open the ticket, and nothing is submitted.
    fireEvent.click(execute);
    expect(screen.queryByText('🧪 Run Simulation Test')).toBeNull();
    expect(mocks.rebalancePortfolio).not.toHaveBeenCalled();

    // Gross exposure and the borrowed fraction are on the page, not hidden.
    const banner = screen.getByTestId('exposure-banner');
    expect(banner.textContent).toContain('129.00%');
    expect(banner.textContent).toContain('-29.00%');
    expect(banner.textContent).toContain('₹2,90,041.00');
    expect(banner.textContent).toContain('financed_gross_exposure_exceeds_100_percent');
  });

  it('gates the modal buttons too: a target that turns leveraged mid-ticket cannot be run', async () => {
    mocks.getVolatilitySizing.mockResolvedValueOnce(fundedPayload);

    render(<VolatilitySizingPage />);

    const execute = await screen.findByText('Execute Rebalance');
    fireEvent.click(execute);
    const runSimulation = screen.getByText('🧪 Run Simulation Test');
    expect(runSimulation).toBeEnabled();

    // The next target is leveraged: the open ticket re-gates itself.
    mocks.getVolatilitySizing.mockResolvedValue(leveragedPayload);
    fireEvent.click(screen.getByTitle('Refresh Sizing Analytics'));

    await waitFor(() => {
      expect(screen.getByText('🧪 Run Simulation Test')).toBeDisabled();
    });
    // The live leg of the same ticket is gated too.
    fireEvent.click(screen.getByText('⚡ Live Database Commit'));
    const confirm = screen.getByText('⚡ Confirm Live Rebalance');
    expect(confirm).toBeDisabled();

    const blocked = screen.getAllByTestId('execution-blocked');
    expect(blocked.length).toBeGreaterThan(0);
    expect(blocked[blocked.length - 1].textContent).toContain('cannot express gross > 100%');

    fireEvent.click(confirm);
    expect(mocks.rebalancePortfolio).not.toHaveBeenCalled();
  });

  it('a fully funded target keeps both buttons live and reports the normalization it ran under', async () => {
    mocks.getVolatilitySizing.mockResolvedValue(fundedPayload);
    mocks.rebalancePortfolio.mockResolvedValue({
      success: true,
      dry_run: true,
      message: 'Simulation completed',
      total_portfolio_value: 1000000,
      total_buy_inr: 50000,
      total_sell_inr: 50000,
      weight_normalization: {
        normalization_rule: 'divide_all_legs_by_gross_exposure',
        normalization_mode: 'fully_funded',
        weights_normalized: true,
        submitted_gross_exposure: 0.99,
        gross_exposure: 1.0,
        execution_eligible: true,
        financing_required: false,
        net_cash_weight: 0.0,
      },
    });

    render(<VolatilitySizingPage />);

    const execute = await screen.findByText('Execute Rebalance');
    expect(execute.closest('button')).toBeEnabled();
    expect(screen.queryByTestId('execution-blocked')).toBeNull();

    fireEvent.click(execute);
    fireEvent.click(screen.getByText('🧪 Run Simulation Test'));

    await waitFor(() => {
      expect(mocks.rebalancePortfolio).toHaveBeenCalledWith(fundedPayload.recommended_weights, true);
    });
    const normalization = await screen.findByTestId('simulation-normalization');
    expect(normalization.textContent).toContain('fully_funded');
    expect(normalization.textContent).toContain('99.00%');
  });

  it('blocks a leveraged target that ships no execution block at all (same rule, derived)', async () => {
    const { execution, exposure, ...withoutBlock } = leveragedPayload;
    mocks.getVolatilitySizing.mockResolvedValue(withoutBlock);

    render(<VolatilitySizingPage />);

    const blocked = await screen.findByTestId('execution-blocked');
    expect(blocked.textContent).toContain('financing');
    // The rupee amount is only quoted when the backend published one; here the
    // borrowed weight is derived and the amount stays unquantified.
    expect(blocked.textContent).toContain('29.00% financing');
    expect(screen.getByTestId('exposure-banner').textContent).toContain('129.00%');
    expect(screen.getByText('Execute Rebalance').closest('button')).toBeDisabled();
  });
});

describe('volatility sizing — unmeasured instructions render N/A', () => {
  it('a sub-lot notional shows its amount and "below minimum lot", never 0 shares', async () => {
    mocks.getVolatilitySizing.mockResolvedValue({
      ...fundedPayload,
      trades: {
        'A.NS': {
          shares_delta: 125,
          amount: 62500.0,
          amount_currency: 'INR',
          sizing_price: 500.0,
          rounding_residual: 0.0,
          rounding_tolerance: 250.0,
          below_minimum_notional: false,
          status: 'executable',
          reason: null,
        },
        'B.NS': {
          shares_delta: 0,
          amount: -1500.0,
          amount_currency: 'INR',
          sizing_price: 3400.0,
          rounding_residual: -1500.0,
          rounding_tolerance: 1700.0,
          below_minimum_notional: true,
          status: 'below_minimum_notional',
          reason: null,
        },
      },
      trade_reconciliation: {
        ...fundedPayload.trade_reconciliation,
        below_minimum_notional_tickers: ['B.NS'],
      },
      sizing_price: { 'A.NS': 500.0, 'B.NS': 3400.0 },
    });

    render(<VolatilitySizingPage />);

    expect(await screen.findAllByText('Below minimum lot')).not.toHaveLength(0);
    // The notional is the fact worth showing...
    expect(screen.getByText('-₹1,500.00')).toBeDefined();
    // ...and the share cell is N/A, not a bare "0".
    const status = screen.getAllByText('Below minimum lot')[0];
    expect(status.getAttribute('title')).toContain('cannot buy a whole share at ₹3,400.00');
    expect(status.getAttribute('title')).toContain('No order is expressible');
    const row = status.closest('tr')!;
    expect(row.textContent).toContain('N/A');
    expect(row.textContent).not.toMatch(/>\s*0\s*</);
  });

  it('a missing sizing price keeps the notional and reports the share count as N/A', async () => {
    mocks.getVolatilitySizing.mockResolvedValue({
      ...fundedPayload,
      sizing_price: {},
      sizing_price_as_of: null,
      sizing_price_provenance: 'unavailable',
      sizing_price_unavailable_reason: 'no_aligned_price_snapshot',
      price_currency_provenance: 'unavailable',
      sizing_price_currency: null,
      trades: {
        'A.NS': {
          shares_delta: null,
          amount: 50000.0,
          amount_currency: null,
          sizing_price: null,
          rounding_residual: null,
          below_minimum_notional: false,
          status: 'unavailable',
          reason: 'sizing_price_unavailable',
        },
        'B.NS': {
          shares_delta: null,
          amount: -50000.0,
          amount_currency: null,
          sizing_price: null,
          rounding_residual: null,
          below_minimum_notional: false,
          status: 'unavailable',
          reason: 'sizing_price_unavailable',
        },
      },
      trade_instructions_status: 'unavailable',
      sizing_price_as_of_display: null,
    });

    render(<VolatilitySizingPage />);

    const notExecutable = await screen.findAllByText('Not executable');
    expect(notExecutable.length).toBeGreaterThan(0);
    expect(notExecutable[0].getAttribute('title')).toContain('share count is N/A');
    // The sizing price date is unavailable, never a fabricated as-of.
    const basis = screen.getByTestId('sizing-basis');
    expect(basis.textContent).toContain('Sizing price as of:');
    expect(basis.textContent).toContain('unavailable');
    expect(basis.textContent).toContain('not reported'); // currency was not reported either
  });
});

describe('volatility sizing — universe, basis, and dropped legs', () => {
  it('builds rows from coverage.requested_tickers and keeps a dropped leg visible', async () => {
    // A roster-only ticker must not become a row; a covered-but-dropped one must.
    mocks.positions = [
      { ticker: 'A.NS', weight: 0.5 },
      { ticker: 'B.NS', weight: 0.3 },
      { ticker: 'ROSTERONLY.NS', weight: 0.2 },
    ];
    mocks.getVolatilitySizing.mockResolvedValue({
      ...fundedPayload,
      current_weights: { 'A.NS': 0.5, 'B.NS': 0.3, 'C.NS': 0.2 },
      recommended_weights: { 'A.NS': 0.55, 'B.NS': 0.45 },
      trades: {
        ...fundedPayload.trades,
        'B.NS': { ...fundedPayload.trades['B.NS'], shares_delta: null, amount: null, status: 'unavailable', reason: 'portfolio_value_unavailable' },
      },
      universe_coverage: {
        requested_tickers: ['A.NS', 'B.NS', 'C.NS'],
        available_tickers: ['A.NS', 'B.NS'],
        covered_tickers: ['A.NS', 'B.NS'],
        missing_tickers: ['C.NS'],
        requested_count: 3,
        available_count: 2,
        coverage_ratio: 0.666667,
        complete: false,
        status: 'partial',
      },
      data_status: 'partial',
    });

    render(<VolatilitySizingPage />);

    // The dropped leg is a row, with no target weight and no share count.
    const table = within(await screen.findByRole('table'));
    const dropped = table.getByText('C.NS').closest('tr')!;
    expect(dropped.textContent).toContain('No sizing instruction');
    expect(dropped.textContent).toContain('N/A');
    expect(dropped.textContent).toContain('No target');
    expect(screen.getByTestId('dropped-legs').textContent).toContain('C.NS');

    // A ticker that exists only in the local roster is not a sizing row.
    expect(screen.queryByText('ROSTERONLY.NS')).toBeNull();
    // Three positions were requested, and the count reflects the request.
    expect(screen.getByText('Position-Level Sizing Analysis (3)')).toBeDefined();
  });

  it('states the sizing basis: model, window, observations, price date, currency, sample status', async () => {
    mocks.getVolatilitySizing.mockResolvedValue(fundedPayload);

    render(<VolatilitySizingPage />);

    const basis = await screen.findByTestId('sizing-basis');
    expect(basis.textContent).toContain('EWMA');
    expect(basis.textContent).toContain('2025-01-02 → 2026-09-07');
    expect(basis.textContent).toContain('299 (min 299 · 252 required)');
    expect(basis.textContent).toContain('Sizing price as of:');
    expect(basis.textContent).toContain('2026-09-07');
    expect(basis.textContent).toContain('INR');
    expect(screen.getByTestId('sizing-sample-status').textContent).toContain('Sufficient sample');
  });

  it('flags an insufficient sample and names the legs below the gate', async () => {
    mocks.getVolatilitySizing.mockResolvedValue({
      ...fundedPayload,
      sizing_history: {
        ...PRICED_HISTORY,
        return_observations: 11,
        min_return_observations: 11,
        max_return_observations: 299,
        meets_minimum_sample: false,
        minimum_sample_status: 'insufficient',
        tickers_below_minimum_sample: ['B.NS'],
      },
    });

    render(<VolatilitySizingPage />);

    const status = await screen.findByTestId('sizing-sample-status');
    expect(status.textContent).toContain('Insufficient sample: 11 of 252 observations');
    expect(status.textContent).toContain('below minimum: B.NS');
  });

  it('surfaces an unavailable sizing response instead of a zero-filled book', async () => {
    mocks.getVolatilitySizing.mockResolvedValue({
      current_weights: { 'A.NS': 1.0 },
      recommended_weights: { 'A.NS': 1.0 },
      // The pre-contract shape: a bare 0 shares / 0 amount carries no status,
      // so it must not be presented as an executable instruction.
      trades: { 'A.NS': { shares_delta: 0, amount: 0 } },
      target_volatility: 0.15,
      data_status: 'unavailable',
      error: 'No price data available for volatility sizing',
    });

    render(<VolatilitySizingPage />);

    const banner = await screen.findByTestId('sizing-error-banner');
    expect(banner.textContent).toContain('No price data available for volatility sizing');
    expect(screen.getAllByText('Not executable').length).toBeGreaterThan(0);
    expect(screen.getByText('Execute Rebalance').closest('button')).toBeDisabled();
  });
});

describe('volatility sizing — CSV export', () => {
  it('exports N/A, never 0, for legs with no expressible share count', async () => {
    mocks.getVolatilitySizing.mockResolvedValue({
      ...fundedPayload,
      trades: {
        'A.NS': fundedPayload.trades['A.NS'],
        'B.NS': {
          shares_delta: 0,
          amount: -1500.0,
          amount_currency: 'INR',
          sizing_price: 3400.0,
          rounding_residual: -1500.0,
          below_minimum_notional: true,
          status: 'below_minimum_notional',
          reason: null,
        },
      },
    });

    const clicked: HTMLAnchorElement[] = [];
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this);
      });

    try {
      render(<VolatilitySizingPage />);
      fireEvent.click(await screen.findByText('Export CSV'));

      expect(clicked).toHaveLength(1);
      const csv = decodeURIComponent(clicked[0].getAttribute('href')!);
      const [, aRow, bRow] = csv.split('\n');
      // Executable leg keeps its whole-share count.
      expect(aRow).toContain('"100"');
      // Sub-lot leg exports N/A for the share count, plus its status.
      // (A leading "-" is apostrophe-prefixed by the shared CSV-injection guard.)
      expect(bRow).toContain('"N/A"');
      expect(bRow).toContain('"Below minimum lot"');
      expect(bRow).toContain('"\'-1500.00"');
      expect(bRow).not.toContain('"0"');
    } finally {
      clickSpy.mockRestore();
    }
  });
});
