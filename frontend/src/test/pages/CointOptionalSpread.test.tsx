/**
 * pairs — `current_spread_zscore` is `Optional[float] = None`, and `.toFixed()`
 * on the null THROWS, so one unrecorded pair blanks the whole route.
 *
 * `backend/app/models/schemas.py:514`
 *   `current_spread_zscore: Optional[float] = None`
 * and its own docstring (:499-503) says why: "`_get_cached_pair` reconstructs
 * this model from DB cache rows written by older builds … Absent means 'not
 * recorded', not 'zero'." `:147` in the page already guards the adjacent
 * `ou_half_life_days`, which is what makes `:150` read as an oversight rather
 * than a decision.
 *
 * `pairs` was `useState<any[]>` (`:41`), so `tsc` could not see it: the array's
 * element type was `any`, and `.toFixed()` on an `any` is legal. A clean
 * `tsc --noEmit` was never evidence against this. The state now carries a real
 * row interface declaring the field nullable, which is what lets the compiler
 * carry the fact all the way to the render.
 *
 * The absent marker is the page's own: the adjacent half-life cell already
 * renders the literal string `N/A` (`:147`).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({ apiGet: vi.fn() }));

vi.mock('@/lib/api', () => ({
  default: { get: mocks.apiGet },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.apiGet.mockResolvedValue({ data: { pairs: [], as_of: '2026-01-05' } });
});

/** One `/analytics/coint` pair row, shaped from `CointPairResult`. */
const pair = (over: Record<string, unknown> = {}) => ({
  ticker_a: 'A.NS',
  ticker_b: 'B.NS',
  engle_granger_pvalue: 0.0081,
  engle_granger_tstat: -3.9,
  is_cointegrated: true,
  hedge_ratio_beta: 1.0142,
  intercept_alpha: 0.21,
  ou_half_life_days: 12.5,
  current_spread_zscore: 2.35,
  signal: 'LONG_A_SHORT_B',
  ...over,
});

const scanWith = async (rows: Record<string, unknown>[]) => {
  mocks.apiGet.mockResolvedValue({
    data: { pairs: rows, as_of: '2026-01-05', as_of_semantics: 'latest_available_observation' },
  });
  const { default: PairsPage } = await import('@/app/dashboard/pairs/page');
  render(<PairsPage />);
  await waitFor(() => {
    expect(mocks.apiGet).toHaveBeenCalled();
  });
};

/** The cells of the row whose pair cell reads `<A> / <B>`. */
const rowCells = async (a: string, b: string) => {
  const label = await screen.findByText(`${a} / ${b}`);
  const row = label.closest('tr') as HTMLElement;
  expect(row).not.toBeNull();
  return Array.from(row.querySelectorAll('td'));
};

describe('pairs — an unrecorded spread z-score does not blank the route', () => {
  it('renders N/A for the null z-score and keeps every other cell on screen', async () => {
    // One cached row written by an older build carries no z-score. The page
    // rendered `p.current_spread_zscore.toFixed(2)` on it, so the exception
    // propagated out of the row render and the table never appeared at all.
    await scanWith([pair({ current_spread_zscore: null })]);

    const cells = await rowCells('A.NS', 'B.NS');
    // Cell 4 is Spread Z-Score.
    expect(cells[4].textContent).toBe('N/A');
    expect(cells[4].textContent).not.toContain('undefined');
    // The page did not blank: the row's neighbours are still published.
    expect(cells[2].textContent).toBe('1.0142');
    expect(cells[3].textContent).toBe('12.5 days');
  });

  it('renders N/A for BOTH absent optionals without losing the row', async () => {
    // `ou_half_life_days` and `current_spread_zscore` are the two
    // `Optional[...] = None` fields the columns actually read.
    await scanWith([
      pair({ ticker_a: 'A.NS', ticker_b: 'B.NS', ou_half_life_days: null, current_spread_zscore: null }),
      pair({ ticker_a: 'C.NS', ticker_b: 'D.NS', current_spread_zscore: -0.42 }),
    ]);

    const absent = await rowCells('A.NS', 'B.NS');
    expect(absent[3].textContent).toBe('N/A');
    expect(absent[4].textContent).toBe('N/A');

    // A measured neighbour is unaffected by the row that could not be scored.
    const measured = await rowCells('C.NS', 'D.NS');
    expect(measured[4].textContent).toBe('-0.42σ');
  });

  it('still renders a MEASURED z-score, with the wide-spread highlight', async () => {
    // 2.35 is |z| > 2, so the cell keeps its amber, bold class. The fix must
    // not flatten a measured reading into the absent style.
    await scanWith([pair({ current_spread_zscore: 2.35 })]);

    const cells = await rowCells('A.NS', 'B.NS');
    expect(cells[4].textContent).toBe('2.35σ');
    expect(cells[4].getAttribute('class')).toContain('text-amber-600');
  });

  it('renders a MEASURED z-score of 0 as 0.00σ, never N/A', async () => {
    // 0 is a spread sitting exactly at its mean — a real measurement. A guard
    // written as `zscore || 'N/A'` would erase it.
    await scanWith([pair({ current_spread_zscore: 0 })]);

    const cells = await rowCells('A.NS', 'B.NS');
    expect(cells[4].textContent).toBe('0.00σ');
    // |0| is not > 2, so no warning colour on a flat spread.
    expect(cells[4].getAttribute('class')).not.toContain('text-amber-600');
  });
});