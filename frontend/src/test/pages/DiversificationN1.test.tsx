import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import DashboardSummary from '@/app/dashboard/page';

const mocks = vi.hoisted(() => ({
  positions: [] as any[],
  totalValue: 0,
}));

const updateLastUpdatedMock = vi.fn();
const fetchPortfolioMock = vi.fn().mockResolvedValue(undefined);

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// eslint-disable-next-line @next/next/no-html-link-for-pages
vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: mocks.positions,
    fetchPortfolio: fetchPortfolioMock,
    isLoading: false,
    error: null,
    totalValue: mocks.totalValue,
  }),
  useUIStore: () => ({ lastUpdated: null, updateLastUpdated: updateLastUpdatedMock }),
}));

vi.mock('@/hooks/useAnalytics', () => ({
  usePortfolioAnalytics: () => ({
    data: {
      summary: {
        realized_volatility: null,
        instrument_volatility: null,
        instrument_volatility_days: 252,
        sharpe_ratio: null,
        max_drawdown: 0,
      },
      riskScore: null,
      realizedRisk: null,
      forecastRisk: null,
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
  usePerformanceData: () => ({ performanceData: [], loading: false }),
  useSectorAllocation: () => [],
}));

vi.mock('@/lib/api', () => ({
  portfolioApi: { addPosition: vi.fn() },
  analyticsApi: {
    getRegime: vi.fn().mockRejectedValue(new Error('no regime')),
    getRiskContribution: vi.fn().mockRejectedValue(new Error('no risk')),
  },
}));

vi.mock('@/components/charts/PerformanceChart', () => ({
  PerformanceChart: () => <div data-testid="perf-chart-stub" />,
}));
vi.mock('@/components/charts/SectorAllocationChart', () => ({
  SectorAllocationChart: () => <div data-testid="sector-chart-stub" />,
}));
vi.mock('@/components/charts/RiskMetricsDisplay', () => ({
  RiskMetricsDisplay: () => <div data-testid="risk-metrics-stub" />,
}));

async function renderAndSettle() {
  render(<DashboardSummary />);
  await waitFor(() => {
    expect(screen.getAllByText('Diversification Score').length).toBeGreaterThan(0);
  });
}

describe('Diversification Score — N ≤ 1 renders 0%, never 100%', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('N = 0 (empty portfolio) → Diversification Score is 0.0%', async () => {
    mocks.positions = [];
    mocks.totalValue = 0;
    await renderAndSettle();
    expect(screen.getAllByText('Diversification Score').length).toBeGreaterThan(0);
    expect(screen.getAllByText('0.0%').length).toBeGreaterThan(0);
    expect(screen.queryByText('100.0%')).toBeNull();
  });

  it('N = 1 (single holding) → Diversification Score is 0.0%, never 100.0%', async () => {
    mocks.positions = [
      {
        id: 1,
        ticker: 'INFY.NS',
        weight: 1,
        quantity: 10,
        buy_price: 1500,
        last_price: 1500,
        market_value: 15000,
        sector: 'IT',
      },
    ];
    mocks.totalValue = 15000;
    await renderAndSettle();
    expect(screen.getAllByText('Diversification Score').length).toBeGreaterThan(0);
    expect(screen.getAllByText('0.0%').length).toBeGreaterThan(0);
    expect(screen.queryByText('100.0%')).toBeNull();
  });
});
