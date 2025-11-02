/**
 * Portfolio Charts Component
 * Data visualization using Recharts for portfolio analytics
 */

'use client';

import React from 'react';
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  BarChart,
  Bar
} from 'recharts';
import { PortfolioPosition, PortfolioSummary, Currency } from '@/types';
import { cn } from '@/lib/utils';

interface PortfolioChartsProps {
  positions: PortfolioPosition[];
  currency: Currency;
  summary: PortfolioSummary | null;
}

const COLORS = [
  '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6',
  '#06B6D4', '#84CC16', '#F97316', '#EC4899', '#6366F1'
];

export function PortfolioCharts({ positions, currency, summary }: PortfolioChartsProps) {
  // Format currency
  const formatCurrency = (amount: number) => {
    const symbol = currency === 'INR' ? '₹' : '$';
    return `${symbol}${amount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
  };

  // Prepare sector allocation data
  const sectorData = Object.entries(summary?.sectors || {}).map(([sector, weight]) => ({
    name: sector,
    value: weight * 100,
    allocation: (weight * 100).toFixed(1) + '%'
  }));

  // Prepare top holdings data (top 10)
  const topHoldingsData = positions
    .sort((a, b) => b.current_value - a.current_value)
    .slice(0, 10)
    .map(pos => ({
      name: pos.ticker,
      value: pos.current_value,
      weight: pos.weight * 100,
      gainLoss: pos.unrealized_gain_loss,
      gainLossPct: pos.unrealized_gain_loss_pct
    }));

  // Prepare performance data (mock historical data for demonstration)
  const performanceData = [
    { date: '2024-01', value: 100000 },
    { date: '2024-02', value: 102500 },
    { date: '2024-03', value: 98500 },
    { date: '2024-04', value: 107800 },
    { date: '2024-05', value: 115200 },
    { date: '2024-06', value: 118900 },
    { date: '2024-07', value: 125400 },
    { date: '2024-08', value: 122800 },
    { date: '2024-09', value: 128900 },
    { date: '2024-10', value: 132400 },
    { date: '2024-11', value: 135600 }
  ];

  // Custom tooltip for charts
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white dark:bg-gray-800 p-3 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg">
          <p className="text-sm font-medium text-gray-900 dark:text-white">{label}</p>
          {payload.map((entry: any, index: number) => (
            <p key={index} className="text-sm" style={{ color: entry.color }}>
              {entry.name}: {entry.name.includes('%') ? entry.value + '%' : formatCurrency(entry.value)}
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Portfolio Performance Chart */}
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Portfolio Performance
        </h3>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={performanceData}>
              <defs>
                <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#3B82F6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
              <XAxis 
                dataKey="date" 
                stroke="#6B7280"
                fontSize={12}
              />
              <YAxis 
                stroke="#6B7280"
                fontSize={12}
                tickFormatter={formatCurrency}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="value"
                stroke="#3B82F6"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#colorValue)"
                name="Portfolio Value"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Sector Allocation Chart */}
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Sector Allocation
        </h3>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={sectorData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, allocation }) => `${name} ${allocation}`}
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {sectorData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip 
                formatter={(value: number) => [`${value.toFixed(1)}%`, 'Allocation']}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top Holdings Chart */}
      {topHoldingsData.length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Top Holdings by Value
          </h3>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={topHoldingsData} layout="horizontal">
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
                <XAxis 
                  type="number"
                  stroke="#6B7280"
                  fontSize={12}
                  tickFormatter={formatCurrency}
                />
                <YAxis 
                  type="category"
                  dataKey="name"
                  stroke="#6B7280"
                  fontSize={12}
                  width={60}
                />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="value" fill="#3B82F6" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Gain/Loss by Position */}
      {topHoldingsData.length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Gain/Loss by Position
          </h3>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={topHoldingsData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
                <XAxis 
                  dataKey="name"
                  stroke="#6B7280"
                  fontSize={12}
                />
                <YAxis 
                  stroke="#6B7280"
                  fontSize={12}
                  tickFormatter={formatCurrency}
                />
                <Tooltip content={<CustomTooltip />} />
                <Bar 
                  dataKey="gainLoss" 
                  fill="#10B981"
                  name="Gain/Loss"
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

export default PortfolioCharts;