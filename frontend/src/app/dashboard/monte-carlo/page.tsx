/**
 * Monte Carlo Goals Page
 * Probability of reaching a target value from your portfolio's own return history
 */

'use client';

import React, { useMemo, useState } from 'react';
import { MetricCard } from '@/components/ui/MetricCard';
import { analyticsApi } from '@/lib/api';
import {
  Target,
  AlertTriangle,
  RefreshCw,
  Play,
  Percent,
  Activity,
  Info,
  TrendingUp,
} from 'lucide-react';

interface MonteCarloResult {
  method: string;
  initial_value: number;
  target_value: number;
  horizon_years: number;
  num_paths: number;
  prob_success: number;
  terminal_percentiles: { p5: number; p25: number; p50: number; p75: number; p95: number };
  fan: { year: number; p5: number; p25: number; p50: number; p75: number; p95: number }[];
  expected_shortfall_vs_target: number;
  historical_mu_annual: number;
  historical_sigma_annual: number;
  student_t_df: number | null;
  disclaimer: string;
}

const METHODS = [
  { id: 'gbm', name: 'GBM', blurb: 'Lognormal, smooth and fast' },
  { id: 'student_t', name: 'Student-t', blurb: 'Fat tails fitted to history' },
  { id: 'bootstrap', name: 'Bootstrap', blurb: 'Resamples actual history' },
] as const;

function FanChart({ fan, target }: { fan: MonteCarloResult['fan']; target: number }) {
  const W = 640;
  const H = 240;
  const PAD = 8;
  const { min, max } = useMemo(() => {
    const vals = fan.flatMap((p) => [p.p5, p.p95, target]);
    return { min: Math.min(...vals), max: Math.max(...vals) };
  }, [fan, target]);
  const span = max - min || 1;
  const x = (yr: number) => PAD + (yr / fan[fan.length - 1].year) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - ((v - min) / span) * (H - 2 * PAD);

  const band = (lo: keyof typeof fan[0], hi: keyof typeof fan[0]) =>
    `M ${fan.map((p) => `${x(p.year).toFixed(1)} ${y(p[hi] as number).toFixed(1)}`).join(' L ')}` +
    ` L ${[...fan].reverse().map((p) => `${x(p.year).toFixed(1)} ${y(p[lo] as number).toFixed(1)}`).join(' L ')} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-56" role="img" aria-label="Outcome fan chart">
      {[fan[0].p50, target].includes(target) ? null : (
        <line x1={PAD} x2={W - PAD} y1={y(target)} y2={y(target)}
          stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="6 4" />
      )}
      <path d={band('p5', 'p95')} fill="rgba(16,185,129,0.14)" />
      <path d={band('p25', 'p75')} fill="rgba(16,185,129,0.28)" />
      <path
        d={`M ${fan.map((p) => `${x(p.year).toFixed(1)} ${y(p.p50).toFixed(1)}`).join(' L ')}`}
        fill="none" stroke="#059669" strokeWidth="2.5"
      />
      <text x={W - PAD} y={y(target) - 5} textAnchor="end" className="fill-amber-600 dark:fill-amber-400" fontSize="11">
        Target
      </text>
    </svg>
  );
}

export default function MonteCarloPage() {
  const [targetInput, setTargetInput] = useState('200000');
  const [horizon, setHorizon] = useState(5);
  const [method, setMethod] = useState<string>('student_t');
  const [result, setResult] = useState<MonteCarloResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runSimulation = async () => {
    setRunning(true);
    setError(null);
    try {
      const data = await analyticsApi.runMonteCarlo({
        target_value: Number(targetInput),
        horizon_years: horizon,
        method,
        num_paths: 2000,
      });
      setResult(data);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : 'Simulation failed');
    } finally {
      setRunning(false);
    }
  };

  const fmtMoney = (v: number) =>
    v >= 10_000_000
      ? `₹${(v / 10_000_000).toFixed(2)}Cr`
      : v >= 100_000
        ? `₹${(v / 100_000).toFixed(2)}L`
        : `₹${Math.round(v).toLocaleString('en-IN')}`;

  const pct = result ? Math.round(result.prob_success * 100) : null;

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-lime-600 to-emerald-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Goal Probability</h1>
            <p className="text-lime-100">
              Can your portfolio hit a target? Simulated from its own return history
            </p>
          </div>
          <Target className="hidden md:block w-16 h-16 text-lime-200" />
        </div>
      </div>

      {/* Inputs */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Set your goal
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mb-5">
          <div>
            <label htmlFor="mc-target" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Target value (₹)
            </label>
            <input
              id="mc-target"
              type="number"
              min="1"
              value={targetInput}
              onChange={(e) => setTargetInput(e.target.value)}
              disabled={running}
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-gray-900 dark:text-white tabular-nums focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
            />
          </div>
          <div>
            <label htmlFor="mc-horizon" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Horizon: {horizon} year{horizon > 1 ? 's' : ''}
            </label>
            <input
              id="mc-horizon"
              type="range"
              min="1"
              max="30"
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
              disabled={running}
              className="w-full accent-emerald-600"
            />
          </div>
          <div>
            <span className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Engine
            </span>
            <div className="flex rounded-lg border border-gray-300 dark:border-gray-600 overflow-hidden">
              {METHODS.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setMethod(m.id)}
                  disabled={running}
                  title={m.blurb}
                  className={`flex-1 px-2 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                    method === m.id
                      ? 'bg-emerald-600 text-white'
                      : 'bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800'
                  }`}
                >
                  {m.name}
                </button>
              ))}
            </div>
          </div>
        </div>
        <button
          onClick={runSimulation}
          disabled={running || !targetInput || Number(targetInput) <= 0}
          className="inline-flex items-center px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-400 dark:disabled:bg-gray-600 text-white font-medium rounded-lg transition-colors"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${running ? 'animate-spin' : ''}`} />
          {running ? 'Simulating 2,000 paths…' : 'Run simulation'}
        </button>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-3">
          Starting value defaults to your current portfolio market value. Returns calibrated on
          two years of cached closes.
        </p>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 mr-2" />
            <h3 className="text-red-800 dark:text-red-300 font-medium">Simulation failed</h3>
          </div>
          <p className="text-red-700 dark:text-red-400 text-sm mt-1">{error}</p>
        </div>
      )}

      {/* Empty State */}
      {!result && !running && !error && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-10 border border-gray-200 dark:border-gray-700 text-center">
          <Play className="w-10 h-10 text-emerald-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
            No simulation yet
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md mx-auto">
            Pick a target and horizon, then run the simulation to see your probability of
            success and the full range of outcomes.
          </p>
        </div>
      )}

      {/* Results */}
      {!running && result && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <MetricCard
              title="Probability of Success"
              value={`${pct}%`}
              icon={Percent}
            />
            <MetricCard
              title="Median Outcome"
              value={fmtMoney(result.terminal_percentiles.p50)}
              icon={Activity}
            />
            <MetricCard
              title="Bad Year (5th pct)"
              value={fmtMoney(result.terminal_percentiles.p5)}
              icon={AlertTriangle}
            />
            <MetricCard
              title="Good Year (95th pct)"
              value={fmtMoney(result.terminal_percentiles.p95)}
              icon={TrendingUp}
            />
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Range of Outcomes
              </h3>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {result.num_paths.toLocaleString('en-IN')} paths · {result.method} engine
                {result.student_t_df !== null && ` · tail df ${result.student_t_df}`}
              </span>
            </div>
            <FanChart fan={result.fan} target={result.target_value} />
            <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-2 tabular-nums">
              <span>Today · {fmtMoney(result.initial_value)}</span>
              <span>{result.horizon_years}y · target {fmtMoney(result.target_value)}</span>
            </div>
          </div>

          {pct !== null && pct < 50 && (
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4">
              <p className="text-sm text-amber-800 dark:text-amber-300">
                Below coin-flip odds. Median outcome lands at{' '}
                <span className="font-semibold tabular-nums">
                  {fmtMoney(result.terminal_percentiles.p50)}
                </span>{' '}
                vs your {fmtMoney(result.target_value)} target — a longer horizon, higher
                contributions, or a different mix changes this math.
              </p>
            </div>
          )}

          <div className="flex items-start space-x-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
            <Info className="w-5 h-5 text-blue-600 dark:text-blue-400 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-blue-800 dark:text-blue-300">{result.disclaimer}</p>
          </div>
        </>
      )}
    </div>
  );
}
