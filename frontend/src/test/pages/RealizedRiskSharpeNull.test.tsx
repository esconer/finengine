/**
 * A withheld Sharpe ratio is ABSENT, not zero.
 *
 * The engine publishes `sharpe_ratio: null` with a stated reason when a leg has
 * under 10 return observations (analytics_engine._calculate_basic_metrics).
 * The route's `annualization` flag is computed from a DIFFERENT count than the
 * engine's threshold — the route gates per-position rows on the raw row length
 * (`own_days`, analytics.py:4496) while the engine gates on the NaN-dropped
 * return count. A position can therefore carry `annualized: true` and
 * `sharpe_ratio: null` at the same time, which reaches this page.
 *
 * The colour band is the defect. In JavaScript `null >= 1` is `false` and
 * `null >= 0` is `true`, so an unguarded null falls into the yellow 0–1
 * "acceptable" band and reads exactly like a measured sub-1.0 Sharpe. Text is
 * already correct (`formatRatio` → 'N/A'); the band is what lies.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import RealizedRiskPage from '@/app/dashboard/realized-risk/page';

const updateLastUpdatedMock = vi.fn();

/**
 * The exact reachability window: `annualized` true (raw row length cleared the
 * 30-day route gate) but `sharpe_ratio` withheld by the engine's own <10
 * return-observation threshold.
 */
const positionsWithNullSharpe = {
  'SHORT.NS': {
    annual_volatility: 0.31,
    sharpe_ratio: null,
    max_drawdown: -0.11,
    total_return: 0.04,
    data_points: 34,
    annualized: true,
    is_limited_history: false,
  },
};

/** A measured Sharpe in the yellow 0–1 band, as the control case. */
const positionsWithMeasuredSharpe = {
  'MEASURED.NS': {
    annual_volatility: 0.22,
    sharpe_ratio: 0.5,
    max_drawdown: -0.09,
    total_return: 0.06,
    data_points: 210,
    annualized: true,
    is_limited_history: false,
  },
};

const makeRealizedRisk = (positions: Record<string, unknown>) => ({
  portfolio: {
    annual_return: null,
    annual_volatility: null,
    sharpe_ratio: null,
    sortino_ratio: null,
    max_drawdown: -0.02,
    var_95: -0.01,
    cvar_95: -0.015,
    hit_ratio: 0.5,
  },
  positions: {},
  instrument_risk: {
    portfolio: {
      annual_return: null,
      annual_volatility: 0.22,
      sharpe_ratio: 0.5,
      sortino_ratio: 0.6,
    },
    positions,
  },
  warnings: [],
  history_coverage: {
    requested_start: '2026-01-01',
    effective_start: '2026-01-01',
    intersection_start: '2026-01-01',
    covered_days: 210,
    full_history_days: 252,
    full_history_start: '2025-06-01',
    tickers: {},
  },
  methodology: 'test',
});

let realizedRisk = makeRealizedRisk(positionsWithMeasuredSharpe);

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: [{ ticker: 'MEASURED.NS' }, { ticker: 'SHORT.NS' }],
    fetchPortfolio: vi.fn().mockResolvedValue(undefined),
    isLoading: false,
    error: null,
    totalValue: 0,
  }),
  useUIStore: () => ({ lastUpdated: null, updateLastUpdated: updateLastUpdatedMock }),
}));

vi.mock('@/hooks/useAnalytics', () => ({
  usePortfolioAnalytics: () => ({
    data: { realizedRisk },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
  usePerformanceData: () => ({ performanceData: [], loading: false }),
}));

/** Column order in `positionColumns`: Ticker, Weight, Total Return,
 *  Volatility, Sharpe Ratio, Max Drawdown, VaR. Sharpe is index 4. */
const SHARPE_CELL_INDEX = 4;

const sharpeCellFor = (ticker: string): HTMLElement => {
  const cell = screen.getByText(ticker).closest('tr')?.querySelectorAll('td')[SHARPE_CELL_INDEX];
  if (!cell) throw new Error(`No Sharpe cell rendered for ${ticker}`);
  return cell;
};

describe('RealizedRiskPage — withheld Sharpe is never colour-banded as a number', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders a null Sharpe as N/A in neutral styling, not in the 0-1 "acceptable" band', () => {
    realizedRisk = makeRealizedRisk(positionsWithNullSharpe);
    render(<RealizedRiskPage />);

    const cell = sharpeCellFor('SHORT.NS');

    // Absent renders as the N/A dash convention.
    expect(cell.textContent).toContain('N/A');

    // The band that `null >= 0` used to select: a withheld ratio must never
    // wear the colour of a measured sub-1.0 Sharpe.
    expect(cell.querySelector('.text-yellow-600')).toBeNull();
    expect(cell.querySelector('.text-green-600')).toBeNull();
    expect(cell.querySelector('.text-red-600')).toBeNull();

    // Neutral, matching the file's other absent-value cells.
    expect(cell.querySelector('.text-gray-400')).not.toBeNull();
  });

  it('still colour-bands a MEASURED Sharpe by its value', () => {
    realizedRisk = makeRealizedRisk(positionsWithMeasuredSharpe);
    render(<RealizedRiskPage />);

    const cell = sharpeCellFor('MEASURED.NS');

    // The fix must not flatten a real number into neutral.
    expect(cell.textContent).toContain('0.50');
    expect(cell.querySelector('.text-yellow-600')).not.toBeNull();
    expect(cell.querySelector('.text-gray-400')).toBeNull();
  });

  it('keeps a measured zero reading as 0.00, never as N/A — 0.00 is a number', () => {
    realizedRisk = makeRealizedRisk({
      'ZERO.NS': {
        annual_volatility: 0.22,
        sharpe_ratio: 0,
        max_drawdown: -0.09,
        total_return: 0,
        data_points: 210,
        annualized: true,
        is_limited_history: false,
      },
    });
    render(<RealizedRiskPage />);

    const cell = sharpeCellFor('ZERO.NS');

    // The mirror of format-invariants' "N/A-never-0": an absent value renders
    // as the dash, so a MEASURED zero must stay distinguishable as 0.00.
    // `null >= 0` and `0 >= 0` are both true, so text is the only thing that
    // separates them — this is the assertion that holds the fix to N/A-not-0
    // rather than "strip every falsy value".
    expect(cell.textContent).toContain('0.00');
    expect(cell.textContent).not.toContain('N/A');
    expect(cell.querySelector('.text-gray-400')).toBeNull();
  });

  it('renders the portfolio-level withheld Sharpe as N/A and skips the efficiency insight', () => {
    realizedRisk = makeRealizedRisk(positionsWithMeasuredSharpe);
    render(<RealizedRiskPage />);

    // `portfolio.sharpe_ratio` is null and `portfolio.sortino_ratio` is null in
    // this fixture, so the "Risk-Adjusted Efficiency" insight must not fire.
    expect(screen.queryByText('Risk-Adjusted Efficiency')).toBeNull();

    // The instrument-risk Sharpe card reads `instrument_risk.portfolio`, whose
    // sharpe is 0.5 here — a measured number, so it must NOT be flattened.
    const sharpeCard = screen
      .getAllByText('Sharpe Ratio')
      .map((el) => el.closest('[data-testid="metric-card"]'))
      .find((card) => card != null);
    expect(sharpeCard).toBeDefined();
    expect(sharpeCard?.textContent).toContain('0.50');
  });
});
