/**
 * Portfolio Statistics Component
 * Displays comprehensive portfolio analytics and performance metrics
 */

'use client';

import React from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Activity,
  DollarSign,
  Percent,
  Target
} from 'lucide-react';
import { PortfolioPosition, Currency } from '@/types';
import { cn } from '@/lib/utils';

interface PortfolioStatsProps {
  positions: PortfolioPosition[];
  currency: Currency;
}

export function PortfolioStats({ positions, currency }: PortfolioStatsProps) {
  // Calculate comprehensive statistics
  const stats = React.useMemo(() => {
    if (positions.length === 0) {
      return {
        bestPerformer: null,
        worstPerformer: null,
        avgGainLoss: 0,
        portfolioConcentration: 0,
        totalGainLoss: 0,
        totalGainLossPct: 0,
        totalCost: 0,
        totalCurrentValue: 0,
        winnersCount: 0,
        losersCount: 0
      };
    }

    const totalCost = positions.reduce((sum, pos) => sum + pos.total_cost, 0);
    const totalCurrentValue = positions.reduce((sum, pos) => sum + pos.current_value, 0);
    const totalGainLoss = totalCurrentValue - totalCost;
    const totalGainLossPct = totalCost > 0 ? (totalGainLoss / totalCost) * 100 : 0;

    // Find best and worst performers
    const bestPerformer = positions.reduce((best, pos) => 
      pos.unrealized_gain_loss_pct > best.unrealized_gain_loss_pct ? pos : best
    );
    
    const worstPerformer = positions.reduce((worst, pos) => 
      pos.unrealized_gain_loss_pct < worst.unrealized_gain_loss_pct ? pos : worst
    );

    // Portfolio concentration (largest position weight)
    const portfolioConcentration = Math.max(...positions.map(pos => pos.weight * 100));

    // Winners vs Losers
    const winnersCount = positions.filter(pos => pos.unrealized_gain_loss > 0).length;
    const losersCount = positions.filter(pos => pos.unrealized_gain_loss < 0).length;

    return {
      bestPerformer,
      worstPerformer,
      avgGainLoss: positions.reduce((sum, pos) => sum + pos.unrealized_gain_loss_pct, 0) / positions.length,
      portfolioConcentration,
      totalGainLoss,
      totalGainLossPct,
      totalCost,
      totalCurrentValue,
      winnersCount,
      losersCount
    };
  }, [positions]);

  const formatCurrency = (amount: number) => {
    const symbol = currency === 'INR' ? '₹' : '$';
    return `${symbol}${Math.abs(amount).toLocaleString('en-US', { 
      minimumFractionDigits: 0, 
      maximumFractionDigits: 0 
    })}`;
  };

  const formatPercent = (value: number) => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  if (positions.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Portfolio Statistics
        </h3>
        <p className="text-gray-500 dark:text-gray-400 text-center py-8">
          Add positions to see portfolio statistics
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">
        Portfolio Statistics
      </h3>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Best Performer */}
        <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-green-800 dark:text-green-200">
                Best Performer
              </p>
              <p className="text-lg font-semibold text-green-900 dark:text-green-100">
                {stats.bestPerformer?.ticker}
              </p>
              <p className="text-sm text-green-700 dark:text-green-300">
                {formatPercent(stats.bestPerformer?.unrealized_gain_loss_pct || 0)}
              </p>
            </div>
            <TrendingUp className="h-8 w-8 text-green-600" />
          </div>
        </div>

        {/* Worst Performer */}
        <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-red-800 dark:text-red-200">
                Worst Performer
              </p>
              <p className="text-lg font-semibold text-red-900 dark:text-red-100">
                {stats.worstPerformer?.ticker}
              </p>
              <p className="text-sm text-red-700 dark:text-red-300">
                {formatPercent(stats.worstPerformer?.unrealized_gain_loss_pct || 0)}
              </p>
            </div>
            <TrendingDown className="h-8 w-8 text-red-600" />
          </div>
        </div>

        {/* Winners vs Losers */}
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
                Winners / Losers
              </p>
              <p className="text-lg font-semibold text-blue-900 dark:text-blue-100">
                {stats.winnersCount} / {stats.losersCount}
              </p>
              <p className="text-sm text-blue-700 dark:text-blue-300">
                {((stats.winnersCount / positions.length) * 100).toFixed(0)}% winners
              </p>
            </div>
            <Activity className="h-8 w-8 text-blue-600" />
          </div>
        </div>

        {/* Portfolio Concentration */}
        <div className="bg-purple-50 dark:bg-purple-900/20 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-purple-800 dark:text-purple-200">
                Largest Position
              </p>
              <p className="text-lg font-semibold text-purple-900 dark:text-purple-100">
                {stats.portfolioConcentration.toFixed(1)}%
              </p>
              <p className="text-sm text-purple-700 dark:text-purple-300">
                Concentration Risk
              </p>
            </div>
            <Target className="h-8 w-8 text-purple-600" />
          </div>
        </div>
      </div>

      {/* Additional Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
        {/* Total Cost */}
        <div className="text-center">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Total Investment
          </p>
          <p className="text-xl font-semibold text-gray-900 dark:text-white">
            {formatCurrency(stats.totalCost)}
          </p>
        </div>

        {/* Current Value */}
        <div className="text-center">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Current Value
          </p>
          <p className="text-xl font-semibold text-gray-900 dark:text-white">
            {formatCurrency(stats.totalCurrentValue)}
          </p>
        </div>

        {/* Average Gain/Loss */}
        <div className="text-center">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Average Return
          </p>
          <p className={cn(
            'text-xl font-semibold',
            stats.avgGainLoss >= 0 ? 'text-green-600' : 'text-red-600'
          )}>
            {formatPercent(stats.avgGainLoss)}
          </p>
        </div>
      </div>
    </div>
  );
}

export default PortfolioStats;