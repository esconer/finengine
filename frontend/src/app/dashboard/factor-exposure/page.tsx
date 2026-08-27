/**
 * Factor Exposure Page - Multi-factor risk analysis
 */

'use client';

import React, { useState, useEffect } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import { analyticsApi } from '@/lib/api';
import { usePortfolioStore } from '@/lib/store';
import {
  Target,
  BarChart3,
  TrendingUp,
  Activity,
  RefreshCw,
  Download,
  Settings,
  AlertTriangle
} from 'lucide-react';

interface FactorData {
  portfolio: Record<string, number>;
  positions: Record<string, Record<string, number>>;
  r_squared: number;
  adjusted_r_squared: number;
  data_range?: {
    start: string;
    end: string;
  };
  lookback_days: number;
  methodology?: string;
}

interface FactorMetric {
  name: string;
  portfolio_value: number;
  interpretation: string;
  risk_level: 'High' | 'Medium' | 'Low';
  color_class: string;
}

export default function FactorExposurePage() {
  const [factorData, setFactorData] = useState<FactorData | null>(null);
  const [lookbackDays, setLookbackDays] = useState(252);
  const [loading, setLoading] = useState(false);
  const [positionData, setPositionData] = useState<any[]>([]);

  const { positions, fetchPortfolio } = usePortfolioStore();

  const fetchFactorData = async () => {
    setLoading(true);
    try {
      const tickers = positions.map(p => p.ticker).join(',');
      const data = await analyticsApi.getFactorExposure({
        tickers,
        lookback_days: lookbackDays
      });
      setFactorData(data);

      // Convert positions data for table
      const positionsList = Object.entries(data.positions || {}).map(([ticker, factors]: [string, any]) => ({
        ticker,
        ...factors
      }));
      setPositionData(positionsList);
    } catch (error) {
      console.error('Failed to fetch factor exposure data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
    fetchFactorData();
  }, []);

  useEffect(() => {
    if (positions.length > 0) {
      fetchFactorData();
    }
  }, [positions, lookbackDays]);

  const handleLookbackChange = (days: number) => {
    setLookbackDays(days);
  };

  const handleRefresh = () => {
    fetchFactorData();
  };

  // Format metrics for display
  const formatFactor = (value: number, decimals = 3) => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(decimals)}`;
  };

  const getRiskColor = (value: number): string => {
    const absValue = Math.abs(value);
    if (absValue > 0.8) return 'text-red-600 dark:text-red-400';
    if (absValue > 0.4) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-green-600 dark:text-green-400';
  };

  const getBarColor = (value: number): string => {
    const absValue = Math.abs(value);
    if (absValue > 0.8) return 'bg-red-500';
    if (absValue > 0.4) return 'bg-yellow-500';
    return 'bg-green-500';
  };

  // Factor interpretation helper
  const getFactorInterpretation = (factorName: string, value: number) => {
    if (factorName.toLowerCase().includes('beta') || factorName.toLowerCase().includes('market')) {
      if (value > 1.2) return 'High Beta';
      if (value < 0.8) return 'Defensive';
      return 'Market-Like';
    }
    if (factorName.toLowerCase().includes('alpha')) {
      if (value > 0.001) return 'Positive Alpha';
      if (value < -0.001) return 'Negative Alpha';
      return 'Neutral Alpha';
    }
    return 'Neutral exposure';
  };

  const factorMetrics = [
    { name: 'Market Beta (β)', portfolio_value: factorData?.portfolio?.market ?? 1.0, interpretation: 'Sensitivity to NIFTY 50 benchmark', risk_level: 'Medium' as const, color_class: 'bg-blue-500' },
    { name: "Jensen's Alpha (α)", portfolio_value: factorData?.portfolio?.alpha ?? 0.0, interpretation: 'Excess daily return over benchmark', risk_level: 'Low' as const, color_class: 'bg-green-500' },
  ];

  const handleExportCSV = () => {
    if (!positionData || positionData.length === 0) return;
    const headers = 'Ticker,Market Beta,Jensens Alpha\n';
    const rows = positionData
      .map(p => `${p.ticker},${(p.market ?? 1).toFixed(4)},${(p.alpha ?? 0).toFixed(6)}`)
      .join('\n');
    const blob = new Blob([headers + rows], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `factor-exposure-${lookbackDays}d.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Position-level factor table columns
  const positionColumns = [
    {
      header: 'Ticker',
      accessorKey: 'ticker',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="font-medium text-gray-900 dark:text-white">
            {data.ticker}
          </div>
        );
      },
    },
    {
      header: 'Market Beta (β)',
      accessorKey: 'market',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className={getRiskColor(data.market)}>
            {formatFactor(data.market ?? 1.0)}
          </div>
        );
      },
    },
    {
      header: "Jensen's Alpha (α)",
      accessorKey: 'alpha',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className={(data.alpha ?? 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
            {formatFactor(data.alpha ?? 0.0, 4)}
          </div>
        );
      },
    },
  ];

  const rSquared = factorData?.r_squared ?? 0.40;
  const systematicShare = Number((rSquared * 100).toFixed(1));
  const idiosyncraticShare = Number(((1 - rSquared) * 100).toFixed(1));
  const benchmarkCorr = Number((Math.sqrt(Math.max(0, rSquared)) * 100).toFixed(1));

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-green-600 to-teal-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Factor Exposure</h1>
            <p className="text-green-100">
              Statistical factor model with market benchmark regression vs NIFTY 50
            </p>
            <div className="flex items-center mt-2 space-x-4">
              <div className="text-green-200 text-sm">
                Lookback: {lookbackDays} days
              </div>
              {factorData?.data_range && (
                <div className="text-green-200 text-sm">
                  Period: {factorData.data_range.start} to {factorData.data_range.end}
                </div>
              )}
              {factorData && (
                <div className="text-green-200 text-sm">
                  R²: {factorData.r_squared?.toFixed(3) || 'N/A'}
                </div>
              )}
            </div>
          </div>
          <div className="hidden md:flex items-center space-x-2">
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="bg-white/20 hover:bg-white/30 rounded-lg p-2 transition-colors"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <Target className="w-16 h-16 text-green-200" />
          </div>
        </div>
      </div>

      {/* Key Factor Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Market Beta (β)"
          value={factorData?.portfolio?.market ? formatFactor(factorData.portfolio.market) : '1.000'}
          icon={Target}
          loading={loading}
        />
        <MetricCard
          title="Jensen's Alpha (α)"
          value={factorData?.portfolio?.alpha !== undefined ? formatFactor(factorData.portfolio.alpha, 4) : '0.0000'}
          icon={TrendingUp}
          loading={loading}
        />
        <MetricCard
          title="R-Squared (R²)"
          value={factorData?.r_squared !== undefined ? factorData.r_squared.toFixed(3) : 'N/A'}
          icon={BarChart3}
          loading={loading}
        />
        <MetricCard
          title="Model Fit Quality"
          value={factorData?.r_squared && factorData.r_squared > 0.7 ? 'Strong' : factorData?.r_squared && factorData.r_squared > 0.4 ? 'Moderate' : 'Weak'}
          icon={Settings}
          loading={loading}
        />
      </div>

      {/* Factor Analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Portfolio Factor Loadings
            </h3>
            <Settings className="w-5 h-5 text-gray-500" />
          </div>
          <div className="space-y-4">
            {factorMetrics.map((factor) => (
              <div key={factor.name} className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    {factor.name}
                  </span>
                  <span className={`text-sm font-medium ${getRiskColor(factor.portfolio_value)}`}>
                    {formatFactor(factor.portfolio_value)}
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${getBarColor(factor.portfolio_value)}`}
                      style={{ width: `${Math.min(Math.abs(factor.portfolio_value) * 60, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 dark:text-gray-400 w-24 text-right">
                    {getFactorInterpretation(factor.name, factor.portfolio_value)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Live Factor & Benchmark Variance Decomposition */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Variance Decomposition vs NIFTY 50
              </h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">Systematic vs Idiosyncratic Risk Breakdown</p>
            </div>
            <BarChart3 className="w-5 h-5 text-teal-500" />
          </div>
          <div className="space-y-4">
            <div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-gray-600 dark:text-gray-400">Market Correlation</span>
                <span className="font-semibold text-gray-900 dark:text-white">{benchmarkCorr}%</span>
              </div>
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                <div className="bg-teal-500 h-2 rounded-full" style={{ width: `${benchmarkCorr}%` }} />
              </div>
            </div>
            <div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-gray-600 dark:text-gray-400">Systematic (Market) Risk</span>
                <span className="font-semibold text-blue-600 dark:text-blue-400">{systematicShare}%</span>
              </div>
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                <div className="bg-blue-500 h-2 rounded-full" style={{ width: `${systematicShare}%` }} />
              </div>
            </div>
            <div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-gray-600 dark:text-gray-400">Specific (Idiosyncratic) Risk</span>
                <span className="font-semibold text-purple-600 dark:text-purple-400">{idiosyncraticShare}%</span>
              </div>
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                <div className="bg-purple-500 h-2 rounded-full" style={{ width: `${idiosyncraticShare}%` }} />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Position-Level Factor Analysis */}
      {positionData.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700">
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Position-Level Factor Exposures
              </h3>
              <div className="flex items-center space-x-2">
                <select
                  value={lookbackDays}
                  onChange={(e) => handleLookbackChange(parseInt(e.target.value))}
                  className="px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                >
                  <option value={126}>6 months</option>
                  <option value={252}>1 year</option>
                  <option value={504}>2 years</option>
                  <option value={756}>3 years</option>
                </select>
                <button
                  onClick={handleExportCSV}
                  className="flex items-center px-3 py-2 text-sm bg-gray-100 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-500 transition-colors"
                >
                  <Download className="w-4 h-4 mr-1" />
                  Export
                </button>
              </div>
            </div>
          </div>

          <DataTable
            data={positionData}
            columns={positionColumns}
            loading={loading}
            searchablePlaceholder="Search positions..."
            exportable={false}
          />
        </div>
      )}

      {/* Factor Insights */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Factor Analysis Insights
        </h3>
        <div className="space-y-4">
          {factorData?.r_squared && factorData.r_squared < 0.4 && (
            <div className="flex items-start space-x-3">
              <AlertTriangle className="w-5 h-5 text-yellow-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Low Model Fit</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  R-squared of {factorData.r_squared.toFixed(3)} suggests the factor model explains less than half the portfolio variance. Consider additional factors or alternative models.
                </p>
              </div>
            </div>
          )}

          {factorData?.portfolio?.market && Math.abs(factorData.portfolio.market - 1) > 0.2 && (
            <div className="flex items-start space-x-3">
              <Target className="w-5 h-5 text-blue-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Market Sensitivity</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Portfolio beta of {formatFactor(factorData.portfolio.market)} indicates {factorData.portfolio.market > 1.2 ? 'high' : factorData.portfolio.market < 0.8 ? 'low' : 'moderate'} market sensitivity.
                </p>
              </div>
            </div>
          )}

          <div className="flex items-start space-x-3">
            <BarChart3 className="w-5 h-5 text-green-600 mt-0.5" />
            <div>
              <h4 className="font-medium text-gray-900 dark:text-white">Analysis Methodology</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {factorData?.methodology || `Factor exposures calculated using statistical regression over ${lookbackDays}-day lookback period.`}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}