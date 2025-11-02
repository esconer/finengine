/**
 * Volatility Sizing Page - Dynamic position sizing based on volatility
 */

'use client';

import React, { useState, useEffect } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import { analyticsApi } from '@/lib/api';
import { usePortfolioStore } from '@/lib/store';
import {
  Zap,
  Target,
  TrendingUp,
  Activity,
  RefreshCw,
  Download,
  Settings,
  BarChart3,
  AlertTriangle
} from 'lucide-react';

interface VolatilitySizingData {
  current_weights: Record<string, number>;
  recommended_weights: Record<string, number>;
  trades: Record<string, {
    shares_delta: number;
    amount: number;
  }>;
  target_volatility: number;
  model_params: Record<string, any>;
  methodology?: string;
}

interface PositionSizing {
  ticker: string;
  current_weight: number;
  target_weight: number;
  recommended_weight: number;
  volatility: number;
  weight_change: number;
  shares_delta: number;
  amount_delta: number;
}

export default function VolatilitySizingPage() {
  const [sizingData, setSizingData] = useState<VolatilitySizingData | null>(null);
  const [selectedModel, setSelectedModel] = useState('EWMA');
  const [targetVolatility, setTargetVolatility] = useState(0.15);
  const [loading, setLoading] = useState(false);
  const [positionData, setPositionData] = useState<PositionSizing[]>([]);

  const { positions } = usePortfolioStore();

  const fetchSizingData = async () => {
    setLoading(true);
    try {
      const data = await analyticsApi.getVolatilitySizing({
        model: selectedModel,
        target_volatility: targetVolatility
      });
      setSizingData(data);
      
      // Convert data for table
      const positionsList = positions.map(pos => {
        const currentWeight = pos.weight;
        const recommendedWeight = data.recommended_weights[pos.ticker] || currentWeight;
        const targetWeight = data.trades[pos.ticker]?.shares_delta ? recommendedWeight : currentWeight;
        const weightChange = recommendedWeight - currentWeight;
        const sharesDelta = data.trades[pos.ticker]?.shares_delta || 0;
        const amountDelta = data.trades[pos.ticker]?.amount || 0;
        
        return {
          ticker: pos.ticker,
          current_weight: currentWeight,
          target_weight: targetWeight,
          recommended_weight: recommendedWeight,
          volatility: Math.random() * 0.3 + 0.1, // Mock volatility data
          weight_change: weightChange,
          shares_delta: sharesDelta,
          amount_delta: amountDelta,
        };
      });
      
      setPositionData(positionsList);
    } catch (error) {
      console.error('Failed to fetch volatility sizing data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (positions.length > 0) {
      fetchSizingData();
    }
  }, [positions, selectedModel, targetVolatility]);

  const handleModelChange = (model: string) => {
    setSelectedModel(model);
  };

  const handleTargetVolatilityChange = (vol: number) => {
    setTargetVolatility(vol);
  };

  const handleRefresh = () => {
    fetchSizingData();
  };

  const handleRebalance = async () => {
    // In a real implementation, this would call an API to execute the rebalancing
    alert('Rebalancing functionality would be implemented here');
  };

  // Format metrics for display
  const formatPercentage = (value: number, decimals = 2) => {
    return `${(value * 100).toFixed(decimals)}%`;
  };

  const formatCurrency = (value: number) => {
    if (Math.abs(value) >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
    if (Math.abs(value) >= 1000) return `$${(value / 1000).toFixed(1)}K`;
    return `$${value.toLocaleString()}`;
  };

  const getChangeColor = (change: number): string => {
    if (change > 0.01) return 'text-green-600 dark:text-green-400';
    if (change < -0.01) return 'text-red-600 dark:text-red-400';
    return 'text-gray-600 dark:text-gray-400';
  };

  const getChangeBgColor = (change: number): string => {
    if (change > 0.01) return 'bg-green-100 dark:bg-green-900/20 border-green-200 dark:border-green-800';
    if (change < -0.01) return 'bg-red-100 dark:bg-red-900/20 border-red-200 dark:border-red-800';
    return 'bg-gray-100 dark:bg-gray-700 border-gray-200 dark:border-gray-600';
  };

  // Position sizing table columns
  const positionColumns = [
    {
      header: 'Ticker',
      accessorKey: 'ticker',
      cell: ({ row }: any) => (
        <div className="font-medium text-gray-900 dark:text-white">
          {row.ticker}
        </div>
      ),
    },
    {
      header: 'Current Weight',
      accessorKey: 'current_weight',
      cell: ({ row }: any) => (
        <div className="text-gray-900 dark:text-white">
          {formatPercentage(row.current_weight)}
        </div>
      ),
    },
    {
      header: 'Target Weight',
      accessorKey: 'target_weight',
      cell: ({ row }: any) => (
        <div className="text-gray-900 dark:text-white">
          {formatPercentage(row.target_weight)}
        </div>
      ),
    },
    {
      header: 'Recommended Weight',
      accessorKey: 'recommended_weight',
      cell: ({ row }: any) => (
        <div className="text-gray-900 dark:text-white">
          {formatPercentage(row.recommended_weight)}
        </div>
      ),
    },
    {
      header: 'Volatility',
      accessorKey: 'volatility',
      cell: ({ row }: any) => (
        <div className="text-gray-900 dark:text-white">
          {formatPercentage(row.volatility)}
        </div>
      ),
    },
    {
      header: 'Weight Change',
      accessorKey: 'weight_change',
      cell: ({ row }: any) => (
        <div className={`font-medium ${getChangeColor(row.weight_change)}`}>
          {row.weight_change > 0 ? '+' : ''}{formatPercentage(row.weight_change)}
        </div>
      ),
    },
    {
      header: 'Action',
      accessorKey: 'recommended_action',
      cell: ({ row }: any) => {
        const action = Math.abs(row.weight_change) < 0.005 ? 'Hold' : row.weight_change > 0 ? 'Buy' : 'Sell';
        const colorClass = action === 'Buy' ? 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-300' :
                          action === 'Sell' ? 'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-300' :
                          'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
        return (
          <span className={`px-2 py-1 text-xs rounded-full font-medium ${colorClass}`}>
            {action}
          </span>
        );
      },
    },
  ];

  // Calculate summary metrics
  const totalWeightChange = positionData.reduce((sum, pos) => sum + Math.abs(pos.weight_change), 0);
  const buyCount = positionData.filter(pos => pos.weight_change > 0.01).length;
  const sellCount = positionData.filter(pos => pos.weight_change < -0.01).length;
  const holdCount = positionData.filter(pos => Math.abs(pos.weight_change) <= 0.01).length;

  const models = [
    { name: 'Risk Parity', description: 'Equal risk contribution across positions', volatility: '15.0%', actual: '14.2%' },
    { name: 'Volatility Targeting', description: 'Target specific portfolio volatility', volatility: '12.0%', actual: '13.8%' },
    { name: 'Equal Risk', description: 'Conservative risk distribution', volatility: '10.0%', actual: '11.2%' },
  ];

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-yellow-600 to-orange-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Volatility Sizing</h1>
            <p className="text-yellow-100">
              Dynamic position sizing based on volatility models
            </p>
            <div className="flex items-center mt-2 space-x-4">
              <div className="text-yellow-200 text-sm">
                Model: {selectedModel}
              </div>
              <div className="text-yellow-200 text-sm">
                Target Vol: {formatPercentage(targetVolatility)}
              </div>
              {sizingData && (
                <div className="text-yellow-200 text-sm">
                  Est. Portfolio Vol: {formatPercentage(0.142)} {/* Mock current volatility */}
                </div>
              )}
            </div>
          </div>
          <div className="hidden md:flex items-center space-x-2">
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="bg-white/20 hover:bg-white/30 rounded-lg p-2 transition-colors"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <Zap className="w-16 h-16 text-yellow-200" />
          </div>
        </div>
      </div>

      {/* Volatility Sizing Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Target Volatility"
          value={formatPercentage(targetVolatility)}
          change={0}
          changeType="neutral"
          icon={Target}
          loading={loading}
        />
        <MetricCard
          title="Current Portfolio Vol"
          value="14.2%"
          change={-0.3}
          changeType="positive"
          icon={Activity}
          loading={loading}
        />
        <MetricCard
          title="Vol-Adj Sharpe"
          value="1.24"
          change={0.08}
          changeType="positive"
          icon={TrendingUp}
          loading={loading}
        />
        <MetricCard
          title="Sizing Efficiency"
          value="94.7%"
          change={1.2}
          changeType="positive"
          icon={Zap}
          loading={loading}
        />
      </div>

      {/* Model Configuration */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Volatility Models
          </h3>
          <div className="space-y-3">
            {models.map((model) => (
              <div
                key={model.name}
                className={`p-4 border-2 rounded-lg cursor-pointer transition-colors ${
                  selectedModel === model.name
                    ? 'border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-900/20'
                    : 'border-gray-200 dark:border-gray-600 hover:border-gray-300 dark:hover:border-gray-500'
                }`}
                onClick={() => handleModelChange(model.name.replace(' ', '').toUpperCase())}
              >
                <div className="flex items-center justify-between">
                  <h4 className={`font-medium ${
                    selectedModel === model.name
                      ? 'text-yellow-900 dark:text-yellow-300'
                      : 'text-gray-900 dark:text-white'
                  }`}>
                    {model.name}
                  </h4>
                  {selectedModel === model.name.replace(' ', '').toUpperCase() && (
                    <div className="w-4 h-4 bg-yellow-600 rounded-full"></div>
                  )}
                </div>
                <p className={`text-sm mt-1 ${
                  selectedModel === model.name
                    ? 'text-yellow-700 dark:text-yellow-400'
                    : 'text-gray-600 dark:text-gray-400'
                }`}>
                  {model.description}
                </p>
                <div className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  Target Vol: {model.volatility} | Est. Vol: {model.actual}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            Target Volatility Setting
          </h3>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Target Portfolio Volatility
              </label>
              <input
                type="range"
                min="0.05"
                max="0.30"
                step="0.01"
                value={targetVolatility}
                onChange={(e) => handleTargetVolatilityChange(parseFloat(e.target.value))}
                className="w-full"
              />
              <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-1">
                <span>5%</span>
                <span className="font-medium text-gray-900 dark:text-white">
                  {formatPercentage(targetVolatility)}
                </span>
                <span>30%</span>
              </div>
            </div>
            
            <div className="grid grid-cols-3 gap-2">
              {[0.10, 0.15, 0.20].map((vol) => (
                <button
                  key={vol}
                  className={`p-2 text-sm rounded border transition-colors ${
                    targetVolatility === vol
                      ? 'border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-900/20 text-yellow-900 dark:text-yellow-300'
                      : 'border-gray-200 dark:border-gray-600 hover:border-gray-300 text-gray-900 dark:text-white'
                  }`}
                  onClick={() => handleTargetVolatilityChange(vol)}
                >
                  {formatPercentage(vol)}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Position Sizing Analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Volatility-Adjusted Weights
            </h3>
            <BarChart3 className="w-5 h-5 text-gray-500" />
          </div>
          <div className="space-y-3">
            {positionData.slice(0, 6).map((position) => (
              <div key={position.ticker} className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    {position.ticker}
                  </span>
                  <span className="text-sm text-gray-600 dark:text-gray-400">
                    Target: {formatPercentage(position.target_weight)}
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="text-xs text-gray-500 dark:text-gray-400 w-12">Current</span>
                  <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                    <div
                      className="h-2 rounded-full bg-blue-500"
                      style={{ width: `${position.current_weight * 400}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-600 dark:text-gray-400 w-8">
                    {formatPercentage(position.current_weight)}
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="text-xs text-gray-500 dark:text-gray-400 w-12">Adjusted</span>
                  <div className="flex-1 bg-gray-300 dark:bg-gray-600 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${position.weight_change > 0 ? 'bg-green-500' : position.weight_change < 0 ? 'bg-red-500' : 'bg-gray-500'}`}
                      style={{ width: `${position.recommended_weight * 400}%` }}
                    />
                  </div>
                  <span className={`text-xs w-8 ${
                    getChangeColor(position.weight_change)
                  }`}>
                    {formatPercentage(position.recommended_weight)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Volatility Forecast
            </h3>
            <Activity className="w-5 h-5 text-gray-500" />
          </div>
          <div className="h-64 bg-gray-100 dark:bg-gray-700 rounded-lg flex items-center justify-center">
            <div className="text-center text-gray-500 dark:text-gray-400">
              <Zap className="w-12 h-12 mx-auto mb-2" />
              <p>Volatility forecast chart will be implemented</p>
              <p className="text-xs mt-1">Showing volatility projections and position sizing impact</p>
            </div>
          </div>
        </div>
      </div>

      {/* Position-Level Analysis */}
      {positionData.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700">
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Position-Level Sizing Analysis
              </h3>
              <div className="flex items-center space-x-2">
                <button
                  onClick={handleRebalance}
                  className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 text-white rounded-lg transition-colors"
                >
                  Execute Rebalance
                </button>
                <button className="flex items-center px-3 py-2 text-sm bg-gray-100 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-500 transition-colors">
                  <Download className="w-4 h-4 mr-1" />
                  Export
                </button>
              </div>
            </div>
          </div>

          <DataTable
            data={positionData}
            columns={positionColumns}
            loading={loading}
            searchablePlaceholder="Search positions..."
            exportable={false}
          />
        </div>
      )}

      {/* Rebalancing Recommendations */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Rebalancing Recommendations
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div className="text-center p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800">
            <div className="text-2xl font-bold text-green-600 dark:text-green-400">
              {buyCount}
            </div>
            <div className="text-sm text-green-700 dark:text-green-400">
              Buy Positions
            </div>
          </div>
          <div className="text-center p-4 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
            <div className="text-2xl font-bold text-red-600 dark:text-red-400">
              {sellCount}
            </div>
            <div className="text-sm text-red-700 dark:text-red-400">
              Sell Positions
            </div>
          </div>
          <div className="text-center p-4 bg-gray-50 dark:bg-gray-700 rounded-lg border border-gray-200 dark:border-gray-600">
            <div className="text-2xl font-bold text-gray-600 dark:text-gray-400">
              {holdCount}
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-400">
              Hold Positions
            </div>
          </div>
        </div>
        
        <div className="space-y-3">
          {positionData.filter(pos => Math.abs(pos.weight_change) > 0.01).slice(0, 5).map((position) => (
            <div key={position.ticker} className={`flex items-center justify-between p-3 rounded-lg border ${getChangeBgColor(position.weight_change)}`}>
              <div className="flex items-center space-x-3">
                <div className={`w-2 h-2 rounded-full ${
                  position.weight_change > 0 ? 'bg-green-500' : 'bg-red-500'
                }`}></div>
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {position.weight_change > 0 ? 'Increase' : 'Decrease'} {position.ticker}
                </span>
              </div>
              <span className={`text-sm ${getChangeColor(position.weight_change)}`}>
                {position.weight_change > 0 ? '+' : ''}{formatPercentage(position.weight_change)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Sizing Insights */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Volatility Sizing Insights
        </h3>
        <div className="space-y-4">
          {totalWeightChange > 0.10 && (
            <div className="flex items-start space-x-3">
              <AlertTriangle className="w-5 h-5 text-yellow-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Significant Rebalancing Needed</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Total weight adjustment of {formatPercentage(totalWeightChange)} suggests substantial portfolio changes may be required.
                </p>
              </div>
            </div>
          )}

          {buyCount > sellCount && (
            <div className="flex items-start space-x-3">
              <TrendingUp className="w-5 h-5 text-green-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Net Buying Pressure</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Model suggests increasing exposure to {buyCount} positions while reducing {sellCount} positions.
                </p>
              </div>
            </div>
          )}

          <div className="flex items-start space-x-3">
            <BarChart3 className="w-5 h-5 text-blue-600 mt-0.5" />
            <div>
              <h4 className="font-medium text-gray-900 dark:text-white">Sizing Methodology</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {sizingData?.methodology || `Position sizing using ${selectedModel} model with target volatility of ${formatPercentage(targetVolatility)}.`}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}