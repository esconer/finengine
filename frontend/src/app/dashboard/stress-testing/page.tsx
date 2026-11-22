/**
 * Stress Testing Page - Portfolio stress testing scenarios and impact analysis
 */

'use client';

import React, { useState, useEffect, useMemo, useRef } from 'react';
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable';
import { MetricCard } from '@/components/ui/MetricCard';
import {
  SectionProvenance,
  sectionCoverage,
} from '@/components/provenance/SectionProvenance';
import { analyticsApi } from '@/lib/api';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { usePortfolioStore } from '@/lib/store';
import { escapeCsvCell } from '@/lib/utils';
import {
  TestTube,
  AlertTriangle,
  TrendingDown,
  Activity,
  RefreshCw,
  Play,
  Settings,
  Download,
  Plus,
  X,
  HelpCircle,
  BookOpen,
  Zap,
  ShieldAlert,
  Clock,
  Layers,
  ChevronRight,
  Info
} from 'lucide-react';

/**
 * One row of the position-impact table.
 *
 * Derived by flattening `StressTestResult.position_impacts` (keyed by ticker).
 * Declaring the fields the columns publish is what makes `row.original`
 * non-optional at compile time instead of a runtime `undefined` → `NaN%`
 * (UA-01, 358fb49).
 */
interface StressImpactRow {
  ticker: string;
  /** Proxy impact as a fraction; the severity band is derived from it. */
  impact: number;
  /** Duplicate of `impact`, kept as published by the table's own CSV export. */
  change: number;
}

/**
 * The scalar half of `shock_inputs`, which is the whole of the shock this
 * scenario applied and the bounds it was held to.
 *
 * `analytics_engine.py:4630-4695` publishes far more than this (the sector
 * elasticity table, the instrument overrides, the per-ticker co-movement and
 * volatility maps). Those are declared `unknown` below rather than typed: this
 * page renders none of them, so naming their shapes here would be a claim the
 * code does not make.
 */
interface StressShockInputs {
  /** Signed fraction return applied to every constituent (`units.market_shock`). */
  market_shock?: number | null;
  market_shock_basis?: string | null;
  sector_elasticity_basis?: string | null;
  /** Configured bounds the per-holding impact is clipped into. */
  position_impact_clip?: [number, number] | null;
  position_impact_clip_basis?: string | null;
  /** How many holdings landed in the engine's UNCLASSIFIED sector bucket. */
  unclassified_bucket_member_count?: number | null;
  /** The engine's own prose on that bucket, rendered verbatim when present. */
  bucket_disclosure?: string | null;
  volatility_adjustment?: {
    basis?: string | null;
    reference_annualized_volatility?: number | null;
  } | null;
  co_movement?: {
    basis?: string | null;
    is_applied_to_the_shock?: boolean | null;
  } | null;
  /** Everything else the engine publishes; rendered nowhere on this page. */
  [key: string]: unknown;
}

/**
 * How the engine says it produced the numbers above it.
 *
 * `StressTestResponse` (`src/types/index.ts:710`) declares `methodology` and
 * nothing else from this block, but the route sends all of it
 * (`analytics_engine.py:4736-4751`) and the refusal payload mirrors the success
 * payload key-for-key with nulls (`analytics_engine.py:7094-7112`) — hence every
 * field optional and nullable rather than given a fallback the page would then
 * present as the engine's own words.
 *
 * The page renders these verbatim. They are what stop it describing a
 * `deterministic_factor_proxy` as a simulation: `impact_basis`,
 * `max_drawdown_basis`, `recovery_time_basis` and `confidence_basis` each name
 * the derivation, and two of them say `not_simulated` in as many words.
 */
interface StressDisclosures {
  /** `portfolio_impact * 1.15` — a fixed uplift on the same proxy. */
  max_drawdown_basis?: string | null;
  max_drawdown_formula?: string | null;
  impact_basis?: string | null;
  /** The scenario's configured month estimate, not a measured recovery. */
  recovery_time_basis?: string | null;
  /** A nominal label with no distribution behind it. */
  confidence_basis?: string | null;
  shock_inputs?: StressShockInputs | null;
  methodology?: string | null;
}

interface StressTestResult extends StressDisclosures {
  scenario: string;
  scenario_description?: string;
  max_drawdown: number | null;
  portfolio_impact: number | null;
  position_impacts: Record<string, number>;
  recovery_time: number | null;
  confidence_level?: number;
  error?: string;
  /**
   * The newest delivered daily observation this scenario's returns were built
   * from. Per scenario, not per page: each run re-measures on its own window,
   * so the provenance line below is bound to the ACTIVE scenario's result.
   */
  latest_observation_date?: string | null;
  data_status?: string | null;
  warnings?: string[] | null;
  universe_coverage?: {
    missing_tickers?: string[] | null;
  } | null;
}

/**
 * The basis fields the disclosure renders, in the order the figures appear on
 * the page. `formula` is an optional second field shown in parentheses.
 *
 * Keyed by property access rather than a string index so a rename of a field on
 * `StressDisclosures` is a compile error here instead of a row that silently
 * renders "not published by this response".
 */
const BASIS_ROWS: ReadonlyArray<{
  label: string;
  basis: keyof StressDisclosures;
  formula?: keyof StressDisclosures;
}> = [
  { label: 'Portfolio impact', basis: 'impact_basis' },
  { label: 'Max drawdown', basis: 'max_drawdown_basis', formula: 'max_drawdown_formula' },
  { label: 'Recovery time', basis: 'recovery_time_basis' },
  { label: 'Confidence level', basis: 'confidence_basis' },
];

/**
 * One basis field, or `undefined`/`null` when the response omitted it.
 *
 * Deliberately not defaulted. The engine's refusal payload
 * (`analytics_engine.py:7094-7112`) mirrors the success payload with nulls, so
 * an absent basis is a real absence and the panel says so — a hardcoded
 * fallback string here would be this page inventing the engine's wording,
 * which is exactly what the disclosure exists to stop.
 */
const basisOf = (result: StressTestResult, field: keyof StressDisclosures): string | undefined => {
  const value = result[field];
  return typeof value === 'string' && value.length > 0 ? value : undefined;
};

/**
 * The scalars of `shock_inputs` a reader needs to interpret the result.
 *
 * Every line is a backend value or a backend string; nothing here computes a
 * number. `market_shock` is a signed fraction return
 * (`units.market_shock`, `analytics_engine.py:4697`), so it is rendered through
 * the page's single fraction→percent conversion rather than printed raw.
 */
const shockSummary = (
  shock: StressShockInputs | null | undefined
): ReadonlyArray<{ label: string; value: string }> => {
  if (!shock) return [];
  const rows: Array<{ label: string; value: string }> = [];

  if (typeof shock.market_shock === 'number' && Number.isFinite(shock.market_shock)) {
    const shockPct = (shock.market_shock * 100).toFixed(1);
    rows.push({
      label: 'Applied market shock',
      value: `${shock.market_shock > 0 ? '+' : ''}${shockPct}%${shock.market_shock_basis ? ` (${shock.market_shock_basis})` : ''}`,
    });
  }
  if (typeof shock.position_impact_clip === 'object' && Array.isArray(shock.position_impact_clip)) {
    const [lo, hi] = shock.position_impact_clip;
    rows.push({
      label: 'Position impact clip',
      value:
        typeof lo === 'number' && typeof hi === 'number'
          ? `${(lo * 100).toFixed(1)}% to ${(hi * 100).toFixed(1)}%${shock.position_impact_clip_basis ? ` (${shock.position_impact_clip_basis})` : ''}`
          : 'not published by this response',
    });
  }
  if (shock.sector_elasticity_basis) {
    rows.push({ label: 'Sector elasticity', value: String(shock.sector_elasticity_basis) });
  }
  if (shock.volatility_adjustment?.basis) {
    const ref = shock.volatility_adjustment.reference_annualized_volatility;
    rows.push({
      label: 'Volatility adjustment',
      value:
        typeof ref === 'number' && Number.isFinite(ref)
          ? `${shock.volatility_adjustment.basis} (reference ${(ref * 100).toFixed(0)}%)`
          : String(shock.volatility_adjustment.basis),
    });
  }
  if (shock.co_movement?.basis) {
    rows.push({
      label: 'Co-movement',
      value:
        shock.co_movement.is_applied_to_the_shock === false
          ? `${shock.co_movement.basis} (measured, NOT applied to the shock)`
          : String(shock.co_movement.basis),
    });
  }
  if (typeof shock.unclassified_bucket_member_count === 'number') {
    rows.push({
      label: 'UNCLASSIFIED bucket',
      value: `${shock.unclassified_bucket_member_count} holding(s)`,
    });
  }
  if (shock.bucket_disclosure) {
    rows.push({ label: 'UNCLASSIFIED disclosure', value: String(shock.bucket_disclosure) });
  }
  return rows;
};

interface Scenario {
  name: string;
  type: 'Historical' | 'Hypothetical';
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  color_class: string;
}

interface ExplainerContent {
  title: string;
  category: string;
  formula?: string;
  whatItMeans: string;
  howInferred: string;
  whyImportant: string;
  howToInterpret: string[];
}

const EXPLAINERS: Record<string, ExplainerContent> = {
  worst_case: {
    title: 'Worst-Case Scenario Drawdown',
    category: 'Tail Risk & Stress Peak',
    formula: '$$\\text{Worst Case Impact} = \\min_{s \\in \\mathcal{S}} \\sum_{i=1}^N w_i \\times \\Delta r_{i,s}$$',
    whatItMeans: 'The largest proxy portfolio loss among all evaluated historical crises and hypothetical macroeconomic shocks (e.g. 2008 Lehman crash or 2020 COVID shock). It is the worst of several deterministic factor shocks, not the deepest point of a simulated price path.',
    howInferred: 'Computed by aggregating constituent-level stress drawdowns under each scenario, weighted by portfolio position allocations, and selecting the most severe negative impact.',
    whyImportant: 'Reveals your portfolio’s maximum capital vulnerability during catastrophic liquidity panics, helping determine required cash cushions and tail-risk hedges.',
    howToInterpret: [
      'Worst-case drawdown < -35%: High vulnerability to severe liquidity shocks. Review high-beta holdings.',
      'Worst-case drawdown -20% to -35%: Typical equity portfolio tail risk; manageable with 18-24 month recovery horizon.',
      'Worst-case drawdown > -20%: Highly defensive allocation with strong capital preservation characteristics.'
    ]
  },
  best_case: {
    title: 'Best-Case / Least Severe Stress Impact',
    category: 'Mild Shock Baseline',
    formula: '$$\\text{Best Case Impact} = \\max_{s \\in \\mathcal{S}} \\sum_{i=1}^N w_i \\times \\Delta r_{i,s}$$',
    whatItMeans: 'The mildest loss across all evaluated stress scenarios (typically minor monetary tightening or moderate sector rotations).',
    howInferred: 'Identified by finding the minimum drawdown (least negative portfolio return) across every stress scenario that has been evaluated. Each one is a deterministic factor shock proxy — no path sampling, no simulated return.',
    whyImportant: 'Establishes a lower bound for expected portfolio drawdowns during routine macroeconomic market turbulence.',
    howToInterpret: [
      'Drawdowns around -10% to -15% represent normal market pullbacks.',
      'If best-case loss is still worse than -20%, the portfolio lacks non-correlated defensive hedges.'
    ]
  },
  avg_impact: {
    title: 'Average Stress Impact',
    category: 'Macro Resilience Average',
    formula: '$$\\overline{\\text{Impact}} = \\frac{1}{|\\mathcal{S}|} \\sum_{s \\in \\mathcal{S}} \\text{Impact}_s$$',
    whatItMeans: 'The arithmetic mean loss across all tested scenarios, representing typical portfolio behavior under adverse market shocks.',
    howInferred: 'Calculated by summing the total portfolio impact across all tested scenarios and dividing by the number of scenarios executed.',
    whyImportant: 'Provides a consolidated summary of portfolio resilience across diverse shocks (monetary tightening, panic spikes, recessions, and sector de-ratings).',
    howToInterpret: [
      'Average impact < -25%: Aggressive growth tilt with high systematic market sensitivity.',
      'Average impact -15% to -25%: Balanced portfolio behavior across varying shock conditions.',
      'Average impact > -15%: Defensive allocation with strong drawdown buffers.'
    ]
  },
  scenarios_tested: {
    title: 'Stress Test Scenario Coverage',
    category: 'Risk Engine Coverage',
    formula: '$$\\text{Coverage} = \\frac{N_{\\text{executed}}}{N_{\\text{total}}}$$',
    whatItMeans: 'The number of standard institutional stress scenarios and custom user shocks currently evaluated against your portfolio.',
    howInferred: 'Tracked dynamically as scenarios are executed against live price series via the Daisy Risk Engine API.',
    whyImportant: 'Testing fewer than all scenarios creates blind spots in interest rate, liquidity, or sector-specific risks.',
    howToInterpret: [
      'Always aim for 4 of 4 standard scenarios tested to ensure complete risk visibility.',
      'Use the "Run All Scenarios" button to evaluate all models concurrently in a single click.'
    ]
  },
  market_crash: {
    title: 'Market Crash / 2008 Financial Crisis Scenario',
    category: 'Historical Systemic Crisis',
    formula: '$$\\text{Impact}_i = -35\\% \\times \\min\\left(2.8, \\max\\left(0.5, \\frac{\\sigma_i}{\\sigma_{\\text{market}}}\\right)\\right)$$',
    whatItMeans: 'Applies a -35% NIFTY base market shock, modelled on the 2008 Global Financial Crisis, to every holding.',
    howInferred: "Each stock's drawdown is scaled by its measured annualized volatility against a fixed reference level, held inside a configured band. The factors and their basis are published per ticker in `shock_inputs.volatility_adjustment`.",
    whyImportant: 'Tests portfolio survival during systemic liquidation events where market liquidity vanishes and asset correlations spike towards 1.0.',
    howToInterpret: [
      'Every holding takes the same base market shock, scaled by its sector elasticity and by its measured volatility. The two factors and their basis are published per ticker in `shock_inputs`; the drawdown this scenario lands on each holding is the drawdown column of its own table.',
      'A holding classified into a lower-elasticity sector takes a smaller share of that base shock. The multiplier this engine applies to each sector is published in `shock_inputs.sector_elasticity_table` and is a configured table, not a measurement of this book.',
      'The recovery figure on the card is this scenario’s configured month estimate, not a simulated recovery path.'
    ]
  },
  interest_rate_shock: {
    title: '300bp Interest Rate Shock Scenario',
    category: 'Hypothetical Monetary Shock',
    formula: '$$\\text{Impact}_i = -15\\% \\times \\text{VolFactor}_i$$',
    whatItMeans: 'Applies a -15% base market shock for a 300 basis point (+3.00%) policy rate increase by the RBI / US Federal Reserve to curb inflationary spikes.',
    howInferred: 'Scales an immediate equity discount rate expansion and multiple compression across portfolio constituents based on individual asset volatility.',
    whyImportant: 'Evaluates capital cost inflation, debt-servicing headwinds, and growth valuation contraction across corporate balance sheets.',
    howToInterpret: [
      'Capital-intensive and leveraged businesses experience steeper drawdowns.',
      'Cash-rich companies and defensive yield assets outperform.',
      'The recovery figure on the card is this scenario’s configured month estimate, not a simulated recovery path.'
    ]
  },
  volatility_spike: {
    title: 'COVID-19 / Panic Volatility Spike Scenario',
    category: 'Historical Panic Liquidation',
    formula: '$$\\text{Impact}_i = -22\\% \\times \\text{VolFactor}_i$$',
    whatItMeans: 'Applies a -22% base market shock for an abrupt panic-driven volatility spike (India VIX > 40) replicating the March 2020 COVID-19 pandemic drawdown.',
    howInferred: 'Models immediate risk-off market selling across all asset classes with volatility-scaled position drawdowns.',
    whyImportant: 'Tests whether short-term panic drawdowns cause margin breaches or forced portfolio liquidations before markets rebound.',
    howToInterpret: [
      'This is a scaled factor shock, not a replay of the 2020 tape.',
      'The recovery figure on the card is this scenario’s configured month estimate, not a simulated recovery path.',
      'Ensure adequate liquidity buffers to prevent panic selling at market troughs.'
    ]
  },
  tech_sector_correction: {
    title: 'Tech & Growth Sector De-Rating',
    category: 'Hypothetical Sector Shock',
    formula: '$$\\text{Impact}_i = -18\\% \\times \\text{VolFactor}_i$$',
    whatItMeans: 'Applies a -18% base market shock for a targeted valuation de-rating and growth multiple contraction across technology, software, and digital services companies.',
    howInferred: 'Applies sector-weighted shocks based on historical tech drawdowns and beta loadings.',
    whyImportant: 'Highlights single-sector concentration risks and valuation vulnerability in high P/E growth stocks.',
    howToInterpret: [
      'High growth stocks are shocked hardest by the sector elasticity table; traditional value assets are shocked less.',
      'Diversifying into utilities, healthcare, and FMCG mitigates tech de-rating risk.'
    ]
  },
  custom_scenario: {
    title: 'Custom Scenario Shock',
    category: 'Custom Parameterized Shock',
    formula: '$$\\text{Custom Impact}_i = \\text{Shock}_{\\text{user}} \\times \\text{VolFactor}_i$$',
    whatItMeans: 'Allows portfolio managers to input bespoke market shocks (e.g. -25% geopolitical tension, -12% budget announcement) and evaluate customized portfolio drawdowns.',
    howInferred: 'The engine applies your custom market shock percentage and scales individual constituent impacts by active volatility factors.',
    whyImportant: 'Enables tailored stress testing for specific upcoming macroeconomic events, policy announcements, or geopolitical risks.',
    howToInterpret: [
      'Enter a market shock percentage (e.g. -20 for a 20% decline).',
      'Use this to stress test specific downside scenarios tailored to your investment thesis.'
    ]
  },
  position_impacts: {
    title: 'Position-Level Stress Breakdown',
    category: 'Constituent Risk Triage',
    formula: '$$\\text{Loss}_i = w_i \\times \\text{Impact}_i$$',
    whatItMeans: 'Displays each individual stock’s projected percentage decline and risk severity tier under the currently selected stress test scenario.',
    howInferred: 'Calculated via univariate volatility scaling against the scenario’s base market shock: $\\text{Impact}_i = \\text{Shock}_{\\text{scenario}} \\times \\text{VolFactor}_i$.',
    whyImportant: 'Pinpoints exactly which individual holdings drive the majority of your portfolio’s downside loss during stress events.',
    howToInterpret: [
      'Critical (<-25%): Severe drawdown risks; enforce position sizing caps (<5% weight).',
      'High (-15% to -25%): Moderate to high cyclical volatility.',
      'Medium (-5% to -15%): Controlled, resilient market performance.',
      'Low (>-5%): Outstanding capital preservation and defense.'
    ]
  },
  severity_grading: {
    title: 'Stress Severity Grading Levels',
    category: 'Institutional Risk Tiers',
    formula: '$$\\text{Severity} = \\begin{cases} \\text{Critical} & \\text{Impact} < -25\\% \\\\ \\text{High} & -25\\% \\le \\text{Impact} < -15\\% \\\\ \\text{Medium} & -15\\% \\le \\text{Impact} < -5\\% \\\\ \\text{Low} & \\text{Impact} \\ge -5\\% \\end{cases}$$',
    whatItMeans: 'A standardized 4-tier risk classification indicating the severity of projected capital impairment for each holding.',
    howInferred: 'Derived directly from the position’s proxy percentage impact under the active scenario (`impact_basis`).',
    whyImportant: 'Provides instantaneous visual triage so managers know which positions require stop-loss orders or dynamic hedging.',
    howToInterpret: [
      'Critical positions require strict stop-loss rules or smaller portfolio allocations.',
      'A resilient portfolio should have fewer than 30% of constituents in the Critical category.'
    ]
  },
  recovery_analysis: {
    title: 'Mean Time to Recovery (MTTR)',
    category: 'Liquidity & Horizon Duration',
    formula: '$$\\text{Average Recovery} = \\frac{1}{|\\mathcal{S}|} \\sum_{s \\in \\mathcal{S}} \\text{Recovery Months}_s$$',
    whatItMeans: 'The number of months each scenario is configured to assume before the book is treated as recovered.',
    howInferred: 'Read off the scenario table as a fixed month estimate and published unchanged (`recovery_time_basis`: configured_recovery_estimate_not_simulated). No rebound path is measured or simulated — a different scenario with the same shape of shock carries a different estimate, not a measurement.',
    whyImportant: 'Ensures investment horizons and cash reserve buffers are aligned so investors are never forced to liquidate assets at market bottoms.',
    howToInterpret: [
      'Recovery > 18 months: Requires long-term investment horizon and dedicated cash reserves.',
      'Recovery 6-12 months: Typical cyclical correction timeline.',
      'Recovery < 6 months: Swift event-driven rebound.'
    ]
  }
};

interface HelpExplainerModalProps {
  itemKey: string | null;
  onClose: () => void;
}

function HelpExplainerModal({ itemKey, onClose }: HelpExplainerModalProps) {
  if (!itemKey || !EXPLAINERS[itemKey]) return null;
  const exp = EXPLAINERS[itemKey];

  return (
    // Radix owns Escape, the focus trap and focus restore; the backdrop click
    // it adds on top of the `onClose` below is the behaviour this panel had.
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        overlayClassName="bg-black/60 backdrop-blur-sm"
        className="max-w-2xl gap-0 sm:rounded-2xl dark:bg-gray-900 shadow-2xl max-h-[90vh] overflow-y-auto relative text-gray-900 dark:text-gray-100"
      >
        {/* Header */}
        <div className="flex items-start justify-between pb-4 border-b border-gray-100 dark:border-gray-800">
          <div className="flex items-center space-x-3">
            <div className="p-2.5 rounded-xl bg-orange-50 dark:bg-orange-950/40 text-orange-600 dark:text-orange-400 border border-orange-200/50 dark:border-orange-800/40">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-orange-600 dark:text-orange-400">
                {exp.category}
              </span>
              <DialogTitle className="text-xl font-bold leading-normal text-gray-900 dark:text-white">
                {exp.title}
              </DialogTitle>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="mt-6 space-y-6 text-sm leading-relaxed">
          {/* What it means */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1.5 flex items-center gap-1.5">
              <Info className="w-3.5 h-3.5 text-blue-500" />
              What this metric means
            </h3>
            <p className="text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800/60 p-3.5 rounded-xl border border-gray-100 dark:border-gray-800">
              {exp.whatItMeans}
            </p>
          </div>

          {/* Formula */}
          {exp.formula && (
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1.5 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-amber-500" />
                Mathematical Formulation
              </h3>
              <div className="bg-orange-50/50 dark:bg-orange-950/20 text-orange-900 dark:text-orange-200 font-mono text-xs p-3.5 rounded-xl border border-orange-200/40 dark:border-orange-900/30 overflow-x-auto">
                {exp.formula}
              </div>
            </div>
          )}

          {/* How it is calculated */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1.5 flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-purple-500" />
              How it is inferred & calculated
            </h3>
            <p className="text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800/60 p-3.5 rounded-xl border border-gray-100 dark:border-gray-800">
              {exp.howInferred}
            </p>
          </div>

          {/* Why it is important */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1.5 flex items-center gap-1.5">
              <ShieldAlert className="w-3.5 h-3.5 text-red-500" />
              Why it is critical for risk management
            </h3>
            <p className="text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800/60 p-3.5 rounded-xl border border-gray-100 dark:border-gray-800">
              {exp.whyImportant}
            </p>
          </div>

          {/* How to interpret */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-2 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-emerald-500" />
              How to infer & act on these values
            </h3>
            <div className="space-y-2">
              {exp.howToInterpret.map((rule, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-2.5 bg-emerald-50/40 dark:bg-emerald-950/20 text-emerald-950 dark:text-emerald-200 p-3 rounded-xl border border-emerald-200/40 dark:border-emerald-900/30 text-xs"
                >
                  <ChevronRight className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                  <span>{rule}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-6 pt-4 border-t border-gray-100 dark:border-gray-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 text-xs font-semibold bg-orange-600 hover:bg-orange-700 text-white rounded-xl transition-colors shadow-sm"
          >
            Got it, close
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function HelpBtn({ itemKey, onOpen }: { itemKey: string; onOpen: (key: string) => void }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onOpen(itemKey);
      }}
      className="inline-flex items-center justify-center w-5 h-5 rounded-full text-gray-400 hover:text-orange-600 dark:hover:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-950/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 focus-visible:ring-offset-2"
      title="Click to understand what this means and how it is calculated"
      aria-label="Help"
    >
      <HelpCircle className="w-3.5 h-3.5" />
    </button>
  );
}

export default function StressTestingPage() {
  /**
   * The four built-in scenarios, named only.
   *
   * The prose that used to sit here — "(-35% NIFTY shock)", "(-15% shock)" —
   * asserted a shock magnitude the page held as a hand-typed string rather than
   * as data, for a magnitude the engine resolves at
   * `analytics_engine.py:4308-4379` and republishes twice: as
   * `scenario_description` and as `shock_inputs.market_shock`. So the
   * description rendered on a card is the engine's, and this seed is only what
   * the card shows before a scenario has ever run (`describedFor` below).
   */
  const [scenarios, setScenarios] = useState<Scenario[]>([
    {
      name: 'Market Crash',
      type: 'Historical',
      description: 'Global financial crisis scenario, 2008',
      icon: AlertTriangle,
      color_class: 'text-red-500'
    },
    {
      name: 'Interest Rate Shock',
      type: 'Hypothetical',
      description: '300bp RBI / central bank rate increase scenario',
      icon: TrendingDown,
      color_class: 'text-orange-500'
    },
    {
      name: 'Volatility Spike',
      type: 'Hypothetical',
      description: 'COVID-19 market panic volatility scenario',
      icon: Activity,
      color_class: 'text-blue-500'
    },
    {
      name: 'Tech Sector Correction',
      type: 'Hypothetical',
      description: 'Major technology and growth multiple decline',
      icon: TestTube,
      color_class: 'text-purple-500'
    },
  ]);

  const [stressResults, setStressResults] = useState<Record<string, StressTestResult>>({});
  const [activeScenarioName, setActiveScenarioName] = useState<string>('Market Crash');
  const [activeExplainer, setActiveExplainer] = useState<string | null>(null);
  const [customScenario, setCustomScenario] = useState({
    name: '',
    market_shock: '',
    type: 'Hypothetical' as 'Historical' | 'Hypothetical'
  });
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [runningAll, setRunningAll] = useState(false);
  const runSeq = useRef(0);

  const { positions, fetchPortfolio } = usePortfolioStore();

  const runStressTest = async (scenarioName: string) => {
    setLoading(true);
    setRunError(null);
    try {
      const data = await analyticsApi.runStressTest({
        scenario: scenarioName
      });
      setStressResults(prev => ({
        ...prev,
        [scenarioName]: data
      }));
      setActiveScenarioName(scenarioName);
    } catch (error) {
      console.error('Failed to run stress test:', error);
      setRunError(error instanceof Error ? error.message : 'Failed to run stress test');
    } finally {
      setLoading(false);
    }
  };

  const runAllScenarios = async () => {
    const seq = ++runSeq.current;
    setRunningAll(true);
    setLoading(true);
    setRunError(null);
    try {
      const results: Record<string, StressTestResult> = {};
      const failures: string[] = [];
      for (const sc of scenarios) {
        if (seq !== runSeq.current) return;
        try {
          const data = await analyticsApi.runStressTest({
            scenario: sc.name
          });
          results[sc.name] = data;
        } catch (e) {
          console.error(`Failed to run scenario ${sc.name}:`, e);
          failures.push(sc.name);
        }
      }
      if (seq !== runSeq.current) return;
      setStressResults(prev => ({ ...prev, ...results }));
      const firstSuccess = Object.keys(results)[0];
      if (firstSuccess) {
        setActiveScenarioName(firstSuccess);
      }
      if (failures.length > 0) {
        setRunError(`${failures.length} of ${scenarios.length} scenarios failed (${failures.join(', ')}).`);
      }
    } finally {
      setRunningAll(false);
      setLoading(false);
    }
  };

  const runCustomStressTest = async () => {
    if (!customScenario.name || !customScenario.market_shock) {
      setRunError('Please fill in all required fields');
      return;
    }

    setLoading(true);
    setRunError(null);
    try {
      const shockPct = Number(customScenario.market_shock);
      const data = await analyticsApi.runStressTest({
        scenario: `Custom: ${customScenario.name} (${shockPct}%)`,
        tickers: positions.map(p => p.ticker)
      });

      if (data.error || data.portfolio_impact == null) {
        setRunError(typeof data.error === 'string' ? data.error : 'Stress test returned no computable impact for this shock.');
        return;
      }
      
      // The engine resolves a custom scenario by PARSING the percentage out of
      // the scenario text (`analytics_engine.py:4389-4393`) and republishes what
      // it actually applied as `scenario_description` plus
      // `shock_inputs.market_shock`. The seed below is only what the card shows
      // for the moment before that response exists; `describedFor` prefers the
      // engine's own string for every branch, custom included.
      const newScenario: Scenario = {
        name: customScenario.name,
        type: customScenario.type,
        description: `${shockPct}% market shock`,
        icon: TestTube,
        color_class: 'text-emerald-500'
      };
      
      setScenarios(prev => [...prev, newScenario]);
      setStressResults(prev => ({
        ...prev,
        [customScenario.name]: data
      }));
      setActiveScenarioName(customScenario.name);
      
      setShowCustomForm(false);
      setCustomScenario({ name: '', market_shock: '', type: 'Hypothetical' });
    } catch (error) {
      console.error('Failed to run custom stress test:', error);
      setRunError(error instanceof Error ? error.message : 'Failed to run custom stress test');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
  }, []);

  useEffect(() => {
    if (positions.length > 0 && Object.keys(stressResults).length === 0) {
      runAllScenarios();
    }
    return () => {
      // Cancel in-flight auto-run on unmount / positions change
      runSeq.current++;
    };
  }, [positions]);

  /**
   * FRACTION in, percent out.
   *
   * The engine declares both impact fields as fractions:
   *   `analytics_engine.py:4431` `"portfolio_impact": "fraction_of_portfolio_value"`
   *   `analytics_engine.py:4432` `"position_impacts": "fraction_of_position_value"`
   *
   * Every one of the four places that used to sniff the scale
   * (`Math.abs(v) <= 1.0 && v !== 0 ? v * 100 : v`) has the same contract, so
   * the scale lives in ONE place now. The sniff multiplied exactly the
   * legitimate in-window values and left the ones a leveraged book can actually
   * produce unscaled — a -1.5 (a 150% loss) printed as "-1.5%". The `!== 0`
   * clause shows the sniff was narrowed once and never removed; a measured 0
   * renders as "0.0%" either way, so it bought nothing.
   */
  const impactPercent = (value: number | null | undefined): number | null => {
    if (value === undefined || value === null || isNaN(value)) return null;
    return value * 100;
  };

  const formatPercentage = (value: number | undefined | null, decimals = 1) => {
    const pct = impactPercent(value);
    return pct === null ? 'N/A' : `${pct >= 0 ? '+' : ''}${pct.toFixed(decimals)}%`;
  };

  const getImpactColor = (impact: number | null | undefined): string => {
    const pct = impactPercent(impact);
    if (pct === null) return 'text-gray-400 dark:text-gray-500';
    if (pct < -25) return 'text-red-600 dark:text-red-400';
    if (pct < -15) return 'text-orange-600 dark:text-orange-400';
    if (pct < -5) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-green-600 dark:text-green-400';
  };

  const getImpactBgColor = (impact: number | null | undefined): string => {
    const pct = impactPercent(impact);
    if (pct === null) return 'bg-gray-50 dark:bg-gray-800/40 border-gray-200 dark:border-gray-700';
    if (pct < -25) return 'bg-red-50 dark:bg-red-950/20 border-red-200 dark:border-red-800';
    if (pct < -15) return 'bg-orange-50 dark:bg-orange-950/20 border-orange-200 dark:border-orange-800';
    if (pct < -5) return 'bg-yellow-50 dark:bg-yellow-950/20 border-yellow-200 dark:border-yellow-800';
    return 'bg-green-50 dark:bg-green-950/20 border-green-200 dark:border-green-800';
  };

  /**
   * The description a scenario card shows.
   *
   * The engine resolves the scenario name to its own config row
   * (`analytics_engine.py:4305-4393`) and republishes the row's description as
   * `scenario_description`. Every card used to ignore that and print a
   * hand-typed string instead, so a page copy drift (the page said "NIFTY 50"
   * where the engine said "NIFTY") was invisible. Prefer the engine's word for
   * every branch — built-in and custom alike — and fall back to the seed only
   * for a scenario that has not run yet.
   */
  const describedFor = (scenario: Scenario, result?: StressTestResult): string =>
    result?.scenario_description || scenario.description;

  const severityFor = (rawImpact: number | null | undefined): { label: string; className: string } | null => {
    const impactVal = impactPercent(rawImpact);
    if (impactVal === null) return null;
    const severity = impactVal < -25 ? 'Critical' : impactVal < -15 ? 'High' : impactVal < -5 ? 'Medium' : 'Low';
    const colorClass = severity === 'Critical' ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 border-red-200 dark:border-red-800' :
                      severity === 'High' ? 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300 border-orange-200 dark:border-orange-800' :
                      severity === 'Medium' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300 border-yellow-200 dark:border-yellow-800' :
                      'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800';
    return { label: severity, className: colorClass };
  };

  // Derive active position table data based on activeScenarioName
  const activeResult = stressResults[activeScenarioName];
  const positionData = useMemo<StressImpactRow[]>(() => {
    if (!activeResult || !activeResult.position_impacts) return [];
    return Object.entries(activeResult.position_impacts).map(([ticker, impact]) => ({
      ticker,
      impact,
      change: impact
    }));
  }, [activeResult]);

  // Position impact table columns
  const positionColumns: DataTableColumn<StressImpactRow>[] = [
    {
      header: 'Ticker',
      accessorKey: 'ticker',
      cell: ({ row }) => {
        const data = row.original;
        return (
          <div className="flex items-center space-x-2">
            <span className="font-semibold text-gray-900 dark:text-white">
              {data.ticker}
            </span>
          </div>
        );
      },
    },
    {
      // `impact_basis` is `deterministic_factor_proxy`: the column carries a
      // scaled shock, not a simulated return. Naming it a simulation here is
      // what the whole disclosure below this page exists to stop.
      header: 'Stress Impact (proxy)',
      accessorKey: 'impact',
      cell: ({ row }) => {
        const data = row.original;
        return (
          <div className={`font-semibold ${getImpactColor(data.impact)}`}>
            {formatPercentage(data.impact, 1)}
          </div>
        );
      },
    },
    {
      header: 'Severity Level',
      accessorKey: 'severity_level',
      cell: ({ row }) => {
        const data = row.original;
        const sev = severityFor(data.impact);
        if (!sev) {
          return (
            <span className="px-2.5 py-1 text-xs rounded-full font-semibold border bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400 border-gray-200 dark:border-gray-600">
              N/A
            </span>
          );
        }
        return (
          <span className={`px-2.5 py-1 text-xs rounded-full font-semibold border ${sev.className}`}>
            {sev.label}
          </span>
        );
      },
    },
  ];

  const handleExportCSV = () => {
    if (!positionData || positionData.length === 0) return;
    const headers = ['Ticker', 'Scenario', 'Impact', 'Severity'];
    const rows = positionData
      .map(p => {
        const sev = severityFor(p.impact);
        return [
          p.ticker,
          activeScenarioName,
          formatPercentage(p.impact, 2),
          sev ? sev.label : 'N/A'
        ].map(escapeCsvCell).join(',');
      });
    const csvContent = [headers.map(escapeCsvCell).join(','), ...rows].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `stress-impact-${activeScenarioName.toLowerCase().replace(/\s+/g, '-')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Calculate summary metrics (null until at least one scenario returns a value)
  const stressTestResults = Object.values(stressResults);
  const impacts = stressTestResults.map(r => r.portfolio_impact).filter((v): v is number => v != null);
  const worstCase = impacts.length > 0 ? Math.min(...impacts) : null;
  const bestCase = impacts.length > 0 ? Math.max(...impacts) : null;
  const avgImpact = impacts.length > 0 ? (impacts.reduce((sum: number, v) => sum + v, 0) / impacts.length) : null;
  const worstCaseScenario = worstCase != null
    ? (stressTestResults.find(r => r.portfolio_impact === worstCase)?.scenario ?? null)
    : null;
  const recoveryTimes = stressTestResults
    .map(r => r.recovery_time)
    .filter((v): v is number => v != null);
  const avgRecovery = recoveryTimes.length > 0
    ? recoveryTimes.reduce((sum, v) => sum + v, 0) / recoveryTimes.length
    : null;

  return (
    <div className="space-y-6">
      {/* Help Explainer Modal */}
      <HelpExplainerModal
        itemKey={activeExplainer}
        onClose={() => setActiveExplainer(null)}
      />

      {/* Hero Section */}
      <div className="bg-gradient-to-r from-orange-600 via-red-600 to-amber-700 rounded-2xl p-6 text-white shadow-lg relative overflow-hidden">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2.5 py-0.5 text-xs font-semibold bg-white/20 rounded-full">
                Multi-Factor Shock Proxy
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
              Stress Testing & Scenario Analysis
            </h1>
            <p className="text-orange-100 text-sm mt-1 max-w-2xl">
              Deterministic factor shocks for historical liquidity freezes, monetary tightening, panic volatility spikes, and custom macro drawdowns, applied across portfolio holdings. No path sampling is run — every figure below publishes the basis it was derived on.
            </p>
            <div className="flex flex-wrap items-center mt-3 gap-4 text-xs text-orange-200">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                Scenarios evaluated: <strong className="text-white">{stressTestResults.length} of {scenarios.length}</strong>
              </div>
              <div>•</div>
              <div>Portfolio positions: <strong className="text-white">{positions.length}</strong></div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={runAllScenarios}
              disabled={runningAll || loading}
              className="flex items-center px-4 py-2 text-xs font-semibold bg-white text-orange-700 hover:bg-orange-50 rounded-xl transition-all shadow-sm disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${runningAll ? 'animate-spin' : ''}`} />
              {runningAll ? 'Running All...' : 'Run All Scenarios'}
            </button>
            <button
              onClick={() => setShowCustomForm(!showCustomForm)}
              className="flex items-center px-4 py-2 text-xs font-semibold bg-white/20 hover:bg-white/30 text-white rounded-xl transition-all backdrop-blur-sm border border-white/20"
            >
              <Plus className="w-3.5 h-3.5 mr-1.5" />
              Custom Shock
            </button>
            <HelpBtn itemKey="custom_scenario" onOpen={setActiveExplainer} />
          </div>
        </div>
      </div>

      {/* Provenance for the ACTIVE scenario. Each run re-measures on its own
          window, so a page-level date would describe whichever scenario ran
          last, not the one on screen. */}
      <SectionProvenance
        section={`Stress testing — ${activeScenarioName}`}
        asOf={activeResult?.latest_observation_date ?? null}
        coverage={sectionCoverage(activeResult?.universe_coverage)}
        warnings={activeResult?.warnings ?? null}
      />

      {/* Basis disclosure for the ACTIVE scenario. The engine already names how
          every figure on this page was produced — `impact_basis:
          deterministic_factor_proxy`, `recovery_time_basis:
          configured_recovery_estimate_not_simulated`, and so on
          (`analytics_engine.py:4736-4751`). None of it was rendered, which is
          how a page could badge itself a simulation engine while the response
          said in as many words that no path was sampled. Everything
          below is the engine's own string, printed verbatim: the page restates
          no derivation and supplies no fallback wording of its own. */}
      {activeResult && (
        <div
          data-testid="stress-basis-disclosure"
          className="bg-amber-50/60 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/40 rounded-xl p-5"
        >
          <div className="flex items-start gap-3 mb-3">
            <Info className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-bold text-amber-900 dark:text-amber-200">
                What these numbers are — {activeScenarioName}
              </h3>
              <p className="text-xs text-amber-800 dark:text-amber-300/90 mt-1">
                Reproduced from the API response. Each figure below is the basis the
                engine published for it; none of them is a sampled or simulated outcome.
              </p>
            </div>
          </div>

          <dl className="space-y-1.5 text-xs">
            {BASIS_ROWS.map(({ label, basis, formula }) => {
              const value = basisOf(activeResult, basis);
              return (
                <div key={label} className="flex flex-col sm:flex-row sm:items-baseline gap-0.5 sm:gap-3">
                  <dt className="font-semibold text-amber-900 dark:text-amber-200 sm:w-44 shrink-0">{label}</dt>
                  <dd className="font-mono text-amber-800 dark:text-amber-300/90 break-words">
                    {value ?? 'not published by this response'}
                    {value && formula && (
                      <span className="font-sans text-amber-700/80 dark:text-amber-400/70">
                        {' '}({basisOf(activeResult, formula)})
                      </span>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>

          {/* `shock_inputs` is the engine's own account of the shock it applied.
              The scalars that change what a reader should make of the result are
              the applied shock, its basis, the configured clip the impacts are
              held inside, and the count of holdings that fell into the
              UNCLASSIFIED sector bucket. The per-ticker maps in the same object
              are published but not charted on this page. */}
          {shockSummary(activeResult.shock_inputs).map(({ label, value }) => (
            <div key={label} className="flex flex-col sm:flex-row sm:items-baseline gap-0.5 sm:gap-3 mt-1.5 text-xs">
              <span className="font-semibold text-amber-900 dark:text-amber-200 sm:w-44 shrink-0">{label}</span>
              <span className="font-mono text-amber-800 dark:text-amber-300/90 break-words">{value}</span>
            </div>
          ))}

          {activeResult.methodology && (
            <div className="mt-4 pt-3 border-t border-amber-200/70 dark:border-amber-900/40">
              <div className="text-xs font-semibold uppercase tracking-wider text-amber-900 dark:text-amber-300 mb-1.5">
                Methodology (as published)
              </div>
              <p className="text-xs text-amber-800 dark:text-amber-300/90 leading-relaxed">
                {activeResult.methodology}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Custom Scenario Builder */}
      {showCustomForm && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6 border border-gray-200 dark:border-gray-700 animate-in fade-in duration-200">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <TestTube className="w-5 h-5 text-orange-600 dark:text-orange-400" />
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Create Custom Stress Test Scenario
              </h3>
              <HelpBtn itemKey="custom_scenario" onOpen={setActiveExplainer} />
            </div>
            <button
              onClick={() => setShowCustomForm(false)}
              className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              aria-label="Close custom scenario form"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
            <div>
              <label
                htmlFor="custom-scenario-name"
                className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5"
              >
                Scenario Name *
              </label>
              <input
                id="custom-scenario-name"
                type="text"
                value={customScenario.name}
                onChange={(e) => setCustomScenario(prev => ({ ...prev, name: e.target.value }))}
                className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-orange-500 focus:outline-none"
                placeholder="e.g. Geopolitical Oil Shock"
              />
            </div>
            <div>
              <label
                htmlFor="custom-scenario-market-shock"
                className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5"
              >
                Market Shock (%) *
              </label>
              <input
                id="custom-scenario-market-shock"
                type="number"
                value={customScenario.market_shock}
                onChange={(e) => setCustomScenario(prev => ({ ...prev, market_shock: e.target.value }))}
                className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-orange-500 focus:outline-none"
                placeholder="-20"
              />
            </div>
            <div className="flex items-end">
              <button
                onClick={runCustomStressTest}
                disabled={loading}
                className="w-full px-4 py-2 text-sm font-semibold bg-orange-600 hover:bg-orange-700 text-white rounded-lg transition-colors shadow-sm disabled:opacity-50"
              >
                {loading ? 'Evaluating...' : 'Run Stress Test'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Top 4 Key Stress Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="relative">
          <MetricCard
            title="Worst Case Scenario"
            value={formatPercentage(worstCase, 1)}
            icon={AlertTriangle}
            loading={loading && stressTestResults.length === 0}
          />
          <div className="absolute top-4 right-4">
            <HelpBtn itemKey="worst_case" onOpen={setActiveExplainer} />
          </div>
        </div>

        <div className="relative">
          <MetricCard
            title="Best Case Scenario"
            value={formatPercentage(bestCase, 1)}
            icon={TrendingDown}
            loading={loading && stressTestResults.length === 0}
          />
          <div className="absolute top-4 right-4">
            <HelpBtn itemKey="best_case" onOpen={setActiveExplainer} />
          </div>
        </div>

        <div className="relative">
          <MetricCard
            title="Average Impact"
            value={formatPercentage(avgImpact, 1)}
            icon={Activity}
            loading={loading && stressTestResults.length === 0}
          />
          <div className="absolute top-4 right-4">
            <HelpBtn itemKey="avg_impact" onOpen={setActiveExplainer} />
          </div>
        </div>

        <div className="relative">
          <MetricCard
            title="Scenarios Tested"
            value={`${stressTestResults.length} of ${scenarios.length}`}
            icon={TestTube}
            loading={loading}
          />
          <div className="absolute top-4 right-4">
            <HelpBtn itemKey="scenarios_tested" onOpen={setActiveExplainer} />
          </div>
        </div>
      </div>

      {/* Stress Test Scenarios Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {scenarios.map((scenario) => {
          const result = stressResults[scenario.name];
          const Icon = scenario.icon;
          const isSelected = activeScenarioName === scenario.name;
          const explainerKey = scenario.name === 'Market Crash' ? 'market_crash' :
                               scenario.name === 'Interest Rate Shock' ? 'interest_rate_shock' :
                               scenario.name === 'Volatility Spike' ? 'volatility_spike' :
                               scenario.name === 'Tech Sector Correction' ? 'tech_sector_correction' : 'custom_scenario';
          
          return (
            <div
              key={scenario.name}
              role="button"
              tabIndex={0}
              onClick={() => {
                if (result) {
                  setActiveScenarioName(scenario.name);
                }
              }}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && result) {
                  e.preventDefault();
                  setActiveScenarioName(scenario.name);
                }
              }}
              className={`bg-white dark:bg-gray-800 rounded-xl shadow-md p-5 border transition-all cursor-pointer relative ${
                isSelected
                  ? 'ring-2 ring-orange-500 border-orange-500 shadow-orange-500/10'
                  : result
                  ? `${getImpactBgColor(result.portfolio_impact)} hover:shadow-lg`
                  : 'border-gray-200 dark:border-gray-700 hover:border-gray-300'
              }`}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center space-x-2">
                  <Icon className={`w-5 h-5 ${scenario.color_class}`} />
                  <h3 className="text-base font-bold text-gray-900 dark:text-white">
                    {scenario.name}
                  </h3>
                </div>
                <div className="flex items-center gap-1">
                  {result && (
                    <span className={`px-2 py-0.5 text-xs rounded-full font-bold ${getImpactColor(result.portfolio_impact)}`}>
                      {formatPercentage(result.portfolio_impact, 1)}
                    </span>
                  )}
                  <HelpBtn itemKey={explainerKey} onOpen={setActiveExplainer} />
                </div>
              </div>
              
              <div className="space-y-2.5 text-xs">
                <div className="flex justify-between items-center text-gray-600 dark:text-gray-400">
                  <span>Scenario Type</span>
                  <span className="font-semibold text-gray-900 dark:text-white">{scenario.type}</span>
                </div>
                <div className="flex justify-between items-center text-gray-600 dark:text-gray-400">
                  <span>Description</span>
                  <span className="font-medium text-gray-900 dark:text-white text-right truncate max-w-[140px]" title={describedFor(scenario, result)}>
                    {describedFor(scenario, result)}
                  </span>
                </div>
                
                {result ? (
                  <>
                    <div className="flex justify-between items-center text-gray-600 dark:text-gray-400">
                      <span>Portfolio Impact</span>
                      <span className={`font-bold ${getImpactColor(result.portfolio_impact)}`}>
                        {formatPercentage(result.portfolio_impact, 1)}
                      </span>
                    </div>
                    {/* The figure above is a deterministic factor proxy, not a
                        sampled return. Print the engine's own basis token next
                        to it rather than describing it in this page's words. */}
                    {result.impact_basis && (
                      <div className="flex justify-between items-center gap-2 text-gray-500 dark:text-gray-500">
                        <span>Basis</span>
                        <span className="font-mono text-right truncate" title={result.impact_basis}>
                          {result.impact_basis}
                        </span>
                      </div>
                    )}
                    <div className="flex justify-between items-center text-gray-600 dark:text-gray-400">
                      <span>Recovery Time</span>
                      <span className="font-semibold text-gray-900 dark:text-white">
                        {result.recovery_time != null ? `${result.recovery_time} months` : 'N/A'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center text-gray-600 dark:text-gray-400">
                      <span>Confidence Level</span>
                      <span className="font-semibold text-gray-900 dark:text-white">
                        {result.confidence_level != null
                          ? `${result.confidence_level < 1 ? (result.confidence_level * 100).toFixed(0) : result.confidence_level}%`
                          : 'N/A'}
                      </span>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setActiveScenarioName(scenario.name);
                      }}
                      className={`w-full mt-2 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${
                        isSelected
                          ? 'bg-orange-600 text-white border-orange-600'
                          : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {isSelected ? '✓ Viewing Positions' : 'View Positions'}
                    </button>
                  </>
                ) : (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      runStressTest(scenario.name);
                    }}
                    disabled={loading}
                    className="w-full mt-3 px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white font-semibold rounded-lg transition-colors duration-200 disabled:opacity-50 flex items-center justify-center"
                  >
                    <Play className="w-3.5 h-3.5 mr-1.5" />
                    {loading ? 'Evaluating...' : 'Run Test'}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Position Impact Analysis Section */}
      {(runError || activeResult?.error) && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4 text-sm text-amber-800 dark:text-amber-200">
          {runError || activeResult?.error}
        </div>
      )}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-md border border-gray-200 dark:border-gray-700 overflow-hidden">
        <DataTable
          title={`Position-Level Impact Analysis (${activeScenarioName})`}
          data={positionData}
          columns={positionColumns}
          loading={loading}
          searchablePlaceholder="Search constituent ticker..."
          exportable={false}
          actions={
            <div className="flex items-center space-x-2">
              <HelpBtn itemKey="position_impacts" onOpen={setActiveExplainer} />
              <div className="flex items-center space-x-1.5 ml-2">
                <span className="text-xs text-gray-500 dark:text-gray-400 hidden sm:inline">Scenario:</span>
                <select
                  value={activeScenarioName}
                  onChange={(e) => {
                    const chosen = e.target.value;
                    setActiveScenarioName(chosen);
                    if (!stressResults[chosen]) {
                      runStressTest(chosen);
                    }
                  }}
                  className="px-2.5 py-1.5 text-xs font-medium border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-orange-500 focus:outline-none"
                >
                  {scenarios.map(s => (
                    <option key={s.name} value={s.name}>
                      {s.name} {stressResults[s.name] ? `(${formatPercentage(stressResults[s.name].portfolio_impact, 1)})` : ''}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={handleExportCSV}
                className="flex items-center px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 border border-gray-300 dark:border-gray-600 transition-colors"
                title="Export stress impacts to CSV"
              >
                <Download className="w-3.5 h-3.5 mr-1" />
                CSV
              </button>
            </div>
          }
        />
      </div>

      {/* Stress Testing Insights Card */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Activity className="w-5 h-5 text-orange-600 dark:text-orange-400" />
            Stress Testing Insights & Interpretation
          </h3>
          <HelpBtn itemKey="recovery_analysis" onOpen={setActiveExplainer} />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="flex items-start space-x-3 bg-red-50/50 dark:bg-red-950/20 p-4 rounded-xl border border-red-200/50 dark:border-red-900/30">
            <AlertTriangle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
            <div>
              <div className="flex items-center gap-1.5">
                <h4 className="text-xs font-bold uppercase tracking-wider text-red-900 dark:text-red-300">
                  Worst-Case Tail Risk
                </h4>
                <HelpBtn itemKey="worst_case" onOpen={setActiveExplainer} />
              </div>
              <p className="text-xs text-red-800 dark:text-red-300/80 mt-1">
                {worstCase != null ? (
                  <>Portfolio worst-case loss is <strong>{formatPercentage(worstCase, 1)}</strong> under the {worstCaseScenario ?? 'tested'} scenario. Review high-beta cyclical holdings to manage catastrophic drawdown risk.</>
                ) : (
                  <>No scenario results yet — run a stress test to measure worst-case tail risk.</>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-start space-x-3 bg-blue-50/50 dark:bg-blue-950/20 p-4 rounded-xl border border-blue-200/50 dark:border-blue-900/30">
            <Clock className="w-5 h-5 text-blue-600 shrink-0 mt-0.5" />
            <div>
              <div className="flex items-center gap-1.5">
                <h4 className="text-xs font-bold uppercase tracking-wider text-blue-900 dark:text-blue-300">
                  Recovery Horizon (MTTR)
                </h4>
                <HelpBtn itemKey="recovery_analysis" onOpen={setActiveExplainer} />
              </div>
              <p className="text-xs text-blue-800 dark:text-blue-300/80 mt-1">
                {avgRecovery != null ? (
                  <>Average recovery time is <strong>{avgRecovery.toFixed(1)} months</strong> across {recoveryTimes.length} of {stressTestResults.length} tested scenarios. Ensure liquidity buffers match this horizon.</>
                ) : (
                  <>No recovery data yet — average recovery time is <strong>N/A</strong>.</>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-start space-x-3 bg-emerald-50/50 dark:bg-emerald-950/20 p-4 rounded-xl border border-emerald-200/50 dark:border-emerald-900/30">
            <ShieldAlert className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
            <div>
              <div className="flex items-center gap-1.5">
                <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-900 dark:text-emerald-300">
                  Severity Triage
                </h4>
                <HelpBtn itemKey="severity_grading" onOpen={setActiveExplainer} />
              </div>
              <p className="text-xs text-emerald-800 dark:text-emerald-300/80 mt-1">
                Constituents are classified by institutional severity tiers (Critical, High, Medium, Low) to prioritize stop-loss rules and position sizing adjustments.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}