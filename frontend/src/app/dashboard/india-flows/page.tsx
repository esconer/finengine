'use client';

import React, { useState, useEffect } from 'react';
import { RefreshCw, Zap, AlertCircle } from 'lucide-react';
import api from '@/lib/api';

export default function IndiaFlowsPage() {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [flows, setFlows] = useState<any[]>([]);
    const [anomalies, setAnomalies] = useState<any[]>([]);
    const [liquidity, setLiquidity] = useState<any>(null);
    const [lastUpdated, setLastUpdated] = useState<string | null>(null);

    const fetchData = async () => {
        setLoading(true);
        setError(null);
        try {
            // No per-request .catch: an outage must surface as an error,
            // never as a fabricated "no anomalies" success.
            const [flowRes, anomalyRes, liqRes] = await Promise.all([
                api.get('/analytics/india-flows?lookback_days=30'),
                api.get('/analytics/delivery-anomalies'),
                api.get('/analytics/liquidity-limits')
            ]);
            setFlows(flowRes.data.flows || []);
            setAnomalies(anomalyRes.data.anomalies || []);
            setLiquidity(liqRes.data);
            setLastUpdated(new Date().toISOString());
        } catch (err) {
            console.error('Error fetching India microstructure data', err);
            setError(err instanceof Error ? err.message : 'Failed to load India microstructure data');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, []);

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
                        <Zap className="w-6 h-6 text-amber-500" />
                        India Market Microstructure & Flows
                    </h1>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                        NSE delivery anomalies, FII/DII institutional net flows, and participation ADV limits.
                        {lastUpdated && (
                            <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">
                                As of {new Date(lastUpdated).toLocaleTimeString('en-IN')}
                            </span>
                        )}
                    </p>
                </div>
                <button
                    onClick={fetchData}
                    disabled={loading}
                    className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

            {error && (
                <div className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-800 dark:text-red-300 flex items-center gap-2" data-testid="india-flows-error">
                    <AlertCircle className="w-5 h-5 flex-shrink-0" />
                    <span>{error}</span>
                </div>
            )}

            {/* FII/DII Institutional Net Flows (30D) */}
            {!loading && !error && (
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 shadow-sm">
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                        FII/DII Institutional Net Flows (30D)
                    </h3>
                    {flows.length === 0 ? (
                        <div className="py-8 text-center text-gray-500">No institutional flow records available for the last 30 sessions.</div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-sm text-gray-500 dark:text-gray-400">
                                <thead className="bg-gray-50 dark:bg-gray-700/50 text-xs uppercase text-gray-700 dark:text-gray-300">
                                    <tr>
                                        <th className="px-4 py-3">Date</th>
                                        <th className="px-4 py-3">FII Net (₹ Cr)</th>
                                        <th className="px-4 py-3">DII Net (₹ Cr)</th>
                                        <th className="px-4 py-3">Total Net (₹ Cr)</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                                    {flows.map((f, idx) => (
                                        <tr key={idx} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                                            <td className="px-4 py-3 font-semibold text-gray-900 dark:text-white">{f.date}</td>
                                            <td className={`px-4 py-3 font-mono ${(f.fii_net_crores ?? 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                                                {f.fii_net_crores}
                                            </td>
                                            <td className={`px-4 py-3 font-mono ${(f.dii_net_crores ?? 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                                                {f.dii_net_crores}
                                            </td>
                                            <td className="px-4 py-3 font-mono font-semibold">
                                                {f.total_net_crores}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {/* Delivery Anomalies */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 shadow-sm">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                    Delivery % Spikes & Institutional Accumulation Alerts
                </h3>
                {loading ? (
                    <div className="py-8 text-center text-gray-500">Loading delivery anomalies…</div>
                ) : !error && anomalies.length === 0 ? (
                    <div className="py-8 text-center text-gray-500">No &gt;2σ delivery spikes detected in portfolio holdings today.</div>
                ) : anomalies.length > 0 ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm text-gray-500 dark:text-gray-400">
                            <thead className="bg-gray-50 dark:bg-gray-700/50 text-xs uppercase text-gray-700 dark:text-gray-300">
                                <tr>
                                    <th className="px-4 py-3">Symbol</th>
                                    <th className="px-4 py-3">Today Delivery %</th>
                                    <th className="px-4 py-3">20D Avg Delivery %</th>
                                    <th className="px-4 py-3">Z-Score</th>
                                    <th className="px-4 py-3">Signal</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                                {anomalies.map((a, idx) => (
                                    <tr key={idx} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                                        <td className="px-4 py-3 font-semibold text-gray-900 dark:text-white">{a.symbol}</td>
                                        <td className="px-4 py-3 font-bold text-green-600">{a.current_delivery_pct}%</td>
                                        <td className="px-4 py-3">{a.avg_20d_delivery_pct}%</td>
                                        <td className="px-4 py-3 font-semibold">
                                            {a.z_score > 0 ? `+${a.z_score}` : a.z_score}σ
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${a.is_anomaly ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'}`}>
                                                {a.signal}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : null}
            </div>

            {/* ADV Liquidity Limits */}
            {liquidity && liquidity.positions && liquidity.positions.length > 0 && (
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 shadow-sm">
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                        Participation-Based Liquidity & Days-to-Liquidate
                    </h3>
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm text-gray-500 dark:text-gray-400">
                            <thead className="bg-gray-50 dark:bg-gray-700/50 text-xs uppercase text-gray-700 dark:text-gray-300">
                                <tr>
                                    <th className="px-4 py-3">Holding</th>
                                    <th className="px-4 py-3">Market Value</th>
                                    <th className="px-4 py-3">30D ADV</th>
                                    <th className="px-4 py-3">Days @ 10% ADV</th>
                                    <th className="px-4 py-3">Days @ 20% ADV</th>
                                    <th className="px-4 py-3">Liquidity Tier</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                                {liquidity.positions.map((p: any, idx: number) => {
                                    const formatInr = (val: number) => {
                                        if (!val) return '₹0';
                                        if (val >= 10000000) return `₹${(val / 10000000).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Cr`;
                                        if (val >= 100000) return `₹${(val / 100000).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} L`;
                                        return `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
                                    };
                                    // Sub-0.1 day liquidation windows are real but round to "0d";
                                    // only a zero market value is a true 0-day position.
                                    const formatDays = (days: number | null | undefined, marketValue: number, adv: number) => {
                                        const d = typeof days === 'number' && !isNaN(days) ? days : 0;
                                        if (d > 0 && d < 0.1) return '<0.1d';
                                        if (d === 0 && marketValue > 0 && adv > 0) return '<0.1d';
                                        return `${d}d`;
                                    };
                                    return (
                                        <tr key={idx} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                                            <td className="px-4 py-3 font-semibold text-gray-900 dark:text-white">{p.ticker}</td>
                                            <td className="px-4 py-3 font-mono">₹{p.position_value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</td>
                                            <td className="px-4 py-3 font-mono font-medium text-slate-900 dark:text-slate-200">{formatInr(p.adv_30d_rupees)}</td>
                                            <td className="px-4 py-3 font-medium">{formatDays(p.days_to_liquidate_10pct_adv, p.position_value, p.adv_30d_rupees)}</td>
                                            <td className="px-4 py-3 font-medium">{formatDays(p.days_to_liquidate_20pct_adv, p.position_value, p.adv_30d_rupees)}</td>
                                            <td className="px-4 py-3">
                                                <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${p.liquidity_tier === 'HIGHLY_LIQUID' ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300' : (p.liquidity_tier === 'MODERATE_LIQUIDITY' ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300' : 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300')}`}>
                                                    {p.liquidity_tier}
                                                </span>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}
