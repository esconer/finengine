import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { AddPositionModalSimple } from '@/components/portfolio/AddPositionModalSimple';

vi.mock('@/lib/api', () => ({
  portfolioApi: {
    getPortfolio: vi.fn(),
  },
}));

import { portfolioApi } from '@/lib/api';

describe('AddPositionModalSimple — zero-state weight invariant', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (portfolioApi.getPortfolio as ReturnType<typeof vi.fn>).mockResolvedValue({
      positions: [],
      total_value: 0,
    });
  });

  it('first position in an empty portfolio auto-sets weight to 100.00%', async () => {
    const onAdd = vi.fn().mockResolvedValue(undefined);
    render(
      <AddPositionModalSimple
        isOpen={true}
        onClose={vi.fn()}
        onAdd={onAdd}
        currency="INR"
      />
    );

    fireEvent.change(screen.getByPlaceholderText(/MOTHERSON\.NS/i), {
      target: { value: 'INFY.NS' },
    });
    fireEvent.change(screen.getByPlaceholderText('100'), {
      target: { value: '10' },
    });
    fireEvent.change(screen.getByPlaceholderText('100.00'), {
      target: { value: '1500' },
    });

    expect(await screen.findByDisplayValue('100.00%')).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: /Add Position/ }));
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onAdd.mock.calls[0][0].weight).toBe(1);
  });
});
