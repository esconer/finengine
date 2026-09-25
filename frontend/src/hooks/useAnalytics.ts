/**
 * Analytics service hook for portfolio analytics
 */

import { useState, useEffect, useRef } from 'react';
import { analyticsApi } from '@/lib/api';
import type { PerformanceHistoryEnvelope, PerformanceHistoryRow } from '@/lib/api';
import { usePortfolioStore } from '@/lib/store';

interface AnalyticsData {
  summary: any;
  realizedRisk: any;
  forecastRisk: any;
  factorExposure: any;
  concentration: any;
  liquidity: any;
  riskScore: any;
}

const isZeroMetricsPayload = (value: unknown): boolean => {
  return value !== null
    && typeof value === 'object'
    && (value as { zero_metrics?: unknown }).zero_metrics === true;
};

const fulfilledValueOrNull = (result: PromiseSettledResult<any>): any => {
  return result.status === 'fulfilled' && !isZeroMetricsPayload(result.value)
    ? result.value
    : null;
};

/**
 * Freshness of one performance window, as disclosed by the endpoint.
 *
 * `status` is the endpoint's own data status, narrowed by the delivered
 * coverage: a delivery below the coverage floor, or a stale/truncated window,
 * is `partial`. `unknown` is a valid answer — the legacy bare-array response
 * carries no measured expectation, so its window is never called complete.
 */
export interface PerformanceFreshness {
  status: 'available' | 'partial' | 'unavailable' | 'unknown';
  asOf: string | null;
  asOfSemantics: string | null;
  requestedDays: number | null;
  deliveredStart: string | null;
  deliveredEnd: string | null;
  observationCount: number;
  expectedObservationCount: number | null;
  coverageRatio: number | null;
  truncated: boolean | null;
  stale: boolean | null;
  warnings: string[];
}

// A delivered window shorter than this share of the endpoint's own expected
// observation count is disclosed as partial rather than presented as complete.
const PERFORMANCE_COVERAGE_FLOOR = 0.8;

const finiteNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const optionalNumber = (value: unknown): number | null => {
  const parsed = finiteNumber(value);
  return parsed === null ? null : parsed;
};

const optionalText = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value.trim() : null;

/**
 * Normalize both performance-history wire shapes to one chart array plus the
 * delivered-window evidence, so no consumer has to know which shape arrived.
 * The legacy array still yields chart rows; it simply yields no freshness claim.
 */
export const normalizePerformanceHistory = (
  payload: unknown,
  requestedDays: number,
): { rows: PerformanceHistoryRow[]; freshness: PerformanceFreshness | null } => {
  if (Array.isArray(payload)) {
    return { rows: payload as PerformanceHistoryRow[], freshness: null };
  }
  if (!payload || typeof payload !== 'object') {
    return { rows: [], freshness: null };
  }

  const envelope = payload as PerformanceHistoryEnvelope;
  const rows = Array.isArray(envelope.data) ? envelope.data : [];
  const coverage = envelope.history_coverage ?? {};
  const observationCount = optionalNumber(coverage.observation_count) ?? rows.length;
  const expected = optionalNumber(coverage.expected_observation_count);
  const ratio = optionalNumber(coverage.coverage_ratio)
    ?? (expected && expected > 0 ? observationCount / expected : null);
  const truncated = typeof coverage.truncated === 'boolean' ? coverage.truncated : null;
  const stale = typeof coverage.stale === 'boolean' ? coverage.stale : null;
  const declared = envelope.data_status;
  const deliveredStart = optionalText(coverage.delivered_start);
  const deliveredEnd = optionalText(coverage.delivered_end);

  let status: PerformanceFreshness['status'];
  if (declared === 'unavailable' || observationCount === 0) {
    status = 'unavailable';
  } else if (declared === 'partial') {
    status = 'partial';
  } else if (expected === null) {
    // No measured expectation: unmeasured, never assumed complete.
    status = 'unknown';
  } else if ((ratio !== null && ratio < PERFORMANCE_COVERAGE_FLOOR) || truncated === true || stale === true) {
    status = 'partial';
  } else {
    status = 'available';
  }

  return {
    rows,
    freshness: {
      status,
      asOf: optionalText(envelope.as_of) ?? deliveredEnd,
      asOfSemantics: optionalText(envelope.as_of_semantics),
      requestedDays: optionalNumber(coverage.requested_days) ?? requestedDays,
      deliveredStart,
      deliveredEnd,
      observationCount,
      expectedObservationCount: expected,
      coverageRatio: ratio,
      truncated,
      stale,
      warnings: Array.isArray(envelope.warnings)
        ? envelope.warnings.filter((item): item is string => typeof item === 'string')
        : [],
    },
  };
};

export const usePortfolioAnalytics = () => {
  const [data, setData] = useState<AnalyticsData>({
    summary: null,
    realizedRisk: null,
    forecastRisk: null,
    factorExposure: null,
    concentration: null,
    liquidity: null,
    riskScore: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { positions } = usePortfolioStore();
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);
  const inFlightRef = useRef<{ key: string; requestId: number; promise: Promise<void> } | null>(null);
  const tickerKey = positions.map(p => `${p.ticker}:${p.weight}:${p.last_price}`).join(',');

  const fetchAnalyticsData = async () => {
    if (inFlightRef.current?.key === tickerKey && inFlightRef.current.requestId === requestIdRef.current) {
      return inFlightRef.current.promise;
    }

    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);

    const request = (async () => {
      try {
        // Get tickers from current portfolio
        const tickers = positions.map(p => p.ticker).join(',');

        // Fetch all analytics data in parallel
        const [
          summary,
          realizedRisk,
          forecastRisk,
          factorExposure,
          concentration,
          liquidity,
          riskScore,
        ] = await Promise.allSettled([
          analyticsApi.getSummary(),
          analyticsApi.getRealizedRisk({ tickers }),
          analyticsApi.getForecastRisk({ tickers }),
          analyticsApi.getFactorExposure({ tickers }),
          analyticsApi.getConcentrationMetrics(),
          analyticsApi.getLiquidityMetrics(),
          analyticsApi.getRiskScore(),
        ]);

        // Discard stale responses — a newer portfolio snapshot superseded this one (B11)
        if (!mountedRef.current || requestId !== requestIdRef.current) return;

        const results = [summary, realizedRisk, forecastRisk, factorExposure, concentration, liquidity, riskScore];
        const rejectedCount = results.filter(r => r.status === 'rejected').length;

        if (rejectedCount === results.length) {
          setError('Failed to fetch analytics data');
        } else if (rejectedCount > 0) {
          console.warn(`Partial analytics failure: ${rejectedCount} metrics endpoints were unreachable.`);
        }

        setData({
          summary: fulfilledValueOrNull(summary),
          realizedRisk: fulfilledValueOrNull(realizedRisk),
          forecastRisk: fulfilledValueOrNull(forecastRisk),
          factorExposure: fulfilledValueOrNull(factorExposure),
          concentration: fulfilledValueOrNull(concentration),
          liquidity: fulfilledValueOrNull(liquidity),
          riskScore: fulfilledValueOrNull(riskScore),
        });

      } catch (err: any) {
        if (!mountedRef.current || requestId !== requestIdRef.current) return;
        setError(err.message || 'Failed to fetch analytics data');
      } finally {
        if (mountedRef.current && requestId === requestIdRef.current) {
          setLoading(false);
        }
      }
    })();

    inFlightRef.current = { key: tickerKey, requestId, promise: request };
    try {
      await request;
    } finally {
      if (inFlightRef.current?.promise === request) {
        inFlightRef.current = null;
      }
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    if (positions.length > 0) {
      void fetchAnalyticsData();
    } else {
      requestIdRef.current++;
      setData({
        summary: null,
        realizedRisk: null,
        forecastRisk: null,
        factorExposure: null,
        concentration: null,
        liquidity: null,
        riskScore: null,
      });
      setError(null);
      setLoading(false);
    }

    return () => {
      mountedRef.current = false;
    };
  }, [tickerKey]);

  return {
    data,
    loading,
    error,
    refresh: fetchAnalyticsData,
  };
};

export const usePerformanceData = (days: number = 90) => {
  const [performanceData, setPerformanceData] = useState<PerformanceHistoryRow[]>([]);
  const [freshness, setFreshness] = useState<PerformanceFreshness | null>(null);
  const [loading, setLoading] = useState(true);
  const { positions } = usePortfolioStore();
  const tickerKey = positions.map(p => `${p.ticker}:${p.quantity || 0}`).join(',');

  useEffect(() => {
    let isMounted = true;
    const fetchPerformanceData = async () => {
      if (positions.length === 0) {
        setPerformanceData([]);
        setFreshness(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      try {
        const tickers = positions.map(p => p.ticker).join(',');
        // Opt into the disclosure envelope: the chart must be able to say how
        // much of the requested window it actually received.
        const payload = await analyticsApi.getPerformanceHistory({
          days,
          tickers,
          include_metadata: true,
        });
        if (isMounted) {
          const normalized = normalizePerformanceHistory(payload, days);
          setPerformanceData(normalized.rows);
          setFreshness(normalized.freshness);
        }
      } catch (err) {
        console.error('Failed to fetch performance history:', err);
        if (isMounted) {
          setPerformanceData([]);
          setFreshness(null);
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    fetchPerformanceData();
    return () => {
      isMounted = false;
    };
  }, [tickerKey, days]);

  return { performanceData, loading, freshness };
};

export const useSectorAllocation = () => {
  const [sectorData, setSectorData] = useState<any[]>([]);
  const { positions } = usePortfolioStore();
  const tickerKey = positions.map(p => `${p.ticker}:${p.sector || ''}:${p.market_value || 0}`).join(',');

  useEffect(() => {
    if (positions.length === 0) {
      setSectorData([]);
      return;
    }

    // Calculate sector allocation from live portfolio market values
    const totalMv = positions.reduce((sum, p) => sum + (p.market_value || 0), 0);
    const sectorMap = new Map<string, number>();
    
    positions.forEach(position => {
      const sector = position.sector || 'Unknown';
      const mv = position.market_value || 0;
      const currentShare = sectorMap.get(sector) || 0;
      const weight = totalMv > 0 ? (mv / totalMv) : (position.weight || 0);
      sectorMap.set(sector, currentShare + weight);
    });

    // Convert to array format for charts
    const sectorArray = Array.from(sectorMap.entries()).map(([name, value]) => ({
      name,
      value,
      percentage: value, // Normalized live market-value weights
    }));

    setSectorData(sectorArray);
  }, [tickerKey]);

  return sectorData;
};