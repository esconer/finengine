/**
 * The optimizer publishes a reconciled trade list; this pins the one path that
 * turns it into a committed book, and the three ways that path must refuse.
 *
 * The contract, in the order a user meets it:
 *
 *  - the apply submits the RECONCILED TRADE LIST, not `result.weights`. The
 *    rebalance workflow normalizes whatever it is handed to sum to 1.0, so
 *    posting the solver's full target vector would rebalance the whole book
 *    instead of the trades the user was shown, and posting the trade list
 *    raw would inflate every leg by 1/gross. Legs the trade list does not move
 *    are held at their published current weight and NAMED, because a ticker
 *    absent from the target map is skipped rather than liquidated;
 *  - a target that needs financing, an unavailable run, and a leg the solver
 *    left unmeasured are all ineligible — the button is disabled, the reason
 *    is on the page, and `rebalancePortfolio` is never called, not even to
 *    simulate;
 *  - the confirm leg is gated on a dry run of this exact target having
 *    completed, and the authorisation is single-use;
 *  - a leg with no measured weight renders N/A on the trade list, never a
 *    computed delta out of a missing input.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  runOptimization: vi.fn(),
  rebalancePortfolio: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: { runOptimization: mocks.runOptimization },
  portfolioApi: { rebalancePortfolio: mocks.rebalancePortfolio },
}));

import OptimizePage from '@/app/dashboard/optimize/page';

const RECONCILIATION_RULE =
  'weight_delta == round(recommended_weight - current_weight, 4) over the PUBLISHED legs';

const NORMALIZATION = {
  normalization_rule: 'divide_all_legs_by_gross_exposure',
  normalization_mode: 'fully_funded',
  weights_normalized: false,
  submitted_gross_exposure: 1.0,
  gross_exposure: 1.0,
  execution_eligible: true,
  financing_required: false,
};

/**
 * A funded, reconciled run. C is in the universe and the current weights but is
 * not traded (its solver delta was under the reconciliation threshold), so the
 * apply must NAME it at 20% to hold it rather than omit it.
 */
const fundedResult = {
  strategy: 'hrp',
  weights: { 'A.NS': 0.6, 'B.NS': 0.15, 'C.NS': 0.2, 'D.NS': 0.05 },
  expected_annual_return: 0.1,
  expected_annual_volatility: 0.15,
  expected_sharpe: 0.8,
  solver: 'hrp-test',
  universe: ['A.NS', 'B.NS', 'C.NS', 'D.NS'],
  current_weights: { 'A.NS': 0.4, 'B.NS': 0.3, 'C.NS': 0.2, 'D.NS': 0.1 },
  trades_required: {
    'A.NS': { current_weight: 0.4, recommended_weight: 0.6, weight_delta: 0.2 },
    'B.NS': { current_weight: 0.3, recommended_weight: 0.15, weight_delta: -0.15 },
    'D.NS': { current_weight: 0.1, recommended_weight: 0.05, weight_delta: -0.05 },
  },
  weight_normalization: NORMALIZATION,
  trades_required_basis: {
    weight_decimals: 4,
    weight_delta_rule: RECONCILIATION_RULE,
    trade_count: 3,
  },
  data_status: 'available',
  disclaimer: 'For illustration only.',
};

/** The vector the apply must submit: the trade list, plus every held leg. */
const EXPECTED_TARGET = {
  'A.NS': 0.6,
  'B.NS': 0.15,
  'D.NS': 0.05,
  'C.NS': 0.2,
};

const dryRunResponse = {
  success: true,
  dry_run: true,
  message: 'Simulation completed successfully (0 database records altered)',
  total_portfolio_value: 1000000,
  total_turnover_pct: 0.2,
  total_buy_inr: 200000,
  total_sell_inr: 200000,
  weight_normalization: NORMALIZATION,
  orders: [
    { ticker: 'A.NS', action: 'Buy', current_weight: 0.4, target_weight: 0.6, weight_delta: 0.2, shares_delta: 100 },
    { ticker: 'B.NS', action: 'Sell', current_weight: 0.3, target_weight: 0.15, weight_delta: -0.15, shares_delta: -50 },
    { ticker: 'C.NS', action: 'Hold', current_weight: 0.2, target_weight: 0.2, weight_delta: 0, shares_delta: 0 },
    { ticker: 'D.NS', action: 'Sell', current_weight: 0.1, target_weight: 0.05, weight_delta: -0.05, shares_delta: -10 },
  ],
};

const liveResponse = {
  success: true,
  dry_run: false,
  message: 'Successfully rebalanced 4 live positions in database',
  total_portfolio_value: 1000000,
  weight_normalization: NORMALIZATION,
  orders: dryRunResponse.orders,
};

async function runOptimizer(payload: unknown) {
  mocks.runOptimization.mockResolvedValue(payload);
  render(<OptimizePage />);
  fireEvent.click(screen.getByRole('button', { name: /Run HRP/i }));
  await waitFor(() => expect(screen.getByTestId('apply-panel')).toBeDefined());
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.rebalancePortfolio.mockResolvedValue(dryRunResponse);
});

// ---------------------------------------------------------------------------
// the apply submits the reconciled trade list
// ---------------------------------------------------------------------------
describe('optimize — the apply path', () => {
  it('submits the reconciled trade list, not the solver target vector', async () => {
    // The solver wanted a very different book (90/10). The trade list is what
    // the user was shown and what must be applied; the difference is surfaced.
    await runOptimizer({
      ...fundedResult,
      weights: { 'A.NS': 0.9, 'B.NS': 0.1 },
    });

    fireEvent.click(screen.getByText('Apply these trades'));
    fireEvent.click(screen.getByText('Simulate first'));

    await waitFor(() => {
      expect(mocks.rebalancePortfolio).toHaveBeenCalledTimes(1);
    });
    // Every traded leg comes from trades_required; C is HELD at its published
    // weight and named, so the workflow neither liquidates it nor re-normalizes.
    expect(mocks.rebalancePortfolio).toHaveBeenCalledWith(EXPECTED_TARGET, true);
    expect(mocks.rebalancePortfolio).not.toHaveBeenCalledWith(
      { 'A.NS': 0.9, 'B.NS': 0.1 },
      expect.anything()
    );

    // The disagreement is on the ticket, not resolved silently.
    const divergence = screen.getByTestId('apply-divergence');
    expect(divergence.textContent).toContain('A.NS');
    expect(divergence.textContent).toContain('B.NS');
    expect(divergence.textContent).toContain('trade list is what was shown');
  });

  it('shows the trades and the reconciliation rule before anything is committed', async () => {
    await runOptimizer(fundedResult);

    fireEvent.click(screen.getByText('Apply these trades'));

    // The confirm leg exists only inside the ticket, and it starts disabled:
    // nothing is committed before a dry run of this target.
    expect(screen.getByTestId('apply-confirm')).toBeDisabled();
    expect(mocks.rebalancePortfolio).not.toHaveBeenCalled();

    const trades = screen.getByTestId('apply-trades');
    expect(within(trades).getByText('A.NS')).toBeDefined();
    expect(trades.textContent).toContain('40.0%');
    expect(trades.textContent).toContain('60.0%');
    expect(trades.textContent).toContain('+20.0%');

    // The reconciliation rule and the normalization rule are both disclosed.
    const rule = screen.getByTestId('apply-reconciliation');
    expect(rule.textContent).toContain(RECONCILIATION_RULE);
    expect(rule.textContent).toContain('divide_all_legs_by_gross_exposure');

    // The held leg is named as held, not silently omitted.
    const summary = screen.getByTestId('apply-target-summary');
    expect(summary.textContent).toContain('100.00%');
    expect(summary.textContent).toContain('C.NS');
  });

  it('simulates first, then applies: the live leg is gated on the dry run', async () => {
    let releaseDryRun: (v: unknown) => void = () => {};
    mocks.rebalancePortfolio
      .mockImplementationOnce(() => new Promise((resolve) => { releaseDryRun = resolve; }))
      .mockResolvedValueOnce(liveResponse);

    await runOptimizer(fundedResult);
    fireEvent.click(screen.getByText('Apply these trades'));
    fireEvent.click(screen.getByTestId('apply-simulate'));

    // In flight: the confirm leg is not reachable, and nothing is committed.
    expect(screen.getByTestId('apply-confirm')).toBeDisabled();
    expect(mocks.rebalancePortfolio).toHaveBeenCalledTimes(1);
    expect(mocks.rebalancePortfolio.mock.calls[0][1]).toBe(true);

    releaseDryRun(dryRunResponse);

    await waitFor(() => {
      expect(screen.getByTestId('simulation-orders')).toBeDefined();
    });
    const dry = screen.getByTestId('simulation-orders');
    expect(dry.textContent).toContain('4 orders');
    expect(dry.textContent).toContain('no records altered');
    expect(dry.textContent).toContain('fully_funded');

    const confirm = screen.getByTestId('apply-confirm');
    expect(confirm).toBeEnabled();
    expect(confirm.textContent).toBe('Confirm and apply');
    fireEvent.click(confirm);

    await waitFor(() => {
      expect(mocks.rebalancePortfolio).toHaveBeenCalledTimes(2);
    });
    expect(mocks.rebalancePortfolio).toHaveBeenNthCalledWith(2, EXPECTED_TARGET, false);
    expect(await screen.findByTestId('apply-success')).toBeDefined();
  });

  it('never commits a target whose dry run has not run', async () => {
    await runOptimizer(fundedResult);
    fireEvent.click(screen.getByText('Apply these trades'));

    // No dry run has happened for this target, so the confirm leg is not
    // reachable — and clicking it anyway reaches nothing.
    expect(screen.getByTestId('apply-confirm')).toBeDisabled();
    fireEvent.click(screen.getByTestId('apply-confirm'));
    expect(mocks.rebalancePortfolio).not.toHaveBeenCalled();
    expect(screen.queryByTestId('apply-success')).toBeNull();
  });

  it('applies once: the authorisation is single-use', async () => {
    mocks.rebalancePortfolio
      .mockResolvedValueOnce(dryRunResponse)
      .mockResolvedValueOnce(liveResponse);

    await runOptimizer(fundedResult);
    fireEvent.click(screen.getByText('Apply these trades'));
    fireEvent.click(screen.getByTestId('apply-simulate'));
    await waitFor(() => expect(screen.getByTestId('simulation-orders')).toBeDefined());

    fireEvent.click(screen.getByTestId('apply-confirm'));
    await waitFor(() => expect(screen.getByTestId('apply-success')).toBeDefined());
    expect(mocks.rebalancePortfolio).toHaveBeenCalledTimes(2);

    // The ticket cannot be committed a second time, even by a direct click.
    const confirm = screen.getByTestId('apply-confirm');
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(mocks.rebalancePortfolio).toHaveBeenCalledTimes(2);
  });

  it('reports a rejected live apply instead of claiming success', async () => {
    mocks.rebalancePortfolio
      .mockResolvedValueOnce(dryRunResponse)
      .mockRejectedValueOnce(new Error('Rebalance target rejected (financing_required)'));

    await runOptimizer(fundedResult);
    fireEvent.click(screen.getByText('Apply these trades'));
    fireEvent.click(screen.getByTestId('apply-simulate'));
    await waitFor(() => expect(screen.getByTestId('simulation-orders')).toBeDefined());
    fireEvent.click(screen.getByTestId('apply-confirm'));

    const error = await screen.findByTestId('apply-error');
    expect(error.textContent).toContain('Rebalancing failed');
    expect(error.textContent).toContain('financing_required');
    expect(screen.queryByTestId('apply-success')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// fail-closed
// ---------------------------------------------------------------------------
describe('optimize — the apply is fail-closed', () => {
  it('a financing target is never sent, not even to simulate', async () => {
    // Both legs grow: the reconciled list sums to 150% of the book, which a
    // rebalance cannot express because normalization does not create financing.
    await runOptimizer({
      ...fundedResult,
      universe: ['A.NS', 'B.NS'],
      current_weights: { 'A.NS': 0.5, 'B.NS': 0.5 },
      weights: { 'A.NS': 0.9, 'B.NS': 0.6 },
      trades_required: {
        'A.NS': { current_weight: 0.5, recommended_weight: 0.9, weight_delta: 0.4 },
        'B.NS': { current_weight: 0.5, recommended_weight: 0.6, weight_delta: 0.1 },
      },
    });

    const blocked = screen.getByTestId('execution-blocked');
    expect(blocked.textContent).toContain('50.00% financing');
    expect(blocked.textContent).toContain('a normal rebalance cannot express gross > 100%');
    expect(blocked.textContent).toContain('divide_all_legs_by_gross_exposure');

    const apply = screen.getByText('Apply these trades').closest('button')!;
    expect(apply).toBeDisabled();
    fireEvent.click(apply);
    expect(screen.queryByTestId('apply-ticket')).toBeNull();
    expect(mocks.rebalancePortfolio).not.toHaveBeenCalled();
  });

  it('an unmeasured leg blocks the apply rather than being applied as a zero', async () => {
    await runOptimizer({
      ...fundedResult,
      trades_required: {
        ...fundedResult.trades_required,
        // The solver published a leg with no measurable target weight.
        'B.NS': { current_weight: null, recommended_weight: null, weight_delta: null },
      },
    });

    const blocked = screen.getByTestId('execution-blocked');
    expect(blocked.textContent).toContain('B.NS');
    expect(blocked.textContent).toContain('no measured weight');
    expect(blocked.textContent).toContain('partial rebalance');

    expect(screen.getByText('Apply these trades').closest('button')).toBeDisabled();
    expect(mocks.rebalancePortfolio).not.toHaveBeenCalled();
  });

  it('an unavailable optimizer run is not an executable target', async () => {
    await runOptimizer({
      strategy: 'hrp',
      weights: {},
      expected_annual_return: null,
      expected_annual_volatility: null,
      expected_sharpe: null,
      solver: 'hrp-test',
      universe: ['A.NS', 'B.NS'],
      current_weights: { 'A.NS': 0.5, 'B.NS': 0.5 },
      trades_required: {
        'A.NS': { current_weight: 0.5, recommended_weight: 0.5, weight_delta: 0 },
      },
      data_status: 'unavailable',
      error: 'No price data available for optimization',
      disclaimer: 'For illustration only.',
    });

    const blocked = screen.getByTestId('execution-blocked');
    expect(blocked.textContent).toContain('unavailable');
    expect(blocked.textContent).toContain('No price data available for optimization');
    expect(screen.getByText('Apply these trades').closest('button')).toBeDisabled();
    expect(mocks.rebalancePortfolio).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// the trade list itself: an absent weight is N/A, never a computed delta
// ---------------------------------------------------------------------------
describe('optimize — an unmeasured trade leg is N/A, not a full-size buy', () => {
  it('renders N/A for an absent current weight and computes no delta', async () => {
    await runOptimizer({
      ...fundedResult,
      trades_required: {
        // The optimizer reported a target for this holding but never measured
        // where it sits now. `0` here would read as a full-size buy.
        'Z.NS': { current_weight: null, recommended_weight: 0.4, weight_delta: null },
        'A.NS': fundedResult.trades_required['A.NS'],
        'B.NS': fundedResult.trades_required['B.NS'],
        'D.NS': fundedResult.trades_required['D.NS'],
      },
      universe: ['A.NS', 'B.NS', 'D.NS', 'Z.NS'],
    });

    const row = screen.getByTestId('trade-Z.NS');
    // The current side is N/A, never a fabricated 0.0% position...
    expect(screen.getByTestId('trade-from-Z.NS').textContent).toBe('N/A');
    expect(row.textContent).not.toMatch(/0\.0%\s*→/);
    // ...and no delta is derived out of the missing input.
    const badge = screen.getByTestId('trade-delta-Z.NS');
    expect(badge.textContent).toBe('N/A');
    expect(badge.textContent).not.toMatch(/[+-]\d/);
    // The fabricated "0.0% → 40.0% → +40.0%" row must not exist anywhere.
    expect(row.textContent).not.toContain('+40.0%');
    // The recommended side is real and is still shown.
    expect(screen.getByTestId('trade-to-Z.NS').textContent).toBe('40.0%');
  });

  it('keeps a measured zero and its real delta exactly as before', async () => {
    await runOptimizer({
      ...fundedResult,
      trades_required: {
        'E.NS': { current_weight: 0, recommended_weight: 0.4, weight_delta: 0.4 },
        'A.NS': fundedResult.trades_required['A.NS'],
        'B.NS': fundedResult.trades_required['B.NS'],
        'D.NS': fundedResult.trades_required['D.NS'],
      },
      universe: ['A.NS', 'B.NS', 'D.NS', 'E.NS'],
    });

    const row = screen.getByTestId('trade-E.NS');
    expect(row.textContent).toContain('0.0%');
    expect(row.textContent).toContain('40.0%');
    expect(screen.getByTestId('trade-delta-E.NS').textContent).toBe('+40.0%');
  });
});
