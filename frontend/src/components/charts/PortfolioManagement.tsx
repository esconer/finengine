/**
 * PortfolioManagement component for adding/editing positions and rebalancing
 */

import React, { useState, useEffect } from 'react';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import {
    Plus,
    Edit3,
    Save,
    X,
    AlertTriangle,
    TrendingUp,
    Target,
} from 'lucide-react';
import { usePortfolioStore } from '@/lib/store';
import { portfolioApi, dataApi } from '@/lib/api';

interface PositionFormData {
    ticker: string;
    weight: number;
    quantity: number;
    buy_price: number;
    region: string;
    custom_name?: string;
}

interface PositionEditData extends PositionFormData {
    id?: number;
}

interface PortfolioManagementProps {
    trigger?: React.ReactNode;
    mode: 'add' | 'edit' | 'rebalance';
    position?: any;
    onClose?: () => void;
    className?: string;
}

export const PortfolioManagement: React.FC<PortfolioManagementProps> = ({
    trigger,
    mode,
    position,
    onClose,
    className = '',
}) => {
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [validating, setValidating] = useState(false);
    const [formData, setFormData] = useState<PositionFormData>({
        ticker: '',
        weight: 0,
        quantity: 0,
        buy_price: 0,
        region: 'US',
        custom_name: '',
    });
    const [errors, setErrors] = useState<Record<string, string>>({});
    const { fetchPortfolio, positions } = usePortfolioStore();

    // Pre-fill form data when editing
    useEffect(() => {
        if (mode === 'edit' && position) {
            setFormData({
                ticker: position.ticker,
                weight: position.weight,
                quantity: position.quantity || 0,
                buy_price: position.buy_price || 0,
                region: 'US', // Default region
                custom_name: position.custom_name || '',
            });
        }
    }, [mode, position]);

    const regions = [
        { value: 'US', label: 'United States' },
        { value: 'EU', label: 'Europe' },
        { value: 'APAC', label: 'Asia-Pacific' },
        { value: 'EM', label: 'Emerging Markets' },
    ];

    const validateForm = (): boolean => {
        const newErrors: Record<string, string> = {};

        if (!formData.ticker.trim()) {
            newErrors.ticker = 'Ticker is required';
        }

        if (formData.weight <= 0 || formData.weight > 1) {
            newErrors.weight = 'Weight must be between 0 and 1 (0% and 100%)';
        }

        if (formData.quantity <= 0) {
            newErrors.quantity = 'Quantity must be greater than 0';
        }

        if (formData.buy_price <= 0) {
            newErrors.buy_price = 'Buy price must be greater than 0';
        }

        // Check for duplicate ticker when adding
        if (mode === 'add' && positions.some(p => p.ticker.toUpperCase() === formData.ticker.toUpperCase())) {
            newErrors.ticker = 'This ticker already exists in the portfolio';
        }

        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const validateTicker = async (ticker: string) => {
        if (!ticker.trim()) return;

        setValidating(true);
        try {
            await dataApi.validateTicker(ticker);
            setErrors(prev => ({ ...prev, ticker: '' })); // Clear ticker error if validation passes
        } catch (error: any) {
            setErrors(prev => ({
                ...prev,
                ticker: error.response?.data?.detail || 'Invalid ticker symbol'
            }));
        } finally {
            setValidating(false);
        }
    };

    const handleTickerChange = (ticker: string) => {
        setFormData(prev => ({ ...prev, ticker: ticker.toUpperCase() }));

        // Clear previous ticker error
        if (errors.ticker) {
            setErrors(prev => ({ ...prev, ticker: '' }));
        }

        // Validate ticker after short delay
        if (ticker.length >= 1) {
            const timeoutId = setTimeout(() => {
                validateTicker(ticker);
            }, 500);
            return () => clearTimeout(timeoutId);
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!validateForm()) return;

        setLoading(true);
        try {
            if (mode === 'add') {
                await portfolioApi.addPosition(formData);
            } else if (mode === 'edit') {
                await portfolioApi.updatePosition(formData.ticker, {
                    weight: formData.weight,
                    custom_name: formData.custom_name,
                });
            }

            await fetchPortfolio();
            setOpen(false);
            onClose?.();

            // Reset form
            setFormData({
                ticker: '',
                weight: 0,
                quantity: 0,
                buy_price: 0,
                region: 'US',
                custom_name: '',
            });
            setErrors({});
        } catch (error: any) {
            setErrors({
                submit: error.response?.data?.detail || 'Failed to save position',
            });
        } finally {
            setLoading(false);
        }
    };

    const handleRebalance = async () => {
        setLoading(true);
        try {
            await portfolioApi.normalizeWeights('proportional');
            await fetchPortfolio();
            setOpen(false);
            onClose?.();
        } catch (error: any) {
            setErrors({
                submit: error.response?.data?.detail || 'Failed to rebalance portfolio',
            });
        } finally {
            setLoading(false);
        }
    };

    const getDialogTitle = (): string => {
        switch (mode) {
            case 'add':
                return 'Add Position';
            case 'edit':
                return 'Edit Position';
            case 'rebalance':
                return 'Rebalance Portfolio';
            default:
                return 'Portfolio Management';
        }
    };

    const getDialogDescription = (): string => {
        switch (mode) {
            case 'add':
                return 'Add a new position to your portfolio';
            case 'edit':
                return `Edit position details for ${formData.ticker}`;
            case 'rebalance':
                return 'Normalize portfolio weights to sum to 100%';
            default:
                return 'Manage your portfolio positions';
        }
    };

    const defaultTrigger = (
        <button className={`inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors ${className}`}>
            {mode === 'add' && <Plus className="w-4 h-4 mr-2" />}
            {mode === 'edit' && <Edit3 className="w-4 h-4 mr-2" />}
            {mode === 'rebalance' && <Target className="w-4 h-4 mr-2" />}
            {mode === 'add' && 'Add Position'}
            {mode === 'edit' && 'Edit'}
            {mode === 'rebalance' && 'Rebalance'}
        </button>
    );

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                {trigger || defaultTrigger}
            </DialogTrigger>
            <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                    <DialogTitle>{getDialogTitle()}</DialogTitle>
                    <DialogDescription>{getDialogDescription()}</DialogDescription>
                </DialogHeader>

                {mode === 'rebalance' ? (
                    <div className="space-y-4">
                        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                            <div className="flex items-center">
                                <AlertTriangle className="w-5 h-5 text-blue-600 dark:text-blue-400 mr-2" />
                                <div>
                                    <h4 className="text-sm font-medium text-blue-800 dark:text-blue-200">
                                        Rebalancing will normalize all positions
                                    </h4>
                                    <p className="text-sm text-blue-700 dark:text-blue-300 mt-1">
                                        This will adjust all position weights proportionally so they sum to 100%.
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className="flex justify-end space-x-2">
                            <button
                                onClick={() => setOpen(false)}
                                className="px-4 py-2 text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                                disabled={loading}
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleRebalance}
                                disabled={loading}
                                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg flex items-center disabled:opacity-50"
                            >
                                {loading ? (
                                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" />
                                ) : (
                                    <Target className="w-4 h-4 mr-2" />
                                )}
                                Rebalance Portfolio
                            </button>
                        </div>
                    </div>
                ) : (
                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div className="space-y-2">
                            <label htmlFor="ticker" className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                Ticker Symbol *
                            </label>
                            <input
                                type="text"
                                id="ticker"
                                value={formData.ticker}
                                onChange={(e) => handleTickerChange(e.target.value)}
                                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.ticker
                                    ? 'border-red-500 dark:border-red-400'
                                    : 'border-gray-300 dark:border-gray-600'
                                    } bg-white dark:bg-gray-700 text-gray-900 dark:text-white`}
                                placeholder="e.g., AAPL"
                                maxLength={10}
                                disabled={mode === 'edit'}
                            />
                            {errors.ticker && (
                                <p className="text-sm text-red-600 dark:text-red-400">{errors.ticker}</p>
                            )}
                            {validating && (
                                <p className="text-sm text-blue-600 dark:text-blue-400">Validating ticker...</p>
                            )}
                        </div>

                        <div className="space-y-2">
                            <label htmlFor="weight" className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                Weight (0-1) *
                            </label>
                            <input
                                type="number"
                                id="weight"
                                step="0.01"
                                min="0"
                                max="1"
                                value={formData.weight}
                                onChange={(e) => {
                                    const weight = parseFloat(e.target.value) || 0;
                                    setFormData(prev => ({ ...prev, weight }));
                                    if (errors.weight) setErrors(prev => ({ ...prev, weight: '' }));
                                }}
                                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.weight
                                    ? 'border-red-500 dark:border-red-400'
                                    : 'border-gray-300 dark:border-gray-600'
                                    } bg-white dark:bg-gray-700 text-gray-900 dark:text-white`}
                                placeholder="0.25"
                            />
                            {errors.weight && (
                                <p className="text-sm text-red-600 dark:text-red-400">{errors.weight}</p>
                            )}
                            <p className="text-sm text-gray-600 dark:text-gray-400">
                                Weight: {(formData.weight * 100).toFixed(1)}%
                            </p>
                        </div>

                        <div className="space-y-2">
                            <label htmlFor="quantity" className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                Quantity *
                            </label>
                            <input
                                type="number"
                                id="quantity"
                                step="0.01"
                                min="0"
                                value={formData.quantity}
                                onChange={(e) => {
                                    const quantity = parseFloat(e.target.value) || 0;
                                    setFormData(prev => ({ ...prev, quantity }));
                                    if (errors.quantity) setErrors(prev => ({ ...prev, quantity: '' }));
                                }}
                                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.quantity
                                    ? 'border-red-500 dark:border-red-400'
                                    : 'border-gray-300 dark:border-gray-600'
                                    } bg-white dark:bg-gray-700 text-gray-900 dark:text-white`}
                                placeholder="100"
                            />
                            {errors.quantity && (
                                <p className="text-sm text-red-600 dark:text-red-400">{errors.quantity}</p>
                            )}
                        </div>

                        <div className="space-y-2">
                            <label htmlFor="buy_price" className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                Buy Price *
                            </label>
                            <input
                                type="number"
                                id="buy_price"
                                step="0.01"
                                min="0"
                                value={formData.buy_price}
                                onChange={(e) => {
                                    const buy_price = parseFloat(e.target.value) || 0;
                                    setFormData(prev => ({ ...prev, buy_price }));
                                    if (errors.buy_price) setErrors(prev => ({ ...prev, buy_price: '' }));
                                }}
                                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.buy_price
                                    ? 'border-red-500 dark:border-red-400'
                                    : 'border-gray-300 dark:border-gray-600'
                                    } bg-white dark:bg-gray-700 text-gray-900 dark:text-white`}
                                placeholder="150.00"
                            />
                            {errors.buy_price && (
                                <p className="text-sm text-red-600 dark:text-red-400">{errors.buy_price}</p>
                            )}
                        </div>

                        <div className="space-y-2">
                            <label htmlFor="region" className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                Region
                            </label>
                            <Select
                                value={formData.region}
                                onValueChange={(value: string) => setFormData(prev => ({ ...prev, region: value }))}
                            >
                                <SelectTrigger>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {regions.map((region) => (
                                        <SelectItem key={region.value} value={region.value}>
                                            {region.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <div className="space-y-2">
                            <label htmlFor="custom_name" className="text-sm font-medium text-gray-700 dark:text-gray-300">
                                Custom Name (Optional)
                            </label>
                            <input
                                type="text"
                                id="custom_name"
                                value={formData.custom_name}
                                onChange={(e) => setFormData(prev => ({ ...prev, custom_name: e.target.value }))}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                                placeholder="Custom display name"
                                maxLength={50}
                            />
                        </div>

                        {errors.submit && (
                            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3">
                                <p className="text-sm text-red-600 dark:text-red-400">{errors.submit}</p>
                            </div>
                        )}

                        <div className="flex justify-end space-x-2 pt-4">
                            <button
                                type="button"
                                onClick={() => {
                                    setOpen(false);
                                    onClose?.();
                                }}
                                className="px-4 py-2 text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700"
                                disabled={loading}
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                disabled={loading || validating}
                                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg flex items-center disabled:opacity-50"
                            >
                                {loading ? (
                                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" />
                                ) : mode === 'add' ? (
                                    <Plus className="w-4 h-4 mr-2" />
                                ) : (
                                    <Save className="w-4 h-4 mr-2" />
                                )}
                                {mode === 'add' ? 'Add Position' : 'Save Changes'}
                            </button>
                        </div>
                    </form>
                )}
            </DialogContent>
        </Dialog>
    );
};

export default PortfolioManagement;