import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import DashboardSummary from '@/app/dashboard/page';

/**
 * Ticket 02: dashboard freshness caption + honest risk-score delta.
 *
 * The page renders the real `usePerformanceData`/`usePortfolioAnalytics`
 * hooks against a mocked API, so both the response normalization and the
 * rendered disclosure are covered: a short/stale window must name the
 * delivered window, an unavailable window must never claim freshness, and the
 * risk score's hardcoded `change: 0` must render as N/A, never 0.00%.
 */

const updateLastUpdatedMock = vi.fn();
const fetchPortfolioMock = vi.fn().mockResolvedValue(undefined);

const positions = [
  {
    id: 1,
    ticker: 'STK.NS',
    weight: 1,
    quantity: 10,
    buy_price: 90,
    last_price: 100,
    market_value: 1000,
    sector: 'Bank',
  },
];

const rows = Array.from({ length: 20 }, (_, index) => ({
  date: `2026-09-${String(index + 1).padStart(2, '0')}`,
  portfolio_value: 1000 + index,
  return: 0.001,
}));

// 20 delivered observations for a 90-day request: the v3 artifact's window.
const truncatedEnvelope = {
  data: rows,
  data_status: 'partial',
  as_of: '2026-09-20',
  as_of_semantics: 'last_delivered_observation_date',
  history_coverage: {
    requested_start: '2026-06-27',
    requested_end: '2026-09-25',
    requested_days: 90,
    delivered_start: '2026-09-01',
    delivered_end: '2026-09-20',
    observation_count: 20,
    expected_observation_count: 62,
    first_observation: '2026-09-01',
    last_observation: '2026-09-20',
    coverage_ratio: 0.322581,
    truncated: true,
    stale: true,
    status: 'partial',
  },
  warnings: ['Price cache only covers part of the requested window'],
};

const completeEnvelope = {
  data: rows,
  data_status: 'available',
  as_of: '2026-09-20',
  as_of_semantics: 'last_delivered_observation_date',
  history_coverage: {
    requested_days: 90,
    delivered_start: '2026-09-01',
    delivered_end: '2026-09-20',
    observation_count: 20,
    expected_observation_count: 20,
    coverage_ratio: 1,
    truncated: false,
    stale: false,
    status: 'complete',
  },
  warnings: [],
};

const unavailableEnvelope = {
  data: [],
  data_status: 'unavailable',
  as_of: null,
  as_of_semantics: null,
  history_coverage: {
    requested_days: 90,
    observation_count: 0,
    expected_observation_count: 62,
    coverage_ratio: 0,
    truncated: true,
    stale: true,
    status: 'unavailable',
  },
  warnings: ['No usable price history in the requested window'],
};

const mocks = vi.hoisted(() => ({
  performanceResponse: null as unknown,
  riskScoreResponse: null as unknown,
  api: {
    getSummary: vi.fn(),
    getRealizedRisk: vi.fn(),
    getForecastRisk: vi.fn(),
    getFactorExposure: vi.fn(),
    getConcentrationMetrics: vi.fn(),
    getLiquidityMetrics: vi.fn(),
    getRiskScore: vi.fn(),
    getPerformanceHistory: vi.fn(),
    getRegime: vi.fn(),
    getRiskContribution: vi.fn(),
  },
}));

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
    positions,
    fetchPortfolio: fetchPortfolioMock,
    isLoading: false,
    error: null,
    totalValue: 1000,
  }),
  useUIStore: () => ({ lastUpdated: null, updateLastUpdated: updateLastUpdatedMock }),
}));

vi.mock('@/lib/api', () => ({
  portfolioApi: { addPosition: vi.fn() },
  analyticsApi: {
    getSummary: mocks.api.getSummary,
    getRealizedRisk: mocks.api.getRealizedRisk,
    getForecastRisk: mocks.api.getForecastRisk,
    getFactorExposure: mocks.api.getFactorExposure,
    getConcentrationMetrics: mocks.api.getConcentrationMetrics,
    getLiquidityMetrics: mocks.api.getLiquidityMetrics,
    getRiskScore: mocks.api.getRiskScore,
    getPerformanceHistory: mocks.api.getPerformanceHistory,
    getRegime: mocks.api.getRegime,
    getRiskContribution: mocks.api.getRiskContribution,
  },
}));

// Chart widgets are irrelevant here; the stub reports the row count so the
// normalization contract is still observable.
vi.mock('@/components/charts/PerformanceChart', () => ({
  PerformanceChart: ({ data }: { data?: unknown[] }) => (
    <div data-testid="perf-chart-stub">{`perf-chart-stub:${data?.length ?? 0}`}</div>
  ),
}));
vi.mock('@/components/charts/SectorAllocationChart', () => ({
  SectorAllocationChart: () => <div data-testid="sector-chart-stub" />,
}));
vi.mock('@/components/charts/RiskMetricsDisplay', () => ({
  RiskMetricsDisplay: () => <div data-testid="risk-metrics-stub" />,
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.performanceResponse = truncatedEnvelope;
  mocks.riskScoreResponse = { overall_score: 42, risk_level: 'Medium', change: 0 };
  mocks.api.getSummary.mockResolvedValue({
    realized_volatility: null,
    sharpe_ratio: null,
    max_drawdown: 0,
  });
  mocks.api.getRealizedRisk.mockResolvedValue({ portfolio: {} });
  mocks.api.getForecastRisk.mockResolvedValue({ portfolio: {} });
  mocks.api.getFactorExposure.mockResolvedValue({ portfolio: {} });
  mocks.api.getConcentrationMetrics.mockResolvedValue({ by_weight: { 'STK.NS': 1 } });
  mocks.api.getLiquidityMetrics.mockResolvedValue({ overall_score: 8 });
  mocks.api.getRiskScore.mockImplementation(async () => mocks.riskScoreResponse);
  mocks.api.getPerformanceHistory.mockImplementation(async () => mocks.performanceResponse);
  mocks.api.getRegime.mockRejectedValue(new Error('no regime'));
  mocks.api.getRiskContribution.mockRejectedValue(new Error('no risk'));
});

describe('DashboardSummary — performance freshness caption', () => {
  it('discloses a short, stale delivered window instead of a silent chart', async () => {
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByTestId('performance-freshness-caption')).toBeDefined();
    });
    const caption = screen.getByTestId('performance-freshness-caption').textContent ?? '';
    expect(caption).toContain('Partial performance window');
    // Requested vs delivered, and the delivered window itself.
    expect(caption).toContain('20 of 62 observations');
    expect(caption).toContain('2026-09-01 to 2026-09-20');
    expect(caption).toContain('requested 90d');
    expect(caption).toContain('stale');
    // The rows are still the chart's series.
    expect(screen.getByTestId('perf-chart-stub').textContent).toBe('perf-chart-stub:20');
    // The disclosure envelope is opt-in, not the legacy array.
    expect(mocks.api.getPerformanceHistory).toHaveBeenCalledWith(
      expect.objectContaining({ include_metadata: true, days: 90 }),
    );
  });

  it('normalizes the legacy bare array to the same chart without a freshness claim', async () => {
    mocks.performanceResponse = rows;
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByTestId('perf-chart-stub').textContent).toBe('perf-chart-stub:20');
    });
    // An unmeasured window is never labelled fresh or partial.
    expect(screen.queryByTestId('performance-freshness-caption')).toBeNull();
  });

  it('stays silent for a complete delivered window', async () => {
    mocks.performanceResponse = completeEnvelope;
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByTestId('perf-chart-stub').textContent).toBe('perf-chart-stub:20');
    });
    expect(screen.queryByTestId('performance-freshness-caption')).toBeNull();
  });

  it('never claims freshness when the window is unavailable', async () => {
    mocks.performanceResponse = unavailableEnvelope;
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByTestId('performance-freshness-caption')).toBeDefined();
    });
    const caption = screen.getByTestId('performance-freshness-caption').textContent ?? '';
    expect(caption).toContain('Performance window unavailable');
    expect(caption).not.toMatch(/fresh/i);
    expect(screen.getByTestId('perf-chart-stub').textContent).toBe('perf-chart-stub:0');
  });
});

describe('DashboardSummary — risk-score delta honesty', () => {
  it('renders an unmeasured hardcoded zero as N/A, never 0.00%', async () => {
    mocks.riskScoreResponse = { overall_score: 42, risk_level: 'Medium', change: 0 };
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByTestId('risk-score-delta-caption')).toBeDefined();
    });
    const caption = screen.getByTestId('risk-score-delta-caption').textContent ?? '';
    expect(caption).toContain('Risk-score change: N/A');
    expect(caption).toContain('no persisted prior score');
    expect(caption).not.toMatch(/\+\s?0\.00/);
    expect(caption).not.toMatch(/:\s?0(\.00)?\b/);
  });

  it('renders a genuine measured delta', async () => {
    mocks.riskScoreResponse = { overall_score: 42, risk_level: 'Medium', change: -3.5 };
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByTestId('risk-score-delta-caption')).toBeDefined();
    });
    expect(screen.getByTestId('risk-score-delta-caption').textContent).toContain('Risk-score change: -3.50');
  });

  it('keeps a measured zero when the route proves a prior score', async () => {
    mocks.riskScoreResponse = { overall_score: 42, risk_level: 'Medium', change: 0, prior_score: 42 };
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByTestId('risk-score-delta-caption')).toBeDefined();
    });
    const caption = screen.getByTestId('risk-score-delta-caption').textContent ?? '';
    expect(caption).toContain('Risk-score change: 0.00');
    expect(caption).not.toContain('N/A');
  });

  it('renders an explicitly nulled change as N/A', async () => {
    mocks.riskScoreResponse = {
      overall_score: 42,
      risk_level: 'Medium',
      change: null,
      change_status: 'unavailable',
      change_reason: 'no_persisted_prior_score',
    };
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByTestId('risk-score-delta-caption')).toBeDefined();
    });
    expect(screen.getByTestId('risk-score-delta-caption').textContent).toContain('Risk-score change: N/A');
  });

  it('adds no delta caption when the risk score itself is unavailable', async () => {
    mocks.riskScoreResponse = null;
    render(<DashboardSummary />);

    await waitFor(() => {
      expect(screen.getByTestId('perf-chart-stub')).toBeDefined();
    });
    expect(screen.queryByTestId('risk-score-delta-caption')).toBeNull();
  });
});
