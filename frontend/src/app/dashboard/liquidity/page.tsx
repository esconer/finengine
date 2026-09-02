/**
 * Liquidity Page - Portfolio liquidity analysis and educational engine
 */

'use client';

import React, { useState, useEffect } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import { analyticsApi } from '@/lib/api';
import { usePortfolioStore } from '@/lib/store';
import {
  Droplets,
  Clock,
  AlertTriangle,
  TrendingDown,
  RefreshCw,
  Download,
  BarChart3,
  Activity,
  HelpCircle,
  X,
  Info
} from 'lucide-react';

interface ExplainerContent {
  title: string;
  what: string;
  howInferred: string;
  whyImportant: string;
  howToInfer: string;
  benchmark?: string;
}

const EXPLAINERS: Record<string, ExplainerContent> = {
  overall_score: {
    title: 'Overall Liquidity Score (0 - 10)',
    what: 'A composite portfolio score measuring how easily active positions can be converted into cash without causing significant market price slippage or impact.',
    howInferred: 'Derived by aggregating individual constituent liquidity scores weighted by trading volume, daily turnover (Volume × Price), and market capitalization across all 14 active holdings.',
    whyImportant: 'High liquidity ensures you can enter, exit, or rebalance positions rapidly during market stress without paying steep liquidity penalties or moving the market against yourself.',
    howToInfer: '8.0 – 10.0 indicates strong institutional liquidity (liquidate within 1-2 days). 6.0 – 8.0 represents adequate liquidity (2-5 days). Below 6.0 indicates potential trading bottlenecks.',
    benchmark: 'Institutional target ≥ 7.5/10 for actively managed retail and multi-cap equity portfolios.'
  },
  days_to_liquidate: {
    title: 'Estimated Portfolio Liquidation Horizon',
    what: 'The projected number of active trading days required to completely liquidate all portfolio holdings under normal market conditions without exceeding 10% of daily volume (Participation Rate ≤ 10%).',
    howInferred: 'Calculated as Position Shares / (0.10 × 30-Day Average Daily Volume) across all constituents, taking the portfolio-weighted execution timeline.',
    whyImportant: 'Forcing a fast liquidation on illiquid positions in a single day creates severe market impact and slippage, eroding portfolio returns.',
    howToInfer: '1-2 days means your portfolio has minimal execution friction. 2-5 days represents standard liquidity. Over 5 days requires phased block execution or algorithmic VWAP/TWAP slicing.',
    benchmark: 'Target: ≤ 2-3 days for complete portfolio unwind.'
  },
  liquidity_risk_level: {
    title: 'Liquidity Risk Classification',
    what: 'The aggregate risk tier (Low, Medium, High) reflecting potential exit friction and market impact exposure.',
    howInferred: 'Mapped directly from the Overall Liquidity Score: Score ≥ 8.0 → Low Risk; 6.0 ≤ Score < 8.0 → Medium Risk; Score < 6.0 → High Risk.',
    whyImportant: 'Provides immediate risk governance for fund managers, ensuring the portfolio adheres to regulatory redemption and cash-buffer requirements.',
    howToInfer: 'Low: Safe for fast redemptions. Medium: Monitor mid-cap allocations during market drawdowns. High: High risk of lock-in or heavy discount sales during panics.',
    benchmark: 'Standard target: Low to Medium Risk.'
  },
  high_liquidity_positions: {
    title: 'High Liquidity Constituents Count & Ratio',
    what: 'The number and percentage of portfolio positions that achieve a High liquidity rating (Score ≥ 8.0/10).',
    howInferred: 'Count of positions where Category = "High" divided by total active holdings (N = 14).',
    whyImportant: 'Shows the concentration of cash-convertible assets that can be tapped immediately to meet unexpected capital calls or redeploy into new opportunities.',
    howToInfer: 'A higher percentage (> 50%) provides strong structural stability and ensures that large redemptions can be fulfilled by trimming large-caps without touching small-cap core holdings.',
    benchmark: 'Prudent institutional baseline: ≥ 40% – 60%.'
  },
  position_levels: {
    title: 'Position Liquidity Score Ranking (0 - 10)',
    what: 'Relative liquidity ranking for each active stock and ETF holding in your portfolio.',
    howInferred: 'Calculated from 30-day average daily turnover (₹ Value Traded/day), average daily volume, and market capitalization from NSE/BSE exchange feeds.',
    whyImportant: 'Identifies which specific holdings are liquid anchors (like NTPC, CIPLA, MOTHERSON) and which are illiquid small-caps (like ARROWGREEN or JKIL) that require careful order sizing.',
    howToInfer: 'Green (8-10): Ultra liquid; execute at market. Yellow (6-8): Mid-tier; use limit orders. Red (<6): Illiquid; slice orders across multiple sessions.',
    benchmark: 'Individual holding liquidity target ≥ 6.0/10.'
  },
  distribution: {
    title: 'Portfolio Liquidity Distribution',
    what: 'Breakdown of active positions across three primary liquidity tiers: High (8-10), Medium (6-8), and Low (0-6).',
    howInferred: 'Classifies the 14 constituents by their individual liquidity score and visualizes the allocation across the three tiers.',
    whyImportant: 'Prevents the illusion of safety where a portfolio has high overall value but is heavily concentrated in a long tail of illiquid small-caps.',
    howToInfer: 'Healthy portfolios have a pyramidal or top-heavy distribution with the majority of positions in High and Medium tiers.',
    benchmark: 'Target: < 20% of portfolio positions in the Low Liquidity tier.'
  },
  ticker_col: {
    title: 'Ticker Symbol',
    what: 'Official NSE/BSE security identifier with exchange suffix (e.g. .NS for National Stock Exchange).',
    howInferred: 'Extracted directly from your portfolio holdings database.',
    whyImportant: 'Uniquely identifies the asset for execution and market microstructure analysis.',
    howToInfer: 'Verify against exchange listings to ensure accurate market data matching.'
  },
  score_col: {
    title: 'Constituent Liquidity Score',
    what: 'Individual asset score from 0.0 to 10.0 reflecting its relative liquidity in the Indian equity and ETF marketplace.',
    howInferred: 'Derived from 30-day average volume, price, and daily rupee turnover.',
    whyImportant: 'Tells you how fast you can trade this specific stock without paying excessive bid-ask spreads.',
    howToInfer: 'Scores above 8.0 mean you can trade large quantities instantly. Scores below 6.0 suggest phased execution.'
  },
  category_col: {
    title: 'Liquidity Category',
    what: 'Categorical badge (High, Medium, Low) summarizing the asset execution tier.',
    howInferred: 'High (Score ≥ 8.0), Medium (6.0 ≤ Score < 8.0), Low (Score < 6.0).',
    whyImportant: 'Provides an instant visual indicator of execution constraints in trading dashboards.',
    howToInfer: 'Use High-liquidity assets for tactical rebalancing; handle Low-liquidity assets with patient limit orders.'
  },
  volume_col: {
    title: '30-Day Average Traded Volume',
    what: 'Mean daily number of shares or ETF units traded across NSE and BSE over the past 30 trading sessions.',
    howInferred: 'Calculated as Sum(Daily Volume) / 30 from clean exchange OHLCV data.',
    whyImportant: 'Direct measure of market depth and continuous order-flow matching.',
    howToInfer: 'Format uses Indian numbering notation (Cr = Crores / 10M, L = Lakhs / 100K). Higher volume means tighter spreads and deeper order books.'
  },
  market_cap_col: {
    title: 'Market Capitalization / Fund AUM',
    what: 'Total equity market valuation (Total Shares × Current Market Price) for companies, or total Assets Under Management (AUM) for Exchange-Traded Funds (ETFs).',
    howInferred: 'Retrieved dynamically from live exchange market feeds (yfinance / NSE FastInfo) and localized into Indian Rupee Crores (₹ Cr).',
    whyImportant: 'Large-cap companies (Market Cap > ₹50,000 Cr) and large ETFs typically enjoy deep institutional backing, market maker support, and low slippage.',
    howToInfer: '₹20,000+ Cr = Large Cap / Major ETF; ₹5,000 - ₹20,000 Cr = Mid Cap; < ₹5,000 Cr = Small Cap / Micro Cap.'
  },
  spread_col: {
    title: 'Estimated Bid-Ask Spread',
    what: 'The percentage difference between the highest price a buyer is willing to pay (Bid) and the lowest price a seller is willing to accept (Ask).',
    howInferred: 'Estimated empirically from daily turnover, volume depth, and volatility: Spread ≈ max(0.02%, Base - log(Turnover)).',
    whyImportant: 'The spread represents the immediate round-trip transaction cost incurred just to enter and exit a position.',
    howToInfer: '0.02% – 0.08% is ultra-tight (large caps & index ETFs). 0.10% – 0.30% is standard mid-cap spread. Over 0.35% means trading friction is significant.'
  },
  liquidation_time_col: {
    title: 'Position Liquidation Time',
    what: 'Projected timeframe to execute your entire held quantity without exceeding 10% of the daily market volume.',
    howInferred: 'Computed as Quantity / (0.10 × 30-Day Average Daily Volume).',
    whyImportant: 'Ensures order execution does not overwhelm the market and trigger price collapse.',
    howToInfer: '1-2 days = trivial execution. 2-5 days = standard execution. 5-10 days = requires careful algorithmic execution.'
  }
};

function HelpExplainerModal({ itemKey, onClose }: { itemKey: string; onClose: () => void }) {
  const info = EXPLAINERS[itemKey];
  if (!info) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-xl w-full p-6 shadow-2xl relative text-slate-100 max-h-[90vh] overflow-y-auto">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
          aria-label="Close explainer"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center space-x-3 mb-4">
          <div className="p-2 bg-cyan-500/20 text-cyan-400 rounded-lg">
            <Info className="w-6 h-6" />
          </div>
          <h3 className="text-xl font-bold text-white">{info.title}</h3>
        </div>

        <div className="space-y-4 text-sm leading-relaxed">
          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-cyan-400 uppercase tracking-wider mb-1">What This Number Means</h4>
            <p className="text-slate-200">{info.what}</p>
          </div>

          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-cyan-400 uppercase tracking-wider mb-1">How It Is Inferred</h4>
            <p className="text-slate-300">{info.howInferred}</p>
          </div>

          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-cyan-400 uppercase tracking-wider mb-1">Why It Is Important</h4>
            <p className="text-slate-300">{info.whyImportant}</p>
          </div>

          <div className="bg-slate-800/80 p-3.5 rounded-lg border border-slate-700/60">
            <h4 className="text-xs font-semibold text-cyan-400 uppercase tracking-wider mb-1">How To Interpret This Value</h4>
            <p className="text-slate-300">{info.howToInfer}</p>
          </div>

          {info.benchmark && (
            <div className="bg-emerald-950/40 p-3 rounded-lg border border-emerald-800/50 text-emerald-200 text-xs font-medium">
              💡 <span className="font-semibold text-emerald-300">Target Benchmark:</span> {info.benchmark}
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg font-medium text-sm transition-colors"
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
      className="inline-flex items-center justify-center w-4 h-4 ml-1.5 text-slate-400 hover:text-cyan-400 rounded-full hover:bg-slate-800/60 transition-colors"
      title={label || 'Click to understand this metric'}
      aria-label={label || 'Explainer info'}
    >
      <HelpCircle className="w-3.5 h-3.5" />
    </button>
  );
}

interface LiquidityData {
  overall_score: number;
  liquidation_time_days: string;
  risk_level: string;
  by_position: Record<string, {
    score: number;
    category: string;
    avg_volume?: number;
    avg_turnover?: number;
    market_cap?: number;
    spread?: number;
    liquidation_days: string;
  }>;
  volume_stats: {
    avg_volume: number;
    total_portfolio_volume: number;
    high_volume_pct: number;
    medium_volume_pct: number;
    low_volume_pct: number;
  };
  methodology?: string;
}

interface PositionLiquidity {
  ticker: string;
  score: number;
  category: 'High' | 'Medium' | 'Low';
  liquidation_days: string;
  volume_30d: number;
  avg_turnover: number;
  market_cap: number;
  bid_ask_spread: number;
}

export default function LiquidityPage() {
  const [liquidityData, setLiquidityData] = useState<LiquidityData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [positionData, setPositionData] = useState<PositionLiquidity[]>([]);
  const [activeExplainer, setActiveExplainer] = useState<string | null>(null);

  const { positions, fetchPortfolio } = usePortfolioStore();

  const fetchLiquidityData = async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await analyticsApi.getLiquidityMetrics();
      setLiquidityData(data);

      // Convert by_position data for table
      const positionsList: PositionLiquidity[] = [];

      if (data.by_position && Object.keys(data.by_position).length > 0) {
        Object.entries(data.by_position).forEach(([ticker, posData]: [string, any]) => {
          const posObj = positions.find(p => p.ticker === ticker);
          
          // Use real market cap from backend or fallback to dynamic turnover capitalization
          const realMarketCap = posData.market_cap && posData.market_cap > 0
            ? posData.market_cap
            : (posData.avg_turnover ? posData.avg_turnover * 250 : 5000000000);

          positionsList.push({
            ticker,
            score: posData.score || 0,
            category: posData.category || (posData.score >= 8 ? 'High' : posData.score >= 6 ? 'Medium' : 'Low'),
            liquidation_days: posData.liquidation_days || (posData.score >= 8 ? '1-2' : posData.score >= 6 ? '2-3' : '5-10'),
            volume_30d: posData.avg_volume || 0,
            avg_turnover: posData.avg_turnover || (posData.avg_volume && posObj?.last_price ? posData.avg_volume * posObj.last_price : 0),
            market_cap: realMarketCap,
            bid_ask_spread: posData.spread && posData.spread > 0 ? posData.spread : (posData.score >= 8 ? 0.0004 : posData.score >= 6 ? 0.0012 : 0.0035),
          });
        });
      }

      setPositionData(positionsList.sort((a, b) => b.score - a.score));
    } catch (err) {
      console.error('Failed to fetch liquidity data:', err);
      setError(err instanceof Error ? err.message : 'Failed to load liquidity data');

      setLiquidityData({
        overall_score: 7.8,
        liquidation_time_days: '1-2',
        risk_level: 'Low',
        by_position: {},
        volume_stats: {
          avg_volume: 5000000,
          total_portfolio_volume: 25000000,
          high_volume_pct: 60,
          medium_volume_pct: 30,
          low_volume_pct: 10
        }
      });

      setPositionData([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
    fetchLiquidityData();
  }, []);

  useEffect(() => {
    if (positions.length > 0) {
      fetchLiquidityData();
    }
  }, [positions]);

  const handleRefresh = () => {
    fetchLiquidityData();
  };

  // Format metrics for display
  const formatScore = (value: number | undefined | null, decimals = 1) => {
    if (value === undefined || value === null || isNaN(value)) {
      return 'N/A';
    }
    return `${value.toFixed(decimals)}/10`;
  };

  const formatCurrency = (value: number | undefined | null) => {
    if (value === undefined || value === null || isNaN(value)) {
      return '₹0';
    }
    if (value >= 10000000000000) return `₹${(value / 1000000000000).toFixed(2)} L Cr`;
    if (value >= 10000000) return `₹${(value / 10000000).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`;
    if (value >= 100000) return `₹${(value / 100000).toLocaleString('en-IN', { maximumFractionDigits: 2 })} L`;
    return `₹${value.toLocaleString('en-IN')}`;
  };

  const formatVolume = (value: number | undefined | null) => {
    if (value === undefined || value === null || isNaN(value)) {
      return '0';
    }
    if (value >= 10000000) return `${(value / 10000000).toFixed(2)} Cr`;
    if (value >= 100000) return `${(value / 100000).toFixed(2)} L`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return value.toLocaleString('en-IN');
  };

  const formatPercentage = (value: number | undefined | null, decimals = 2) => {
    if (value === undefined || value === null || isNaN(value)) {
      return '0.00%';
    }
    const scaled = Math.abs(value) <= 1.0 && value !== 0 ? value * 100 : value;
    return `${scaled.toFixed(decimals)}%`;
  };

  const getScoreColor = (score: number): string => {
    if (score >= 8) return 'text-emerald-500 dark:text-emerald-400 font-bold';
    if (score >= 6) return 'text-amber-500 dark:text-amber-400 font-bold';
    return 'text-rose-500 dark:text-rose-400 font-bold';
  };

  const getScoreBgColor = (score: number): string => {
    if (score >= 8) return 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800/40';
    if (score >= 6) return 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800/40';
    return 'bg-rose-50 dark:bg-rose-950/20 border-rose-200 dark:border-rose-800/40';
  };

  // CSV Export
  const handleExportCSV = () => {
    if (!positionData.length) return;
    const headers = ['Ticker', 'Liquidity Score', 'Category', 'Avg Volume (30D)', 'Market Cap (INR)', 'Bid-Ask Spread (%)', 'Liquidation Time (Days)'];
    const rows = positionData.map(p => [
      p.ticker,
      p.score.toFixed(1),
      p.category,
      p.volume_30d,
      p.market_cap,
      (p.bid_ask_spread * 100).toFixed(2) + '%',
      p.liquidation_days
    ]);
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `portfolio_liquidity_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const overallScore = liquidityData?.overall_score || 0;
  const highVolumeCount = positionData.filter(p => p.score >= 8).length;
  const mediumVolumeCount = positionData.filter(p => p.score >= 6 && p.score < 8).length;
  const lowVolumeCount = positionData.filter(p => p.score < 6).length;

  // Position liquidity table columns with ? explainers
  const positionColumns: ColumnDef<PositionLiquidity>[] = [
    {
      header: () => (
        <div className="flex items-center">
          <span>Ticker</span>
          <HelpBtn onClick={() => setActiveExplainer('ticker_col')} />
        </div>
      ),
      accessorKey: 'ticker',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="font-semibold text-gray-900 dark:text-white">
            {data.ticker}
          </div>
        );
      },
    },
    {
      header: () => (
        <div className="flex items-center">
          <span>Liquidity Score</span>
          <HelpBtn onClick={() => setActiveExplainer('score_col')} />
        </div>
      ),
      accessorKey: 'score',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className={`${getScoreColor(data.score)}`}>
            {formatScore(data.score)}
          </div>
        );
      },
    },
    {
      header: () => (
        <div className="flex items-center">
          <span>Category</span>
          <HelpBtn onClick={() => setActiveExplainer('category_col')} />
        </div>
      ),
      accessorKey: 'category',
      cell: ({ row }: any) => {
        const data = row.original || row;
        const colorClass = data.category === 'High' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' :
          data.category === 'Medium' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' :
            'bg-rose-500/20 text-rose-300 border border-rose-500/40';
        return (
          <span className={`px-2.5 py-0.5 text-xs rounded-full font-semibold ${colorClass}`}>
            {data.category}
          </span>
        );
      },
    },
    {
      header: () => (
        <div className="flex items-center">
          <span>Avg Volume (30D)</span>
          <HelpBtn onClick={() => setActiveExplainer('volume_col')} />
        </div>
      ),
      accessorKey: 'volume_30d',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-900 dark:text-white font-mono">
            {formatVolume(data.volume_30d)}
          </div>
        );
      },
    },
    {
      header: () => (
        <div className="flex items-center">
          <span>Market Cap / AUM</span>
          <HelpBtn onClick={() => setActiveExplainer('market_cap_col')} />
        </div>
      ),
      accessorKey: 'market_cap',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-900 dark:text-white font-mono font-medium">
            {formatCurrency(data.market_cap)}
          </div>
        );
      },
    },
    {
      header: () => (
        <div className="flex items-center">
          <span>Bid-Ask Spread</span>
          <HelpBtn onClick={() => setActiveExplainer('spread_col')} />
        </div>
      ),
      accessorKey: 'bid_ask_spread',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-gray-900 dark:text-white font-mono">
            {formatPercentage(data.bid_ask_spread, 2)}
          </div>
        );
      },
    },
    {
      header: () => (
        <div className="flex items-center">
          <span>Liquidation Time</span>
          <HelpBtn onClick={() => setActiveExplainer('liquidation_time_col')} />
        </div>
      ),
      accessorKey: 'liquidation_days',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="text-slate-300 font-medium">
            {data.liquidation_days ? `${data.liquidation_days} days` : 'N/A'}
          </div>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      {/* Active Explainer Modal */}
      {activeExplainer && (
        <HelpExplainerModal
          itemKey={activeExplainer}
          onClose={() => setActiveExplainer(null)}
        />
      )}

      {/* Hero Section */}
      <div className="bg-gradient-to-r from-cyan-600 via-sky-600 to-blue-600 rounded-xl p-6 text-white shadow-lg relative overflow-hidden">
        <div className="absolute right-0 top-0 translate-x-8 -translate-y-8 w-64 h-64 bg-white/10 rounded-full blur-3xl pointer-events-none" />
        <div className="flex items-center justify-between relative z-10">
          <div>
            <div className="flex items-center space-x-3 mb-2">
              <h1 className="text-3xl font-bold tracking-tight">Liquidity Analysis</h1>
              <span className="px-3 py-0.5 rounded-full text-xs font-semibold bg-white/20 text-white backdrop-blur-sm">
                NSE/BSE MICROSTRUCTURE
              </span>
            </div>
            <p className="text-cyan-100 max-w-2xl text-sm leading-relaxed">
              Real-time constituent market depth, daily rupee turnover analysis, execution timelines, and trading constraints across all {positions.length} active positions.
            </p>
            <div className="flex flex-wrap items-center mt-4 gap-3">
              <div className="bg-black/20 backdrop-blur-md px-3 py-1.5 rounded-lg text-cyan-100 text-xs font-medium border border-white/10">
                Overall Score: <span className="font-bold text-white ml-1">{formatScore(overallScore)}</span>
              </div>
              <div className="bg-black/20 backdrop-blur-md px-3 py-1.5 rounded-lg text-cyan-100 text-xs font-medium border border-white/10">
                Risk Level: <span className="font-bold text-white ml-1">{liquidityData?.risk_level || (positions.length > 0 ? 'Low' : 'N/A')}</span>
              </div>
              <div className="bg-black/20 backdrop-blur-md px-3 py-1.5 rounded-lg text-cyan-100 text-xs font-medium border border-white/10">
                Est. Liquidation: <span className="font-bold text-white ml-1">{liquidityData?.liquidation_time_days ? `${liquidityData.liquidation_time_days} days` : (positions.length > 0 ? '< 1 day' : 'N/A')}</span>
              </div>
            </div>
          </div>
          <div className="hidden md:flex items-center space-x-3">
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="bg-white/20 hover:bg-white/30 rounded-xl p-2.5 transition-colors border border-white/10 shadow-sm"
              title="Refresh Liquidity Metrics"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <div className="p-3 bg-white/10 backdrop-blur-md rounded-xl border border-white/20 shadow-inner">
              <Droplets className="w-10 h-10 text-cyan-200" />
            </div>
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 mr-2" />
            <h3 className="text-red-800 dark:text-red-300 font-medium">Error Loading Liquidity Data</h3>
          </div>
          <p className="text-red-700 dark:text-red-400 text-sm mt-1">{error}</p>
          <button
            onClick={handleRefresh}
            className="mt-2 px-3 py-1 bg-red-100 dark:bg-red-800 text-red-700 dark:text-red-300 rounded text-sm hover:bg-red-200 dark:hover:bg-red-700 transition-colors"
          >
            Try Again
          </button>
        </div>
      )}

      {/* Metric Cards with ? Buttons */}
      {!loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="relative group">
            <MetricCard
              title="Overall Liquidity Score"
              value={formatScore(overallScore)}
              icon={Droplets}
              loading={loading}
            />
            <div className="absolute top-4 right-4 z-10">
              <HelpBtn onClick={() => setActiveExplainer('overall_score')} />
            </div>
          </div>

          <div className="relative group">
            <MetricCard
              title="Avg. Days to Liquidate"
              value={liquidityData?.liquidation_time_days ? `${liquidityData.liquidation_time_days} days` : (positions.length > 0 ? '< 1 day' : 'N/A')}
              icon={Clock}
              loading={loading}
            />
            <div className="absolute top-4 right-4 z-10">
              <HelpBtn onClick={() => setActiveExplainer('days_to_liquidate')} />
            </div>
          </div>

          <div className="relative group">
            <MetricCard
              title="Liquidity Risk"
              value={liquidityData?.risk_level || (positions.length > 0 ? 'Low' : 'N/A')}
              icon={AlertTriangle}
              loading={loading}
            />
            <div className="absolute top-4 right-4 z-10">
              <HelpBtn onClick={() => setActiveExplainer('liquidity_risk_level')} />
            </div>
          </div>

          <div className="relative group">
            <MetricCard
              title="High Liquidity Positions"
              value={`${highVolumeCount} (${positionData.length > 0 ? formatPercentage(highVolumeCount / positionData.length, 1) : '0.0%'})`}
              icon={TrendingDown}
              loading={loading}
            />
            <div className="absolute top-4 right-4 z-10">
              <HelpBtn onClick={() => setActiveExplainer('high_liquidity_positions')} />
            </div>
          </div>
        </div>
      )}

      {/* Liquidity Breakdown */}
      {!loading && !error && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Position Liquidity Levels */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center space-x-2">
                  <h3 className="text-lg font-semibold text-white">
                    Position Liquidity Levels
                  </h3>
                  <HelpBtn onClick={() => setActiveExplainer('position_levels')} />
                </div>
                <BarChart3 className="w-5 h-5 text-slate-400" />
              </div>
              <div className="space-y-3.5">
                {positionData.slice(0, 8).map((position) => (
                  <div key={position.ticker} className="flex items-center justify-between">
                    <div className="flex items-center space-x-2.5">
                      <span className="text-sm font-medium text-slate-200 w-28 truncate">
                        {position.ticker}
                      </span>
                      <span className={`px-2 py-0.5 text-xs rounded-full font-semibold ${
                        position.category === 'High' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' :
                        position.category === 'Medium' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' :
                        'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                      }`}>
                        {position.category}
                      </span>
                    </div>
                    <div className="flex items-center space-x-3">
                      <div className="w-28 bg-slate-800 rounded-full h-2.5 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            position.category === 'High' ? 'bg-emerald-500' :
                            position.category === 'Medium' ? 'bg-amber-500' : 'bg-rose-500'
                          }`}
                          style={{ width: `${(position.score / 10) * 100}%` }}
                        />
                      </div>
                      <span className={`text-sm font-mono ${getScoreColor(position.score)} w-12 text-right`}>
                        {formatScore(position.score)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Liquidity Distribution */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center space-x-2">
                  <h3 className="text-lg font-semibold text-white">
                    Liquidity Distribution
                  </h3>
                  <HelpBtn onClick={() => setActiveExplainer('distribution')} />
                </div>
                <Activity className="w-5 h-5 text-slate-400" />
              </div>

              <div className="space-y-5 pt-2">
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-slate-300 flex items-center">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 mr-2" />
                      High Liquidity (8.0 - 10.0)
                    </span>
                    <span className="text-emerald-400 font-semibold font-mono">
                      {highVolumeCount} positions ({positionData.length > 0 ? ((highVolumeCount / positionData.length) * 100).toFixed(1) : 0}%)
                    </span>
                  </div>
                  <div className="w-full bg-slate-800 rounded-full h-3 overflow-hidden">
                    <div
                      className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                      style={{ width: `${positionData.length > 0 ? (highVolumeCount / positionData.length) * 100 : 0}%` }}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-slate-300 flex items-center">
                      <span className="w-2.5 h-2.5 rounded-full bg-amber-500 mr-2" />
                      Medium Liquidity (6.0 - 7.9)
                    </span>
                    <span className="text-amber-400 font-semibold font-mono">
                      {mediumVolumeCount} positions ({positionData.length > 0 ? ((mediumVolumeCount / positionData.length) * 100).toFixed(1) : 0}%)
                    </span>
                  </div>
                  <div className="w-full bg-slate-800 rounded-full h-3 overflow-hidden">
                    <div
                      className="h-full bg-amber-500 rounded-full transition-all duration-500"
                      style={{ width: `${positionData.length > 0 ? (mediumVolumeCount / positionData.length) * 100 : 0}%` }}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-slate-300 flex items-center">
                      <span className="w-2.5 h-2.5 rounded-full bg-rose-500 mr-2" />
                      Low Liquidity (0.0 - 5.9)
                    </span>
                    <span className="text-rose-400 font-semibold font-mono">
                      {lowVolumeCount} positions ({positionData.length > 0 ? ((lowVolumeCount / positionData.length) * 100).toFixed(1) : 0}%)
                    </span>
                  </div>
                  <div className="w-full bg-slate-800 rounded-full h-3 overflow-hidden">
                    <div
                      className="h-full bg-rose-500 rounded-full transition-all duration-500"
                      style={{ width: `${positionData.length > 0 ? (lowVolumeCount / positionData.length) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Position-Level Liquidity Analysis Table */}
          {positionData.length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl shadow-sm overflow-hidden">
              <div className="p-5 border-b border-slate-800 flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-bold text-white">
                    Position-Level Liquidity Analysis ({positionData.length})
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Constituent order execution metrics, 30-day average daily volumes, and real-time market capitalizations.
                  </p>
                </div>
                <button
                  onClick={handleExportCSV}
                  className="flex items-center px-3.5 py-1.5 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg border border-slate-700 transition-colors shadow-sm"
                >
                  <Download className="w-3.5 h-3.5 mr-1.5 text-cyan-400" />
                  Export CSV
                </button>
              </div>

              <DataTable
                data={positionData}
                columns={positionColumns}
                loading={loading}
                searchablePlaceholder="Search positions by ticker..."
                exportable={false}
              />
            </div>
          )}

          {/* Liquidity Risk Assessment & Insights */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
            <h3 className="text-lg font-bold text-white mb-4">
              Liquidity Risk Assessment
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-800/40">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="font-semibold text-emerald-300 text-sm">
                    {overallScore >= 8 ? 'Robust Market Depth' : overallScore >= 6 ? 'Adequate Liquidity Buffer' : 'Limited Liquidity'}
                  </h4>
                  <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300">
                    LOW RISK
                  </span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  {highVolumeCount} of {positionData.length} holdings are high-liquidity large-caps/ETFs capable of rapid cash conversion with minimal price impact.
                </p>
              </div>

              <div className="p-4 rounded-xl bg-amber-950/20 border border-amber-800/40">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="font-semibold text-amber-300 text-sm">Monitor Mid-Cap Volatility</h4>
                  <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300">
                    MEDIUM RISK
                  </span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  {mediumVolumeCount} position{mediumVolumeCount !== 1 ? 's' : ''} require standard limit orders or multi-session execution during turbulent volatility regimes.
                </p>
              </div>

              <div className="p-4 rounded-xl bg-rose-950/20 border border-rose-800/40">
                <div className="flex items-center justify-between mb-1.5">
                  <h4 className="font-semibold text-rose-300 text-sm">Execution Discipline</h4>
                  <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-300">
                    ACTION ADVISORY
                  </span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  {lowVolumeCount > 0
                    ? `${lowVolumeCount} small-cap position(s) should be liquidated using participation limits (≤ 10% daily volume) to prevent severe slippage.`
                    : 'All active holdings maintain healthy trading depth; zero severe liquidity traps detected.'}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}