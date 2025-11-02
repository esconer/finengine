/**
 * Portfolio Filters Component
 * Search and filter portfolio positions
 */

'use client';

import React from 'react';
import { Search, Filter, X } from 'lucide-react';
import { cn } from '@/lib/utils';

interface PortfolioFiltersProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  sectorFilter: string;
  onSectorChange: (sector: string) => void;
  sectors: string[];
  className?: string;
}

export function PortfolioFilters({
  searchQuery,
  onSearchChange,
  sectorFilter,
  onSectorChange,
  sectors,
  className
}: PortfolioFiltersProps) {
  return (
    <div className={cn("bg-white dark:bg-gray-900 rounded-lg shadow p-6", className)}>
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between space-y-4 lg:space-y-0 lg:space-x-4">
        {/* Search Input */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
          <input
            type="text"
            placeholder="Search by ticker, name, or sector..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400"
          />
          {searchQuery && (
            <button
              onClick={() => onSearchChange('')}
              className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Sector Filter */}
        <div className="flex items-center space-x-2">
          <Filter className="w-4 h-4 text-gray-500 dark:text-gray-400" />
          <select
            value={sectorFilter}
            onChange={(e) => onSectorChange(e.target.value)}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
          >
            <option value="">All Sectors</option>
            {sectors.map((sector) => (
              <option key={sector} value={sector}>
                {sector}
              </option>
            ))}
          </select>
          
          {/* Clear Filters */}
          {(searchQuery || sectorFilter) && (
            <button
              onClick={() => {
                onSearchChange('');
                onSectorChange('');
              }}
              className="flex items-center space-x-1 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              <X className="w-4 h-4" />
              <span>Clear</span>
            </button>
          )}
        </div>
      </div>

      {/* Active Filters Display */}
      {(searchQuery || sectorFilter) && (
        <div className="mt-4 flex flex-wrap gap-2">
          {searchQuery && (
            <div className="flex items-center space-x-1 px-3 py-1 bg-blue-100 dark:bg-blue-900/20 text-blue-800 dark:text-blue-300 rounded-full text-sm">
              <span>Search: "{searchQuery}"</span>
              <button
                onClick={() => onSearchChange('')}
                className="hover:text-blue-900 dark:hover:text-blue-200"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
          
          {sectorFilter && (
            <div className="flex items-center space-x-1 px-3 py-1 bg-green-100 dark:bg-green-900/20 text-green-800 dark:text-green-300 rounded-full text-sm">
              <span>Sector: {sectorFilter}</span>
              <button
                onClick={() => onSectorChange('')}
                className="hover:text-green-900 dark:hover:text-green-200"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default PortfolioFilters;