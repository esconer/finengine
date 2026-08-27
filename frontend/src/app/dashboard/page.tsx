'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import { PerformanceChart } from '@/components/charts/PerformanceChart';
import { SectorAllocationChart } from '@/components/charts/SectorAllocationChart';
import { RiskMetricsDisplay } from '@/components/charts/RiskMetricsDisplay';
import { AddPositionModalSimple } from '@/components/portfolio/AddPositionModalSimple';
import { usePortfolioStore, useUIStore } from '@/lib/store';
import { portfolioApi, analyticsApi } from '@/lib/api';
import { usePortfolioAnalytics, usePerformanceData, useSectorAllocation } from '@/hooks/useAnalytics';
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Target,
  Activity,
  AlertTriangle,
  BarChart3,
  Shield,
  RefreshCw,
  Edit,
  Trash2,
  Download,
  Radar,
  PieChart
} from 'lucide-react';

const REGIME_CHIP: Record<string, string> = {
  calm: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300',
  volatile: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
  crisis: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300'
};

interface PortfolioPosition {
  id: number;
  ticker: string;
  weight: number;
  last_price: number;
  market_value: number;
  sector: string;
  industry: string;
  custom_name?: string;
  added_on: string;
  updated_on: string;
}

export default function DashboardSummary() {
  const router = useRouter();
  const { positions, fetchPortfolio, isLoading, error, totalValue } = usePortfolioStore();
  const { updateLastUpdated } = useUIStore();
  const [showAddModal, setShowAddModal] = useState(false);
  const { data: analyticsData, loading: analyticsLoading, refresh: refreshAnalytics } = usePortfolioAnalytics();
  const { performanceData, loading: performanceLoading } = usePerformanceData(90);
  const sectorData = useSectorAllocation();
  const [regimeInfo, setRegimeInfo] = useState<{ current_regime: string; stability_pct: number } | null>(null);
  const [riskDrivers, setRiskDrivers] = useState<[string, number][] | null>(null);

  useEffect(() => {
    fetchPortfolio();
  }, [fetchPortfolio]);

  // Supplementary widgets: regime + risk drivers load quietly and never block the page
  useEffect(() => {
    analyticsApi
      .getRegime({ with_portfolio: false })
      .then((r) => setRegimeInfo({ current_regime: r.current_regime, stability_pct: r.stability_pct }))
      .catch(() => setRegimeInfo(null));
    analyticsApi
      .getRiskContribution()
      .then((r) => {
        const entries = Object.entries(r.positions?.volatility ?? {}) as [string, number][];
        entries.sort(([, a], [, b]) => b - a);
        setRiskDrivers(entries.slice(0, 3));
      })
      .catch(() => setRiskDrivers(null));
  }, []);

  useEffect(() => {
    if (!isLoading && !error && positions.length > 0) {
      updateLastUpdated();
    }
  }, [isLoading, error, positions.length, updateLastUpdated]);

  // Quantitative Diversification Score based on Herfindahl Concentration & Sector Breadth
  const diversificationScore = useMemo(() => {
    if (positions.length <= 1) return 0;
    const weights = positions.map(p => {
      const mv = p.market_value || ((p as any).quantity ? (p as any).quantity * (p.last_price || 0) : 0);
      return (totalValue && totalValue > 0) ? (mv / totalValue) : p.weight;
    });
    const totalW = weights.reduce((a, b) => a + b, 0) || 1;
    const normW = weights.map(w => w / totalW);
    const hhi = normW.reduce((sum, w) => sum + w * w, 0); // 1.0 for 1 stock, 0.5 for 2 equal stocks, 0.1 for 10 stocks
    const effectiveN = 1 / Math.max(hhi, 0.01);
    // Score scaled from 0% (1 stock) to 100% (10+ effective stocks across 4+ sectors)
    const positionScore = Math.min(100, Math.max(0, ((effectiveN - 1) / 9) * 100));
    const sectorMultiplier = Math.min(1, Math.max(0.25, (sectorData.length / 4)));
    return Math.round(positionScore * sectorMultiplier);
  }, [positions, totalValue, sectorData]);

  // Calculate enhanced portfolio metrics
  const portfolioMetrics = {
    totalValue: totalValue || 0,
    positionsCount: positions.length,
    totalWeight: positions.reduce((sum, pos) => sum + pos.weight, 0),
    averageWeight: positions.length > 0 ? (100 / positions.length) : 0,
    topSector: sectorData.length > 0 ? sectorData[0]?.name || 'N/A' : 'N/A',
    riskScore: analyticsData.riskScore?.overall_score || 0,
    volatility: analyticsData.summary?.realized_volatility || 0,
    sharpeRatio: analyticsData.summary?.sharpe_ratio || 0,
    maxDrawdown: analyticsData.summary?.max_drawdown || 0,
    diversificationScore,
  };

  // DataTable columns with enhanced functionality
  const positionColumns = [
    {
      header: 'Ticker',
      accessorKey: 'ticker' as keyof PortfolioPosition,
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="font-medium text-gray-900 dark:text-white">
            {data.ticker || 'N/A'}
          </div>
        );
      },
    },
    {
      header: 'Weight',
      accessorKey: 'weight' as keyof PortfolioPosition,
      cell: ({ row }: any) => {
        const data = row.original || row;
        const liveWeight = (totalValue && totalValue > 0 && data.market_value)
          ? (data.market_value / totalValue)
          : (data.weight || 0);
        return (
          <div className="text-gray-900 dark:text-white font-medium">
            {`${(liveWeight * 100).toFixed(2)}%`}
          </div>
        );
      },
    },
    {
      header: 'Market Value',
      accessorKey: 'market_value' as keyof PortfolioPosition,
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-900 dark:text-white">
            {data.market_value ? `₹${data.market_value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '₹0.00'}
          </div>
        );
      },
    },
    {
      header: 'Price',
      accessorKey: 'last_price' as keyof PortfolioPosition,
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-900 dark:text-white">
            {data.last_price ? `₹${data.last_price.toFixed(2)}` : '₹0.00'}
          </div>
        );
      },
    },
    {
      header: 'Sector',
      accessorKey: 'sector' as keyof PortfolioPosition,
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-600 dark:text-gray-400">
            {data.sector || 'N/A'}
          </div>
        );
      },
    },
    {
      header: 'Actions',
      accessorKey: 'id' as keyof PortfolioPosition,
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="flex items-center space-x-2">
            <button className="p-1 text-gray-600 hover:text-blue-600 dark:text-gray-400 dark:hover:text-blue-400">
              <Edit className="w-4 h-4" />
            </button>
            <button className="p-1 text-gray-600 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400">
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        );
      },
    },
  ];

  // Add position handler
  const handleAddPosition = async (positionData: any) => {
    try {
      await portfolioApi.addPosition(positionData);
      // Refresh portfolio data
      await fetchPortfolio();
    } catch (error) {
      console.error('Failed to add position:', error);
      throw error;
    }
  };

  const handleExportCSV = async () => {
    try {
      const response = await fetch('/api/v1/portfolio/export/csv');
      const csvData = await response.text();

      const blob = new Blob([csvData], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `portfolio-${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to export CSV:', error);
    }
  };

  const handleRefreshData = async () => {
    await fetchPortfolio();
    await refreshAnalytics();
  };

  if (error) {
    return (
      <div className="space-y-6">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 mr-2" />
            <span className="text-red-800 dark:text-red-300">
              Error loading portfolio: {error}
            </span>
          </div>
        </div>
      </div>
    );
  }

  const isOverallLoading = isLoading || analyticsLoading;

  return (
    <div className="space-y-6">
      {/* Hero Section with Live Status */}
      <div className="bg-gradient-to-r from-blue-600 to-purple-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Portfolio Overview</h1>
            <p className="text-blue-100">
              Real-time risk analysis and portfolio management
            </p>
            <div className="flex items-center mt-2 space-x-4">
              <div className="flex items-center text-green-300">
                <div className="w-2 h-2 bg-green-400 rounded-full mr-2"></div>
                <span className="text-sm">Live Data Active</span>
              </div>
              {analyticsData.summary?.last_updated && (
                <div className="text-blue-200 text-sm">
                  Last updated: {new Date(analyticsData.summary.last_updated).toLocaleTimeString()}
                </div>
              )}
            </div>
          </div>
          <div className="hidden md:flex items-center space-x-2">
            <button
              onClick={handleRefreshData}
              disabled={isOverallLoading}
              className="bg-white/20 hover:bg-white/30 rounded-lg p-2 transition-colors"
            >
              <RefreshCw className={`w-5 h-5 ${isOverallLoading ? 'animate-spin' : ''}`} />
            </button>
            <BarChart3 className="w-16 h-16 text-blue-200" />
          </div>
        </div>
      </div>

      {/* Enhanced Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Total Portfolio Value"
          value={portfolioMetrics.totalValue}
          icon={DollarSign}
          loading={isOverallLoading}
        />
        <MetricCard
          title="Number of Positions"
          value={portfolioMetrics.positionsCount}
          icon={Target}
          loading={isOverallLoading}
        />
        <MetricCard
          title="Risk Score"
          value={portfolioMetrics.riskScore.toFixed(1)}
          icon={Shield}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Sharpe Ratio"
          value={portfolioMetrics.sharpeRatio.toFixed(2)}
          icon={TrendingUp}
          loading={analyticsLoading}
        />
      </div>

      {/* Market Regime + Top Risk Drivers */}
      {(regimeInfo || (riskDrivers && riskDrivers.length > 0)) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {regimeInfo && (
            <Link
              href="/dashboard/regime"
              className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-5 border border-gray-200 dark:border-gray-700 flex items-center justify-between hover:border-blue-300 dark:hover:border-blue-600 transition-colors"
            >
              <div className="flex items-center space-x-4">
                <Radar className="w-8 h-8 text-blue-500" />
                <div>
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    Market Regime
                  </p>
                  <div className="flex items-center mt-1">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-sm font-semibold ${
                        REGIME_CHIP[regimeInfo.current_regime.toLowerCase()] ??
                        'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200'
                      }`}
                    >
                      {regimeInfo.current_regime.charAt(0).toUpperCase() +
                        regimeInfo.current_regime.slice(1)}
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400 ml-3 tabular-nums">
                      {regimeInfo.stability_pct.toFixed(0)}% stability
                    </span>
                  </div>
                </div>
              </div>
              <span className="text-xs text-blue-600 dark:text-blue-400 font-medium">
                Details →
              </span>
            </Link>
          )}

          {riskDrivers && riskDrivers.length > 0 && (
            <Link
              href="/dashboard/risk-contribution"
              className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-5 border border-gray-200 dark:border-gray-700 hover:border-orange-300 dark:hover:border-orange-600 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center space-x-3">
                  <PieChart className="w-6 h-6 text-orange-500" />
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    Top Risk Drivers
                  </p>
                </div>
                <span className="text-xs text-orange-600 dark:text-orange-400 font-medium">
                  Details →
                </span>
              </div>
              <div className="space-y-1.5 mt-3">
                {riskDrivers.map(([ticker, share]) => (
                  <div key={ticker} className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-700 dark:text-gray-300 w-20 truncate">
                      {ticker}
                    </span>
                    <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-1.5">
                      <div
                        className="h-1.5 rounded-full bg-orange-500"
                        style={{ width: `${share * 100}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-600 dark:text-gray-400 w-10 text-right tabular-nums">
                      {(share * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </Link>
          )}
        </div>
      )}

      {/* Risk Metrics Display */}
      <RiskMetricsDisplay
        data={{
          risk_score: portfolioMetrics.riskScore,
          risk_level: analyticsData.riskScore?.risk_level || 'Unknown',
          annual_volatility: portfolioMetrics.volatility,
          sharpe_ratio: portfolioMetrics.sharpeRatio,
          max_drawdown: portfolioMetrics.maxDrawdown,
          var_95: analyticsData.realizedRisk?.portfolio?.var_95 || 0,
          cvar_95: analyticsData.realizedRisk?.portfolio?.cvar_95 || 0,
          // Add FORECAST RISK DATA - This fixes the N/A issue
          forecast_volatility: analyticsData.forecastRisk?.portfolio?.volatility_forecast || null,
          forecast_var: analyticsData.forecastRisk?.portfolio?.var_forecast || null,
          realized_volatility: analyticsData.summary?.realized_volatility || portfolioMetrics.volatility,
        }}
        loading={analyticsLoading}
      />

      {/* Performance Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PerformanceChart
          data={performanceData}
          loading={performanceLoading}
          showBenchmark={false}
        />
        <SectorAllocationChart
          data={sectorData}
          loading={isOverallLoading}
        />
      </div>

      {/* Portfolio Positions Table with Management */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Portfolio Positions ({positions.length})
            </h3>
            <div className="flex items-center space-x-2">
              <button
                onClick={handleExportCSV}
                className="flex items-center px-3 py-2 text-sm bg-gray-100 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-500 transition-colors"
              >
                <Download className="w-4 h-4 mr-1" />
                Export
              </button>
              <button
                onClick={() => setShowAddModal(true)}
                className="flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                <TrendingUp className="w-4 h-4 mr-2" />
                Add Position
              </button>
            </div>
          </div>
        </div>

        <DataTable
          data={positions}
          columns={positionColumns}
          loading={isOverallLoading}
          searchablePlaceholder="Search positions..."
          exportable={false}
        />

        {/* Add Position Modal */}
        <AddPositionModalSimple
          isOpen={showAddModal}
          onClose={() => setShowAddModal(false)}
          onAdd={handleAddPosition}
          currency="INR"
        />
      </div>

      {/* Quick Actions */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Quick Actions
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <button
            onClick={() => setShowAddModal(true)}
            className="p-4 text-left rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <TrendingUp className="w-6 h-6 text-green-600 mb-2" />
            <div className="text-sm font-medium text-gray-900 dark:text-white">
              Add Position
            </div>
          </button>

          <button
            onClick={() => router.push('/dashboard/realized-risk')}
            className="p-4 text-left rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <RefreshCw className="w-6 h-6 text-blue-600 mb-2" />
            <div className="text-sm font-medium text-gray-900 dark:text-white">
              Risk Analytics
            </div>
          </button>

          <button
            onClick={() => router.push('/dashboard/optimize')}
            className="p-4 text-left rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <Target className="w-6 h-6 text-purple-600 mb-2" />
            <div className="text-sm font-medium text-gray-900 dark:text-white">
              Rebalance
            </div>
          </button>

          <button
            onClick={() => router.push('/dashboard/stress-testing')}
            className="p-4 text-left rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <Shield className="w-6 h-6 text-orange-600 mb-2" />
            <div className="text-sm font-medium text-gray-900 dark:text-white">
              Stress Test
            </div>
          </button>
        </div>
      </div>

      {/* Portfolio Health Summary */}
      {positions.length > 0 && (
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Portfolio Health Summary
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="text-center">
              <div className={`text-2xl font-bold ${
                diversificationScore <= 20
                  ? 'text-red-500 dark:text-red-400'
                  : diversificationScore <= 60
                  ? 'text-amber-500 dark:text-amber-400'
                  : 'text-green-600 dark:text-green-400'
              }`}>
                {diversificationScore}%
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Diversification Score
              </div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                {Math.max(0, (portfolioMetrics.totalWeight - 1) * 100).toFixed(1)}%
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Weight Drift
              </div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">
                {sectorData.length}
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Sectors Covered
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}