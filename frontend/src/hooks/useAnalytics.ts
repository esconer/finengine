/**
 * Analytics service hook for portfolio analytics
 */

import { useState, useEffect, useRef } from 'react';
import { analyticsApi } from '@/lib/api';
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
  const [performanceData, setPerformanceData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const { positions } = usePortfolioStore();
  const tickerKey = positions.map(p => `${p.ticker}:${p.quantity || 0}`).join(',');

  useEffect(() => {
    let isMounted = true;
    const fetchPerformanceData = async () => {
      if (positions.length === 0) {
        setPerformanceData([]);
        setLoading(false);
        return;
      }

      setLoading(true);
      try {
        const tickers = positions.map(p => p.ticker).join(',');
        const data = await analyticsApi.getPerformanceHistory({ days, tickers });
        if (isMounted) {
          setPerformanceData(Array.isArray(data) ? data : []);
        }
      } catch (err) {
        console.error('Failed to fetch performance history:', err);
        if (isMounted) {
          setPerformanceData([]);
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

  return { performanceData, loading };
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