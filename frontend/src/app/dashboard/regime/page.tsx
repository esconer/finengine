/**
 * Market Regime Page
 * HMM classification of NIFTY (calm / volatile / crisis) + portfolio behavior in regime
 */

'use client';

import React, { useState, useEffect } from 'react';
import { MetricCard } from '@/components/ui/MetricCard';
import { analyticsApi } from '@/lib/api';
import {
  Radar,
  AlertTriangle,
  RefreshCw,
  Gauge,
  Waves,
  CalendarRange,
} from 'lucide-react';

interface RegimeData {
  as_of: string;
  current_regime: string;
  stability_pct: number;
  states: {
    regime: string;
    ann_ret: number;
    ann_vol: number;
    historical_days_pct: number;
  }[];
  recent_history: { date: string; regime: string }[];
  observations: number;
  portfolio_in_current_regime?: { days: number; ann_ret: number; ann_vol: number };
}

const REGIME_STYLES: Record<string, { label: string; chip: string; dot: string }> = {
  calm: {
    label: 'Calm',
    chip: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300',
    dot: 'bg-emerald-500',
  },
  volatile: {
    label: 'Volatile',
    chip: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
    dot: 'bg-amber-500',
  },
  crisis: {
    label: 'Crisis',
    chip: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
    dot: 'bg-red-500',
  },
};

function regimeStyle(regime: string) {
  const key = regime.toLowerCase();
  return REGIME_STYLES[key] ?? { label: regime, chip: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200', dot: 'bg-gray-400' };
}

export default function RegimePage() {
  const [data, setData] = useState<RegimeData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRegime = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await analyticsApi.getRegime();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to detect market regime');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRegime();
  }, []);

  const fmtPct = (v: number | null | undefined, decimals = 1) =>
    v === null || v === undefined || Number.isNaN(v)
      ? 'N/A'
      : `${(v * 100).toFixed(decimals)}%`;

  const current = data ? regimeStyle(data.current_regime) : null;

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-sky-600 to-blue-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Market Regime</h1>
            <p className="text-sky-100">
              Hidden-Markov state of NIFTY 50 — calm, volatile, or crisis — and how your
              book behaves inside it
            </p>
            {data && (
              <div className="flex items-center mt-2 space-x-4 text-sm text-sky-200 tabular-nums">
                <span>As of {data.as_of}</span>
                <span>{data.observations} trading days analyzed</span>
              </div>
            )}
          </div>
          <div className="hidden md:flex items-center space-x-2">
            <button
              onClick={fetchRegime}
              disabled={loading}
              className="bg-white/20 hover:bg-white/30 rounded-lg p-2 transition-colors"
              aria-label="Refresh regime"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <Radar className="w-16 h-16 text-sky-200" />
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 mr-2" />
            <h3 className="text-red-800 dark:text-red-300 font-medium">
              Regime detection failed
            </h3>
          </div>
          <p className="text-red-700 dark:text-red-400 text-sm mt-1">{error}</p>
          <button
            onClick={fetchRegime}
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
              Classifying NIFTY regimes...
            </h3>
          </div>
          <p className="text-blue-700 dark:text-blue-400 text-sm mt-1">
            Fitting a three-state hidden Markov model over benchmark returns and volatility
          </p>
        </div>
      )}

      {!loading && !error && data && current && (
        <>
          {/* Current Regime Banner */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <MetricCard title="Current Regime" value={current.label} icon={Radar} />
            <MetricCard
              title="Stability"
              value={`${data.stability_pct.toFixed(1)}%`}
              icon={Gauge}
            />
            <MetricCard title="Benchmark Vol (this regime)" value={
              (() => {
                const s = data.states.find(
                  (st) => st.regime.toLowerCase() === data.current_regime.toLowerCase()
                );
                return s ? fmtPct(s.ann_vol) : 'N/A';
              })()
            } icon={Waves} />
            <MetricCard
              title="Days in Regime (hist.)"
              value={(() => {
                const s = data.states.find(
                  (st) => st.regime.toLowerCase() === data.current_regime.toLowerCase()
                );
                return s ? `${s.historical_days_pct.toFixed(0)}%` : 'N/A';
              })()}
              icon={CalendarRange}
            />
          </div>

          {/* HMM State Table */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="p-4 border-b border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                The Three States the Model Found
              </h3>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full tabular-nums">
                <thead className="bg-gray-50 dark:bg-gray-900/60">
                  <tr>
                    {['Regime', 'Annualized Return', 'Annualized Volatility', 'Share of History'].map(
                      (h) => (
                        <th
                          key={h}
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide"
                        >
                          {h}
                        </th>
                      )
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {data.states.map((state) => {
                    const style = regimeStyle(state.regime);
                    const isCurrent =
                      state.regime.toLowerCase() === data.current_regime.toLowerCase();
                    return (
                      <tr key={state.regime} className={isCurrent ? 'bg-blue-50/60 dark:bg-blue-900/10' : ''}>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${style.chip}`}
                          >
                            <span className={`w-1.5 h-1.5 rounded-full mr-1.5 ${style.dot}`} />
                            {style.label}
                            {isCurrent && (
                              <span className="ml-1.5 font-normal">· now</span>
                            )}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-900 dark:text-white">
                          {fmtPct(state.ann_ret)}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-900 dark:text-white">
                          {fmtPct(state.ann_vol)}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                          {state.historical_days_pct.toFixed(0)}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Recent Regime Timeline */}
          {data.recent_history.length > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                Last {data.recent_history.length} Trading Days
              </h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                One segment per day, colored by the regime the model assigned.
              </p>
              <div className="flex gap-[2px] h-8" role="img" aria-label="Daily regime timeline">
                {data.recent_history.map((day, i) => {
                  const style = regimeStyle(day.regime);
                  return (
                    <div
                      key={`${day.date}-${i}`}
                      className={`flex-1 min-w-[3px] rounded-sm ${style.dot}`}
                      title={`${day.date}: ${style.label}`}
                    />
                  );
                })}
              </div>
              <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-2 tabular-nums">
                <span>{data.recent_history[0].date}</span>
                <span>{data.recent_history[data.recent_history.length - 1].date}</span>
              </div>
            </div>
          )}

          {/* Portfolio in Current Regime */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">
              Your Portfolio Inside This Regime
            </h3>
            {data.portfolio_in_current_regime ? (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
                <div>
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
                    Overlap Days
                  </p>
                  <p className="text-xl font-semibold text-gray-900 dark:text-white tabular-nums">
                    {data.portfolio_in_current_regime.days}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
                    Your Annualized Return
                  </p>
                  <p
                    className={`text-xl font-semibold tabular-nums ${
                      data.portfolio_in_current_regime.ann_ret >= 0
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-rose-600 dark:text-rose-400'
                    }`}
                  >
                    {fmtPct(data.portfolio_in_current_regime.ann_ret)}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
                    Your Annualized Volatility
                  </p>
                  <p className="text-xl font-semibold text-gray-900 dark:text-white tabular-nums">
                    {fmtPct(data.portfolio_in_current_regime.ann_vol)}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Add holdings to your portfolio to see how it has historically behaved in{' '}
                {current.label.toLowerCase()} conditions.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
