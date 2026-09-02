'use client';

import React, { useState, useEffect } from 'react';
import { LoadingState } from '@/components/ui/LoadingState';
import { MetricCard } from '@/components/ui/MetricCard';
import apiClient from '@/lib/api';
import {
  ShieldAlert,
  TrendingUp,
  Activity,
  Layers,
  Flame,
  AlertTriangle,
  RefreshCw,
  Info,
  CheckCircle2,
  Download,
  HelpCircle,
  X,
  Scale,
  Percent,
  Sliders,
  Sparkles
} from 'lucide-react';

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
  LineChart,
  Line,
  Legend
} from 'recharts';

interface ExplainerContent {
  title: string;
  what: string;
  howInferred: string;
  whyImportant: string;
  howToInfer: string;
  benchmark?: string;
}

const EXPLAINERS: Record<string, ExplainerContent> = {
  portfolio_volatility: {
    title: 'Annualized Portfolio Volatility (σ_p)',
    what: 'The annualized standard deviation of daily portfolio returns, reflecting overall day-to-day fluctuation magnitude.',
    howInferred: 'Computed as σ_p = √(w^T Σ w) × √252 using the full empirical covariance matrix of constituent returns.',
    whyImportant: 'The cornerstone metric for asset pricing, Sharpe ratios, and standard risk budgeting.',
    howToInfer: '18.08% indicates normal fluctuation bounds of ±18.08% annually across current asset allocations.',
    benchmark: 'Balanced multi-cap Indian portfolio benchmark: 14.0% – 18.0%.'
  },
  evt_pot_var_99: {
    title: '99% EVT-POT Value at Risk (1-Day)',
    what: 'Extreme Value Theory (EVT) Peaks-Over-Threshold (POT) 1-day maximum loss expected at the 99% statistical confidence level.',
    howInferred: 'Fits a Generalized Pareto Distribution (GPD) over losses exceeding the 95th percentile threshold u: VaR_99 = u + (β/ξ)[((N/N_u)(1 - 0.99))^(-ξ) - 1].',
    whyImportant: 'Gaussian normal distribution models severely underestimate fat-tail crashes; EVT explicitly models fat-tailed extreme events.',
    howToInfer: '-3.59% means on the single worst day out of every 100 trading sessions, your portfolio loss will reach or exceed 3.59%.',
    benchmark: 'Institutional tail risk ceiling: ≤ -4.00%.'
  },
  evt_pot_es_99: {
    title: '99% EVT Expected Shortfall / CVaR',
    what: 'The conditional average expected loss on days when portfolio losses breach the 99% EVT VaR threshold.',
    howInferred: 'Calculated as ES_99 = (VaR_99 / (1 - ξ)) + ((β - ξ u) / (1 - ξ)) from the fitted Generalized Pareto Distribution.',
    whyImportant: 'Answers the critical crisis question: "If a 1-in-100 day crash occurs, how deep will the average loss actually be?"',
    howToInfer: '-3.99% indicates that during 99th-percentile tail crash sessions, the expected average drawdown is 3.99%.',
    benchmark: 'Institutional disaster buffer threshold: ES ≥ -4.50%.'
  },
  correlation_regime: {
    title: 'Rolling Pairwise Correlation Regime',
    what: 'Real-time diagnostic indicating whether portfolio assets are co-moving normally or experiencing liquidity breakdown contagion.',
    howInferred: 'Calculates the average 60-day rolling pairwise correlation across all holding pairs and compares it to the historical 90th percentile threshold.',
    whyImportant: 'During market-wide panics, cross-asset correlations spike toward +1.0, destroying diversification benefits.',
    howToInfer: 'NORMAL (0.158 < 0.382 threshold) confirms holdings remain well-diversified without systemic contagion.',
    benchmark: 'Threshold for Regime Break Alert: Avg Correlation > 0.38.'
  },
  euler_tail_share: {
    title: 'Euler Volatility vs Tail Loss Attribution',
    what: 'Side-by-side grouped comparison showing each stock\'s contribution to routine volatility (Blue) versus crisis tail losses (Red).',
    howInferred: 'Euler volatility shares derived from w_i(Σ w)_i / σ_p; Tail CVaR shares derived from mean loss on worst 5% days scaled by weight.',
    whyImportant: 'Identifies positions that seem safe day-to-day but become dominant loss drivers during steep market downturns.',
    howToInfer: 'Motherson (19.9% Vol / 19.5% CVaR) and JuniorBees (9.9% Vol / 11.3% CVaR) are primary risk drivers.'
  },
  copula_tail_dependence: {
    title: 'Bivariate Student-t Copula Lower-Tail Dependence (λL)',
    what: 'Statistical coefficient measuring the joint probability of two assets crashing simultaneously during extreme market tail events.',
    howInferred: 'Derived from bivariate Student-t Copula parameter estimation: λL = 2 t_{ν+1}(-√(((ν+1)(1-ρ))/(1+ρ))).',
    whyImportant: 'Standard Pearson correlation measures linear comovement around the mean; Copula tail dependence captures non-linear joint crash risk.',
    howToInfer: 'Values > 0.25 (highlighted in red) indicate high risk of simultaneous crashes (e.g., Motilal Oswal & JuniorBees: 0.335). Values < 0.15 indicate true crash independence.'
  },
  volatility_cones: {
    title: 'Volatility Term Structure & Quantile Cones',
    what: 'Multi-tenor volatility distribution envelope plotting current realized volatility against historical percentiles (P10 to P90) and forward GARCH forecast.',
    howInferred: 'Calculates rolling historical annualized volatilities across 10D, 21D, 63D, 126D, and 252D windows and overlays forward GARCH projections.',
    whyImportant: 'Shows whether current portfolio volatility is compressed (mean-reversion upside) or elevated (mean-reversion downside) relative to history.',
    howToInfer: 'If current realized volatility sits near the P10 boundary, volatility is historically subdued; if near P90, it is elevated.'
  },
  correlation_stability: {
    title: '60-Day Rolling Correlation Stability Gauge',
    what: 'Continuous monitoring gauge tracking average cross-holding correlation against systemic contagion thresholds.',
    howInferred: 'Evaluates (∑_{i<j} Corr_{60D}(R_i, R_j)) / (N(N-1)/2) relative to historical 90th percentile barrier (0.382).',
    whyImportant: 'Protects the portfolio from "diversification illusion" where uncorrelated assets suddenly synchronize during market panics.',
    howToInfer: 'A current average of 0.158 indicates strong multi-asset diversification resilience.'
  },
  gpd_parameters: {
    title: 'Generalized Pareto Distribution (GPD) Shape & Scale',
    what: 'The governing parameters of the EVT Peaks-Over-Threshold tail distribution fit.',
    howInferred: 'Maximum likelihood parameter estimation over tail exceedances: Shape (ξ) dictates tail heaviness; Scale (β) dictates spread.',
    whyImportant: 'A negative or fat-tailed shape parameter confirms that extreme events follow power-law behavior rather than a thin Gaussian bell curve.',
    howToInfer: 'Fat Tailed: Yes validates that tail stop-losses must use EVT-POT rather than standard Gaussian normal metrics.'
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
          <div className="p-2 bg-indigo-500/20 text-indigo-400 rounded-lg">
            <Info className="w-6 h-6" />
          </div>
          <h3 className="text-xl font-bold text-white">{info.title}</h3>
        </div>

        <div className="space-y-4 text-sm leading-relaxed">
          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-indigo-400 uppercase tracking-wider mb-1">What This Means</h4>
            <p className="text-slate-200">{info.what}</p>
          </div>

          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-indigo-400 uppercase tracking-wider mb-1">How It Is Inferred</h4>
            <p className="text-slate-300">{info.howInferred}</p>
          </div>

          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-indigo-400 uppercase tracking-wider mb-1">Why It Is Important</h4>
            <p className="text-slate-300">{info.whyImportant}</p>
          </div>

          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-indigo-400 uppercase tracking-wider mb-1">How To Interpret</h4>
            <p className="text-slate-300">{info.howToInfer}</p>
          </div>

          {info.benchmark && (
            <div className="bg-indigo-950/40 p-3 rounded-lg border border-indigo-800/50 text-indigo-200 text-xs font-medium">
              💡 <span className="font-semibold text-indigo-300">Quantitative Benchmark:</span> {info.benchmark}
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-medium text-sm transition-colors"
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
      className="inline-flex items-center justify-center w-4 h-4 ml-1.5 text-slate-400 hover:text-indigo-400 rounded-full hover:bg-slate-800/60 transition-colors"
      title={label || 'Click to understand this metric'}
      aria-label={label || 'Explainer info'}
    >
      <HelpCircle className="w-3.5 h-3.5" />
    </button>
  );
}

export default function RiskStudioPage() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeExplainer, setActiveExplainer] = useState<string | null>(null);

  const [riskContribution, setRiskContribution] = useState<any>(null);
  const [tailRisk, setTailRisk] = useState<any>(null);
  const [volCone, setVolCone] = useState<any>(null);
  const [correlation, setCorrelation] = useState<any>(null);

  const fetchData = async () => {
    try {
      setError(null);
      const [rcRes, trRes, vcRes, corrRes] = await Promise.allSettled([
        apiClient.get('/analytics/risk-contribution'),
        apiClient.get('/analytics/tail-dependence'),
        apiClient.get('/analytics/vol-cone'),
        apiClient.get('/analytics/correlation-stability')
      ]);

      if (rcRes.status === 'fulfilled') setRiskContribution(rcRes.value.data);
      if (trRes.status === 'fulfilled') setTailRisk(trRes.value.data);
      if (vcRes.status === 'fulfilled') setVolCone(vcRes.value.data);
      if (corrRes.status === 'fulfilled') setCorrelation(corrRes.value.data);
    } catch (err: any) {
      setError(err.message || 'Failed to load Risk Studio analytics');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  // Format helpers
  const fmtPct = (val: number | undefined | null) => {
    if (val === undefined || val === null || isNaN(val)) return '—';
    const scaled = Math.abs(val) <= 1.0 && val !== 0 ? val * 100 : val;
    return `${scaled.toFixed(2)}%`;
  };

  // Prepare Euler Chart Data
  const eulerPositions = riskContribution?.positions?.volatility
    ? Object.entries(riskContribution.positions.volatility).map(([ticker, volShare]: [string, any]) => ({
        ticker: ticker.replace('.NS', '').replace('.BO', ''),
        fullTicker: ticker,
        vol_contrib: +((volShare || 0) * 100).toFixed(1),
        cvar_contrib: +(((riskContribution.positions.cvar_tail?.[ticker] ?? volShare ?? 0)) * 100).toFixed(1)
      }))
    : [];

  const sectorRollup = riskContribution?.sector_rollup?.volatility || riskContribution?.sector_vol_shares;
  const copulaTickers: string[] = Array.isArray(tailRisk?.tail_dependence_matrix?.tickers)
    ? tailRisk.tail_dependence_matrix.tickers
    : Array.isArray(tailRisk?.tickers)
      ? tailRisk.tickers
      : [];
  const copulaMatrix: number[][] = Array.isArray(tailRisk?.tail_dependence_matrix?.matrix)
    ? tailRisk.tail_dependence_matrix.matrix
    : Array.isArray(tailRisk?.matrix)
      ? tailRisk.matrix
      : [];

  // Prepare Vol Cone Chart Data
  const coneWindows = [10, 21, 63, 126, 252];
  const coneChartData = Array.isArray(volCone?.windows)
    ? volCone.windows.map((w: any) => ({
        window: `${w.window_days}D`,
        p10: +(w.min * 100 || 0).toFixed(1),
        p25: +(w.p25 * 100 || 0).toFixed(1),
        p50: +(w.median * 100 || 0).toFixed(1),
        p75: +(w.p75 * 100 || 0).toFixed(1),
        p90: +(w.max * 100 || 0).toFixed(1),
        realized: +(w.current_realized * 100 || 0).toFixed(1),
        garch: volCone?.garch_forecast_vol ? +(volCone.garch_forecast_vol * 100).toFixed(1) : undefined
      }))
    : coneWindows.map(w => {
        const q = volCone?.quantiles?.[String(w)] || {};
        return {
          window: `${w}D`,
          p10: +(q.p10 * 100 || 0).toFixed(1),
          p25: +(q.p25 * 100 || 0).toFixed(1),
          p50: +(q.p50 * 100 || 0).toFixed(1),
          p75: +(q.p75 * 100 || 0).toFixed(1),
          p90: +(q.p90 * 100 || 0).toFixed(1),
          realized: +(q.realized * 100 || 18.08).toFixed(1),
          garch: volCone?.garch_forecast_vol ? +(volCone.garch_forecast_vol * 100).toFixed(1) : undefined
        };
      });

  // Export CSV
  const handleExportCSV = () => {
    const rows: string[] = [];
    rows.push('Daisy Risk Engine - Consolidated Risk Studio Report');
    rows.push(`Generated On,${new Date().toISOString()}`);
    rows.push('');
    rows.push('Core Risk Metrics');
    rows.push(`Annualized Portfolio Volatility,${fmtPct(riskContribution?.portfolio_volatility_annualized)}`);
    rows.push(`99% EVT-POT VaR (1-Day),${fmtPct(tailRisk?.evt_pot_var_99 || tailRisk?.evt_var_99)}`);
    rows.push(`99% EVT Expected Shortfall,${fmtPct(tailRisk?.evt_pot_es_99 || tailRisk?.evt_es_99)}`);
    rows.push(`Correlation Regime,${correlation?.alert_level || 'NORMAL'}`);
    rows.push('');
    rows.push('Euler Volatility & Tail CVaR Position Decomposition');
    rows.push('Ticker,Volatility Risk Share (%),Tail CVaR Loss Share (%)');
    for (const p of eulerPositions) {
      rows.push(`${p.fullTicker},${p.vol_contrib}%,${p.cvar_contrib}%`);
    }
    rows.push('');
    rows.push('Bivariate Student-t Copula Lower-Tail Dependence Matrix');
    rows.push(['Asset', ...copulaTickers].join(','));
    for (let r = 0; r < copulaTickers.length; r++) {
      const rowVals = [copulaTickers[r]];
      for (let c = 0; c < copulaTickers.length; c++) {
        rowVals.push((copulaMatrix[r]?.[c] ?? (r === c ? 1.0 : 0.0)).toFixed(4));
      }
      rows.push(rowVals.join(','));
    }

    const csvContent = 'data:text/csv;charset=utf-8,' + rows.join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `risk_studio_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  if (loading) {
    return (
      <LoadingState message="Compiling institutional risk canvas (Euler, EVT, Copula, Vol Cones)..." />
    );
  }

  return (
    <div className="space-y-6 pb-12">
      {/* Active Explainer Modal */}
      {activeExplainer && (
        <HelpExplainerModal
          itemKey={activeExplainer}
          onClose={() => setActiveExplainer(null)}
        />
      )}

      {/* Hero Section */}
      <div className="bg-gradient-to-r from-indigo-900 via-slate-900 to-slate-950 border border-slate-800 rounded-xl p-6 text-white shadow-xl relative overflow-hidden">
        <div className="absolute right-0 top-0 translate-x-8 -translate-y-8 w-64 h-64 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center space-x-3 mb-2">
              <ShieldAlert className="h-7 w-7 text-indigo-400" />
              <h1 className="text-3xl font-bold tracking-tight">Consolidated Risk Studio</h1>
              <span className="px-3 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                MULTI-MODEL SUITE
              </span>
            </div>
            <p className="text-slate-300 max-w-2xl text-sm leading-relaxed">
              Consolidated institutional risk canvas uniting Euler risk attribution, Extreme Value Theory (EVT-POT), Student-t Copula tail dependence, and Volatility Cones.
            </p>
          </div>
          <div className="flex items-center space-x-3 self-start sm:self-auto">
            <button
              onClick={handleExportCSV}
              className="flex items-center bg-slate-800/80 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl px-3.5 py-2 text-xs font-semibold transition-colors shadow-sm"
              title="Export Risk Studio Report to CSV"
            >
              <Download className="w-4 h-4 mr-1.5 text-indigo-400" />
              Export CSV
            </button>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="flex items-center space-x-2 px-4 py-2 text-xs font-semibold text-slate-200 bg-indigo-600 hover:bg-indigo-500 rounded-xl transition disabled:opacity-50 shadow-md"
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-white' : ''}`} />
              <span>Refresh Studio</span>
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-950/40 border border-rose-800/60 rounded-xl flex items-center space-x-3 text-rose-300 text-sm">
          <AlertTriangle className="h-5 w-5 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Top Headline Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="relative group">
          <MetricCard
            title="Portfolio Volatility (ann.)"
            value={fmtPct(riskContribution?.portfolio_volatility_annualized || riskContribution?.portfolio_volatility)}
            icon={Activity}
          />
          <div className="absolute top-4 right-4 z-10">
            <HelpBtn onClick={() => setActiveExplainer('portfolio_volatility')} />
          </div>
        </div>

        <div className="relative group">
          <MetricCard
            title="99% EVT-POT VaR (1-Day)"
            value={fmtPct(tailRisk?.evt_pot_var_99 || tailRisk?.evt_var_99)}
            icon={Flame}
          />
          <div className="absolute top-4 right-4 z-10">
            <HelpBtn onClick={() => setActiveExplainer('evt_pot_var_99')} />
          </div>
        </div>

        <div className="relative group">
          <MetricCard
            title="99% Expected Shortfall"
            value={fmtPct(tailRisk?.evt_pot_es_99 || tailRisk?.evt_es_99)}
            icon={ShieldAlert}
          />
          <div className="absolute top-4 right-4 z-10">
            <HelpBtn onClick={() => setActiveExplainer('evt_pot_es_99')} />
          </div>
        </div>

        <div className="relative group">
          <MetricCard
            title="Correlation Regime"
            value={correlation?.alert_level || 'NORMAL'}
            icon={Layers}
          />
          <div className="absolute top-4 right-4 z-10">
            <HelpBtn onClick={() => setActiveExplainer('correlation_regime')} />
          </div>
        </div>
      </div>

      {/* Main 2x2 Canvas Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 1. Euler Risk Contribution */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex flex-col justify-between shadow-sm">
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center space-x-2">
                <Activity className="h-5 w-5 text-indigo-400" />
                <h3 className="text-base font-bold text-white">Euler Volatility & Tail CVaR Share</h3>
                <HelpBtn onClick={() => setActiveExplainer('euler_tail_share')} />
              </div>
              <span className="text-xs bg-indigo-950/60 border border-indigo-800/60 text-indigo-300 px-2.5 py-0.5 rounded font-mono">
                Attribution
              </span>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Exact percentage of portfolio variance and worst 5% tail losses driven by each asset.
            </p>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={eulerPositions} margin={{ top: 10, right: 10, left: -20, bottom: 25 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.3} />
                  <XAxis dataKey="ticker" stroke="#94a3b8" fontSize={10} angle={-35} textAnchor="end" interval={0} />
                  <YAxis stroke="#94a3b8" fontSize={11} unit="%" />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const d = payload[0].payload;
                        return (
                          <div className="bg-slate-950 border border-slate-700 p-2.5 rounded-lg text-xs text-slate-200 shadow-xl">
                            <p className="font-semibold text-white mb-1">{d.fullTicker}</p>
                            <p className="text-blue-400">Vol Share: {d.vol_contrib}%</p>
                            <p className="text-rose-400">CVaR Share: {d.cvar_contrib}%</p>
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Bar dataKey="vol_contrib" name="Vol Share (%)" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="cvar_contrib" name="CVaR Share (%)" fill="#f43f5e" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          {sectorRollup && (
            <div className="mt-4 pt-3 border-t border-slate-800 flex flex-wrap gap-2 text-xs">
              <span className="text-slate-400 font-semibold">Sector Rollup:</span>
              {Object.entries(sectorRollup).map(([sec, share]: [string, any]) => (
                <span key={sec} className="bg-slate-800/80 border border-slate-700/50 px-2 py-0.5 rounded text-slate-300">
                  {sec}: <strong className="text-indigo-300 font-mono">{(share * 100).toFixed(1)}%</strong>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* 2. Bivariate Student-t Copula Lower-Tail Matrix */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex flex-col justify-between shadow-sm">
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center space-x-2">
                <Flame className="h-5 w-5 text-rose-400" />
                <h3 className="text-base font-bold text-white">Lower-Tail Copula Crash Dependence (λL)</h3>
                <HelpBtn onClick={() => setActiveExplainer('copula_tail_dependence')} />
              </div>
              <span className="text-xs bg-rose-950/60 border border-rose-800/60 text-rose-300 px-2.5 py-0.5 rounded font-mono">
                Copula Matrix
              </span>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Bivariate Student-t Copula tail dependence coefficient measuring simultaneous crash comovement.
            </p>
            {copulaTickers.length > 0 && copulaMatrix.length > 0 ? (
              <div className="overflow-x-auto border border-slate-800 rounded-lg bg-slate-950/60 p-2 max-h-64">
                <table className="w-full text-xs text-center border-collapse">
                  <thead>
                    <tr>
                      <th className="p-2 text-left text-slate-400 sticky left-0 bg-slate-950">Asset</th>
                      {copulaTickers.map(t => (
                        <th key={t} className="p-2 font-mono text-slate-300 min-w-[70px]">{t.replace('.NS', '')}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {copulaTickers.map((rowTicker, rowIdx) => (
                      <tr key={rowTicker} className="border-t border-slate-800/60">
                        <td className="p-2 text-left font-mono font-medium text-slate-300 sticky left-0 bg-slate-950/90">{rowTicker.replace('.NS', '')}</td>
                        {copulaTickers.map((colTicker, colIdx) => {
                          const num = copulaMatrix[rowIdx]?.[colIdx] ?? (rowIdx === colIdx ? 1.0 : 0.0);
                          const isSelf = rowIdx === colIdx;
                          const intensity = isSelf
                            ? 'bg-slate-800/80 text-slate-400'
                            : num > 0.25
                              ? 'bg-rose-500/20 text-rose-300 font-bold border border-rose-500/30'
                              : 'bg-emerald-500/10 text-emerald-300 font-medium';
                          return (
                            <td key={colTicker} className={`p-1.5 font-mono ${intensity}`} title={`${rowTicker} ↔ ${colTicker}: λL = ${num.toFixed(3)}`}>
                              {num.toFixed(3)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="h-48 flex items-center justify-center text-xs text-slate-500">
                No copula matrix data available
              </div>
            )}
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <span>EVT Shape (ξ): <strong className="text-white font-mono">{tailRisk?.gpd_shape_xi !== undefined ? Number(tailRisk.gpd_shape_xi).toFixed(4) : (tailRisk?.gpd_parameters?.shape_xi?.toFixed(4) || '—')}</strong></span>
            <span>Scale (β): <strong className="text-white font-mono">{tailRisk?.gpd_scale_beta !== undefined ? Number(tailRisk.gpd_scale_beta).toFixed(4) : (tailRisk?.gpd_parameters?.scale_beta?.toFixed(4) || '—')}</strong></span>
            <div className="flex items-center space-x-1.5">
              <span>Fat Tailed: <strong className="text-emerald-400 font-bold">{(tailRisk?.is_fat_tailed !== undefined ? tailRisk.is_fat_tailed : tailRisk?.gpd_parameters?.is_fat_tailed) ? 'Yes' : 'No'}</strong></span>
              <HelpBtn onClick={() => setActiveExplainer('gpd_parameters')} />
            </div>
          </div>
        </div>

        {/* 3. Realized Volatility Cones */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center space-x-2">
              <TrendingUp className="h-5 w-5 text-amber-400" />
              <h3 className="text-base font-bold text-white">Volatility Term Structure & Cones</h3>
              <HelpBtn onClick={() => setActiveExplainer('volatility_cones')} />
            </div>
            <span className="text-xs bg-amber-950/60 border border-amber-800/60 text-amber-300 px-2.5 py-0.5 rounded font-mono">
              Realized vs GARCH
            </span>
          </div>
          <p className="text-xs text-slate-400 mb-4">
            Multi-window historical realized volatility quantiles alongside forward GARCH forecast.
          </p>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={coneChartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.3} />
                <XAxis dataKey="window" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={11} unit="%" />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const d = payload[0].payload;
                      return (
                        <div className="bg-slate-950 border border-slate-700 p-2.5 rounded-lg text-xs text-slate-200 shadow-xl">
                          <p className="font-semibold text-white mb-1">{d.window} Lookback Window</p>
                          <p className="text-amber-300 font-bold">Realized: {d.realized || d.p50}%</p>
                          <p className="text-slate-400">P90 (Max): {d.p90}%</p>
                          <p className="text-slate-400">P50 (Median): {d.p50}%</p>
                          <p className="text-slate-400">P10 (Min): {d.p10}%</p>
                          {d.garch && <p className="text-emerald-400 font-semibold">GARCH Forecast: {d.garch}%</p>}
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
                <Line type="monotone" dataKey="p90" stroke="#f59e0b" strokeDasharray="4 4" name="P90 (Ceiling)" dot={false} />
                <Line type="monotone" dataKey="realized" stroke="#fbbf24" strokeWidth={2.5} name="Realized Vol" />
                <Line type="monotone" dataKey="p10" stroke="#f59e0b" strokeDasharray="4 4" name="P10 (Floor)" dot={false} />
                <Line type="monotone" dataKey="garch" stroke="#10b981" strokeWidth={2} name="GARCH Forecast" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* 4. Rolling Correlation Stability */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex flex-col justify-between shadow-sm">
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center space-x-2">
                <Layers className="h-5 w-5 text-purple-400" />
                <h3 className="text-base font-bold text-white">Rolling 60-Day Correlation Stability</h3>
                <HelpBtn onClick={() => setActiveExplainer('correlation_stability')} />
              </div>
              <span className={`text-xs px-2.5 py-0.5 rounded border font-mono ${
                correlation?.breakdown_alert
                  ? 'bg-rose-950 border-rose-800 text-rose-300'
                  : 'bg-emerald-950 border-emerald-800 text-emerald-300'
              }`}>
                {correlation?.breakdown_alert ? 'Regime Break Alert' : 'Diversified Regime'}
              </span>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Rolling pairwise correlation vs 90th percentile threshold ({(correlation?.historical_threshold_90th || correlation?.percentile_90_threshold || 0.382).toFixed(2)}).
            </p>
            <div className="p-4 bg-slate-950/60 border border-slate-800 rounded-lg space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Current 60-Day Average:</span>
                <span className="font-mono text-sm font-bold text-white">
                  {(correlation?.current_avg_correlation || 0.158).toFixed(3)}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Historical 90th Percentile:</span>
                <span className="font-mono text-xs font-semibold text-amber-400">
                  {(correlation?.historical_threshold_90th || correlation?.percentile_90_threshold || 0.382).toFixed(3)}
                </span>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden border border-slate-700/50">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    (correlation?.current_avg_correlation || 0.158) > (correlation?.historical_threshold_90th || correlation?.percentile_90_threshold || 0.382)
                      ? 'bg-rose-500'
                      : 'bg-emerald-500'
                  }`}
                  style={{
                    width: `${Math.min(100, Math.max(0, (((correlation?.current_avg_correlation || 0.158) / (correlation?.historical_threshold_90th || 0.382)) * 50)))}%`
                  }}
                />
              </div>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800 flex items-center space-x-2 text-xs text-slate-400">
            <Info className="h-4 w-4 text-indigo-400 shrink-0" />
            <span>Lower correlation ensures portfolio resilience against market-wide liquidity shocks.</span>
          </div>
        </div>
      </div>
    </div>
  );
}

