import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import DashboardSummary from '@/app/dashboard/page';

const updateLastUpdatedMock = vi.fn();
const fetchPortfolioMock = vi.fn().mockResolvedValue(undefined);
const FIVE_MIN_AGO = new Date(Date.now() - 5 * 60 * 1000).toISOString();

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
    positions: [],
    fetchPortfolio: fetchPortfolioMock,
    isLoading: false,
    error: null,
    totalValue: 0,
  }),
  useUIStore: () => ({ lastUpdated: FIVE_MIN_AGO, updateLastUpdated: updateLastUpdatedMock }),
}));

vi.mock('@/hooks/useAnalytics', () => ({
  usePortfolioAnalytics: () => ({
    data: {
      // Holding window too young: gate nulled the annualized ratios.
      // Summary carries NO full-history vol field, so N/A is honest.
      summary: {
        realized_volatility: null,
        sharpe_ratio: null,
        max_drawdown: 0,
        last_updated: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
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

// Heavy chart widgets are irrelevant to the vol/timestamp contract.
vi.mock('@/components/charts/PerformanceChart', () => ({
  PerformanceChart: () => <div data-testid="perf-chart-stub" />,
}));
vi.mock('@/components/charts/SectorAllocationChart', () => ({
  SectorAllocationChart: () => <div data-testid="sector-chart-stub" />,
}));
vi.mock('@/components/charts/RiskMetricsDisplay', () => ({
  RiskMetricsDisplay: () => <div data-testid="risk-metrics-stub" />,
}));

describe('DashboardSummary — vol N/A caption + store timestamp', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps N/A vol with a model+window caption instead of fabricating a number', async () => {
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByText('Annual Volatility')).toBeDefined();
    });
    expect(screen.getByText('N/A')).toBeDefined();
    expect(screen.getByText(/Holding-window realized vol/)).toBeDefined();
    expect(screen.getByText(/30 trading days/)).toBeDefined();
  });

  it('reads "Last updated" from the shared store clock, not summary.last_updated', async () => {
    render(<DashboardSummary />);

    // Store clock (5 min ago) renders in Header-style relative form…
    await waitFor(() => {
      expect(screen.getByText(/Last updated: 5m ago/)).toBeDefined();
    });
    // …and stamps the store when fresh analytics arrive.
    await waitFor(() => {
      expect(updateLastUpdatedMock).toHaveBeenCalled();
    });
  });
});
