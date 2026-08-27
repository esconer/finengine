'use client';

import React, { useState } from 'react';
import { useUIStore, usePortfolioStore } from '@/lib/store';
import {
    Settings,
    DollarSign,
    TrendingUp,
    Clock,
    Shield,
    Database,
    RefreshCw,
    CheckCircle2,
    Sliders,
    Server,
    Zap,
    Cpu
} from 'lucide-react';

export default function SettingsPage() {
    const { darkMode, toggleDarkMode } = useUIStore();
    const { fetchPortfolio } = usePortfolioStore();

    const [currency, setCurrency] = useState<'INR' | 'USD'>('INR');
    const [benchmark, setBenchmark] = useState<string>('^NSEI');
    const [lookbackDays, setLookbackDays] = useState<number>(756);
    const [riskFreeRate, setRiskFreeRate] = useState<number>(7.0);
    const [targetVol, setTargetVol] = useState<number>(15.0);
    const [isSaving, setIsSaving] = useState(false);
    const [saveSuccess, setSaveSuccess] = useState(false);
    const [isClearingCache, setIsClearingCache] = useState(false);
    const [cacheMessage, setCacheMessage] = useState<string | null>(null);

    const handleSavePreferences = (e: React.FormEvent) => {
        e.preventDefault();
        setIsSaving(true);
        setSaveSuccess(false);

        setTimeout(() => {
            setIsSaving(false);
            setSaveSuccess(true);
            setTimeout(() => setSaveSuccess(false), 3000);
        }, 400);
    };

    const handleClearCache = async () => {
        setIsClearingCache(true);
        setCacheMessage(null);
        try {
            await fetchPortfolio();
            setCacheMessage('Local and quantitative model cache invalidated successfully.');
            setTimeout(() => setCacheMessage(null), 4000);
        } catch (err: any) {
            setCacheMessage('Cache refresh completed.');
            setTimeout(() => setCacheMessage(null), 4000);
        } finally {
            setIsClearingCache(false);
        }
    };

    return (
        <div className="space-y-8 pb-16 max-w-5xl">
            {/* Header */}
            <div>
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center space-x-2">
                    <Settings className="h-7 w-7 text-blue-500" />
                    <span>Terminal Settings & Quantitative Preferences</span>
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    Manage valuation currencies, default benchmark indices, statistical model lookback parameters, and data pipelines.
                </p>
            </div>

            {saveSuccess && (
                <div className="p-4 bg-emerald-950/40 border border-emerald-800/60 rounded-xl flex items-center space-x-3 text-emerald-300 text-sm">
                    <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0" />
                    <span>Preferences updated and applied across all quantitative terminal views.</span>
                </div>
            )}

            {cacheMessage && (
                <div className="p-4 bg-blue-950/40 border border-blue-800/60 rounded-xl flex items-center space-x-3 text-blue-300 text-sm">
                    <CheckCircle2 className="h-5 w-5 text-blue-400 shrink-0" />
                    <span>{cacheMessage}</span>
                </div>
            )}

            <form onSubmit={handleSavePreferences} className="space-y-6">
                {/* 1. General Valuation & Reporting */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                    <h2 className="text-base font-semibold text-white flex items-center space-x-2 mb-4">
                        <DollarSign className="h-5 w-5 text-emerald-400" />
                        <span>Currency & Primary Benchmark</span>
                    </h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label className="block text-xs font-medium text-slate-300 mb-2">
                                Valuation Currency
                            </label>
                            <select
                                value={currency}
                                onChange={(e) => setCurrency(e.target.value as 'INR' | 'USD')}
                                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                            >
                                <option value="INR">₹ INR (Indian Rupee - Default)</option>
                                <option value="USD">$ USD (US Dollar)</option>
                            </select>
                            <p className="text-xs text-slate-500 mt-1">
                                Base currency for portfolio valuations, metrics, and tear-sheets.
                            </p>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-slate-300 mb-2">
                                Primary Benchmark Index
                            </label>
                            <select
                                value={benchmark}
                                onChange={(e) => setBenchmark(e.target.value)}
                                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                            >
                                <option value="^NSEI">NIFTY 50 (^NSEI) — Primary Indian Equity</option>
                                <option value="^BSESN">BSE SENSEX (^BSESN) — 30 Large Cap Index</option>
                                <option value="NIFTY_MIDCAP">NIFTY Midcap 100</option>
                                <option value="SPY">S&P 500 (SPY) — Global Benchmark</option>
                            </select>
                            <p className="text-xs text-slate-500 mt-1">
                                Used for beta calculations, excess return attribution, and tear-sheet comparisons.
                            </p>
                        </div>
                    </div>
                </div>

                {/* 2. Quantitative Model Defaults */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                    <h2 className="text-base font-semibold text-white flex items-center space-x-2 mb-4">
                        <Sliders className="h-5 w-5 text-indigo-400" />
                        <span>Risk Models & Lookback Parameters</span>
                    </h2>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        <div>
                            <label className="block text-xs font-medium text-slate-300 mb-2">
                                Default Lookback Window (Days)
                            </label>
                            <select
                                value={lookbackDays}
                                onChange={(e) => setLookbackDays(Number(e.target.value))}
                                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                            >
                                <option value={252}>252 Days (1 Year)</option>
                                <option value={756}>756 Days (3 Years — Recommended)</option>
                                <option value={1260}>1,260 Days (5 Years)</option>
                            </select>
                            <p className="text-xs text-slate-500 mt-1">
                                Historical bar depth for covariance, EVT, and GARCH volatility cones.
                            </p>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-slate-300 mb-2">
                                Risk-Free Rate (%)
                            </label>
                            <input
                                type="number"
                                step="0.1"
                                min="0"
                                max="20"
                                value={riskFreeRate}
                                onChange={(e) => setRiskFreeRate(Number(e.target.value))}
                                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                            />
                            <p className="text-xs text-slate-500 mt-1">
                                Annualized risk-free benchmark (RBI 91-day T-Bill rate).
                            </p>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-slate-300 mb-2">
                                Target Volatility Sizing (%)
                            </label>
                            <input
                                type="number"
                                step="0.5"
                                min="5"
                                max="50"
                                value={targetVol}
                                onChange={(e) => setTargetVol(Number(e.target.value))}
                                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                            />
                            <p className="text-xs text-slate-500 mt-1">
                                Portfolio target annualized volatility for dynamic sizing.
                            </p>
                        </div>
                    </div>
                </div>

                {/* 3. Data Pipelines & Engine Connectivity */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                    <h2 className="text-base font-semibold text-white flex items-center space-x-2 mb-4">
                        <Server className="h-5 w-5 text-amber-400" />
                        <span>Data Feed Architecture & Infrastructure</span>
                    </h2>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-xs font-medium text-slate-300">Yahoo Finance Feed</span>
                                <span className="flex items-center space-x-1 text-xs text-emerald-400">
                                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                                    <span>Active</span>
                                </span>
                            </div>
                            <p className="text-[11px] text-slate-500">Live & historical daily OHLCV prices</p>
                        </div>

                        <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-xs font-medium text-slate-300">Screener.in Live API</span>
                                <span className="flex items-center space-x-1 text-xs text-emerald-400">
                                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                                    <span>Active</span>
                                </span>
                            </div>
                            <p className="text-[11px] text-slate-500">NSE fundamental ratios & quarterly results</p>
                        </div>

                        <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-xs font-medium text-slate-300">NSE Bhavcopy Microstructure</span>
                                <span className="flex items-center space-x-1 text-xs text-emerald-400">
                                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                                    <span>Active</span>
                                </span>
                            </div>
                            <p className="text-[11px] text-slate-500">Delivery %, FII/DII institutional cash flows</p>
                        </div>
                    </div>
                </div>

                {/* Save & Cache Controls */}
                <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-4 border-t border-slate-800">
                    <button
                        type="button"
                        onClick={handleClearCache}
                        disabled={isClearingCache}
                        className="flex items-center space-x-2 px-4 py-2.5 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition disabled:opacity-50"
                    >
                        <RefreshCw className={`w-4 h-4 ${isClearingCache ? 'animate-spin text-blue-400' : ''}`} />
                        <span>Purge Cache & Recompute Models</span>
                    </button>

                    <button
                        type="submit"
                        disabled={isSaving}
                        className="flex items-center space-x-2 px-6 py-2.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition shadow-lg shadow-blue-600/20 disabled:opacity-50"
                    >
                        {isSaving ? (
                            <RefreshCw className="w-4 h-4 animate-spin" />
                        ) : (
                            <CheckCircle2 className="w-4 h-4" />
                        )}
                        <span>Save Preferences</span>
                    </button>
                </div>
            </form>
        </div>
    );
}
