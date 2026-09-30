import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import ScreenerStudioPage from '@/app/dashboard/screener-studio/page';
import * as api from '@/lib/api';

vi.mock('@/lib/api', () => ({
  screenerApi: {
    getStrategies: vi.fn().mockResolvedValue([
      { key: 'coffee_can', name: 'Coffee Can Portfolio', description: 'ROCE > 15%' },
      { key: 'magic_formula', name: 'Magic Formula', description: 'High ROCE + Low PE' },
    ]),
    runScreen: vi.fn().mockResolvedValue({
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
          book_value: 250.0,
        },
      ],
    }),
    runCustomScreen: vi.fn().mockResolvedValue({
      strategy: 'custom',
      name: 'Custom Filter',
      description: 'Custom criteria',
      count: 1,
      stocks: [],
    }),
  },
  portfolioApi: {
    addPosition: vi.fn().mockResolvedValue({ status: 'success' }),
    getPortfolio: vi.fn().mockResolvedValue({ positions: [], total_value: 0 }),
  },
  // The per-row "what would this do?" action mounts MarginalImpactPanel, which
  // asks the analytics layer for the proposal's impact. Declared INSIDE the
  // factory: vi.mock is hoisted, so an outer const would be read before its
  // initialization. Shaped from MarginalTradeImpactResponse — a measured
  // concentration half, which is always measurable for a non-empty book.
  analyticsApi: {
    getMarginalTradeImpact: vi.fn().mockResolvedValue({
      proposal_provenance: 'user_supplied: the proposed legs and their target weights are an instruction from the caller, not an observation.',
      funding_rule: "A named leg's `target_weight` is its weight in the book AFTER the change, funded by selling down the legs you did not name in proportion to their current weights.",
      current_weights: { 'INFY.NS': 1 },
      proposed_weights: { 'INFY.NS': 0.95, 'TCS.NS': 0.05 },
      cash_weight: null,
      funding_residual: 0,
      concentration: {
        state: 'measured',
        reason: null,
        metrics: {
          herfindahl_index: {
            before: 1.0, after: 0.9075, delta: -0.0925,
            state: 'measured', reason: null, observations: 2,
            units: 'sum_of_squared_weights',
          },
          effective_positions: {
            before: 1.0, after: 1.1019, delta: 0.1019,
            state: 'measured', reason: null, observations: 2,
            units: 'count_of_effective_positions',
          },
          top_3: {
            before: 1.0, after: 1.0, delta: 0,
            state: 'measured', reason: null, observations: 2,
            units: 'fraction_of_weight',
          },
          diversification_score: {
            before: 0, after: 9.25, delta: 9.25,
            state: 'measured', reason: null, observations: 2,
            units: 'index_0_to_100',
          },
        },
        by_leg: {},
        before: {},
        after: {},
        weight_provenance_vocabulary: {},
        proposed_tickers: ['TCS.NS'],
        basis: 'concentration_analysis(weights) over the current book.',
      },
      risk: {
        state: 'unmeasurable',
        reason: '3 shared return sessions on the complete-case frame, below the 30 required to annualize (MIN_ANNUALIZE_DAYS).',
        shared_sessions: 3,
        minimum_shared_sessions_required: 30,
        metrics: {},
        per_ticker_return_observations: { 'TCS.NS': 3 },
        thresholds: {},
      },
      disclosure: {
        proposal_provenance: 'user_supplied: the proposed legs and their target weights are an instruction from the caller, not an observation.',
        persisted: false,
        funding_rule: "A named leg's `target_weight` is its weight in the book AFTER the change.",
        weight_derivation: { funding: 'sell_and_rebalance' },
        weight_provenance_vocabulary: {},
        thresholds: {},
        states: ['measured', 'unmeasurable', 'not_attempted'],
        minimum_shared_sessions_required: 30,
        resolved_from: 'the persisted book via _load_portfolio_allocation',
        resolved_via_resolve_allocation: false,
      },
      universe_coverage: {},
      data_status: 'partial',
      error: null,
    }),
  },
}));

describe('ScreenerStudioPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, 'alert').mockImplementation(() => {});
  });

  it('renders screener studio and screened stocks', async () => {
    render(<ScreenerStudioPage />);
    expect(screen.getByText('Screener Studio')).toBeDefined();

    await waitFor(() => {
      expect(screen.getByText('TCS')).toBeDefined();
    });

    expect(screen.getByText('Tata Consultancy Services')).toBeDefined();
    expect(screen.getByText('₹4,100.00')).toBeDefined();
    expect(screen.getByText('52.0%')).toBeDefined();
  });

  it('first add to an empty portfolio computes weight 1.00 (zero-state invariant)', async () => {
    render(<ScreenerStudioPage />);
    await waitFor(() => {
      expect(screen.getByText('TCS')).toBeDefined();
    });

    fireEvent.click(screen.getByText('Portfolio'));

    await waitFor(() => {
      expect(api.portfolioApi.addPosition).toHaveBeenCalledWith(
        expect.objectContaining({ ticker: 'TCS.NS', quantity: 1, weight: 1 })
      );
    });
    await screen.findByText('Added');
  });

  it('add failure surfaces the error inline, never window.alert', async () => {
    vi.mocked(api.portfolioApi.getPortfolio).mockRejectedValueOnce(
      new Error('portfolio service down')
    );

    render(<ScreenerStudioPage />);
    await waitFor(() => {
      expect(screen.getByText('TCS')).toBeDefined();
    });

    fireEvent.click(screen.getByText('Portfolio'));

    await screen.findByText('portfolio service down');
    expect(window.alert).not.toHaveBeenCalled();
  });

  it('strategy load failure renders the backend message with a Retry control', async () => {
    vi.mocked(api.screenerApi.getStrategies).mockRejectedValueOnce(
      new Error('strategies service down')
    );

    render(<ScreenerStudioPage />);

    await screen.findByText('strategies service down');
    expect(screen.getByText('Retry')).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// The bridge: a screen finds a candidate, and the reader needs to know what
// buying it does to the book they already hold. `screener_service._screen_ticker`
// (backend/app/services/screener_service.py:45-52) already stamps every screened
// row's `ticker` with `.NS` / `.BO`, and `addPosition` has been sending that
// same suffixed field all along — so the panel gets a ticker the analytics
// layer can resolve, with no new plumbing. These tests pin that, per exchange.
// ---------------------------------------------------------------------------
describe('ScreenerStudioPage — "what would this do?" bridge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const screenWith = async (ticker: string, symbol: string) => {
    vi.mocked(api.screenerApi.runScreen).mockResolvedValueOnce({
      strategy: 'coffee_can',
      name: 'Coffee Can Portfolio',
      description: 'ROCE > 15%',
      count: 1,
      stocks: [
        {
          symbol,
          ticker,
          name: 'Screened Candidate',
          price: 4100.0,
          market_cap_cr: 150000.0,
          pe_ratio: 28.5,
          roce_pct: 52.0,
          roe_pct: 48.0,
          dividend_yield_pct: 1.2,
          book_value: 250.0,
        },
      ],
    });
    render(<ScreenerStudioPage />);
    await screen.findByText(symbol);
  };

  it('pre-fills the panel with the screened ticker INCLUDING its .NS suffix', async () => {
    // `symbol` is the bare name the screener ran on; `ticker` is the suffixed
    // one. Sending `symbol` would ask analytics about a ticker that does not
    // exist, which is the exact failure this test exists to prevent.
    await screenWith('TCS.NS', 'TCS');

    fireEvent.click(
      screen.getByRole('button', { name: /what would TCS\.NS do to your portfolio/i })
    );

    expect(screen.getByTestId('marginal-subject-ticker')).toHaveTextContent('TCS.NS');
    await waitFor(() => {
      expect(api.analyticsApi.getMarginalTradeImpact).toHaveBeenCalledWith(
        expect.objectContaining({
          legs: [{ ticker: 'TCS.NS', target_weight: expect.any(Number) }],
        })
      );
    });
    const [req] = vi.mocked(api.analyticsApi.getMarginalTradeImpact).mock.calls.at(-1)!;
    expect(req.legs[0].ticker).toBe('TCS.NS');
    expect(req.legs[0].ticker).not.toBe('TCS');
  });

  it('pre-fills the panel with a BSE scrip INCLUDING its .BO suffix', async () => {
    // Numeric scrips keep .BO (`screener_service._screen_ticker`); the panel
    // must not normalise them to .NS.
    await screenWith('500112.BO', '500112');

    fireEvent.click(
      screen.getByRole('button', { name: /what would 500112\.BO do to your portfolio/i })
    );

    expect(screen.getByTestId('marginal-subject-ticker')).toHaveTextContent('500112.BO');
    await waitFor(() => {
      const [req] = vi.mocked(api.analyticsApi.getMarginalTradeImpact).mock.calls.at(-1)!;
      expect(req.legs[0].ticker).toBe('500112.BO');
    });
  });

  it('renders the measured delta and the refused half side by side, honestly', async () => {
    await screenWith('TCS.NS', 'TCS');

    fireEvent.click(
      screen.getByRole('button', { name: /what would TCS\.NS do to your portfolio/i })
    );

    // Concentration was measured: its delta is on screen.
    const delta = await screen.findByTestId('marginal-delta-herfindahl_index');
    expect(delta).toHaveAttribute('data-role', 'delta');
    expect(delta).toHaveTextContent('-0.09');

    // Risk was refused for a short sample: it shows its reason and publishes no
    // metric table. One screen, two honest answers.
    const refusal = screen.getByTestId('marginal-refusal-risk');
    expect(refusal).toHaveAttribute('data-state', 'unmeasurable');
    expect(refusal).toHaveTextContent('below the 30 required to annualize');
    expect(screen.queryByTestId('marginal-metrics-risk')).toBeNull();
  });

  it('the impact action does not add the position', async () => {
    await screenWith('TCS.NS', 'TCS');

    fireEvent.click(
      screen.getByRole('button', { name: /what would TCS\.NS do to your portfolio/i })
    );

    await screen.findByTestId('marginal-impact-panel');
    expect(api.portfolioApi.addPosition).not.toHaveBeenCalled();
  });

  it('the existing Portfolio action still adds the position, unchanged', async () => {
    // The bridge is additive: the pre-existing per-row action keeps its own
    // behaviour and its own ticker.
    await screenWith('TCS.NS', 'TCS');

    fireEvent.click(screen.getByText('Portfolio'));

    await waitFor(() => {
      expect(api.portfolioApi.addPosition).toHaveBeenCalledWith(
        expect.objectContaining({ ticker: 'TCS.NS', quantity: 1, weight: 1 })
      );
    });
  });
});
