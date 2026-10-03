/**
 * AddPositionModalSimple â€” an UNMEASURED book total must not become a
 * 100% position weight.
 *
 * Two sites, both FE-7:
 *   1. `:45 setTotalPortfolioValue(data.total_value || 0)` â€” the same
 *      laundering the store just stopped doing (`store.ts` now types
 *      `totalValue: number | null`). This is LOCAL state, so the store's
 *      nullable type protects nothing here: `PortfolioSummary.total_value` is
 *      declared `number` (types/index.ts:58) and `null` slips past `tsc`.
 *   2. `:88-89 positionValue / (totalPortfolioValue + positionValue)` â€” with the
 *      total laundered to 0 the denominator became `positionValue`, so the
 *      weight came out as exactly 1.0: a fabricated 100% for a book whose
 *      value was never known.
 *
 * THE INVARIANT THAT MUST NOT CHANGE (AGENTS.md, "Zero-State Portfolio
 * Weights"): the first asset added to an EMPTY portfolio is 100.00%, and that
 * is a REAL measurement â€” an empty book consists entirely of the one position
 * being added. It must survive even when the payload omits `total_value`, and
 * it must not be generalised into "unknown total â‡’ 100%". Those are different
 * cases: an empty book is measured to be empty, an unknown total is not
 * measured at all. The first two cases below pin the invariant; the third is
 * the defect.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { AddPositionModalSimple } from '@/components/portfolio/AddPositionModalSimple';
import { portfolioApi } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  portfolioApi: { getPortfolio: vi.fn() },
}));

const getPortfolio = () => portfolioApi.getPortfolio as unknown as ReturnType<typeof vi.fn>;

/** A holding in an existing book, so the modal is NOT on its zero-state path. */
const existingBook = (totalValue: unknown) => ({
  positions: [
    { id: 1, ticker: 'HOLD.NS', quantity: 10, buy_price: 100, last_price: 100, current_value: 1000 },
  ],
  total_value: totalValue,
  total_weight: 1,
});

beforeEach(() => {
  vi.clearAllMocks();
});

const openWith = async (payload: Record<string, unknown>) => {
  getPortfolio().mockResolvedValue(payload);
  const onAdd = vi.fn().mockResolvedValue(undefined);
  render(
    <AddPositionModalSimple isOpen onClose={vi.fn()} onAdd={onAdd} currency="INR" />
  );
  // The weight is only computed after the portfolio fetch lands.
  await waitFor(() => {
    expect(getPortfolio()).toHaveBeenCalled();
  });
  return onAdd;
};

/** Types a complete, valid position: 10 shares at 1500. */
const fillPosition = () => {
  fireEvent.change(screen.getByLabelText('Stock Ticker *'), { target: { value: 'INFY.NS' } });
  fireEvent.change(screen.getByPlaceholderText('100'), { target: { value: '10' } });
  fireEvent.change(screen.getByPlaceholderText('100.00'), { target: { value: '1500' } });
};

const weightField = () => screen.getByLabelText('Portfolio Weight (Auto-calculated)') as HTMLInputElement;

describe('AddPositionModalSimple â€” the zero-state weight invariant holds', () => {
  it('still publishes weight 1.0 for an empty book measured at zero', async () => {
    const onAdd = await openWith({ positions: [], total_value: 0 });
    fillPosition();

    await waitFor(() => {
      expect(weightField().value).toBe('100.00%');
    });

    fireEvent.click(screen.getByRole('button', { name: /Add Position/ }));
    await waitFor(() => {
      expect(onAdd).toHaveBeenCalledTimes(1);
    });
    expect(onAdd.mock.calls[0][0].weight).toBe(1);
  });

  it('still publishes weight 1.0 for an empty book whose total was NOT published', async () => {
    // The discriminating case. `positions: []` is a MEASUREMENT: the book has
    // no holdings, so the position being added is the whole of it. That is a
    // real 100% and must not become N/A, even with `total_value` absent â€” the
    // missing total is irrelevant to a book with nothing in it.
    const onAdd = await openWith({ positions: [], total_value: null });
    fillPosition();

    await waitFor(() => {
      expect(weightField().value).toBe('100.00%');
    });

    fireEvent.click(screen.getByRole('button', { name: /Add Position/ }));
    await waitFor(() => {
      expect(onAdd).toHaveBeenCalledTimes(1);
    });
    expect(onAdd.mock.calls[0][0].weight).toBe(1);
  });
});

describe('AddPositionModalSimple â€” an unknown total for a NON-empty book refuses', () => {
  it('never publishes a 100% weight derived from a laundered zero total', async () => {
    const onAdd = await openWith(existingBook(null));
    fillPosition();

    // 10 Ã— 1500 = 15000 against a total of 0 + 15000 â†’ 1.0 exactly. That is the
    // fabrication: the book holds a position the engine never valued, and the
    // new one was published as the entire portfolio.
    await waitFor(() => {
      expect(weightField().value).not.toBe('100.00%');
    });
    expect(weightField().value).toBe('N/A');
  });

  it('names the reason instead of publishing a number', async () => {
    await openWith(existingBook(null));
    fillPosition();

    await waitFor(() => {
      expect(screen.getAllByText(/portfolio total/i).length).toBeGreaterThan(0);
    });
    expect(weightField().value).toBe('N/A');
  });

  it('refuses to submit, because no correct weight can be recorded', async () => {
    // The weight field is read-only, so there is no honest value a user could
    // supply instead: the only correct answer to "what share of my book is
    // this?" when the book's value is unknown is to decline the write.
    const onAdd = await openWith(existingBook(null));
    fillPosition();

    await waitFor(() => {
      expect((screen.getByRole('button', { name: /Add Position/ }) as HTMLButtonElement).disabled)
        .toBe(true);
    });

    fireEvent.click(screen.getByRole('button', { name: /Add Position/ }));
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('still computes the real weight when the total IS published', async () => {
    // 15000 / (1000 + 15000) = 0.9375. A guard that refused every non-empty
    // book would pass the cases above and break this one.
    const onAdd = await openWith(existingBook(1000));
    fillPosition();

    await waitFor(() => {
      expect(weightField().value).toBe('93.75%');
    });

    fireEvent.click(screen.getByRole('button', { name: /Add Position/ }));
    await waitFor(() => {
      expect(onAdd).toHaveBeenCalledTimes(1);
    });
    expect(onAdd.mock.calls[0][0].weight).toBeCloseTo(0.9375, 6);
  });

  it('still computes the real weight for a book measured at zero total value', async () => {
    // A book with holdings but a MEASURED total of 0 is not the same as an
    // unknown total: the engine said zero, so the arithmetic is defined.
    const onAdd = await openWith(existingBook(0));
    fillPosition();

    await waitFor(() => {
      expect(weightField().value).toBe('100.00%');
    });
    fireEvent.click(screen.getByRole('button', { name: /Add Position/ }));
    await waitFor(() => {
      expect(onAdd).toHaveBeenCalledTimes(1);
    });
    expect(onAdd.mock.calls[0][0].weight).toBe(1);
  });
});
