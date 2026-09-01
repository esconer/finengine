'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import {
  Filter,
  Sparkles,
  TrendingUp,
  Shield,
  Coins,
  Percent,
  Search,
  Plus,
  Check,
  RefreshCw,
  ExternalLink,
  ChevronRight,
  Sliders,
  AlertCircle,
  BarChart3,
  ArrowUpDown,
  BookOpen,
} from 'lucide-react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
  ColumnDef,
  SortingState,
} from '@tanstack/react-table';

import { screenerApi, portfolioApi } from '@/lib/api';
import { ScreenerStock, ScreenerStrategyMeta, ScreenerStrategyResponse } from '@/types';
import { formatCurrency, formatPercent } from '@/lib/utils';

export default function ScreenerStudioPage() {
  const [strategies, setStrategies] = useState<ScreenerStrategyMeta[]>([]);
  const [activeStrategy, setActiveStrategy] = useState<string>('coffee_can');
  const [screenerData, setScreenerData] = useState<ScreenerStrategyResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Custom filters
  const [showCustomFilters, setShowCustomFilters] = useState(false);
  const [minRoce, setMinRoce] = useState<number>(15);
  const [minRoe, setMinRoe] = useState<number>(15);
  const [maxPe, setMaxPe] = useState<number>(30);
  const [minMcapCr, setMinMcapCr] = useState<number>(5000);
  const [minDivYield, setMinDivYield] = useState<number>(0);

  // Table state
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'market_cap_cr', desc: true },
  ]);
  const [globalFilter, setGlobalFilter] = useState('');
  const [addedStocks, setAddedStocks] = useState<Record<string, boolean>>({});
  const [addingStock, setAddingStock] = useState<string | null>(null);

  const STRATEGY_ICONS: Record<string, React.ReactNode> = {
    coffee_can: <TrendingUp className="w-4 h-4 text-emerald-400" />,
    magic_formula: <Sparkles className="w-4 h-4 text-indigo-400" />,
    debt_free: <Shield className="w-4 h-4 text-cyan-400" />,
    high_dividend: <Coins className="w-4 h-4 text-amber-400" />,
    undervalued_growth: <BarChart3 className="w-4 h-4 text-purple-400" />,
  };

  useEffect(() => {
    const fetchStrategies = async () => {
      try {
        const meta = await screenerApi.getStrategies();
        setStrategies(meta);
      } catch (err) {
        console.error('Error fetching strategies:', err);
      }
    };
    fetchStrategies();
  }, []);

  const runScreen = async (stratKey: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await screenerApi.runScreen(stratKey, 50);
      setScreenerData(result);
    } catch (err: any) {
      console.error('Error running screen:', err);
      setError(err?.response?.data?.detail || err.message || 'Screen execution failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeStrategy !== 'custom') {
      runScreen(activeStrategy);
    }
  }, [activeStrategy]);

  const handleCustomScreenSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setActiveStrategy('custom');
    try {
      const result = await screenerApi.runCustomScreen({
        min_roce: Number(minRoce),
        min_roe: Number(minRoe),
        max_pe: Number(maxPe),
        min_mcap_cr: Number(minMcapCr),
        min_div_yield: Number(minDivYield),
        max_stocks: 50,
      });
      setScreenerData(result);
    } catch (err: any) {
      console.error('Error running custom screen:', err);
      setError(err?.response?.data?.detail || err.message || 'Custom screen failed');
    } finally {
      setLoading(false);
    }
  };

  const handleAddToPortfolio = async (stock: ScreenerStock) => {
    setAddingStock(stock.symbol);
    try {
      await portfolioApi.addPosition({
        ticker: stock.ticker,
        quantity: 1,
        buy_price: stock.price || 0,
        weight: 0,
        region: 'IN',
      });
      setAddedStocks((prev) => ({ ...prev, [stock.symbol]: true }));
      setTimeout(() => {
        setAddedStocks((prev) => ({ ...prev, [stock.symbol]: false }));
      }, 3000);
    } catch (err) {
      console.error('Failed to add to portfolio:', err);
      alert(`Could not add ${stock.symbol} to portfolio.`);
    } finally {
      setAddingStock(null);
    }
  };

  const formatCr = (num?: number | null) => {
    if (num === null || num === undefined) return '-';
    if (num >= 100000) {
      return `₹${(num / 100000).toFixed(2)} L Cr`;
    }
    return `₹${Number(num).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
  };

  // TanStack Table columns
  const columns = useMemo<ColumnDef<ScreenerStock>[]>(
    () => [
      {
        header: '#',
        id: 'index',
        cell: (info) => (
          <span className="text-slate-400 font-mono text-xs">{info.row.index + 1}</span>
        ),
      },
      {
        accessorKey: 'symbol',
        header: 'Stock & Ticker',
        cell: ({ row }) => {
          const data = row.original || row;
          return (
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <Link
                  href={`/dashboard/equity-research?ticker=${encodeURIComponent(data.symbol)}`}
                  className="font-bold text-blue-400 hover:underline flex items-center gap-1"
                >
                  {data.symbol}
                  <ExternalLink className="w-3 h-3 text-slate-500" />
                </Link>
                <span className="px-1.5 py-0.2 text-[10px] bg-slate-800 text-slate-400 rounded">
                  NSE
                </span>
              </div>
              <span className="text-xs text-slate-300 truncate max-w-xs">{data.name}</span>
            </div>
          );
        },
      },
      {
        accessorKey: 'price',
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 text-right w-full justify-end font-mono"
          >
            Price (₹)
            <ArrowUpDown className="w-3 h-3 text-slate-400" />
          </button>
        ),
        cell: ({ row }) => {
          const data = row.original || row;
          return (
            <div className="text-right font-mono font-semibold text-white">
              ₹{data.price?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </div>
          );
        },
      },
      {
        accessorKey: 'market_cap_cr',
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 text-right w-full justify-end font-mono"
          >
            Market Cap
            <ArrowUpDown className="w-3 h-3 text-slate-400" />
          </button>
        ),
        cell: ({ row }) => {
          const data = row.original || row;
          return (
            <div className="text-right font-mono text-slate-200">
              {formatCr(data.market_cap_cr)}
            </div>
          );
        },
      },
      {
        accessorKey: 'pe_ratio',
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 text-right w-full justify-end font-mono"
          >
            P/E
            <ArrowUpDown className="w-3 h-3 text-slate-400" />
          </button>
        ),
        cell: ({ row }) => {
          const data = row.original || row;
          return (
            <div className="text-right font-mono text-slate-300">
              {data.pe_ratio !== null && data.pe_ratio !== undefined ? `${data.pe_ratio.toFixed(1)}x` : '-'}
            </div>
          );
        },
      },
      {
        accessorKey: 'roce_pct',
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 text-right w-full justify-end font-mono"
          >
            ROCE (%)
            <ArrowUpDown className="w-3 h-3 text-slate-400" />
          </button>
        ),
        cell: ({ row }) => {
          const data = row.original || row;
          return (
            <div className="text-right font-mono font-bold text-emerald-400">
              {data.roce_pct !== null && data.roce_pct !== undefined ? `${data.roce_pct.toFixed(1)}%` : '-'}
            </div>
          );
        },
      },
      {
        accessorKey: 'roe_pct',
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 text-right w-full justify-end font-mono"
          >
            ROE (%)
            <ArrowUpDown className="w-3 h-3 text-slate-400" />
          </button>
        ),
        cell: ({ row }) => {
          const data = row.original || row;
          return (
            <div className="text-right font-mono font-bold text-emerald-400">
              {data.roe_pct !== null && data.roe_pct !== undefined ? `${data.roe_pct.toFixed(1)}%` : '-'}
            </div>
          );
        },
      },
      {
        accessorKey: 'dividend_yield_pct',
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 text-right w-full justify-end font-mono"
          >
            Div Yield
            <ArrowUpDown className="w-3 h-3 text-slate-400" />
          </button>
        ),
        cell: ({ row }) => {
          const data = row.original || row;
          return (
            <div className="text-right font-mono text-cyan-300">
              {data.dividend_yield_pct !== null && data.dividend_yield_pct !== undefined
                ? `${data.dividend_yield_pct.toFixed(2)}%`
                : '-'}
            </div>
          );
        },
      },
      {
        id: 'actions',
        header: 'Action',
        cell: ({ row }) => {
          const data = row.original || row;
          const isAdded = addedStocks[data.symbol];
          const isAdding = addingStock === data.symbol;
          return (
            <div className="flex items-center gap-2">
              <Link
                href={`/dashboard/equity-research?ticker=${encodeURIComponent(data.symbol)}`}
                className="p-1.5 bg-slate-800 hover:bg-slate-700 text-blue-300 rounded text-xs transition-colors"
                title="Deep Equity Research"
              >
                <BookOpen className="w-3.5 h-3.5" />
              </Link>
              <button
                onClick={() => handleAddToPortfolio(data)}
                disabled={isAdding || isAdded}
                className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold transition-all ${
                  isAdded
                    ? 'bg-emerald-600 text-white'
                    : 'bg-blue-600/30 hover:bg-blue-600 text-blue-200 hover:text-white border border-blue-500/40'
                }`}
              >
                {isAdded ? (
                  <>
                    <Check className="w-3 h-3" />
                    <span>Added</span>
                  </>
                ) : isAdding ? (
                  <RefreshCw className="w-3 h-3 animate-spin" />
                ) : (
                  <>
                    <Plus className="w-3 h-3" />
                    <span>Portfolio</span>
                  </>
                )}
              </button>
            </div>
          );
        },
      },
    ],
    [addedStocks, addingStock]
  );

  const table = useReactTable({
    data: screenerData?.stocks || [],
    columns,
    state: {
      sorting,
      globalFilter,
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 20,
      },
    },
  });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 lg:p-6 space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/80 backdrop-blur border border-slate-800 p-4 rounded-xl shadow-lg">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-indigo-600/20 text-indigo-400 rounded-lg border border-indigo-500/30">
            <Filter className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
              Screener Studio
              <span className="px-2 py-0.5 text-xs font-medium bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 rounded">
                Institutional Formulae
              </span>
            </h1>
            <p className="text-xs text-slate-400">
              Quantitative screening engine for Indian equities powered by bfinance 10-year audited fundamentals
            </p>
          </div>
        </div>

        <button
          onClick={() => setShowCustomFilters(!showCustomFilters)}
          className="flex items-center gap-2 px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold transition-colors self-start md:self-auto"
        >
          <Sliders className="w-4 h-4 text-indigo-400" />
          <span>{showCustomFilters ? 'Hide Custom Builder' : 'Custom Screener Builder'}</span>
        </button>
      </div>

      {/* Pre-built Strategy Selector Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {strategies.map((strat) => {
          const isActive = activeStrategy === strat.key;
          return (
            <button
              key={strat.key}
              onClick={() => setActiveStrategy(strat.key)}
              className={`p-3.5 rounded-xl border text-left transition-all relative overflow-hidden flex flex-col justify-between ${
                isActive
                  ? 'bg-slate-900 border-blue-500 shadow-md ring-1 ring-blue-500/30'
                  : 'bg-slate-900/60 border-slate-800 hover:bg-slate-900 hover:border-slate-700'
              }`}
            >
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <div className="p-1.5 bg-slate-950 rounded border border-slate-800">
                    {STRATEGY_ICONS[strat.key] || <TrendingUp className="w-4 h-4 text-blue-400" />}
                  </div>
                  {isActive && (
                    <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                  )}
                </div>
                <div className="text-xs font-bold text-white">{strat.name}</div>
                <p className="text-[11px] text-slate-400 line-clamp-2 leading-snug">
                  {strat.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>

      {/* Custom Screener Builder Drawer */}
      {showCustomFilters && (
        <form
          onSubmit={handleCustomScreenSubmit}
          className="bg-slate-900 border border-indigo-500/40 p-5 rounded-xl shadow-xl space-y-4 animate-in fade-in slide-in-from-top-2 duration-200"
        >
          <div className="flex items-center justify-between pb-2 border-b border-slate-800">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Sliders className="w-4 h-4 text-indigo-400" />
              Multi-Parameter Custom Screening Criteria
            </h3>
            <span className="text-xs text-slate-400">Scan entire Indian stock universe</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 text-xs">
            <div>
              <label className="block text-slate-300 font-semibold mb-1">Min ROCE (%)</label>
              <input
                type="number"
                value={minRoce}
                onChange={(e) => setMinRoce(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-700 text-white px-3 py-2 rounded-lg focus:outline-none focus:border-indigo-500 font-mono"
              />
            </div>

            <div>
              <label className="block text-slate-300 font-semibold mb-1">Min ROE (%)</label>
              <input
                type="number"
                value={minRoe}
                onChange={(e) => setMinRoe(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-700 text-white px-3 py-2 rounded-lg focus:outline-none focus:border-indigo-500 font-mono"
              />
            </div>

            <div>
              <label className="block text-slate-300 font-semibold mb-1">Max P/E Multiple</label>
              <input
                type="number"
                value={maxPe}
                onChange={(e) => setMaxPe(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-700 text-white px-3 py-2 rounded-lg focus:outline-none focus:border-indigo-500 font-mono"
              />
            </div>

            <div>
              <label className="block text-slate-300 font-semibold mb-1">Min Market Cap (₹ Cr)</label>
              <input
                type="number"
                value={minMcapCr}
                onChange={(e) => setMinMcapCr(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-700 text-white px-3 py-2 rounded-lg focus:outline-none focus:border-indigo-500 font-mono"
              />
            </div>

            <div>
              <label className="block text-slate-300 font-semibold mb-1">Min Div. Yield (%)</label>
              <input
                type="number"
                value={minDivYield}
                onChange={(e) => setMinDivYield(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-700 text-white px-3 py-2 rounded-lg focus:outline-none focus:border-indigo-500 font-mono"
              />
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              type="submit"
              disabled={loading}
              className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold rounded-lg transition-colors shadow-lg shadow-indigo-600/30"
            >
              {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Filter className="w-4 h-4" />}
              <span>Execute Custom Screen</span>
            </button>
          </div>
        </form>
      )}

      {/* Screen Results Workspace */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg space-y-4">
        {/* Active Strategy Header & Search Filter */}
        <div className="p-4 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-900/90">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              {screenerData?.name || 'Screen Results'}
              {screenerData && (
                <span className="px-2 py-0.5 bg-blue-950 text-blue-300 border border-blue-800 rounded-full text-xs font-mono">
                  {screenerData.count} Stocks Found
                </span>
              )}
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">{screenerData?.description}</p>
          </div>

          <div className="relative">
            <input
              type="text"
              value={globalFilter ?? ''}
              onChange={(e) => setGlobalFilter(e.target.value)}
              placeholder="Search screened stocks..."
              className="bg-slate-950 border border-slate-700 text-slate-100 pl-8 pr-3 py-1.5 rounded-lg text-xs focus:outline-none focus:border-blue-500 w-56"
            />
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
          </div>
        </div>

        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 space-y-3">
            <RefreshCw className="w-7 h-7 text-indigo-400 animate-spin" />
            <p className="text-xs text-slate-400">Scanning Indian equity universe with 10-year audited metrics...</p>
          </div>
        ) : error ? (
          <div className="p-6 text-center text-red-300 text-xs">
            <AlertCircle className="w-6 h-6 text-red-400 mx-auto mb-2" />
            {error}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left text-slate-300">
                <thead className="bg-slate-950 text-slate-400 font-mono uppercase border-b border-slate-800">
                  {table.getHeaderGroups().map((headerGroup) => (
                    <tr key={headerGroup.id}>
                      {headerGroup.headers.map((header) => (
                        <th key={header.id} className="py-3 px-4">
                          {header.isPlaceholder
                            ? null
                            : flexRender(header.column.columnDef.header, header.getContext())}
                        </th>
                      ))}
                    </tr>
                  ))}
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {table.getRowModel().rows.length === 0 ? (
                    <tr>
                      <td colSpan={columns.length} className="text-center py-10 text-slate-500 italic">
                        No stocks matched the specified screen criteria.
                      </td>
                    </tr>
                  ) : (
                    table.getRowModel().rows.map((row) => (
                      <tr key={row.id} className="hover:bg-slate-800/40 transition-colors">
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className="py-3 px-4">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            <div className="p-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
              <div>
                Showing {table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1} to{' '}
                {Math.min(
                  (table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize,
                  table.getFilteredRowModel().rows.length
                )}{' '}
                of {table.getFilteredRowModel().rows.length} screened stocks
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => table.previousPage()}
                  disabled={!table.getCanPreviousPage()}
                  className="px-3 py-1 bg-slate-800 text-slate-200 rounded disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  onClick={() => table.nextPage()}
                  disabled={!table.getCanNextPage()}
                  className="px-3 py-1 bg-slate-800 text-slate-200 rounded disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
