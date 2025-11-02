/**
 * Currency Selector Component
 * Toggle between USD and INR currencies
 */

'use client';

import React from 'react';
import { DollarSign, IndianRupee } from 'lucide-react';
import { Currency } from '@/types';
import { cn } from '@/lib/utils';

interface CurrencySelectorProps {
  selectedCurrency: Currency;
  onCurrencyChange: (currency: Currency) => void;
  className?: string;
}

const currencies: { code: Currency; name: string; symbol: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { code: 'USD', name: 'US Dollar', symbol: '$', icon: DollarSign },
  { code: 'INR', name: 'Indian Rupee', symbol: '₹', icon: IndianRupee },
];

export function CurrencySelector({ selectedCurrency, onCurrencyChange, className }: CurrencySelectorProps) {
  return (
    <div className={cn("flex items-center space-x-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-1", className)}>
      {currencies.map((currency) => {
        const Icon = currency.icon;
        const isSelected = selectedCurrency === currency.code;
        
        return (
          <button
            key={currency.code}
            onClick={() => onCurrencyChange(currency.code)}
            className={cn(
              "flex items-center space-x-2 px-3 py-2 rounded-md text-sm font-medium transition-all duration-200",
              isSelected
                ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm"
                : "text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-200 dark:hover:bg-gray-700"
            )}
            title={currency.name}
          >
            <Icon className="w-4 h-4" />
            <span className="hidden sm:inline">{currency.symbol} {currency.code}</span>
            <span className="sm:hidden">{currency.symbol}</span>
          </button>
        );
      })}
    </div>
  );
}

export default CurrencySelector;