/**
 * V3-06 holding-window disclosure: a reconstructed analytics start is never
 * presented as a stored holding date, and a position's limited-history status
 * comes from its OWN return observations rather than portfolio/global counts.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import RealizedRiskPage from '@/app/dashboard/realized-risk/page';
import TearSheetPage from '@/app/dashboard/tear-sheet/page';
import { analyticsApi } from '@/lib/api';
import {
  analyticsStartClaim,
  describeOwnHistory,
  holdingWindowHeadline,
  isOwnHistoryLimited,
  observationsOf,
  provenanceNote,
  resolveTickerStart,
  resolveWindowStart,
} from '@/lib/historyFormat';

// Both pages read the UI store differently (hook vs getState), so the mock is
// a callable store with a getState attached. The positions array is hoisted so
// its identity is stable across renders, exactly like a zustand snapshot.
const { updateLastUpdatedMock, useUIStoreMock, portfolioPositions } = vi.hoisted(() => {
  const updateLastUpdated = vi.fn();
  const useUIStore: any = () => ({ lastUpdated: null, updateLastUpdated });
  useUIStore.getState = () => ({ updateLastUpdated });
  return {
    updateLastUpdatedMock: updateLastUpdated,
    useUIStoreMock: useUIStore,
    portfolioPositions: [
      { ticker: 'NIFTYIETF.NS', added_on: '2026-06-08' },
      { ticker: 'OLD.NS', added_on: '2026-08-04' },
    ],
  };
});

// NIFTYIETF shape from the v3 artifact: 20 own return observations behind a
// 176-day full-exchange-history instrument leg, window start inferred from the
// buy price (2026-05-19) while the stored import stamp is 2026-06-08.
const inferredCoverage = {
  requested_start: '2025-09-08',
  effective_start: '2026-08-04',
  intersection_start: '2026-08-04',
  oldest_holding: '2026-05-19',
  covered_days: 39,
  truncated: true,
  annualized: true,
  full_history_days: 176,
  full_history_start: '2026-01-02',
  effective_start_source: 'stored_added_on',
  tickers: {
    'NIFTYIETF.NS': {
      effective_start: '2026-05-19',
      analytics_start: '2026-05-19',
      analytics_start_source: 'buy_price_inferred',
      stored_added_on: '2026-06-08',
      buy_price_inferred: '2026-05-19',
      raw_days: 21,
      masked_days: 21,
      return_observations: 20,
      limited_history: true,
    },
    'OLD.NS': {
      effective_start: '2026-08-04',
      analytics_start: '2026-08-04',
      analytics_start_source: 'stored_added_on',
      stored_added_on: '2026-08-04',
      raw_days: 39,
      masked_days: 39,
      return_observations: 38,
    },
  },
};

const realizedRisk = {
  portfolio: { max_drawdown: -0.02, var_95: -0.01, cvar_95: -0.015, hit_ratio: 0.5 },
  positions: {
    'NIFTYIETF.NS': { data_points: 20, is_limited_history: true, weight: 0.4, history_warning: null },
  },
  instrument_risk: {
    portfolio: { annual_return: 0.1, annual_volatility: 0.2, sharpe_ratio: 0.5, sortino_ratio: 0.6 },
    positions: {
      'NIFTYIETF.NS': { annual_volatility: 0.22, sharpe_ratio: 0.9, max_drawdown: -0.08, total_return: 0.05, data_points: 20 },
      'OLD.NS': { annual_volatility: 0.18, sharpe_ratio: 1.1, max_drawdown: -0.11, total_return: 0.08, data_points: 38 },
    },
  },
  warnings: [
    {
      ticker: 'NIFTYIETF.NS',
      data_points: 20,
      message:
        'NIFTYIETF.NS: 20 own return observations — analytics start 2026-05-19 is inferred from the buy price; no holding date was stored (import stamp 2026-06-08).',
    },
    {
      ticker: 'OLD.NS',
      data_points: 38,
      message: 'OLD.NS: 38 own return observations — held since 2026-08-04 (stored import date).',
    },
  ],
  data_range: { start: '2025-09-08', end: '2026-09-07' },
  history_coverage: inferredCoverage,
  methodology: 'test',
};

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: portfolioPositions,
    fetchPortfolio: vi.fn().mockResolvedValue(undefined),
    isLoading: false,
    error: null,
    totalValue: 0,
  }),
  useUIStore: useUIStoreMock,
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

vi.mock('@/lib/api', () => ({
  analyticsApi: { getTearSheet: vi.fn() },
}));

describe('historyFormat — provenance vocabulary', () => {
  it('reads the declared source first, then the stored import date', () => {
    expect(
      resolveTickerStart({
        effective_start: '2026-05-19',
        stored_added_on: '2026-06-08',
      }).source,
    ).toBe('buy_price_inferred');
    expect(
      resolveTickerStart({
        effective_start: '2026-08-04',
        stored_added_on: '2026-08-04',
      }).source,
    ).toBe('stored_added_on');
    // Declared provenance wins even when the stored date is missing.
    expect(
      resolveTickerStart({ effective_start: '2026-05-19', analytics_start_source: 'buy_price_inferred' })
        .source,
    ).toBe('buy_price_inferred');
    // A date with nothing to compare against is never called a holding date.
    expect(resolveTickerStart({ effective_start: '2026-05-19' }).source).toBe('unknown');
  });

  it('never claims a holding date that was not stored', () => {
    expect(analyticsStartClaim('2026-06-08', 'stored_added_on')).toBe(
      'held since 2026-06-08 (stored import date)',
    );
    const inferred = analyticsStartClaim('2026-05-19', 'buy_price_inferred', '2026-06-08');
    expect(inferred).toContain('inferred from the buy price');
    expect(inferred).toContain('no holding date was stored');
    expect(inferred).toContain('2026-06-08');
    expect(inferred).not.toContain('held since');
    expect(analyticsStartClaim(null, 'unknown')).toBe('holding start unknown');
    expect(analyticsStartClaim('2026-05-19', 'unknown')).toContain('provenance not reported');
  });

  it('uses each position own observations for the limited-history gate', () => {
    // 20 own observations behind a 39-day portfolio and a 176-day instrument
    // leg is still limited history for that position.
    const short = { return_observations: 20, data_points: 20 };
    const long = { return_observations: 176, data_points: 176 };
    expect(observationsOf(short)).toBe(20);
    expect(isOwnHistoryLimited(short)).toBe(true);
    expect(isOwnHistoryLimited(long)).toBe(false);
    expect(describeOwnHistory(short)).toBe('20 own return observations');
    expect(isOwnHistoryLimited({ return_observations: 175, is_limited_history: true })).toBe(false);
    expect(isOwnHistoryLimited({ is_limited_history: true })).toBe(true);
    expect(observationsOf({})).toBeNull();
  });

  it('adds the inferred qualifier only to the headline it belongs to', () => {
    const stored = holdingWindowHeadline({
      coveredDays: 39,
      start: '2026-08-04',
      source: 'stored_added_on',
      heldLonger: 1,
      total: 2,
      fullDays: 176,
    });
    expect(stored).toBe(
      'Realized P&L covers 39 trading days since 2026-08-04 — 1 of 2 positions held longer; instrument risk uses full 176d',
    );
    const inferred = holdingWindowHeadline({ coveredDays: 39, start: '2026-05-19', source: 'buy_price_inferred' });
    expect(inferred).toContain('(inferred analytics start)');
    expect(inferred).not.toContain('held since');
  });

  it('provenance note names the inferred legs and stays silent otherwise', () => {
    const note = provenanceNote({ coverage: inferredCoverage });
    expect(note).toContain('NIFTYIETF.NS');
    expect(note).toContain('inferred from the buy price');
    expect(note).not.toContain('OLD.NS');
    expect(
      provenanceNote({
        coverage: {
          ...inferredCoverage,
          tickers: { 'OLD.NS': inferredCoverage.tickers['OLD.NS'] },
        },
      }),
    ).toBeNull();
    // The portfolio window is the newest start: here a stored date.
    expect(resolveWindowStart({ coverage: inferredCoverage }).source).toBe('stored_added_on');
  });
});

describe('RealizedRiskPage — per-position provenance disclosure', () => {
  beforeEach(() => vi.clearAllMocks());

  it('names the inferred analytics start and never says "held since" for it', async () => {
    render(<RealizedRiskPage />);

    const banner = await screen.findByTestId('coverage-banner');
    expect(banner.textContent).toMatch(/Realized P&L covers 39 trading days since 2026-08-04/);

    const note = screen.getByTestId('coverage-provenance');
    expect(note.textContent).toMatch(/NIFTYIETF\.NS: analytics start 2026-05-19 is inferred from the buy price/);
    expect(note.textContent).toMatch(/no holding date was stored \(import stamp 2026-06-08\)/);

    fireEvent.click(screen.getByTestId('coverage-details-toggle'));
    await waitFor(() => expect(screen.getByTestId('coverage-details')).toBeDefined());
    const bullets = Array.from(
      screen.getByTestId('coverage-details').querySelectorAll('p'),
    )
      .map((node) => node.textContent ?? '')
      .filter((text) => text.trim().startsWith('•'));

    const etf = bullets.find((text) => text.includes('NIFTYIETF.NS')) ?? '';
    const stored = bullets.find((text) => text.includes('OLD.NS')) ?? '';

    // The inferred leg states its OWN observations and its inferred start...
    expect(etf).toMatch(/20 own return observations/);
    expect(etf).toMatch(/analytics start 2026-05-19 is inferred from the buy price/);
    expect(etf).toMatch(/no holding date was stored \(import stamp 2026-06-08\)/);
    // ...and never claims a holding date, while the stored leg keeps its own.
    expect(etf).not.toMatch(/held since/);
    expect(stored).toMatch(/38 own return observations/);
    expect(stored).toMatch(/held since 2026-08-04 \(stored import date\)/);
  });

  it('badges the 20-observation leg as limited on its own sample, not the 176d instrument leg', async () => {
    render(<RealizedRiskPage />);

    await screen.findByTestId('coverage-banner');
    const badge = await screen.findByTitle(/20 own return observations/);
    expect(badge.textContent).toContain('<30d own history');
    expect(badge.getAttribute('title')).toMatch(/inferred from the buy price/);
    expect(badge.getAttribute('title')).toMatch(/annualized ratios are suppressed below 30 own observations/);
    // The full-history instrument leg does not lift the holding-window status.
    expect(screen.getByText('Instrument Risk — Full Exchange History (176 trading days, since 2026-01-02)')).toBeDefined();
  });
});

describe('TearSheetPage — holding-window provenance', () => {
  beforeEach(() => vi.clearAllMocks());

  it('labels the book window with its provenance and shows the inferred note', async () => {
    (analyticsApi.getTearSheet as ReturnType<typeof vi.fn>).mockResolvedValue({
      window: { start: '2025-09-08', end: '2026-09-07' },
      holdings: { 'NIFTYIETF.NS': 0.4, 'OLD.NS': 0.6 },
      metrics: { total_return: 0.0548, max_drawdown: -0.02 },
      full_history: { metrics: { total_return: 0.2648, cagr: 0.2598, days: 176 } },
      relative_vs_nifty: {},
      monthly_returns: { '2026': { '8': 0.02 } },
      underwater: [{ date: '2026-09-07', drawdown: -0.02 }],
      history_coverage: inferredCoverage,
      methodology: 'test',
    });

    render(<TearSheetPage />);

    const holding = await screen.findByTestId('holding-section');
    expect(holding.textContent).toMatch(/Current book since 2026-08-04/);

    const note = screen.getByTestId('holding-provenance');
    expect(note.textContent).toMatch(/analytics start 2026-05-19 is inferred from the buy price/);

    const chip = screen.getByTestId('holding-window-chip');
    expect(chip.textContent).toMatch(/39d since 2026-08-04/);
    // Stored window start: no inferred qualifier, and the claim says "held since".
    expect(chip.getAttribute('title')).toBe('held since 2026-08-04 (stored import date)');
  });

  it('qualifies an inferred book window start in the chip and the heading', async () => {
    (analyticsApi.getTearSheet as ReturnType<typeof vi.fn>).mockResolvedValue({
      window: { start: '2025-09-08', end: '2026-09-07' },
      holdings: { 'NOBUY.NS': 1.0 },
      metrics: { total_return: 0.02, max_drawdown: -0.01 },
      full_history: null,
      relative_vs_nifty: {},
      monthly_returns: {},
      underwater: [{ date: '2026-09-07', drawdown: -0.01 }],
      history_coverage: {
        ...inferredCoverage,
        effective_start: '2026-05-19',
        intersection_start: '2026-05-19',
        effective_start_source: 'buy_price_inferred',
        tickers: {
          'NOBUY.NS': {
            ...inferredCoverage.tickers['NIFTYIETF.NS'],
            effective_start: '2026-05-19',
            stored_added_on: null,
          },
        },
      },
      methodology: 'test',
    });

    render(<TearSheetPage />);

    const holding = await screen.findByTestId('holding-section');
    expect(holding.textContent).toMatch(/Current book since 2026-05-19 \(inferred analytics start\)/);
    expect(holding.textContent).not.toMatch(/held since 2026-05-19/);

    const chip = screen.getByTestId('holding-window-chip');
    expect(chip.getAttribute('title')).toMatch(/no holding date was stored/);
  });
});
