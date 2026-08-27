/**
 * SectorAllocationChart component for displaying portfolio sector allocation
 */

import React from 'react';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  Legend,
} from 'recharts';

interface SectorData {
  name: string;
  value: number;
  percentage: number;
  color?: string;
}

interface SectorAllocationChartProps {
  data: SectorData[];
  loading?: boolean;
  className?: string;
}

// Color palette for different sectors
const COLORS = [
  '#3b82f6', // Blue
  '#10b981', // Green
  '#f59e0b', // Yellow
  '#ef4444', // Red
  '#8b5cf6', // Purple
  '#06b6d4', // Cyan
  '#84cc16', // Lime
  '#f97316', // Orange
  '#ec4899', // Pink
  '#6b7280', // Gray
];

export const SectorAllocationChart: React.FC<SectorAllocationChartProps> = ({
  data,
  loading = false,
  className = '',
}) => {
  // Assign colors to sectors
  const dataWithColors = data.map((item, index) => ({
    ...item,
    color: COLORS[index % COLORS.length],
  }));

  const formatPercentage = (value: number): string => {
    return `${(value * 100).toFixed(1)}%`;
  };

  const formatValue = (value: number): string => {
    return value.toFixed(2);
  };

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-white dark:bg-gray-800 p-3 border border-gray-200 dark:border-gray-600 rounded-lg shadow-lg">
          <p className="text-sm font-medium text-gray-900 dark:text-white">
            {data.name}
          </p>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Allocation: {formatValue(data.percentage * 100)}%
          </p>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Weight: {formatValue(data.value)}
          </p>
        </div>
      );
    }
    return null;
  };

  const CustomLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percentage }: any) => {
    if (percentage < 0.05) return null; // Hide labels for slices smaller than 5%
    
    const RADIAN = Math.PI / 180;
    const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
    const x = cx + radius * Math.cos(-midAngle * RADIAN);
    const y = cy + radius * Math.sin(-midAngle * RADIAN);

    return (
      <text
        x={x}
        y={y}
        fill="white"
        textAnchor={x > cx ? 'start' : 'end'}
        dominantBaseline="central"
        fontSize={12}
        fontWeight="bold"
      >
        {`${(percentage * 100).toFixed(0)}%`}
      </text>
    );
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
          Sector Allocation
        </h3>
        <div className="h-64 flex items-center justify-center">
          <p className="text-gray-500 dark:text-gray-400">No sector data available</p>
        </div>
      </div>
    );
  }

  // Calculate top sectors for summary
  const sortedData = [...dataWithColors].sort((a, b) => b.value - a.value);
  const topSector = sortedData[0];
  const topCount = Math.min(3, sortedData.length);
  const top3Allocation = sortedData.slice(0, 3).reduce((sum, item) => sum + item.percentage, 0);

  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          Sector Allocation
        </h3>
        <div className="text-right">
          <div className="text-sm text-gray-600 dark:text-gray-400">Top Sector</div>
          <div className="text-lg font-bold text-gray-900 dark:text-white">
            {topSector?.name || 'N/A'}
          </div>
          <div className="text-sm text-gray-500 dark:text-gray-400">
            {sortedData.length === 1
              ? '100.0% Allocation'
              : `Top ${topCount}: ${formatPercentage(top3Allocation)}`}
          </div>
        </div>
      </div>
      
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={dataWithColors}
              cx="50%"
              cy="50%"
              labelLine={false}
              label={CustomLabel}
              outerRadius={80}
              fill="#8884d8"
              dataKey="value"
            >
              {dataWithColors.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
            <Legend
              verticalAlign="bottom"
              height={36}
              formatter={(value, entry) => (
                <span style={{ color: entry.color }} className="text-sm">
                  {value}
                </span>
              )}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default SectorAllocationChart;