/**
 * Enhanced Add Position Modal Component - Fixed Visibility Issues
 * Complete form for adding new portfolio positions with real-time market data
 */

'use client';

import React, { useState, useEffect } from 'react';
import { X, Plus, Search, Loader, TrendingUp, DollarSign, CheckCircle, AlertCircle } from 'lucide-react';
import { PortfolioCreateRequest, Currency } from '@/types';
import { cn } from '@/lib/utils';

interface MarketData {
  current_price: number;
  sector: string;
  industry: string;
  is_valid: boolean;
}

interface AddPositionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAdd: (position: PortfolioCreateRequest) => Promise<void>;
  currency: Currency;
}

export function AddPositionModal({ isOpen, onClose, onAdd, currency }: AddPositionModalProps) {
  const [formData, setFormData] = useState<PortfolioCreateRequest>({
    ticker: '',
    weight: 0,
    quantity: 0,
    buy_price: 0,
    region: 'US',
    custom_name: ''
  });
  const [marketData, setMarketData] = useState<MarketData | null>(null);
  const [isValidatingTicker, setIsValidatingTicker] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [existingPositions, setExistingPositions] = useState<any[]>([]);
  const [isLoadingExisting, setIsLoadingExisting] = useState(false);

  // Fetch existing positions when modal opens
  React.useEffect(() => {
    if (isOpen) {
      fetchExistingPositions();
    }
  }, [isOpen]);

  const fetchExistingPositions = async () => {
    setIsLoadingExisting(true);
    try {
      const response = await fetch(`http://localhost:8000/api/v1/portfolio`);
      if (response.ok) {
        const data = await response.json();
        setExistingPositions(data.positions || []);
      }
    } catch (error) {
      console.error('Failed to fetch existing positions:', error);
    } finally {
      setIsLoadingExisting(false);
    }
  };

  // Reset form when modal opens
  React.useEffect(() => {
    if (isOpen) {
      setFormData({
        ticker: '',
        weight: 0,
        quantity: 0,
        buy_price: 0,
        region: 'US',
        custom_name: ''
      });
      setMarketData(null);
      setErrors({});
    }
  }, [isOpen]);

  // Validate ticker and fetch market data
  const validateTicker = async (ticker: string) => {
    if (!ticker || ticker.length < 1) {
      setMarketData(null);
      return;
    }

    setIsValidatingTicker(true);
    try {
      // Use quote endpoint for current market data (most reliable)
      const quoteResponse = await fetch(`http://localhost:8000/api/v1/data/quote/${ticker.toUpperCase()}`);
      if (quoteResponse.ok) {
        const quoteData = await quoteResponse.json();
        if (quoteData && quoteData.current_price) {
          setMarketData({
            current_price: quoteData.current_price,
            sector: quoteData.sector || 'Technology',
            industry: quoteData.industry || 'General',
            is_valid: true
          });
          // Auto-fill buy price with current market price if buy price is empty
          if (formData.buy_price === 0) {
            setFormData(prev => ({ ...prev, buy_price: quoteData.current_price }));
          }
          setIsValidatingTicker(false);
          return;
        }
      }

      // Fallback: Try historical data endpoint if quote fails
      const response = await fetch(`http://localhost:8000/api/v1/data/${ticker.toUpperCase()}`);
      if (response.ok) {
        const data = await response.json();
        const latestPrice = data.data?.[data.data.length - 1]?.close;
        if (latestPrice) {
          setMarketData({
            current_price: latestPrice,
            sector: 'Technology', // Default sector
            industry: 'General',
            is_valid: true
          });
          // Auto-fill buy price with current market price if buy price is empty
          if (formData.buy_price === 0) {
            setFormData(prev => ({ ...prev, buy_price: latestPrice }));
          }
          setIsValidatingTicker(false);
          return;
        }
      }

      // If both fail, mark as invalid
      setMarketData({
        current_price: 0,
        sector: 'Unknown',
        industry: 'Unknown',
        is_valid: false
      });
    } catch (error) {
      console.error('Failed to validate ticker:', error);
      setMarketData({
        current_price: 0,
        sector: 'Unknown',
        industry: 'Unknown',
        is_valid: false
      });
    } finally {
      setIsValidatingTicker(false);
    }
  };

  // Auto-calculate weight when quantity or buy price changes
  useEffect(() => {
    if (formData.quantity > 0 && formData.buy_price > 0 && marketData?.current_price) {
      const estimatedTotalCost = formData.quantity * formData.buy_price;
      const estimatedMarketValue = formData.quantity * marketData.current_price;
      const estimatedWeight = estimatedMarketValue / (estimatedMarketValue + 100000); // Assume base portfolio value
      setFormData(prev => ({ ...prev, weight: Math.min(estimatedWeight, 0.5) })); // Cap at 50%
    }
  }, [formData.quantity, formData.buy_price, marketData?.current_price]);

  // Check for duplicate ticker
  const checkForDuplicate = () => {
    if (formData.ticker && existingPositions.length > 0) {
      const existingPosition = existingPositions.find(
        pos => pos.ticker.toUpperCase() === formData.ticker.toUpperCase()
      );
      if (existingPosition) {
        setErrors({
          ticker: `Ticker "${formData.ticker}" already exists in your portfolio`
        });
        return true;
      }
    }
    return false;
  };

  // Validate ticker when it changes
  useEffect(() => {
    if (formData.ticker.length >= 1) {
      // First check for duplicates
      if (checkForDuplicate()) {
        return;
      }
      
      // Then validate with market data
      const timeoutId = setTimeout(() => validateTicker(formData.ticker), 500);
      return () => clearTimeout(timeoutId);
    } else {
      setMarketData(null);
      setErrors({});
    }
  }, [formData.ticker, existingPositions]);

  // Validate form
  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!formData.ticker.trim()) {
      newErrors.ticker = 'Ticker symbol is required';
    } else if (!/^[A-Za-z]{1,10}(\.[A-Za-z]{1,5})?$/.test(formData.ticker.trim())) {
      newErrors.ticker = 'Invalid ticker symbol format';
    } else if (marketData && !marketData.is_valid) {
      newErrors.ticker = 'Ticker not found or invalid';
    }

    if (formData.weight <= 0 || formData.weight > 1) {
      newErrors.weight = 'Weight must be between 0 and 1';
    }

    if (formData.quantity <= 0) {
      newErrors.quantity = 'Quantity must be greater than 0';
    }

    if (formData.buy_price <= 0) {
      newErrors.buy_price = 'Buy price must be greater than 0';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!validateForm()) return;

    try {
      setIsSubmitting(true);
      setErrors({}); // Clear any previous errors
      
      console.log('🔄 Modal: Submitting position data:', formData);
      await onAdd(formData);
      console.log('✅ Modal: Position added successfully');
      onClose();
    } catch (error: any) {
      console.error('❌ Modal: Failed to add position:', error);
      
      // Handle specific error types
      const errorMessage = error.message || 'Failed to add position. Please try again.';
      
      // Parse validation errors from backend
      if (errorMessage.includes('validation') || errorMessage.includes('validation failed')) {
        // Handle field-specific validation errors
        const fieldErrors: Record<string, string> = {};
        
        if (errorMessage.includes('weight')) {
          fieldErrors.weight = 'Weight must be between 0 and 1';
        }
        if (errorMessage.includes('quantity')) {
          fieldErrors.quantity = 'Quantity must be greater than 0';
        }
        if (errorMessage.includes('buy_price')) {
          fieldErrors.buy_price = 'Buy price must be greater than 0';
        }
        if (errorMessage.includes('ticker')) {
          fieldErrors.ticker = 'Invalid ticker symbol';
        }
        
        setErrors(fieldErrors);
      } else if (errorMessage.includes('already exists') || errorMessage.includes('duplicate')) {
        // Enhanced duplicate ticker handling
        setErrors({ 
          ticker: `Ticker "${formData.ticker}" already exists in your portfolio` 
        });
      } else if (errorMessage.includes('not valid') || errorMessage.includes('does not exist')) {
        setErrors({ ticker: 'Ticker not found or invalid' });
      } else if (errorMessage.includes('409') || errorMessage.includes('Conflict')) {
        // Handle 409 Conflict specifically
        setErrors({ 
          ticker: `Ticker "${formData.ticker}" already exists in your portfolio` 
        });
      } else {
        setErrors({ submit: errorMessage });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle input change
  const handleInputChange = (field: keyof PortfolioCreateRequest, value: string | number) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: '' }));
    }
  };

  // Calculate estimated values
  const estimatedTotalCost = formData.quantity * formData.buy_price;
  const estimatedMarketValue = formData.quantity * (marketData?.current_price || 0);
  const estimatedGainLoss = estimatedMarketValue - estimatedTotalCost;
  const estimatedGainLossPct = estimatedTotalCost > 0 ? (estimatedGainLoss / estimatedTotalCost) * 100 : 0;

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[9999] overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-4 text-center sm:block sm:p-0">
        {/* Overlay */}
        <div
          className="fixed inset-0 transition-opacity bg-gray-900 bg-opacity-75"
          onClick={onClose}
        />

        {/* Modal Container */}
        <div className="inline-block w-full max-w-2xl max-h-[90vh] my-4 text-left align-middle transition-all transform bg-white dark:bg-gray-900 shadow-xl rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          {/* Sticky Header */}
          <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 sticky top-0 z-10">
            <div>
              <h3 className="text-xl font-semibold leading-6 text-gray-900 dark:text-white">
                Add Portfolio Position
              </h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Add a new stock position to your portfolio
              </p>
            </div>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors flex-shrink-0"
            >
              <X className="w-6 h-6" />
            </button>
          </div>

          {/* Scrollable Form Container */}
          <div className="overflow-y-auto max-h-[calc(90vh-140px)] p-6">
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Ticker Symbol */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Ticker Symbol *
                </label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                  <input
                    type="text"
                    value={formData.ticker}
                    onChange={(e) => handleInputChange('ticker', e.target.value.toUpperCase())}
                    placeholder="AAPL or AAPL.NS"
                    className={cn(
                      "w-full pl-10 pr-12 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 transition-colors",
                      errors.ticker ? "border-red-300 dark:border-red-600" : "border-gray-300 dark:border-gray-600"
                    )}
                  />
                  {isValidatingTicker && (
                    <Loader className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4 animate-spin" />
                  )}
                  {marketData?.is_valid && !isValidatingTicker && (
                    <CheckCircle className="absolute right-3 top-1/2 transform -translate-y-1/2 text-green-500 w-4 h-4" />
                  )}
                  {marketData?.is_valid === false && !isValidatingTicker && (
                    <AlertCircle className="absolute right-3 top-1/2 transform -translate-y-1/2 text-red-500 w-4 h-4" />
                  )}
                </div>
                {errors.ticker && (
                  <p className="mt-2 text-sm text-red-600 dark:text-red-400">{errors.ticker}</p>
                )}
                {marketData?.is_valid && marketData.current_price > 0 && (
                  <p className="mt-2 text-sm text-green-600 dark:text-green-400 flex items-center space-x-2">
                    <TrendingUp className="w-4 h-4" />
                    <span>Market Price: {currency} {marketData.current_price.toFixed(2)}</span>
                  </p>
                )}
              </div>

              {/* Market Data Display */}
              {marketData?.is_valid && (
                <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                  <div className="flex items-center space-x-2 text-sm">
                    <DollarSign className="w-4 h-4 text-blue-600" />
                    <span className="text-blue-800 dark:text-blue-200">
                      {marketData.sector} • {marketData.industry}
                    </span>
                  </div>
                </div>
              )}

              {/* Existing Position Warning */}
              {formData.ticker && (() => {
                const existingPosition = existingPositions.find(
                  pos => pos.ticker.toUpperCase() === formData.ticker.toUpperCase()
                );
                return existingPosition ? (
                  <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4">
                    <div className="flex items-start space-x-2">
                      <AlertCircle className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" />
                      <div>
                        <h4 className="text-sm font-medium text-amber-800 dark:text-amber-200">
                          Ticker already exists
                        </h4>
                        <div className="mt-1 text-sm text-amber-700 dark:text-amber-300">
                          <p>Current position details:</p>
                          <ul className="mt-1 space-y-1">
                            <li>• Quantity: {existingPosition.quantity}</li>
                            <li>• Buy Price: {currency} {existingPosition.buy_price?.toFixed(2)}</li>
                            <li>• Weight: {(existingPosition.weight * 100).toFixed(1)}%</li>
                          </ul>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : null;
              })()}

              {/* Quantity and Buy Price Row */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Quantity */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
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
                      "w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 transition-colors",
                      errors.quantity ? "border-red-300 dark:border-red-600" : "border-gray-300 dark:border-gray-600"
                    )}
                  />
                  {errors.quantity && (
                    <p className="mt-2 text-sm text-red-600 dark:text-red-400">{errors.quantity}</p>
                  )}
                </div>

                {/* Buy Price */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Avg Buy Price * ({currency})
                  </label>
                  <input
                    type="number"
                    value={formData.buy_price || ''}
                    onChange={(e) => handleInputChange('buy_price', parseFloat(e.target.value) || 0)}
                    placeholder="150.00"
                    min="0"
                    step="0.01"
                    className={cn(
                      "w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 transition-colors",
                      errors.buy_price ? "border-red-300 dark:border-red-600" : "border-gray-300 dark:border-gray-600"
                    )}
                  />
                  {errors.buy_price && (
                    <p className="mt-2 text-sm text-red-600 dark:text-red-400">{errors.buy_price}</p>
                  )}
                </div>
              </div>

              {/* Portfolio Weight */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Portfolio Weight *
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
                    "w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 transition-colors",
                    errors.weight ? "border-red-300 dark:border-red-600" : "border-gray-300 dark:border-gray-600"
                  )}
                />
                <div className="flex items-center justify-between mt-2">
                  {errors.weight ? (
                    <p className="text-sm text-red-600 dark:text-red-400">{errors.weight}</p>
                  ) : (
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      Enter as decimal (0.15 = 15%)
                    </p>
                  )}
                  {formData.weight > 0 && (
                    <p className="text-sm text-blue-600 dark:text-blue-400 font-medium">
                      {(formData.weight * 100).toFixed(1)}%
                    </p>
                  )}
                </div>
              </div>

              {/* Custom Name */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Custom Name (Optional)
                </label>
                <input
                  type="text"
                  value={formData.custom_name || ''}
                  onChange={(e) => handleInputChange('custom_name', e.target.value)}
                  placeholder="Apple Inc."
                  className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400 transition-colors"
                />
              </div>

              {/* Estimated Values Display */}
              {formData.quantity > 0 && formData.buy_price > 0 && marketData?.is_valid && (
                <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 space-y-3">
                  <h4 className="text-sm font-medium text-gray-900 dark:text-white">Estimated Values</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                    <div>
                      <span className="text-gray-600 dark:text-gray-400">Total Cost:</span>
                      <span className="ml-2 font-medium text-gray-900 dark:text-white">
                        {currency} {estimatedTotalCost.toLocaleString()}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-600 dark:text-gray-400">Market Value:</span>
                      <span className="ml-2 font-medium text-gray-900 dark:text-white">
                        {currency} {estimatedMarketValue.toLocaleString()}
                      </span>
                    </div>
                    <div className="col-span-1 md:col-span-2">
                      <span className="text-gray-600 dark:text-gray-400">Est. Gain/Loss:</span>
                      <span className={cn(
                        "ml-2 font-medium",
                        estimatedGainLoss >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
                      )}>
                        {estimatedGainLoss >= 0 ? '+' : ''}{currency} {estimatedGainLoss.toLocaleString()}
                        ({estimatedGainLossPct >= 0 ? '+' : ''}{estimatedGainLossPct.toFixed(2)}%)
                      </span>
                    </div>
                  </div>
                </div>
              )}

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
                  disabled={isSubmitting || isValidatingTicker || !marketData?.is_valid}
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
      </div>
    </div>
  );
}

export default AddPositionModal;