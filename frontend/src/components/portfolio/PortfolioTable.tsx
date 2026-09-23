/**
 * Portfolio Holdings Table Component
 * Displays portfolio positions with sorting and actions
 */

'use client';

import React from 'react';
import {
  Edit,
  Trash2,
  TrendingUp,
  TrendingDown,
  ArrowUpDown,
  ArrowUp,
  ArrowDown
} from 'lucide-react';
import { PortfolioPosition, Currency } from '@/types';
import { cn, formatCurrency } from '@/lib/utils';

interface PortfolioTableProps {
  positions: PortfolioPosition[];
  currency: Currency;
  onEdit: (position: PortfolioPosition) => void;
  onDelete: (id: number, ticker: string) => void;
  onSort: (key: keyof PortfolioPosition, direction: 'asc' | 'desc') => void;
  sortConfig: { key: keyof PortfolioPosition; direction: 'asc' | 'desc' } | null;
  loading?: boolean;
}

export function PortfolioTable({
  positions,
  currency,
  onEdit,
  onDelete,
  onSort,
  sortConfig,
  loading = false
}: PortfolioTableProps) {
  // Guarded money/percent rendering — missing or non-finite values show an em dash
  const money = (amount?: number | null) =>
    amount != null && Number.isFinite(amount) ? formatCurrency(amount, currency) : '—';

  const formatPercentage = (value: number) =>
    Number.isFinite(value) ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}%` : '—';

  // Handle sort
  const handleSort = (key: keyof PortfolioPosition) => {
    const currentDirection = sortConfig?.key === key ? sortConfig.direction : null;
    const newDirection = currentDirection === 'asc' ? 'desc' : 'asc';
    onSort(key, newDirection);
  };

  // Get sort icon
  const getSortIcon = (key: keyof PortfolioPosition) => {
    if (sortConfig?.key !== key) {
      return <ArrowUpDown className="w-4 h-4 text-gray-400" />;
    }
    return sortConfig.direction === 'asc' ? 
      <ArrowUp className="w-4 h-4 text-blue-600" /> : 
      <ArrowDown className="w-4 h-4 text-blue-600" />;
  };

  // Sortable column header with accessible button + aria-sort (05-B12)
  const sortableTh = (label: string, key: keyof PortfolioPosition) => {
    const ariaSort =
      sortConfig != null && sortConfig.key === key
        ? sortConfig.direction === 'asc'
          ? 'ascending'
          : 'descending'
        : undefined;
    return (
      <th
        aria-sort={ariaSort}
        className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
      >
        <button
          type="button"
          onClick={() => handleSort(key)}
          aria-label={`Sort by ${label}`}
          className="flex items-center space-x-1 select-none w-full text-left cursor-pointer
                   text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 rounded"
        >
          <span>{label}</span>
          {getSortIcon(key)}
        </button>
      </th>
    );
  };

  if (loading) {
    return (
      <div className="p-8 text-center">
        <div className="animate-pulse space-y-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 bg-gray-200 dark:bg-gray-700 rounded" />
          ))}
        </div>
      </div>
    );
  }

  if (positions.length === 0) {
    return (
      <div className="p-8 text-center text-gray-500 dark:text-gray-400">
        <p>No portfolio positions found</p>
        <p className="text-sm mt-2">Add your first position to get started</p>
      </div>
    );
  }

  const totalPortfolioValue = positions.reduce(
    (sum, p) => sum + (p.current_value || (p.quantity * (p.last_price || 0)) || 0),
    0
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-gray-50 dark:bg-gray-800">
          <tr>
            {sortableTh('Symbol', 'ticker')}
            {sortableTh('Quantity', 'quantity')}
            {sortableTh('Avg Cost', 'buy_price')}
            {sortableTh('Current Price', 'last_price')}
            {sortableTh('Market Value', 'current_value')}
            {sortableTh('Total Cost', 'total_cost')}
            {sortableTh('P&L', 'unrealized_gain_loss')}
            {sortableTh('P&L %', 'unrealized_gain_loss_pct')}
            {sortableTh('Weight', 'weight')}
            <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
          {positions.map((position) => (
            <tr key={position.id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
              <td className="px-6 py-4 whitespace-nowrap">
                <div className="flex flex-col">
                  <div className="text-sm font-medium text-gray-900 dark:text-white">
                    {position.ticker}
                  </div>
                  {position.custom_name && (
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {position.custom_name}
                    </div>
                  )}
                </div>
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                {Number.isFinite(position.quantity) ? position.quantity.toLocaleString() : '—'}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                {money(position.buy_price)}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">
                {money(position.last_price)}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
                {money(position.current_value)}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                {money(position.total_cost)}
              </td>
              <td className="px-6 py-4 whitespace-nowrap">
                <div className="flex items-center space-x-1">
                  {position.unrealized_gain_loss >= 0 ? (
                    <TrendingUp className="w-4 h-4 text-green-500" />
                  ) : (
                    <TrendingDown className="w-4 h-4 text-red-500" />
                  )}
                  <span className={cn(
                    "text-sm font-medium",
                    position.unrealized_gain_loss >= 0 ? "text-green-600" : "text-red-600"
                  )}>
                    {money(position.unrealized_gain_loss)}
                  </span>
                </div>
              </td>
              <td className="px-6 py-4 whitespace-nowrap">
                <span className={cn(
                  "text-sm font-medium",
                  position.unrealized_gain_loss >= 0 ? "text-green-600" : "text-red-600"
                )}>
                  {formatPercentage(position.unrealized_gain_loss_pct)}
                </span>
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
                {totalPortfolioValue > 0
                  ? `${(((position.current_value || (position.quantity * (position.last_price || 0))) / totalPortfolioValue) * 100).toFixed(2)}%`
                  : `${((position.weight || 0) * 100).toFixed(2)}%`}
              </td>
              <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                <div className="flex items-center justify-end space-x-2">
                  <button
                    onClick={() => onEdit(position)}
                    aria-label={`Edit ${position.ticker}`}
                    className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
                    title="Edit position"
                  >
                    <Edit className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => onDelete(position.id, position.ticker)}
                    aria-label={`Delete ${position.ticker}`}
                    className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300"
                    title="Delete position"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default PortfolioTable;