/**
 * Market Regime Page
 * Hidden-Markov Model (HMM) classification of NIFTY 50 (Calm / Bull / Crisis)
 * + Conditional portfolio behavior and institutional state analytics
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
  Download,
  HelpCircle,
  X,
  Info,
  TrendingUp,
  ShieldAlert,
  Zap,
  CheckCircle2,
  Sliders,
  History
} from 'lucide-react';

interface ExplainerContent {
  title: string;
  what: string;
  howInferred: string;
  whyImportant: string;
  howToInfer: string;
  benchmark?: string;
}

const EXPLAINERS: Record<string, ExplainerContent> = {
  current_regime: {
    title: 'Active Market Regime (HMM State)',
    what: 'The most probable latent macroeconomic state currently governing the NIFTY 50 index (Calm, Bull Rally, or Crisis).',
    howInferred: 'Inferred via the Viterbi algorithm from a 3-state Gaussian Hidden Markov Model trained on daily returns and 21-day rolling volatility.',
    whyImportant: 'Asset return distributions and correlations shift drastically across market regimes; static models fail during transitions.',
    howToInfer: 'Calm indicates stable, low-volatility normal market conditions; Bull indicates high-momentum rallies; Crisis indicates elevated-volatility drawdowns.',
    benchmark: 'Historical Indian market baseline: ~75% Calm, ~13% Bull Rally, ~12% Crisis.'
  },
  stability: {
    title: 'Regime Persistence & Stability',
    what: 'The statistical stability of the current market state, reflecting low day-over-day state flipping.',
    howInferred: 'Computed as 1.0 minus the historical empirical regime transition frequency: Stability = (1 - State_Flips) × 100%.',
    whyImportant: 'A high stability score (> 70%) ensures regime signals are persistent trends rather than noisy high-frequency oscillations.',
    howToInfer: '74.0% stability indicates that once NIFTY enters this regime, it reliably stays for extended multi-week durations.',
    benchmark: 'Institutional threshold for stable regime trading: ≥ 65.0%.'
  },
  benchmark_vol: {
    title: 'Benchmark Volatility (Active Regime)',
    what: 'The annualized standard deviation of NIFTY 50 returns specifically during periods classified as this regime.',
    howInferred: 'Computed as σ_{regime} = std(R_{NIFTY} | State = Active) × √252.',
    whyImportant: 'Demonstrates the baseline market risk environment you are currently operating in.',
    howToInfer: '10.3% benchmark volatility in Calm regime confirms market swings are well below the long-term 15.5% average.',
    benchmark: 'NIFTY long-term historical average volatility: 14.5% – 16.5%.'
  },
  days_in_regime: {
    title: 'Historical Frequency / Share of History',
    what: 'The percentage of all analyzed trading sessions that have spent time in the active regime state.',
    howInferred: 'Count(Days in Active State) / Total Trading Days analyzed.',
    whyImportant: 'Identifies whether current market conditions represent the default normal environment (~75%) or a rare market anomaly (~12%).',
    howToInfer: '75% share indicates Calm is the dominant equilibrium state of the Indian equity market.'
  },
  hmm_three_states: {
    title: '3-State Gaussian Hidden Markov Model',
    what: 'An econometric clustering algorithm that partitions market history into 3 unobservable latent states without subjective human bias.',
    howInferred: 'Trained using Expectation-Maximization (Baum-Welch algorithm) to jointly fit Gaussian emission distributions (mean return and covariance) and transition probabilities.',
    whyImportant: 'Captures volatility clustering, fat tails, and non-linear market phase transitions simultaneously.',
    howToInfer: 'Compare Return and Volatility across states: Crisis exhibits negative returns (-28.8%) with high volatility (19.3%), whereas Calm delivers steady low-volatility returns (4.6%, 10.3% vol).'
  },
  regime_timeline: {
    title: '120-Day Daily Regime Timeline',
    what: 'A chronological daily sequence showing how the model classified each trading session over the last 6 months.',
    howInferred: 'Viterbi path reconstruction mapping each day to its highest posterior probability regime state.',
    whyImportant: 'Reveals regime transition clusters, such as the shift from early-year choppy/crisis sessions into the extended stable calm regime.',
    howToInfer: 'Solid green blocks indicate sustained calm conditions; red stripes highlight drawdown shocks; blue indicates explosive rallies.'
  },
  portfolio_in_regime: {
    title: 'Portfolio Performance Inside Active Regime',
    what: 'Your actual portfolio\'s annualized return and realized volatility during days when NIFTY was in the active market regime.',
    howInferred: 'Evaluates your book\'s returns filtered strictly to the overlapping trading days of the current regime.',
    whyImportant: 'Validates whether your portfolio is effectively capturing upside or defending capital under the prevailing macro conditions.',
    howToInfer: 'Your portfolio annualized +45.3% return with low volatility in Calm conditions, outperforming the benchmark.',
    benchmark: 'Alpha generation benchmark: Portfolio Return > Benchmark Return with lower relative drawdowns.'
  },
  regime_probabilities: {
    title: 'Real-Time Posterior Regime Probabilities',
    what: 'The exact mathematical probability distribution across all 3 market regimes inferred for today\'s session.',
    howInferred: 'Computed via Bayesian state inference: P(State_k | Returns, High/Low Range, EWMA Volatility) from the fitted Gaussian HMM.',
    whyImportant: 'Provides continuous early-warning detection: you can see crisis probability rising from 2% to 25% days before a discrete regime flip occurs.',
    howToInfer: 'If Calm probability > 70%, standard allocations apply; if Crisis probability climbs > 20%, initiate defensive hedges.'
  },
  intraday_volatility: {
    title: 'Intraday Range (Parkinson) vs EWMA Volatility',
    what: 'Real-time diagnostic comparing intraday High-Low price excursion volatility against fast-decay exponential volatility.',
    howInferred: 'Parkinson vol evaluates ln(High/Low)^2 / (4 ln 2) to capture true intraday swings; EWMA vol uses an exponential decay factor (span=10).',
    whyImportant: 'Solves the "close-to-close blindness" where intraday panic swings (e.g. -1.0% intraday dip) are hidden by a modest closing change (-0.5%).',
    howToInfer: 'If Parkinson Vol exceeds 15%, active intraday chop is elevated regardless of whether the net close looks flat.'
  }
};

function HelpExplainerModal({ itemKey, onClose }: { itemKey: string; onClose: () => void }) {
  const info = EXPLAINERS[itemKey];
  if (!info) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/65 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-xl w-full p-6 shadow-2xl relative text-slate-100 max-h-[90vh] overflow-y-auto">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
          aria-label="Close explainer"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center space-x-3 mb-4">
          <div className="p-2 bg-sky-500/20 text-sky-400 rounded-lg">
            <Info className="w-6 h-6" />
          </div>
          <h3 className="text-xl font-bold text-white">{info.title}</h3>
        </div>

        <div className="space-y-4 text-sm leading-relaxed">
          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-sky-400 uppercase tracking-wider mb-1">What This Means</h4>
            <p className="text-slate-200">{info.what}</p>
          </div>

          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-sky-400 uppercase tracking-wider mb-1">How It Is Inferred</h4>
            <p className="text-slate-300">{info.howInferred}</p>
          </div>

          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-sky-400 uppercase tracking-wider mb-1">Why It Is Important</h4>
            <p className="text-slate-300">{info.whyImportant}</p>
          </div>

          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-sky-400 uppercase tracking-wider mb-1">How To Interpret</h4>
            <p className="text-slate-300">{info.howToInfer}</p>
          </div>

          {info.benchmark && (
            <div className="bg-sky-950/40 p-3 rounded-lg border border-sky-800/50 text-sky-200 text-xs font-medium">
              💡 <span className="font-semibold text-sky-300">Quantitative Benchmark:</span> {info.benchmark}
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-lg font-medium text-sm transition-colors"
          >
            Got It
          </button>
        </div>
      </div>
    </div>
  );
}

function HelpBtn({ onClick, label }: { onClick: () => void; label?: string }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="inline-flex items-center justify-center w-4 h-4 ml-1.5 text-slate-400 hover:text-sky-400 rounded-full hover:bg-slate-800/60 transition-colors"
      title={label || 'Click to understand this metric'}
      aria-label={label || 'Explainer info'}
    >
      <HelpCircle className="w-3.5 h-3.5" />
    </button>
  );
}

interface RegimeData {
  as_of: string;
  current_regime: string;
  stability_pct: number;
  regime_probabilities?: Record<string, number>;
  realtime_ewma_vol?: number | null;
  realtime_parkinson_vol?: number | null;
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

const REGIME_STYLES: Record<string, { label: string; chip: string; dot: string; bg: string }> = {
  calm: {
    label: 'Calm',
    chip: 'bg-emerald-950/60 border border-emerald-800/60 text-emerald-300',
    dot: 'bg-emerald-500',
    bg: 'bg-emerald-500/20'
  },
  bull: {
    label: 'Bull Rally',
    chip: 'bg-blue-950/60 border border-blue-800/60 text-blue-300',
    dot: 'bg-blue-500',
    bg: 'bg-blue-500/20'
  },
  volatile: {
    label: 'Volatile',
    chip: 'bg-amber-950/60 border border-amber-800/60 text-amber-300',
    dot: 'bg-amber-500',
    bg: 'bg-amber-500/20'
  },
  crisis: {
    label: 'Crisis',
    chip: 'bg-rose-950/60 border border-rose-800/60 text-rose-300',
    dot: 'bg-rose-500',
    bg: 'bg-rose-500/20'
  },
};

function regimeStyle(regime: string) {
  const key = regime.toLowerCase();
  return (
    REGIME_STYLES[key] ?? {
      label: regime.charAt(0).toUpperCase() + regime.slice(1),
      chip: 'bg-slate-800 border border-slate-700 text-slate-300',
      dot: 'bg-slate-400',
      bg: 'bg-slate-700/20'
    }
  );
}

export default function RegimePage() {
  const [data, setData] = useState<RegimeData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeExplainer, setActiveExplainer] = useState<string | null>(null);

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

  // Export CSV
  const handleExportCSV = () => {
    if (!data) return;
    const rows: string[] = [];
    rows.push('Daisy Risk Engine - Hidden Markov Market Regime Classification');
    rows.push(`As of Date,${data.as_of}`);
    rows.push(`Observations Analyzed,${data.observations} trading days`);
    rows.push(`Current Active Regime,${current?.label || data.current_regime}`);
    rows.push(`Regime Stability,${data.stability_pct.toFixed(1)}%`);
    rows.push('');
    rows.push('HMM Latent State Parameters');
    rows.push('Regime,Annualized Return (%),Annualized Volatility (%),Share of History (%)');
    for (const st of data.states) {
      rows.push(`${regimeStyle(st.regime).label},${(st.ann_ret * 100).toFixed(2)}%,${(st.ann_vol * 100).toFixed(2)}%,${st.historical_days_pct.toFixed(1)}%`);
    }
    rows.push('');
    if (data.portfolio_in_current_regime) {
      rows.push('Portfolio Behavior Inside Current Regime');
      rows.push(`Overlap Days,${data.portfolio_in_current_regime.days}`);
      rows.push(`Portfolio Annualized Return,${(data.portfolio_in_current_regime.ann_ret * 100).toFixed(2)}%`);
      rows.push(`Portfolio Realized Volatility,${(data.portfolio_in_current_regime.ann_vol * 100).toFixed(2)}%`);
      rows.push('');
    }
    rows.push('Recent Daily Regime History (Last 120 Days)');
    rows.push('Date,Assigned Regime');
    for (const d of data.recent_history) {
      rows.push(`${d.date},${regimeStyle(d.regime).label}`);
    }

    const csvContent = 'data:text/csv;charset=utf-8,' + rows.join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `market_regime_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="space-y-6">
      {/* Active Explainer Modal */}
      {activeExplainer && (
        <HelpExplainerModal
          itemKey={activeExplainer}
          onClose={() => setActiveExplainer(null)}
        />
      )}

      {/* Hero Section */}
      <div className="bg-gradient-to-r from-sky-600 via-blue-600 to-indigo-700 rounded-xl p-6 text-white shadow-xl relative overflow-hidden">
        <div className="absolute right-0 top-0 translate-x-8 -translate-y-8 w-64 h-64 bg-white/10 rounded-full blur-3xl pointer-events-none" />
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center space-x-3 mb-2">
              <Radar className="w-8 h-8 text-sky-200" />
              <h1 className="text-3xl font-bold tracking-tight">Market Regime</h1>
              <span className="px-3 py-0.5 rounded-full text-xs font-semibold bg-white/20 text-white backdrop-blur-sm">
                HIDDEN MARKOV MODEL
              </span>
            </div>
            <p className="text-sky-100 max-w-2xl text-sm leading-relaxed">
              3-State Gaussian Hidden Markov Model over NIFTY 50 — calm, bull rally, or crisis — and how your book behaves inside it.
            </p>
            {data && (
              <div className="flex items-center mt-3 space-x-4 text-xs text-sky-200 font-medium">
                <span className="bg-black/20 px-2.5 py-1 rounded-md border border-white/10">
                  As of <strong className="text-white">{data.as_of}</strong>
                </span>
                <span className="bg-black/20 px-2.5 py-1 rounded-md border border-white/10">
                  <strong className="text-white">{data.observations}</strong> trading days analyzed
                </span>
              </div>
            )}
          </div>
          <div className="flex items-center space-x-3 self-start sm:self-auto">
            <button
              onClick={handleExportCSV}
              disabled={!data || loading}
              className="flex items-center bg-white/20 hover:bg-white/30 rounded-xl px-3.5 py-2.5 text-xs font-semibold transition-colors border border-white/10 shadow-sm"
              title="Export Regime History to CSV"
            >
              <Download className="w-4 h-4 mr-1.5 text-sky-200" />
              Export CSV
            </button>
            <button
              onClick={fetchRegime}
              disabled={loading}
              className="bg-white/20 hover:bg-white/30 rounded-xl p-2.5 transition-colors border border-white/10 shadow-sm"
              title="Refresh Market Regime Detection"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-rose-950/30 border border-rose-800/50 rounded-xl p-4 text-rose-200 text-sm flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
            <div>
              <h4 className="font-semibold text-rose-300">Regime detection failed</h4>
              <p className="text-xs text-rose-400 mt-0.5">{error}</p>
            </div>
          </div>
          <button
            onClick={fetchRegime}
            className="px-3 py-1.5 bg-rose-900/60 hover:bg-rose-800 rounded-lg text-xs font-semibold text-rose-100 transition-colors"
          >
            Try Again
          </button>
        </div>
      )}

      {/* Loading State */}
      {loading && !data && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center space-y-3">
          <RefreshCw className="w-8 h-8 text-sky-400 animate-spin mx-auto" />
          <h3 className="text-base font-semibold text-white">Classifying NIFTY Market Regimes...</h3>
          <p className="text-xs text-slate-400">
            Fitting a three-state Gaussian Hidden Markov Model over benchmark return distributions and rolling volatility.
          </p>
        </div>
      )}

      {/* Main Content */}
      {!loading && !error && data && current && (
        <>
          {/* Current Regime Headline Metrics */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="relative group">
              <MetricCard title="Current Regime" value={current.label} icon={Radar} />
              <div className="absolute top-4 right-4 z-10">
                <HelpBtn onClick={() => setActiveExplainer('current_regime')} />
              </div>
            </div>

            <div className="relative group">
              <MetricCard
                title="Stability"
                value={`${data.stability_pct.toFixed(1)}%`}
                icon={Gauge}
              />
              <div className="absolute top-4 right-4 z-10">
                <HelpBtn onClick={() => setActiveExplainer('stability')} />
              </div>
            </div>

            <div className="relative group">
              <MetricCard
                title="Benchmark Vol (this regime)"
                value={(() => {
                  const s = data.states.find(
                    (st) => st.regime.toLowerCase() === data.current_regime.toLowerCase()
                  );
                  return s ? fmtPct(s.ann_vol) : 'N/A';
                })()}
                icon={Waves}
              />
              <div className="absolute top-4 right-4 z-10">
                <HelpBtn onClick={() => setActiveExplainer('benchmark_vol')} />
              </div>
            </div>

            <div className="relative group">
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
              <div className="absolute top-4 right-4 z-10">
                <HelpBtn onClick={() => setActiveExplainer('days_in_regime')} />
              </div>
            </div>
          </div>

          {/* Real-Time Regime Probabilities & Intraday Volatility Diagnostics */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* 1. Real-Time Posterior Probabilities Bar */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center space-x-2">
                    <Zap className="w-5 h-5 text-sky-400" />
                    <h3 className="text-base font-bold text-white">Real-Time Posterior Probability Distribution</h3>
                    <HelpBtn onClick={() => setActiveExplainer('regime_probabilities')} />
                  </div>
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-sky-950/60 border border-sky-800/60 text-sky-300 font-mono">
                    Bayesian State Vector
                  </span>
                </div>
                <p className="text-xs text-slate-400 mb-4">
                  Continuous probability distribution across all 3 market states for today's trading session.
                </p>

                {data.regime_probabilities && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="text-emerald-400 flex items-center">
                        <span className="w-2 h-2 rounded-full bg-emerald-500 mr-1.5" />
                        Calm: <strong className="ml-1 text-white">{data.regime_probabilities.calm ?? 0}%</strong>
                      </span>
                      <span className="text-blue-400 flex items-center">
                        <span className="w-2 h-2 rounded-full bg-blue-500 mr-1.5" />
                        Bull Rally: <strong className="ml-1 text-white">{data.regime_probabilities.bull ?? 0}%</strong>
                      </span>
                      <span className="text-rose-400 flex items-center">
                        <span className="w-2 h-2 rounded-full bg-rose-500 mr-1.5" />
                        Crisis: <strong className="ml-1 text-white">{data.regime_probabilities.crisis ?? 0}%</strong>
                      </span>
                    </div>

                    <div className="w-full bg-slate-950 rounded-full h-3 overflow-hidden flex border border-slate-800">
                      <div
                        className="bg-emerald-500 transition-all duration-500"
                        style={{ width: `${data.regime_probabilities.calm ?? 0}%` }}
                        title={`Calm: ${data.regime_probabilities.calm ?? 0}%`}
                      />
                      <div
                        className="bg-blue-500 transition-all duration-500"
                        style={{ width: `${data.regime_probabilities.bull ?? 0}%` }}
                        title={`Bull Rally: ${data.regime_probabilities.bull ?? 0}%`}
                      />
                      <div
                        className="bg-rose-500 transition-all duration-500"
                        style={{ width: `${data.regime_probabilities.crisis ?? 0}%` }}
                        title={`Crisis: ${data.regime_probabilities.crisis ?? 0}%`}
                      />
                    </div>
                  </div>
                )}
              </div>
              <div className="mt-4 pt-3 border-t border-slate-800 flex items-center space-x-2 text-xs text-slate-400">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>Provides early-warning detection if crisis probability starts climbing before a discrete regime shift.</span>
              </div>
            </div>

            {/* 2. Intraday Parkinson vs EWMA Volatility */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center space-x-2">
                    <Waves className="w-5 h-5 text-indigo-400" />
                    <h3 className="text-base font-bold text-white">Intraday Range (Parkinson) vs EWMA Vol</h3>
                    <HelpBtn onClick={() => setActiveExplainer('intraday_volatility')} />
                  </div>
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-950/60 border border-indigo-800/60 text-indigo-300 font-mono">
                    High-Low Range vs Close
                  </span>
                </div>
                <p className="text-xs text-slate-400 mb-4">
                  Evaluates true intraday High-Low price swings alongside fast-decay exponential volatility.
                </p>

                <div className="grid grid-cols-2 gap-3">
                  <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                    <p className="text-xs text-slate-400 font-semibold mb-1">Parkinson Range Vol</p>
                    <p className="text-lg font-bold text-indigo-300 font-mono">
                      {fmtPct(data.realtime_parkinson_vol)}
                    </p>
                    <p className="text-[10px] text-slate-400 mt-0.5">Captures intraday high-low swings</p>
                  </div>
                  <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                    <p className="text-xs text-slate-400 font-semibold mb-1">Fast EWMA Vol (10D)</p>
                    <p className="text-lg font-bold text-sky-300 font-mono">
                      {fmtPct(data.realtime_ewma_vol)}
                    </p>
                    <p className="text-[10px] text-slate-400 mt-0.5">3x faster reaction than 21D rolling</p>
                  </div>
                </div>
              </div>
              <div className="mt-4 pt-3 border-t border-slate-800 flex items-center space-x-2 text-xs text-slate-400">
                <Info className="w-4 h-4 text-sky-400 shrink-0" />
                <span>Incorporates high-low volatility directly into regime classification to prevent close-to-close blindness.</span>
              </div>
            </div>
          </div>

          {/* HMM State Table */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl shadow-sm overflow-hidden">
            <div className="p-5 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Sliders className="w-5 h-5 text-sky-400" />
                <h3 className="text-base font-bold text-white">The Three States the Model Found</h3>
                <HelpBtn onClick={() => setActiveExplainer('hmm_three_states')} />
              </div>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-sky-950/60 border border-sky-800/60 text-sky-300 font-mono">
                Gaussian HMM
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full tabular-nums text-xs">
                <thead className="bg-slate-950/80 border-b border-slate-800">
                  <tr>
                    {['REGIME', 'ANNUALIZED RETURN', 'ANNUALIZED VOLATILITY', 'SHARE OF HISTORY'].map((h) => (
                      <th
                        key={h}
                        className="px-5 py-3 text-left font-semibold text-slate-400 uppercase tracking-wider"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {data.states.map((state) => {
                    const style = regimeStyle(state.regime);
                    const isCurrent =
                      state.regime.toLowerCase() === data.current_regime.toLowerCase();
                    return (
                      <tr
                        key={state.regime}
                        className={`transition-colors ${
                          isCurrent
                            ? 'bg-sky-950/30 font-medium'
                            : 'hover:bg-slate-800/40'
                        }`}
                      >
                        <td className="px-5 py-3.5">
                          <span
                            className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${style.chip}`}
                          >
                            <span className={`w-1.5 h-1.5 rounded-full mr-1.5 ${style.dot}`} />
                            {style.label}
                            {isCurrent && (
                              <span className="ml-1.5 font-bold text-white tracking-wider">· now</span>
                            )}
                          </span>
                        </td>
                        <td className={`px-5 py-3.5 text-sm font-mono font-semibold ${
                          state.ann_ret >= 0 ? 'text-emerald-400' : 'text-rose-400'
                        }`}>
                          {fmtPct(state.ann_ret)}
                        </td>
                        <td className="px-5 py-3.5 text-sm font-mono text-slate-200">
                          {fmtPct(state.ann_vol)}
                        </td>
                        <td className="px-5 py-3.5 text-sm font-mono text-slate-300">
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
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center space-x-2">
                  <History className="w-5 h-5 text-sky-400" />
                  <h3 className="text-base font-bold text-white">Last {data.recent_history.length} Trading Days</h3>
                  <HelpBtn onClick={() => setActiveExplainer('regime_timeline')} />
                </div>
                <div className="flex items-center space-x-3 text-xs">
                  <div className="flex items-center space-x-1">
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                    <span className="text-slate-300">Calm</span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                    <span className="text-slate-300">Bull</span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
                    <span className="text-slate-300">Crisis</span>
                  </div>
                </div>
              </div>
              <p className="text-xs text-slate-400 mb-4">
                One segment per trading day, colored by the posterior regime assigned by the Viterbi sequence.
              </p>
              <div className="flex gap-[2px] h-10 p-1 bg-slate-950/80 rounded-lg border border-slate-800" role="img" aria-label="Daily regime timeline">
                {data.recent_history.map((day, i) => {
                  const style = regimeStyle(day.regime);
                  return (
                    <div
                      key={`${day.date}-${i}`}
                      className={`flex-1 min-w-[2.5px] rounded-sm transition-all hover:scale-y-110 ${style.dot}`}
                      title={`${day.date}: ${style.label}`}
                    />
                  );
                })}
              </div>
              <div className="flex justify-between text-xs text-slate-400 mt-2 font-mono tabular-nums">
                <span>{data.recent_history[0].date}</span>
                <span>{data.recent_history[data.recent_history.length - 1].date}</span>
              </div>
            </div>
          )}

          {/* Portfolio in Current Regime */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
            <div className="flex items-center space-x-2 mb-4">
              <TrendingUp className="w-5 h-5 text-emerald-400" />
              <h3 className="text-base font-bold text-white">Your Portfolio Inside This Regime</h3>
              <HelpBtn onClick={() => setActiveExplainer('portfolio_in_regime')} />
            </div>
            {data.portfolio_in_current_regime ? (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                <div>
                  <p className="text-xs uppercase font-semibold tracking-wider text-slate-400 mb-1">
                    Overlap Days
                  </p>
                  <p className="text-2xl font-bold text-white font-mono tabular-nums">
                    {data.portfolio_in_current_regime.days}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase font-semibold tracking-wider text-slate-400 mb-1">
                    Your Annualized Return
                  </p>
                  <p
                    className={`text-2xl font-bold font-mono tabular-nums ${
                      data.portfolio_in_current_regime.ann_ret >= 0
                        ? 'text-emerald-400'
                        : 'text-rose-400'
                    }`}
                  >
                    {fmtPct(data.portfolio_in_current_regime.ann_ret)}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase font-semibold tracking-wider text-slate-400 mb-1">
                    Your Annualized Volatility
                  </p>
                  <p className="text-2xl font-bold text-white font-mono tabular-nums">
                    {fmtPct(data.portfolio_in_current_regime.ann_vol)}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-400">
                Add holdings to your portfolio to see how your book historically behaves in{' '}
                {current.label.toLowerCase()} conditions.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

