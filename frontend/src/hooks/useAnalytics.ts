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
    const generateMockPerformanceData = () => {
      if (positions.length === 0) {
        setPerformanceData([]);
        setLoading(false);
        return;
      }

      // Generate mock performance data for the last N days
      const data = [];
      const startDate = new Date();
      startDate.setDate(startDate.getDate() - days);
      
      let portfolioValue = 100000; // Starting value
      const tickers = positions.map(p => p.ticker);
      
      for (let i = 0; i < days; i++) {
        const date = new Date(startDate);
        date.setDate(date.getDate() + i);
        
        // Mock daily returns with some volatility
        const dailyReturn = (Math.random() - 0.48) * 0.02; // Slight positive bias
        portfolioValue *= (1 + dailyReturn);
        
        data.push({
          date: date.toISOString().split('T')[0],
          portfolio_value: portfolioValue,
          return: dailyReturn,
        });
      }
      
      setPerformanceData(data);
      setLoading(false);
    };

    generateMockPerformanceData();
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

    // Calculate sector allocation from portfolio positions
    const sectorMap = new Map<string, number>();
    
    positions.forEach(position => {
      const sector = position.sector || 'Unknown';
      const currentWeight = sectorMap.get(sector) || 0;
      sectorMap.set(sector, currentWeight + position.weight);
    });

    // Convert to array format for charts
    const sectorArray = Array.from(sectorMap.entries()).map(([name, value]) => ({
      name,
      value,
      percentage: value, // Already normalized weights
    }));

    setSectorData(sectorArray);
  }, [positions]);

  return sectorData;
};