'use client';

import React, { useState, useEffect } from 'react';
import { RefreshCw, Zap } from 'lucide-react';
import api from '@/lib/api';

export default function IndiaFlowsPage() {
    const [loading, setLoading] = useState(true);
    const [flows, setFlows] = useState<any[]>([]);
    const [anomalies, setAnomalies] = useState<any[]>([]);
    const [liquidity, setLiquidity] = useState<any>(null);

    const fetchData = async () => {
        setLoading(true);
        try {
            const [flowRes, anomalyRes, liqRes] = await Promise.all([
                api.get('/analytics/india-flows?lookback_days=30').catch(() => ({ data: { flows: [] } })),
                api.get('/analytics/delivery-anomalies').catch(() => ({ data: { anomalies: [] } })),
                api.get('/analytics/liquidity-limits').catch(() => ({ data: { positions: [] } }))
            ]);
            setFlows(flowRes.data.flows || []);
            setAnomalies(anomalyRes.data.anomalies || []);
            setLiquidity(liqRes.data);
        } catch (err) {
            console.error('Error fetching India microstructure data', err);
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

            {/* Delivery Anomalies */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 shadow-sm">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                    Delivery % Spikes & Institutional Accumulation Alerts
                </h3>
                {anomalies.length === 0 ? (
                    <div className="py-8 text-center text-gray-500">No &gt;2σ delivery spikes detected in portfolio holdings today.</div>
                ) : (
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
                                        <td className="px-4 py-3 font-semibold">+{a.z_score}σ</td>
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
                )}
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
                                {liquidity.positions.map((p: any, idx: number) => (
                                    <tr key={idx} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                                        <td className="px-4 py-3 font-semibold text-gray-900 dark:text-white">{p.ticker}</td>
                                        <td className="px-4 py-3">₹{p.position_value.toLocaleString('en-IN')}</td>
                                        <td className="px-4 py-3">₹{p.adv_30d_rupees.toLocaleString('en-IN')}</td>
                                        <td className="px-4 py-3 font-medium">{p.days_to_liquidate_10pct_adv}d</td>
                                        <td className="px-4 py-3 font-medium">{p.days_to_liquidate_20pct_adv}d</td>
                                        <td className="px-4 py-3">
                                            <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${p.liquidity_tier === 'HIGHLY_LIQUID' ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300' : (p.liquidity_tier === 'MODERATE_LIQUIDITY' ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300' : 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300')}`}>
                                                {p.liquidity_tier}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}
