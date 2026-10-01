import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { usePortfolioAnalytics, useSectorAllocation } from '@/hooks/useAnalytics';

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

// ===========================================================================
// useSectorAllocation — an unpriced holding is not a zero-value holding.
//
// `p.market_value || 0` inside the reduce, then `mv = position.market_value || 0`
// inside the loop. Both collapse "no market value recorded" onto "market value
// is zero", so an unpriced holding contributed a real 0 to the total and a real
// 0 share to its sector. The sector's percentage was then understated — the
// weights still summed to 100%, but one of them was fabricated — and the
// published slice read as a confident 0.0%.
// ===========================================================================
describe('useSectorAllocation — a holding with no market value publishes no share', () => {
  const byName = (rows: { name: string; value: number }[]) =>
    Object.fromEntries(rows.map((r) => [r.name, r.value]));

  beforeEach(() => {
    mocks.positions = [
      { ticker: 'A.NS', sector: 'Tech', market_value: 600, weight: 0.6 },
      { ticker: 'B.NS', sector: 'Tech', market_value: 400, weight: 0.4 },
      // Unpriced: the engine recorded a holding but never a value for it.
      { ticker: 'C.NS', sector: 'Energy', market_value: null, weight: 0.5 },
    ];
  });

  it('refuses to publish a share for the unpriced holding, and keeps the rest honest', () => {
    const { result } = renderHook(() => useSectorAllocation());

    const shares = byName(result.current);
    // The denominator is the MEASURED book (1000), not 1000-plus-a-fabricated-0
    // that happened to be the same number here. Tech keeps its true 100% of the
    // measured book rather than being dragged down to 50% by a phantom value.
    expect(shares['Tech']).toBeCloseTo(1, 10);
    // Energy had no measured market value, so there is no share to publish.
    // Publishing 0 would be a claim that Energy is worth nothing.
    expect(shares['Energy']).toBeUndefined();
    // The other sectors' published percentages are unchanged.
    expect(result.current.find((r) => r.name === 'Tech')?.percentage).toBeCloseTo(1, 10);
  });

  it('still publishes a real 0% for a holding MEASURED at zero', () => {
    // The other half of the rule: a market_value of 0 is a measurement. A fix
    // written as `if (!mv) skip` would silently drop this holding instead.
    mocks.positions = [
      { ticker: 'A.NS', sector: 'Tech', market_value: 1000, weight: 1 },
      { ticker: 'B.NS', sector: 'Energy', market_value: 0, weight: 0 },
    ];

    const { result } = renderHook(() => useSectorAllocation());

    const shares = byName(result.current);
    expect(shares['Tech']).toBeCloseTo(1, 10);
    expect(shares['Energy']).toBeCloseTo(0, 10);
    expect(result.current.find((r) => r.name === 'Energy')).toBeDefined();
  });

  it('returns nothing at all rather than a full 100% for a wholly unpriced book', () => {
    // Every holding unmeasured means there is no denominator. Publishing a
    // sector at 100% here would be the worst version of the bug.
    mocks.positions = [
      { ticker: 'A.NS', sector: 'Tech', market_value: null },
      { ticker: 'B.NS', sector: 'Energy', market_value: undefined },
    ];

    const { result } = renderHook(() => useSectorAllocation());

    expect(result.current).toEqual([]);
  });
});
