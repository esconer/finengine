'use client';

import React, { useState, useEffect } from 'react';
import { DashboardLayout } from '@/components/layout/DashboardLayout';
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
    CheckCircle2
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
    Line
} from 'recharts';

export default function RiskStudioPage() {
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState<string | null>(null);

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

    if (loading) {
        return (
            <DashboardLayout title="Risk Studio">
                <LoadingState message="Compiling institutional risk canvas (Euler, EVT, Copula, Vol Cones)..." />
            </DashboardLayout>
        );
    }

    // Format helpers
    const fmtPct = (val: number | undefined | null) =>
        val !== undefined && val !== null ? `${(val * 100).toFixed(2)}%` : '—';

    // Prepare Euler Chart Data
    const eulerPositions = riskContribution?.positions
        ? Object.entries(riskContribution.positions).map(([ticker, data]: [string, any]) => ({
              ticker,
              vol_contrib: +(data.vol_contribution_pct || 0).toFixed(1),
              cvar_contrib: +(data.cvar_contribution_pct || 0).toFixed(1)
          }))
        : [];

    // Prepare Vol Cone Chart Data
    const coneWindows = [10, 21, 63, 126, 252];
    const coneChartData = coneWindows.map(w => {
        const q = volCone?.quantiles?.[String(w)] || {};
        return {
            window: `${w}D`,
            p10: +(q.p10 * 100 || 0).toFixed(1),
            p25: +(q.p25 * 100 || 0).toFixed(1),
            p50: +(q.p50 * 100 || 0).toFixed(1),
            p75: +(q.p75 * 100 || 0).toFixed(1),
            p90: +(q.p90 * 100 || 0).toFixed(1),
            garch: volCone?.garch_forecast_vol ? +(volCone.garch_forecast_vol * 100).toFixed(1) : undefined
        };
    });

    return (
        <DashboardLayout title="Risk Studio">
            <div className="space-y-6 pb-12">
                {/* Header */}
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                    <div>
                        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center space-x-2">
                            <ShieldAlert className="h-7 w-7 text-indigo-500" />
                            <span>Consolidated Risk Studio</span>
                        </h1>
                        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                            Institutional multi-factor risk attribution, Extreme Value Theory (EVT), Student-t Copula crash dependence, and Volatility Cones.
                        </p>
                    </div>
                    <button
                        onClick={handleRefresh}
                        disabled={refreshing}
                        className="flex items-center space-x-2 px-4 py-2 text-sm font-medium text-slate-200 bg-slate-800 border border-slate-700 rounded-lg hover:bg-slate-700 transition disabled:opacity-50 self-start sm:self-auto"
                    >
                        <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-blue-400' : ''}`} />
                        <span>Refresh Studio</span>
                    </button>
                </div>

                {error && (
                    <div className="p-4 bg-red-950/40 border border-red-800/60 rounded-xl flex items-center space-x-3 text-red-300 text-sm">
                        <AlertTriangle className="h-5 w-5 text-red-400 shrink-0" />
                        <span>{error}</span>
                    </div>
                )}

                {/* Top Metrics Row */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <MetricCard
                        title="Portfolio Volatility (ann.)"
                        value={fmtPct(riskContribution?.portfolio_volatility)}
                        icon={Activity}
                    />
                    <MetricCard
                        title="99% EVT-POT VaR (1-Day)"
                        value={fmtPct(tailRisk?.evt_var_99)}
                        icon={Flame}
                    />
                    <MetricCard
                        title="99% Expected Shortfall"
                        value={fmtPct(tailRisk?.evt_es_99)}
                        icon={ShieldAlert}
                    />
                    <MetricCard
                        title="Correlation Regime"
                        value={correlation?.alert_level || 'NORMAL'}
                        icon={Layers}
                    />
                </div>

                {/* Main 2x2 Canvas Grid */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* 1. Euler Risk Contribution */}
                    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex flex-col justify-between">
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <h3 className="text-base font-semibold text-white flex items-center space-x-2">
                                    <Activity className="h-5 w-5 text-blue-400" />
                                    <span>Euler Volatility & Tail CVaR Share</span>
                                </h3>
                                <span className="text-xs bg-blue-950 border border-blue-800 text-blue-300 px-2 py-0.5 rounded">
                                    Attribution
                                </span>
                            </div>
                            <p className="text-xs text-slate-400 mb-4">
                                Exact percentage of portfolio variance and worst 5% tail losses driven by each asset.
                            </p>
                            <div className="h-64 w-full">
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={eulerPositions} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.3} />
                                        <XAxis dataKey="ticker" stroke="#94a3b8" fontSize={11} />
                                        <YAxis stroke="#94a3b8" fontSize={11} unit="%" />
                                        <Tooltip
                                            content={({ active, payload }) => {
                                                if (active && payload && payload.length) {
                                                    const d = payload[0].payload;
                                                    return (
                                                        <div className="bg-slate-950 border border-slate-700 p-2.5 rounded-lg text-xs text-slate-200">
                                                            <p className="font-semibold text-white">{d.ticker}</p>
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
                        {riskContribution?.sector_vol_shares && (
                            <div className="mt-4 pt-3 border-t border-slate-800 flex flex-wrap gap-2 text-xs">
                                <span className="text-slate-400">Sector Rollup:</span>
                                {Object.entries(riskContribution.sector_vol_shares).map(([sec, share]: [string, any]) => (
                                    <span key={sec} className="bg-slate-800 px-2 py-0.5 rounded text-slate-300">
                                        {sec}: <strong className="text-white">{(share * 100).toFixed(1)}%</strong>
                                    </span>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* 2. Bivariate Student-t Copula Lower-Tail Matrix */}
                    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex flex-col justify-between">
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <h3 className="text-base font-semibold text-white flex items-center space-x-2">
                                    <Flame className="h-5 w-5 text-rose-400" />
                                    <span>Lower-Tail Copula Crash Dependence (λL)</span>
                                </h3>
                                <span className="text-xs bg-rose-950 border border-rose-800 text-rose-300 px-2 py-0.5 rounded">
                                    Copula Matrix
                                </span>
                            </div>
                            <p className="text-xs text-slate-400 mb-4">
                                Bivariate Student-t Copula tail dependence coefficient measuring simultaneous crash comovement.
                            </p>
                            {tailRisk?.tail_dependence_matrix ? (
                                <div className="overflow-x-auto border border-slate-800 rounded-lg bg-slate-950/60 p-2">
                                    <table className="w-full text-xs text-center">
                                        <thead>
                                            <tr>
                                                <th className="p-2 text-left text-slate-400">Asset</th>
                                                {Object.keys(tailRisk.tail_dependence_matrix).map(k => (
                                                    <th key={k} className="p-2 font-mono text-slate-300">{k}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {Object.entries(tailRisk.tail_dependence_matrix).map(([rowK, cols]: [string, any]) => (
                                                <tr key={rowK} className="border-t border-slate-800/60">
                                                    <td className="p-2 text-left font-mono font-medium text-slate-300">{rowK}</td>
                                                    {Object.entries(cols).map(([colK, val]: [string, any]) => {
                                                        const num = typeof val === 'number' ? val : 0;
                                                        const isSelf = rowK === colK;
                                                        const intensity = isSelf ? 'bg-slate-800/80 text-slate-400' : num > 0.3 ? 'bg-rose-500/20 text-rose-300 font-semibold' : 'bg-emerald-500/10 text-emerald-300';
                                                        return (
                                                            <td key={colK} className={`p-2 font-mono ${intensity}`}>
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
                            <span>EVT Shape: <strong className="text-white font-mono">{tailRisk?.gpd_parameters?.shape_xi?.toFixed(4) || '—'}</strong></span>
                            <span>Scale: <strong className="text-white font-mono">{tailRisk?.gpd_parameters?.scale_beta?.toFixed(4) || '—'}</strong></span>
                            <span>Fat Tailed: <strong className="text-emerald-400">{tailRisk?.gpd_parameters?.is_fat_tailed ? 'Yes' : 'No'}</strong></span>
                        </div>
                    </div>

                    {/* 3. Realized Volatility Cones */}
                    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-base font-semibold text-white flex items-center space-x-2">
                                <TrendingUp className="h-5 w-5 text-amber-400" />
                                <span>Volatility Term Structure & Cones</span>
                            </h3>
                            <span className="text-xs bg-amber-950 border border-amber-800 text-amber-300 px-2 py-0.5 rounded">
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
                                                    <div className="bg-slate-950 border border-slate-700 p-2.5 rounded-lg text-xs text-slate-200">
                                                        <p className="font-semibold text-white mb-1">{d.window} Lookback Window</p>
                                                        <p className="text-slate-400">P90 (Max): {d.p90}%</p>
                                                        <p className="text-amber-400 font-medium">P50 (Median): {d.p50}%</p>
                                                        <p className="text-slate-400">P10 (Min): {d.p10}%</p>
                                                        {d.garch && <p className="text-emerald-400 font-semibold">GARCH Forecast: {d.garch}%</p>}
                                                    </div>
                                                );
                                            }
                                            return null;
                                        }}
                                    />
                                    <Line type="monotone" dataKey="p90" stroke="#f59e0b" strokeDasharray="4 4" name="P90" dot={false} />
                                    <Line type="monotone" dataKey="p50" stroke="#fbbf24" strokeWidth={2} name="P50 (Median)" />
                                    <Line type="monotone" dataKey="p10" stroke="#f59e0b" strokeDasharray="4 4" name="P10" dot={false} />
                                    <Line type="monotone" dataKey="garch" stroke="#10b981" strokeWidth={2} name="GARCH Forecast" />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                    </div>

                    {/* 4. Rolling Correlation Stability */}
                    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex flex-col justify-between">
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <h3 className="text-base font-semibold text-white flex items-center space-x-2">
                                    <Layers className="h-5 w-5 text-purple-400" />
                                    <span>Rolling 60-Day Correlation Stability</span>
                                </h3>
                                <span className={`text-xs px-2 py-0.5 rounded border ${
                                    correlation?.breakdown_alert
                                        ? 'bg-red-950 border-red-800 text-red-300'
                                        : 'bg-emerald-950 border-emerald-800 text-emerald-300'
                                }`}>
                                    {correlation?.breakdown_alert ? 'Regime Break Alert' : 'Diversified Regime'}
                                </span>
                            </div>
                            <p className="text-xs text-slate-400 mb-4">
                                Rolling pairwise correlation vs 90th percentile threshold ({correlation?.percentile_90_threshold?.toFixed(2) || '0.54'}).
                            </p>
                            <div className="p-4 bg-slate-950/60 border border-slate-800 rounded-lg space-y-3">
                                <div className="flex items-center justify-between text-xs">
                                    <span className="text-slate-400">Current 60-Day Average:</span>
                                    <span className="font-mono text-sm font-semibold text-white">
                                        {(correlation?.current_avg_correlation || 0).toFixed(3)}
                                    </span>
                                </div>
                                <div className="flex items-center justify-between text-xs">
                                    <span className="text-slate-400">Historical 90th Percentile:</span>
                                    <span className="font-mono text-xs text-amber-400">
                                        {(correlation?.percentile_90_threshold || 0).toFixed(3)}
                                    </span>
                                </div>
                                <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                                    <div
                                        className={`h-full rounded-full ${
                                            (correlation?.current_avg_correlation || 0) > (correlation?.percentile_90_threshold || 0.54)
                                                ? 'bg-rose-500'
                                                : 'bg-emerald-500'
                                        }`}
                                        style={{
                                            width: `${Math.min(100, Math.max(0, ((correlation?.current_avg_correlation || 0) + 1) * 50))}%`
                                        }}
                                    />
                                </div>
                            </div>
                        </div>
                        <div className="mt-4 pt-3 border-t border-slate-800 flex items-center space-x-2 text-xs text-slate-400">
                            <Info className="h-4 w-4 text-slate-500 shrink-0" />
                            <span>Lower correlation ensures portfolio resilience against market-wide liquidity shocks.</span>
                        </div>
                    </div>
                </div>
            </div>
        </DashboardLayout>
    );
}
