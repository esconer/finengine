/**
 * Risk Contribution Page
 * Euler decomposition of portfolio risk per position + CVaR tail attribution
 */

'use client';

import React, { useState, useEffect } from 'react';
import { MetricCard } from '@/components/ui/MetricCard';
import { analyticsApi } from '@/lib/api';
import {
  PieChart,
  AlertTriangle,
  RefreshCw,
  Layers,
  Crosshair,
  BarChart3,
  Activity,
} from 'lucide-react';

interface RiskContributionData {
  window: { start: string; end: string };
  positions: {
    volatility: Record<string, number>;
    cvar_tail: Record<string, number>;
  };
  sector_rollup: {
    volatility: Record<string, number>;
    cvar: Record<string, number>;
  };
  portfolio_volatility_annualized: number;
  portfolio_var_95_daily: number;
  portfolio_cvar_95_daily: number | null;
  methodology: string;
}

function ContributionBars({
  entries,
  colorClass,
}: {
  entries: [string, number][];
  colorClass: string;
}) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400">
        Not enough tail observations to attribute this model.
      </p>
    );
  }
  const max = Math.max(...entries.map(([, v]) => v), 0.000001);
  return (
    <div className="space-y-4">
      {entries.map(([ticker, share]) => (
        <div key={ticker} className="flex items-center justify-between">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300 w-24 truncate">
            {ticker}
          </span>
          <div className="flex-1 mx-3">
            <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5">
              <div
                className={`h-2.5 rounded-full ${colorClass} transition-all duration-500`}
                style={{ width: `${(share / max) * 100}%` }}
              />
            </div>
          </div>
          <span className="text-sm font-semibold text-gray-900 dark:text-white w-16 text-right tabular-nums">
            {(share * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
}

export default function RiskContributionPage() {
  const [data, setData] = useState<RiskContributionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRiskContribution = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await analyticsApi.getRiskContribution();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load risk contribution data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRiskContribution();
  }, []);

  const volEntries = data
    ? (Object.entries(data.positions.volatility) as [string, number][]).sort(
        ([, a], [, b]) => b - a
      )
    : [];
  const cvarEntries = data
    ? (Object.entries(data.positions.cvar_tail) as [string, number][]).sort(
        ([, a], [, b]) => b - a
      )
    : [];
  const sectorEntries = data
    ? (Object.entries(data.sector_rollup.volatility) as [string, number][]).sort(
        ([, a], [, b]) => b - a
      )
    : [];

  const topDriver = volEntries[0];
  const fmtPct = (v: number | null | undefined, decimals = 2) =>
    v === null || v === undefined || Number.isNaN(v)
      ? 'N/A'
      : `${(v * 100).toFixed(decimals)}%`;

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-orange-600 to-rose-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Risk Contribution</h1>
            <p className="text-orange-100">
              Which positions actually drive your risk — not just which are biggest
            </p>
            {data && (
              <div className="flex items-center mt-2 space-x-4">
                <div className="text-orange-200 text-sm">
                  Window: {data.window.start} → {data.window.end}
                </div>
              </div>
            )}
          </div>
          <div className="hidden md:flex items-center space-x-2">
            <button
              onClick={fetchRiskContribution}
              disabled={loading}
              className="bg-white/20 hover:bg-white/30 rounded-lg p-2 transition-colors"
              aria-label="Refresh risk contribution"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <PieChart className="w-16 h-16 text-orange-200" />
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 mr-2" />
            <h3 className="text-red-800 dark:text-red-300 font-medium">
              Could not decompose portfolio risk
            </h3>
          </div>
          <p className="text-red-700 dark:text-red-400 text-sm mt-1">{error}</p>
          <button
            onClick={fetchRiskContribution}
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
            <h3 className="text-blue-800 dark:text-blue-300 font-medium">
              Decomposing portfolio risk...
            </h3>
          </div>
          <p className="text-blue-700 dark:text-blue-400 text-sm mt-1">
            Running the exact Euler decomposition over one year of co-movements
          </p>
        </div>
      )}

      {!loading && !error && data && (
        <>
          {/* Portfolio-Level Numbers */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <MetricCard
              title="Portfolio Volatility (ann.)"
              value={fmtPct(data.portfolio_volatility_annualized)}
              icon={Activity}
              loading={loading}
            />
            <MetricCard
              title="Daily VaR 95%"
              value={fmtPct(data.portfolio_var_95_daily)}
              icon={Crosshair}
              loading={loading}
            />
            <MetricCard
              title="Daily CVaR 95%"
              value={
                data.portfolio_cvar_95_daily === null
                  ? 'N/A'
                  : fmtPct(data.portfolio_cvar_95_daily)
              }
              icon={Layers}
              loading={loading}
            />
            <MetricCard
              title="Top Risk Driver"
              value={topDriver ? `${topDriver[0]} · ${(topDriver[1] * 100).toFixed(0)}%` : 'N/A'}
              icon={BarChart3}
              loading={loading}
            />
          </div>

          {/* Position Contributions */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">
                Share of Portfolio Volatility
              </h3>
              <ContributionBars entries={volEntries} colorClass="bg-orange-500" />
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">
                Share of Tail Losses (CVaR)
              </h3>
              <ContributionBars entries={cvarEntries} colorClass="bg-rose-500" />
            </div>
          </div>

          {/* Sector Rollup */}
          {sectorEntries.length > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">
                Volatility Contribution by Sector
              </h3>
              <ContributionBars entries={sectorEntries} colorClass="bg-amber-500" />
            </div>
          )}

          {/* Divergence Insight */}
          {volEntries.length > 0 && cvarEntries.length > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">
                What This Tells You
              </h3>
              {(() => {
                const tailHeavier = [...volEntries]
                  .map(([t, v]) => ({
                    ticker: t,
                    diff: (data.positions.cvar_tail[t] ?? 0) - v,
                  }))
                  .sort((a, b) => b.diff - a.diff)[0];
                if (!tailHeavier || Math.abs(tailHeavier.diff) < 0.05) {
                  return (
                    <p className="text-sm text-gray-600 dark:text-gray-400">
                      Volatility shares and tail-loss shares line up closely — your day-to-day
                      risk drivers are also your crisis drivers.
                    </p>
                  );
                }
                return (
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    On the worst days,{' '}
                    <span className="font-semibold text-gray-900 dark:text-white">
                      {tailHeavier.ticker}
                    </span>{' '}
                    contributes{' '}
                    <span className="font-semibold text-rose-600 dark:text-rose-400 tabular-nums">
                      {(Math.abs(tailHeavier.diff) * 100).toFixed(0)}%
                    </span>{' '}
                    more of your losses than it does of everyday volatility — its crashes are
                    worse than its usual moves suggest.
                  </p>
                );
              })()}
            </div>
          )}

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
