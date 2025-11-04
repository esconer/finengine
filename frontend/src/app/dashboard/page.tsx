'use client';

import React, { useState, useEffect } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import { PerformanceChart } from '@/components/charts/PerformanceChart';
import { SectorAllocationChart } from '@/components/charts/SectorAllocationChart';
import { RiskMetricsDisplay } from '@/components/charts/RiskMetricsDisplay';
import { AddPositionModalSimple } from '@/components/portfolio/AddPositionModalSimple';
import { usePortfolioStore, useUIStore } from '@/lib/store';
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
  Download
} from 'lucide-react';

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
  const { positions, fetchPortfolio, isLoading, error, totalValue } = usePortfolioStore();
  const { updateLastUpdated } = useUIStore();
  const [showAddModal, setShowAddModal] = useState(false);
  const { data: analyticsData, loading: analyticsLoading, refresh: refreshAnalytics } = usePortfolioAnalytics();
  const { performanceData, loading: performanceLoading } = usePerformanceData(90);
  const sectorData = useSectorAllocation();

  useEffect(() => {
    fetchPortfolio();
  }, [fetchPortfolio]);

  useEffect(() => {
    if (!isLoading && !error && positions.length > 0) {
      updateLastUpdated();
    }
  }, [isLoading, error, positions.length, updateLastUpdated]);

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
        return (
          <div className="text-gray-900 dark:text-white">
            {data.weight ? `${(data.weight * 100).toFixed(2)}%` : '0.00%'}
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
            {data.market_value ? `$${data.market_value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '$0.00'}
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
            {data.last_price ? `$${data.last_price.toFixed(2)}` : '$0.00'}
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
      const response = await fetch('http://localhost:8000/api/v1/portfolio/add', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(positionData),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to add position');
      }

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
          change={2.4}
          changeType="positive"
          loading={isOverallLoading}
        />
        <MetricCard
          title="Number of Positions"
          value={portfolioMetrics.positionsCount}
          icon={Target}
          change={positions.length > 0 ? 1 : 0}
          changeType={positions.length > 0 ? 'positive' : 'neutral'}
          loading={isOverallLoading}
        />
        <MetricCard
          title="Risk Score"
          value={portfolioMetrics.riskScore.toFixed(1)}
          icon={Shield}
          change={portfolioMetrics.riskScore > 0 ? -2.3 : 0}
          changeType={portfolioMetrics.riskScore <= 25 ? 'positive' : 'negative'}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Sharpe Ratio"
          value={portfolioMetrics.sharpeRatio.toFixed(2)}
          icon={TrendingUp}
          change={portfolioMetrics.sharpeRatio > 0 ? 0.15 : 0}
          changeType={portfolioMetrics.sharpeRatio > 1 ? 'positive' : 'negative'}
          loading={analyticsLoading}
        />
      </div>

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
          currency="USD"
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
            onClick={handleRefreshData}
            disabled={isOverallLoading}
            className="p-4 text-left rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-6 h-6 text-blue-600 mb-2 ${isOverallLoading ? 'animate-spin' : ''}`} />
            <div className="text-sm font-medium text-gray-900 dark:text-white">
              Run Analysis
            </div>
          </button>

          <button
            onClick={async () => {
              try {
                const response = await fetch('http://localhost:8000/api/v1/portfolio/rebalance', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ method: 'proportional' })
                });
                if (response.ok) {
                  await fetchPortfolio();
                  alert('Portfolio rebalanced successfully');
                } else {
                  alert('Failed to rebalance portfolio');
                }
              } catch (error) {
                alert('Error rebalancing portfolio');
              }
            }}
            className="p-4 text-left rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <Target className="w-6 h-6 text-purple-600 mb-2" />
            <div className="text-sm font-medium text-gray-900 dark:text-white">
              Rebalance
            </div>
          </button>

          <button
            onClick={() => window.location.href = '/dashboard/stress-testing'}
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
              <div className="text-2xl font-bold text-green-600 dark:text-green-400">
                {((1 - portfolioMetrics.riskScore / 100) * 100).toFixed(0)}%
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