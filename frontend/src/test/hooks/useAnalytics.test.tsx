import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { usePortfolioAnalytics } from '@/hooks/useAnalytics';

const mocks = vi.hoisted(() => ({
  positions: [
    { ticker: 'A.NS', weight: 0.6, last_price: 100 },
    { ticker: 'B.NS', weight: 0.4, last_price: 50 },
  ] as any[],
  api: {
    getSummary: vi.fn(),
    getRealizedRisk: vi.fn(),
    getForecastRisk: vi.fn(),
    getFactorExposure: vi.fn(),
    getConcentrationMetrics: vi.fn(),
    getLiquidityMetrics: vi.fn(),
    getRiskScore: vi.fn(),
  },
}));

vi.mock('@/lib/api', () => ({ analyticsApi: mocks.api }));
vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({ positions: mocks.positions }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

beforeEach(() => {
  Object.values(mocks.api).forEach((mock) => mock.mockReset());
  mocks.api.getSummary.mockResolvedValue({ total_positions: 2 });
  mocks.api.getRealizedRisk.mockResolvedValue({ positions: {} });
  mocks.api.getForecastRisk.mockResolvedValue({ positions: {} });
  mocks.api.getFactorExposure.mockResolvedValue({ positions: {} });
  mocks.api.getConcentrationMetrics.mockResolvedValue({ by_weight: { 'A.NS': 0.6 } });
  mocks.api.getLiquidityMetrics.mockResolvedValue({ by_position: {} });
  mocks.api.getRiskScore.mockResolvedValue({ overall_score: 25 });
});

describe('usePortfolioAnalytics request lifecycle', () => {
  it('coalesces repeated refreshes for the same in-flight portfolio snapshot', async () => {
    const requests = {
      summary: deferred<unknown>(),
      realizedRisk: deferred<unknown>(),
      forecastRisk: deferred<unknown>(),
      factorExposure: deferred<unknown>(),
      concentration: deferred<unknown>(),
      liquidity: deferred<unknown>(),
      riskScore: deferred<unknown>(),
    };

    mocks.api.getSummary.mockImplementation(() => requests.summary.promise);
    mocks.api.getRealizedRisk.mockImplementation(() => requests.realizedRisk.promise);
    mocks.api.getForecastRisk.mockImplementation(() => requests.forecastRisk.promise);
    mocks.api.getFactorExposure.mockImplementation(() => requests.factorExposure.promise);
    mocks.api.getConcentrationMetrics.mockImplementation(() => requests.concentration.promise);
    mocks.api.getLiquidityMetrics.mockImplementation(() => requests.liquidity.promise);
    mocks.api.getRiskScore.mockImplementation(() => requests.riskScore.promise);

    const { result } = renderHook(() => usePortfolioAnalytics());

    await waitFor(() => expect(mocks.api.getSummary).toHaveBeenCalledTimes(1));

    act(() => {
      void result.current.refresh();
      void result.current.refresh();
    });

    const callsWhilePending = {
      summary: mocks.api.getSummary.mock.calls.length,
      realizedRisk: mocks.api.getRealizedRisk.mock.calls.length,
      forecastRisk: mocks.api.getForecastRisk.mock.calls.length,
      factorExposure: mocks.api.getFactorExposure.mock.calls.length,
      concentration: mocks.api.getConcentrationMetrics.mock.calls.length,
      liquidity: mocks.api.getLiquidityMetrics.mock.calls.length,
      riskScore: mocks.api.getRiskScore.mock.calls.length,
    };

    await act(async () => {
      requests.summary.resolve({ total_positions: 2 });
      requests.realizedRisk.resolve({ positions: {} });
      requests.forecastRisk.resolve({ positions: {} });
      requests.factorExposure.resolve({ positions: {} });
      requests.concentration.resolve({ by_weight: { 'A.NS': 0.6 } });
      requests.liquidity.resolve({ by_position: {} });
      requests.riskScore.resolve({ overall_score: 25 });
    });

    expect(callsWhilePending).toEqual({
      summary: 1,
      realizedRisk: 1,
      forecastRisk: 1,
      factorExposure: 1,
      concentration: 1,
      liquidity: 1,
      riskScore: 1,
    });
  });

  it('marks zero_metrics HTTP-200 responses unavailable without discarding valid siblings', async () => {
    mocks.api.getConcentrationMetrics.mockResolvedValue({
      largest_position: 0,
      error: 'No portfolio positions found',
      zero_metrics: true,
    });
    mocks.api.getLiquidityMetrics.mockResolvedValue({
      overall_score: 5,
      error: 'No portfolio positions found',
      zero_metrics: true,
    });

    const { result } = renderHook(() => usePortfolioAnalytics());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data.concentration).toBeNull();
    expect(result.current.data.liquidity).toBeNull();
    expect(result.current.data.summary).toEqual({ total_positions: 2 });
    expect(result.current.data.riskScore).toEqual({ overall_score: 25 });
  });
});
