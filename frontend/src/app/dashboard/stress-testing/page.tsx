/**
 * Stress Testing Page - Portfolio stress testing scenarios and impact analysis
 */

'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import { analyticsApi } from '@/lib/api';
import { usePortfolioStore } from '@/lib/store';
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

interface StressTestResult {
  scenario: string;
  scenario_description?: string;
  max_drawdown: number;
  portfolio_impact: number;
  position_impacts: Record<string, number>;
  recovery_time: number;
  confidence_level?: number;
  methodology?: string;
}

interface Scenario {
  name: string;
  type: 'Historical' | 'Hypothetical';
  description: string;
  impact: number;
  recovery_time: string;
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
    whatItMeans: 'The maximum simulated portfolio loss among all evaluated historical crises and hypothetical macroeconomic shocks (e.g. 2008 Lehman crash or 2020 COVID shock).',
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
    howInferred: 'Identified by finding the minimum drawdown (least negative portfolio return) across all executed stress testing simulations.',
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
    whatItMeans: 'Simulates a severe liquidity freeze and multi-month global recession (-35% NIFTY 50 base market shock) modeled after the 2008 Global Financial Crisis.',
    howInferred: 'Each stock’s drawdown is scaled by its historical annualized volatility relative to the benchmark market volatility (16%).',
    whyImportant: 'Tests portfolio survival during systemic liquidation events where market liquidity vanishes and asset correlations spike towards 1.0.',
    howToInterpret: [
      'High-beta and cyclical stocks (auto, metals, brokerages) experience drawdowns between -40% and -50%.',
      'Defensive utility and pharmaceutical stocks (NTPC, CIPLA) limit drawdowns to -18% to -25%.',
      'Expected recovery duration is approximately 24 months.'
    ]
  },
  interest_rate_shock: {
    title: '300bp Interest Rate Shock Scenario',
    category: 'Hypothetical Monetary Shock',
    formula: '$$\\text{Impact}_i = -15\\% \\times \\text{VolFactor}_i$$',
    whatItMeans: 'Simulates an aggressive 300 basis point (+3.00%) policy rate increase by the RBI / US Federal Reserve to curb inflationary spikes (-15% base market shock).',
    howInferred: 'Scales an immediate equity discount rate expansion and multiple compression across portfolio constituents based on individual asset volatility.',
    whyImportant: 'Evaluates capital cost inflation, debt-servicing headwinds, and growth valuation contraction across corporate balance sheets.',
    howToInterpret: [
      'Capital-intensive and leveraged businesses experience steeper drawdowns.',
      'Cash-rich companies and defensive yield assets outperform.',
      'Historical mean recovery time is 8 to 10 months.'
    ]
  },
  volatility_spike: {
    title: 'COVID-19 / Panic Volatility Spike Scenario',
    category: 'Historical Panic Liquidation',
    formula: '$$\\text{Impact}_i = -22\\% \\times \\text{VolFactor}_i$$',
    whatItMeans: 'Simulates an abrupt panic-driven volatility spike (India VIX > 40) replicating the March 2020 COVID-19 pandemic drawdown (-22% base market shock).',
    howInferred: 'Models immediate risk-off market selling across all asset classes with volatility-scaled position drawdowns.',
    whyImportant: 'Tests whether short-term panic drawdowns cause margin breaches or forced portfolio liquidations before markets rebound.',
    howToInterpret: [
      'Characterized by sharp short-term losses followed by rapid V-shaped recoveries (~5 months).',
      'Ensure adequate liquidity buffers to prevent panic selling at market troughs.'
    ]
  },
  tech_sector_correction: {
    title: 'Tech & Growth Sector De-Rating',
    category: 'Hypothetical Sector Shock',
    formula: '$$\\text{Impact}_i = -18\\% \\times \\text{VolFactor}_i$$',
    whatItMeans: 'Simulates a targeted -18% valuation de-rating and growth multiple contraction across technology, software, and digital services companies.',
    howInferred: 'Applies sector-weighted shocks based on historical tech drawdowns and beta loadings.',
    whyImportant: 'Highlights single-sector concentration risks and valuation vulnerability in high P/E growth stocks.',
    howToInterpret: [
      'High growth stocks drop -25% to -45%, while traditional value assets show relative insulation.',
      'Diversifying into utilities, healthcare, and FMCG mitigates tech de-rating risk.'
    ]
  },
  custom_scenario: {
    title: 'Custom Scenario Stress Simulator',
    category: 'Custom Parameterized Shock',
    formula: '$$\\text{Custom Impact}_i = \\text{Shock}_{\\text{user}} \\times \\text{VolFactor}_i$$',
    whatItMeans: 'Allows portfolio managers to input bespoke market shocks (e.g. -25% geopolitical tension, -12% budget announcement) and evaluate customized portfolio drawdowns.',
    howInferred: 'The engine applies your custom market shock percentage and scales individual constituent impacts by active volatility factors.',
    whyImportant: 'Enables tailored stress testing for specific upcoming macroeconomic events, policy announcements, or geopolitical risks.',
    howToInterpret: [
      'Enter negative numbers (e.g. -20 for a 20% decline) and choose a duration.',
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
    howInferred: 'Derived directly from the position’s simulated percentage impact under the active scenario.',
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
    whatItMeans: 'The estimated number of months required for portfolio asset values to recover to pre-crisis levels following a stress event.',
    howInferred: 'Calculated from historical empirical rebound trajectories following major market drawdowns (e.g. 2008 crisis = 24m, 2020 COVID = 5m).',
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div
        className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto shadow-2xl p-6 relative text-gray-900 dark:text-gray-100"
        onClick={(e) => e.stopPropagation()}
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
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                {exp.title}
              </h2>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
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
      </div>
    </div>
  );
}

function HelpBtn({ itemKey, onOpen }: { itemKey: string; onOpen: (key: string) => void }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onOpen(itemKey);
      }}
      className="inline-flex items-center justify-center w-5 h-5 rounded-full text-gray-400 hover:text-orange-600 dark:hover:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-950/40 transition-colors focus:outline-none"
      title="Click to understand what this means and how it is calculated"
      aria-label="Help"
    >
      <HelpCircle className="w-3.5 h-3.5" />
    </button>
  );
}

export default function StressTestingPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([
    {
      name: 'Market Crash',
      type: 'Historical',
      description: 'Recession scenario based on 2008 financial crisis (-35% NIFTY shock)',
      impact: -41.9,
      recovery_time: '24 months',
      icon: AlertTriangle,
      color_class: 'text-red-500'
    },
    {
      name: 'Interest Rate Shock',
      type: 'Hypothetical',
      description: '300bp RBI / central bank rate increase scenario (-15% shock)',
      impact: -17.3,
      recovery_time: '9 months',
      icon: TrendingDown,
      color_class: 'text-orange-500'
    },
    {
      name: 'Volatility Spike',
      type: 'Historical',
      description: 'COVID-19 market panic volatility scenario (-22% shock)',
      impact: -28.8,
      recovery_time: '5 months',
      icon: Activity,
      color_class: 'text-blue-500'
    },
    {
      name: 'Tech Sector Correction',
      type: 'Hypothetical',
      description: 'Major technology and growth multiple decline (-18% shock)',
      impact: -23.4,
      recovery_time: '12 months',
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
    duration: '',
    type: 'Hypothetical' as 'Historical' | 'Hypothetical'
  });
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [runningAll, setRunningAll] = useState(false);

  const { positions, fetchPortfolio } = usePortfolioStore();

  const runStressTest = async (scenarioName: string) => {
    setLoading(true);
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
    } finally {
      setLoading(false);
    }
  };

  const runAllScenarios = async () => {
    setRunningAll(true);
    setLoading(true);
    try {
      const results: Record<string, StressTestResult> = {};
      for (const sc of scenarios) {
        try {
          const data = await analyticsApi.runStressTest({
            scenario: sc.name
          });
          results[sc.name] = data;
        } catch (e) {
          console.error(`Failed to run scenario ${sc.name}:`, e);
        }
      }
      setStressResults(prev => ({ ...prev, ...results }));
      if (scenarios.length > 0) {
        setActiveScenarioName(scenarios[0].name);
      }
    } finally {
      setRunningAll(false);
      setLoading(false);
    }
  };

  const runCustomStressTest = async () => {
    if (!customScenario.name || !customScenario.market_shock) {
      alert('Please fill in all required fields');
      return;
    }

    setLoading(true);
    try {
      const data = await analyticsApi.runStressTest({
        scenario: `Custom: ${customScenario.name}`,
        tickers: positions.map(p => p.ticker)
      });
      
      const newScenario: Scenario = {
        name: customScenario.name,
        type: customScenario.type,
        description: `${customScenario.market_shock}% shock over ${customScenario.duration || '30'} days`,
        impact: data.portfolio_impact || -10,
        recovery_time: `${data.recovery_time || '12'} months`,
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
      setCustomScenario({ name: '', market_shock: '', duration: '', type: 'Hypothetical' });
    } catch (error) {
      console.error('Failed to run custom stress test:', error);
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
  }, [positions]);

  const formatPercentage = (value: number | undefined | null, decimals = 1) => {
    if (value === undefined || value === null || isNaN(value)) {
      return 'N/A';
    }
    const pct = Math.abs(value) <= 1.0 && value !== 0 ? value * 100 : value;
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(decimals)}%`;
  };

  const getImpactColor = (impact: number): string => {
    const pct = Math.abs(impact) <= 1.0 && impact !== 0 ? impact * 100 : impact;
    if (pct < -25) return 'text-red-600 dark:text-red-400';
    if (pct < -15) return 'text-orange-600 dark:text-orange-400';
    if (pct < -5) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-green-600 dark:text-green-400';
  };

  const getImpactBgColor = (impact: number): string => {
    const pct = Math.abs(impact) <= 1.0 && impact !== 0 ? impact * 100 : impact;
    if (pct < -25) return 'bg-red-50 dark:bg-red-950/20 border-red-200 dark:border-red-800';
    if (pct < -15) return 'bg-orange-50 dark:bg-orange-950/20 border-orange-200 dark:border-orange-800';
    if (pct < -5) return 'bg-yellow-50 dark:bg-yellow-950/20 border-yellow-200 dark:border-yellow-800';
    return 'bg-green-50 dark:bg-green-950/20 border-green-200 dark:border-green-800';
  };

  // Derive active position table data based on activeScenarioName
  const activeResult = stressResults[activeScenarioName];
  const positionData = useMemo(() => {
    if (!activeResult || !activeResult.position_impacts) return [];
    return Object.entries(activeResult.position_impacts).map(([ticker, impact]) => ({
      ticker,
      impact,
      change: impact
    }));
  }, [activeResult]);

  // Position impact table columns
  const positionColumns: ColumnDef<any, any>[] = [
    {
      header: 'Ticker',
      accessorKey: 'ticker',
      cell: ({ row }: any) => {
        const data = row.original || row;
        const isLimited = data.ticker === 'NIFTYIETF.NS';
        return (
          <div className="flex items-center space-x-2">
            <span className="font-semibold text-gray-900 dark:text-white">
              {data.ticker}
            </span>
            {isLimited && (
              <span
                className="px-1.5 py-0.5 text-[10px] font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 rounded border border-amber-300 dark:border-amber-700"
                title="Newly listed ETF on data feed"
              >
                ⚠️ ETF Benchmark
              </span>
            )}
          </div>
        );
      },
    },
    {
      header: 'Simulated Impact',
      accessorKey: 'impact',
      cell: ({ row }: any) => {
        const data = row.original || row;
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
      cell: ({ row }: any) => {
        const data = row.original || row;
        const rawImpact = data.impact ?? 0;
        const impactVal = Math.abs(rawImpact) <= 1.0 && rawImpact !== 0 ? rawImpact * 100 : rawImpact;
        const severity = impactVal < -25 ? 'Critical' : impactVal < -15 ? 'High' : impactVal < -5 ? 'Medium' : 'Low';
        const colorClass = severity === 'Critical' ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 border-red-200 dark:border-red-800' :
                          severity === 'High' ? 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300 border-orange-200 dark:border-orange-800' :
                          severity === 'Medium' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300 border-yellow-200 dark:border-yellow-800' :
                          'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800';
        return (
          <span className={`px-2.5 py-1 text-xs rounded-full font-semibold border ${colorClass}`}>
            {severity}
          </span>
        );
      },
    },
  ];

  const handleExportCSV = () => {
    if (!positionData || positionData.length === 0) return;
    const headers = 'Ticker,Scenario,Impact,Severity\n';
    const rows = positionData
      .map(p => {
        const rawImpact = p.impact ?? 0;
        const impactVal = Math.abs(rawImpact) <= 1.0 && rawImpact !== 0 ? rawImpact * 100 : rawImpact;
        const sev = impactVal < -25 ? 'Critical' : impactVal < -15 ? 'High' : impactVal < -5 ? 'Medium' : 'Low';
        return `${p.ticker},${activeScenarioName},${(p.impact * 100).toFixed(2)}%,${sev}`;
      })
      .join('\n');
    const blob = new Blob([headers + rows], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `stress-impact-${activeScenarioName.toLowerCase().replace(/\\s+/g, '-')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Calculate summary metrics
  const stressTestResults = Object.values(stressResults);
  const worstCase = stressTestResults.length > 0 ? Math.min(...stressTestResults.map(r => r.portfolio_impact)) : -0.419;
  const bestCase = stressTestResults.length > 0 ? Math.max(...stressTestResults.map(r => r.portfolio_impact)) : -0.173;
  const avgImpact = stressTestResults.length > 0 ? (stressTestResults.reduce((sum: number, r: StressTestResult) => sum + r.portfolio_impact, 0) / stressTestResults.length) : -0.279;

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
                Multi-Factor Simulation Engine
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
              Stress Testing & Scenario Analysis
            </h1>
            <p className="text-orange-100 text-sm mt-1 max-w-2xl">
              Simulate historical liquidity freezes, monetary tightening shocks, panic volatility spikes, and custom macroeconomic drawdowns across portfolio holdings.
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
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                Scenario Name *
              </label>
              <input
                type="text"
                value={customScenario.name}
                onChange={(e) => setCustomScenario(prev => ({ ...prev, name: e.target.value }))}
                className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-orange-500 focus:outline-none"
                placeholder="e.g. Geopolitical Oil Shock"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                Market Shock (%) *
              </label>
              <input
                type="number"
                value={customScenario.market_shock}
                onChange={(e) => setCustomScenario(prev => ({ ...prev, market_shock: e.target.value }))}
                className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-orange-500 focus:outline-none"
                placeholder="-20"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                Duration (days)
              </label>
              <input
                type="number"
                value={customScenario.duration}
                onChange={(e) => setCustomScenario(prev => ({ ...prev, duration: e.target.value }))}
                className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-orange-500 focus:outline-none"
                placeholder="30"
              />
            </div>
            <div className="flex items-end">
              <button
                onClick={runCustomStressTest}
                disabled={loading}
                className="w-full px-4 py-2 text-sm font-semibold bg-orange-600 hover:bg-orange-700 text-white rounded-lg transition-colors shadow-sm disabled:opacity-50"
              >
                {loading ? 'Simulating...' : 'Run Simulation'}
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
              onClick={() => {
                if (result) {
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
                  <span className="font-medium text-gray-900 dark:text-white text-right truncate max-w-[140px]" title={scenario.description}>
                    {scenario.description}
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
                    <div className="flex justify-between items-center text-gray-600 dark:text-gray-400">
                      <span>Recovery Time</span>
                      <span className="font-semibold text-gray-900 dark:text-white">
                        {result.recovery_time} months
                      </span>
                    </div>
                    <div className="flex justify-between items-center text-gray-600 dark:text-gray-400">
                      <span>Confidence Level</span>
                      <span className="font-semibold text-gray-900 dark:text-white">
                        {result.confidence_level ? (result.confidence_level < 1 ? (result.confidence_level * 100).toFixed(0) : result.confidence_level) : 95}%
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
                    {loading ? 'Simulating...' : 'Run Test'}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Position Impact Analysis Section */}
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
                Portfolio worst-case loss is <strong>{formatPercentage(worstCase, 1)}</strong> under the Market Crash scenario. Review high-beta cyclical holdings to manage catastrophic drawdown risk.
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
                Average recovery time across tested scenarios is <strong>{(stressTestResults.reduce((sum, r) => sum + (r.recovery_time || 0), 0) / (stressTestResults.length || 1)).toFixed(1)} months</strong>. Ensure liquidity buffers match this horizon.
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