/**
 * Realized Risk Page - Historical risk metrics and performance analysis
 */

'use client';

import React, { useState, useEffect } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import { RiskMetricsDisplay } from '@/components/charts/RiskMetricsDisplay';
import { usePortfolioAnalytics } from '@/hooks/useAnalytics';
import { usePortfolioStore } from '@/lib/store';
import {
  TrendingDown,
  TrendingUp,
  Activity,
  AlertTriangle,
  Calendar,
  BarChart3,
  Download,
  RefreshCw
} from 'lucide-react';

interface RiskMetrics {
  annual_return: number;
  annual_volatility: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  skewness: number;
  kurtosis: number;
  max_drawdown: number;
  var_95: number;
  cvar_95: number;
  hit_ratio: number;
}

interface PositionRisk {
  annual_return: number;
  annual_volatility: number;
  sharpe_ratio: number;
  max_drawdown: number;
  var_95: number;
  weight: number;
}

export default function RealizedRiskPage() {
  const [dateRange, setDateRange] = useState({
    start: '',
    end: '',
  });
  const [loading, setLoading] = useState(false);
  const [positionData, setPositionData] = useState<any[]>([]);

  const { data: analyticsData, loading: analyticsLoading, refresh } = usePortfolioAnalytics();
  const { positions } = usePortfolioStore();

  const realizedRisk = analyticsData.realizedRisk;

  // Generate position risk data for table
  useEffect(() => {
    if (realizedRisk?.positions) {
      const positionsList = Object.entries(realizedRisk.positions).map(([ticker, data]: [string, any]) => ({
        ticker,
        ...data
      }));
      setPositionData(positionsList);
    }
  }, [realizedRisk]);

  // Default date range to last year
  useEffect(() => {
    const end = new Date();
    const start = new Date();
    start.setFullYear(start.getFullYear() - 1);

    setDateRange({
      start: start.toISOString().split('T')[0],
      end: end.toISOString().split('T')[0],
    });
  }, []);

  const handleDateRangeChange = (field: string, value: string) => {
    setDateRange(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleRefresh = async () => {
    setLoading(true);
    await refresh();
    setLoading(false);
  };

  // Format metrics for display
  const formatPercentage = (value: number, decimals = 2) => {
    return `${(value * 100).toFixed(decimals)}%`;
  };

  const formatRatio = (value: number | undefined | null, decimals = 2) => {
    return (value || 0).toFixed(decimals);
  };

  // DataTable columns
  const positionColumns = [
    {
      header: 'Ticker',
      accessorKey: 'ticker',
      cell: ({ row }: any) => (
        <div className="font-medium text-gray-900 dark:text-white">
          {row.ticker}
        </div>
      ),
    },
    {
      header: 'Weight',
      accessorKey: 'weight',
      cell: ({ row }: any) => (
        <div className="text-gray-900 dark:text-white">
          {formatPercentage(row.weight)}
        </div>
      ),
    },
    {
      header: 'Annual Return',
      accessorKey: 'annual_return',
      cell: ({ row }: any) => (
        <div className={`${row.annual_return >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
          }`}>
          {formatPercentage(row.annual_return)}
        </div>
      ),
    },
    {
      header: 'Volatility',
      accessorKey: 'annual_volatility',
      cell: ({ row }: any) => (
        <div className="text-gray-900 dark:text-white">
          {formatPercentage(row.annual_volatility)}
        </div>
      ),
    },
    {
      header: 'Sharpe Ratio',
      accessorKey: 'sharpe_ratio',
      cell: ({ row }: any) => (
        <div className={`${row.sharpe_ratio >= 1 ? 'text-green-600 dark:text-green-400' :
            row.sharpe_ratio >= 0 ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-600 dark:text-red-400'
          }`}>
          {formatRatio(row.sharpe_ratio)}
        </div>
      ),
    },
    {
      header: 'Max Drawdown',
      accessorKey: 'max_drawdown',
      cell: ({ row }: any) => (
        <div className="text-red-600 dark:text-red-400">
          {formatPercentage(row.max_drawdown)}
        </div>
      ),
    },
    {
      header: 'VaR (95%)',
      accessorKey: 'var_95',
      cell: ({ row }: any) => (
        <div className="text-red-600 dark:text-red-400">
          {formatPercentage(row.var_95)}
        </div>
      ),
    },
  ];

  if (realizedRisk?.positions) {
    return (
      <div className="space-y-6">
        {/* Hero Section */}
        <div className="bg-gradient-to-r from-red-600 to-orange-600 rounded-lg p-6 text-white">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold mb-2">Realized Risk</h1>
              <p className="text-red-100">
                Historical risk metrics and portfolio performance analysis
              </p>
              <div className="flex items-center mt-2 space-x-4">
                <div className="text-red-200 text-sm">
                  Period: {dateRange.start} to {dateRange.end}
                </div>
                {realizedRisk.data_range && (
                  <div className="text-red-200 text-sm">
                    Analysis Period: {realizedRisk.data_range.start} to {realizedRisk.data_range.end}
                  </div>
                )}
              </div>
            </div>
            <div className="hidden md:flex items-center space-x-2">
              <button
                onClick={handleRefresh}
                disabled={loading || analyticsLoading}
                className="bg-white/20 hover:bg-white/30 rounded-lg p-2 transition-colors"
              >
                <RefreshCw className={`w-5 h-5 ${loading || analyticsLoading ? 'animate-spin' : ''}`} />
              </button>
              <TrendingDown className="w-16 h-16 text-red-200" />
            </div>
          </div>
        </div>

        {/* Risk Metrics */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <MetricCard
            title="Annual Return"
            value={realizedRisk?.portfolio?.annual_return ? formatPercentage(realizedRisk.portfolio.annual_return) : 'N/A'}
            change={realizedRisk?.portfolio?.annual_return ? 2.1 : 0}
            changeType={realizedRisk?.portfolio?.annual_return >= 0 ? "positive" : "negative"}
            icon={TrendingUp}
            loading={analyticsLoading}
          />
          <MetricCard
            title="Annual Volatility"
            value={realizedRisk?.portfolio?.annual_volatility ? formatPercentage(realizedRisk.portfolio.annual_volatility) : 'N/A'}
            change={realizedRisk?.portfolio?.annual_volatility ? -0.8 : 0}
            changeType="neutral"
            icon={Activity}
            loading={analyticsLoading}
          />
          <MetricCard
            title="Sharpe Ratio"
            value={realizedRisk?.portfolio?.sharpe_ratio ? formatRatio(realizedRisk.portfolio.sharpe_ratio) : 'N/A'}
            change={realizedRisk?.portfolio?.sharpe_ratio ? 0.12 : 0}
            changeType={realizedRisk?.portfolio?.sharpe_ratio >= 1 ? "positive" : "negative"}
            icon={TrendingUp}
            loading={analyticsLoading}
          />
          <MetricCard
            title="Max Drawdown"
            value={realizedRisk?.portfolio?.max_drawdown ? formatPercentage(realizedRisk.portfolio.max_drawdown) : 'N/A'}
            change={realizedRisk?.portfolio?.max_drawdown ? 1.3 : 0}
            changeType="negative"
            icon={TrendingDown}
            loading={analyticsLoading}
          />
        </div>

        {/* Risk Metrics Display */}
        <RiskMetricsDisplay
          data={{
            risk_score: 0, // Will be calculated from other metrics
            risk_level: 'Unknown',
            annual_volatility: realizedRisk?.portfolio?.annual_volatility || 0,
            sharpe_ratio: realizedRisk?.portfolio?.sharpe_ratio || 0,
            max_drawdown: realizedRisk?.portfolio?.max_drawdown || 0,
            var_95: realizedRisk?.portfolio?.var_95 || 0,
            cvar_95: realizedRisk?.portfolio?.cvar_95 || 0,
          }}
          loading={analyticsLoading}
        />

        {/* Extended Metrics */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <MetricCard
            title="Sortino Ratio"
            value={realizedRisk?.portfolio?.sortino_ratio ? formatRatio(realizedRisk.portfolio.sortino_ratio) : 'N/A'}
            change={0}
            changeType="neutral"
            icon={BarChart3}
            loading={analyticsLoading}
          />
          <MetricCard
            title="VaR (95%)"
            value={realizedRisk?.portfolio?.var_95 ? formatPercentage(realizedRisk.portfolio.var_95) : 'N/A'}
            change={0}
            changeType="negative"
            icon={AlertTriangle}
            loading={analyticsLoading}
          />
          <MetricCard
            title="CVaR (95%)"
            value={realizedRisk?.portfolio?.cvar_95 ? formatPercentage(realizedRisk.portfolio.cvar_95) : 'N/A'}
            change={0}
            changeType="negative"
            icon={AlertTriangle}
            loading={analyticsLoading}
          />
          <MetricCard
            title="Hit Ratio"
            value={realizedRisk?.portfolio?.hit_ratio ? formatPercentage(realizedRisk.portfolio.hit_ratio) : 'N/A'}
            change={0}
            changeType="neutral"
            icon={Activity}
            loading={analyticsLoading}
          />
        </div>

        {/* Charts Section */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Risk Metrics Over Time
              </h3>
              <Calendar className="w-5 h-5 text-gray-500" />
            </div>
            <div className="h-64 bg-gray-100 dark:bg-gray-700 rounded-lg flex items-center justify-center">
              <div className="text-center text-gray-500 dark:text-gray-400">
                <Activity className="w-12 h-12 mx-auto mb-2" />
                <p>Risk metrics chart will be implemented in future step</p>
                <p className="text-xs mt-1">Showing rolling volatility and VaR over time</p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Drawdown Analysis
              </h3>
              <TrendingDown className="w-5 h-5 text-gray-500" />
            </div>
            <div className="h-64 bg-gray-100 dark:bg-gray-700 rounded-lg flex items-center justify-center">
              <div className="text-center text-gray-500 dark:text-gray-400">
                <TrendingDown className="w-12 h-12 mx-auto mb-2" />
                <p>Drawdown chart will be implemented in future step</p>
                <p className="text-xs mt-1">Historical drawdown periods and recovery analysis</p>
              </div>
            </div>
          </div>
        </div>

        {/* Position-Level Risk Analysis */}
        {positionData.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700">
            <div className="p-4 border-b border-gray-200 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Position-Level Risk Analysis
                </h3>
                <div className="flex items-center space-x-2">
                  <button className="flex items-center px-3 py-2 text-sm bg-gray-100 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-500 transition-colors">
                    <Download className="w-4 h-4 mr-1" />
                    Export
                  </button>
                </div>
              </div>
            </div>

            <DataTable
              data={positionData}
              columns={positionColumns}
              loading={analyticsLoading}
              searchablePlaceholder="Search positions..."
              exportable={false}
            />
          </div>
        )}

        {/* Risk Analysis Insights */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Key Risk Insights
          </h3>
          <div className="space-y-4">
            {realizedRisk?.portfolio?.max_drawdown && realizedRisk.portfolio.max_drawdown < -0.05 && (
              <div className="flex items-start space-x-3">
                <AlertTriangle className="w-5 h-5 text-yellow-600 mt-0.5" />
                <div>
                  <h4 className="font-medium text-gray-900 dark:text-white">High Drawdown Risk</h4>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Portfolio experienced a maximum drawdown of {formatPercentage(realizedRisk.portfolio.max_drawdown)} over the analysis period.
                  </p>
                </div>
              </div>
            )}

            {realizedRisk?.portfolio?.sharpe_ratio && realizedRisk.portfolio.sharpe_ratio > 1 && (
              <div className="flex items-start space-x-3">
                <TrendingUp className="w-5 h-5 text-green-600 mt-0.5" />
                <div>
                  <h4 className="font-medium text-gray-900 dark:text-white">Strong Risk-Adjusted Returns</h4>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Sharpe ratio of {formatRatio(realizedRisk.portfolio.sharpe_ratio)} indicates excellent risk-adjusted performance.
                  </p>
                </div>
              </div>
            )}

            <div className="flex items-start space-x-3">
              <BarChart3 className="w-5 h-5 text-blue-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Analysis Methodology</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {realizedRisk?.methodology || 'Risk metrics calculated using historical price data with statistical models.'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Fallback loading state
  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-red-600 to-orange-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Realized Risk</h1>
            <p className="text-red-100">
              Historical risk metrics and portfolio performance analysis
            </p>
          </div>
          <div className="hidden md:block">
            <TrendingDown className="w-16 h-16 text-red-200" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {[1, 2, 3, 4].map((i) => (
          <MetricCard
            key={i}
            title="Loading..."
            value="..."
            loading={true}
            icon={Activity}
          />
        ))}
      </div>
    </div>
  );
}