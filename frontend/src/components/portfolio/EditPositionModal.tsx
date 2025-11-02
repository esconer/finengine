/**
 * Edit Position Modal Component
 * Form for editing existing portfolio positions
 */

'use client';

import React, { useState, useEffect } from 'react';
import { X, Save, Loader } from 'lucide-react';
import { PortfolioPosition, PortfolioUpdateRequest, Currency } from '@/types';
import { cn } from '@/lib/utils';

interface EditPositionModalProps {
  isOpen: boolean;
  position: PortfolioPosition | null;
  onClose: () => void;
  onUpdate: (id: number, updates: PortfolioUpdateRequest) => Promise<void>;
  currency: Currency;
}

export function EditPositionModal({ isOpen, position, onClose, onUpdate, currency }: EditPositionModalProps) {
  const [formData, setFormData] = useState<PortfolioUpdateRequest>({
    weight: 0,
    quantity: 0,
    buy_price: 0,
    custom_name: ''
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Initialize form data when position changes
  useEffect(() => {
    if (position && isOpen) {
      setFormData({
        weight: position.weight,
        quantity: position.quantity,
        buy_price: position.buy_price,
        custom_name: position.custom_name || ''
      });
      setErrors({});
    }
  }, [position, isOpen]);

  // Validate form
  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (formData.weight !== undefined && (formData.weight <= 0 || formData.weight > 1)) {
      newErrors.weight = 'Weight must be between 0 and 1';
    }

    if (formData.quantity !== undefined && formData.quantity <= 0) {
      newErrors.quantity = 'Quantity must be greater than 0';
    }

    if (formData.buy_price !== undefined && formData.buy_price <= 0) {
      newErrors.buy_price = 'Buy price must be greater than 0';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!position || !validateForm()) return;

    try {
      setIsSubmitting(true);
      // Only include fields that have been changed
      const updates: PortfolioUpdateRequest = {};
      if (formData.weight !== undefined && formData.weight !== position.weight) {
        updates.weight = formData.weight;
      }
      if (formData.quantity !== undefined && formData.quantity !== position.quantity) {
        updates.quantity = formData.quantity;
      }
      if (formData.buy_price !== undefined && formData.buy_price !== position.buy_price) {
        updates.buy_price = formData.buy_price;
      }
      if (formData.custom_name !== undefined && formData.custom_name !== position.custom_name) {
        updates.custom_name = formData.custom_name;
      }

      await onUpdate(position.id, updates);
    } catch (error) {
      console.error('Failed to update position:', error);
      setErrors({ submit: 'Failed to update position. Please try again.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle input change
  const handleInputChange = (field: keyof PortfolioUpdateRequest, value: string | number) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: '' }));
    }
  };

  if (!isOpen || !position) return null;

  // Calculate current metrics
  const currentValue = position.current_value;
  const totalCost = position.total_cost;
  const unrealizedGainLoss = position.unrealized_gain_loss;
  const unrealizedGainLossPct = position.unrealized_gain_loss_pct;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
        {/* Overlay */}
        <div 
          className="fixed inset-0 transition-opacity bg-gray-500 bg-opacity-75"
          onClick={onClose}
        />

        {/* Modal */}
        <div className="inline-block w-full max-w-lg p-6 my-8 overflow-hidden text-left align-middle transition-all transform bg-white dark:bg-gray-900 shadow-xl rounded-lg">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-medium leading-6 text-gray-900 dark:text-white">
                Edit Position
              </h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                {position.ticker} - {position.custom_name || 'No custom name'}
              </p>
            </div>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Current Position Info */}
          <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 mb-6">
            <h4 className="text-sm font-medium text-gray-900 dark:text-white mb-3">Current Position</h4>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500 dark:text-gray-400">Quantity:</span>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">
                  {position.quantity.toLocaleString()}
                </span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Avg Cost:</span>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">
                  {currency === 'INR' ? '₹' : '$'}{position.buy_price.toFixed(2)}
                </span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Current Value:</span>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">
                  {currency === 'INR' ? '₹' : '$'}{currentValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">P&L:</span>
                <span className={cn(
                  "ml-2 font-medium",
                  unrealizedGainLoss >= 0 ? "text-green-600" : "text-red-600"
                )}>
                  {unrealizedGainLoss >= 0 ? '+' : ''}
                  {currency === 'INR' ? '₹' : '$'}{unrealizedGainLoss.toFixed(2)} 
                  ({unrealizedGainLossPct.toFixed(2)}%)
                </span>
              </div>
            </div>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Portfolio Weight */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Portfolio Weight
              </label>
              <input
                type="number"
                value={formData.weight || ''}
                onChange={(e) => handleInputChange('weight', parseFloat(e.target.value) || 0)}
                placeholder="0.15"
                min="0"
                max="1"
                step="0.01"
                className={cn(
                  "w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400",
                  errors.weight ? "border-red-300" : "border-gray-300 dark:border-gray-600"
                )}
              />
              {errors.weight && (
                <p className="mt-1 text-sm text-red-600">{errors.weight}</p>
              )}
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Current: {(position.weight * 100).toFixed(2)}% | Enter as decimal (0.15 = 15%)
              </p>
            </div>

            {/* Quantity */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Quantity
              </label>
              <input
                type="number"
                value={formData.quantity || ''}
                onChange={(e) => handleInputChange('quantity', parseFloat(e.target.value) || 0)}
                placeholder="100"
                min="0"
                step="0.01"
                className={cn(
                  "w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400",
                  errors.quantity ? "border-red-300" : "border-gray-300 dark:border-gray-600"
                )}
              />
              {errors.quantity && (
                <p className="mt-1 text-sm text-red-600">{errors.quantity}</p>
              )}
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Current: {position.quantity.toLocaleString()} shares
              </p>
            </div>

            {/* Buy Price */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Average Buy Price ({currency})
              </label>
              <input
                type="number"
                value={formData.buy_price || ''}
                onChange={(e) => handleInputChange('buy_price', parseFloat(e.target.value) || 0)}
                placeholder="150.00"
                min="0"
                step="0.01"
                className={cn(
                  "w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400",
                  errors.buy_price ? "border-red-300" : "border-gray-300 dark:border-gray-600"
                )}
              />
              {errors.buy_price && (
                <p className="mt-1 text-sm text-red-600">{errors.buy_price}</p>
              )}
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Current: {currency === 'INR' ? '₹' : '$'}{position.buy_price.toFixed(2)}
              </p>
            </div>

            {/* Custom Name */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Custom Name
              </label>
              <input
                type="text"
                value={formData.custom_name || ''}
                onChange={(e) => handleInputChange('custom_name', e.target.value)}
                placeholder="Apple Inc."
                className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400"
              />
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Current: {position.custom_name || 'None'}
              </p>
            </div>

            {/* Error Message */}
            {errors.submit && (
              <div className="p-3 text-sm text-red-600 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
                {errors.submit}
              </div>
            )}

            {/* Actions */}
            <div className="flex space-x-3 pt-4">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="flex-1 flex items-center justify-center space-x-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? (
                  <Loader className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                <span>{isSubmitting ? 'Updating...' : 'Update Position'}</span>
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export default EditPositionModal;