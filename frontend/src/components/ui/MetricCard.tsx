/**
 * MetricCard component for displaying key portfolio metrics
 */

import React from 'react';
import { LucideIcon } from 'lucide-react';

export interface MetricCardProps {
  title: string;
  value: number | string;
  change?: number;
  changeType?: 'positive' | 'negative' | 'neutral';
  icon?: LucideIcon;
  loading?: boolean;
  className?: string;
  prefix?: string;
  suffix?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  change,
  icon: Icon,
  loading = false,
  className = '',
  prefix,
  suffix = '',
}) => {
  const formatValue = (val: number | string): string => {
    if (typeof val === 'number') {
      if (!Number.isFinite(val)) {
        return 'N/A';
      }
      if (prefix === undefined) {
        return `${val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${suffix}`;
      }
      const sign = val < 0 ? '-' : '';
      const abs = Math.abs(val);
      let numStr: string;
      if (prefix === '₹') {
        numStr =
          abs >= 10000000
            ? `${sign}₹${(abs / 10000000).toFixed(2)}Cr`
            : abs >= 100000
            ? `${sign}₹${(abs / 100000).toFixed(2)}L`
            : `${sign}₹${abs.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      } else {
        numStr =
          abs >= 1000000
            ? `${sign}${prefix}${(abs / 1000000).toFixed(1)}M`
            : abs >= 1000
            ? `${sign}${prefix}${(abs / 1000).toFixed(1)}K`
            : `${sign}${prefix}${abs.toFixed(2)}`;
      }
      return `${numStr}${suffix}`;
    }
    if (!val || val === 'NaN%') {
      return 'N/A';
    }
    return `${val}${suffix}`;
  };

  const formatChange = (val: number): string => {
    const sign = val >= 0 ? '+' : '';
    return `${sign}${val.toFixed(2)}%`;
  };

  const getChangeColor = (type: string): string => {
    switch (type) {
      case 'positive':
        return 'text-green-600 dark:text-green-400';
      case 'negative':
        return 'text-red-600 dark:text-red-400';
      default:
        return 'text-gray-600 dark:text-gray-400';
    }
  };

  const getChangeBgColor = (type: string): string => {
    switch (type) {
      case 'positive':
        return 'bg-green-100 dark:bg-green-900/20';
      case 'negative':
        return 'bg-red-100 dark:bg-red-900/20';
      default:
        return 'bg-gray-100 dark:bg-gray-800';
    }
  };

  if (loading) {
    return (
      <div
        data-testid="metric-card"
        className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 ${className}`}
      >
        <div className="animate-pulse">
          <div className="flex items-center justify-between mb-4">
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-24"></div>
            <div className="h-6 w-6 bg-gray-300 dark:bg-gray-600 rounded"></div>
          </div>
          <div className="h-8 bg-gray-300 dark:bg-gray-600 rounded w-32 mb-2"></div>
          <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-16"></div>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="metric-card"
      className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 ${className}`}
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400">{title}</h3>
        {Icon && (
          <Icon className="h-5 w-5 text-gray-500 dark:text-gray-400" />
        )}
      </div>
      
      <div className="space-y-2">
        <p className="text-2xl font-bold text-gray-900 dark:text-white">
          {formatValue(value)}
        </p>
        
        {change !== undefined && Number.isFinite(change) && (
          <div className="flex items-center">
            <span
              className={`text-sm px-2 py-1 rounded-full font-medium ${getChangeBgColor(
                change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral'
              )} ${getChangeColor(change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral')}`}
            >
              {formatChange(change)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

export default MetricCard;