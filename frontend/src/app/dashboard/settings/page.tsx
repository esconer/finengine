'use client';

import React, { useEffect, useState } from 'react';
import { useUIStore, usePortfolioStore } from '@/lib/store';
import { dataApi } from '@/lib/api';
import {
    Settings,
    DollarSign,
    Shield,
    RefreshCw,
    CheckCircle2,
    Sliders,
    Server,
    HardDrive,
    Trash2,
    AlertTriangle
} from 'lucide-react';

type PrimarySource = 'bfinance' | 'yfinance';

interface CacheClearResult {
    cleared: Record<string, number>;
    total_rows_cleared: number;
    portfolio_preserved: boolean;
}

const SOURCE_META: Record<PrimarySource, { label: string; blurb: string }> = {
    bfinance: {
        label: 'bfinance (Recommended)',
        blurb: 'Fast quotes, 10-13Y Ind AS statements, Indian market depth',
    },
    yfinance: {
        label: 'yfinance',
        blurb: 'Yahoo Finance feed — global coverage, .NS/.BO auto-suffix',
    },
};

export default function SettingsPage() {
    const { darkMode, toggleDarkMode } = useUIStore();
    const { fetchPortfolio } = usePortfolioStore();

    const [currency, setCurrency] = useState<'INR' | 'USD'>('INR');
    const [benchmark, setBenchmark] = useState<string>('^NSEI');
    const [lookbackDays, setLookbackDays] = useState<number>(756);
    const [riskFreeRate, setRiskFreeRate] = useState<number>(7.0);
    const [targetVol, setTargetVol] = useState<number>(15.0);
    const [primarySource, setPrimarySource] = useState<PrimarySource>('bfinance');
    const [isSaving, setIsSaving] = useState(false);
    const [saveSuccess, setSaveSuccess] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [isClearingCache, setIsClearingCache] = useState(false);
    const [cacheMessage, setCacheMessage] = useState<string | null>(null);
    const [cacheClearedSummary, setCacheClearedSummary] = useState<CacheClearResult | null>(null);

    // Load the persisted primary source so the selector reflects backend truth
    useEffect(() => {
        let cancelled = false;
        dataApi.getConfig()
            .then((cfg) => {
                if (!cancelled && cfg?.primary_source) {
                    setPrimarySource(cfg.primary_source);
                }
            })
            .catch(() => {
                /* keep default bfinance on failure — backend falls back identically */
            });
        return () => { cancelled = true; };
    }, []);

    const fallbackChain =
        primarySource === 'bfinance'
            ? 'bfinance → yfinance → Alpha Vantage (last resort)'
            : 'yfinance → bfinance → Alpha Vantage (last resort)';

    const handleSavePreferences = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsSaving(true);
        setSaveSuccess(false);
        setSaveError(null);

        try {
            // Persist the data-source preference; the backend cascade honors
            // it on every subsequent fetch (no restart needed).
            await dataApi.updateConfig({ primary_source: primarySource });
            setSaveSuccess(true);
            setTimeout(() => setSaveSuccess(false), 3000);
        } catch (err) {
            setSaveError('Could not save the data-source preference. Is the backend running?');
            setTimeout(() => setSaveError(null), 5000);
        } finally {
            setIsSaving(false);
        }
    };

    const handleClearCache = async () => {
        const confirmed = window.confirm(
            'Purge all cached market data (price history, analytics, fetch logs, NSE microstructure)?\n\n' +
            'Fresh data will be pulled from the configured vendor chain on next use.\n' +
            'Your portfolio holdings (tickers, quantities, avg buy prices) are NOT affected.'
        );
        if (!confirmed) return;

        setIsClearingCache(true);
        setCacheMessage(null);
        setCacheClearedSummary(null);
        try {
            const result = await dataApi.clearCache();
            setCacheClearedSummary(result);
            setCacheMessage(
                `Cleared ${result.total_rows_cleared.toLocaleString('en-IN')} cached rows. ` +
                'Portfolio holdings preserved.'
            );
            // Refresh live views so stale numbers vanish immediately
            await fetchPortfolio();
            setTimeout(() => setCacheMessage(null), 6000);
        } catch (err) {
            setCacheMessage('Cache purge failed. Is the backend running?');
            setTimeout(() => setCacheMessage(null), 5000);
        } finally {
            setIsClearingCache(false);
        }
    };

    const nonZeroCleared = cacheClearedSummary
        ? Object.entries(cacheClearedSummary.cleared).filter(
            ([key, count]) => key !== 'in_memory_caches' && count > 0
        )
        : [];

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

            {saveError && (
                <div className="p-4 bg-red-950/40 border border-red-800/60 rounded-xl flex items-center space-x-3 text-red-300 text-sm">
                    <AlertTriangle className="h-5 w-5 text-red-400 shrink-0" />
                    <span>{saveError}</span>
                </div>
            )}

            {cacheMessage && (
                <div className="p-4 bg-blue-950/40 border border-blue-800/60 rounded-xl flex items-start space-x-3 text-blue-300 text-sm">
                    <CheckCircle2 className="h-5 w-5 text-blue-400 shrink-0 mt-0.5" />
                    <div className="space-y-1">
                        <span>{cacheMessage}</span>
                        {cacheClearedSummary && nonZeroCleared.length > 0 && (
                            <p className="text-[11px] text-blue-400/80">
                                {nonZeroCleared.map(([store, count]) => `${store}: ${count.toLocaleString('en-IN')}`).join(' · ')}
                            </p>
                        )}
                    </div>
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

                {/* 3. Data Sources & Engine Connectivity */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
                    <h2 className="text-base font-semibold text-white flex items-center space-x-2 mb-4">
                        <Server className="h-5 w-5 text-amber-400" />
                        <span>Data Feed Architecture & Infrastructure</span>
                    </h2>

                    {/* Primary data source selector */}
                    <div className="mb-6">
                        <label className="block text-xs font-medium text-slate-300 mb-2">
                            Primary Data Source
                        </label>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            {(Object.keys(SOURCE_META) as PrimarySource[]).map((source) => {
                                const selected = primarySource === source;
                                return (
                                    <button
                                        key={source}
                                        type="button"
                                        onClick={() => setPrimarySource(source)}
                                        className={`text-left p-4 rounded-lg border transition ${
                                            selected
                                                ? 'border-blue-500 bg-blue-950/40 shadow-lg shadow-blue-900/20'
                                                : 'border-slate-800 bg-slate-950/60 hover:border-slate-600'
                                        }`}
                                    >
                                        <div className="flex items-center justify-between mb-1">
                                            <span className={`text-sm font-medium ${selected ? 'text-blue-300' : 'text-slate-300'}`}>
                                                {SOURCE_META[source].label}
                                            </span>
                                            {selected && (
                                                <span className="flex items-center space-x-1 text-xs text-blue-400">
                                                    <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
                                                    <span>Primary</span>
                                                </span>
                                            )}
                                        </div>
                                        <p className="text-[11px] text-slate-500">{SOURCE_META[source].blurb}</p>
                                    </button>
                                );
                            })}
                        </div>
                        <div className="mt-3 flex items-center space-x-2 text-xs text-slate-400 bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-2">
                            <HardDrive className="w-4 h-4 text-slate-500 shrink-0" />
                            <span>
                                Fallback chain: <span className="text-slate-200 font-mono">{fallbackChain}</span>
                                {' '}— the other vendor is always the fallback; Alpha Vantage is the last resort.
                            </span>
                        </div>
                        <p className="text-[11px] text-slate-500 mt-2">
                            Applies to price history, live quotes, and fundamentals. Concall audio, audited
                            statements, and screeners remain bfinance-exclusive; USD/INR FX remains yfinance-only.
                        </p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-xs font-medium text-slate-300">Market Price Feed</span>
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
                    <div className="flex flex-col items-center sm:items-start gap-1">
                        <button
                            type="button"
                            onClick={handleClearCache}
                            disabled={isClearingCache}
                            className="flex items-center space-x-2 px-4 py-2.5 text-xs font-medium text-red-300 bg-red-950/40 hover:bg-red-950/70 border border-red-900/60 rounded-lg transition disabled:opacity-50"
                        >
                            {isClearingCache ? (
                                <RefreshCw className="w-4 h-4 animate-spin text-red-400" />
                            ) : (
                                <Trash2 className="w-4 h-4" />
                            )}
                            <span>Clear Market Data Cache</span>
                        </button>
                        <p className="text-[11px] text-slate-500 flex items-center gap-1">
                            <Shield className="w-3 h-3" />
                            Portfolio holdings (tickers, quantities, avg buy prices) are never touched.
                        </p>
                    </div>

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
