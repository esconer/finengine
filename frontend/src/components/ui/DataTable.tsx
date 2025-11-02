/**
 * DataTable component for displaying portfolio positions and data
 */

import React, { useState, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  ColumnDef,
  flexRender,
  SortingState,
} from '@tanstack/react-table';

interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T, any>[];
  loading?: boolean;
  searchable?: boolean;
  exportable?: boolean;
  searchablePlaceholder?: string;
  onSort?: (key: string, direction: 'asc' | 'desc') => void;
  onExport?: () => void;
  className?: string;
}

export function DataTable<T>({
  data,
  columns,
  loading = false,
  searchable = true,
  exportable = false,
  searchablePlaceholder = "Search...",
  onSort,
  onExport,
  className = '',
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState('');

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      globalFilter,
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 10,
      },
    },
  });

  const handleSort = (column: string, direction: 'asc' | 'desc') => {
    setSorting([{ id: column, desc: direction === 'desc' }]);
    onSort?.(column, direction);
  };

  const formatCurrency = (value: number): string => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value);
  };

  const formatPercentage = (value: number | undefined | null): string => {
    if (value === undefined || value === null || isNaN(value)) {
      return '-';
    }
    return `${(value * 100).toFixed(2)}%`;
  };

  // Default formatters for common data types
  const defaultFormatters = useMemo(() => ({
    currency: (value: any) => {
      const num = typeof value === 'string' ? parseFloat(value) : value;
      return isNaN(num) ? '-' : formatCurrency(num);
    },
    percentage: (value: any) => {
      const num = typeof value === 'string' ? parseFloat(value) : value;
      return isNaN(num) ? '-' : formatPercentage(num);
    },
    number: (value: any) => {
      const num = typeof value === 'string' ? parseFloat(value) : value;
      return isNaN(num) ? '-' : num.toLocaleString();
    },
    text: (value: any) => value || '-',
  }), []);

  if (loading) {
    return (
      <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md ${className}`}>
        <div className="p-6">
          <div className="animate-pulse space-y-4">
            {/* Search bar skeleton */}
            <div className="h-10 bg-gray-300 dark:bg-gray-600 rounded w-64"></div>
            
            {/* Table header skeleton */}
            <div className="grid grid-cols-4 gap-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-4 bg-gray-300 dark:bg-gray-600 rounded"></div>
              ))}
            </div>
            
            {/* Table rows skeleton */}
            {[...Array(5)].map((_, i) => (
              <div key={i} className="grid grid-cols-4 gap-4">
                {[...Array(4)].map((_, j) => (
                  <div key={j} className="h-4 bg-gray-200 dark:bg-gray-700 rounded"></div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700 ${className}`}>
      {/* Header with search and export */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Portfolio Positions ({data.length})
          </h3>
          
          <div className="flex items-center gap-4">
            {searchable && (
              <input
                type="text"
                placeholder={searchablePlaceholder}
                value={globalFilter ?? ''}
                onChange={(e) => setGlobalFilter(e.target.value)}
                className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md 
                         bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                         focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            )}
            
            {exportable && onExport && (
              <button
                onClick={onExport}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md 
                         transition-colors duration-200 focus:outline-none focus:ring-2 
                         focus:ring-blue-500 focus:ring-offset-2"
              >
                Export CSV
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-50 dark:bg-gray-700">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={`header-group-${headerGroup.id}`}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={`header-${header.id}-${header.column.id}`}
                    className="px-6 py-3 text-left text-xs font-medium text-gray-500
                             dark:text-gray-300 uppercase tracking-wider cursor-pointer
                             hover:bg-gray-100 dark:hover:bg-gray-600"
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    <div className="flex items-center space-x-2">
                      <span>
                        {flexRender(header.column.columnDef.header, header.getContext())}
                      </span>
                      <div className="flex flex-col">
                        <span className={`text-xs ${sorting[0]?.id === header.column.id && sorting[0]?.desc === false ? 'text-blue-600' : 'text-gray-400'}`}>
                          ↑
                        </span>
                        <span className={`text-xs ${sorting[0]?.id === header.column.id && sorting[0]?.desc === true ? 'text-blue-600' : 'text-gray-400'}`}>
                          ↓
                        </span>
                      </div>
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
            {table.getRowModel().rows.map((row, rowIndex) => (
              <tr key={`row-${row.id}-${rowIndex}`} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                {row.getVisibleCells().map((cell, cellIndex) => (
                  <td key={`cell-${cell.id}-${rowIndex}-${cellIndex}`} className="px-6 py-4 whitespace-nowrap text-sm">
                    <span className="text-gray-900 dark:text-white">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="px-6 py-3 border-t border-gray-200 dark:border-gray-700 flex items-center justify-between">
        <div className="text-sm text-gray-700 dark:text-gray-300">
          Showing {table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1} to{' '}
          {Math.min(
            (table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize,
            table.getFilteredRowModel().rows.length
          )}{' '}
          of {table.getFilteredRowModel().rows.length} results
        </div>
        
        <div className="flex items-center space-x-2">
          <button
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
            className="px-3 py-1 text-sm bg-gray-100 dark:bg-gray-600 text-gray-700 dark:text-gray-300 
                     rounded hover:bg-gray-200 dark:hover:bg-gray-500 disabled:opacity-50 
                     disabled:cursor-not-allowed"
          >
            Previous
          </button>
          
          <span className="text-sm text-gray-700 dark:text-gray-300">
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
          </span>
          
          <button
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
            className="px-3 py-1 text-sm bg-gray-100 dark:bg-gray-600 text-gray-700 dark:text-gray-300 
                     rounded hover:bg-gray-200 dark:hover:bg-gray-500 disabled:opacity-50 
                     disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

export default DataTable;