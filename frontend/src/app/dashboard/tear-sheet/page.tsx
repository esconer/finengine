/**
 * Performance Tear-Sheet Page
 * Portfolio vs NIFTY 50 via the quantstats suite on real holdings
 */

'use client';

import React, { useState, useEffect } from 'react';
import { MetricCard } from '@/components/ui/MetricCard';
import { analyticsApi } from '@/lib/api';
import {
  Newspaper,
  AlertTriangle,
  RefreshCw,
  TrendingUp,
  Activity,
  CalendarDays,
  Scale,
} from 'lucide-react';

interface TearSheetData {
  window: { start: string; end: string };
  holdings: Record<string, number>;
  metrics: Record<string, number | null>;
  relative_vs_nifty: Record<string, number | null>;
  monthly_returns: Record<string, Record<string, number>>;
  underwater: { date: string; drawdown: number }[];
  methodology: string;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export default function TearSheetPage() {
  const [data, setData] = useState<TearSheetData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTearSheet = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await analyticsApi.getTearSheet();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tear-sheet data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTearSheet();
  }, []);

  const fmt = (value: number | null | undefined, decimals = 2, suffix = '') => {
    if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
    return `${(value * 100).toFixed(decimals)}${suffix}`;
  };

  const fmtRatio = (value: number | null | undefined, decimals = 2) => {
    if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
    return value.toFixed(decimals);
  };

  const heatColor = (value: number): string => {
    // Cap intensity at ±8% monthly move so typical months stay legible
    const capped = Math.max(-0.08, Math.min(0.08, value));
    if (capped >= 0) return `rgba(16, 185, 129, ${0.15 + (capped / 0.08) * 0.75})`;
    return `rgba(239, 68, 68, ${0.15 + (-capped / 0.08) * 0.75})`;
  };

  const years = data ? Object.keys(data.monthly_returns).sort() : [];

  const drawdownPoints = data?.underwater ?? [];
  const worstDrawdown = drawdownPoints.length
    ? Math.min(...drawdownPoints.map((p) => p.drawdown))
    : null;

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-emerald-600 to-teal-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Performance Tear-Sheet</h1>
            <p className="text-emerald-100">
              Your portfolio against NIFTY 50 · full quantstats suite
            </p>
            {data && (
              <div className="flex items-center mt-2 space-x-4">
                <div className="text-emerald-200 text-sm">
                  Window: {data.window.start} → {data.window.end}
                </div>
                <div className="text-emerald-200 text-sm">
                  Holdings: {Object.keys(data.holdings).length}
                </div>
              </div>
            )}
          </div>
          <div className="hidden md:flex items-center space-x-2">
            <button
              onClick={fetchTearSheet}
              disabled={loading}
              className="bg-white/20 hover:bg-white/30 rounded-lg p-2 transition-colors"
              aria-label="Refresh tear-sheet"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <Newspaper className="w-16 h-16 text-emerald-200" />
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 mr-2" />
            <h3 className="text-red-800 dark:text-red-300 font-medium">Could not build tear-sheet</h3>
          </div>
          <p className="text-red-700 dark:text-red-400 text-sm mt-1">{error}</p>
          <button
            onClick={fetchTearSheet}
            className="mt-2 px-3 py-1 bg-red-100 dark:bg-red-800 text-red-700 dark:text-red-300 rounded text-sm hover:bg-red-200 dark:hover:bg-red-700 transition-colors"
          >
            Try Again
          </button>
        </div>
      )}

      {/* Loading State */}
      {loading && !data && (
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
          <div className="flex items-center">
            <RefreshCw className="w-5 h-5 text-blue-600 dark:text-blue-400 mr-2 animate-spin" />
            <h3 className="text-blue-800 dark:text-blue-300 font-medium">Computing tear-sheet...</h3>
          </div>
          <p className="text-blue-700 dark:text-blue-400 text-sm mt-1">
            Running the quantstats suite over one year of cached closes
          </p>
        </div>
      )}

      {/* Headline Metrics */}
      {!loading && !error && data && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <MetricCard
              title="Total Return"
              value={fmt(data.metrics.total_return, 2, '%')}
              icon={TrendingUp}
              loading={loading}
            />
            <MetricCard
              title="CAGR"
              value={fmt(data.metrics.cagr, 2, '%')}
              icon={Activity}
              loading={loading}
            />
            <MetricCard
              title="Sharpe Ratio"
              value={fmtRatio(data.metrics.sharpe)}
              icon={Scale}
              loading={loading}
            />
            <MetricCard
              title="Max Drawdown"
              value={fmt(data.metrics.max_drawdown, 2, '%')}
              icon={AlertTriangle}
              loading={loading}
            />
          </div>

          {/* Relative vs NIFTY */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Against NIFTY 50
            </h3>
            {Object.keys(data.relative_vs_nifty).length === 0 ? (
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Benchmark history unavailable for this window.
              </p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-6">
                {[
                  { label: 'Beta', key: 'beta_vs_nifty', ratio: true },
                  { label: 'Alpha (ann.)', key: 'alpha_annualized', pct: true },
                  { label: 'Portfolio Sharpe', key: null, own: fmtRatio(data.metrics.sharpe) },
                  { label: 'Benchmark Sharpe', key: 'benchmark_sharpe', ratio: true },
                  { label: 'Portfolio Vol', key: null, own: fmt(data.metrics.volatility, 2, '%') },
                  { label: 'Benchmark Vol', key: 'benchmark_volatility', pct: true },
                ].map((item) => (
                  <div key={item.label}>
                    <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
                      {item.label}
                    </p>
                    <p className="text-xl font-semibold text-gray-900 dark:text-white tabular-nums">
                      {item.own !== undefined
                        ? item.own
                        : item.pct
                          ? fmt(data.relative_vs_nifty[item.key!], 2, '%')
                          : fmtRatio(data.relative_vs_nifty[item.key!])}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Monthly Returns Heatmap */}
          {years.length > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 overflow-x-auto">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Monthly Returns
                </h3>
                <CalendarDays className="w-5 h-5 text-gray-500" />
              </div>
              <table className="min-w-full tabular-nums">
                <thead>
                  <tr>
                    <th className="text-left text-xs font-medium text-gray-500 dark:text-gray-400 pb-2 pr-3">
                      Year
                    </th>
                    {MONTHS.map((m) => (
                      <th
                        key={m}
                        className="text-center text-xs font-medium text-gray-500 dark:text-gray-400 pb-2 px-1 min-w-[52px]"
                      >
                        {m}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {years.map((year) => (
                    <tr key={year}>
                      <td className="text-sm font-medium text-gray-700 dark:text-gray-300 pr-3">
                        {year}
                      </td>
                      {MONTHS.map((_, mi) => {
                        const mKey = String(mi + 1);
                        const val = data.monthly_returns[year]?.[mKey] ?? (data.monthly_returns[year] as any)?.[mi + 1] ?? (data.monthly_returns[year] as any)?.[MONTHS[mi]] ?? (data.monthly_returns[year] as any)?.[MONTHS[mi].toUpperCase()];
                        return (
                          <td key={mi} className="px-1 pb-1">
                            {val === undefined ? (
                              <div className="h-8 rounded bg-gray-100 dark:bg-gray-900" />
                            ) : (
                              <div
                                className="h-8 rounded flex items-center justify-center text-xs font-medium text-gray-900 dark:text-gray-950"
                                style={{ backgroundColor: heatColor(val) }}
                                title={`${MONTHS[mi]} ${year}: ${(val * 100).toFixed(2)}%`}
                              >
                                {(val * 100).toFixed(1)}
                              </div>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Underwater + Holdings */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {drawdownPoints.length > 0 && (
              <div className="lg:col-span-2 bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
                <div className="flex items-center justify-between mb-6">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                    Underwater Curve
                  </h3>
                  <span className="text-sm text-red-600 dark:text-red-400 font-medium tabular-nums">
                    Worst: {fmt(worstDrawdown, 2, '%')}
                  </span>
                </div>
                <svg viewBox="0 0 600 120" className="w-full h-28" preserveAspectRatio="none">
                  <path
                    d={`M 0 10 ${drawdownPoints
                      .map((p, i) => {
                        const x = (i / (drawdownPoints.length - 1)) * 600;
                        const depth = Math.min(1, Math.abs(p.drawdown) / Math.abs(worstDrawdown || 1));
                        const y = 10 + depth * 100;
                        return `L ${x.toFixed(1)} ${y.toFixed(1)}`;
                      })
                      .join(' ')} L 600 10 Z`}
                    fill="rgba(239, 68, 68, 0.25)"
                    stroke="rgba(239, 68, 68, 0.9)"
                    strokeWidth="1.5"
                  />
                </svg>
                <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-2 tabular-nums">
                  <span>{drawdownPoints[0].date}</span>
                  <span>{drawdownPoints[drawdownPoints.length - 1].date}</span>
                </div>
              </div>
            )}

            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Weights Used
              </h3>
              <div className="space-y-3">
                {Object.entries(data.holdings).map(([ticker, weight]) => (
                  <div key={ticker} className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                      {ticker}
                    </span>
                    <span className="text-sm text-gray-900 dark:text-white tabular-nums">
                      {(weight * 100).toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Methodology */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
              Methodology
            </h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">{data.methodology}</p>
          </div>
        </>
      )}
    </div>
  );
}
