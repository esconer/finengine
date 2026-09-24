/**
 * Portfolio Management Page
 * Complete CRUD interface for portfolio management with currency toggle and risk analytics
 */

'use client';

import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
    Plus,
    DollarSign,
    TrendingUp,
    TrendingDown,
    RefreshCw,
    Filter,
    Edit2,
    Trash2,
    Check,
    X,
    AlertTriangle,
    Shield,
    Activity,
    UploadCloud
} from 'lucide-react';
import {
    PortfolioPosition,
    PortfolioSummary,
    PortfolioCreateRequest,
    PortfolioUpdateRequest,
    Currency
} from '@/types';
import { DashboardLayout } from '@/components/layout/DashboardLayout';
import { LoadingState } from '@/components/ui/LoadingState';
import { PortfolioStats } from '@/components/portfolio/PortfolioStats';
import { AddPositionModalSimple } from '@/components/portfolio/AddPositionModalSimple';
import { PortfolioDropzone } from '@/components/portfolio/PortfolioDropzone';
import { analyticsApi, portfolioApi } from '@/lib/api';
import { usePortfolioStore } from '@/lib/store';
import { cn, formatCurrency as sharedFormatCurrency } from '@/lib/utils';

// Payload already carries snake_case calculated fields (PortfolioPosition)
type SimplePortfolioPosition = PortfolioPosition;

const monetaryValue = (base: number | null | undefined, native: number | null | undefined): number => {
    if (typeof base === 'number' && Number.isFinite(base)) return base;
    if (typeof native === 'number' && Number.isFinite(native)) return native;
    return 0;
};

export default function PortfolioManagePage() {
    // State management
    const [positions, setPositions] = useState<SimplePortfolioPosition[]>([]);
    const [summary, setSummary] = useState<PortfolioSummary | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isLoadingForecast, setIsLoadingForecast] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [forecastNotice, setForecastNotice] = useState<string | null>(null);
    const [currency, setCurrency] = useState<Currency>('INR');
    const { setPortfolioSnapshot, setPositionCount } = usePortfolioStore();
    const fetchSequence = useRef(0);

    // Modal states
    const [showAddModal, setShowAddModal] = useState(false);
    const [showImportModal, setShowImportModal] = useState(false);
    const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
    const [isDeleting, setIsDeleting] = useState(false);

    // Editing states
    const [editingTicker, setEditingTicker] = useState<string | null>(null);
    const [editingValues, setEditingValues] = useState<{
        quantity: number;
        buy_price: number;
        weight: number;
        custom_name: string;
        added_on: string;
    }>({
        quantity: 0,
        buy_price: 0,
        weight: 0,
        custom_name: '',
        added_on: ''
    });

    // Filter states
    const [searchQuery, setSearchQuery] = useState('');
    const [sortBy, setSortBy] = useState<keyof SimplePortfolioPosition>('current_value');
    const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

    // Fetch forecast risk data for all positions
    const fetchForecastRisk = async (positions: SimplePortfolioPosition[]) => {
        try {
            setIsLoadingForecast(true);

            if (positions.length === 0) return;

            // Get unique tickers from positions
            const tickers = positions.map(p => p.ticker).join(',');

            const response = await analyticsApi.getForecastRisk({
                model: 'GARCH',
                horizon: 1,
                tickers
            });

            const data = (response as any)?.data || response;
            if (data) {
                // Surface backend null+flag contract (error / is_limited_history)
                setForecastNotice(
                    data.error
                        ? String(data.error)
                        : data.is_limited_history
                            ? 'Limited price history — forecasts may be unreliable.'
                            : null
                );
            }
            if (data && data.positions) {
                // Update positions with forecast risk data
                const updatedPositions = positions.map(position => {
                    const tickerData = data.positions?.[position.ticker];
                    if (tickerData) {
                        const vol =
                            typeof tickerData.volatility_forecast === 'number'
                                ? tickerData.volatility_forecast
                                : undefined;
                        const varFc =
                            typeof tickerData.var_forecast === 'number'
                                ? tickerData.var_forecast
                                : undefined;
                        return {
                            ...position,
                            volatility_forecast: vol,
                            var_forecast: varFc,
                            risk_level: vol !== undefined ? getRiskLevel(vol) : undefined
                        };
                    }
                    return {
                        ...position,
                        volatility_forecast: undefined,
                        var_forecast: undefined,
                        risk_level: undefined
                    };
                });

                setPositions(updatedPositions);
            }
        } catch (err) {
            console.error('Failed to fetch forecast risk:', err);
            // No forecast data → N/A, never a fabricated risk classification
            setForecastNotice('Forecast risk unavailable — showing N/A.');
            const updatedPositions = positions.map(position => ({
                ...position,
                volatility_forecast: undefined,
                var_forecast: undefined,
                risk_level: undefined
            }));
            setPositions(updatedPositions);
        } finally {
            setIsLoadingForecast(false);
        }
    };

    // Determine risk level based on volatility forecast
    const getRiskLevel = (volatility: number): 'Low' | 'Medium' | 'High' => {
        if (volatility < 20) return 'Low';
        if (volatility < 40) return 'Medium';
        return 'High';
    };

    // Fetch portfolio data
    const fetchPortfolio = async () => {
        const sequence = ++fetchSequence.current;
        try {
            setIsLoading(true);
            setError(null);

            const data = await portfolioApi.getPortfolio({ currency });
            if (sequence !== fetchSequence.current) return;

            // Preserve native fields for editing while using the API's explicit
            // base-currency fields for every displayed monetary value.
            const transformedPositions = data.positions.map((pos: any) => {
                const nativeCost = pos.quantity * pos.buy_price;
                const nativeCurrent = pos.current_value ?? pos.market_value ?? 0;
                const baseCost = monetaryValue(pos.total_cost_base, nativeCost);
                const baseCurrent = monetaryValue(pos.current_value_base, nativeCurrent);
                return {
                    ...pos,
                    total_cost: nativeCost,
                    unrealized_gain_loss: nativeCurrent - nativeCost,
                    unrealized_gain_loss_pct: nativeCost > 0 ? ((nativeCurrent - nativeCost) / nativeCost) * 100 : NaN,
                    current_value: nativeCurrent,
                    total_cost_base: baseCost,
                    current_value_base: baseCurrent,
                    market_value_base: monetaryValue(pos.market_value_base, baseCurrent),
                    unrealized_gain_loss_base: monetaryValue(
                        pos.unrealized_gain_loss_base,
                        baseCurrent - baseCost
                    ),
                    unrealized_gain_loss_pct_base: monetaryValue(
                        pos.unrealized_gain_loss_pct_base,
                        baseCost > 0 ? ((baseCurrent - baseCost) / baseCost) * 100 : NaN
                    ),
                    buy_price_base: monetaryValue(pos.buy_price_base, pos.buy_price),
                    last_price_base: monetaryValue(pos.last_price_base, pos.last_price),
                };
            });

            setPositions(transformedPositions);
            setSummary({
                positions: transformedPositions,
                total_value: data.total_value,
                total_positions: data.total_positions,
                total_weight: data.total_weight,
                sectors: data.sectors,
                currency: data.currency,
                base_currency: data.base_currency,
                currency_provenance: data.currency_provenance,
                position_currencies: data.position_currencies
            });
            setPositionCount?.(data.total_positions);
            if (currency === 'INR') {
                setPortfolioSnapshot?.({
                    positions: transformedPositions,
                    total_value: data.total_value,
                    total_weight: data.total_weight,
                });
            }

            // Fire-and-forget: GARCH latency must not block first paint
            // (forecast columns have their own isLoadingForecast skeletons).
            void fetchForecastRisk(transformedPositions);
        } catch (err) {
            if (sequence !== fetchSequence.current) return;
            console.error('Failed to fetch portfolio:', err);
            setError('Failed to load portfolio data. Please try again.');
        } finally {
            if (sequence === fetchSequence.current) setIsLoading(false);
        }
    };

    // Initialize data
    useEffect(() => {
        fetchPortfolio();
    }, [currency]);

    // Handle currency toggle
    const handleCurrencyChange = (newCurrency: Currency) => {
        setCurrency(newCurrency);
    };

    // Add new position
    const handleAddPosition = async (positionData: PortfolioCreateRequest) => {
        try {
            await portfolioApi.addPosition(positionData);
            // Refresh portfolio data
            await fetchPortfolio();
        } catch (error) {
            console.error('Failed to add position:', error);
            throw error;
        }
    };

    // Update position
    const handleUpdatePosition = async (id: number, updates: PortfolioUpdateRequest) => {
        try {
            const position = positions.find(p => p.id === id);
            if (!position) throw new Error('Position not found');

            await portfolioApi.updatePosition(position.ticker, updates);

            // Refresh portfolio data
            await fetchPortfolio();
        } catch (error) {
            console.error('Failed to update position:', error);
            throw error;
        }
    };

    // Delete position
    const handleDeletePosition = async (ticker: string) => {
        setIsDeleting(true);
        try {
            await portfolioApi.deletePosition(ticker);

            // Refresh portfolio data
            await fetchPortfolio();
            setDeleteConfirm(null);
            setError(null);

            return true;
        } catch (error) {
            console.error('Failed to delete position:', error);
            throw error;
        } finally {
            setIsDeleting(false);
        }
    };

    // Quick edit functions
    const startEditing = (position: SimplePortfolioPosition) => {
        setEditingTicker(position.ticker);
        setEditingValues({
            quantity: position.quantity,
            buy_price: position.buy_price,
            weight: position.weight,
            custom_name: position.custom_name || '',
            added_on: position.added_on ? position.added_on.slice(0, 10) : new Date().toISOString().split('T')[0]
        });
    };

    const cancelEditing = () => {
        setEditingTicker(null);
        setEditingValues({
            quantity: 0,
            buy_price: 0,
            weight: 0,
            custom_name: '',
            added_on: ''
        });
    };

    const saveEditing = async () => {
        if (!editingTicker) return;

        const position = positions.find(p => p.ticker === editingTicker);
        if (!position) return;

        // Block invalid input before the backend 422 arrives
        if (!(editingValues.quantity > 0) || !(editingValues.buy_price > 0)) {
            setError('Quantity and buy price must be greater than 0.');
            return;
        }

        const today = new Date().toISOString().split('T')[0];
        const positionDate = position.added_on ? position.added_on.slice(0, 10) : '';
        const updates: PortfolioUpdateRequest = {
            quantity: editingValues.quantity,
            buy_price: editingValues.buy_price,
            weight: editingValues.weight,
            custom_name: editingValues.custom_name
        };
        if (editingValues.added_on && editingValues.added_on !== positionDate) {
            if (/^\d{4}-\d{2}-\d{2}$/.test(editingValues.added_on) && editingValues.added_on <= today) {
                updates.added_on = editingValues.added_on;
            } else {
                setError('Invalid buy date: must be a valid date, not in the future. Save cancelled.');
                return;
            }
        }

        try {
            await handleUpdatePosition(position.id, updates);
            setEditingTicker(null);
            setError(null);
        } catch (error) {
            setError(error instanceof Error ? error.message : 'Failed to save changes');
        }
    };

    // Handle sorting
    const handleSort = (field: keyof SimplePortfolioPosition) => {
        if (field === sortBy) {
            setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(field);
            setSortDirection('desc');
        }
    };

    // Filter and sort positions
    const filteredPositions = useMemo(() => {
        return positions
            .filter(pos => {
                const matchesSearch = !searchQuery ||
                    pos.ticker.toLowerCase().includes(searchQuery.toLowerCase()) ||
                    (pos.custom_name && pos.custom_name.toLowerCase().includes(searchQuery.toLowerCase())) ||
                    pos.sector.toLowerCase().includes(searchQuery.toLowerCase());

                return matchesSearch;
            })
            .sort((a, b) => {
                const aVal = a[sortBy];
                const bVal = b[sortBy];

                if (typeof aVal === 'string' && typeof bVal === 'string') {
                    return sortDirection === 'asc'
                        ? aVal.localeCompare(bVal)
                        : bVal.localeCompare(aVal);
                }

                if (typeof aVal === 'number' && typeof bVal === 'number') {
                    return sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
                }

                return 0;
            });
    }, [positions, searchQuery, sortBy, sortDirection]);

    // Calculate total portfolio metrics in the selected response currency.
    const totalGainLoss = positions.reduce(
        (sum, pos) => sum + monetaryValue(
            pos.unrealized_gain_loss_base,
            pos.unrealized_gain_loss
        ),
        0
    );
    const totalCost = positions.reduce(
        (sum, pos) => sum + monetaryValue(pos.total_cost_base, pos.total_cost),
        0
    );
    const totalGainLossPct = totalCost > 0 ? (totalGainLoss / totalCost) * 100 : 0;

    const formatCurrency = (amount: number) =>
        sharedFormatCurrency(amount, currency);

    if (isLoading) {
        return (
            <DashboardLayout>
                <LoadingState
                    message="Fetching your investment data..."
                />
            </DashboardLayout>
        );
    }

    return (
        <DashboardLayout>
            <div className="space-y-6">
                {/* Header with Currency Toggle and Actions */}
                <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between space-y-4 lg:space-y-0">
                    <div>
                        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                            Portfolio Management
                        </h1>
                        <p className="text-gray-600 dark:text-gray-400 mt-1">
                            Manage your investment positions with real-time tracking
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                            Values are shown in {currency}; P&L uses current live FX.
                        </p>
                    </div>

                    <div className="flex items-center space-x-4">
                        {/* Currency Toggle */}
                        <div className="flex bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
                            <button
                                onClick={() => handleCurrencyChange('USD')}
                                className={cn(
                                    'flex items-center space-x-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all',
                                    currency === 'USD'
                                        ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow'
                                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                                )}
                            >
                                <DollarSign className="w-4 h-4" />
                                <span>USD</span>
                            </button>
                            <button
                                onClick={() => handleCurrencyChange('INR')}
                                className={cn(
                                    'flex items-center space-x-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all',
                                    currency === 'INR'
                                        ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow'
                                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                                )}
                            >
                                <span className="text-lg">₹</span>
                                <span>INR</span>
                            </button>
                        </div>

                        {/* Action Buttons */}
                        <button
                            onClick={fetchPortfolio}
                            className="flex items-center space-x-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                        >
                            <RefreshCw className="w-4 h-4" />
                            <span>Refresh</span>
                        </button>

                        <button
                            onClick={() => setShowImportModal(true)}
                            className="flex items-center space-x-2 px-4 py-2 text-sm font-medium text-slate-200 bg-slate-800 border border-slate-700 rounded-lg hover:bg-slate-700 focus:outline-none transition-colors"
                        >
                            <UploadCloud className="w-4 h-4 text-blue-400" />
                            <span>Import CSV</span>
                        </button>

                        <button
                            onClick={() => setShowAddModal(true)}
                            className="flex items-center space-x-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors"
                        >
                            <Plus className="w-4 h-4" />
                            <span>Add Position</span>
                        </button>
                    </div>
                </div>

                {/* Error Display */}
                {error && (
                    <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
                        <div className="flex items-center space-x-2">
                            <TrendingDown className="w-5 h-5 text-red-600" />
                            <p className="text-sm font-medium text-red-800 dark:text-red-200">{error}</p>
                        </div>
                    </div>
                )}

                {/* Forecast null+flag notice (error / is_limited_history) */}
                {forecastNotice && (
                    <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4">
                        <div className="flex items-center space-x-2">
                            <AlertTriangle className="w-5 h-5 text-amber-600" />
                            <p className="text-sm font-medium text-amber-800 dark:text-amber-200">{forecastNotice}</p>
                        </div>
                    </div>
                )}

                {/* Portfolio Summary */}
                {summary && (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                        <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
                            <div className="flex items-center">
                                <div className="flex-shrink-0">
                                    <DollarSign className="h-8 w-8 text-blue-600" />
                                </div>
                                <div className="ml-4">
                                    <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Total Value</p>
                                    <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                                        {formatCurrency(summary.total_value)}
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
                            <div className="flex items-center">
                                <div className="flex-shrink-0">
                                    {totalGainLoss >= 0 ? (
                                        <TrendingUp className="h-8 w-8 text-green-600" />
                                    ) : (
                                        <TrendingDown className="h-8 w-8 text-red-600" />
                                    )}
                                </div>
                                <div className="ml-4">
                                    <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Total Gain/Loss</p>
                                    <p className={cn(
                                        'text-2xl font-semibold',
                                        totalGainLoss >= 0 ? 'text-green-600' : 'text-red-600'
                                    )}>
                                        {totalGainLoss >= 0 ? '+' : ''}
                                        {formatCurrency(totalGainLoss)}
                                    </p>
                                    <p className={cn(
                                        'text-sm',
                                        totalGainLoss >= 0 ? 'text-green-600' : 'text-red-600'
                                    )}>
                                        {totalGainLoss >= 0 ? '+' : ''}{totalGainLossPct.toFixed(2)}%
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
                            <div className="flex items-center">
                                <div className="flex-shrink-0">
                                    <Filter className="h-8 w-8 text-purple-600" />
                                </div>
                                <div className="ml-4">
                                    <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Positions</p>
                                    <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                                        {summary.total_positions}
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
                            <div className="flex items-center">
                                <div className="flex-shrink-0">
                                    <TrendingUp className="h-8 w-8 text-orange-600" />
                                </div>
                                <div className="ml-4">
                                    <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Avg Weight</p>
                                    <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                                        {summary.total_positions > 0
                                            ? ((summary.total_weight / summary.total_positions) * 100).toFixed(1)
                                            : '0'
                                        }%
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* Search Filter */}
                {positions.length > 0 && (
                    <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-4">
                        <div className="flex items-center space-x-4">
                            <div className="flex-1">
                                <input
                                    type="text"
                                    placeholder="Search by ticker, name, or sector..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-white"
                                />
                            </div>
                        </div>
                    </div>
                )}

                {/* Portfolio Statistics */}
                {positions.length > 0 && (
                    <PortfolioStats
                        positions={positions}
                        currency={currency}
                    />
                )}

                {/* Portfolio Table with CRUD Operations */}
                {positions.length > 0 ? (
                    <div className="bg-white dark:bg-gray-900 rounded-lg shadow overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                                <thead className="bg-gray-50 dark:bg-gray-800">
                                    <tr>
                                        <th
                                            className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                                            onClick={() => handleSort('ticker')}
                                        >
                                            Symbol {sortBy === 'ticker' && (sortDirection === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                            Quantity
                                        </th>
                                        <th
                                            className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                                            onClick={() => handleSort('buy_price')}
                                        >
                                            Buy Price {sortBy === 'buy_price' && (sortDirection === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th
                                            className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                                            onClick={() => handleSort('added_on')}
                                        >
                                            Buy Date {sortBy === 'added_on' && (sortDirection === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th
                                            className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                                            onClick={() => handleSort('weight')}
                                        >
                                            Weight {sortBy === 'weight' && (sortDirection === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th
                                            className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                                            onClick={() => handleSort('current_value')}
                                        >
                                            Current Value {sortBy === 'current_value' && (sortDirection === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th
                                            className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                                            onClick={() => handleSort('unrealized_gain_loss')}
                                        >
                                            Gain/Loss {sortBy === 'unrealized_gain_loss' && (sortDirection === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                            % Return
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                            Volatility Forecast
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                            VaR Forecast
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                            Risk Level
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                            Actions
                                        </th>
                                    </tr>
                                </thead>
                                <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                                    {filteredPositions.map((position) => (
                                        <tr key={position.id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div>
                                                    <div className="text-sm font-medium text-gray-900 dark:text-white">
                                                        {editingTicker === position.ticker ? (
                                                            <input
                                                                type="text"
                                                                value={editingValues.custom_name || ''}
                                                                onChange={(e) => setEditingValues(prev => ({ ...prev, custom_name: e.target.value }))}
                                                                className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                                                                placeholder="Custom name"
                                                            />
                                                        ) : (
                                                            <>
                                                                {position.ticker}
                                                                {position.custom_name && (
                                                                    <div className="text-xs text-gray-500 mt-1">
                                                                        {position.custom_name}
                                                                    </div>
                                                                )}
                                                            </>
                                                        )}
                                                    </div>
                                                    <div className="text-sm text-gray-500 dark:text-gray-400">
                                                        {position.sector}
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                                                {editingTicker === position.ticker ? (
                                                    <input
                                                        type="number"
                                                        value={editingValues.quantity}
                                                        onChange={(e) => setEditingValues(prev => ({ ...prev, quantity: parseFloat(e.target.value) || 0 }))}
                                                        className="w-20 px-2 py-1 border border-gray-300 rounded text-sm"
                                                        step="0.01"
                                                    />
                                                ) : (
                                                    position.quantity.toLocaleString()
                                                )}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                                                {editingTicker === position.ticker ? (
                                                    <input
                                                        type="number"
                                                        value={editingValues.buy_price}
                                                        onChange={(e) => setEditingValues(prev => ({ ...prev, buy_price: parseFloat(e.target.value) || 0 }))}
                                                        className="w-24 px-2 py-1 border border-gray-300 rounded text-sm"
                                                        step="0.01"
                                                    />
                                                ) : (
                                                    formatCurrency(monetaryValue(position.buy_price_base, position.buy_price))
                                                )}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                                                {editingTicker === position.ticker ? (
                                                    <input
                                                        type="date"
                                                        value={editingValues.added_on}
                                                        max={new Date().toISOString().split('T')[0]}
                                                        onChange={(e) => setEditingValues(prev => ({ ...prev, added_on: e.target.value }))}
                                                        className="w-32 px-2 py-1 border border-gray-300 rounded text-sm"
                                                    />
                                                ) : (
                                                    position.added_on ? position.added_on.slice(0, 10) : '—'
                                                )}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                                                {typeof position.weight === 'number'
                                                    ? `${(position.weight * 100).toFixed(2)}%`
                                                    : <span className="text-gray-500">N/A</span>}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                                                {formatCurrency(monetaryValue(position.current_value_base, position.current_value))}
                                            </td>
                                            <td className={cn(
                                                "px-6 py-4 whitespace-nowrap text-sm font-medium",
                                                monetaryValue(position.unrealized_gain_loss_base, position.unrealized_gain_loss) >= 0 ? "text-green-600" : "text-red-600"
                                            )}>
                                                {monetaryValue(position.unrealized_gain_loss_base, position.unrealized_gain_loss) >= 0 ? '+' : ''}
                                                {formatCurrency(monetaryValue(position.unrealized_gain_loss_base, position.unrealized_gain_loss))}
                                            </td>
                                            <td className={cn(
                                                "px-6 py-4 whitespace-nowrap text-sm font-medium",
                                                monetaryValue(position.unrealized_gain_loss_base, position.unrealized_gain_loss) >= 0 ? "text-green-600" : "text-red-600"
                                            )}>
                                                {Number.isFinite(monetaryValue(position.unrealized_gain_loss_pct_base, position.unrealized_gain_loss_pct))
                                                    ? `${monetaryValue(position.unrealized_gain_loss_base, position.unrealized_gain_loss) >= 0 ? '+' : ''}${monetaryValue(position.unrealized_gain_loss_pct_base, position.unrealized_gain_loss_pct).toFixed(2)}%`
                                                    : <span className="text-gray-500">N/A</span>}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                                                {isLoadingForecast ? (
                                                    <div className="flex items-center space-x-1">
                                                        <Activity className="w-3 h-3 animate-pulse" />
                                                        <span>Loading...</span>
                                                    </div>
                                                ) : position.volatility_forecast != null ? (
                                                    <div className="flex items-center space-x-1">
                                                        <Activity className="w-4 h-4 text-blue-500" />
                                                        <span>{position.volatility_forecast.toFixed(2)}%</span>
                                                    </div>
                                                ) : (
                                                    <span className="text-gray-500">N/A</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                                                {isLoadingForecast ? (
                                                    <div className="flex items-center space-x-1">
                                                        <Activity className="w-3 h-3 animate-pulse" />
                                                        <span>Loading...</span>
                                                    </div>
                                                ) : position.var_forecast != null ? (
                                                    <div className="flex items-center space-x-1">
                                                        <AlertTriangle className="w-4 h-4 text-orange-500" />
                                                        <span className={cn(
                                                            "font-medium",
                                                            position.var_forecast >= 0 ? "text-green-600" : "text-red-600"
                                                        )}>
                                                            {position.var_forecast >= 0 ? '+' : ''}{position.var_forecast.toFixed(2)}%
                                                        </span>
                                                    </div>
                                                ) : (
                                                    <span className="text-gray-500">N/A</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm">
                                                {isLoadingForecast ? (
                                                    <div className="flex items-center space-x-1">
                                                        <Activity className="w-3 h-3 animate-pulse" />
                                                        <span>Loading...</span>
                                                    </div>
                                                ) : position.risk_level ? (
                                                    <span className={cn(
                                                        "inline-flex items-center px-2 py-1 rounded-full text-xs font-medium",
                                                        position.risk_level === 'Low' ? "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400" :
                                                        position.risk_level === 'Medium' ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400" :
                                                        "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400"
                                                    )}>
                                                        <Shield className="w-3 h-3 mr-1" />
                                                        {position.risk_level}
                                                    </span>
                                                ) : (
                                                    <span className="text-gray-500">N/A</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                                {editingTicker === position.ticker ? (
                                                    <div className="flex space-x-2">
                                                        <button
                                                            onClick={saveEditing}
                                                            className="text-green-600 hover:text-green-900"
                                                        >
                                                            <Check className="w-4 h-4" />
                                                        </button>
                                                        <button
                                                            onClick={cancelEditing}
                                                            className="text-red-600 hover:text-red-900"
                                                        >
                                                            <X className="w-4 h-4" />
                                                        </button>
                                                    </div>
                                                ) : (
                                                    <div className="flex space-x-2">
                                                        <button
                                                            onClick={() => startEditing(position)}
                                                            className="text-blue-600 hover:text-blue-900"
                                                        >
                                                            <Edit2 className="w-4 h-4" />
                                                        </button>
                                                        <button
                                                            onClick={() => setDeleteConfirm(position.ticker)}
                                                            className="text-red-600 hover:text-red-900"
                                                        >
                                                            <Trash2 className="w-4 h-4" />
                                                        </button>
                                                    </div>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ) : (
                    <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-12 text-center">
                        <Plus className="mx-auto h-12 w-12 text-gray-400" />
                        <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-white">No positions</h3>
                        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                            Get started by adding your first portfolio position.
                        </p>
                        <div className="mt-6">
                            <button
                                onClick={() => setShowAddModal(true)}
                                className="inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                            >
                                <Plus className="-ml-1 mr-2 h-5 w-5" />
                                Add Position
                            </button>
                        </div>
                    </div>
                )}

                {/* Add Position Modal */}
                <AddPositionModalSimple
                    isOpen={showAddModal}
                    onClose={() => setShowAddModal(false)}
                    onAdd={handleAddPosition}
                    currency={currency}
                />

                {/* Import Portfolio CSV Dropzone Modal */}
                <PortfolioDropzone
                    isOpen={showImportModal}
                    onClose={() => setShowImportModal(false)}
                    onSuccess={fetchPortfolio}
                />

                {/* Delete Confirmation Dialog */}
                {deleteConfirm && (
                    <div
                        className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="delete-confirm-title"
                        onKeyDown={(e) => { if (e.key === 'Escape') setDeleteConfirm(null); }}
                    >
                        <div className="bg-white dark:bg-gray-900 rounded-lg p-6 max-w-md w-full mx-4">
                            <h3 id="delete-confirm-title" className="text-lg font-medium text-gray-900 dark:text-white mb-4">
                                Confirm Delete
                            </h3>
                            <p className="text-gray-600 dark:text-gray-400 mb-4">
                                Are you sure you want to delete position {deleteConfirm}? This action cannot be undone.
                            </p>
                            {error && (
                                <p className="text-sm text-red-600 dark:text-red-400 mb-4">{error}</p>
                            )}
                            <div className="flex justify-end space-x-3">
                                <button
                                    onClick={() => { setDeleteConfirm(null); setError(null); }}
                                    className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-200 dark:hover:bg-gray-700"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={async () => {
                                        try {
                                            await handleDeletePosition(deleteConfirm);
                                        } catch (err) {
                                            // Keep the dialog open and surface the real message
                                            setError(err instanceof Error ? err.message : 'Failed to delete position');
                                        }
                                    }}
                                    disabled={isDeleting}
                                    className="px-4 py-2 text-sm font-medium text-white bg-red-600 border border-transparent rounded-md hover:bg-red-700 disabled:opacity-50"
                                >
                                    {isDeleting ? 'Deleting…' : 'Delete'}
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </DashboardLayout>
    );
}