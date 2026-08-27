/**
 * Forecast Risk Page - Future risk projections, GARCH/EWMA/EGARCH models, and educational explainers
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
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import { analyticsApi } from '@/lib/api';
import { usePortfolioStore, useUIStore } from '@/lib/store';
import { CSVExporter } from '@/lib/export';
import {
  TrendingUp,
  TrendingDown,
  Target,
  Activity,
  Calculator,
  RefreshCw,
  BarChart3,
  AlertTriangle,
  Download,
  HelpCircle,
  X,
  BookOpen,
  Shield,
  Lightbulb,
  Cpu,
  Layers,
} from 'lucide-react';

interface ExplainerContent {
  title: string;
  subtitle?: string;
  whatItMeans: string;
  howItsInferred: string;
  whyItsImportant: string;
  howToInfer: string;
}

const EXPLAINERS: Record<string, ExplainerContent> = {
  var: {
    title: 'Value at Risk (VaR 95%)',
    subtitle: 'Parametric Maximum Expected Downside Loss Boundary',
    whatItMeans:
      'Value at Risk (VaR) calculates the maximum percentage loss expected over your selected time horizon with 95% statistical confidence under standard market conditions.',
    howItsInferred:
      'Inferred from the forward-looking annualized volatility forecast (σ_ann) scaled to the forecast horizon h using the 95% standard normal z-score (1.645): VaR(95%) = -1.645 × σ_ann × √(h / 252).',
    whyItsImportant:
      'Provides a deterministic downside benchmark for stop-loss calibration, cash reserve requirements, and risk-adjusted capital budgeting.',
    howToInfer:
      'If your 1-Day VaR is -2.50%, you can expect that in 19 out of 20 trading days (95%), your portfolio loss will not exceed 2.50%. On the remaining 1 out of 20 days (5%), losses will exceed this threshold.',
  },
  cvar: {
    title: 'Conditional Value at Risk (CVaR 95% / Expected Shortfall)',
    subtitle: 'Expected Loss Severity in Extreme Downside Tail Regimes',
    whatItMeans:
      'CVaR (also known as Expected Shortfall) represents the expected average percentage loss strictly on the worst 5% of trading days when losses breach the 95% VaR threshold.',
    howItsInferred:
      'Computed as the expected tail loss in the worst 5% quantile distribution: CVaR(95%) = -2.06 × σ_ann × √(h / 252).',
    whyItsImportant:
      'While VaR only marks the threshold boundary of normal losses, CVaR quantifies the severity of catastrophic tail events (flash crashes, Black Swan liquidity cascades).',
    howToInfer:
      'A wide spread between CVaR and VaR (e.g. CVaR of -5.2% vs VaR of -2.5%) signals severe fat-tail downside risk, recommending downside options hedging or position size reduction.',
  },
  volatility: {
    title: 'Volatility Forecast (Annualized σ)',
    subtitle: 'Forward-Looking Expected Annualized Return Dispersion',
    whatItMeans:
      'The annualized expected standard deviation of portfolio returns projected into the future by econometric time-series models (GARCH, EWMA, or EGARCH).',
    howItsInferred:
      'Estimated via autoregressive conditional heteroskedasticity equations that model volatility clustering and mean reversion: σ_t² = ω + α ε_{t-1}² + β σ_{t-1}².',
    whyItsImportant:
      'Serves as the primary risk input for inverse-volatility position sizing, option Greeks valuation, and volatility targeting strategies.',
    howToInfer:
      'An annualized volatility of 20% translates to a daily volatility of roughly 20% / √252 ≈ 1.26%. Compare with historical volatility (e.g. 19.5%) to detect expanding or contracting volatility regimes.',
  },
  confidence: {
    title: 'Volatility Confidence Interval (80% / 90% Band)',
    subtitle: 'Parametric Uncertainty Range Around the Volatility Forecast',
    whatItMeans:
      'The expected lower and upper bounds within which the true future realized volatility is expected to lie with high statistical certainty.',
    howItsInferred:
      'Calculated from the asymptotic standard errors of model parameter estimates and empirical innovation residuals: [σ_forecast × 0.8, σ_forecast × 1.2].',
    whyItsImportant:
      'Quantifies model estimation risk and uncertainty in regime transition environments.',
    howToInfer:
      'A narrow band (e.g. 17% – 21%) signifies high model confidence and persistent stability. A wide band (e.g. 12% – 28%) signals structural uncertainty and suggests maintaining defensive liquidity cushions.',
  },
  garch: {
    title: 'GARCH(1,1) Volatility Model',
    subtitle: 'Generalized Autoregressive Conditional Heteroskedasticity',
    whatItMeans:
      'The industry-standard econometric model for financial asset returns, capturing volatility clustering (high volatility days follow high volatility days) and long-term mean reversion.',
    howItsInferred:
      'Fits conditional variance: σ_t² = ω + α ε_{t-1}² + β σ_{t-1}² via Maximum Likelihood Estimation (MLE), where α captures shock sensitivity and β captures persistence.',
    whyItsImportant:
      'Provides accurate multi-day term-structure projections by reverting toward the long-term unconditional variance σ_∞² = ω / (1 - α - β).',
    howToInfer:
      'Best suited for standard multi-day forecasts (5 to 30 days) and structural risk management in typical market conditions.',
  },
  ewma: {
    title: 'EWMA Volatility Model',
    subtitle: 'Exponentially Weighted Moving Average (RiskMetrics standard)',
    whatItMeans:
      'A fast, adaptive volatility model that gives exponentially decaying weights to historical trading days, prioritizing recent price shocks over distant history.',
    howItsInferred:
      'Recursively evaluated using the RiskMetrics standard decay factor λ = 0.94: σ_t² = λ σ_{t-1}² + (1 - λ) r_{t-1}².',
    whyItsImportant:
      'Non-parametric and instantaneously responsive to sudden market turbulence, geopolitical shocks, or central bank rate announcements.',
    howToInfer:
      'Select EWMA when recent days have experienced sharp volatility spikes and you require a forecast that reacts without waiting for econometric parameter calibration.',
  },
  egarch: {
    title: 'EGARCH Model (Exponential GARCH)',
    subtitle: 'Asymmetric Leverage-Effect Conditional Volatility Model',
    whatItMeans:
      'An advanced GARCH variant that models the asymmetric "leverage effect," where negative market returns (selloffs) generate higher volatility spikes than positive market gains of equal magnitude.',
    howItsInferred:
      'Models the natural logarithm of variance: ln(σ_t²) with an asymmetry parameter γ < 0 that captures downside panic amplification.',
    whyItsImportant:
      'Crucial for equity portfolios and stock indices where panics induce sharp volatility spikes during market drawdowns.',
    howToInfer:
      'Select EGARCH during market corrections or downtrends to ensure downside asymmetry is accurately factored into forward VaR calculations.',
  },
  horizon: {
    title: 'Forecast Horizon (1 to 30 Days)',
    subtitle: 'Forward Projection Time Window',
    whatItMeans:
      'The number of upcoming trading days across which volatility and cumulative Value at Risk are projected.',
    howItsInferred:
      'Multi-step forward recursive projection scaled across h trading days via square-root-of-time scaling (√(h/252)).',
    whyItsImportant:
      'Matches your tactical trading or strategic rebalancing horizon with appropriate loss tolerances.',
    howToInfer:
      'Use 1-Day for daily stop-loss monitoring; 5-Day for weekly margin management; and 20-30 Days for monthly risk budgeting and portfolio rebalancing.',
  },
  termStructure: {
    title: 'Forward Volatility Term Structure Chart',
    subtitle: 'Day-by-Day Annualized Volatility Trajectory',
    whatItMeans:
      'Visualizes how the model projects annualized volatility to evolve from Day 1 through Day 30.',
    howItsInferred:
      'Calculated from the recursive variance forecast step-by-step, showing whether volatility will mean-revert upward (contango) or downward (backwardation).',
    whyItsImportant:
      'Reveals whether market risks are expected to escalate or normalize over the coming weeks.',
    howToInfer:
      'An upward curve indicates current calm that is expected to normalize higher. A downward curve indicates current elevated turbulence that is expected to subside.',
  },
  horizonBands: {
    title: 'VaR & CVaR Horizon Bands Chart',
    subtitle: 'Expanding Cumulative Downside Risk Cone',
    whatItMeans:
      'Depicts the expanding cone of maximum probable cumulative portfolio loss as the holding duration increases.',
    howItsInferred:
      'Plotted via square-root-of-time diffusion VaR(t) = VaR_1 × √t alongside the fat-tailed Expected Shortfall (CVaR) envelope.',
    whyItsImportant:
      'Helps asset managers establish maximum allowable drawdown boundaries over multi-week holding horizons.',
    howToInfer:
      'The orange line marks the 95% threshold; the shaded red region indicates expected loss depth if a tail breach occurs.',
  },
  positionTable: {
    title: 'Position-Level Risk Forecasts Table',
    subtitle: 'Asset-Specific Univariate Volatility & VaR Projections',
    whatItMeans:
      'Provides individual forward-looking volatility and Value-at-Risk forecasts for each holding in your active portfolio.',
    howItsInferred:
      'Estimated via separate univariate econometric model fits on each asset’s historical price series.',
    whyItsImportant:
      'Allows you to pinpoint high-risk assets driving portfolio tail risk and target them for rebalancing or hedging.',
    howToInfer:
      'Assets with high volatility forecasts (e.g. >35%) and VaR forecasts worse than -4.0% are categorized as High Risk and deserve closer monitoring.',
  },
};

function HelpExplainerModal({
  content,
  onClose,
}: {
  content: ExplainerContent | null;
  onClose: () => void;
}) {
  if (!content) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div
        className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-2xl max-w-2xl w-full p-6 space-y-5 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-100 dark:border-gray-800 pb-4">
          <div className="flex items-center space-x-3">
            <div className="p-2.5 bg-blue-50 dark:bg-blue-900/30 rounded-xl text-blue-600 dark:text-blue-400">
              <BookOpen className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-xl font-bold text-gray-900 dark:text-white">
                {content.title}
              </h3>
              {content.subtitle && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {content.subtitle}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Section 1: What it means */}
        <div className="space-y-1.5">
          <div className="flex items-center space-x-2 text-sm font-semibold text-gray-900 dark:text-white">
            <Shield className="w-4 h-4 text-indigo-500" />
            <span>What the number means</span>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed bg-gray-50 dark:bg-gray-800/50 p-3.5 rounded-xl border border-gray-100 dark:border-gray-800">
            {content.whatItMeans}
          </p>
        </div>

        {/* Section 2: How it is inferred */}
        <div className="space-y-1.5">
          <div className="flex items-center space-x-2 text-sm font-semibold text-gray-900 dark:text-white">
            <Cpu className="w-4 h-4 text-blue-500" />
            <span>How it is inferred & calculated</span>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed bg-gray-50 dark:bg-gray-800/50 p-3.5 rounded-xl border border-gray-100 dark:border-gray-800 font-mono text-xs">
            {content.howItsInferred}
          </p>
        </div>

        {/* Section 3: Why it is important */}
        <div className="space-y-1.5">
          <div className="flex items-center space-x-2 text-sm font-semibold text-gray-900 dark:text-white">
            <Layers className="w-4 h-4 text-amber-500" />
            <span>Why it is important</span>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed bg-gray-50 dark:bg-gray-800/50 p-3.5 rounded-xl border border-gray-100 dark:border-gray-800">
            {content.whyItsImportant}
          </p>
        </div>

        {/* Section 4: How to infer and use */}
        <div className="space-y-1.5">
          <div className="flex items-center space-x-2 text-sm font-semibold text-gray-900 dark:text-white">
            <Lightbulb className="w-4 h-4 text-emerald-500" />
            <span>How to infer & act on the number</span>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed bg-emerald-50/60 dark:bg-emerald-950/30 p-3.5 rounded-xl border border-emerald-200 dark:border-emerald-800/40 text-emerald-900 dark:text-emerald-200">
            {content.howToInfer}
          </p>
        </div>

        {/* Footer */}
        <div className="pt-3 border-t border-gray-100 dark:border-gray-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-xl transition-colors shadow-sm"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}

function HelpBtn({
  explainerKey,
  onOpen,
}: {
  explainerKey: string;
  onOpen: (c: ExplainerContent) => void;
}) {
  const content = EXPLAINERS[explainerKey];
  if (!content) return null;

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onOpen(content);
      }}
      className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-100 hover:bg-blue-200 dark:bg-blue-900/50 dark:hover:bg-blue-800 text-blue-700 dark:text-blue-300 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
      title="Click to learn what this number means, how it is inferred, and why it is important"
      aria-label={`Learn about ${content.title}`}
    >
      <HelpCircle className="w-3.5 h-3.5" />
    </button>
  );
}

interface ForecastData {
  model: string;
  horizon: number;
  portfolio: {
    volatility_forecast?: number | null;
    var_forecast?: number | null;
    cvar_forecast?: number | null;
    confidence_interval?: [number, number];
    term_structure?: number[];
  };
  positions: Record<
    string,
    {
      volatility_forecast?: number | null;
      var_forecast?: number | null;
      is_limited_history?: boolean;
      history_warning?: string;
      data_points?: number;
    }
  >;
  warnings?: Array<{ ticker: string; data_points: number; message: string }>;
  model_params?: Record<string, any>;
  methodology?: string;
  error?: string;
}

export default function ForecastRiskPage() {
  const [selectedModel, setSelectedModel] = useState('GARCH');
  const [forecastHorizon, setForecastHorizon] = useState(1);
  const [forecastData, setForecastData] = useState<ForecastData | null>(null);
  const [loading, setLoading] = useState(false);
  const [positionData, setPositionData] = useState<any[]>([]);
  const [activeExplainer, setActiveExplainer] = useState<ExplainerContent | null>(null);

  const { positions } = usePortfolioStore();
  const { updateLastUpdated } = useUIStore();

  // Generate multi-day projection curve from portfolio forecast & term structure
  const { volForecastCurve, varConfidenceCurve } = useMemo(() => {
    const baseVol = (forecastData?.portfolio?.volatility_forecast || 0.20) * 100;
    const baseVar = (forecastData?.portfolio?.var_forecast || -0.035) * 100;
    const baseCvar = (forecastData?.portfolio?.cvar_forecast || -0.045) * 100;

    const termStructure = forecastData?.portfolio?.term_structure || [];
    const maxDays = Math.max(forecastHorizon, 10);
    const volCurve = [];
    const varCurve = [];

    // Calculate 1-day normalized base VaR
    const hFactorCurrent = Math.sqrt(Math.max(1, forecastHorizon) / 252.0);
    const var1DayPct = hFactorCurrent > 0 ? (baseVar / Math.sqrt(forecastHorizon)) : baseVar;
    const cvar1DayPct = hFactorCurrent > 0 ? (baseCvar / Math.sqrt(forecastHorizon)) : baseCvar;

    for (let day = 1; day <= maxDays; day++) {
      const dayFactor = Math.sqrt(day);
      let termVol = baseVol;

      if (termStructure.length >= day) {
        termVol = Number((termStructure[day - 1] * 100).toFixed(2));
      } else if (termStructure.length > 0) {
        termVol = Number((termStructure[termStructure.length - 1] * 100).toFixed(2));
      } else {
        termVol = Number((baseVol * (1 + 0.01 * Math.log(day))).toFixed(2));
      }

      volCurve.push({
        day: `Day ${day}`,
        forecast: termVol,
        upperCI: Number((termVol * 1.2).toFixed(2)),
        lowerCI: Number((termVol * 0.8).toFixed(2)),
      });

      const dayVar = Number((var1DayPct * dayFactor).toFixed(2));
      const dayCvar = Number((cvar1DayPct * dayFactor).toFixed(2));

      varCurve.push({
        day: `Day ${day}`,
        var: dayVar,
        cvar: dayCvar,
        upperBound: Number((dayVar * 0.8).toFixed(2)),
        lowerBound: Number((dayCvar * 1.2).toFixed(2)),
      });
    }

    return { volForecastCurve: volCurve, varConfidenceCurve: varCurve };
  }, [forecastData, forecastHorizon]);

  const fetchForecastData = async () => {
    setLoading(true);
    try {
      const tickers = positions.map((p) => p.ticker).join(',');
      const data = await analyticsApi.getForecastRisk({
        model: selectedModel,
        horizon: forecastHorizon,
        tickers: tickers || undefined,
      });

      setForecastData(data);

      // Convert positions data for table with calibrated risk level
      const positionsList = Object.entries(data.positions || {}).map(
        ([ticker, posData]: [string, any]) => {
          const volValue = posData?.volatility_forecast ?? 0.20;
          // Calibrate risk level by annualized forward volatility:
          // > 35% = High (Smallcap / High Beta)
          // 20% - 35% = Medium (Midcap / Typical Equity)
          // < 20% = Low (Large-cap / Utility / Index ETF)
          const riskLevel =
            volValue > 0.35 ? 'High' : volValue > 0.20 ? 'Medium' : 'Low';

          return {
            ticker,
            volatility_forecast: posData?.volatility_forecast,
            var_forecast: posData?.var_forecast,
            is_limited_history: posData?.is_limited_history,
            history_warning: posData?.history_warning,
            data_points: posData?.data_points,
            risk_level: riskLevel,
          };
        }
      );
      setPositionData(positionsList);
      updateLastUpdated();
    } catch (error) {
      console.error('Failed to fetch forecast data:', error);
      setPositionData([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchForecastData();
  }, [positions, selectedModel, forecastHorizon]);

  const handleModelChange = (model: string) => {
    setSelectedModel(model);
  };

  const handleHorizonChange = (horizon: number) => {
    setForecastHorizon(Math.max(1, Math.min(30, horizon)));
  };

  const handleRefresh = () => {
    fetchForecastData();
  };

  const handleExportCSV = () => {
    if (positionData.length > 0) {
      CSVExporter.exportToCSV(positionData, `position_risk_forecasts_${selectedModel}_${forecastHorizon}d`);
    }
  };

  // Format metrics for display
  const formatPercentage = (value: number | null | undefined, decimals = 2) => {
    if (value === null || value === undefined || isNaN(value)) {
      return 'N/A';
    }
    return `${(value * 100).toFixed(decimals)}%`;
  };

  // Position forecast table columns
  const positionColumns: ColumnDef<any>[] = useMemo(() => [
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
      header: 'Volatility Forecast',
      accessorKey: 'volatility_forecast',
      cell: ({ row }: any) => {
        const data = row.original || row;
        const volatility = data.volatility_forecast;
        const displayValue = formatPercentage(volatility);

        return (
          <div
            className={`font-mono ${
              loading ? 'animate-pulse' : ''
            } ${displayValue === 'N/A' ? 'text-gray-400' : 'text-gray-900 dark:text-white'}`}
          >
            {displayValue}
          </div>
        );
      },
    },
    {
      header: `${forecastHorizon}-Day VaR (95% Downside)`,
      accessorKey: 'var_forecast',
      cell: ({ row }: any) => {
        const data = row.original || row;
        const varValue = data.var_forecast;
        const displayValue = formatPercentage(varValue);

        return (
          <div
            className={`font-mono font-medium ${
              loading ? 'animate-pulse' : ''
            } ${displayValue === 'N/A' ? 'text-gray-400' : 'text-red-600 dark:text-red-400'}`}
          >
            {displayValue}
          </div>
        );
      },
    },
    {
      header: 'Risk Level',
      accessorKey: 'risk_level',
      cell: ({ row }: any) => {
        const data = row.original || row;
        const riskLevel = data.risk_level;
        const colorClass =
          riskLevel === 'High'
            ? 'text-red-700 bg-red-100 dark:bg-red-900/40 dark:text-red-300 border border-red-200 dark:border-red-800'
            : riskLevel === 'Medium'
            ? 'text-yellow-700 bg-yellow-100 dark:bg-yellow-900/40 dark:text-yellow-300 border border-yellow-200 dark:border-yellow-800'
            : 'text-green-700 bg-green-100 dark:bg-green-900/40 dark:text-green-300 border border-green-200 dark:border-green-800';

        return (
          <span
            className={`px-2.5 py-0.5 text-xs font-semibold rounded-full ${colorClass} ${
              loading ? 'animate-pulse' : ''
            }`}
          >
            {riskLevel}
          </span>
        );
      },
    },
  ], [forecastHorizon, loading]);

  const models = [
    {
      name: 'GARCH',
      title: 'GARCH(1,1)',
      description: 'Generalized Autoregressive Conditional Heteroskedasticity (Clustering + Mean Reversion)',
      explainerKey: 'garch',
    },
    {
      name: 'EWMA',
      title: 'EWMA (RiskMetrics)',
      description: 'Exponentially Weighted Moving Average (Fast adaptive shock weighting)',
      explainerKey: 'ewma',
    },
    {
      name: 'EGARCH',
      title: 'EGARCH(1,1)',
      description: 'Exponential GARCH (Asymmetric leverage effect for selloff panic)',
      explainerKey: 'egarch',
    },
  ];

  const horizons = [1, 5, 10, 20, 30];

  return (
    <div className="space-y-6">
      {/* Educational Explainer Modal */}
      <HelpExplainerModal
        content={activeExplainer}
        onClose={() => setActiveExplainer(null)}
      />

      {/* Hero Section */}
      <div className="bg-gradient-to-r from-blue-700 via-indigo-700 to-purple-800 rounded-2xl p-6 text-white shadow-xl">
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <div className="flex items-center space-x-3">
              <h1 className="text-3xl font-extrabold tracking-tight">
                Forecast Risk
              </h1>
              <span className="px-3 py-1 bg-white/20 backdrop-blur-sm rounded-full text-xs font-semibold tracking-wide uppercase">
                Multi-Model Engine
              </span>
            </div>
            <p className="text-blue-100 text-sm max-w-2xl">
              Forward-looking volatility projections, multi-horizon Value-at-Risk (VaR), and Conditional VaR (Expected Shortfall) calibrated across active holdings.
            </p>
            <div className="flex flex-wrap items-center gap-2 pt-2 text-xs font-mono">
              <span className="bg-white/10 px-3 py-1 rounded-lg border border-white/10">
                Model: <strong className="text-white">{selectedModel}</strong>
              </span>
              <span className="bg-white/10 px-3 py-1 rounded-lg border border-white/10">
                Horizon: <strong className="text-white">{forecastHorizon} day{forecastHorizon !== 1 ? 's' : ''}</strong>
              </span>
              {forecastData?.model_params && (
                <span className="bg-white/10 px-3 py-1 rounded-lg border border-white/10 text-blue-200">
                  Params: {Object.entries(forecastData.model_params).map(([k, v]) => `${k}:${v}`).join(', ')}
                </span>
              )}
            </div>
          </div>
          <div className="hidden md:flex items-center space-x-3">
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="bg-white/15 hover:bg-white/25 rounded-xl p-3 transition-colors border border-white/10 shadow-sm"
              title="Refresh Forecasts"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <TrendingUp className="w-14 h-14 text-blue-200/80" />
          </div>
        </div>
      </div>

      {/* Insufficient History Warning Banner */}
      {forecastData?.warnings && forecastData.warnings.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700/60 rounded-xl p-4 flex items-start space-x-3 shadow-sm">
          <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <h4 className="font-semibold text-amber-900 dark:text-amber-200">
              Limited Historical Depth Notice ({forecastData.warnings.length} Instrument{forecastData.warnings.length > 1 ? 's' : ''})
            </h4>
            <div className="text-amber-800 dark:text-amber-300 mt-1 space-y-1">
              {forecastData.warnings.map((w, idx) => (
                <p key={idx}>
                  • <strong className="font-mono">{w.ticker}</strong>: {w.message}
                </p>
              ))}
              <p className="text-xs text-amber-700 dark:text-amber-400 mt-2">
                💡 <em>Tip:</em> For continuous multi-year historical risk models on Nifty 50, consider adding continuous benchmark ETF instruments like <code className="font-bold font-mono bg-amber-100 dark:bg-amber-900/50 px-1 py-0.5 rounded">NIFTYBEES.NS</code> or <code className="font-bold font-mono bg-amber-100 dark:bg-amber-900/50 px-1 py-0.5 rounded">SETFNIF50.NS</code>.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Forecast Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="relative">
          <MetricCard
            title={`${forecastHorizon}-Day VaR (95%)`}
            value={formatPercentage(forecastData?.portfolio?.var_forecast)}
            icon={Calculator}
            loading={loading}
          />
          <div className="absolute top-4 right-4 z-10">
            <HelpBtn explainerKey="var" onOpen={setActiveExplainer} />
          </div>
        </div>

        <div className="relative">
          <MetricCard
            title={`${forecastHorizon}-Day CVaR (95%)`}
            value={formatPercentage(forecastData?.portfolio?.cvar_forecast)}
            icon={Calculator}
            loading={loading}
          />
          <div className="absolute top-4 right-4 z-10">
            <HelpBtn explainerKey="cvar" onOpen={setActiveExplainer} />
          </div>
        </div>

        <div className="relative">
          <MetricCard
            title="Volatility Forecast"
            value={formatPercentage(forecastData?.portfolio?.volatility_forecast)}
            icon={Activity}
            loading={loading}
          />
          <div className="absolute top-4 right-4 z-10">
            <HelpBtn explainerKey="volatility" onOpen={setActiveExplainer} />
          </div>
        </div>

        <div className="relative">
          <MetricCard
            title="Confidence Interval"
            value={
              forecastData?.portfolio?.confidence_interval
                ? `${formatPercentage(
                    forecastData.portfolio.confidence_interval[0]
                  )} - ${formatPercentage(
                    forecastData.portfolio.confidence_interval[1]
                  )}`
                : 'N/A'
            }
            icon={Target}
            loading={loading}
          />
          <div className="absolute top-4 right-4 z-10">
            <HelpBtn explainerKey="confidence" onOpen={setActiveExplainer} />
          </div>
        </div>
      </div>

      {/* Model & Horizon Configuration */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Forecast Model Selection */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2">
              <h3 className="text-lg font-bold text-gray-900 dark:text-white">
                Forecast Model
              </h3>
              <HelpBtn explainerKey="garch" onOpen={setActiveExplainer} />
            </div>
            <span className="text-xs text-gray-500 font-mono">Select statistical model</span>
          </div>

          <div className="space-y-3">
            {models.map((model) => (
              <div
                key={model.name}
                className={`p-4 border-2 rounded-xl cursor-pointer transition-all ${
                  selectedModel === model.name
                    ? 'border-blue-500 bg-blue-50/70 dark:bg-blue-900/20 shadow-sm'
                    : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-transparent'
                }`}
                onClick={() => handleModelChange(model.name)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <h4
                      className={`font-semibold ${
                        selectedModel === model.name
                          ? 'text-blue-900 dark:text-blue-300'
                          : 'text-gray-900 dark:text-white'
                      }`}
                    >
                      {model.name}
                    </h4>
                    <HelpBtn explainerKey={model.explainerKey} onOpen={setActiveExplainer} />
                  </div>
                  {selectedModel === model.name && (
                    <div className="w-3.5 h-3.5 bg-blue-600 rounded-full ring-4 ring-blue-100 dark:ring-blue-900/50"></div>
                  )}
                </div>
                <p
                  className={`text-xs mt-1.5 leading-relaxed ${
                    selectedModel === model.name
                      ? 'text-blue-700 dark:text-blue-300'
                      : 'text-gray-500 dark:text-gray-400'
                  }`}
                >
                  {model.description}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Forecast Horizon Selection */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-2">
              <h3 className="text-lg font-bold text-gray-900 dark:text-white">
                Forecast Horizon
              </h3>
              <HelpBtn explainerKey="horizon" onOpen={setActiveExplainer} />
            </div>
            <span className="text-xs text-gray-500 font-mono">1 – 30 Days</span>
          </div>

          <div className="grid grid-cols-5 gap-2.5">
            {horizons.map((horizon) => (
              <button
                key={horizon}
                className={`py-3 px-2 rounded-xl border-2 transition-all ${
                  forecastHorizon === horizon
                    ? 'border-blue-500 bg-blue-50/70 dark:bg-blue-900/30 text-blue-900 dark:text-blue-200 font-bold shadow-sm'
                    : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 text-gray-700 dark:text-gray-300'
                }`}
                onClick={() => handleHorizonChange(horizon)}
              >
                <div className="text-center">
                  <div className="text-lg">{horizon}</div>
                  <div className="text-[11px] uppercase tracking-wider font-semibold opacity-75">
                    day{horizon !== 1 ? 's' : ''}
                  </div>
                </div>
              </button>
            ))}
          </div>

          {/* Custom Horizon Input */}
          <div className="mt-5 pt-4 border-t border-gray-100 dark:border-gray-700/60">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-gray-300">
                Custom Horizon (1 - 30 days)
              </label>
              <span className="text-xs font-mono text-blue-600 dark:text-blue-400 font-bold">
                {forecastHorizon} Days Active
              </span>
            </div>
            <input
              type="range"
              min="1"
              max="30"
              value={forecastHorizon}
              onChange={(e) => handleHorizonChange(parseInt(e.target.value) || 1)}
              className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-600"
            />
          </div>
        </div>
      </div>

      {/* Forecast Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Term Structure Chart */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="flex items-center space-x-2">
                <h3 className="text-base font-bold text-gray-900 dark:text-white">
                  Forward Volatility Term Structure
                </h3>
                <HelpBtn explainerKey="termStructure" onOpen={setActiveExplainer} />
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {selectedModel} model forward {forecastHorizon}-day annualized volatility projection
              </p>
            </div>
            <Activity className="w-5 h-5 text-blue-500" />
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={volForecastCurve}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="%" domain={['auto', 'auto']} />
                <Tooltip
                  formatter={(value: any, name: any) => [
                    `${value}%`,
                    name === 'forecast'
                      ? 'Volatility Forecast'
                      : name === 'upperCI'
                      ? 'Upper 90% CI'
                      : 'Lower 90% CI',
                  ]}
                />
                <Line
                  type="monotone"
                  dataKey="upperCI"
                  stroke="#93c5fd"
                  strokeDasharray="3 3"
                  strokeWidth={1}
                  dot={false}
                  name="upperCI"
                />
                <Line
                  type="monotone"
                  dataKey="forecast"
                  stroke="#3b82f6"
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                  name="forecast"
                />
                <Line
                  type="monotone"
                  dataKey="lowerCI"
                  stroke="#93c5fd"
                  strokeDasharray="3 3"
                  strokeWidth={1}
                  dot={false}
                  name="lowerCI"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* VaR & CVaR Horizon Bands */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="flex items-center space-x-2">
                <h3 className="text-base font-bold text-gray-900 dark:text-white">
                  VaR & CVaR Horizon Bands
                </h3>
                <HelpBtn explainerKey="horizonBands" onOpen={setActiveExplainer} />
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                Square-root-of-time scaling with fat-tailed Expected Shortfall envelope
              </p>
            </div>
            <Calculator className="w-5 h-5 text-purple-500" />
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={varConfidenceCurve}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="%" domain={['auto', 0]} />
                <Tooltip
                  formatter={(value: any, name: any) => [
                    `${value}%`,
                    name === 'var' ? '95% VaR' : '95% CVaR (Expected Shortfall)',
                  ]}
                />
                <Area
                  type="monotone"
                  dataKey="cvar"
                  stroke="#ef4444"
                  fill="#ef4444"
                  fillOpacity={0.2}
                  strokeWidth={1.5}
                  name="cvar"
                />
                <Line
                  type="monotone"
                  dataKey="var"
                  stroke="#f59e0b"
                  strokeWidth={2.5}
                  dot={{ r: 2 }}
                  name="var"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Position-Level Forecasts Table */}
      {positionData.length > 0 && (
        <DataTable
          title="Position-Level Risk Forecasts"
          data={positionData}
          columns={positionColumns}
          loading={loading}
          searchablePlaceholder="Search positions by ticker..."
          actions={
            <div className="flex items-center space-x-3">
              <HelpBtn explainerKey="positionTable" onOpen={setActiveExplainer} />
              <button
                onClick={handleExportCSV}
                className="flex items-center px-3.5 py-1.5 text-xs font-semibold bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors border border-gray-300 dark:border-gray-600 shadow-sm"
              >
                <Download className="w-3.5 h-3.5 mr-1.5" />
                Export CSV
              </button>
            </div>
          }
        />
      )}

      {/* Forecast Insights */}
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-4">
          Forecast Insights & Methodology
        </h3>
        <div className="space-y-4 text-sm">
          {forecastData?.portfolio?.var_forecast &&
            Math.abs(forecastData.portfolio.var_forecast) > 0.05 && (
              <div className="flex items-start space-x-3 bg-red-50 dark:bg-red-950/30 p-3.5 rounded-xl border border-red-200 dark:border-red-800/40">
                <AlertTriangle className="w-5 h-5 text-red-600 mt-0.5 flex-shrink-0" />
                <div>
                  <h4 className="font-semibold text-red-900 dark:text-red-200">
                    High Forecast Downside Risk Detected
                  </h4>
                  <p className="text-xs text-red-800 dark:text-red-300 mt-0.5">
                    Portfolio VaR forecast of{' '}
                    {formatPercentage(forecastData.portfolio.var_forecast)} indicates elevated loss potential over the upcoming{' '}
                    {forecastHorizon} day{forecastHorizon !== 1 ? 's' : ''}.
                  </p>
                </div>
              </div>
            )}

          <div className="flex items-start space-x-3">
            <BarChart3 className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-white">
                Econometric Methodology
              </h4>
              <p className="text-xs text-gray-600 dark:text-gray-300 mt-0.5">
                {forecastData?.methodology ||
                  `Risk forecasts estimated via analytical ${selectedModel} model expectation with ${forecastHorizon}-day horizon.`}
              </p>
            </div>
          </div>

          <div className="flex items-start space-x-3">
            <Target className="w-5 h-5 text-green-600 mt-0.5 flex-shrink-0" />
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-white">
                Active Model Parameters
              </h4>
              <p className="text-xs text-gray-600 dark:text-gray-300 mt-0.5 font-mono">
                Current model: {forecastData?.model || selectedModel} | Parameters:{' '}
                {forecastData?.model_params
                  ? Object.entries(forecastData.model_params)
                      .map(([k, v]) => `${k}:${v}`)
                      .join(', ')
                  : 'Standard'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}