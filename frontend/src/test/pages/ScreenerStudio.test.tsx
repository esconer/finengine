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
