'use client';

import React, { useState, useEffect } from 'react';
import { RefreshCw, Radar, AlertCircle } from 'lucide-react';
import api from '@/lib/api';

export default function PairsScannerPage() {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [pairs, setPairs] = useState<any[]>([]);
    const [lookbackDays] = useState(252);
    const [pValueThreshold] = useState(0.05);

    const fetchPairs = async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await api.get(`/analytics/coint?lookback_days=${lookbackDays}&p_value_threshold=${pValueThreshold}`);
            setPairs(res.data.pairs || []);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Failed to scan cointegrated pairs');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchPairs();
    }, [lookbackDays, pValueThreshold]);

    return (
        <div className="space-y-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
                        <Radar className="w-6 h-6 text-blue-600" />
                        Cointegration & Pairs Scanner
                    </h1>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                        Engle-Granger & Johansen rank tests with Ornstein-Uhlenbeck mean-reversion half-life.
                    </p>
                </div>
                <button
                    onClick={fetchPairs}
                    disabled={loading}
                    className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Scan Universe
                </button>
            </div>

            {error && (
                <div className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-800 dark:text-red-300 flex items-center gap-2">
                    <AlertCircle className="w-5 h-5 flex-shrink-0" />
                    <span>{error}</span>
                </div>
            )}

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 shadow-sm">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                    Ranked Statistical Arbitrage & Mean-Reversion Pairs
                </h3>
                {loading ? (
                    <div className="py-12 text-center text-gray-500">Scanning pairs across your universe...</div>
                ) : pairs.length === 0 ? (
                    <div className="py-12 text-center text-gray-500">
                        No cointegrated pairs found at p &lt; {pValueThreshold}. Add more holdings to expand scanning universe.
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm text-gray-500 dark:text-gray-400">
                            <thead className="bg-gray-50 dark:bg-gray-700/50 text-xs uppercase text-gray-700 dark:text-gray-300">
                                <tr>
                                    <th className="px-4 py-3">Pair</th>
                                    <th className="px-4 py-3">P-Value (EG)</th>
                                    <th className="px-4 py-3">Hedge Ratio (β)</th>
                                    <th className="px-4 py-3">OU Half-Life</th>
                                    <th className="px-4 py-3">Spread Z-Score</th>
                                    <th className="px-4 py-3">Signal</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                                {pairs.map((p, idx) => (
                                    <tr key={idx} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                                        <td className="px-4 py-3 font-semibold text-gray-900 dark:text-white">
                                            {p.ticker_a} / {p.ticker_b}
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${p.engle_granger_pvalue < 0.01 ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'}`}>
                                                {p.engle_granger_pvalue.toFixed(4)}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 font-mono">{p.hedge_ratio_beta.toFixed(4)}</td>
                                        <td className="px-4 py-3">
                                            {p.ou_half_life_days ? `${p.ou_half_life_days.toFixed(1)} days` : 'N/A'}
                                        </td>
                                        <td className={`px-4 py-3 font-mono ${Math.abs(p.current_spread_zscore) > 2 ? 'text-amber-600 dark:text-amber-400 font-bold' : ''}`}>
                                            {p.current_spread_zscore.toFixed(2)}σ
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${p.signal === 'NEUTRAL' ? 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300' : 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300'}`}>
                                                {p.signal}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
}
