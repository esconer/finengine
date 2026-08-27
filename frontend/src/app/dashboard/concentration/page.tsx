/**
 * Concentration Page - Portfolio concentration metrics
 */

'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import { analyticsApi } from '@/lib/api';
import { usePortfolioStore } from '@/lib/store';
import {
  BarChart3,
  Target,
  AlertTriangle,
  TrendingUp,
  RefreshCw,
  Download,
  Settings,
  PieChart
} from 'lucide-react';

interface ConcentrationData {
  largest_position: number;
  top_3: number;
  top_5: number;
  top_10: number;
  herfindahl_index: number;
  effective_positions: number;
  diversification_ratio: number;
  by_weight: Record<string, number>;
  by_sector: Record<string, number>;
  methodology?: string;
}

interface ConcentrationMetric {
  name: string;
  value: number;
  threshold: number;
  status: 'Good' | 'Warning' | 'Risk';
  color_class: string;
  description: string;
}

export default function ConcentrationPage() {
  const [concentrationData, setConcentrationData] = useState<ConcentrationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [positionData, setPositionData] = useState<any[]>([]);

  const { positions, fetchPortfolio } = usePortfolioStore();

  // Compute Lorenz Inequality Curve
  const lorenzCurveData = useMemo(() => {
    if (!positionData || positionData.length === 0) {
      return [{ assetPct: '0%', portfolioCumPct: 0, equalWeightPct: 0 }, { assetPct: '100%', portfolioCumPct: 100, equalWeightPct: 100 }];
    }
    const n = positionData.length;
    // Rank weights ascending for true Lorenz curve
    const sortedWeights = [...positionData].map(p => p.weight).sort((a, b) => a - b);
    const points = [{ assetPct: '0%', portfolioCumPct: 0, equalWeightPct: 0 }];
    let cumSum = 0;
    for (let i = 0; i < n; i++) {
      cumSum += sortedWeights[i];
      const assetPctNum = Math.round(((i + 1) / n) * 100);
      points.push({
        assetPct: `${assetPctNum}%`,
        portfolioCumPct: Number((cumSum * 100).toFixed(1)),
        equalWeightPct: assetPctNum,
      });
    }
    return points;
  }, [positionData]);

  const handleExportCSV = () => {
    if (!positionData || positionData.length === 0) return;
    const headers = 'Ticker,Weight,Cumulative Weight,Sector\n';
    const rows = positionData
      .map(p => `${p.ticker},${(p.weight * 100).toFixed(2)}%,${(p.cumulative_weight * 100).toFixed(2)}%,${p.sector}`)
      .join('\n');
    const blob = new Blob([headers + rows], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `concentration-holdings.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const fetchConcentrationData = async () => {
    setLoading(true);
    try {
      const data = await analyticsApi.getConcentrationMetrics();
      setConcentrationData(data);

      // Convert by_weight data for table with real sector and pre-calculated cumulative weights
      let cumWeight = 0;
      const sortedEntries = Object.entries(data.by_weight || {}).sort(([, a], [, b]) => (b as number) - (a as number));
      const positionsList = sortedEntries.map(([ticker, weight]) => {
        cumWeight += (weight as number);
        const pos = positions.find(p => p.ticker === ticker);
        return {
          ticker,
          weight: weight as number,
          cumulative_weight: cumWeight,
          sector: pos?.sector || 'General'
        };
      });
      setPositionData(positionsList);
    } catch (error) {
      console.error('Failed to fetch concentration data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
    fetchConcentrationData();
  }, []);

  useEffect(() => {
    if (positions.length > 0) {
      fetchConcentrationData();
    }
  }, [positions]);

  const handleRefresh = () => {
    fetchConcentrationData();
  };

  // Format metrics for display
  const formatPercentage = (value: number | undefined | null, decimals = 1) => {
    if (value === undefined || value === null || isNaN(value)) {
      return 'N/A';
    }
    return `${(value * 100).toFixed(decimals)}%`;
  };

  const formatRatio = (value: number, decimals = 2) => {
    return value.toFixed(decimals);
  };

  const getConcentrationStatus = (metric: string, value: number): 'Good' | 'Warning' | 'Risk' => {
    const thresholds: Record<string, { good: number; warning: number }> = {
      largest_position: { good: 0.10, warning: 0.15 },
      top_3: { good: 0.40, warning: 0.60 },
      herfindahl_index: { good: 0.15, warning: 0.25 },
    };

    const threshold = thresholds[metric];
    if (!threshold) return 'Good';

    if (value <= threshold.good) return 'Good';
    if (value <= threshold.warning) return 'Warning';
    return 'Risk';
  };

  const getStatusColor = (status: 'Good' | 'Warning' | 'Risk'): string => {
    switch (status) {
      case 'Good': return 'text-green-600 dark:text-green-400';
      case 'Warning': return 'text-yellow-600 dark:text-yellow-400';
      case 'Risk': return 'text-red-600 dark:text-red-400';
      default: return 'text-gray-600 dark:text-gray-400';
    }
  };

  const getStatusBgColor = (status: 'Good' | 'Warning' | 'Risk'): string => {
    switch (status) {
      case 'Good': return 'bg-green-100 dark:bg-green-900/20 border-green-200 dark:border-green-800';
      case 'Warning': return 'bg-yellow-100 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800';
      case 'Risk': return 'bg-red-100 dark:bg-red-900/20 border-red-200 dark:border-red-800';
      default: return 'bg-gray-100 dark:bg-gray-700 border-gray-200 dark:border-gray-600';
    }
  };

  // Concentration metrics for display
  const concentrationMetrics: ConcentrationMetric[] = [
    {
      name: 'Largest Position',
      value: concentrationData?.largest_position || 0,
      threshold: 0.15,
      status: getConcentrationStatus('largest_position', concentrationData?.largest_position || 0),
      color_class: 'bg-blue-500',
      description: 'Weight of the largest individual position'
    },
    {
      name: 'Top 3 Holdings',
      value: concentrationData?.top_3 || 0,
      threshold: 0.60,
      status: getConcentrationStatus('top_3', concentrationData?.top_3 || 0),
      color_class: 'bg-purple-500',
      description: 'Combined weight of top 3 positions'
    },
    {
      name: 'Top 10 Holdings',
      value: concentrationData?.top_10 || 0,
      threshold: 0.80,
      status: 'Good',
      color_class: 'bg-orange-500',
      description: 'Combined weight of top 10 positions'
    },
    {
      name: 'Herfindahl Index',
      value: concentrationData?.herfindahl_index || 0,
      threshold: 0.25,
      status: getConcentrationStatus('herfindahl_index', concentrationData?.herfindahl_index || 0),
      color_class: 'bg-red-500',
      description: 'Sum of squared position weights'
    },
  ];

  // Position concentration table columns
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
      header: 'Weight',
      accessorKey: 'weight',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-900 dark:text-white">
            {formatPercentage(data.weight)}
          </div>
        );
      },
    },
    {
      header: 'Cumulative %',
      accessorKey: 'cumulative_weight',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-900 dark:text-white">
            {formatPercentage(data.cumulative_weight)}
          </div>
        );
      },
    },
    {
      header: 'Sector',
      accessorKey: 'sector',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-600 dark:text-gray-400">
            {data.sector}
          </div>
        );
      },
    },
    {
      header: 'Concentration Risk',
      accessorKey: 'concentration_risk',
      cell: ({ row }: any) => {
        const data = row.original || row;
        const weightVal = data.weight ?? 0;
        const riskLevel = weightVal > 0.15 ? 'High' : weightVal > 0.10 ? 'Medium' : 'Low';
        const colorClass = riskLevel === 'High' ? 'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-300' :
          riskLevel === 'Medium' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-300' :
            'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-300';
        return (
          <span className={`px-2 py-1 text-xs rounded-full font-medium ${colorClass}`}>
            {riskLevel}
          </span>
        );
      },
    },
  ];

  // Sector concentration data
  const sectorData = concentrationData?.by_sector ? Object.entries(concentrationData.by_sector)
    .map(([sector, weight]) => ({
      sector: sector.replace('_', ' '),
      weight,
      percentage: formatPercentage(weight)
    }))
    .filter(s => s.weight > 0.01)
    .sort((a, b) => b.weight - a.weight) : [];

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-indigo-600 to-purple-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Concentration</h1>
            <p className="text-indigo-100">
              Portfolio concentration metrics and diversification analysis
            </p>
            <div className="flex items-center mt-2 space-x-4">
              <div className="text-indigo-200 text-sm">
                Effective Positions: {concentrationData?.effective_positions?.toFixed(1) || 'N/A'}
              </div>
              <div className="text-indigo-200 text-sm">
                Diversification Ratio: {concentrationData?.diversification_ratio?.toFixed(2) || 'N/A'}
              </div>
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
            <BarChart3 className="w-16 h-16 text-indigo-200" />
          </div>
        </div>
      </div>

      {/* Concentration Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Largest Position"
          value={concentrationData?.largest_position ? formatPercentage(concentrationData.largest_position) : 'N/A'}
          icon={Target}
          loading={loading}
        />
        <MetricCard
          title="Top 3 Holdings"
          value={concentrationData?.top_3 ? formatPercentage(concentrationData.top_3) : 'N/A'}
          icon={BarChart3}
          loading={loading}
        />
        <MetricCard
          title="Herfindahl Index"
          value={concentrationData?.herfindahl_index ? formatRatio(concentrationData.herfindahl_index) : 'N/A'}
          icon={AlertTriangle}
          loading={loading}
        />
        <MetricCard
          title="Effective Positions"
          value={concentrationData?.effective_positions ? formatRatio(concentrationData.effective_positions) : 'N/A'}
          icon={TrendingUp}
          loading={loading}
        />
      </div>

      {/* Detailed Concentration Analysis & Lorenz Curve */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Lorenz Inequality Curve */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Lorenz Concentration Curve
              </h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Cumulative portfolio capital vs equal-weight benchmark
              </p>
            </div>
            <TrendingUp className="w-5 h-5 text-blue-500" />
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={lorenzCurveData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="assetPct" tick={{ fontSize: 11 }} />
                <YAxis unit="%" domain={[0, 100]} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(value: any, name: any) => [`${value}%`, name === 'portfolioCumPct' ? 'Actual Portfolio Weight' : 'Equal-Weight Benchmark']} />
                <Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: '12px' }} />
                <Line type="monotone" dataKey="equalWeightPct" stroke="#9ca3af" strokeDasharray="4 4" strokeWidth={1.5} dot={false} name="Equal-Weight" />
                <Line type="monotone" dataKey="portfolioCumPct" stroke="#3b82f6" strokeWidth={2.5} dot={{ r: 3 }} name="Portfolio Concentration" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Sector Concentration Distribution */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Sector Concentration
              </h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">Industry exposure distribution</p>
            </div>
            <PieChart className="w-5 h-5 text-indigo-500" />
          </div>
          {sectorData.length > 0 ? (
            <div className="space-y-4 pt-2">
              {sectorData.slice(0, 6).map((sector) => (
                <div key={sector.sector} className="space-y-1.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-gray-700 dark:text-gray-300">
                      {sector.sector}
                    </span>
                    <span className="font-semibold text-gray-900 dark:text-white">
                      {sector.percentage}
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5">
                    <div
                      className="h-2.5 rounded-full bg-indigo-500"
                      style={{ width: `${Math.min(sector.weight * 100, 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-400 text-sm">
              No sector concentration data available
            </div>
          )}
        </div>
      </div>

      {/* Position-Level Analysis */}
      {positionData.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700">
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Position Concentration Details
              </h3>
              <div className="flex items-center space-x-2">
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

      {/* Concentration Risk Assessment */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Concentration Risk Assessment
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="text-center">
            <div className="w-16 h-16 bg-green-100 dark:bg-green-900/20 rounded-full flex items-center justify-center mx-auto mb-3">
              <Target className="w-8 h-8 text-green-600 dark:text-green-400" />
            </div>
            <h4 className="font-medium text-gray-900 dark:text-white">
              {concentrationMetrics.filter(m => m.status === 'Good').length >= 3 ? 'Well Diversified' : 'Moderate Diversification'}
            </h4>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              {concentrationMetrics.filter(m => m.status === 'Good').length >= 3
                ? 'Portfolio shows good diversification across holdings'
                : 'Some concentration risk present'
              }
            </p>
          </div>

          <div className="text-center">
            <div className="w-16 h-16 bg-yellow-100 dark:bg-yellow-900/20 rounded-full flex items-center justify-center mx-auto mb-3">
              <BarChart3 className="w-8 h-8 text-yellow-600 dark:text-yellow-400" />
            </div>
            <h4 className="font-medium text-gray-900 dark:text-white">Monitor Closely</h4>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              {concentrationMetrics.filter(m => m.status === 'Warning').length > 0
                ? `${concentrationMetrics.filter(m => m.status === 'Warning').length} concentration metrics need attention`
                : 'Concentration levels within acceptable range'
              }
            </p>
          </div>

          <div className="text-center">
            <div className="w-16 h-16 bg-red-100 dark:bg-red-900/20 rounded-full flex items-center justify-center mx-auto mb-3">
              <AlertTriangle className="w-8 h-8 text-red-600 dark:text-red-400" />
            </div>
            <h4 className="font-medium text-gray-900 dark:text-white">
              {concentrationMetrics.filter(m => m.status === 'Risk').length > 0 ? 'High Concentration Risk' : 'Risk Managed'}
            </h4>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              {concentrationMetrics.filter(m => m.status === 'Risk').length > 0
                ? 'Consider rebalancing to reduce concentration'
                : 'Concentration risk appears well managed'
              }
            </p>
          </div>
        </div>
      </div>

      {/* Concentration Insights */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Concentration Analysis Insights
        </h3>
        <div className="space-y-4">
          {concentrationData?.largest_position && concentrationData.largest_position > 0.15 && (
            <div className="flex items-start space-x-3">
              <AlertTriangle className="w-5 h-5 text-red-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">High Single Position Risk</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Largest position accounts for {formatPercentage(concentrationData.largest_position)}, which may increase portfolio volatility.
                </p>
              </div>
            </div>
          )}

          {concentrationData?.herfindahl_index && concentrationData.herfindahl_index < 0.20 && (
            <div className="flex items-start space-x-3">
              <Target className="w-5 h-5 text-green-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Good Diversification</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Herfindahl Index of {formatRatio(concentrationData.herfindahl_index)} indicates well-diversified portfolio.
                </p>
              </div>
            </div>
          )}

          <div className="flex items-start space-x-3">
            <BarChart3 className="w-5 h-5 text-blue-600 mt-0.5" />
            <div>
              <h4 className="font-medium text-gray-900 dark:text-white">Analysis Methodology</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {concentrationData?.methodology || 'Concentration analysis using Herfindahl-Hirschman Index and effective number of positions.'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}