/**
 * MarginalImpactPanel — the decision instrument.
 *
 * The product gap this closes: a screen found X, and there was no path from
 * "X is interesting" to "here is what buying X does to my book". The backend
 * answers it (`POST /api/v1/analytics/marginal-trade-impact`); these tests hold
 * the rendering to the endpoint's own contract.
 *
 * Fixtures below are shaped from `backend/app/models/schemas.py`
 * (`MarginalTradeImpactResponse`) and the block builders in
 * `backend/app/api/analytics.py` (`_marginal_statistic`,
 * `_marginal_concentration_block`, `_marginal_risk_block`, the route's
 * `_refusal`). They are not invented shapes: every key the backend publishes is
 * present, and `delta === after - before` everywhere it is published.
 *
 * The four properties under test are the ones a fabricated number would break:
 *
 *   1. A refusal is a FIRST-CLASS answer. A block that cannot be measured shows
 *      its reason and renders NO metric table at all — not a table of zeros, and
 *      not a spinner that resolves to 0.
 *   2. The DELTA is the answer and is visually the answer. Before/after are
 *      context around it, never the headline.
 *   3. A null is `N/A`, never a number — and a MEASURED 0 is still `0`, because
 *      a falsy-guard (`value || 'N/A'`) satisfies rule 3 and silently breaks
 *      this one.
 *   4. The weight is user-supplied and is never presented as a measurement.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import { MarginalImpactPanel } from '@/components/portfolio/MarginalImpactPanel';
import { analyticsApi } from '@/lib/api';
import type {
  MarginalTradeImpactResponse,
  MarginalStatistic,
} from '@/lib/api';

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getMarginalTradeImpact: vi.fn(),
  },
}));

const mockedImpact = vi.mocked(analyticsApi.getMarginalTradeImpact);

// ---------------------------------------------------------------------------
// Fixtures — verbatim from the backend builders.
// ---------------------------------------------------------------------------

/** `analytics.py:12596` `_marginal_statistic`. */
const stat = (
  before: number | null,
  after: number | null,
  overrides: Partial<MarginalStatistic> = {}
): MarginalStatistic => ({
  before,
  after,
  delta: before === null || after === null ? null : Number((after - before).toFixed(6)),
  state: 'measured',
  reason: null,
  observations: null,
  ...overrides,
});

const FUNDING_RULE_SELL_AND_REBALANCE =
  "A named leg's `target_weight` is its weight in the book AFTER the change, " +
  'funded by selling down the legs you did not name in proportion to their ' +
  'current weights.';

const PROPOSAL_PROVENANCE =
  'user_supplied: the proposed legs and their target weights are an instruction ' +
  'from the caller, not an observation.';

/**
 * A full measured response. `concentration` is always measurable for a
 * non-empty book (it is arithmetic on a weights dict); `risk` is measured here
 * because the fixture clears the 30-shared-session gate
 * (`MARGINAL_MIN_SHARED_SESSIONS = MIN_ANNUALIZE_DAYS = 30`).
 */
const measuredResponse = (
  overrides: Partial<MarginalTradeImpactResponse> = {}
): MarginalTradeImpactResponse =>
  ({
    proposal_provenance: PROPOSAL_PROVENANCE,
    funding_rule: FUNDING_RULE_SELL_AND_REBALANCE,
    current_weights: { 'HDFCBANK.NS': 0.6, 'INFY.NS': 0.4 },
    proposed_weights: { 'HDFCBANK.NS': 0.57, 'INFY.NS': 0.38, 'TCS.NS': 0.05 },
    cash_weight: null,
    funding_residual: 0,
    concentration: {
      state: 'measured',
      reason: null,
      metrics: {
        herfindahl_index: {
          ...stat(0.58, 0.41, { observations: 3 }),
          units: 'sum_of_squared_weights',
        },
        effective_positions: {
          ...stat(1.72, 2.44, { observations: 3 }),
          units: 'count_of_effective_positions',
        },
        top_3: {
          ...stat(1.0, 0.83, { observations: 3 }),
          units: 'fraction_of_weight',
        },
        diversification_score: {
          ...stat(0.0, 25.0, { observations: 3 }),
          units: 'index_0_to_100',
        },
      },
      by_leg: {
        'TCS.NS': {
          ...stat(0.0, 0.05),
          contribution_units: 'fraction_of_total_weight',
          weight_provenance: 'proposed',
        },
        'HDFCBANK.NS': {
          ...stat(0.6, 0.57),
          contribution_units: 'fraction_of_total_weight',
          weight_provenance: 'measured',
        },
      },
      before: {},
      after: {},
      weight_provenance_vocabulary: {
        measured: 'derived from the persisted book',
        proposed: 'supplied by the caller in this request',
      },
      proposed_tickers: ['TCS.NS'],
      basis: 'concentration_analysis(weights) over the current book.',
    },
    risk: {
      state: 'measured',
      reason: null,
      shared_sessions: 250,
      minimum_shared_sessions_required: 30,
      metrics: {
        annual_volatility: {
          ...stat(0.18, 0.2, { observations: 250 }),
          units: 'annualized_fraction_of_1',
          delta_percentage_points: 2.0,
        },
        var_95: {
          ...stat(0.012, 0.014, { observations: 250 }),
          units: 'daily_loss_fraction_of_1',
          delta_percentage_points: 0.2,
        },
        cvar_95: {
          ...stat(0.02, 0.023, { observations: 250 }),
          units: 'daily_loss_fraction_of_1',
          delta_percentage_points: 0.3,
        },
        sharpe_ratio: {
          ...stat(0.8, 0.84, { observations: 250 }),
          units: 'ratio',
        },
      },
      per_ticker_return_observations: { 'HDFCBANK.NS': 250, 'INFY.NS': 250, 'TCS.NS': 250 },
      tickers_below_minimum_sample: [],
      thresholds: {},
      history_window: null,
      basis: 'calculate_portfolio_metrics over one shared wide return frame.',
      unmeasurable_correlation_reason: null,
    },
    disclosure: {
      proposal_provenance: PROPOSAL_PROVENANCE,
      persisted: false,
      persistence_note: 'no PortfolioPosition row is created by this route',
      funding_rule: FUNDING_RULE_SELL_AND_REBALANCE,
      weight_derivation: {
        funding: 'sell_and_rebalance',
        funding_rule: FUNDING_RULE_SELL_AND_REBALANCE,
        current_weights: { 'HDFCBANK.NS': 0.6, 'INFY.NS': 0.4 },
        proposed_weights: { 'HDFCBANK.NS': 0.57, 'INFY.NS': 0.38, 'TCS.NS': 0.05 },
        current_total: 1.0,
        proposed_total: 1.0,
        funding_residual: 0,
        cash_weight: null,
        proposed_tickers: ['TCS.NS'],
        weight_provenance_vocabulary: {},
        unnamed_book_weight_before: 1.0,
        unnamed_book_weight_after: 0.95,
        unnamed_book_scale_factor: 0.95,
      },
      weight_provenance_vocabulary: {
        measured: 'derived from the persisted book',
        proposed: 'supplied by the caller in this request',
      },
      thresholds: {},
      states: ['measured', 'unmeasurable', 'not_attempted'],
      minimum_shared_sessions_required: 30,
      history_window: null,
      resolved_from: 'the persisted book via _load_portfolio_allocation',
      resolved_via_resolve_allocation: false,
    },
    universe_coverage: {
      requested_tickers: ['HDFCBANK.NS', 'INFY.NS', 'TCS.NS'],
      available_tickers: ['HDFCBANK.NS', 'INFY.NS', 'TCS.NS'],
      covered_tickers: ['HDFCBANK.NS', 'INFY.NS', 'TCS.NS'],
      missing_tickers: [],
      requested_count: 3,
      available_count: 3,
      coverage_ratio: 1,
      complete: true,
      status: 'complete',
    },
    data_status: 'available',
    error: null,
    ...overrides,
  }) as MarginalTradeImpactResponse;

/**
 * The risk half refusing on the shared-session floor
 * (`analytics.py:13029-13041`). `metrics` is present but every figure is null
 * with the reason attached — this is the "candidate with three weeks of history"
 * case, and the honest answer is a refusal, not a delta.
 */
const refusedRiskResponse = (): MarginalTradeImpactResponse =>
  measuredResponse({
    risk: {
      state: 'unmeasurable',
      reason:
        '3 shared return sessions on the complete-case frame, below the 30 ' +
        'required to annualize (MIN_ANNUALIZE_DAYS). Legs below the ' +
        '30-session per-leg minimum: TCS.NS=3',
      shared_sessions: 3,
      minimum_shared_sessions_required: 30,
      metrics: {
        annual_volatility: {
          ...stat(null, null, {
            state: 'unmeasurable',
            reason: '3 shared return sessions on the complete-case frame',
          }),
          units: 'annualized_fraction_of_1',
          delta_percentage_points: null,
        },
        var_95: {
          ...stat(null, null, { state: 'unmeasurable', reason: 'refused' }),
          units: 'daily_loss_fraction_of_1',
          delta_percentage_points: null,
        },
        cvar_95: {
          ...stat(null, null, { state: 'unmeasurable', reason: 'refused' }),
          units: 'daily_loss_fraction_of_1',
          delta_percentage_points: null,
        },
        sharpe_ratio: {
          ...stat(null, null, { state: 'unmeasurable', reason: 'refused' }),
          units: 'ratio',
        },
      },
      per_ticker_return_observations: { 'TCS.NS': 3 },
      tickers_below_minimum_sample: ['TCS.NS'],
      thresholds: {},
      basis: 'calculate_portfolio_metrics over one shared wide return frame.',
    } as MarginalTradeImpactResponse['risk'],
    data_status: 'partial',
  });

/** The route's own top-level `_refusal` (no book at all). */
const topLevelRefusalResponse = (): MarginalTradeImpactResponse =>
  ({
    proposal_provenance: PROPOSAL_PROVENANCE,
    funding_rule: FUNDING_RULE_SELL_AND_REBALANCE,
    current_weights: {},
    proposed_weights: {},
    cash_weight: null,
    funding_residual: null,
    concentration: {
      state: 'not_attempted',
      reason:
        'No portfolio positions found: a marginal impact is a difference ' +
        'between the book as it is and the book as proposed',
      metrics: {},
      by_leg: {},
      before: {},
      after: {},
      weight_provenance_vocabulary: {},
      proposed_tickers: ['TCS.NS'],
      basis: 'concentration_analysis(weights) needs only a weights dict.',
    },
    risk: {
      state: 'not_attempted',
      reason: 'No portfolio positions found: a marginal impact is a difference',
      shared_sessions: null,
      minimum_shared_sessions_required: 30,
      metrics: {},
      per_ticker_return_observations: {},
      thresholds: {},
    },
    disclosure: {
      proposal_provenance: PROPOSAL_PROVENANCE,
      persisted: false,
      weight_provenance_vocabulary: {},
      thresholds: {},
      states: ['measured', 'unmeasurable', 'not_attempted'],
      minimum_shared_sessions_required: 30,
      resolved_from: 'the persisted book via _load_portfolio_allocation',
      resolved_via_resolve_allocation: false,
    },
    universe_coverage: {},
    data_status: 'unavailable',
    error:
      'No portfolio positions found: a marginal impact is a difference ' +
      'between the book as it is and the book as proposed',
  }) as MarginalTradeImpactResponse;

// ---------------------------------------------------------------------------

describe('MarginalImpactPanel — refusals are first-class answers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders an unmeasurable risk half as its REASON, and renders no metric table at all', async () => {
    mockedImpact.mockResolvedValue(refusedRiskResponse());

    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);

    await screen.findByTestId('marginal-refusal-risk');

    const refusal = screen.getByTestId('marginal-refusal-risk');
    // The state travels with the refusal; "unmeasurable" is not inferred from a
    // null, it is read off the payload.
    expect(refusal).toHaveAttribute('data-state', 'unmeasurable');
    expect(refusal).toHaveTextContent(
      '3 shared return sessions on the complete-case frame, below the 30 required to annualize'
    );
    // The floor is NAMED, so the reader knows how far off the answer is.
    expect(refusal).toHaveTextContent('30');
    // The short-history leg is named rather than averaged away.
    expect(refusal).toHaveTextContent('TCS.NS=3');

    // THE assertion. A refused block publishes no measured table. If a metric
    // table exists here it is rendering something as a number that was refused.
    expect(screen.queryByTestId('marginal-metrics-risk')).toBeNull();
    expect(screen.queryByTestId('marginal-delta-annual_volatility')).toBeNull();
    expect(screen.queryByTestId('marginal-delta-sharpe_ratio')).toBeNull();

    // And the panel is still loading for nothing — no spinner left behind that
    // would resolve to 0.
    expect(screen.queryByTestId('marginal-loading')).toBeNull();

    // The concentration half WAS measured, so it is still shown. Refusing one
    // half must not erase the other.
    expect(screen.getByTestId('marginal-metrics-concentration')).toBeInTheDocument();
  });

  it('renders a not_attempted top-level refusal with the endpoint reason, and no numbers', async () => {
    mockedImpact.mockResolvedValue(topLevelRefusalResponse());

    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);

    const refusal = await screen.findByTestId('marginal-refusal');
    expect(refusal).toHaveAttribute('data-state', 'not_attempted');
    expect(refusal).toHaveTextContent('No portfolio positions found');

    expect(screen.queryByTestId('marginal-metrics-concentration')).toBeNull();
    expect(screen.queryByTestId('marginal-metrics-risk')).toBeNull();
    // Not one delta on screen, because none was measured.
    expect(document.querySelectorAll('[data-role="delta"]')).toHaveLength(0);
  });

  it('a pending assessment renders a spinner with NO number beside it', async () => {
    let release: (v: MarginalTradeImpactResponse) => void = () => {};
    mockedImpact.mockReturnValue(
      new Promise<MarginalTradeImpactResponse>((resolve) => {
        release = resolve;
      })
    );

    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);

    const loading = await screen.findByTestId('marginal-loading');
    expect(loading).toBeInTheDocument();
    // The panel's own weight readout must not read as a measurement of the
    // book while the assessment is still in flight.
    expect(document.querySelectorAll('[data-role="delta"]')).toHaveLength(0);

    release(measuredResponse());
    await screen.findByTestId('marginal-metrics-concentration');
    expect(screen.queryByTestId('marginal-loading')).toBeNull();
  });

  it('a transport failure is surfaced, never swallowed into an empty reading', async () => {
    mockedImpact.mockRejectedValue(new Error('analytics service down'));

    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);

    expect(await screen.findByTestId('marginal-error')).toHaveTextContent(
      'analytics service down'
    );
    expect(screen.queryByTestId('marginal-metrics-concentration')).toBeNull();
  });
});

describe('MarginalImpactPanel — the delta is the answer, and it looks like it', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedImpact.mockResolvedValue(measuredResponse());
  });

  it('renders the delta as the dominant cell, with before/after demoted to context', async () => {
    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);
    await screen.findByTestId('marginal-metrics-concentration');

    const delta = screen.getByTestId('marginal-delta-herfindahl_index');
    const levels = screen.getByTestId('marginal-levels-herfindahl_index');

    // The two are separate elements, each declaring which one it is.
    expect(delta).not.toBe(levels);
    expect(delta).toHaveAttribute('data-role', 'delta');
    expect(levels).toHaveAttribute('data-role', 'level');

    // THE claim: the delta is what is on screen first. -0.17 is published as the
    // difference of 0.41 and 0.58 and is rendered as such.
    expect(delta).toHaveTextContent('-0.17');
    // Levels are present as context and are visibly subordinate.
    expect(levels).toHaveTextContent('0.58');
    expect(levels).toHaveTextContent('0.41');
    expect(levels.querySelector('[data-role="level-before"]')).toHaveTextContent('0.58');
    expect(levels.querySelector('[data-role="level-after"]')).toHaveTextContent('0.41');

    // Visually distinguishable is not a claim, it is a rendered fact: the
    // delta carries weight the levels do not.
    expect(delta.className).toMatch(/font-bold/);
    expect(levels.className).not.toMatch(/font-bold/);
    expect(delta.className).not.toBe(levels.className);
  });

  it('a delta is not a level: every metric row separates the two roles', async () => {
    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);
    await screen.findByTestId('marginal-metrics-concentration');

    // Every concentration figure publishes its own delta cell and its own
    // levels cell, and no cell plays both roles.
    for (const key of [
      'herfindahl_index',
      'effective_positions',
      'top_3',
      'diversification_score',
    ]) {
      const delta = screen.getByTestId(`marginal-delta-${key}`);
      const levels = screen.getByTestId(`marginal-levels-${key}`);
      expect(delta).toHaveAttribute('data-role', 'delta');
      expect(levels).toHaveAttribute('data-role', 'level');
      expect(delta).not.toBe(levels);
      // The delta cell never carries a level's class.
      expect(delta.className).toMatch(/font-bold/);
      expect(levels.className).not.toMatch(/font-bold/);
    }

    // Fraction units render as percentages; index units do not. The choice is
    // driven by the endpoint's own `units` field, so it cannot drift.
    expect(screen.getByTestId('marginal-delta-top_3')).toHaveTextContent('-17.00%');
    expect(screen.getByTestId('marginal-levels-top_3')).toHaveTextContent('100.00%');
    expect(screen.getByTestId('marginal-delta-herfindahl_index')).not.toHaveTextContent('%');
  });

  it('states which funding rule it applied, verbatim from the endpoint', async () => {
    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);
    await screen.findByTestId('marginal-metrics-concentration');

    const funding = screen.getByTestId('marginal-funding-rule');
    expect(funding).toHaveTextContent('sell_and_rebalance');
    expect(funding).toHaveTextContent('funded by selling down the legs you did not name');
  });

  it('never presents the proposed weight as a measurement of the book', async () => {
    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);
    await screen.findByTestId('marginal-metrics-concentration');

    expect(screen.getByTestId('marginal-proposal-provenance')).toHaveTextContent(
      'not an observation'
    );
    expect(screen.getByTestId('marginal-weight-origin')).toHaveTextContent(/pre-filled/i);
    expect(screen.getByTestId('marginal-weight-origin')).toHaveTextContent(/not measured/i);
  });

  it('says so when the weight was set by the reader, not assumed by the panel', async () => {
    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);
    await screen.findByTestId('marginal-metrics-concentration');

    const input = screen.getByLabelText(/target weight/i) as HTMLInputElement;
    expect(input.value).toBe('5');

    fireEvent.change(input, { target: { value: '12.5' } });

    await waitFor(() => {
      expect(screen.getByTestId('marginal-weight-origin')).toHaveTextContent(/you set/i);
    });
    // And the change is actually sent, as a FRACTION — 12.5% is 0.125.
    await waitFor(() => {
      const last = mockedImpact.mock.calls.at(-1)?.[0];
      expect(last?.legs).toEqual([{ ticker: 'TCS.NS', target_weight: 0.125 }]);
    });
  });
});

describe('MarginalImpactPanel — null discipline', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders a null as N/A in every field and never as a number', async () => {
    const response = measuredResponse();
    response.concentration = {
      ...response.concentration,
      metrics: {
        // A figure the engine published nothing for: null on all three sides.
        herfindahl_index: {
          ...stat(null, null, {
            state: 'unmeasurable',
            reason: 'concentration_analysis published no herfindahl_index',
            observations: null,
          }),
          units: 'sum_of_squared_weights',
        },
        // A figure with a measured before and an absent after. The absent side
        // is N/A and the present side still renders — they are not the same.
        top_3: {
          ...stat(0.5, null, {
            state: 'unmeasurable',
            reason:
              'calculate_portfolio_metrics published no top_3 for the after book, so no delta exists; it is unknown, not zero',
          }),
          units: 'fraction_of_weight',
        },
        effective_positions: {
          ...stat(1.5, 2.5),
          units: 'count_of_effective_positions',
        },
        diversification_score: {
          ...stat(0, 0),
          units: 'index_0_to_100',
        },
      },
    } as MarginalTradeImpactResponse['concentration'];

    mockedImpact.mockResolvedValue(response);
    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);
    await screen.findByTestId('marginal-metrics-concentration');

    // All-null figure: N/A on the delta AND on both levels.
    const hhi = screen.getByTestId('marginal-delta-herfindahl_index');
    expect(hhi).toHaveTextContent('N/A');
    expect(hhi).not.toHaveTextContent('0.00');
    expect(screen.getByTestId('marginal-levels-herfindahl_index')).toHaveTextContent('N/A');
    // And it says WHY, rather than sitting as a bare N/A.
    expect(screen.getByTestId('marginal-state-herfindahl_index')).toHaveTextContent(
      'concentration_analysis published no herfindahl_index'
    );

    // One-sided figure: the present side is a real number, the absent side is
    // not, and the delta is not invented from the one side that exists.
    expect(screen.getByTestId('marginal-levels-top_3').querySelector(
      '[data-role="level-before"]'
    )).toHaveTextContent('50.00%');
    expect(screen.getByTestId('marginal-levels-top_3').querySelector(
      '[data-role="level-after"]'
    )).toHaveTextContent('N/A');
    expect(screen.getByTestId('marginal-delta-top_3')).toHaveTextContent('N/A');

    // THE measured-zero case. 0 before, 0 after, 0 delta — all real numbers.
    // A `value || 'N/A'` guard, or a falsy check, would turn these into N/A and
    // silently destroy a genuine reading.
    const score = screen.getByTestId('marginal-delta-diversification_score');
    expect(score).toHaveTextContent('0.00');
    expect(score).not.toHaveTextContent('N/A');
    expect(screen.getByTestId('marginal-levels-diversification_score')).toHaveTextContent(
      '0.00'
    );
    expect(
      screen.getByTestId('marginal-levels-diversification_score')
    ).not.toHaveTextContent('N/A');
    expect(screen.getByTestId('marginal-levels-effective_positions')).toHaveTextContent('1.50');
  });

  it('an absent weight reads as N/A in the panel readout, never as 0%', async () => {
    mockedImpact.mockResolvedValue(
      measuredResponse({ current_weights: {}, cash_weight: null, funding_residual: null })
    );

    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);
    await screen.findByTestId('marginal-metrics-concentration');

    expect(screen.getByTestId('marginal-cash-weight')).toHaveTextContent('N/A');
  });
});

describe('MarginalImpactPanel — request shape', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedImpact.mockResolvedValue(measuredResponse());
  });

  it('posts one leg for one ticker, uppercased and exchange-suffixed as the row gave it', async () => {
    render(<MarginalImpactPanel ticker="TCS.NS" defaultTargetWeight={0.05} />);
    await screen.findByTestId('marginal-metrics-concentration');

    expect(mockedImpact).toHaveBeenCalledWith(
      expect.objectContaining({
        legs: [{ ticker: 'TCS.NS', target_weight: 0.05 }],
        funding: 'sell_and_rebalance',
      })
    );
  });

  it('carries the ticker through a BSE scrip suffix unchanged', async () => {
    render(<MarginalImpactPanel ticker="500112.BO" defaultTargetWeight={0.03} />);
    await screen.findByTestId('marginal-metrics-concentration');

    expect(mockedImpact).toHaveBeenCalledWith(
      expect.objectContaining({
        legs: [{ ticker: '500112.BO', target_weight: 0.03 }],
      })
    );
    expect(screen.getByTestId('marginal-subject-ticker')).toHaveTextContent('500112.BO');
  });
});
