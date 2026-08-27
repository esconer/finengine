/**
 * Simple Add Position Modal - BULLETPROOF VERSION
 * Minimal, focused modal with guaranteed field visibility
 */

'use client';

import React, { useState, useEffect } from 'react';
import { X, Plus, Loader } from 'lucide-react';
import { PortfolioCreateRequest, Currency } from '@/types';
import { portfolioApi } from '@/lib/api';
import { cn } from '@/lib/utils';

interface AddPositionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAdd: (position: PortfolioCreateRequest) => Promise<void>;
  currency: Currency;
}

export function AddPositionModalSimple({ isOpen, onClose, onAdd, currency }: AddPositionModalProps) {
  const [formData, setFormData] = useState<PortfolioCreateRequest>({
    ticker: '',
    weight: 0,
    quantity: 0,
    buy_price: 0,
    region: 'US',
    custom_name: ''
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [totalPortfolioValue, setTotalPortfolioValue] = useState(0);
  const [existingCount, setExistingCount] = useState(0);

  // Fetch total portfolio value
  useEffect(() => {
    if (isOpen) {
      fetchTotalPortfolioValue();
    }
  }, [isOpen]);

  const fetchTotalPortfolioValue = async () => {
    try {
      const data = await portfolioApi.getPortfolio({ currency });
      const posList = data.positions || [];
      setExistingCount(posList.length);
      setTotalPortfolioValue(data.total_value || 0);
    } catch (error) {
      console.error('Failed to fetch portfolio total:', error);
      setTotalPortfolioValue(0);
      setExistingCount(0);
    }
  };

  // Reset form when modal opens
  useEffect(() => {
    if (isOpen) {
      setFormData({
        ticker: '',
        weight: 0,
        quantity: 0,
        buy_price: 0,
        region: currency === 'INR' ? 'IN' : 'US',
        custom_name: ''
      });
      setErrors({});
    }
  }, [isOpen, currency]);

  // Auto-calculate weight when quantity or buy price changes
  useEffect(() => {
    if (formData.quantity > 0 && formData.buy_price > 0) {
      const positionValue = formData.quantity * formData.buy_price;
      if (existingCount === 0 || totalPortfolioValue <= 0) {
        // First position in an empty portfolio is always 100% (1.0)
        setFormData(prev => ({ ...prev, weight: 1.0 }));
      } else {
        const newTotalValue = totalPortfolioValue + positionValue;
        const estimatedWeight = positionValue / newTotalValue;
        setFormData(prev => ({ ...prev, weight: estimatedWeight }));
      }
    }
  }, [formData.quantity, formData.buy_price, totalPortfolioValue, existingCount]);

  // Validate form
  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!formData.ticker.trim()) {
      newErrors.ticker = 'Ticker symbol is required';
    } else if (!/^[A-Za-z0-9\-\&\.]{1,20}$/.test(formData.ticker.trim())) {
      newErrors.ticker = 'Invalid ticker symbol format';
    }

    if (formData.quantity <= 0) {
      newErrors.quantity = 'Quantity must be greater than 0';
    }

    if (formData.buy_price <= 0) {
      newErrors.buy_price = 'Buy price must be greater than 0';
    }

    // Validate weight is properly set
    if (formData.weight <= 0 || formData.weight > 1) {
      newErrors.weight = 'Weight must be between 0 and 1';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!validateForm()) {
      return;
    }

    try {
      setIsSubmitting(true);
      setErrors({});
      await onAdd(formData);
      onClose();
    } catch (error: any) {
      setErrors({ submit: error.message || 'Failed to add position. Please try again.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle input change
  const handleInputChange = (field: keyof PortfolioCreateRequest, value: string | number) => {
    let updatedFormData = { ...formData, [field]: value };
    if (field === 'ticker' && typeof value === 'string') {
      const trimmed = value.trim().toUpperCase();
      if (trimmed.endsWith('.NS') || trimmed.endsWith('.BO')) {
        updatedFormData.region = 'IN';
      } else if (trimmed) {
        updatedFormData.region = currency === 'INR' ? 'IN' : 'US';
      }
    }
    setFormData(updatedFormData);
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: '' }));
    }
  };

  const isIndianTicker = formData.ticker.endsWith('.NS') || formData.ticker.endsWith('.BO') || formData.region === 'IN' || currency === 'INR';
  const effectiveCurrency = isIndianTicker ? 'INR' : currency;

  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-[9999] overflow-y-auto bg-gray-900 bg-opacity-75"
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl p-6 w-full max-w-lg mx-4 border border-gray-200 dark:border-gray-700"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6 pb-4 border-b border-gray-200 dark:border-gray-700">
          <div>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Add New Position</h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">Add a stock position to your portfolio</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Ticker Symbol */}
          <div>
            <label className="block text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
              Stock Ticker *
            </label>
            <input
              type="text"
              value={formData.ticker}
              onChange={(e) => handleInputChange('ticker', e.target.value.toUpperCase())}
              placeholder="e.g. MOTHERSON.NS, INFY.NS, AAPL"
              className={cn(
                "w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors text-gray-900 dark:text-white bg-white dark:bg-gray-800",
                errors.ticker ? "border-red-300 dark:border-red-600" : "border-gray-300 dark:border-gray-600"
              )}
            />
            {errors.ticker && (
              <p className="mt-2 text-sm text-red-600 dark:text-red-400">{errors.ticker}</p>
            )}
          </div>

          {/* Quantity and Buy Price Row */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Quantity */}
            <div>
              <label className="block text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
                Quantity *
              </label>
              <input
                type="number"
                value={formData.quantity || ''}
                onChange={(e) => handleInputChange('quantity', parseFloat(e.target.value) || 0)}
                placeholder="100"
                min="0"
                step="0.01"
                className={cn(
                  "w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors text-gray-900 dark:text-white bg-white dark:bg-gray-800",
                  errors.quantity ? "border-red-300 dark:border-red-600" : "border-gray-300 dark:border-gray-600"
                )}
              />
              {errors.quantity && (
                <p className="mt-2 text-sm text-red-600 dark:text-red-400">{errors.quantity}</p>
              )}
            </div>

            {/* Buy Price */}
            <div>
              <label className="block text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
                Buy Price ({effectiveCurrency}) *
              </label>
              <input
                type="number"
                value={formData.buy_price || ''}
                onChange={(e) => handleInputChange('buy_price', parseFloat(e.target.value) || 0)}
                placeholder={effectiveCurrency === 'INR' ? "100.00" : "150.00"}
                min="0"
                step="0.01"
                className={cn(
                  "w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors text-gray-900 dark:text-white bg-white dark:bg-gray-800",
                  errors.buy_price ? "border-red-300 dark:border-red-600" : "border-gray-300 dark:border-gray-600"
                )}
              />
              {errors.buy_price && (
                <p className="mt-2 text-sm text-red-600 dark:text-red-400">{errors.buy_price}</p>
              )}
            </div>
          </div>

          {/* Portfolio Weight Display */}
          <div>
            <label className="block text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
              Portfolio Weight (Auto-calculated)
            </label>
            <div className="relative">
              <input
                type="text"
                value={formData.weight > 0 ? `${(formData.weight * 100).toFixed(2)}%` : 'Auto-calculated'}
                readOnly
                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-800 text-gray-600 dark:text-gray-400 cursor-not-allowed"
              />
              <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
                <span className="text-sm text-gray-500 dark:text-gray-400">%</span>
              </div>
            </div>
            {errors.weight && (
              <p className="mt-2 text-sm text-red-600 dark:text-red-400">{errors.weight}</p>
            )}
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              Weight is automatically calculated based on position value vs total portfolio
            </p>
          </div>

          {/* Custom Name */}
          <div>
            <label className="block text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
              Custom Name (Optional)
            </label>
            <input
              type="text"
              value={formData.custom_name || ''}
              onChange={(e) => handleInputChange('custom_name', e.target.value)}
              placeholder="Apple Inc."
              className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors text-gray-900 dark:text-white bg-white dark:bg-gray-800"
            />
          </div>

          {/* Error Message */}
          {errors.submit && (
            <div className="p-4 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
              {errors.submit}
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex flex-col sm:flex-row space-y-3 sm:space-y-0 sm:space-x-4 pt-6 border-t border-gray-200 dark:border-gray-700">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-3 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex-1 flex items-center justify-center space-x-2 px-4 py-3 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isSubmitting ? (
                <Loader className="w-4 h-4 animate-spin" />
              ) : (
                <Plus className="w-4 h-4" />
              )}
              <span>{isSubmitting ? 'Adding...' : 'Add Position'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default AddPositionModalSimple;