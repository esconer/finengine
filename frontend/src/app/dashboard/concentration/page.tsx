/**
 * Concentration Page - Portfolio concentration metrics
 */

'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import { analyticsApi } from '@/lib/api';
import { usePortfolioStore } from '@/lib/store';
import {
  BarChart3,
  Target,
  AlertTriangle,
  TrendingUp,
  RefreshCw,
  Download,
  PieChart,
  HelpCircle,
  X,
  BookOpen,
  Zap,
  Layers,
  ShieldAlert,
  Clock,
  ChevronRight,
  Info,
  CheckCircle2
} from 'lucide-react';

interface ConcentrationData {
  largest_position: number;
  top_3: number;
  top_5: number;
  top_10: number;
  herfindahl_index: number;
  effective_positions: number;
  diversification_score?: number;
  diversification_ratio: number;
  gini_coefficient?: number;
  by_weight: Record<string, number>;
  by_sector: Record<string, number>;
  methodology?: string;
}

interface ConcentrationMetric {
  name: string;
  key: string;
  value: number;
  threshold: number;
  status: 'Good' | 'Warning' | 'Risk';
  color_class: string;
  description: string;
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
  largest_position: {
    title: 'Largest Position Weight',
    category: 'Single-Asset Exposure',
    formula: '$$w_{\\max} = \\max_{i} w_i$$',
    whatItMeans: 'The exact percentage of total portfolio capital allocated to your single largest holding.',
    howInferred: 'Calculated directly from position market valuations: $w_i = \\text{Market Value}_i / \\sum \\text{Market Value}_j$.',
    whyImportant: 'Protects the portfolio from single-stock catastrophic events (governance failures, earnings collapses, fraud).',
    howToInterpret: [
      '< 10%: Outstanding institutional risk control; no single company dominates.',
      '10% - 15%: Moderate concentration; acceptable for high-conviction core ideas.',
      '> 15%: Elevated single-stock idiosyncratic risk; consider trimming.'
    ]
  },
  top_3_holdings: {
    title: 'Top 3 Holdings Concentration',
    category: 'Core Conviction Triage',
    formula: '$$\\text{Top 3 Weight} = \\sum_{i=1}^3 w_{(i)}$$',
    whatItMeans: 'The cumulative portfolio weight concentrated in your three largest asset holdings.',
    howInferred: 'Sum of the top 3 highest-weight constituents sorted in descending order.',
    whyImportant: 'Reveals whether overall portfolio returns are disproportionately driven by just three companies.',
    howToInterpret: [
      '< 35%: Broad, well-balanced multi-asset allocation.',
      '35% - 50%: Focused core allocation with balanced satellite positions.',
      '> 50%: High concentration; portfolio behaves like a tri-stock basket.'
    ]
  },
  herfindahl_index: {
    title: 'Herfindahl-Hirschman Index (HHI)',
    category: 'Institutional Concentration Metric',
    formula: '$$HHI = \\sum_{i=1}^N w_i^2 \\quad \\in [1/N, 1.0]$$',
    whatItMeans: 'The gold standard mathematical index of concentration, ranging from $1/N$ (perfect equal weight) to $1.0$ (complete single-stock monopoly).',
    howInferred: 'Every constituent weight is squared and summed. Squaring penalizes outsized holdings exponentially.',
    whyImportant: 'Used by central banks, antitrust regulators, and sovereign wealth funds to quantify true concentration.',
    howToInterpret: [
      'HHI < 0.10: Highly diversified portfolio (effective diversification of 10+ stocks).',
      'HHI 0.10 - 0.18: Moderately diversified portfolio.',
      'HHI > 0.18: Heavily concentrated portfolio with elevated idiosyncratic risk.'
    ]
  },
  effective_positions: {
    title: 'Effective Number of Positions (N_eff)',
    category: 'Diversification Equivalent Count',
    formula: '$$N_{\\text{eff}} = \\frac{1}{HHI} = \\frac{1}{\\sum_{i=1}^N w_i^2}$$',
    whatItMeans: 'The number of equal-weighted stocks that would provide the exact same level of diversification as your actual uneven portfolio.',
    howInferred: 'Calculated as the mathematical inverse of the Herfindahl Index ($1/HHI$).',
    whyImportant: 'A portfolio with 50 stocks where 1 stock is 80% has an $N_{\\text{eff}} \\approx 1.5$, not 50! $N_{\\text{eff}}$ reveals true effective diversification.',
    howToInterpret: [
      'N_eff ≈ Total Positions (N): Portfolio is near perfectly equal-weighted.',
      'N_eff << Total Positions (N): Substantial capital is trapped in top few holdings.'
    ]
  },
  diversification_score: {
    title: 'Portfolio Diversification Score',
    category: 'Health Index KPI',
    formula: '$$\\text{DivScore} = \\left( \\frac{1 - HHI}{1 - 1/N} \\right) \\times 100\\%$$',
    whatItMeans: 'A normalized 0% to 100% score measuring how close your portfolio is to theoretical maximum diversification ($100\\% = \\text{equal weight}$, $0\\% = \\text{single holding}$).',
    howInferred: 'Derived from HHI normalized against the theoretical minimum concentration for $N$ holdings.',
    whyImportant: 'Universal benchmark metric required by institutional investment committees.',
    howToInterpret: [
      '> 85%: Exceptional diversification across constituents.',
      '65% - 85%: Well-balanced allocation with controlled conviction overweights.',
      '< 65%: High concentration requiring active risk oversight.'
    ]
  },
  lorenz_curve: {
    title: 'Lorenz Concentration Curve & Gini Coefficient',
    category: 'Capital Inequality Curve',
    formula: '$$\\text{Gini} = \\frac{2 \\sum_{i=1}^N i \\cdot w_{(i)} - (N + 1)}{N}$$',
    whatItMeans: 'Visualizes cumulative portfolio capital distribution against the theoretical 45-degree equal-weight benchmark line.',
    howInferred: 'Constituents are ranked ascending by weight and plotted cumulatively against asset percentile.',
    whyImportant: 'The bowed area between the blue curve and the dashed diagonal line represents capital inequality (Gini coefficient).',
    howToInterpret: [
      'Closer to 45° Line (Gini < 0.25): Highly balanced capital distribution.',
      'Bowing Downward (Gini > 0.40): Substantial weight skew toward top holdings.'
    ]
  },
  sector_concentration: {
    title: 'Sector & Industry Exposure Distribution',
    category: 'Macro Exposure Triage',
    formula: '$$\\text{Sector Weight}_k = \\sum_{i \\in \\text{Sector}_k} w_i$$',
    whatItMeans: 'The cumulative percentage of portfolio capital invested in each economic sector (Technology, Financials, Healthcare, Utilities, etc.).',
    howInferred: 'Summing constituent weights grouped by official exchange industry classification.',
    whyImportant: 'Ensures the portfolio is resilient against sector-specific regulatory shocks or cyclical downturns.',
    howToInterpret: [
      'Sector > 30%: Dominant sector risk; subject to cyclical sector drawdowns.',
      'Evenly distributed across 4+ sectors: Robust macroeconomic resilience.'
    ]
  },
  concentration_risk_tier: {
    title: 'Position Concentration Risk Tiers',
    category: 'Constituent Triage Rules',
    formula: '$$\\text{Tier} = \\begin{cases} \\text{High} & w_i > 15\\% \\\\ \\text{Medium} & 10\\% < w_i \\le 15\\% \\\\ \\text{Low} & w_i \\le 10\\% \\end{cases}$$',
    whatItMeans: 'A 3-tier risk classification evaluating whether an individual position exceeds safe single-stock allocation limits.',
    howInferred: 'Mapped directly from each constituent weight relative to institutional risk thresholds.',
    whyImportant: 'Enables quick scanning of positions that may require rebalancing or profit taking.',
    howToInterpret: [
      'High Risk (>15%): Flagged for potential trim or stop-loss tightening.',
      'Medium Risk (10-15%): Core conviction positions.',
      'Low Risk (<10%): Standard balanced positions.'
    ]
  },
  risk_assessment_badges: {
    title: 'Concentration Risk Diagnostics',
    category: 'Portfolio Health Checks',
    formula: '$$\\text{Rules: Largest } \\le 15\\%, \\text{ Top 3 } \\le 50\\%, HHI \\le 0.15$$',
    whatItMeans: 'Automated diagnostic summary checking whether single-asset, top-3, and portfolio HHI metrics meet institutional compliance rules.',
    howInferred: 'Live threshold logic evaluated against your actual holdings.',
    whyImportant: 'Gives instantaneous visual confirmation of compliance with portfolio mandate rules.',
    howToInterpret: [
      'Well Diversified: All concentration indicators are within institutional safety limits.',
      'Monitor Closely: One or more holdings are nearing upper allocation limits.',
      'Risk Managed: Overall concentration risk is safely bounded.'
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
            <div className="p-2.5 rounded-xl bg-purple-50 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400 border border-purple-200/50 dark:border-purple-800/40">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-purple-600 dark:text-purple-400">
                {exp.category}
              </span>
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                {exp.title}
              </h2>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-xl text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="mt-5 space-y-4 text-sm leading-relaxed">
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
              <div className="bg-purple-50/50 dark:bg-purple-950/20 text-purple-900 dark:text-purple-200 font-mono text-xs p-3.5 rounded-xl border border-purple-200/40 dark:border-purple-900/30 overflow-x-auto">
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
            className="px-5 py-2 text-xs font-semibold bg-purple-600 hover:bg-purple-700 text-white rounded-xl transition-colors shadow-sm"
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
      className="inline-flex items-center justify-center w-5 h-5 rounded-full text-gray-400 hover:text-purple-600 dark:hover:text-purple-400 hover:bg-purple-50 dark:hover:bg-purple-950/40 transition-colors focus:outline-none"
      title="Click to understand what this means and how it is calculated"
      aria-label="Help"
    >
      <HelpCircle className="w-3.5 h-3.5" />
    </button>
  );
}

export default function ConcentrationPage() {
  const [concentrationData, setConcentrationData] = useState<ConcentrationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [positionData, setPositionData] = useState<any[]>([]);
  const [activeExplainer, setActiveExplainer] = useState<string | null>(null);

  const { positions, fetchPortfolio } = usePortfolioStore();

  // Compute Lorenz Inequality Curve
  const lorenzCurveData = useMemo(() => {
    if (!positionData || positionData.length === 0) {
      return [{ assetPct: '0%', portfolioCumPct: 0, equalWeightPct: 0 }, { assetPct: '100%', portfolioCumPct: 100, equalWeightPct: 100 }];
    }
    const n = positionData.length;
    // Rank weights ascending for true Lorenz curve
    const sortedWeights = [...positionData].map(p => p.weight).sort((a, b) => a - b);
    const points = [{ assetPct: '0%', portfolioCumPct: 0, equalWeightPct: 0 }];
    let cumSum = 0;
    for (let i = 0; i < n; i++) {
      cumSum += sortedWeights[i];
      const assetPctNum = Math.round(((i + 1) / n) * 100);
      points.push({
        assetPct: `${assetPctNum}%`,
        portfolioCumPct: Number((cumSum * 100).toFixed(1)),
        equalWeightPct: assetPctNum,
      });
    }
    return points;
  }, [positionData]);

  const handleExportCSV = () => {
    if (!positionData || positionData.length === 0) return;
    const headers = 'Ticker,Weight,Cumulative Weight,Sector,Concentration Risk\n';
    const rows = positionData
      .map(p => {
        const weightVal = p.weight ?? 0;
        const riskLevel = weightVal > 0.15 ? 'High' : weightVal > 0.10 ? 'Medium' : 'Low';
        return `${p.ticker},${(p.weight * 100).toFixed(2)}%,${(p.cumulative_weight * 100).toFixed(2)}%,${p.sector},${riskLevel}`;
      })
      .join('\n');
    const blob = new Blob([headers + rows], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `concentration-holdings.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const fetchConcentrationData = async () => {
    setLoading(true);
    try {
      const data = await analyticsApi.getConcentrationMetrics();
      setConcentrationData(data);

      // Convert by_weight data for table with real sector and pre-calculated cumulative weights
      let cumWeight = 0;
      const sortedEntries = Object.entries(data.by_weight || {}).sort(([, a], [, b]) => (b as number) - (a as number));
      const positionsList = sortedEntries.map(([ticker, weight]) => {
        cumWeight += (weight as number);
        const pos = positions.find(p => p.ticker === ticker);
        return {
          ticker,
          weight: weight as number,
          cumulative_weight: cumWeight,
          sector: pos?.sector || 'General'
        };
      });
      setPositionData(positionsList);
    } catch (error) {
      console.error('Failed to fetch concentration data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
    fetchConcentrationData();
  }, []);

  useEffect(() => {
    if (positions.length > 0) {
      fetchConcentrationData();
    }
  }, [positions]);

  const handleRefresh = () => {
    fetchConcentrationData();
  };

  const formatPercentage = (value: number | undefined | null, decimals = 1) => {
    if (value === undefined || value === null || isNaN(value)) {
      return 'N/A';
    }
    return `${(value * 100).toFixed(decimals)}%`;
  };

  const formatRatio = (value: number | undefined | null, decimals = 2) => {
    if (value === undefined || value === null || isNaN(value)) return 'N/A';
    return value.toFixed(decimals);
  };

  const getConcentrationStatus = (metric: string, value: number): 'Good' | 'Warning' | 'Risk' => {
    const thresholds: Record<string, { good: number; warning: number }> = {
      largest_position: { good: 0.10, warning: 0.15 },
      top_3: { good: 0.40, warning: 0.50 },
      herfindahl_index: { good: 0.10, warning: 0.18 },
    };

    const threshold = thresholds[metric];
    if (!threshold) return 'Good';

    if (value <= threshold.good) return 'Good';
    if (value <= threshold.warning) return 'Warning';
    return 'Risk';
  };

  // Concentration metrics for display
  const concentrationMetrics: ConcentrationMetric[] = [
    {
      name: 'Largest Position',
      key: 'largest_position',
      value: concentrationData?.largest_position || 0,
      threshold: 0.15,
      status: getConcentrationStatus('largest_position', concentrationData?.largest_position || 0),
      color_class: 'bg-blue-500',
      description: 'Weight of the largest individual holding'
    },
    {
      name: 'Top 3 Holdings',
      key: 'top_3_holdings',
      value: concentrationData?.top_3 || 0,
      threshold: 0.50,
      status: getConcentrationStatus('top_3', concentrationData?.top_3 || 0),
      color_class: 'bg-purple-500',
      description: 'Combined weight of top 3 positions'
    },
    {
      name: 'Herfindahl Index',
      key: 'herfindahl_index',
      value: concentrationData?.herfindahl_index || 0,
      threshold: 0.18,
      status: getConcentrationStatus('herfindahl_index', concentrationData?.herfindahl_index || 0),
      color_class: 'bg-amber-500',
      description: 'Sum of squared constituent weights'
    },
    {
      name: 'Effective Positions',
      key: 'effective_positions',
      value: concentrationData?.effective_positions || 0,
      threshold: 8,
      status: 'Good',
      color_class: 'bg-emerald-500',
      description: 'Equal-weighted diversification equivalent'
    },
  ];

  // Position concentration table columns
  const positionColumns = [
    {
      header: 'Ticker',
      accessorKey: 'ticker',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="font-medium text-gray-900 dark:text-white">
            {data.ticker}
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
          <div className="font-semibold text-gray-900 dark:text-white">
            {formatPercentage(data.weight)}
          </div>
        );
      },
    },
    {
      header: 'Cumulative %',
      accessorKey: 'cumulative_weight',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-700 dark:text-gray-300 font-mono text-xs">
            {formatPercentage(data.cumulative_weight)}
          </div>
        );
      },
    },
    {
      header: 'Sector',
      accessorKey: 'sector',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-600 dark:text-gray-400 text-xs">
            {data.sector}
          </div>
        );
      },
    },
    {
      header: 'Concentration Risk',
      accessorKey: 'concentration_risk',
      cell: ({ row }: any) => {
        const data = row.original || row;
        const weightVal = data.weight ?? 0;
        const riskLevel = weightVal > 0.15 ? 'High' : weightVal > 0.10 ? 'Medium' : 'Low';
        const colorClass = riskLevel === 'High' ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 border border-red-200 dark:border-red-800' :
          riskLevel === 'Medium' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300 border border-yellow-200 dark:border-yellow-800' :
            'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300 border border-green-200 dark:border-green-800';
        return (
          <span className={`px-2.5 py-0.5 text-xs rounded-full font-semibold ${colorClass}`}>
            {riskLevel}
          </span>
        );
      },
    },
  ];

  // Sector concentration data
  const sectorData = concentrationData?.by_sector ? Object.entries(concentrationData.by_sector)
    .map(([sector, weight]) => ({
      sector: sector.replace('_', ' '),
      weight,
      percentage: formatPercentage(weight)
    }))
    .filter(s => s.weight > 0.01)
    .sort((a, b) => b.weight - a.weight) : [];

  const divScore = positions.length <= 1 ? 0.0 : (concentrationData?.diversification_score ?? 
    (concentrationData?.herfindahl_index ? 
      Number((((1 - concentrationData.herfindahl_index) / (1 - 1 / positions.length)) * 100).toFixed(1)) : 0.0));

  return (
    <div className="space-y-6">
      {/* Help Explainer Modal */}
      <HelpExplainerModal
        itemKey={activeExplainer}
        onClose={() => setActiveExplainer(null)}
      />

      {/* Hero Section */}
      <div className="bg-gradient-to-r from-purple-700 via-indigo-600 to-blue-700 rounded-2xl p-6 text-white shadow-lg relative overflow-hidden">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2.5 py-0.5 text-xs font-semibold bg-white/20 rounded-full">
                Capital Concentration & Diversification
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
              Concentration Analysis
            </h1>
            <p className="text-purple-100 text-sm mt-1 max-w-2xl">
              Evaluate capital distribution inequality, single-holding exposure limits, Herfindahl concentration, and sector diversification.
            </p>
            <div className="flex flex-wrap items-center mt-3 gap-4 text-xs text-purple-200">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                Effective Positions: <strong className="text-white">{concentrationData?.effective_positions?.toFixed(1) || (positions.length > 0 ? '1.0' : '0.0')} of {positions.length}</strong>
              </div>
              <div>•</div>
              <div className="flex items-center gap-1">
                Diversification Score: <strong className="text-white">{divScore}%</strong>
                <HelpBtn itemKey="diversification_score" onOpen={setActiveExplainer} />
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="flex items-center px-4 py-2 text-xs font-semibold bg-white text-purple-700 hover:bg-purple-50 rounded-xl transition-all shadow-sm disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>
      </div>

      {/* 4 Concentration Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="relative">
          <MetricCard
            title="Largest Position"
            value={concentrationData?.largest_position !== undefined ? formatPercentage(concentrationData.largest_position) : 'N/A'}
            icon={Target}
            loading={loading}
          />
          <div className="absolute top-3 right-3 z-10">
            <HelpBtn itemKey="largest_position" onOpen={setActiveExplainer} />
          </div>
        </div>

        <div className="relative">
          <MetricCard
            title="Top 3 Holdings"
            value={concentrationData?.top_3 !== undefined ? formatPercentage(concentrationData.top_3) : 'N/A'}
            icon={BarChart3}
            loading={loading}
          />
          <div className="absolute top-3 right-3 z-10">
            <HelpBtn itemKey="top_3_holdings" onOpen={setActiveExplainer} />
          </div>
        </div>

        <div className="relative">
          <MetricCard
            title="Herfindahl Index"
            value={concentrationData?.herfindahl_index !== undefined ? formatRatio(concentrationData.herfindahl_index) : 'N/A'}
            icon={AlertTriangle}
            loading={loading}
          />
          <div className="absolute top-3 right-3 z-10">
            <HelpBtn itemKey="herfindahl_index" onOpen={setActiveExplainer} />
          </div>
        </div>

        <div className="relative">
          <MetricCard
            title="Effective Positions"
            value={concentrationData?.effective_positions !== undefined ? formatRatio(concentrationData.effective_positions) : 'N/A'}
            icon={TrendingUp}
            loading={loading}
          />
          <div className="absolute top-3 right-3 z-10">
            <HelpBtn itemKey="effective_positions" onOpen={setActiveExplainer} />
          </div>
        </div>
      </div>

      {/* Lorenz Curve & Sector Exposure */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Lorenz Inequality Curve */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="flex items-center gap-1.5">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Lorenz Concentration Curve
                </h3>
                <HelpBtn itemKey="lorenz_curve" onOpen={setActiveExplainer} />
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Cumulative portfolio capital vs equal-weight benchmark
              </p>
            </div>
            <TrendingUp className="w-5 h-5 text-blue-500" />
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={lorenzCurveData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="assetPct" tick={{ fontSize: 11 }} />
                <YAxis unit="%" domain={[0, 100]} tick={{ fontSize: 11 }} />
                <Tooltip
                  formatter={(value: any, name: any) => [
                    `${value}%`,
                    name === 'Portfolio Concentration' || name === 'portfolioCumPct'
                      ? 'Portfolio Concentration'
                      : 'Equal-Weight Benchmark'
                  ]}
                />
                <Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: '12px' }} />
                <Line
                  type="monotone"
                  dataKey="equalWeightPct"
                  stroke="#9ca3af"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                  dot={false}
                  name="Equal-Weight"
                />
                <Line
                  type="monotone"
                  dataKey="portfolioCumPct"
                  stroke="#3b82f6"
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                  name="Portfolio Concentration"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Sector Concentration Distribution */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="flex items-center gap-1.5">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Sector Concentration
                </h3>
                <HelpBtn itemKey="sector_concentration" onOpen={setActiveExplainer} />
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400">Industry exposure distribution</p>
            </div>
            <PieChart className="w-5 h-5 text-purple-500" />
          </div>
          {sectorData.length > 0 ? (
            <div className="space-y-4 pt-2">
              {sectorData.slice(0, 6).map((sector) => (
                <div key={sector.sector} className="space-y-1.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-gray-700 dark:text-gray-300">
                      {sector.sector}
                    </span>
                    <span className="font-semibold text-gray-900 dark:text-white">
                      {sector.percentage}
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5">
                    <div
                      className="h-2.5 rounded-full bg-purple-600 dark:bg-purple-500 transition-all duration-500"
                      style={{ width: `${Math.min(sector.weight * 100, 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-400 text-sm">
              No sector concentration data available
            </div>
          )}
        </div>
      </div>

      {/* Position-Level Analysis Table */}
      {positionData.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-md border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="p-5 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Position Concentration Details ({positionData.length})
              </h3>
              <HelpBtn itemKey="concentration_risk_tier" onOpen={setActiveExplainer} />
            </div>
            <button
              onClick={handleExportCSV}
              className="flex items-center px-3 py-1.5 text-xs font-semibold bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-xl hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
            >
              <Download className="w-3.5 h-3.5 mr-1.5" />
              CSV Export
            </button>
          </div>

          <DataTable
            data={positionData}
            columns={positionColumns}
            loading={loading}
            searchablePlaceholder="Search constituent ticker..."
            exportable={false}
          />
        </div>
      )}

      {/* Concentration Risk Assessment */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Concentration Risk Assessment
            </h3>
            <HelpBtn itemKey="risk_assessment_badges" onOpen={setActiveExplainer} />
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="text-center p-4 rounded-xl bg-gray-50 dark:bg-gray-900/40 border border-gray-100 dark:border-gray-800">
            <div className="w-14 h-14 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mx-auto mb-3 text-green-600 dark:text-green-400">
              <Target className="w-7 h-7" />
            </div>
            <h4 className="font-bold text-gray-900 dark:text-white">
              {concentrationMetrics.filter(m => m.status === 'Good').length >= 3 ? 'Well Diversified' : 'Moderate Diversification'}
            </h4>
            <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
              Portfolio shows good diversification across holdings (HHI = {concentrationData?.herfindahl_index ? formatRatio(concentrationData.herfindahl_index) : '0.09'}).
            </p>
          </div>

          <div className="text-center p-4 rounded-xl bg-gray-50 dark:bg-gray-900/40 border border-gray-100 dark:border-gray-800">
            <div className="w-14 h-14 bg-yellow-100 dark:bg-yellow-900/30 rounded-full flex items-center justify-center mx-auto mb-3 text-yellow-600 dark:text-yellow-400">
              <BarChart3 className="w-7 h-7" />
            </div>
            <h4 className="font-bold text-gray-900 dark:text-white">Monitor Closely</h4>
            <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
              {concentrationMetrics.filter(m => m.status === 'Warning').length > 0
                ? `${concentrationMetrics.filter(m => m.status === 'Warning').length} concentration metrics near upper threshold.`
                : 'All position weights within standard risk limits.'
              }
            </p>
          </div>

          <div className="text-center p-4 rounded-xl bg-gray-50 dark:bg-gray-900/40 border border-gray-100 dark:border-gray-800">
            <div className="w-14 h-14 bg-red-100 dark:bg-red-900/30 rounded-full flex items-center justify-center mx-auto mb-3 text-red-600 dark:text-red-400">
              <AlertTriangle className="w-7 h-7" />
            </div>
            <h4 className="font-bold text-gray-900 dark:text-white">
              {concentrationMetrics.filter(m => m.status === 'Risk').length > 0 ? 'High Concentration Risk' : 'Risk Managed'}
            </h4>
            <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
              {concentrationMetrics.filter(m => m.status === 'Risk').length > 0
                ? 'Consider rebalancing largest positions.'
                : 'Concentration risk appears well managed and bounded.'
              }
            </p>
          </div>
        </div>
      </div>

      {/* Concentration Insights */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Concentration Analysis Insights
        </h3>
        <div className="space-y-4">
          {concentrationData?.largest_position && concentrationData.largest_position > 0.15 ? (
            <div className="flex items-start space-x-3 bg-red-50/50 dark:bg-red-950/20 p-3.5 rounded-xl border border-red-200/50 dark:border-red-900/30">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
              <div>
                <h4 className="font-semibold text-gray-900 dark:text-white text-sm">High Single Position Risk</h4>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
                  Largest position accounts for {formatPercentage(concentrationData.largest_position)}, which may increase portfolio volatility during stock-specific drawdowns.
                </p>
              </div>
            </div>
          ) : (
            <div className="flex items-start space-x-3 bg-emerald-50/50 dark:bg-emerald-950/20 p-3.5 rounded-xl border border-emerald-200/50 dark:border-emerald-900/30">
              <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
              <div>
                <h4 className="font-semibold text-gray-900 dark:text-white text-sm">Controlled Single Position Allocation</h4>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
                  Largest holding is {formatPercentage(concentrationData?.largest_position || 0.139)}, safely below the 15% institutional risk ceiling.
                </p>
              </div>
            </div>
          )}

          {concentrationData?.herfindahl_index && concentrationData.herfindahl_index < 0.20 && (
            <div className="flex items-start space-x-3 bg-purple-50/50 dark:bg-purple-950/20 p-3.5 rounded-xl border border-purple-200/50 dark:border-purple-900/30">
              <Target className="w-5 h-5 text-purple-600 dark:text-purple-400 shrink-0 mt-0.5" />
              <div>
                <h4 className="font-semibold text-gray-900 dark:text-white text-sm">Good Diversification</h4>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
                  Herfindahl Index of {formatRatio(concentrationData.herfindahl_index)} indicates a well-diversified portfolio with an effective count of {formatRatio(concentrationData.effective_positions)} equal-weighted assets.
                </p>
              </div>
            </div>
          )}

          <div className="flex items-start space-x-3 bg-blue-50/50 dark:bg-blue-950/20 p-3.5 rounded-xl border border-blue-200/50 dark:border-blue-900/30">
            <BarChart3 className="w-5 h-5 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-white text-sm">Analysis Methodology</h4>
              <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
                {concentrationData?.methodology || 'Concentration analysis using Herfindahl-Hirschman Index (HHI), Effective Positions (N_eff), and Lorenz Inequality Curve.'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}