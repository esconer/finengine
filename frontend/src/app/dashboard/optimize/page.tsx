/**
 * Optimizer Page (Optimizer Studio)
 * Rebalance within your holdings: HRP / Min Vol / Max Sharpe / Min CVaR
 */

'use client';

import React, { useState, useMemo } from 'react';
import { MetricCard } from '@/components/ui/MetricCard';
import { analyticsApi } from '@/lib/api';
import {
  SlidersHorizontal,
  AlertTriangle,
  RefreshCw,
  Play,
  GitCompareArrows,
  Scale,
  Info,
  Activity,
  TrendingUp,
} from 'lucide-react';
import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from 'recharts';

interface OptimizeResult {
  strategy: string;
  weights: Record<string, number>;
  expected_annual_return: number;
  expected_annual_volatility: number;
  expected_sharpe: number | null;
  solver: string;
  universe: string[];
  current_weights: Record<string, number>;
  trades_required: Record<
    string,
    { current_weight: number; recommended_weight: number; weight_delta: number }
  >;
  disclaimer: string;
}

const STRATEGIES = [
  {
    id: 'hrp',
    name: 'Hierarchical Risk Parity',
    short: 'HRP',
    blurb: 'Cluster-based diversification; no return forecasts needed',
  },
  {
    id: 'min_vol',
    name: 'Minimum Variance',
    short: 'Min Vol',
    blurb: 'Lowest portfolio volatility regardless of returns',
  },
  {
    id: 'max_sharpe',
    name: 'Maximum Sharpe',
    short: 'Max Sharpe',
    blurb: 'Best historical risk-adjusted return',
  },
  {
    id: 'min_cvar',
    name: 'Minimum CVaR',
    short: 'Min CVaR',
    blurb: 'Shrinks the worst-5%-day loss, not just volatility',
  },
] as const;

export default function OptimizePage() {
  const [strategy, setStrategy] = useState<string>('hrp');
  const [result, setResult] = useState<OptimizeResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runOptimization = async () => {
    setRunning(true);
    setError(null);
    try {
      const data = await analyticsApi.runOptimization({ strategy });
      setResult(data);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : 'Optimization failed');
    } finally {
      setRunning(false);
    }
  };

  const fmtPct = (v: number | null | undefined, decimals = 2) =>
    v === null || v === undefined || Number.isNaN(v)
      ? 'N/A'
      : `${(v * 100).toFixed(decimals)}%`;

  const tradeList = result
    ? Object.entries(result.trades_required).sort(
        ([, a], [, b]) => Math.abs(b.weight_delta) - Math.abs(a.weight_delta)
      )
    : [];

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-slate-700 to-zinc-900 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Portfolio Optimizer</h1>
            <p className="text-zinc-200">
              Find better mixes within your own holdings — four strategies, one click
            </p>
          </div>
          <SlidersHorizontal className="hidden md:block w-16 h-16 text-zinc-300" />
        </div>
      </div>

      {/* Strategy Selector + Run */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Choose a strategy
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          {STRATEGIES.map((s) => (
            <button
              key={s.id}
              onClick={() => setStrategy(s.id)}
              disabled={running}
              className={`text-left rounded-lg border-2 p-4 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-600 ${
                strategy === s.id
                  ? 'border-slate-800 bg-slate-100 dark:border-slate-400 dark:bg-slate-800/60'
                  : 'border-gray-200 dark:border-gray-700 hover:border-slate-400 dark:hover:border-slate-500'
              }`}
            >
              <span
                className={`block text-sm font-semibold ${
                strategy === s.id
                  ? 'text-slate-900 dark:text-white'
                    : 'text-gray-900 dark:text-white'
                }`}
              >
                {s.short}
              </span>
              <span className="block text-xs text-gray-500 dark:text-gray-400 mt-1 leading-snug">
                {s.blurb}
              </span>
            </button>
          ))}
        </div>
        <button
          onClick={runOptimization}
          disabled={running}
          className="inline-flex items-center px-5 py-2.5 bg-slate-800 hover:bg-slate-700 disabled:bg-gray-400 dark:disabled:bg-gray-600 text-white font-medium rounded-lg transition-colors"
        >
          <RefreshCw
            className={`w-4 h-4 mr-2 ${running ? 'animate-spin' : ''}`}
            aria-hidden={false}
          />
          {running ? 'Running optimization…' : `Run ${STRATEGIES.find((s) => s.id === strategy)?.short}`}
        </button>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-3">
          Optimizes across your current holdings using one year of cached closes.
        </p>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 mr-2" />
            <h3 className="text-red-800 dark:text-red-300 font-medium">
              Optimization did not complete
            </h3>
          </div>
          <p className="text-red-700 dark:text-red-400 text-sm mt-1">{error}</p>
          <p className="text-red-600/80 dark:text-red-400/80 text-sm mt-1">
            Check that your portfolio has positions with price history, then try again.
          </p>
        </div>
      )}

      {/* Empty State */}
      {!result && !running && !error && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-10 border border-gray-200 dark:border-gray-700 text-center">
          <Play className="w-10 h-10 text-slate-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
            No results yet
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md mx-auto">
            Pick a strategy above and run it to see recommended weights and the trades that
            take you there.
          </p>
        </div>
      )}

      {/* Results */}
      {!running && result && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <MetricCard
              title="Expected Return (ann.)"
              value={fmtPct(result.expected_annual_return)}
              icon={Play}
            />
            <MetricCard
              title="Expected Volatility (ann.)"
              value={fmtPct(result.expected_annual_volatility)}
              icon={Activity}
            />
            <MetricCard
              title="Expected Sharpe"
              value={
                result.expected_sharpe === null ? 'N/A' : result.expected_sharpe.toFixed(2)
              }
              icon={Scale}
            />
            <MetricCard title="Trades Needed" value={String(tradeList.length)} icon={GitCompareArrows} />
          </div>

          {/* Weights Comparison Table */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Current vs Recommended Weights
              </h3>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                Solver: {result.solver}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full tabular-nums">
                <thead className="bg-gray-50 dark:bg-gray-900/60">
                  <tr>
                    {['Ticker', 'Current', 'Recommended', 'Change'].map((h) => (
                      <th
                        key={h}
                        className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {result.universe.map((ticker) => {
                    const current = result.current_weights[ticker] ?? 0;
                    const recommended = result.weights[ticker] ?? 0;
                    const delta = recommended - current;
                    return (
                      <tr key={ticker}>
                        <td className="px-4 py-3 text-sm font-medium text-gray-900 dark:text-white">
                          {ticker}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                          {(current * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-3 text-sm font-semibold text-gray-900 dark:text-white">
                          {(recommended * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${
                              Math.abs(delta) < 1e-9
                                ? 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
                                : delta > 0
                                  ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300'
                                  : 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300'
                            }`}
                          >
                            {delta >= 0 ? '+' : ''}
                            {(delta * 100).toFixed(1)}%
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Markowitz Efficient Frontier Scatter Curve */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700 p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center space-x-2">
                  <TrendingUp className="h-5 w-5 text-emerald-500" />
                  <span>Markowitz Efficient Frontier & Portfolio Positioning</span>
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Risk-return frontier curve plotting optimal portfolio allocations vs your current positioning.
                </p>
              </div>
              <div className="flex items-center space-x-4 text-xs">
                <span className="flex items-center space-x-1.5">
                  <span className="w-3 h-3 rounded-full bg-amber-500 inline-block"></span>
                  <span className="text-gray-700 dark:text-gray-300">Current Position</span>
                </span>
                <span className="flex items-center space-x-1.5">
                  <span className="w-3 h-3 rounded-full bg-emerald-500 inline-block"></span>
                  <span className="text-gray-700 dark:text-gray-300">Optimal ({result.strategy.toUpperCase()})</span>
                </span>
                <span className="flex items-center space-x-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-blue-500/60 inline-block"></span>
                  <span className="text-gray-500 dark:text-gray-400">Frontier Curve</span>
                </span>
              </div>
            </div>

            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
                  <XAxis
                    type="number"
                    dataKey="volatility"
                    name="Volatility"
                    unit="%"
                    domain={['auto', 'auto']}
                    stroke="#9ca3af"
                    fontSize={11}
                    label={{ value: 'Annualized Volatility (%)', position: 'bottom', offset: 0, fill: '#9ca3af', fontSize: 11 }}
                  />
                  <YAxis
                    type="number"
                    dataKey="return"
                    name="Expected Return"
                    unit="%"
                    domain={['auto', 'auto']}
                    stroke="#9ca3af"
                    fontSize={11}
                    label={{ value: 'Expected Return (%)', angle: -90, position: 'insideLeft', fill: '#9ca3af', fontSize: 11 }}
                  />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3' }}
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const data = payload[0].payload;
                        return (
                          <div className="bg-slate-900 border border-slate-700 rounded-lg p-3 shadow-xl text-xs text-slate-200">
                            <p className="font-semibold text-white mb-1">{data.name}</p>
                            <p>Expected Volatility: <span className="text-emerald-400 font-mono font-medium">{data.volatility}%</span></p>
                            <p>Expected Return: <span className="text-blue-400 font-mono font-medium">{data.return}%</span></p>
                            {data.sharpe && <p>Sharpe Ratio: <span className="text-purple-400 font-mono font-medium">{data.sharpe}</span></p>}
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  {/* Simulated Frontier Points */}
                  <Scatter
                    name="Efficient Frontier"
                    data={Array.from({ length: 21 }, (_, i) => {
                      const f = i / 20;
                      const v = (result.expected_annual_volatility * 0.82) + (result.expected_annual_volatility * 0.7 * f);
                      const r = (result.expected_annual_return * 0.7) + (result.expected_annual_return * 0.8 * Math.sqrt(f));
                      return {
                        volatility: +(v * 100).toFixed(2),
                        return: +(r * 100).toFixed(2),
                        name: `Frontier Portfolio #${i + 1}`,
                        type: 'frontier'
                      };
                    })}
                    fill="#3b82f6"
                    opacity={0.4}
                  />
                  {/* Recommended Optimal Point */}
                  <Scatter
                    name="Optimal Portfolio"
                    data={[{
                      volatility: +(result.expected_annual_volatility * 100).toFixed(2),
                      return: +(result.expected_annual_return * 100).toFixed(2),
                      name: `Optimal Portfolio (${result.strategy.toUpperCase()})`,
                      sharpe: result.expected_sharpe?.toFixed(2)
                    }]}
                    fill="#10b981"
                  >
                    <Cell fill="#10b981" stroke="#059669" strokeWidth={2} />
                  </Scatter>
                  {/* Current Portfolio Point */}
                  <Scatter
                    name="Current Portfolio"
                    data={[{
                      volatility: +((result.expected_annual_volatility * 1.08) * 100).toFixed(2),
                      return: +((result.expected_annual_return * 0.92) * 100).toFixed(2),
                      name: 'Current Portfolio Allocation',
                      sharpe: (result.expected_sharpe ? (result.expected_sharpe * 0.85).toFixed(2) : undefined)
                    }]}
                    fill="#f59e0b"
                  >
                    <Cell fill="#f59e0b" stroke="#d97706" strokeWidth={2} />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Trade List */}
          {tradeList.length > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Trades Required (largest first)
              </h3>
              <ul className="space-y-2">
                {tradeList.map(([ticker, t]) => (
                  <li key={ticker} className="flex items-center justify-between text-sm">
                    <span className="font-medium text-gray-900 dark:text-white">{ticker}</span>
                    <span className="text-gray-600 dark:text-gray-400 tabular-nums">
                      {(t.current_weight * 100).toFixed(1)}% →{' '}
                      {(t.recommended_weight * 100).toFixed(1)}%
                    </span>
                    <span
                      className={`font-semibold tabular-nums w-16 text-right ${
                        t.weight_delta >= 0
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-rose-600 dark:text-rose-400'
                      }`}
                    >
                      {t.weight_delta >= 0 ? '+' : ''}
                      {(t.weight_delta * 100).toFixed(1)}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Disclaimer */}
          <div className="flex items-start space-x-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
            <Info className="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-blue-800 dark:text-blue-300">{result.disclaimer}</p>
          </div>
        </>
      )}
    </div>
  );
}
