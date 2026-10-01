/**
 * Optimizer Page (Optimizer Studio)
 * Rebalance within your holdings: HRP / Min Vol / Max Sharpe / Min CVaR
 */

'use client';

import React, { useState, useMemo, useEffect } from 'react';
import { MetricCard } from '@/components/ui/MetricCard';
import {
  SectionProvenance,
  sectionCoverage,
} from '@/components/provenance/SectionProvenance';
import { analyticsApi, portfolioApi } from '@/lib/api';
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
  ShieldCheck,
  CheckCircle2,
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

/** A published leg. A field the solver did not measure is `null`, never 0. */
interface TradeRow {
  current_weight: number | null;
  recommended_weight: number | null;
  weight_delta: number | null;
}

interface NormalizationBlock {
  normalization_rule?: string | null;
  normalization_mode?: string | null;
  submitted_gross_exposure?: number | null;
  gross_exposure?: number | null;
  execution_eligible?: boolean;
  financing_required?: boolean;
  block_reason?: string | null;
}

interface TradesRequiredBasis {
  weight_decimals?: number | null;
  weight_delta_rule?: string | null;
  trade_count?: number | null;
  current_weights_published_total?: number | null;
  current_weights_rounding_residual?: number | null;
  recommended_weights_published_total?: number | null;
  recommended_weights_rounding_residual?: number | null;
}

interface OptimizeResult {
  strategy: string;
  weights: Record<string, number>;
  expected_annual_return: number | null;
  expected_annual_volatility: number | null;
  expected_sharpe: number | null;
  solver: string;
  universe: string[];
  current_weights: Record<string, number>;
  trades_required: Record<string, TradeRow>;
  disclaimer: string;
  /** The solver's own disclosure of the shared normalization rule. */
  weight_normalization?: NormalizationBlock | null;
  trades_required_basis?: TradesRequiredBasis | null;
  data_status?: string | null;
  error?: string | null;
  /**
   * The newest delivered observation the common return frame was built from.
   * The target weights are solved over the DELIVERED universe only, so this is
   * also the freshness of the covariance matrix behind them.
   */
  latest_observation_date?: string | null;
  warnings?: string[] | null;
  universe_coverage?: {
    missing_tickers?: string[] | null;
  } | null;
}

const NOT_AVAILABLE = 'N/A';

/**
 * Mirrors `GROSS_EXPOSURE_TOLERANCE` in `backend/app/utils/allocations.py`,
 * the tolerance the rebalance endpoint itself judges a submitted target with.
 * A target is financed only above this distance from 1.0.
 */
const GROSS_EXPOSURE_TOLERANCE = 1e-6;

/**
 * Two published legs differing by less than this are the same number at
 * display precision (`TRADE_WEIGHT_DECIMALS` = 4).
 */
const LEG_AGREEMENT_TOLERANCE = 1e-4;

function finiteOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function grossExposureOf(weights: Record<string, number>): number {
  return Object.values(weights).reduce((sum, weight) => sum + Math.abs(weight), 0);
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** The trade list, biggest move first, with every absent leg carried as null. */
type NormalizedTrade = {
  ticker: string;
  current: number | null;
  recommended: number | null;
  delta: number | null;
};

type ApplyTarget = {
  /** The complete target vector the apply will submit. */
  weights: Record<string, number>;
  grossExposure: number;
  /** Legs the optimizer left unmeasured; a partial target is never executed. */
  unmeasurable: string[];
  /** Legs the trade list does not move, named at their published weight. */
  held: string[];
};

type DivergenceRow = {
  ticker: string;
  applied: number;
  /** The solver's own target, or null when it published none for this leg. */
  solver: number | null;
};

/** The part of `portfolioApi.rebalancePortfolio`'s response the ticket reads. */
type RebalanceResult = {
  success?: boolean;
  dry_run?: boolean;
  message?: string;
  total_turnover_pct?: number;
  total_buy_inr?: number;
  total_sell_inr?: number;
  orders?: Array<{
    ticker: string;
    action?: string;
    current_weight: number | null;
    target_weight: number | null;
    weight_delta: number | null;
    shares_delta: number | null;
  }>;
  weight_normalization?: NormalizationBlock | null;
};

/**
 * The vector the apply submits, built from the RECONCILED TRADE LIST.
 *
 * `trades_required` is not a weight vector and must not be posted as one: the
 * rebalance workflow normalizes whatever it is given to sum to 1.0
 * (`divide_all_legs_by_gross_exposure`), so submitting only the legs that move
 * would inflate every one of them by 1/gross and rebalance the whole book.
 *
 * `rebalancePortfolio` also skips any position absent from the target map, so
 * an unnamed leg is held at whatever it happens to be worth now. Every leg is
 * therefore NAMED: the trade list decides the ones that move, and the rest are
 * held at the weight the optimizer published for them. The target is then a
 * complete, fully funded vector, and the executed orders are the trade list.
 */
function buildApplyTarget(result: OptimizeResult | null): ApplyTarget | null {
  if (!result) return null;

  const unmeasurable: string[] = [];
  const held: string[] = [];
  const weights: Record<string, number> = {};
  const traded = new Set(Object.keys(result.trades_required ?? {}));

  for (const [ticker, trade] of Object.entries(result.trades_required ?? {})) {
    const recommended = finiteOrNull(trade?.recommended_weight);
    // A negative or absent target leg carries no instruction; dropping it
    // silently would apply a different portfolio than the one reconciled.
    if (recommended === null || recommended < 0) {
      unmeasurable.push(ticker);
      continue;
    }
    weights[ticker] = recommended;
  }

  for (const [ticker, raw] of Object.entries(result.current_weights ?? {})) {
    if (traded.has(ticker)) continue;
    const current = finiteOrNull(raw);
    if (current === null || current < 0) {
      unmeasurable.push(ticker);
      continue;
    }
    weights[ticker] = current;
    held.push(ticker);
  }

  return {
    weights,
    grossExposure: grossExposureOf(weights),
    unmeasurable,
    held,
  };
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
  {
    id: 'black_litterman',
    name: 'Black-Litterman Bayesian',
    short: 'Black-Litterman',
    blurb: 'Equilibrium prior anchored with subjective investor conviction',
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

  const hasFrontierCoords =
    result != null &&
    result.expected_annual_return != null &&
    result.expected_annual_volatility != null &&
    !Number.isNaN(result.expected_annual_return) &&
    !Number.isNaN(result.expected_annual_volatility);

  const optimalPoint = useMemo(() => {
    if (!result || result.expected_annual_return == null || result.expected_annual_volatility == null) return [];
    return [{
      volatility: +(result.expected_annual_volatility * 100).toFixed(2),
      return: +(result.expected_annual_return * 100).toFixed(2),
      name: `Optimal Portfolio (${result.strategy.toUpperCase()})`,
      sharpe: result.expected_sharpe?.toFixed(2)
    }];
  }, [result]);

  const tradeList = useMemo<NormalizedTrade[]>(() => {
    if (!result) return [];
    return Object.entries(result.trades_required ?? {})
      .map(([ticker, trade]) => ({
        ticker,
        current: finiteOrNull(trade?.current_weight),
        recommended: finiteOrNull(trade?.recommended_weight),
        // A leg with no measured endpoint has no delta. Deriving one from a
        // missing input is how an unreported holding became a full-size BUY.
        delta:
          finiteOrNull(trade?.weight_delta) ??
          (finiteOrNull(trade?.recommended_weight) !== null &&
          finiteOrNull(trade?.current_weight) !== null
            ? finiteOrNull(trade?.recommended_weight)! - finiteOrNull(trade?.current_weight)!
            : null),
      }))
      .sort((a, b) => Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0));
  }, [result]);

  // -------------------------------------------------------------------------
  // apply / rebalance
  // -------------------------------------------------------------------------
  const [showApplyTicket, setShowApplyTicket] = useState(false);
  const [applyInProgress, setApplyInProgress] = useState(false);
  // A dry run authorises exactly one apply of exactly one target. Each of these
  // is stored against the `resultKey` it was produced for, so a new run
  // invalidates it by derivation rather than by a reset effect.
  const [applyError, setApplyError] = useState<{ key: string; text: string } | null>(null);
  const [simulation, setSimulation] = useState<{ key: string; data: RebalanceResult } | null>(null);
  const [applySuccess, setApplySuccess] = useState<{ key: string; text: string } | null>(null);

  const applyTarget = useMemo(() => buildApplyTarget(result), [result]);
  const hasTarget = applyTarget !== null && Object.keys(applyTarget.weights).length > 0;
  const unavailableReason =
    result == null
      ? null
      : result.data_status === 'unavailable'
        ? result.error || 'the optimizer reported no measured result'
        : result.error
          ? result.error
          : null;
  const unmeasuredLegs = useMemo(() => applyTarget?.unmeasurable ?? [], [applyTarget]);
  const financingRequired =
    applyTarget !== null && applyTarget.grossExposure > 1 + GROSS_EXPOSURE_TOLERANCE;
  const normalizationRule =
    result?.weight_normalization?.normalization_rule ?? 'divide_all_legs_by_gross_exposure';

  // The identity of the target on screen. Everything the apply path holds is
  // scoped to it.
  const resultKey = result
    ? JSON.stringify([result.strategy, result.solver, result.universe, result.trades_required])
    : '';
  const liveSimulation = simulation !== null && simulation.key === resultKey ? simulation.data : null;
  const liveError = applyError !== null && applyError.key === resultKey ? applyError.text : null;
  const liveSuccess = applySuccess !== null && applySuccess.key === resultKey ? applySuccess.text : null;

  // One gate for both apply buttons, the same predicate the rebalance endpoint
  // applies to the vector it is handed: a target that needs financing cannot be
  // expressed as a plain rebalance, an unavailable run is not an instruction,
  // and a leg the solver left unmeasured must not be applied as a zero.
  const executionEligible =
    hasTarget && unavailableReason === null && unmeasuredLegs.length === 0 && !financingRequired;

  const executionBlockReason = useMemo(() => {
    if (unavailableReason) {
      return `The optimizer result is unavailable, so it is not an executable target: ${unavailableReason}`;
    }
    if (!hasTarget) {
      return 'No rebalance target is available, so there is nothing to execute.';
    }
    if (unmeasuredLegs.length > 0) {
      return (
        `These legs have no measured weight (${unmeasuredLegs.join(', ')}), so the apply ` +
        'would be a partial rebalance against a target that was never reconciled. ' +
        'Re-run the optimizer.'
      );
    }
    if (financingRequired && applyTarget !== null) {
      return (
        `Target requires ${((applyTarget.grossExposure - 1) * 100).toFixed(2)}% financing ` +
        '(amount not quantified: no portfolio value on this response); a normal rebalance ' +
        `cannot express gross > 100%. Normalization rule '${normalizationRule}' does not ` +
        'create financing.'
      );
    }
    return null;
  }, [unavailableReason, hasTarget, unmeasuredLegs, financingRequired, applyTarget, normalizationRule]);

  // Legs where the reconciled trade list and the solver's own target vector
  // disagree. Never resolved silently: the trade list wins, and the difference
  // is on the ticket before the user confirms.
  const targetDivergence = useMemo<DivergenceRow[]>(() => {
    if (!result || !applyTarget) return [];
    const rows: DivergenceRow[] = [];
    for (const [ticker, applied] of Object.entries(applyTarget.weights)) {
      const solver = finiteOrNull(result.weights?.[ticker]);
      if (solver === null || Math.abs(solver - applied) > LEG_AGREEMENT_TOLERANCE) {
        rows.push({ ticker, applied, solver });
      }
    }
    return rows.sort((a, b) => b.applied - a.applied);
  }, [result, applyTarget]);

  // A dry run authorises exactly one apply of exactly one target: every piece of
  // apply state carries the `resultKey` it was produced for, so a new run
  // invalidates it by derivation and a stale simulation can never confirm a
  // different book.
  const openApplyTicket = () => {
    setShowApplyTicket(true);
    setApplyError(null);
    setApplySuccess(null);
  };

  const closeApplyTicket = () => {
    setShowApplyTicket(false);
    setApplyInProgress(false);
    setSimulation(null);
    setApplySuccess(null);
    setApplyError(null);
  };

  // The apply ticket declares `role="dialog"`, so Escape has to dismiss it. It
  // is NOT portalled through Radix — it is an inline panel with no overlay and
  // no backdrop, and a modal wrapper would both restyle it and move it out of
  // the flow of the trade list it annotates. The listener is inert until the
  // panel exists, and is torn down when it closes.
  useEffect(() => {
    if (!showApplyTicket) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeApplyTicket();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showApplyTicket]);

  const handleRunSimulation = async () => {
    // Fail closed: an ineligible target is never sent, not even to be simulated.
    if (!executionEligible || applyTarget === null) {
      setApplyError({
        key: resultKey,
        text: executionBlockReason || 'This target cannot be applied as a normal rebalance.',
      });
      return;
    }
    setApplyInProgress(true);
    setApplyError(null);
    setApplySuccess(null);
    setSimulation(null);
    try {
      const dry = await portfolioApi.rebalancePortfolio(applyTarget.weights, true);
      setSimulation({ key: resultKey, data: dry });
    } catch (err) {
      setApplyError({ key: resultKey, text: `Simulation failed: ${errorText(err, 'Unknown error')}` });
    } finally {
      setApplyInProgress(false);
    }
  };

  const handleConfirmRebalance = async () => {
    // Fail closed, again: the gate is re-evaluated, never cached from open time.
    if (!executionEligible || applyTarget === null) {
      setApplyError({
        key: resultKey,
        text: executionBlockReason || 'This target cannot be applied as a normal rebalance.',
      });
      return;
    }
    // No blind apply and no double-apply: the dry run must have genuinely run
    // first, and a second click cannot fire while one is in flight.
    if (liveSimulation === null) {
      setApplyError({
        key: resultKey,
        text: 'Simulate the apply first; nothing is committed without a dry run.',
      });
      return;
    }
    if (applyInProgress) return;
    setApplyInProgress(true);
    setApplyError(null);
    try {
      const done = await portfolioApi.rebalancePortfolio(applyTarget.weights, false);
      setApplySuccess({
        key: resultKey,
        text: done?.message || 'Portfolio rebalanced from the optimizer trade list.',
      });
      // The authorisation is single-use: the ticket cannot be applied twice.
      setSimulation(null);
    } catch (err) {
      setApplyError({ key: resultKey, text: `Rebalancing failed: ${errorText(err, 'Unknown error')}` });
    } finally {
      setApplyInProgress(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-slate-700 to-zinc-900 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Portfolio Optimizer</h1>
            <p className="text-zinc-200">
              Find better mixes within your own holdings — five strategies, one click
            </p>
          </div>
          <SlidersHorizontal className="hidden md:block w-16 h-16 text-zinc-300" />
        </div>
      </div>

      {/* Provenance: the observation the target weights were solved on, and
          which holdings were excluded from the solved universe. */}
      <SectionProvenance
        section="Optimizer"
        asOf={result?.latest_observation_date ?? null}
        coverage={sectionCoverage(result?.universe_coverage)}
        warnings={result?.warnings ?? null}
      />

      {/* Strategy Selector + Run */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Choose a strategy
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 mb-5">
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
                    // A ticker the solver omitted from a weight map is UNMEASURED,
                    // not a 0% position. `?? 0` invented a full-size BUY for a
                    // holding the optimizer simply did not report on.
                    const currentRaw = result.current_weights?.[ticker];
                    const recommendedRaw = result.weights?.[ticker];
                    const current = typeof currentRaw === 'number' && Number.isFinite(currentRaw) ? currentRaw : null;
                    const recommended = typeof recommendedRaw === 'number' && Number.isFinite(recommendedRaw) ? recommendedRaw : null;
                    const delta = current === null || recommended === null ? null : recommended - current;
                    return (
                      <tr key={ticker}>
                        <td className="px-4 py-3 text-sm font-medium text-gray-900 dark:text-white">
                          {ticker}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                          {current === null ? 'N/A' : `${(current * 100).toFixed(1)}%`}
                        </td>
                        <td className="px-4 py-3 text-sm font-semibold text-gray-900 dark:text-white">
                          {recommended === null ? 'N/A' : `${(recommended * 100).toFixed(1)}%`}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${
                              delta === null
                                ? 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
                                : Math.abs(delta) < 1e-9
                                ? 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
                                : delta > 0
                                  ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300'
                                  : 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300'
                            }`}
                          >
                            {delta === null
                              ? 'N/A'
                              : `${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(1)}%`}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Optimal Portfolio Risk / Return */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700 p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center space-x-2">
                  <TrendingUp className="h-5 w-5 text-emerald-500" />
                  <span>Optimal Portfolio Risk / Return</span>
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Solved risk-return position for the chosen strategy.
                </p>
              </div>
              <div className="flex items-center space-x-4 text-xs">
                <span className="flex items-center space-x-1.5">
                  <span className="w-3 h-3 rounded-full bg-emerald-500 inline-block"></span>
                  <span className="text-gray-700 dark:text-gray-300">Optimal ({result.strategy.toUpperCase()})</span>
                </span>
              </div>
            </div>

            <div className="h-72 w-full">
              {!hasFrontierCoords ? (
                <div data-testid="frontier-empty" className="h-full flex flex-col items-center justify-center text-center px-6">
                  <AlertTriangle className="w-8 h-8 text-amber-400 mb-3" />
                  <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    Efficient frontier unavailable
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    The optimizer returned no expected risk/return estimates for this run.
                  </p>
                </div>
              ) : (
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
                  {/* Recommended Optimal Point */}
                  <Scatter
                    name="Optimal Portfolio"
                    data={optimalPoint}
                    fill="#10b981"
                  >
                    <Cell fill="#10b981" stroke="#059669" strokeWidth={2} />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Trade List */}
          {tradeList.length > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Trades Required (largest first)
              </h3>
              <ul className="space-y-2">
                {tradeList.map((t) => (
                  <li
                    key={t.ticker}
                    data-testid={`trade-${t.ticker}`}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="font-medium text-gray-900 dark:text-white">{t.ticker}</span>
                    <span className="text-gray-600 dark:text-gray-400 tabular-nums">
                      <span data-testid={`trade-from-${t.ticker}`}>
                        {t.current === null
                          ? NOT_AVAILABLE
                          : `${(t.current * 100).toFixed(1)}%`}
                      </span>
                      {' → '}
                      <span data-testid={`trade-to-${t.ticker}`}>
                        {t.recommended === null
                          ? NOT_AVAILABLE
                          : `${(t.recommended * 100).toFixed(1)}%`}
                      </span>
                    </span>
                    <span
                      data-testid={`trade-delta-${t.ticker}`}
                      className={`font-semibold tabular-nums w-16 text-right ${
                        t.delta === null
                          ? 'inline-block px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
                          : t.delta >= 0
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : 'text-rose-600 dark:text-rose-400'
                      }`}
                    >
                      {t.delta === null
                        ? NOT_AVAILABLE
                        : `${t.delta >= 0 ? '+' : ''}${(t.delta * 100).toFixed(1)}%`}
                    </span>
                  </li>
                ))}
              </ul>

              {/* Apply — the one path from a reconciled trade list to a committed book. */}
              <div
                data-testid="apply-panel"
                className="mt-5 pt-5 border-t border-gray-200 dark:border-gray-700"
              >
                {executionBlockReason && (
                  <div
                    data-testid="execution-blocked"
                    className="flex items-start space-x-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-3 mb-4"
                  >
                    <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />
                    <p className="text-sm text-amber-800 dark:text-amber-300">
                      {executionBlockReason}
                    </p>
                  </div>
                )}
                <button
                  onClick={openApplyTicket}
                  disabled={!executionEligible}
                  title={
                    executionEligible
                      ? 'Open the rebalance ticket'
                      : executionBlockReason || undefined
                  }
                  className="inline-flex items-center px-5 py-2.5 bg-slate-800 hover:bg-slate-700 disabled:bg-gray-400 dark:disabled:bg-gray-600 text-white font-medium rounded-lg transition-colors"
                >
                  <ShieldCheck className="w-4 h-4 mr-2" aria-hidden={false} />
                  Apply these trades
                </button>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                  Submits the reconciled trade list above as a target vector:{' '}
                  {Object.keys(applyTarget?.weights ?? {}).length} legs named, gross{' '}
                  {fmtPct(applyTarget?.grossExposure ?? null)} of the book.
                </p>
              </div>
            </div>
          )}

          {/* Apply ticket — what will happen, shown before anything is committed. */}
          {showApplyTicket && (
            <div
              data-testid="apply-ticket"
              role="dialog"
              aria-modal="true"
              aria-label="Apply optimizer trades"
              className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700"
            >
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
                Apply the optimizer trade list
              </h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
                {result.strategy.toUpperCase()} · solver {result.solver}
              </p>

              <div data-testid="apply-trades" className="mb-4">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
                  Trades this will execute
                </h4>
                <ul className="space-y-1">
                  {tradeList.map((t) => (
                    <li
                      key={t.ticker}
                      className="flex items-center justify-between text-sm tabular-nums"
                    >
                      <span className="font-medium text-gray-900 dark:text-white">
                        {t.ticker}
                      </span>
                      <span className="text-gray-600 dark:text-gray-400">
                        {t.current === null
                          ? NOT_AVAILABLE
                          : `${(t.current * 100).toFixed(1)}%`}{' '}
                        →{' '}
                        {t.recommended === null
                          ? NOT_AVAILABLE
                          : `${(t.recommended * 100).toFixed(1)}%`}
                      </span>
                      <span
                        className={`w-16 text-right font-semibold ${
                          t.delta === null
                            ? 'text-gray-500'
                            : t.delta >= 0
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-rose-600 dark:text-rose-400'
                        }`}
                      >
                        {t.delta === null
                          ? NOT_AVAILABLE
                          : `${t.delta >= 0 ? '+' : ''}${(t.delta * 100).toFixed(1)}%`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              <div
                data-testid="apply-reconciliation"
                className="flex items-start space-x-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-3 mb-4"
              >
                <Info className="w-4 h-4 text-blue-600 dark:text-blue-400 mt-0.5 flex-shrink-0" />
                <p className="text-xs text-blue-800 dark:text-blue-300">
                  <span className="font-semibold">Reconciliation rule: </span>
                  {result.trades_required_basis?.weight_delta_rule ??
                    'the optimizer did not publish a weight_delta rule for this run'}
                  <br />
                  <span className="font-semibold">Normalization rule: </span>
                  {normalizationRule} — a target above 100% gross is rejected, not
                  scaled down.
                </p>
              </div>

              <div
                data-testid="apply-target-summary"
                className="text-xs text-gray-600 dark:text-gray-400 mb-4 space-y-1"
              >
                <p>
                  Target vector: {Object.keys(applyTarget?.weights ?? {}).length} legs, gross{' '}
                  {fmtPct(applyTarget?.grossExposure ?? null)} of the book.
                </p>
                {applyTarget && applyTarget.held.length > 0 && (
                  <p>
                    Held at published current weight (the trade list does not move them):{' '}
                    {applyTarget.held.join(', ')}. Any drift since this optimization ran
                    shows in the simulation below.
                  </p>
                )}
              </div>

              {targetDivergence.length > 0 && (
                <div
                  data-testid="apply-divergence"
                  className="flex items-start space-x-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-3 mb-4"
                >
                  <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />
                  <div className="text-xs text-amber-800 dark:text-amber-300">
                    <p className="font-semibold">
                      The trade list and the solver&apos;s own target vector disagree. The
                      trade list is what was shown, so the trade list is what is applied:
                    </p>
                    <ul className="mt-1 space-y-0.5">
                      {targetDivergence.map((d) => (
                        <li key={d.ticker}>
                          {d.ticker}: applying {fmtPct(d.applied)}; solver target{' '}
                          {d.solver === null ? NOT_AVAILABLE : fmtPct(d.solver)}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              {liveSimulation && (
                <div
                  data-testid="simulation-orders"
                  className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 mb-4"
                >
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">
                    Dry run — {liveSimulation.orders?.length ?? 0} orders, no records altered
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                    Turnover {fmtPct(liveSimulation.total_turnover_pct ?? null)} · buys{' '}
                    {liveSimulation.total_buy_inr ?? NOT_AVAILABLE} · sells{' '}
                    {liveSimulation.total_sell_inr ?? NOT_AVAILABLE} · normalization{' '}
                    {liveSimulation.weight_normalization?.normalization_mode ?? NOT_AVAILABLE}
                  </p>
                  <ul className="space-y-0.5">
                    {(liveSimulation.orders ?? []).map((o) => (
                      <li key={o.ticker} className="text-xs tabular-nums text-gray-600 dark:text-gray-400">
                        {o.ticker}: {o.action} · {fmtPct(o.current_weight)} →{' '}
                        {fmtPct(o.target_weight)} · {o.shares_delta} shares
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {liveError && (
                <div
                  data-testid="apply-error"
                  className="flex items-start space-x-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 mb-4"
                >
                  <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-red-800 dark:text-red-300">{liveError}</p>
                </div>
              )}

              {liveSuccess && (
                <div
                  data-testid="apply-success"
                  className="flex items-start space-x-2 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg p-3 mb-4"
                >
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-emerald-800 dark:text-emerald-300">
                    {liveSuccess}
                  </p>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-3">
                <button
                  data-testid="apply-simulate"
                  onClick={handleRunSimulation}
                  disabled={applyInProgress || !executionEligible}
                  className="inline-flex items-center px-4 py-2 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 font-medium rounded-lg transition-colors disabled:opacity-50"
                >
                  Simulate first
                </button>
                <button
                  data-testid="apply-confirm"
                  onClick={handleConfirmRebalance}
                  disabled={
                    applyInProgress ||
                    !executionEligible ||
                    liveSimulation === null ||
                    liveSuccess !== null
                  }
                  className="inline-flex items-center px-4 py-2 bg-emerald-700 hover:bg-emerald-600 disabled:bg-gray-400 dark:disabled:bg-gray-600 text-white font-medium rounded-lg transition-colors"
                >
                  {applyInProgress ? 'Working…' : 'Confirm and apply'}
                </button>
                <button
                  onClick={closeApplyTicket}
                  className="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
                >
                  Close
                </button>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                The apply is only enabled after a dry run of this exact target has
                completed, and only once.
              </p>
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
