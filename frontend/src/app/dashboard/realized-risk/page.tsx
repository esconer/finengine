/**
 * Realized Risk Page - Historical risk metrics and performance analysis
 */

'use client';

import React, { useState, useEffect } from 'react';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import { usePortfolioAnalytics, usePerformanceData } from '@/hooks/useAnalytics';
import { usePortfolioStore, useUIStore } from '@/lib/store';
import { CSVExporter } from '@/lib/export';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import {
  TrendingDown,
  TrendingUp,
  Activity,
  AlertTriangle,
  BarChart3,
  Download,
  RefreshCw,
  Shield,
  Target,
} from 'lucide-react';

export default function RealizedRiskPage() {
  const [dateRange, setDateRange] = useState({
    start: '',
    end: '',
  });
  const [loading, setLoading] = useState(false);
  const [positionData, setPositionData] = useState<any[]>([]);

  const { data: analyticsData, loading: analyticsLoading, refresh } = usePortfolioAnalytics();
  const { performanceData } = usePerformanceData(252);
  const { positions } = usePortfolioStore();
  const { updateLastUpdated } = useUIStore();

  const realizedRisk = analyticsData.realizedRisk;

  useEffect(() => {
    if (analyticsData.realizedRisk) {
      updateLastUpdated();
    }
  }, [analyticsData.realizedRisk, updateLastUpdated]);

  // Compute live rolling volatility and underwater drawdown series from performance data
  const { drawdownSeries, rollingVolSeries } = React.useMemo(() => {
    if (!performanceData || performanceData.length < 2) {
      return { drawdownSeries: [], rollingVolSeries: [] };
    }
    let peak = -Infinity;
    const dd: { date: string; drawdown: number }[] = [];
    const returns: number[] = [];
    const vol: { date: string; volatility: number }[] = [];

    for (let i = 0; i < performanceData.length; i++) {
      const p = performanceData[i];
      const val = p.portfolio_value || 0;
      if (val > peak) peak = val;
      const drawdown = peak > 0 ? (val - peak) / peak : 0;
      dd.push({
        date: p.date,
        drawdown: Number((drawdown * 100).toFixed(2)),
      });

      if (i > 0) {
        const prev = performanceData[i - 1].portfolio_value || 1;
        returns.push((val - prev) / prev);
      }
      if (returns.length >= 10) {
        const windowRet = returns.slice(-21);
        const mean = windowRet.reduce((a, b) => a + b, 0) / windowRet.length;
        const variance =
          windowRet.reduce((sum, r) => sum + Math.pow(r - mean, 2), 0) /
          Math.max(1, windowRet.length - 1);
        const annVol = Math.sqrt(variance * 252) * 100;
        vol.push({
          date: p.date,
          volatility: Number(annVol.toFixed(2)),
        });
      }
    }
    return { drawdownSeries: dd, rollingVolSeries: vol };
  }, [performanceData]);

  // Generate position risk data for table
  useEffect(() => {
    if (realizedRisk?.positions) {
      const positionsList = Object.entries(realizedRisk.positions).map(([ticker, data]: [string, any]) => ({
        ticker,
        ...data,
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

  const handleRefresh = async () => {
    setLoading(true);
    await refresh();
    updateLastUpdated();
    setLoading(false);
  };

  const handleExportCSV = () => {
    if (positionData.length > 0) {
      CSVExporter.exportToCSV(positionData, 'realized_risk_positions');
    }
  };

  // Format metrics for display
  const formatPercentage = (value: number | undefined | null, decimals = 2) => {
    if (value === undefined || value === null) return 'N/A';
    return `${(value * 100).toFixed(decimals)}%`;
  };

  const formatRatio = (value: number | undefined | null, decimals = 2) => {
    if (value === undefined || value === null || Number.isNaN(value)) return 'N/A';
    return value.toFixed(decimals);
  };

  // DataTable columns
  const positionColumns = [
    {
      header: 'Ticker',
      accessorKey: 'ticker',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="flex items-center space-x-2">
            <span className="font-semibold text-gray-900 dark:text-white">
              {data.ticker}
            </span>
            {data.is_limited_history && (
              <span
                className="inline-flex items-center text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-700/50"
                title={data.history_warning || `Limited history: ${data.data_points} trading days`}
              >
                ⚠️ &lt;30d history
              </span>
            )}
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
          <div className="font-mono text-gray-900 dark:text-white">
            {formatPercentage(data.weight)}
          </div>
        );
      },
    },
    {
      header: 'Annual Return',
      accessorKey: 'annual_return',
      cell: ({ row }: any) => {
        const data = row.original || row;
        const isPositive = data.annual_return >= 0;
        return (
          <div className={`font-mono ${isPositive ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
            {isPositive ? '+' : ''}{formatPercentage(data.annual_return)}
          </div>
        );
      },
    },
    {
      header: 'Volatility',
      accessorKey: 'annual_volatility',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="font-mono text-gray-900 dark:text-white">
            {formatPercentage(data.annual_volatility)}
          </div>
        );
      },
    },
    {
      header: 'Sharpe Ratio',
      accessorKey: 'sharpe_ratio',
      cell: ({ row }: any) => {
        const data = row.original || row;
        if (data.is_limited_history) {
          return (
            <div className="font-mono text-xs text-amber-600 dark:text-amber-400" title="Insufficient data (<30d) for annualized Sharpe ratio">
              -- <span className="text-[10px] text-gray-400">(Limited)</span>
            </div>
          );
        }
        return (
          <div className={`font-mono font-medium ${
            data.sharpe_ratio >= 1 ? 'text-green-600 dark:text-green-400' :
            data.sharpe_ratio >= 0 ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-600 dark:text-red-400'
          }`}>
            {formatRatio(data.sharpe_ratio)}
          </div>
        );
      },
    },
    {
      header: 'Max Drawdown',
      accessorKey: 'max_drawdown',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="font-mono text-red-600 dark:text-red-400">
            {formatPercentage(data.max_drawdown)}
          </div>
        );
      },
    },
    {
      header: 'VaR (95%)',
      accessorKey: 'var_95',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="font-mono text-red-600 dark:text-red-400">
            {formatPercentage(data.var_95)}
          </div>
        );
      },
    },
  ];

  const hasData = Boolean(realizedRisk?.portfolio);

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-red-600 to-orange-600 rounded-lg p-6 text-white shadow-lg">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Realized Risk</h1>
            <p className="text-red-100">
              Historical risk metrics and portfolio performance analysis
            </p>
            <div className="flex flex-wrap items-center mt-3 gap-4 text-xs font-mono text-red-100">
              <span className="bg-white/10 px-2.5 py-1 rounded">
                Universe: {positions.length} active positions
              </span>
              <span className="bg-white/10 px-2.5 py-1 rounded">
                Period: {dateRange.start || '252d lookback'} to {dateRange.end || 'Latest'}
              </span>
              {realizedRisk?.data_range && (
                <span className="bg-white/10 px-2.5 py-1 rounded">
                  Data Span: {realizedRisk.data_range.start} → {realizedRisk.data_range.end}
                </span>
              )}
            </div>
          </div>
          <div className="hidden md:flex items-center space-x-3">
            <button
              onClick={handleRefresh}
              disabled={loading || analyticsLoading}
              className="bg-white/20 hover:bg-white/30 rounded-lg p-2.5 transition-colors"
              title="Refresh Realized Risk"
            >
              <RefreshCw className={`w-5 h-5 ${loading || analyticsLoading ? 'animate-spin' : ''}`} />
            </button>
            <TrendingDown className="w-12 h-12 text-red-200" />
          </div>
        </div>
      </div>

      {/* Insufficient History Warning Banner */}
      {realizedRisk?.warnings && realizedRisk.warnings.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700/60 rounded-xl p-4 flex items-start space-x-3 shadow-sm">
          <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <h4 className="font-semibold text-amber-900 dark:text-amber-200">
              Data Quality Notice: Limited Historical Depth Detected ({realizedRisk.warnings.length} Instrument{realizedRisk.warnings.length > 1 ? 's' : ''})
            </h4>
            <div className="text-amber-800 dark:text-amber-300 mt-1 space-y-1">
              {realizedRisk.warnings.map((w: any, idx: number) => (
                <p key={idx}>
                  • <strong className="font-mono">{w.ticker}</strong>: {w.message}
                </p>
              ))}
              <p className="text-xs text-amber-700 dark:text-amber-400 mt-2">
                💡 <em>Tip:</em> For continuous multi-year historical risk metrics and backtesting on Nifty 50, use continuous ETF benchmarks like <code className="font-bold font-mono bg-amber-100 dark:bg-amber-900/50 px-1 py-0.5 rounded">NIFTYBEES.NS</code> or <code className="font-bold font-mono bg-amber-100 dark:bg-amber-900/50 px-1 py-0.5 rounded">SETFNIF50.NS</code> in your portfolio.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Row 1: Return & Risk-Adjusted Ratios */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Annual Return"
          value={hasData && realizedRisk?.portfolio?.annual_return != null ? formatPercentage(realizedRisk.portfolio.annual_return) : 'N/A'}
          icon={TrendingUp}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Annual Volatility"
          value={hasData && realizedRisk?.portfolio?.annual_volatility != null ? formatPercentage(realizedRisk.portfolio.annual_volatility) : 'N/A'}
          icon={Activity}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Sharpe Ratio"
          value={hasData && realizedRisk?.portfolio?.sharpe_ratio != null ? formatRatio(realizedRisk.portfolio.sharpe_ratio) : 'N/A'}
          icon={Target}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Sortino Ratio"
          value={hasData && realizedRisk?.portfolio?.sortino_ratio != null ? formatRatio(realizedRisk.portfolio.sortino_ratio) : 'N/A'}
          icon={BarChart3}
          loading={analyticsLoading}
        />
      </div>

      {/* Row 2: Tail Risk & Downside Distribution */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Max Drawdown"
          value={hasData && realizedRisk?.portfolio?.max_drawdown !== undefined ? formatPercentage(realizedRisk.portfolio.max_drawdown) : 'N/A'}
          icon={TrendingDown}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Value at Risk (95% Daily)"
          value={hasData && realizedRisk?.portfolio?.var_95 !== undefined ? formatPercentage(realizedRisk.portfolio.var_95) : 'N/A'}
          icon={AlertTriangle}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Conditional VaR (95% Daily)"
          value={hasData && realizedRisk?.portfolio?.cvar_95 !== undefined ? formatPercentage(realizedRisk.portfolio.cvar_95) : 'N/A'}
          icon={Shield}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Hit Ratio (% Positive Days)"
          value={hasData && realizedRisk?.portfolio?.hit_ratio !== undefined ? formatPercentage(realizedRisk.portfolio.hit_ratio) : 'N/A'}
          icon={Activity}
          loading={analyticsLoading}
        />
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Rolling 21-Day Volatility (%)
              </h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">Annualized historical realized volatility trend</p>
            </div>
            <Activity className="w-5 h-5 text-blue-500" />
          </div>
          <div className="h-64">
            {rollingVolSeries.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rollingVolSeries}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="%" domain={['auto', 'auto']} />
                  <Tooltip formatter={(value: any) => [`${value}%`, 'Rolling Volatility']} />
                  <Line type="monotone" dataKey="volatility" stroke="#3b82f6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-gray-400 text-sm">
                Loading volatility history...
              </div>
            )}
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Underwater Drawdown (%)
              </h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">Peak-to-trough portfolio wealth drawdown</p>
            </div>
            <TrendingDown className="w-5 h-5 text-red-500" />
          </div>
          <div className="h-64">
            {drawdownSeries.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={drawdownSeries}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="%" domain={['auto', 0]} />
                  <Tooltip formatter={(value: any) => [`${value}%`, 'Drawdown']} />
                  <Area type="monotone" dataKey="drawdown" stroke="#ef4444" fill="#ef4444" fillOpacity={0.2} strokeWidth={1.5} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-gray-400 text-sm">
                Loading drawdown history...
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Position-Level Risk Analysis */}
      <DataTable
        title="Position-Level Risk Analysis"
        data={positionData}
        columns={positionColumns}
        loading={analyticsLoading}
        searchablePlaceholder="Search positions..."
        exportable={false}
        actions={
          <button
            onClick={handleExportCSV}
            className="flex items-center px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-md hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
          >
            <Download className="w-3.5 h-3.5 mr-1.5" />
            Export CSV
          </button>
        }
      />

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
                <h4 className="font-medium text-gray-900 dark:text-white">Drawdown Vulnerability</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Portfolio experienced a peak-to-trough drawdown of {formatPercentage(realizedRisk.portfolio.max_drawdown)} over the 252-day lookback window.
                </p>
              </div>
            </div>
          )}

          {realizedRisk?.portfolio?.sharpe_ratio && realizedRisk.portfolio.sharpe_ratio > 0.5 && (
            <div className="flex items-start space-x-3">
              <TrendingUp className="w-5 h-5 text-green-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Risk-Adjusted Efficiency</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Sharpe ratio of {formatRatio(realizedRisk.portfolio.sharpe_ratio)} and Sortino ratio of {formatRatio(realizedRisk.portfolio.sortino_ratio)} demonstrate healthy excess return relative to downside volatility.
                </p>
              </div>
            </div>
          )}

          <div className="flex items-start space-x-3">
            <BarChart3 className="w-5 h-5 text-blue-600 mt-0.5" />
            <div>
              <h4 className="font-medium text-gray-900 dark:text-white">Analysis Methodology</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {realizedRisk?.methodology || 'Risk metrics calculated using empirical daily returns, parametric variance-covariance matrices, and historical drawdown series.'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}