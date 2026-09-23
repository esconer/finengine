'use client';

import React, { useEffect, useState } from 'react';
import { useUIStore, usePortfolioStore } from '@/lib/store';
import { dataApi } from '@/lib/api';
import {
    Settings,
    Shield,
    RefreshCw,
    CheckCircle2,
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

    const [primarySource, setPrimarySource] = useState<PrimarySource>('bfinance');
    const [savedSource, setSavedSource] = useState<PrimarySource | null>(null);
    const [isSaving, setIsSaving] = useState(false);
    const [saveSuccess, setSaveSuccess] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [isClearingCache, setIsClearingCache] = useState(false);
    const [cacheMessage, setCacheMessage] = useState<string | null>(null);
    const [cacheClearedSummary, setCacheClearedSummary] = useState<CacheClearResult | null>(null);

    // Only the primary data-source preference is persisted (backend
    // PUT /data/config accepts primary_source|cache_ttl_minutes|enable_cache).
    // No placebo controls: nothing else is offered until a real backend key exists.
    const dirty = savedSource === null || primarySource !== savedSource;

    // Load the persisted primary source so the selector reflects backend truth
    useEffect(() => {
        let cancelled = false;
        dataApi.getConfig()
            .then((cfg) => {
                if (!cancelled && cfg?.primary_source) {
                    setPrimarySource(cfg.primary_source);
                    setSavedSource(cfg.primary_source);
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
            setSavedSource(primarySource);
            setSaveSuccess(true);
            setTimeout(() => setSaveSuccess(false), 3000);
        } catch (err) {
            // Keep the error until the next save — validation text must stay readable
            setSaveError(
                err instanceof Error && err.message
                    ? err.message
                    : 'Could not save the data-source preference. Is the backend running?'
            );
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
            setCacheMessage(
                err instanceof Error && err.message
                    ? err.message
                    : 'Cache purge failed. Is the backend running?'
            );
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
                    Configure the primary market data source and purge cached vendor data.
                </p>
            </div>

            {saveSuccess && (
                <div className="p-4 bg-emerald-950/40 border border-emerald-800/60 rounded-xl flex items-center space-x-3 text-emerald-300 text-sm">
                    <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0" />
                    <span>Data-source preference saved.</span>
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
                {/* Data Sources & Engine Connectivity */}
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

                    {/* Feed descriptions — status pills removed: no health endpoint backs them */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                            <span className="text-xs font-medium text-slate-300">Market Price Feed</span>
                            <p className="text-[11px] text-slate-500 mt-1">Live & historical daily OHLCV prices</p>
                        </div>

                        <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                            <span className="text-xs font-medium text-slate-300">Screener.in Live API</span>
                            <p className="text-[11px] text-slate-500 mt-1">NSE fundamental ratios & quarterly results</p>
                        </div>

                        <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg">
                            <span className="text-xs font-medium text-slate-300">NSE Bhavcopy Microstructure</span>
                            <p className="text-[11px] text-slate-500 mt-1">Delivery %, FII/DII institutional cash flows</p>
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
                        disabled={isSaving || !dirty}
                        className="flex items-center space-x-2 px-6 py-2.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition shadow-lg shadow-blue-600/20 disabled:opacity-50"
                    >
                        {isSaving ? (
                            <RefreshCw className="w-4 h-4 animate-spin" />
                        ) : (
                            <CheckCircle2 className="w-4 h-4" />
                        )}
                        <span>Save Data Source Preference</span>
                    </button>
                </div>
            </form>
        </div>
    );
}
