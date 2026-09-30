import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// The export itself is covered in institutional-review-pdf.test.ts. This file
// covers the other half of the contract: that the call site actually fetches
// the three analytics routes and hands the responses to the exporter, and that
// a failed route leaves its block absent rather than fabricated.

const get = vi.fn();
vi.mock('@/lib/api', () => ({ default: { get: (...a: unknown[]) => get(...a) } }));

const exportInstitutionalReviewPDF = vi.fn().mockResolvedValue(undefined);
vi.mock('@/lib/export', () => ({
  ExportService: { exportInstitutionalReviewPDF: (...a: unknown[]) => exportInstitutionalReviewPDF(...a) },
}));

const addNotification = vi.fn();
vi.mock('@/hooks/useRealTime', () => ({ useNotifications: () => ({ addNotification }) }));

const storeState = {
  darkMode: false,
  toggleDarkMode: vi.fn(),
  liveDataMode: false,
  toggleLiveDataMode: vi.fn(),
  lastUpdated: null,
};
vi.mock('@/lib/store', () => ({
  useUIStore: (sel: (s: unknown) => unknown) => sel(storeState),
  usePortfolioStore: (sel: (s: unknown) => unknown) => sel(portfolioState),
}));

const portfolioState = {
  positions: [
    { ticker: 'INFY.NS', market_value_base: 1000, market_value: 900, weight: 1 },
    { ticker: 'TCS.NS', market_value: 500, weight: 0 },
  ],
  positionCount: 2,
  fetchPortfolio: vi.fn(),
  isLoading: false,
};

import { Header } from '@/components/layout/Header';

const ok = (data: unknown) => ({ data });

beforeEach(() => {
  get.mockReset();
  exportInstitutionalReviewPDF.mockClear();
  addNotification.mockClear();
  exportInstitutionalReviewPDF.mockResolvedValue(undefined);
  get.mockImplementation((url: string) => {
    if (url === '/analytics/risk-contribution') {
      return Promise.resolve(ok({ positions: { volatility: { 'INFY.NS': 0.6 }, cvar_tail: { 'INFY.NS': 0.4 } } }));
    }
    if (url === '/analytics/liquidity-limits') {
      return Promise.resolve(ok({ portfolio_weighted_days_to_liquidate_10pct: 0.5 }));
    }
    return Promise.resolve(ok({ liquidation_time_days: '1-2' }));
  });
});

async function clickExport() {
  render(<Header title="Review" />);
  fireEvent.click(screen.getByRole('button', { name: /Export PDF/i }));
  await waitFor(() => expect(exportInstitutionalReviewPDF).toHaveBeenCalled());
}

describe('Header -> exportInstitutionalReviewPDF wiring', () => {
  it('fetches all three analytics routes', async () => {
    await clickExport();
    const urls = get.mock.calls.map((c) => c[0]);
    expect(urls).toContain('/analytics/risk-contribution');
    expect(urls).toContain('/analytics/liquidity-limits');
    expect(urls).toContain('/analytics/liquidity');
  });

  it('passes the three responses as riskMetrics, keyed to the right route', async () => {
    await clickExport();
    const { riskMetrics } = exportInstitutionalReviewPDF.mock.calls[0][0];
    expect(riskMetrics.riskContribution.positions.volatility).toEqual({ 'INFY.NS': 0.6 });
    expect(riskMetrics.riskContribution.positions.cvar_tail).toEqual({ 'INFY.NS': 0.4 });
    expect(riskMetrics.liquidityLimits.portfolio_weighted_days_to_liquidate_10pct).toBe(0.5);
    expect(riskMetrics.liquidity.liquidation_time_days).toBe('1-2');
  });

  it('still passes positions, totalValue and currency', async () => {
    await clickExport();
    const payload = exportInstitutionalReviewPDF.mock.calls[0][0];
    expect(payload.positions).toHaveLength(2);
    // market_value_base wins over market_value, as before.
    expect(payload.totalValue).toBe(1500);
    expect(payload.currency).toBe('INR');
  });

  it('leaves a failed route’s block undefined rather than substituting another', async () => {
    get.mockImplementation((url: string) => {
      if (url === '/analytics/risk-contribution') return Promise.reject(new Error('503'));
      if (url === '/analytics/liquidity-limits') return Promise.reject(new Error('503'));
      return Promise.resolve(ok({ liquidation_time_days: '1-2' }));
    });
    vi.spyOn(console, 'error').mockImplementation(() => {});

    await clickExport();
    const { riskMetrics } = exportInstitutionalReviewPDF.mock.calls[0][0];
    expect(riskMetrics.riskContribution).toBeUndefined();
    expect(riskMetrics.liquidityLimits).toBeUndefined();
    // The one route that answered is still carried through.
    expect(riskMetrics.liquidity.liquidation_time_days).toBe('1-2');
    // ...and the export still runs rather than being aborted.
    expect(exportInstitutionalReviewPDF).toHaveBeenCalledTimes(1);
  });

  it('still exports when every route fails, with an empty snapshot', async () => {
    get.mockImplementation(() => Promise.reject(new Error('offline')));
    vi.spyOn(console, 'error').mockImplementation(() => {});

    await clickExport();
    const payload = exportInstitutionalReviewPDF.mock.calls[0][0];
    expect(payload.riskMetrics).toEqual({});
    expect(exportInstitutionalReviewPDF).toHaveBeenCalledTimes(1);
  });

  it('surfaces an exporter failure as an error notification', async () => {
    exportInstitutionalReviewPDF.mockRejectedValueOnce(new Error('boom'));
    vi.spyOn(console, 'error').mockImplementation(() => {});

    render(<Header title="Review" />);
    fireEvent.click(screen.getByRole('button', { name: /Export PDF/i }));

    await waitFor(() =>
      expect(addNotification).toHaveBeenCalledWith(
        'error', 'Export Failed', "Couldn't generate the PDF review."
      )
    );
  });
});
