/**
 * RiskMetricsDisplay component for showing portfolio risk metrics
 */

import React from 'react';
import { MetricCard } from '@/components/ui/MetricCard';
import {
  TrendingDown,
  Activity,
  Shield,
  AlertTriangle,
  BarChart3,
  Target,
} from 'lucide-react';

interface RiskMetricsData {
  risk_score: number;
  risk_level: string;
  annual_volatility: number;
  sharpe_ratio: number;
  max_drawdown: number;
  var_95: number;
  cvar_95: number;
  concentration_score?: number;
  liquidity_score?: number;
  realized_volatility?: number;
  forecast_volatility?: number | null;
  forecast_var?: number | null;
}

interface RiskMetricsDisplayProps {
  data?: RiskMetricsData;
  loading?: boolean;
  className?: string;
}

export const RiskMetricsDisplay: React.FC<RiskMetricsDisplayProps> = ({
  data,
  loading = false,
  className = '',
}) => {
  // Default data when none provided
  const defaultData: RiskMetricsData = {
    risk_score: 0,
    risk_level: 'Unknown',
    annual_volatility: 0,
    sharpe_ratio: 0,
    max_drawdown: 0,
    var_95: 0,
    cvar_95: 0,
  };

  const metrics = data || defaultData;

  const getRiskLevelColor = (level: string): string => {
    switch (level.toLowerCase()) {
      case 'low':
        return 'text-green-600 dark:text-green-400';
      case 'medium':
        return 'text-yellow-600 dark:text-yellow-400';
      case 'high':
        return 'text-red-600 dark:text-red-400';
      default:
        return 'text-gray-600 dark:text-gray-400';
    }
  };

  const getRiskScoreChangeType = (score: number): 'positive' | 'negative' | 'neutral' => {
    if (score <= 25) return 'positive'; // Low risk is good
    if (score <= 50) return 'neutral';
    return 'negative'; // High risk is bad
  };

  const getVolatilityChangeType = (vol: number): 'positive' | 'negative' | 'neutral' => {
    if (vol <= 0.15) return 'positive'; // Low volatility is good
    if (vol <= 0.25) return 'neutral';
    return 'negative'; // High volatility is bad
  };

  const formatPercentage = (value: number | null | undefined): string => {
    if (value === null || value === undefined || isNaN(value)) {
      return 'N/A';
    }
    return `${(value * 100).toFixed(2)}%`;
  };

  const getVaRInterpretation = (var95: number): { level: string; color: string } => {
    const varPct = Math.abs(var95);
    if (varPct <= 0.02) return { level: 'Low', color: 'text-green-600 dark:text-green-400' };
    if (varPct <= 0.05) return { level: 'Medium', color: 'text-yellow-600 dark:text-yellow-400' };
    return { level: 'High', color: 'text-red-600 dark:text-red-400' };
  };

  if (loading) {
    return (
      <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 ${className}`}>
        <div className="animate-pulse">
          <div className="h-6 bg-gray-300 dark:bg-gray-600 rounded w-48 mb-4"></div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-32 bg-gray-200 dark:bg-gray-700 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  const varInterpretation = getVaRInterpretation(metrics.var_95);

  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700 ${className}`}>
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          Risk Metrics Overview
        </h3>
        <div className="flex items-center space-x-2">
          <Shield className={`w-5 h-5 ${getRiskLevelColor(metrics.risk_level)}`} />
          <span className={`text-sm font-medium ${getRiskLevelColor(metrics.risk_level)}`}>
            {metrics.risk_level} Risk
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Risk Score"
          value={metrics.risk_score.toFixed(1)}
          icon={Shield}
          change={metrics.risk_score > 0 ? -5.2 : 0}
          changeType={getRiskScoreChangeType(metrics.risk_score)}
          loading={loading}
        />

        <MetricCard
          title="Volatility Forecast"
          value={metrics.forecast_volatility ? formatPercentage(metrics.forecast_volatility) : 'N/A'}
          icon={Activity}
          change={metrics.forecast_volatility && metrics.forecast_volatility > 0 ? -0.8 : 0}
          changeType={getVolatilityChangeType(metrics.forecast_volatility || 0.2)}
          loading={loading}
        />

        <MetricCard
          title="VaR Forecast"
          value={metrics.forecast_var ? formatPercentage(metrics.forecast_var) : 'N/A'}
          icon={TrendingDown}
          change={metrics.forecast_var && Math.abs(metrics.forecast_var) > 0.02 ? -2.3 : 0}
          changeType={Math.abs(metrics.forecast_var || 0) <= 0.02 ? 'positive' : 'negative'}
          loading={loading}
        />

        <MetricCard
          title="Sharpe Ratio"
          value={metrics.sharpe_ratio.toFixed(2)}
          icon={Target}
          change={metrics.sharpe_ratio > 0 ? 0.15 : 0}
          changeType={metrics.sharpe_ratio > 0.5 ? 'positive' : 'negative'}
          loading={loading}
        />
      </div>

      {/* Additional Risk Details */}
      <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium text-gray-900 dark:text-white">Value at Risk (95%)</h4>
            <AlertTriangle className="w-4 h-4 text-gray-500 dark:text-gray-400" />
          </div>
          <div className="text-2xl font-bold text-red-600 dark:text-red-400">
            {formatPercentage(metrics.var_95)}
          </div>
          <div className={`text-sm ${varInterpretation.color}`}>
            {varInterpretation.level} Risk
          </div>
        </div>

        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium text-gray-900 dark:text-white">Conditional VaR</h4>
            <Target className="w-4 h-4 text-gray-500 dark:text-gray-400" />
          </div>
          <div className="text-2xl font-bold text-red-600 dark:text-red-400">
            {formatPercentage(metrics.cvar_95)}
          </div>
          <div className="text-sm text-gray-600 dark:text-gray-400">
            Expected loss beyond VaR
          </div>
        </div>

        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium text-gray-900 dark:text-white">Risk Level</h4>
            <Shield className="w-4 h-4 text-gray-500 dark:text-gray-400" />
          </div>
          <div className={`text-2xl font-bold ${getRiskLevelColor(metrics.risk_level)}`}>
            {metrics.risk_level}
          </div>
          <div className="text-sm text-gray-600 dark:text-gray-400">
            Overall assessment
          </div>
        </div>
      </div>

      {/* Risk Alerts */}
      {metrics.risk_score > 50 && (
        <div className="mt-6 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400 mr-2" />
            <div>
              <h4 className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                Risk Alert
              </h4>
              <p className="text-sm text-yellow-700 dark:text-yellow-300 mt-1">
                Portfolio risk score is elevated. Consider diversification or risk reduction strategies.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default RiskMetricsDisplay;