'use client';

import React, { useState, useEffect } from 'react';
import { RefreshCw, Zap, AlertCircle } from 'lucide-react';
import api from '@/lib/api';

// Ticket 08 (V3-15): the India page is a composite of three heterogeneous
// components.  Local types only — `frontend/src/types/index.ts` is owned by
// another workstream, so these shapes are declared here.
type ComponentStatus = 'available' | 'partial' | 'unavailable' | null | undefined;

interface FlowRow {
    date: string;
    fii_net_crores: number | null;
    dii_net_crores: number | null;
    total_net_crores: number | null;
    available_categories?: string[];
}

interface FlowPayload {
    flows?: FlowRow[];
    data_status?: ComponentStatus;
    as_of?: string | null;
    available_categories?: string[];
    missing_categories?: string[];
    incomplete_dates?: string[];
    lookback_days?: number;
}

interface DeliveryAnomaly {
    symbol: string;
    current_delivery_pct: number;
    avg_20d_delivery_pct: number;
    z_score: number;
    is_anomaly: boolean;
    signal: string;
}

interface DeliveryPayload {
    anomalies?: DeliveryAnomaly[];
    data_status?: ComponentStatus;
    as_of?: string | null;
    requested_symbols?: string[];
    covered_symbols?: string[];
    missing_symbols?: string[];
    lookback_days?: number;
    sigma_threshold?: number;
}

interface LiquidityRow {
    ticker: string;
    position_value: number | null;
    adv_30d_rupees: number | null;
    days_to_liquidate_10pct_adv: number | null;
    days_to_liquidate_20pct_adv: number | null;
    liquidity_tier: string;
    data_status?: ComponentStatus;
}

interface LiquidityPayload {
    positions?: LiquidityRow[];
    data_status?: ComponentStatus;
    latest_observation_date?: string | null;
    adv_lookback_sessions?: number;
    portfolio_value?: number | null;
    currency?: string;
}

const MISSING = '\u2014'; // em dash: an absent measurement is never a zero

/**
 * Freshness comes from the stored records only.  A client fetch timestamp is
 * not an observation date, so the page never renders one as "As of".
 */
function asOfLabel(label: string, value?: string | null) {
    if (value) {
        return `${label} as of ${value}`;
    }
    return `${label}: the stored records do not publish an observation date`;
}

export default function IndiaFlowsPage() {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [flows, setFlows] = useState<FlowRow[]>([]);
    const [anomalies, setAnomalies] = useState<DeliveryAnomaly[]>([]);
    const [liquidity, setLiquidity] = useState<LiquidityPayload | null>(null);
    const [flowStatus, setFlowStatus] = useState<ComponentStatus>(null);
    const [flowMeta, setFlowMeta] = useState<FlowPayload>({});
    const [deliveryStatus, setDeliveryStatus] = useState<ComponentStatus>(null);
    const [deliveryMeta, setDeliveryMeta] = useState<DeliveryPayload>({});
    const [liquidityStatus, setLiquidityStatus] = useState<ComponentStatus>(null);
    // Server-declared observation dates only.  `null` means "the stored records
    // do not provide one" and is rendered as such.
    const [flowAsOf, setFlowAsOf] = useState<string | null>(null);
    const [deliveryAsOf, setDeliveryAsOf] = useState<string | null>(null);
    const [liquidityAsOf, setLiquidityAsOf] = useState<string | null>(null);

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
            const flowPayload: FlowPayload = flowRes.data ?? {};
            const deliveryPayload: DeliveryPayload = anomalyRes.data ?? {};
            const liquidityPayload: LiquidityPayload = liqRes.data ?? {};

            setFlows(flowPayload.flows || []);
            setFlowStatus(flowPayload.data_status ?? null);
            setFlowMeta(flowPayload);
            setFlowAsOf(flowPayload.as_of ?? null);
            setAnomalies(deliveryPayload.anomalies || []);
            setDeliveryStatus(deliveryPayload.data_status ?? null);
            setDeliveryMeta(deliveryPayload);
            setDeliveryAsOf(deliveryPayload.as_of ?? null);
            setLiquidity(liquidityPayload);
            setLiquidityStatus(liquidityPayload.data_status ?? null);
            setLiquidityAsOf(liquidityPayload.latest_observation_date ?? null);
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

    const missingCategories = flowMeta.missing_categories || [];
    const incompleteDates = flowMeta.incomplete_dates || [];
    const deliveryMissingSymbols = deliveryMeta.missing_symbols || [];
    const deliveryRequested = deliveryMeta.requested_symbols?.length ?? 0;
    const liquidityRows = liquidity?.positions || [];
    // "No anomalies" is a success claim: legal only when the component measured
    // the whole requested universe and the result set is genuinely empty.
    const deliveryComplete = deliveryStatus === 'available' && deliveryMissingSymbols.length === 0;
    const canClaimNoAnomalies = deliveryComplete && anomalies.length === 0;
    // Same rule for flows: an empty table is not evidence of zero net flow.
    const canClaimNoFlows =
        flowStatus === 'available' && missingCategories.length === 0 && flows.length === 0;

    const flowAsOfText = asOfLabel('FII/DII flows', flowAsOf);
    const deliveryAsOfText = asOfLabel('Delivery anomalies', deliveryAsOf);
    const liquidityAsOfText = asOfLabel('Liquidity', liquidityAsOf);

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
                        <Zap className="w-6 h-6 text-amber-500" />
                        India Market Microstructure &amp; Flows
                    </h1>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                        NSE delivery anomalies, market-wide FII/DII institutional net flows, and
                        participation ADV limits. Each card is dated from its own stored records.
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

            {/* FII/DII Institutional Net Flows — market-wide, not per holding */}
            {!loading && !error && (
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 shadow-sm">
                    <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
                        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                            FII/DII Institutional Net Flows (30D)
                        </h3>
                        <span className="text-xs text-gray-400 dark:text-gray-500" data-testid="flow-as-of">
                            {flowAsOfText}
                        </span>
                    </div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                        Market-wide NSE aggregates. These are not measured per holding, so no holding
                        coverage or weight is implied for this card.
                    </p>
                    {flowStatus === 'unavailable' || flowStatus == null ? (
                        <div className="py-8 text-center text-gray-500" data-testid="flows-unavailable">
                            Institutional flow data is unavailable; no zero-flow result is being shown.
                        </div>
                    ) : (
                        <>
                            {flowStatus === 'partial' && (
                                <p
                                    className="mb-3 text-xs text-amber-600 dark:text-amber-400"
                                    data-testid="flows-partial"
                                >
                                    Institutional flow coverage is partial; measured sessions are shown
                                    below and missing FII/DII legs are not treated as zero.
                                </p>
                            )}
                            {flows.length === 0 ? (
                                <div className="py-8 text-center text-gray-500" data-testid="flows-empty">
                                    {canClaimNoFlows
                                        ? 'No institutional flow records are stored for the last 30 sessions.'
                                        : 'No institutional flow records are available; no zero-flow result is being shown.'}
                                </div>
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
                                                    <td className={`px-4 py-3 font-mono ${f.fii_net_crores == null ? 'text-gray-400' : f.fii_net_crores >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                                                        {f.fii_net_crores ?? MISSING}
                                                    </td>
                                                    <td className={`px-4 py-3 font-mono ${f.dii_net_crores == null ? 'text-gray-400' : f.dii_net_crores >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                                                        {f.dii_net_crores ?? MISSING}
                                                    </td>
                                                    <td className="px-4 py-3 font-mono font-semibold">
                                                        {f.total_net_crores ?? MISSING}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </>
                    )}
                    {missingCategories.length > 0 && (
                        <p className="mt-3 text-xs text-amber-600 dark:text-amber-400" data-testid="flows-missing-categories">
                            Missing categories: {missingCategories.join(', ')}. Their cells stay blank
                            ({MISSING}); a missing leg is never read as a zero flow.
                        </p>
                    )}
                    {incompleteDates.length > 0 && (
                        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                            Sessions without both FII and DII: {incompleteDates.join(', ')}.
                        </p>
                    )}
                </div>
            )}

            {/* Delivery Anomalies — symbol-scoped over the requested roster */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 shadow-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                        Delivery % Spikes &amp; Institutional Accumulation Alerts
                    </h3>
                    <span className="text-xs text-gray-400 dark:text-gray-500" data-testid="delivery-as-of">
                        {deliveryAsOfText}
                    </span>
                </div>
                {loading ? (
                    <div className="py-8 text-center text-gray-500">Loading delivery anomalies…</div>
                ) : !error && (deliveryStatus === 'unavailable' || deliveryStatus == null) ? (
                    <div className="py-8 text-center text-gray-500" data-testid="delivery-unavailable">
                        Delivery data is unavailable; no anomaly result is being shown.
                    </div>
                ) : !error && anomalies.length === 0 && !canClaimNoAnomalies ? (
                    <div className="py-8 text-center text-amber-600 dark:text-amber-400" data-testid="delivery-partial">
                        Delivery coverage is incomplete
                        {deliveryRequested > 0
                            ? ` (${deliveryRequested - deliveryMissingSymbols.length}/${deliveryRequested} requested symbols have delivery history)`
                            : ''}
                        ; the absence of a spike is not a measured result.
                    </div>
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
                ) : canClaimNoAnomalies ? (
                    <div className="py-8 text-center text-gray-500" data-testid="delivery-none">
                        No &gt;2σ delivery spikes detected across the {deliveryRequested} requested
                        symbols.
                    </div>
                ) : null}
                {deliveryMissingSymbols.length > 0 && (
                    <p className="mt-3 text-xs text-amber-600 dark:text-amber-400" data-testid="delivery-missing-symbols">
                        No delivery history for: {deliveryMissingSymbols.join(', ')}. These symbols are
                        excluded from the spike result rather than counted as normal.
                    </p>
                )}
            </div>

            {/* ADV Liquidity Limits — the only component with holding coverage */}
            {!loading && !error && (
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 shadow-sm">
                    <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
                        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                            Participation-Based Liquidity &amp; Days-to-Liquidate
                        </h3>
                        <span className="text-xs text-gray-400 dark:text-gray-500" data-testid="liquidity-as-of">
                            {liquidityAsOfText}
                        </span>
                    </div>
                    {liquidityStatus === 'unavailable' || liquidityStatus == null ? (
                        <div className="py-8 text-center text-gray-500" data-testid="liquidity-unavailable">
                            Liquidity data is unavailable for the current portfolio.
                        </div>
                    ) : liquidityRows.length === 0 ? (
                        <div className="py-8 text-center text-gray-500">
                            No portfolio positions are available for liquidity measurement.
                        </div>
                    ) : (
                        <>
                            {liquidityStatus === 'partial' && (
                                <p className="mb-3 text-xs text-amber-600 dark:text-amber-400" data-testid="liquidity-partial">
                                    Partial coverage: rows below are measured per holding and are badged
                                    individually where ADV or Amihud history is missing.
                                </p>
                            )}
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
                                        {liquidityRows.map((p, idx) => {
                                            const formatInr = (val: number | null | undefined) => {
                                                if (val == null || !Number.isFinite(val)) return MISSING;
                                                if (val === 0) return '₹0';
                                                if (val >= 10000000) return `₹${(val / 10000000).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Cr`;
                                                if (val >= 100000) return `₹${(val / 100000).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} L`;
                                                return `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
                                            };
                                            // Sub-0.1 day liquidation windows are real but round to "0d";
                                            // only a zero market value is a true 0-day position.
                                            const formatDays = (days: number | null | undefined, marketValue: number | null, adv: number | null) => {
                                                if (days == null || !Number.isFinite(days)) return MISSING;
                                                const d = days;
                                                if (d > 0 && d < 0.1) return '<0.1d';
                                                if (d === 0 && (marketValue ?? 0) > 0 && (adv ?? 0) > 0) return '<0.1d';
                                                return `${d}d`;
                                            };
                                            // Each row is badged by its own measurement status; a
                                            // missing ADV series is not a zero-day liquidation.
                                            const rowStatus = p.data_status ?? null;
                                            const rowMeasured = rowStatus === 'available';
                                            const tierClasses = !rowMeasured
                                                ? 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                                                : p.liquidity_tier === 'HIGHLY_LIQUID'
                                                    ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300'
                                                    : (p.liquidity_tier === 'MODERATE_LIQUIDITY'
                                                        ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300'
                                                        : 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300');
                                            const rowClasses = rowMeasured
                                                ? 'hover:bg-gray-50 dark:hover:bg-gray-700/30'
                                                : 'bg-amber-50/40 dark:bg-amber-900/10';
                                            return (
                                                <tr
                                                    key={idx}
                                                    className={rowClasses}
                                                    data-testid={`liquidity-row-${p.ticker}`}
                                                >
                                                    <td className="px-4 py-3 font-semibold text-gray-900 dark:text-white">
                                                        {p.ticker}
                                                        {rowStatus && rowStatus !== 'available' && (
                                                            <span
                                                                className="ml-2 inline-flex px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                                                                data-testid={`liquidity-row-status-${p.ticker}`}
                                                            >
                                                                {rowStatus}
                                                            </span>
                                                        )}
                                                    </td>
                                                    <td className="px-4 py-3 font-mono">
                                                        {p.position_value == null
                                                            ? MISSING
                                                            : `₹${p.position_value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
                                                    </td>
                                                    <td className="px-4 py-3 font-mono font-medium text-slate-900 dark:text-slate-200">{formatInr(p.adv_30d_rupees)}</td>
                                                    <td className="px-4 py-3 font-medium">{formatDays(p.days_to_liquidate_10pct_adv, p.position_value, p.adv_30d_rupees)}</td>
                                                    <td className="px-4 py-3 font-medium">{formatDays(p.days_to_liquidate_20pct_adv, p.position_value, p.adv_30d_rupees)}</td>
                                                    <td className="px-4 py-3">
                                                        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${tierClasses}`}>
                                                            {rowMeasured ? p.liquidity_tier : `${p.liquidity_tier} (${rowStatus ?? 'unavailable'})`}
                                                        </span>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
