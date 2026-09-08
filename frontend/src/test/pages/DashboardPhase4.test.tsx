import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import DashboardSummary from '@/app/dashboard/page';

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

// Ten equal positions across 4 sectors: HHI = 0.1, N_eff = 10 → score 100.
const positions = Array.from({ length: 10 }, (_, i) => ({
  id: i + 1,
  ticker: `STK${i}.NS`,
  weight: 0.1,
  quantity: 10,
  buy_price: 90,
  last_price: 100,
  market_value: 1000,
  sector: ['Bank', 'IT', 'Energy', 'Pharma'][i % 4],
}));

const sectors = [
  { name: 'Bank', value: 3000 },
  { name: 'IT', value: 3000 },
  { name: 'Energy', value: 2000 },
  { name: 'Pharma', value: 2000 },
];

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions,
    fetchPortfolio: fetchPortfolioMock,
    isLoading: false,
    error: null,
    totalValue: 10000,
  }),
  useUIStore: () => ({ lastUpdated: null, updateLastUpdated: updateLastUpdatedMock }),
}));

vi.mock('@/hooks/useAnalytics', () => ({
  usePortfolioAnalytics: () => ({
    data: {
      // Staggered book: holding-window vol gates, instrument vol stays live.
      summary: {
        realized_volatility: null,
        instrument_volatility: 0.185,
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
  useSectorAllocation: () => sectors,
}));

vi.mock('@/lib/api', () => ({
  portfolioApi: { addPosition: vi.fn() },
  analyticsApi: {
    getRegime: vi.fn().mockRejectedValue(new Error('no regime')),
    getRiskContribution: vi.fn().mockRejectedValue(new Error('no risk')),
  },
}));

// Heavy chart widgets are irrelevant to the vol/diversification contract.
vi.mock('@/components/charts/PerformanceChart', () => ({
  PerformanceChart: () => <div data-testid="perf-chart-stub" />,
}));
vi.mock('@/components/charts/SectorAllocationChart', () => ({
  SectorAllocationChart: () => <div data-testid="sector-chart-stub" />,
}));
vi.mock('@/components/charts/RiskMetricsDisplay', () => ({
  RiskMetricsDisplay: () => <div data-testid="risk-metrics-stub" />,
}));

describe('DashboardSummary — Phase 4 instrument vol + diversification decimals', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('Ann Vol card shows full-history asset vol with caption, never N/A-gated', async () => {
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByText('Annual Volatility')).toBeDefined();
    });
    expect(screen.getByText('18.50%')).toBeDefined();
    const caption = screen.getByTestId('vol-caption');
    expect(caption.textContent).toMatch(/full-history asset vol/);
    expect(screen.queryByText('N/A')).toBeNull();
  });

  it('diversification renders 1 decimal, never a bare "100%"', async () => {
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByText('Annual Volatility')).toBeDefined();
    });
    // Perfect-10 book: score is exactly 100 → must render "100.0%".
    expect(screen.getAllByText('100.0%').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Diversification Score').length).toBeGreaterThan(0);
  });
});
