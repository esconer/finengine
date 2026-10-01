/**
 * Realized Risk Page - Historical risk metrics and performance analysis
 */

'use client';

import React, { useState, useEffect } from 'react';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable';
import {
  SectionProvenance,
  sectionCoverage,
} from '@/components/provenance/SectionProvenance';
import type {
  InstrumentRiskPositionRow,
  RealizedRiskPositionRow,
} from '@/lib/api';
import { usePortfolioAnalytics, usePerformanceData } from '@/hooks/useAnalytics';
import { usePortfolioStore, useUIStore } from '@/lib/store';
import {
  describeOwnHistory,
  holdingWindowCaption,
  holdingWindowHeadline,
  isOwnHistoryLimited,
  perTickerDetail,
  positionHistoryTooltip,
  provenanceNote,
  resolveTickerStart,
  resolveWindowStart,
  startQualifier,
  type AnalyticsStartSource,
  type HistoryCoverage,
} from '@/lib/historyFormat';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import {
  TrendingDown,
  TrendingUp,
  Activity,
  AlertTriangle,
  BarChart3,
  Download,
  RefreshCw,
  Shield,
  Target,
} from 'lucide-react';

/**
 * One rendered position row: an instrument-risk (full exchange history) row or
 * a holding-period row, plus the provenance the route derives. Both source
 * shapes are unions of nullable metrics — a withheld ratio is ABSENT, never 0 —
 * so every numeric field here is nullable and each cell must guard before use.
 */
type PositionRiskRow = Partial<
  Omit<RealizedRiskPositionRow, 'ticker'> & Omit<InstrumentRiskPositionRow, 'ticker'>
> & {
  ticker: string;
  weight?: number;
  analytics_start: string | null;
  analytics_start_source: AnalyticsStartSource;
  stored_added_on: string | null;
  is_limited_history: boolean;
  history_warning: string | null;
};

export default function RealizedRiskPage() {
  const [loading, setLoading] = useState(false);
  const [showCoverageDetail, setShowCoverageDetail] = useState(false);

  const { data: analyticsData, loading: analyticsLoading, refresh } = usePortfolioAnalytics();
  const { performanceData, loading: perfLoading } = usePerformanceData(252);
  const { positions } = usePortfolioStore();
  const { updateLastUpdated } = useUIStore();

  const realizedRisk = analyticsData.realizedRisk;

  // Stored import dates, used only to label a window start the route has not
  // annotated: a start that predates `added_on` cannot be the stored date.
  const storedAddedOnByTicker = React.useMemo(() => {
    const out: Record<string, string | null> = {};
    for (const p of positions as any[]) {
      if (p?.ticker) out[p.ticker] = p?.added_on ?? null;
    }
    return out;
  }, [positions]);

  useEffect(() => {
    if (analyticsData.realizedRisk) {
      updateLastUpdated();
    }
  }, [analyticsData.realizedRisk, updateLastUpdated]);

  // Compute live rolling volatility and underwater drawdown series from performance data
  const { drawdownSeries, rollingVolSeries } = React.useMemo(() => {
    if (!performanceData || performanceData.length < 2) {
      return { drawdownSeries: [], rollingVolSeries: [] };
    }
    // A drawdown series is only measurable over a window where EVERY observation
    // has a portfolio value. `p.portfolio_value || 0` substituted a fabricated
    // 0 — which also became `peak`, flattening every later real value to a 0.00%
    // drawdown. An incomplete window is a gap, not a flat line: fall through to
    // the empty state the chart already knows how to render.
    const hasCompleteWindow = performanceData.every(
      (p) => typeof p.portfolio_value === 'number' && Number.isFinite(p.portfolio_value) && p.portfolio_value > 0
    );
    if (!hasCompleteWindow) {
      return { drawdownSeries: [], rollingVolSeries: [] };
    }
    let peak = -Infinity;
    const dd: { date: string; drawdown: number }[] = [];
    const returns: number[] = [];
    const vol: { date: string; volatility: number }[] = [];

    for (let i = 0; i < performanceData.length; i++) {
      const p = performanceData[i];
      const val = p.portfolio_value as number;
      if (val > peak) peak = val;
      const drawdown = peak > 0 ? (val - peak) / peak : 0;
      dd.push({
        date: p.date,
        drawdown: Number((drawdown * 100).toFixed(2)),
      });

      if (i > 0) {
        const prev = performanceData[i - 1].portfolio_value;
        if (prev) {
          returns.push((val - prev) / prev);
        }
      }
      if (returns.length >= 21) {
        const windowRet = returns.slice(-21);
        const mean = windowRet.reduce((a, b) => a + b, 0) / windowRet.length;
        const variance =
          windowRet.reduce((sum, r) => sum + Math.pow(r - mean, 2), 0) /
          Math.max(1, windowRet.length - 1);
        const annVol = Math.sqrt(variance * 252) * 100;
        vol.push({
          date: p.date,
          volatility: Number(annVol.toFixed(2)),
        });
      }
    }
    return { drawdownSeries: dd, rollingVolSeries: vol };
  }, [performanceData]);

  // Generate position risk data for table. Derived, never stored in state: a
  // state round-trip here would re-run on every store snapshot change.
  const positionData = React.useMemo<PositionRiskRow[]>(() => {
    if (!realizedRisk?.positions) return [];
    // DSP-10: per-position risk rows come from the FULL-history
    // instrument_risk block; holding-period data stays in realizedRisk.positions.
    const instrumentPositions = realizedRisk.instrument_risk?.positions || {};
    const source = Object.keys(instrumentPositions).length ? instrumentPositions : realizedRisk.positions;
    // Limited-history status is that position's OWN measured sample: a
    // portfolio-sized count must never make a 20-observation leg look like
    // full history, and the route's honest warning (when present) is kept.
    return Object.entries(source).map(([ticker, data]) => {
      const start = resolveTickerStart(
        realizedRisk.history_coverage?.tickers?.[ticker],
        storedAddedOnByTicker[ticker],
      );
      return {
        ...data,
        ticker,
        weight: realizedRisk.positions?.[ticker]?.weight,
        analytics_start: start.start,
        analytics_start_source: start.source,
        stored_added_on: start.storedAddedOn,
        is_limited_history: isOwnHistoryLimited(data),
        // Only the holding-period row carries a route-published warning; the
        // full-history row publishes none, so it falls back to the derived text.
        history_warning:
          ('history_warning' in data ? data.history_warning : null) ?? describeOwnHistory(data),
      };
    });
  }, [realizedRisk, storedAddedOnByTicker]);

  const handleRefresh = async () => {
    setLoading(true);
    await refresh();
    updateLastUpdated();
    setLoading(false);
  };

  const handleExportCSV = async () => {
    if (positionData.length > 0) {
      // Dynamic import keeps jsPDF/xlsx/file-saver out of this route's initial
      // chunk: a static import put the whole export stack on first paint of a
      // page that only needs it after a click. Same split as Header.tsx:108
      // and dashboard/forecast-risk/page.tsx:515.
      const { CSVExporter } = await import('@/lib/export');
      CSVExporter.exportToCSV(positionData, 'realized_risk_positions');
    }
  };

  // Format metrics for display
  const formatPercentage = (value: number | undefined | null, decimals = 2) => {
    if (value === undefined || value === null) return 'N/A';
    return `${(value * 100).toFixed(decimals)}%`;
  };

  const formatRatio = (value: number | undefined | null, decimals = 2) => {
    if (value === undefined || value === null || Number.isNaN(value)) return 'N/A';
    return value.toFixed(decimals);
  };

  // DataTable columns
  const positionColumns: DataTableColumn<PositionRiskRow>[] = [
    {
      header: 'Ticker',
      accessorKey: 'ticker',
      cell: ({ row }) => {
        const data = row.original;
        return (
          <div className="flex items-center space-x-2">
            <span className="font-semibold text-gray-900 dark:text-white">
              {data.ticker}
            </span>
            {data.is_limited_history && (
              <span
                className="inline-flex items-center text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-700/50"
                title={positionHistoryTooltip(data.ticker, data, {
                  start: data.analytics_start ?? null,
                  source: data.analytics_start_source,
                  storedAddedOn: data.stored_added_on ?? null,
                  buyPriceInferred: null,
                })}
              >
                ⚠️ &lt;30d own history
              </span>
            )}
          </div>
        );
      },
    },
    {
      header: 'Weight',
      accessorKey: 'weight',
      cell: ({ row }) => {
        const data = row.original;
        return (
          <div className="font-mono text-gray-900 dark:text-white">
            {formatPercentage(data.weight)}
          </div>
        );
      },
    },
    {
      header: 'Total Return (Full History)',
      accessorKey: 'total_return',
      cell: ({ row }) => {
        const data = row.original;
        const ret = data.total_return ?? data.annual_return;
        if (ret == null) {
          return <div className="font-mono text-gray-400">N/A</div>;
        }
        const isPositive = ret >= 0;
        return (
          <div className={`font-mono ${isPositive ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
            {isPositive ? '+' : ''}{formatPercentage(ret)}
          </div>
        );
      },
    },
    {
      header: 'Volatility',
      accessorKey: 'annual_volatility',
      cell: ({ row }) => {
        const data = row.original;
        return (
          <div className="font-mono text-gray-900 dark:text-white">
            {formatPercentage(data.annual_volatility)}
          </div>
        );
      },
    },
    {
      header: 'Sharpe Ratio',
      accessorKey: 'sharpe_ratio',
      cell: ({ row }) => {
        const data = row.original;
        if (data.is_limited_history || data.annualized === false) {
          return (
            <div className="font-mono text-xs text-amber-600 dark:text-amber-400" title="Insufficient data (<30d) for annualized Sharpe ratio">
              -- <span className="text-[10px] text-gray-400">(Limited)</span>
            </div>
          );
        }
        // A withheld ratio is ABSENT, not zero, so it may not be banded.
        // `null >= 1` is false and `null >= 0` is TRUE, so an unguarded null
        // falls into the yellow 0-1 band below and reads exactly like a
        // measured sub-1.0 Sharpe — while `undefined` falls to red, so the
        // two spellings of "absent" render as different verdicts. Gate on
        // nullish before the band and render neutral, like the other
        // absent-value cells on this page. The engine withholds this field
        // below 10 return observations with a stated reason, so a null here is
        // a measurement that was refused, never a zero.
        const sharpe = data.sharpe_ratio;
        const measured = typeof sharpe === 'number' && !Number.isNaN(sharpe);
        if (!measured) {
          return (
            <div
              className="font-mono text-gray-400"
              title="Not measured — insufficient return observations to annualize"
            >
              {formatRatio(null)}
            </div>
          );
        }
        return (
          <div className={`font-mono font-medium ${
            sharpe >= 1 ? 'text-green-600 dark:text-green-400' :
            sharpe >= 0 ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-600 dark:text-red-400'
          }`}>
            {formatRatio(sharpe)}
          </div>
        );
      },
    },
    {
      header: 'Max Drawdown',
      accessorKey: 'max_drawdown',
      cell: ({ row }) => {
        const data = row.original;
        return (
          <div className="font-mono text-red-600 dark:text-red-400">
            {formatPercentage(data.max_drawdown)}
          </div>
        );
      },
    },
    {
      header: 'VaR (95%)',
      accessorKey: 'var_95',
      cell: ({ row }) => {
        const data = row.original;
        return (
          <div className="font-mono text-red-600 dark:text-red-400">
            {formatPercentage(data.var_95)}
          </div>
        );
      },
    },
  ];

  const hasData = Boolean(realizedRisk?.portfolio);
  // DSP-10: full-exchange-history portfolio risk (instrument characteristics)
  const fullHistory = realizedRisk?.instrument_risk?.portfolio;

  // Phase 2 disclosure: one summary banner for the holding-intersection window.
  // The envelope types this block, so the cast to the shared vocabulary is no
  // longer load-bearing — `HistoryCoverage` is a subset of what the route sends.
  const coverage: HistoryCoverage | undefined = realizedRisk?.history_coverage;
  const coverageWarnings = realizedRisk?.warnings || [];
  const intersection = coverage?.intersection_start || coverage?.effective_start;
  const coveredDays = coverage?.covered_days ?? coverageWarnings[0]?.data_points;
  const fullDays = coverage?.full_history_days;
  const coverageTickers = coverage?.tickers || {};
  const coverageNames = Object.keys(coverageTickers);
  const coverageTotal = coverageNames.length || positions.length || coverageWarnings.length;
  const heldLonger = coverageNames.length
    ? coverageNames.filter(
        (t: string) =>
          coverageTickers[t]?.effective_start && intersection &&
          coverageTickers[t].effective_start < intersection
      ).length
    : null;
  // The window start's provenance: the route's own source when it published
  // one, otherwise derived from the stored import dates above.
  const windowStart = resolveWindowStart({ coverage, storedAddedOnByTicker });
  const inferredNote = provenanceNote({ coverage, storedAddedOnByTicker });

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-red-600 to-orange-600 rounded-lg p-6 text-white shadow-lg">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Realized Risk</h1>
            <p className="text-red-100">
              Historical risk metrics and portfolio performance analysis
            </p>
            <div className="flex flex-wrap items-center mt-3 gap-4 text-xs font-mono text-red-100">
              <span className="bg-white/10 px-2.5 py-1 rounded">
                Universe: {positions.length} active positions
              </span>
              {realizedRisk?.data_range && (
                <span className="bg-white/10 px-2.5 py-1 rounded">
                  Data Span: {realizedRisk.data_range.start} → {realizedRisk.data_range.end}
                </span>
              )}
            </div>
          </div>
          <div className="hidden md:flex items-center space-x-3">
            <button
              onClick={handleRefresh}
              disabled={loading || analyticsLoading}
              className="bg-white/20 hover:bg-white/30 rounded-lg p-2.5 transition-colors"
              title="Refresh Realized Risk"
            >
              <RefreshCw className={`w-5 h-5 ${loading || analyticsLoading ? 'animate-spin' : ''}`} />
            </button>
            <TrendingDown className="w-12 h-12 text-red-200" />
          </div>
        </div>
      </div>

      {/* Provenance: what these risk numbers were measured on, and when. The
          envelope already publishes it — `latest_observation_date` and
          `universe_coverage.missing_tickers` — so this renders the endpoint's
          own claims and adds no measurement of its own.

          `warnings` is deliberately NOT passed here. This page already renders
          them, behind the coverage banner's expanded-details toggle, and
          `RealizedRiskBanner.test.tsx` holds that collapsed by design: the
          per-position history notes are a bullet wall the reader opts into.
          Duplicating them into an always-open line would undo that decision and
          put the same sentences on screen twice. The warnings are not lost —
          they are one click away, which is where this page already keeps them. */}
      <SectionProvenance
        section="Realized risk"
        asOf={realizedRisk?.latest_observation_date ?? null}
        coverage={sectionCoverage(realizedRisk?.universe_coverage)}
      />

      {/* Holding-intersection coverage banner (Phase 2 disclosure) */}
      {coverageWarnings.length > 0 && (
        <div data-testid="coverage-banner" className="bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700/60 rounded-xl p-4 flex items-start space-x-3 shadow-sm">
          <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm flex-1">
            <h4 className="font-semibold text-amber-900 dark:text-amber-200">
              {holdingWindowHeadline({
                coveredDays,
                start: intersection,
                source: windowStart.source,
                heldLonger,
                total: coverageTotal,
                fullDays,
              })}
            </h4>
            {holdingWindowCaption(intersection, fullDays) && (
              <p data-testid="coverage-caption" className="text-xs font-mono text-amber-700 dark:text-amber-400 mt-1">
                {holdingWindowCaption(intersection, fullDays)}
              </p>
            )}
            {inferredNote && (
              <p data-testid="coverage-provenance" className="text-xs text-amber-800 dark:text-amber-300 mt-1">
                {inferredNote}
              </p>
            )}
            <button
              type="button"
              data-testid="coverage-details-toggle"
              aria-expanded={showCoverageDetail}
              onClick={() => setShowCoverageDetail((v) => !v)}
              className="mt-2 text-xs font-medium text-amber-800 dark:text-amber-300 underline underline-offset-2 hover:text-amber-900 dark:hover:text-amber-200"
            >
              {showCoverageDetail ? 'Hide' : 'Show'} per-ticker detail ({coverageWarnings.length})
            </button>
            {showCoverageDetail && (
              <div data-testid="coverage-details" className="text-amber-800 dark:text-amber-300 mt-2 space-y-1">
                {coverageWarnings.map((w, idx: number) => {
                  // Both the route's message and the derived detail lead with
                  // the ticker, so the bullet is not prefixed a second time.
                  const own = w.message ?? perTickerDetail(
                    w.ticker,
                    coverageTickers[w.ticker],
                    realizedRisk?.positions?.[w.ticker],
                    storedAddedOnByTicker[w.ticker],
                  );
                  return <p key={idx}>• {own}</p>;
                })}
                <p className="text-xs text-amber-700 dark:text-amber-400 mt-2">
                  💡 <em>Tip:</em> For continuous multi-year historical risk metrics and backtesting on Nifty 50, use continuous ETF benchmarks like <code className="font-bold font-mono bg-amber-100 dark:bg-amber-900/50 px-1 py-0.5 rounded">NIFTYBEES.NS</code> or <code className="font-bold font-mono bg-amber-100 dark:bg-amber-900/50 px-1 py-0.5 rounded">SETFNIF50.NS</code> in your portfolio.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Row 1: Instrument Risk — full exchange history (DSP-10) */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center space-x-2">
          <Activity className="w-4 h-4 text-blue-500" />
          <span>
            Instrument Risk — Full Exchange History
            {realizedRisk?.history_coverage?.full_history_days
              ? ` (${realizedRisk.history_coverage.full_history_days} trading days${realizedRisk.history_coverage.full_history_start ? `, since ${realizedRisk.history_coverage.full_history_start}` : ''})`
              : ''}
          </span>
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <MetricCard
            title="Annual Return"
            value={fullHistory?.annual_return != null ? formatPercentage(fullHistory.annual_return) : 'N/A'}
            icon={TrendingUp}
            loading={analyticsLoading}
          />
          <MetricCard
            title="Annual Volatility"
            value={fullHistory?.annual_volatility != null ? formatPercentage(fullHistory.annual_volatility) : 'N/A'}
            icon={Activity}
            loading={analyticsLoading}
          />
          <MetricCard
            title="Sharpe Ratio"
            value={fullHistory?.sharpe_ratio != null ? formatRatio(fullHistory.sharpe_ratio) : 'N/A'}
            icon={Target}
            loading={analyticsLoading}
          />
          <MetricCard
            title="Sortino Ratio"
            value={fullHistory?.sortino_ratio != null ? formatRatio(fullHistory.sortino_ratio) : 'N/A'}
            icon={BarChart3}
            loading={analyticsLoading}
          />
        </div>
      </div>

      {/* Row 2: Tail Risk & Downside Distribution — holding-period realized P&L */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center space-x-2">
          <TrendingDown className="w-4 h-4 text-red-500" />
          <span>
            Holding-Period Realized P&amp;L
            {intersection
              ? ` (since ${intersection}${startQualifier(windowStart.source)})`
              : ''}
          </span>
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Max Drawdown"
          value={hasData && realizedRisk?.portfolio?.max_drawdown != null ? formatPercentage(realizedRisk.portfolio.max_drawdown) : 'N/A'}
          icon={TrendingDown}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Value at Risk (95% Daily)"
          value={hasData && realizedRisk?.portfolio?.var_95 != null ? formatPercentage(realizedRisk.portfolio.var_95) : 'N/A'}
          icon={AlertTriangle}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Conditional VaR (95% Daily)"
          value={hasData && realizedRisk?.portfolio?.cvar_95 != null ? formatPercentage(realizedRisk.portfolio.cvar_95) : 'N/A'}
          icon={Shield}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Hit Ratio (% Positive Days)"
          value={hasData && realizedRisk?.portfolio?.hit_ratio != null ? formatPercentage(realizedRisk.portfolio.hit_ratio) : 'N/A'}
          icon={Activity}
          loading={analyticsLoading}
        />
        </div>
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Rolling 21-Day Volatility (%)
              </h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">Annualized historical realized volatility trend</p>
            </div>
            <Activity className="w-5 h-5 text-blue-500" />
          </div>
          <div className="h-64">
            {rollingVolSeries.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rollingVolSeries}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="%" domain={['auto', 'auto']} />
                  <Tooltip formatter={(value: any) => [`${value}%`, 'Rolling Volatility']} />
                  <Line type="monotone" dataKey="volatility" stroke="#3b82f6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div data-testid="rolling-vol-empty" className="h-full flex items-center justify-center text-gray-400 text-sm">
                {perfLoading ? 'Loading...' : 'No performance history yet'}
              </div>
            )}
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Underwater Drawdown (%)
              </h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">Peak-to-trough portfolio wealth drawdown</p>
            </div>
            <TrendingDown className="w-5 h-5 text-red-500" />
          </div>
          <div className="h-64">
            {drawdownSeries.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={drawdownSeries}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="%" domain={['auto', 0]} />
                  <Tooltip formatter={(value: any) => [`${value}%`, 'Drawdown']} />
                  <Area type="monotone" dataKey="drawdown" stroke="#ef4444" fill="#ef4444" fillOpacity={0.2} strokeWidth={1.5} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div data-testid="drawdown-empty" className="h-full flex items-center justify-center text-gray-400 text-sm">
                {perfLoading ? 'Loading...' : 'No performance history yet'}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Position-Level Risk Analysis */}
      <DataTable
        title="Position-Level Risk Analysis"
        data={positionData}
        columns={positionColumns}
        loading={analyticsLoading}
        searchablePlaceholder="Search positions..."
        exportable={false}
        actions={
          <button
            onClick={handleExportCSV}
            className="flex items-center px-3 py-1.5 text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-md hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
          >
            <Download className="w-3.5 h-3.5 mr-1.5" />
            Export CSV
          </button>
        }
      />

      {/* Risk Analysis Insights */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Key Risk Insights
        </h3>
        <div className="space-y-4">
          {realizedRisk?.portfolio?.max_drawdown && realizedRisk.portfolio.max_drawdown < -0.05 && (
            <div className="flex items-start space-x-3">
              <AlertTriangle className="w-5 h-5 text-yellow-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Drawdown Vulnerability</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Portfolio experienced a peak-to-trough drawdown of {formatPercentage(realizedRisk.portfolio.max_drawdown)}
                  {realizedRisk?.data_range
                    ? ` over ${realizedRisk.data_range.start} → ${realizedRisk.data_range.end}`
                    : ' over the available history window'}.
                </p>
              </div>
            </div>
          )}

          {realizedRisk?.portfolio?.sharpe_ratio && realizedRisk.portfolio.sharpe_ratio > 0.5 && (
            <div className="flex items-start space-x-3">
              <TrendingUp className="w-5 h-5 text-green-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Risk-Adjusted Efficiency</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Sharpe ratio of {formatRatio(realizedRisk.portfolio.sharpe_ratio)} and Sortino ratio of {formatRatio(realizedRisk.portfolio.sortino_ratio)} demonstrate healthy excess return relative to downside volatility.
                </p>
              </div>
            </div>
          )}

          <div className="flex items-start space-x-3">
            <BarChart3 className="w-5 h-5 text-blue-600 mt-0.5" />
            <div>
              <h4 className="font-medium text-gray-900 dark:text-white">Analysis Methodology</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {realizedRisk?.methodology || 'Risk metrics calculated using empirical daily returns, parametric variance-covariance matrices, and historical drawdown series.'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}