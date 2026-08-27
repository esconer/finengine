/**
 * Analytics service hook for portfolio analytics
 */

import { useState, useEffect } from 'react';
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

  const fetchAnalyticsData = async () => {
    setLoading(true);
    setError(null);

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

      const results = [summary, realizedRisk, forecastRisk, factorExposure, concentration, liquidity, riskScore];
      const rejectedCount = results.filter(r => r.status === 'rejected').length;

      if (rejectedCount === results.length) {
        setError('Failed to fetch analytics data');
      } else if (rejectedCount > 0) {
        console.warn(`Partial analytics failure: ${rejectedCount} metrics endpoints were unreachable.`);
      }

      setData({
        summary: summary.status === 'fulfilled' ? summary.value : null,
        realizedRisk: realizedRisk.status === 'fulfilled' ? realizedRisk.value : null,
        forecastRisk: forecastRisk.status === 'fulfilled' ? forecastRisk.value : null,
        factorExposure: factorExposure.status === 'fulfilled' ? factorExposure.value : null,
        concentration: concentration.status === 'fulfilled' ? concentration.value : null,
        liquidity: liquidity.status === 'fulfilled' ? liquidity.value : null,
        riskScore: riskScore.status === 'fulfilled' ? riskScore.value : null,
      });

    } catch (err: any) {
      setError(err.message || 'Failed to fetch analytics data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (positions.length > 0) {
      fetchAnalyticsData();
    } else {
      setLoading(false);
    }
  }, [positions]);

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
  }, [positions, days]);

  return { performanceData, loading };
};

export const useSectorAllocation = () => {
  const [sectorData, setSectorData] = useState<any[]>([]);
  const { positions } = usePortfolioStore();

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
  }, [positions]);

  return sectorData;
};