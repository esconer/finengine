import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import TearSheetPage from '@/app/dashboard/tear-sheet/page';

const updateLastUpdatedMock = vi.fn();

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getTearSheet: vi.fn().mockResolvedValue({
      window: { start: '2025-09-08', end: '2026-09-07' },
  holdings: { 'OLD.NS': 0.5, 'NEW.NS': 0.5 },
  metrics: {
    total_return: 0.0548,
    cagr: null,
    sharpe: null,
    sortino: null,
    calmar: null,
    omega: null,
    tail_ratio: null,
    volatility: null,
    max_drawdown: -0.02,
    skew: null,
    kurtosis: null,
  },
  full_history: {
    metrics: {
      total_return: 0.2648,
      cagr: 0.2598,
      sharpe: 1.26,
      sortino: 1.4,
      calmar: 1.82,
      volatility: 0.19,
      max_drawdown: -0.1424,
      days: 518,
    },
    relative_vs_nifty: {
      beta_vs_nifty: 1.07,
      alpha_annualized: 0.2851,
      overlap_days: 250,
    },
    start: '2024-08-12',
  },
  relative_vs_nifty: {
    beta_vs_nifty: null,
    alpha_annualized: null,
    benchmark_sharpe: -0.2,
    benchmark_volatility: 0.15,
    benchmark_max_drawdown: -0.1,
    benchmark_total_return: -0.026,
    overlap_days: 20,
  },
  monthly_returns: { '2026': { '8': 0.02, '9': -0.01 } },
  underwater: [
    { date: '2026-08-04', drawdown: 0.0 },
    { date: '2026-09-07', drawdown: -0.02 },
  ],
  history_coverage: {
    effective_start: '2026-08-04',
    intersection_start: '2026-08-04',
    oldest_holding: '2020-01-01',
    covered_days: 25,
    truncated: true,
    annualized: false,
    requested_start: '2025-09-08',
  },
  methodology: 'test',
    }),
  },
}));

vi.mock('@/lib/store', () => ({
  useUIStore: { getState: () => ({ updateLastUpdated: updateLastUpdatedMock }) },
}));

describe('TearSheetPage — Phase 3 full-history headlines', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('headlines read full_history with a trading-days caption, not the gated holding leg', async () => {
    render(<TearSheetPage />);

    const caption = await screen.findByTestId('headline-caption');
    expect(caption.textContent).toBe('Full-history · 518 trading days');

    // Headline cards carry full-history values…
    expect(screen.getAllByText('26.48%').length).toBeGreaterThan(0);
    // …while the holding leg (5.48%) lives only in the demoted book section.
    const holding = screen.getByTestId('holding-section');
    expect(holding.textContent).toMatch(/Current book since 2026-08-04/);
    expect(holding.textContent).toMatch(/5\.48%/);
  });

  it('headline beta/alpha come from full_relative', async () => {
    render(<TearSheetPage />);

    await screen.findByTestId('headline-caption');
    // Full-history β 1.07 / α +28.51%, not the gated holding nulls.
    expect(screen.getAllByText('1.07').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\+28\.51%/).length).toBeGreaterThan(0);
  });
});
