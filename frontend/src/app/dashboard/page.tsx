'use client';

import React, { useState, useEffect, useMemo, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
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
  Download,
  Radar,
  PieChart
} from 'lucide-react';

const REGIME_CHIP: Record<string, string> = {
  calm: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300',
  bull: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
  crisis: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300'
};

import { PortfolioPosition } from '@/types';

// Relative-time formatter matching Header.tsx so every page reads the same.
function formatLastUpdated(timestamp: string | null) {
  if (!timestamp) return 'Never';

  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;

  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  return date.toLocaleDateString();
}

export default function DashboardSummary() {
  const router = useRouter();
  const { positions, fetchPortfolio, isLoading, error, totalValue } = usePortfolioStore();
  const { lastUpdated, updateLastUpdated, liveDataMode } = useUIStore();
  const [showAddModal, setShowAddModal] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const { data: analyticsData, loading: analyticsLoading, refresh: refreshAnalytics } = usePortfolioAnalytics();
  const { performanceData, loading: performanceLoading } = usePerformanceData(90);
  const sectorData = useSectorAllocation();
  const [regimeInfo, setRegimeInfo] = useState<{ current_regime: string; stability_pct: number } | null>(null);
  const [riskDrivers, setRiskDrivers] = useState<[string, number][] | null>(null);
  const supplementaryRequestRef = useRef<Promise<{
    regime: { current_regime: string; stability_pct: number } | null;
    risk: Record<string, any> | null;
  }> | null>(null);

  useEffect(() => {
    fetchPortfolio();
  }, [fetchPortfolio]);

  // Supplementary widgets: regime + risk drivers load quietly and never block
  // the page. Coalesce the pair so StrictMode/route refreshes do not duplicate
  // the same in-flight requests.
  useEffect(() => {
    let mounted = true;
    if (!supplementaryRequestRef.current) {
      supplementaryRequestRef.current = Promise.allSettled([
        analyticsApi.getRegime({ with_portfolio: false }),
        analyticsApi.getRiskContribution(),
      ])
        .then(([regimeResult, riskResult]) => ({
          regime: regimeResult.status === 'fulfilled' ? regimeResult.value : null,
          risk: riskResult.status === 'fulfilled' ? riskResult.value : null,
        }))
        .finally(() => {
          supplementaryRequestRef.current = null;
        });
    }

    void supplementaryRequestRef.current.then(({ regime, risk }) => {
      if (!mounted) return;
      if (regime?.current_regime) {
        setRegimeInfo(regime);
      } else {
        setRegimeInfo(null);
      }
      if (risk) {
        const entries = Object.entries(risk.positions?.volatility ?? {}) as [string, number][];
        entries.sort(([, a], [, b]) => b - a);
        setRiskDrivers(entries.slice(0, 3));
      } else {
        setRiskDrivers(null);
      }
    });

    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (!isLoading && !error && positions.length > 0) {
      updateLastUpdated();
    }
  }, [isLoading, error, positions.length, updateLastUpdated]);

  // Stamp the shared store clock when fresh analytics arrive, like the
  // realized-risk / forecast-risk pages do — the header reads this clock.
  useEffect(() => {
    if (analyticsData.summary) {
      updateLastUpdated();
    }
  }, [analyticsData.summary, updateLastUpdated]);

  // The concentration endpoint owns the canonical base-currency score. Do not
  // recompute it from native position values mixed with a converted total.
  const diversificationScore = useMemo<number | null>(() => {
    if (positions.length === 0) return null;
    if (positions.length === 1) return 0;
    const canonical = analyticsData.concentration?.diversification_score;
    return typeof canonical === 'number' && Number.isFinite(canonical)
      ? canonical
      : null;
  }, [positions.length, analyticsData.concentration]);

  const totalCost = useMemo(() => {
    return positions.reduce((sum, p) => {
      const baseCost = p.total_cost_base;
      if (typeof baseCost === 'number' && Number.isFinite(baseCost)) {
        return sum + baseCost;
      }
      const q = p.quantity || 0;
      const baseBuyPrice = p.buy_price_base;
      if (q > 0 && typeof baseBuyPrice === 'number' && Number.isFinite(baseBuyPrice)) {
        return sum + q * baseBuyPrice;
      }
      // Never mix a legacy native cost into a base-currency total.
      return sum;
    }, 0);
  }, [positions]);

  // Calculate enhanced portfolio metrics
  const portfolioMetrics = useMemo(() => {
    const totalGainLoss = (totalValue || 0) - totalCost;
    const totalGainLossPct = totalCost > 0 ? (totalGainLoss / totalCost) * 100 : 0;
    return {
      totalValue: totalValue || 0,
      totalGainLoss,
      totalGainLossPct,
      positionsCount: positions.length,
      totalWeight: positions.reduce((sum, pos) => sum + pos.weight, 0),
      averageWeight: positions.length > 0 ? (100 / positions.length) : 0,
      topSector: sectorData.length > 0 ? sectorData[0]?.name || 'N/A' : 'N/A',
      riskScore: analyticsData.riskScore?.overall_score ?? null,
      volatility: analyticsData.summary?.realized_volatility ?? null,
      sharpeRatio: analyticsData.summary?.sharpe_ratio ?? null,
      maxDrawdown: analyticsData.summary?.max_drawdown ?? null,
      diversificationScore,
    };
  }, [positions, totalValue, sectorData, totalCost, analyticsData, diversificationScore]);

  // Phase 4: the Ann Vol card reads full-history asset vol (unmasked), so it
  // never N/A-gates on intersection length. Falls back to holding-window
  // realized vol for older summary payloads without the field.
  const summaryAny = analyticsData.summary as any;
  const instrumentVol: number | null = summaryAny?.instrument_volatility ?? null;
  const instrumentVolDays: number | null = summaryAny?.instrument_volatility_days ?? null;
  const volCardValue = instrumentVol ?? portfolioMetrics.volatility;

  // DataTable columns with enhanced functionality
  const positionColumns = useMemo(() => [
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
        const baseValue = typeof data.market_value_base === 'number'
          ? data.market_value_base
          : (typeof data.current_value_base === 'number' ? data.current_value_base : null);
        const liveWeight = (totalValue && totalValue > 0 && typeof baseValue === 'number')
          ? (baseValue / totalValue)
          : data.weight;
        if (liveWeight == null || !Number.isFinite(liveWeight)) {
          return <div className="text-gray-500">N/A</div>;
        }
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
        const baseValue = typeof data.market_value_base === 'number'
          ? data.market_value_base
          : (typeof data.current_value_base === 'number' ? data.current_value_base : null);
        return (
          <div className="text-gray-900 dark:text-white">
            {baseValue !== null ? `₹${baseValue.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : 'N/A'}
          </div>
        );
      },
    },
    {
      header: 'Price',
      accessorKey: 'last_price' as keyof PortfolioPosition,
      cell: ({ row }: any) => {
        const data = row.original || row;
        const basePrice = typeof data.last_price_base === 'number'
          ? data.last_price_base
          : null;
        return (
          <div className="text-gray-900 dark:text-white">
            {basePrice !== null ? `₹${basePrice.toFixed(2)}` : 'N/A'}
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
  ], [totalValue]);

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
      setExportError(null);
      const csvData = await portfolioApi.exportCSV();
      if (typeof csvData !== 'string' || csvData.trim().length === 0) {
        throw new Error('Export returned an empty file');
      }

      const blob = new Blob([csvData], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `portfolio-${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (error: any) {
      console.error('Failed to export CSV:', error);
      setExportError(error?.message || 'Failed to export portfolio CSV');
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
              Portfolio analytics and risk management
            </p>
            <div className="flex items-center mt-2 space-x-4">
              <div className={`flex items-center ${liveDataMode ? 'text-green-300' : 'text-blue-200'}`}>
                <div className={`w-2 h-2 rounded-full mr-2 ${liveDataMode ? 'bg-green-400' : 'bg-blue-300'}`}></div>
                <span className="text-sm">{liveDataMode ? 'Live Data Active' : 'Live Data Off'}</span>
              </div>
              {lastUpdated && (
                <div className="text-blue-200 text-sm">
                  Last updated: {formatLastUpdated(lastUpdated)}
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

      {/* Key Portfolio Summary Metrics (Deduplicated) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Total Portfolio Value"
          value={portfolioMetrics.totalValue}
          prefix="₹"
          icon={TrendingUp}
          loading={isOverallLoading}
        />
        <div>
          <MetricCard
            title="Unrealized P&L"
            value={`${portfolioMetrics.totalGainLoss >= 0 ? '+' : '-'}₹${Math.abs(portfolioMetrics.totalGainLoss).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            change={totalCost > 0 ? portfolioMetrics.totalGainLossPct : undefined}
            changeType={portfolioMetrics.totalGainLoss >= 0 ? 'positive' : 'negative'}
            icon={portfolioMetrics.totalGainLoss >= 0 ? TrendingUp : TrendingDown}
            loading={isOverallLoading}
          />
          {!isOverallLoading && positions.length > 0 && (
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">Uses current live FX for mixed-currency positions.</p>
          )}
        </div>
        <div>
          <MetricCard
            title="Annual Volatility"
            value={volCardValue === null ? 'N/A' : `${(volCardValue * 100).toFixed(2)}%`}
            icon={Activity}
            loading={analyticsLoading}
          />
          {!analyticsLoading && volCardValue !== null && instrumentVol !== null && (
            <p data-testid="vol-caption" className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              full-history asset vol{instrumentVolDays !== null ? ` · ${instrumentVolDays}d` : ''}
            </p>
          )}
          {!analyticsLoading && volCardValue === null && (
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              Holding-window realized vol (√252 annualized) — needs ≥ 30 trading days
            </p>
          )}
        </div>
        <MetricCard
          title="Diversification Score"
          value={portfolioMetrics.diversificationScore === null
            ? 'N/A'
            : `${portfolioMetrics.diversificationScore.toFixed(1)}%`}
          icon={Shield}
          loading={analyticsLoading}
        />
      </div>

      {/* Market Regime + Top Risk Drivers */}
      {(regimeInfo || (riskDrivers && riskDrivers.length > 0)) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {regimeInfo && (
            <Link
              href="/dashboard/regime"
              className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-5 border border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
                    Market Regime
                  </p>
                  <div className="flex items-center mt-1">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                        REGIME_CHIP[regimeInfo.current_regime] ??
                        'bg-gray-100 text-gray-800'
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
                    <span className="text-xs font-medium text-gray-700 dark:text-gray-300 w-24 truncate">
                      {ticker}
                    </span>
                    <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="h-1.5 rounded-full bg-orange-500 transition-all duration-300"
                        style={{ width: `${Math.min(100, Math.max(0, share * 100))}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-600 dark:text-gray-400 w-12 text-right tabular-nums font-mono">
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
          var_95: analyticsData.realizedRisk?.portfolio?.var_95 ?? null,
          cvar_95: analyticsData.realizedRisk?.portfolio?.cvar_95 ?? null,
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
          currency="INR"
        />
        <SectorAllocationChart
          data={sectorData}
          loading={isOverallLoading}
        />
      </div>

      {/* Portfolio Positions Table with Management */}
      <div>
        {exportError && (
          <div
            data-testid="export-error-banner"
            className="mb-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3"
          >
            <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 mt-0.5 shrink-0" />
            <div className="text-sm text-red-800 dark:text-red-300 flex-1">
              <span className="font-semibold">CSV export failed:</span> {exportError}
            </div>
            <button
              type="button"
              onClick={() => setExportError(null)}
              className="text-xs font-semibold text-red-700 dark:text-red-300 hover:underline shrink-0"
            >
              Dismiss
            </button>
          </div>
        )}
        <DataTable
          data={positions}
          columns={positionColumns}
          loading={isOverallLoading}
          searchablePlaceholder="Search positions..."
          exportable={false}
          actions={
            <div className="flex items-center space-x-2">
              <button
                onClick={handleExportCSV}
                className="flex items-center px-3 py-2 text-sm bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
              >
                <Download className="w-4 h-4 mr-1" />
                Export
              </button>
              <button
                onClick={() => setShowAddModal(true)}
                className="flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
              >
                <TrendingUp className="w-4 h-4 mr-2" />
                Add Position
              </button>
            </div>
          }
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
                diversificationScore === null
                  ? 'text-gray-500 dark:text-gray-400'
                  : diversificationScore <= 20
                  ? 'text-red-500 dark:text-red-400'
                  : diversificationScore <= 60
                  ? 'text-amber-500 dark:text-amber-400'
                  : 'text-green-600 dark:text-green-400'
              }`}>
                {diversificationScore === null ? 'N/A' : `${diversificationScore.toFixed(1)}%`}
              </div>
              <div className="text-sm text-gray-600 dark:text-gray-400">
                Diversification Score
              </div>
            </div>
            <div className="text-center">
              <div className={`text-2xl font-bold ${
                ((portfolioMetrics.totalWeight - 1) * 100) >= 0
                  ? 'text-blue-600 dark:text-blue-400'
                  : 'text-amber-500 dark:text-amber-400'
              }`}>
                {((portfolioMetrics.totalWeight - 1) * 100).toFixed(1)}%
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