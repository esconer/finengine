import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PortfolioStats } from '@/components/portfolio/PortfolioStats';
import type { PortfolioPosition } from '@/types';

const position = {
  id: 1,
  ticker: 'AAPL',
  weight: 1,
  quantity: 1,
  buy_price: 90,
  region: 'US',
  primary_source: 'test',
  last_validated_source: 'test',
  last_price: 100,
  market_value: 100,
  sector: 'Technology',
  industry: 'Software',
  added_on: '2025-01-01',
  updated_on: '2025-01-01',
  total_cost: 90,
  unrealized_gain_loss: 10,
  unrealized_gain_loss_pct: 11.111,
  current_value: 100,
  native_currency: 'USD',
  value_currency: 'USD',
  buy_price_base: 90,
  last_price_base: 100,
  market_value_base: 80,
  current_value_base: 80,
  total_cost_base: 72,
  unrealized_gain_loss_base: 8,
  unrealized_gain_loss_pct_base: 11.111,
} as PortfolioPosition;

describe('PortfolioStats monetary-unit contract', () => {
  it('renders base-currency values for a USD view', () => {
    render(<PortfolioStats positions={[position]} currency="USD" />);

    expect(screen.getByText('$80.00')).toBeDefined();
    expect(screen.getByText('$72.00')).toBeDefined();
    expect(screen.getAllByText('+11.11%').length).toBeGreaterThan(0);
    expect(screen.queryByText('$100.00')).toBeNull();
    expect(screen.queryByText('$90.00')).toBeNull();
  });
});
