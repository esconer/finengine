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

  const { positions } = usePortfolioStore();

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

  const getFactorInterpretation = (factorName: string, value: number): string => {
    const interpretations: Record<string, Record<string, string>> = {
      'Market': {
        high: 'High market sensitivity',
        medium: 'Moderate market exposure',
        low: 'Low market correlation'
      },
      'Value': {
        high: 'Strong value tilt',
        medium: 'Balanced value exposure',
        low: 'Growth-oriented'
      },
      'Momentum': {
        high: 'Strong momentum factor',
        medium: 'Moderate momentum',
        low: 'Contrarian positioning'
      },
      'Quality': {
        high: 'High-quality bias',
        medium: 'Balanced quality',
        low: 'Lower quality exposure'
      },
      'Size': {
        high: 'Large-cap tilt',
        medium: 'Balanced size',
        low: 'Small-cap exposure'
      }
    };

    const absValue = Math.abs(value);
    let level = 'medium';
    if (absValue > 0.8) level = 'high';
    else if (absValue < 0.3) level = 'low';

    return interpretations[factorName]?.[level] || 'Neutral exposure';
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

  // Factor metrics for the main display
  const factorMetrics: FactorMetric[] = [
    { name: 'Market', portfolio_value: factorData?.portfolio?.market || 0, interpretation: 'Market beta exposure', risk_level: 'Medium' as const, color_class: 'bg-blue-500' },
    { name: 'Value', portfolio_value: factorData?.portfolio?.value || 0, interpretation: 'Value factor tilt', risk_level: 'Low' as const, color_class: 'bg-green-500' },
    { name: 'Momentum', portfolio_value: factorData?.portfolio?.momentum || 0, interpretation: 'Momentum exposure', risk_level: 'Medium' as const, color_class: 'bg-purple-500' },
    { name: 'Quality', portfolio_value: factorData?.portfolio?.quality || 0, interpretation: 'Quality bias', risk_level: 'Low' as const, color_class: 'bg-orange-500' },
    { name: 'Size', portfolio_value: factorData?.portfolio?.size || 0, interpretation: 'Size factor exposure', risk_level: 'Low' as const, color_class: 'bg-teal-500' },
    { name: 'Rates', portfolio_value: factorData?.portfolio?.rates || 0, interpretation: 'Interest rate sensitivity', risk_level: 'Low' as const, color_class: 'bg-indigo-500' },
  ].filter(metric => Math.abs(metric.portfolio_value) > 0.01); // Filter out near-zero exposures

  // Position-level factor table columns
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
      header: 'Market',
      accessorKey: 'market',
      cell: ({ row }: any) => (
        <div className={getRiskColor(row.market)}>
          {formatFactor(row.market)}
        </div>
      ),
    },
    {
      header: 'Value',
      accessorKey: 'value',
      cell: ({ row }: any) => (
        <div className={getRiskColor(row.value)}>
          {formatFactor(row.value)}
        </div>
      ),
    },
    {
      header: 'Momentum',
      accessorKey: 'momentum',
      cell: ({ row }: any) => (
        <div className={getRiskColor(row.momentum)}>
          {formatFactor(row.momentum)}
        </div>
      ),
    },
    {
      header: 'Quality',
      accessorKey: 'quality',
      cell: ({ row }: any) => (
        <div className={getRiskColor(row.quality)}>
          {formatFactor(row.quality)}
        </div>
      ),
    },
    {
      header: 'Size',
      accessorKey: 'size',
      cell: ({ row }: any) => (
        <div className={getRiskColor(row.size)}>
          {formatFactor(row.size)}
        </div>
      ),
    },
    {
      header: 'R² Contribution',
      accessorKey: 'r_squared',
      cell: ({ row }: any) => {
        const r2Contribution = Math.abs(row.market) * 0.5 + Math.abs(row.value) * 0.2 + Math.abs(row.momentum) * 0.2;
        return (
          <div className={`${r2Contribution > 0.7 ? 'text-red-600' : r2Contribution > 0.4 ? 'text-yellow-600' : 'text-green-600'}`}>
            {r2Contribution.toFixed(3)}
          </div>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-green-600 to-teal-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Factor Exposure</h1>
            <p className="text-green-100">
              Multi-factor risk analysis and exposure metrics
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
          title="Market Beta"
          value={factorData?.portfolio?.market ? formatFactor(factorData.portfolio.market) : 'N/A'}
          change={0.03}
          changeType="neutral"
          icon={Target}
          loading={loading}
        />
        <MetricCard
          title="Value Factor"
          value={factorData?.portfolio?.value ? formatFactor(factorData.portfolio.value) : 'N/A'}
          change={-0.12}
          changeType={factorData?.portfolio?.value && factorData.portfolio.value < 0 ? "negative" : "positive"}
          icon={TrendingUp}
          loading={loading}
        />
        <MetricCard
          title="Momentum Factor"
          value={factorData?.portfolio?.momentum ? formatFactor(factorData.portfolio.momentum) : 'N/A'}
          change={0.08}
          changeType="positive"
          icon={Activity}
          loading={loading}
        />
        <MetricCard
          title="Quality Factor"
          value={factorData?.portfolio?.quality ? formatFactor(factorData.portfolio.quality) : 'N/A'}
          change={0.05}
          changeType="positive"
          icon={BarChart3}
          loading={loading}
        />
      </div>

      {/* Extended Factor Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <MetricCard
          title="R-squared"
          value={factorData?.r_squared ? factorData.r_squared.toFixed(3) : 'N/A'}
          change={0.02}
          changeType="positive"
          icon={BarChart3}
          loading={loading}
        />
        <MetricCard
          title="Adjusted R²"
          value={factorData?.adjusted_r_squared ? factorData.adjusted_r_squared.toFixed(3) : 'N/A'}
          change={0.01}
          changeType="positive"
          icon={Target}
          loading={loading}
        />
        <MetricCard
          title="Model Fit Quality"
          value={factorData?.r_squared && factorData.r_squared > 0.7 ? 'Strong' : factorData?.r_squared && factorData.r_squared > 0.4 ? 'Moderate' : 'Weak'}
          change={0}
          changeType={factorData?.r_squared && factorData.r_squared > 0.7 ? "positive" : "neutral"}
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
                      style={{ width: `${Math.min(Math.abs(factor.portfolio_value) * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 dark:text-gray-400 w-16">
                    {getFactorInterpretation(factor.name, factor.portfolio_value)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Factor Correlations
            </h3>
            <BarChart3 className="w-5 h-5 text-gray-500" />
          </div>
          <div className="h-64 bg-gray-100 dark:bg-gray-700 rounded-lg flex items-center justify-center">
            <div className="text-center text-gray-500 dark:text-gray-400">
              <BarChart3 className="w-12 h-12 mx-auto mb-2" />
              <p>Factor correlation matrix will be implemented</p>
              <p className="text-xs mt-1">Showing inter-factor relationships</p>
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