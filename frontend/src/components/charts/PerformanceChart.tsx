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
}

export const PerformanceChart: React.FC<PerformanceChartProps> = ({
  data,
  loading = false,
  showBenchmark = false,
  className = '',
}) => {
  const formatCurrency = (value: number): string => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
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

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white dark:bg-gray-800 p-3 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg">
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
            {formatDate(label)}
          </p>
          {payload.map((entry: any, index: number) => (
            <p key={index} className="text-sm font-medium" style={{ color: entry.color }}>
              {entry.name}: {formatCurrency(entry.value)}
              {entry.data && entry.data.return && (
                <span className="text-gray-500 ml-1">
                  ({entry.data.return > 0 ? '+' : ''}{(entry.data.return * 100).toFixed(2)}%)
                </span>
              )}
            </p>
          ))}
        </div>
      );
    }
    return null;
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

  // Calculate portfolio return percentage from first to last
  const startValue = data[0]?.portfolio_value || 0;
  const endValue = data[data.length - 1]?.portfolio_value || 0;
  const totalReturn = startValue > 0 ? ((endValue - startValue) / startValue) * 100 : 0;

  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          Portfolio Performance
        </h3>
        <div className="text-right">
          <div className="text-sm text-gray-600 dark:text-gray-400">Total Return</div>
          <div className={`text-lg font-bold ${totalReturn >= 0 ? 'text-green-600' : 'text-red-600'}`}>
            {totalReturn >= 0 ? '+' : ''}{totalReturn.toFixed(2)}%
          </div>
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
            <Tooltip content={<CustomTooltip />} />
            
            {/* Reference line at 100% for normalized returns */}
            <ReferenceLine 
              y={startValue} 
              stroke="#6b7280" 
              strokeDasharray="2 2" 
              strokeOpacity={0.5}
            />
            
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

export default PerformanceChart;