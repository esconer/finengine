/**
 * PerformanceChart component for displaying portfolio performance over time
 */

import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';

interface PerformanceData {
  date: string;
  portfolio_value: number;
  benchmark_value?: number;
  return?: number;
}

interface PerformanceChartProps {
  data: PerformanceData[];
  loading?: boolean;
  showBenchmark?: boolean;
  className?: string;
  currency?: string;
}

interface TooltipProps {
  active?: boolean;
  payload?: any[];
  label?: string;
  currency?: string;
}

const PerformanceCustomTooltip = ({ active, payload, label, currency = 'INR' }: TooltipProps) => {
  if (active && payload && payload.length) {
    const isINR = currency === 'INR';
    const formattedDate = new Date(label || '').toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
    return (
      <div className="bg-white dark:bg-gray-800 p-3 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg">
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
          {formattedDate}
        </p>
        {payload.map((entry: any, index: number) => {
          const formattedVal = new Intl.NumberFormat(isINR ? 'en-IN' : 'en-US', {
            style: 'currency',
            currency: currency || 'INR',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
          }).format(entry.value);
          return (
            <p key={index} className="text-sm font-medium" style={{ color: entry.color }}>
              {entry.name}: {formattedVal}
              {entry.data && entry.data.return && (
                <span className="text-gray-500 ml-1">
                  ({entry.data.return > 0 ? '+' : ''}{(entry.data.return * 100).toFixed(2)}%)
                </span>
              )}
            </p>
          );
        })}
      </div>
    );
  }
  return null;
};

const PerformanceChartImpl: React.FC<PerformanceChartProps> = ({
  data,
  loading = false,
  showBenchmark = false,
  className = '',
  currency = 'INR',
}) => {
  const formatCurrency = (value: number): string => {
    const isINR = currency === 'INR';
    return new Intl.NumberFormat(isINR ? 'en-IN' : 'en-US', {
      style: 'currency',
      currency: currency || 'INR',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  const formatDate = (dateStr: string): string => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
  };

  if (loading) {
    return (
      <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 ${className}`}>
        <div className="animate-pulse">
          <div className="h-6 bg-gray-300 dark:bg-gray-600 rounded w-48 mb-4"></div>
          <div className="h-64 bg-gray-200 dark:bg-gray-700 rounded"></div>
        </div>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 ${className}`}>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Portfolio Performance
        </h3>
        <div className="h-64 flex items-center justify-center">
          <p className="text-gray-500 dark:text-gray-400">No performance data available</p>
        </div>
      </div>
    );
  }

  // Total return is a RATIO, and a ratio needs both terms. An absent first
  // reading used to be absorbed by `data[0]?.portfolio_value || 0`, which then
  // satisfied `startValue > 0 ? … : 0` and published 0 — rendered green by
  // `totalReturn >= 0` below. That is "no change" asserted about a portfolio
  // that was never measured, and a fabricated 0 is indistinguishable from a real
  // one. So the return is withheld unless it is computable, and the absence is
  // rendered uncoloured: green would still read as "no change", red as "loss".
  // House pattern: the same hasCompleteWindow gate at realized-risk/page.tsx.
  const rawStart = data[0]?.portfolio_value;
  const rawEnd = data[data.length - 1]?.portfolio_value;
  const startValue =
    typeof rawStart === 'number' && Number.isFinite(rawStart) ? rawStart : null;
  const endValue =
    typeof rawEnd === 'number' && Number.isFinite(rawEnd) ? rawEnd : null;
  // A MEASURED start of 0 is not a starting point: the ratio is undefined, so
  // it is absent for the same reason an absent start is. The distinction that
  // matters downstream is start present + end present — a genuinely flat window
  // is a real 0.00% and still renders green.
  const totalReturn =
    startValue !== null && startValue > 0 && endValue !== null
      ? ((endValue - startValue) / startValue) * 100
      : null;

  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          Portfolio Performance
        </h3>
        <div className="text-right">
          <div className="text-sm text-gray-600 dark:text-gray-400">Total Return</div>
          {totalReturn === null ? (
            <div
              className="text-lg font-bold text-gray-400 dark:text-gray-500"
              title="Total return needs a recorded portfolio value at both ends of the window"
            >
              N/A
            </div>
          ) : (
            <div className={`text-lg font-bold ${totalReturn >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              {totalReturn >= 0 ? '+' : ''}{totalReturn.toFixed(2)}%
            </div>
          )}
        </div>
      </div>
      
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
            <XAxis
              dataKey="date"
              tickFormatter={formatDate}
              className="text-gray-600 dark:text-gray-400"
              fontSize={12}
            />
            <YAxis
              tickFormatter={formatCurrency}
              className="text-gray-600 dark:text-gray-400"
              fontSize={12}
            />
            <Tooltip content={<PerformanceCustomTooltip currency={currency} />} />
            
            {/* Reference line at the starting value. Suppressed when there is no
                measured start: drawn at a fabricated 0 it would assert a
                baseline the data never had. */}
            {startValue !== null && (
              <ReferenceLine
                y={startValue}
                stroke="#6b7280"
                strokeDasharray="2 2"
                strokeOpacity={0.5}
              />
            )}
            
            <Line
              type="monotone"
              dataKey="portfolio_value"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              name="Portfolio"
            />
            
            {showBenchmark && data[0]?.benchmark_value && (
              <Line
                type="monotone"
                dataKey="benchmark_value"
                stroke="#10b981"
                strokeWidth={2}
                strokeDasharray="5 5"
                dot={false}
                name="Benchmark"
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export const PerformanceChart = React.memo(PerformanceChartImpl);

export default PerformanceChart;