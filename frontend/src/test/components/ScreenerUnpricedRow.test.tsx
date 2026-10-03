/**
 * screener-studio — a screened row with no published price must not render
 * `₹undefined`, and the control that cannot act must be gated.
 *
 * The fabricated `buy_price: 0` was already refused at the top of
 * `handleAddToPortfolio` (`page.tsx:179-185`). Two things survived it:
 *
 *   1. The PRICE CELL rendered `₹{data.price?.toLocaleString('en-IN', …)}`.
 *      `ScreenerStock.price` is typed `number` (types/index.ts:1072) but the
 *      endpoint can omit it, so the optional chain returned `undefined`. React
 *      DROPS an `undefined` child rather than stringifying it, so the string on
 *      screen is not "₹undefined" — it is a bare `₹`: the cell publishes a
 *      currency with no amount, which reads as a price that exists. (Without
 *      the `?.` it threw instead.) Either way the absent price is stated as a
 *      present one.
 *   2. The Portfolio button was `disabled={isAdding || isAdded}` — not gated on
 *      the absent price, so the control invited an action that cannot succeed.
 *
 * The file's own absent-value convention for a numeric cell is `'-'`: the
 * market-cap (`formatCr`), P/E, ROCE, ROE and dividend-yield columns all render
 * it. The missing-price note is stated ON THE ROW, beside the dash, so the
 * refusal is reachable without a click — a `disabled` control cannot be
 * clicked, which would otherwise leave the reason unreachable in production.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import type { ScreenerStrategyResponse } from '@/types';

const mocks = vi.hoisted(() => ({
  runScreen: vi.fn(),
  getStrategies: vi.fn(),
  getPortfolio: vi.fn(),
  addPosition: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard/screener-studio',
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock('@/lib/api', () => ({
  screenerApi: {
    getStrategies: mocks.getStrategies,
    runScreen: mocks.runScreen,
    runCustomScreen: vi.fn().mockResolvedValue({ stocks: [] }),
  },
  portfolioApi: {
    getPortfolio: mocks.getPortfolio,
    addPosition: mocks.addPosition,
  },
  analyticsApi: { getMarginalTradeImpact: vi.fn().mockResolvedValue({}) },
  default: { get: vi.fn().mockResolvedValue({ data: {} }) },
}));

/** The row for one screened symbol, located by its own <tr>. */
const rowFor = (symbol: string) =>
  (screen.getByText(symbol).closest('tr') as HTMLTableRowElement);

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getStrategies.mockResolvedValue([]);
  mocks.getPortfolio.mockResolvedValue({ positions: [], total_value: 0 });
  mocks.addPosition.mockResolvedValue({ status: 'success' });
});

const screenWith = async (price: unknown) => {
  mocks.runScreen.mockResolvedValue({
    strategy: 'coffee_can',
    name: 'Coffee Can Portfolio',
    description: 'ROCE > 15%',
    count: 1,
    stocks: [
      {
        symbol: 'TCS',
        ticker: 'TCS.NS',
        name: 'Tata Consultancy Services',
        price,
        market_cap_cr: 1500000.0,
        pe_ratio: 28.5,
        roce_pct: 52.0,
        roe_pct: 48.0,
        dividend_yield_pct: 1.2,
      },
    ],
  } as unknown as ScreenerStrategyResponse);

  const { default: Page } = await import('@/app/dashboard/screener-studio/page');
  render(<Page />);
  await screen.findByText('TCS');
};

describe('screener-studio — an unpriced row states its absence and gates its control', () => {
  it('states the absent price as a dash, never a bare currency symbol', async () => {
    await screenWith(undefined);

    const row = rowFor('TCS');
    const priceCell = row.cells[2];
    // Before the fix the cell rendered exactly `₹`: React drops an `undefined`
    // child instead of stringifying it, so the reader saw a currency with no
    // amount attached and no hint that the price was never published.
    expect(priceCell.textContent).not.toContain('₹');
    expect(priceCell.textContent).not.toContain('undefined');
    // The file's own absent marker for a numeric cell, as the P/E and ROCE
    // columns beside it already use — with the reason beside it.
    expect(priceCell.textContent).toContain('-');
    expect(priceCell.textContent).toContain('No price published');
  });

  it('states the missing price on the row, so the refusal is reachable', async () => {
    await screenWith(undefined);

    const row = rowFor('TCS');
    // A disabled control cannot be clicked, so the reason cannot live behind a
    // click. It sits on the row instead.
    expect(row.textContent).toMatch(/no price published/i);
  });

  it('leaves the Portfolio control disabled for an unpriced row', async () => {
    await screenWith(undefined);

    const button = rowFor('TCS').querySelectorAll('button')[1] as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    // And activating it anyway still writes nothing.
    fireEvent.click(button);
    expect(mocks.addPosition).not.toHaveBeenCalled();
  });

  it('leaves a PRICED row enabled and posting its real buy price, unchanged', async () => {
    await screenWith(4100.0);

    const row = rowFor('TCS');
    expect(row.cells[2].textContent).toBe('₹4,100.00');
    expect(row.textContent).not.toMatch(/no price published/i);

    const button = rowFor('TCS').querySelectorAll('button')[1] as HTMLButtonElement;
    expect(button.disabled).toBe(false);

    fireEvent.click(button);
    await waitFor(() => {
      expect(mocks.addPosition).toHaveBeenCalledWith(
        expect.objectContaining({ ticker: 'TCS.NS', quantity: 1, buy_price: 4100.0 })
      );
    });
  });
});