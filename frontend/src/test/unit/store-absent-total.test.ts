/**
 * The store must not fabricate an absent total, and must not throw on an absent
 * `positions`.
 *
 * Two halves, both of them the "missing value became a number" family:
 *
 *   1. `totalValue: snapshot.total_value || 0` published `₹0.00` app-wide for a
 *      payload that carried no total. `dashboard/page.tsx:156-162` is already
 *      hardened against exactly this — its own comment reads "NaN || 0 is 0,
 *      which turns a broken payload into a confident ₹0.00" — but it can only
 *      harden what the store hands it. A `null` total reaches that guard and
 *      renders N/A; a laundered `0` does not.
 *   2. `positionCount: snapshot.positions.length` read the RAW field on the line
 *      after `positions: snapshot.positions || []` had already substituted `[]`.
 *      The substitution does not protect the next line: an absent `positions`
 *      substituted `[]` and then raised `Cannot read properties of undefined`.
 *
 * The total is typed `number | null` so a consumer cannot accidentally treat
 * absence as a number. `fetchPortfolio` carries the same `|| 0` and is held to
 * the same contract here, because it is the same field reaching the same
 * consumers by a different route.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { usePortfolioStore } from '@/lib/store';
import { portfolioApi } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  portfolioApi: {
    getPortfolio: vi.fn(),
    addPosition: vi.fn(),
    bulkAddPositions: vi.fn(),
    updatePosition: vi.fn(),
    deletePosition: vi.fn(),
  },
  analyticsApi: {},
  dataApi: {},
}));

/** A holding with no `id` collisions and only the fields the store touches. */
const position = (ticker: string) => ({
  id: ticker.length,
  ticker,
  weight: 0.5,
  last_price: 100,
  market_value: 1000,
  sector: 'Tech',
  industry: 'Software',
  added_on: '2025-01-01',
  updated_on: '2025-01-01',
});

beforeEach(() => {
  vi.mocked(portfolioApi.getPortfolio).mockReset();
  usePortfolioStore.setState({
    positions: [],
    selectedTickers: [],
    isLoading: false,
    error: null,
    totalValue: 0,
    totalWeight: 0,
    positionCount: 0,
  });
});

describe('setPortfolioSnapshot — an absent total stays null, never ₹0.00', () => {
  it('keeps totalValue null when the snapshot carries no total_value', () => {
    // `snapshot.total_value || 0` turned "the payload said nothing" into a
    // measured ₹0.00, which is indistinguishable on screen from an empty book
    // that really is worth zero.
    usePortfolioStore.getState().setPortfolioSnapshot({
      positions: [position('A.NS')],
      total_value: null,
      total_weight: 1,
    });

    expect(usePortfolioStore.getState().totalValue).toBeNull();
  });

  it('keeps totalValue null when total_value is NaN', () => {
    // `NaN || 0` is 0. This is the exact laundering the dashboard page's comment
    // warns about, one layer up.
    usePortfolioStore.getState().setPortfolioSnapshot({
      positions: [position('A.NS')],
      total_value: Number.NaN,
      total_weight: 1,
    });

    expect(usePortfolioStore.getState().totalValue).toBeNull();
  });

  it('still stores a MEASURED total of 0, never null', () => {
    // The other half of the rule. An empty book really is worth ₹0, and a
    // `value || null` guard would erase that measurement.
    usePortfolioStore.getState().setPortfolioSnapshot({
      positions: [],
      total_value: 0,
      total_weight: 0,
    });

    expect(usePortfolioStore.getState().totalValue).toBe(0);
  });

  it('keeps a real total exactly as published', () => {
    usePortfolioStore.getState().setPortfolioSnapshot({
      positions: [position('A.NS')],
      total_value: 111400,
      total_weight: 1,
    });

    expect(usePortfolioStore.getState().totalValue).toBe(111400);
  });
});

describe('setPortfolioSnapshot — an absent positions array does not throw', () => {
  it('reads the substituted array, not the raw undefined field', () => {
    // `positions: snapshot.positions || []` on one line, then
    // `snapshot.positions.length` on the next: the substitution does not protect
    // the read below it, so this raised
    // "Cannot read properties of undefined (reading 'length')".
    expect(() =>
      usePortfolioStore.getState().setPortfolioSnapshot({
        positions: undefined as never,
        total_value: 1000,
        total_weight: 1,
      })
    ).not.toThrow();

    expect(usePortfolioStore.getState().positions).toEqual([]);
    expect(usePortfolioStore.getState().positionCount).toBe(0);
  });

  it('counts the positions it stored, not a stale count', () => {
    usePortfolioStore.getState().setPortfolioSnapshot({
      positions: [position('A.NS'), position('B.NS'), position('C.NS')],
      total_value: 3000,
      total_weight: 1.5,
    });

    expect(usePortfolioStore.getState().positionCount).toBe(3);
  });
});

describe('fetchPortfolio — the same absent-total contract on the other route', () => {
  it('keeps totalValue null when the payload carries no total_value', async () => {
    vi.mocked(portfolioApi.getPortfolio).mockResolvedValueOnce({
      positions: [position('A.NS')],
      total_weight: 1,
    } as never);

    await usePortfolioStore.getState().fetchPortfolio();

    expect(usePortfolioStore.getState().totalValue).toBeNull();
  });

  it('still stores a MEASURED total of 0', async () => {
    vi.mocked(portfolioApi.getPortfolio).mockResolvedValueOnce({
      positions: [],
      total_value: 0,
      total_positions: 0,
      total_weight: 0,
      sectors: {},
    } as never);

    await usePortfolioStore.getState().fetchPortfolio();

    expect(usePortfolioStore.getState().totalValue).toBe(0);
  });
});