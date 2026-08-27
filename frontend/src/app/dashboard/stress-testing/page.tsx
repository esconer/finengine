/**
 * Stress Testing Page - Portfolio stress testing scenarios
 */

'use client';

import React, { useState, useEffect } from 'react';
import { ColumnDef } from '@tanstack/react-table';
import { MetricCard } from '@/components/ui/MetricCard';
import { DataTable } from '@/components/ui/DataTable';
import { analyticsApi } from '@/lib/api';
import { usePortfolioStore } from '@/lib/store';
import {
  TestTube,
  AlertTriangle,
  TrendingDown,
  Activity,
  RefreshCw,
  Play,
  Settings,
  Download,
  Plus,
  X
} from 'lucide-react';

interface StressTestResult {
  scenario: string;
  max_drawdown: number;
  portfolio_impact: number;
  position_impacts: Record<string, number>;
  recovery_time: number;
  confidence_level: number;
  methodology?: string;
}

interface Scenario {
  name: string;
  type: 'Historical' | 'Hypothetical';
  description: string;
  impact: number;
  recovery_time: string;
  icon: React.ComponentType<{ className?: string }>;
  color_class: string;
}

export default function StressTestingPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([
    {
      name: 'Market Crash',
      type: 'Historical',
      description: 'Recession scenario based on 2008 financial crisis',
      impact: -24.3,
      recovery_time: '18 months',
      icon: AlertTriangle,
      color_class: 'text-red-500'
    },
    {
      name: 'Interest Rate Shock',
      type: 'Hypothetical',
      description: '300bp rate increase scenario',
      impact: -12.7,
      recovery_time: '8 months',
      icon: TrendingDown,
      color_class: 'text-orange-500'
    },
    {
      name: 'Volatility Spike',
      type: 'Historical',
      description: 'COVID-19 market volatility scenario',
      impact: -8.9,
      recovery_time: '3 months',
      icon: Activity,
      color_class: 'text-blue-500'
    },
    {
      name: 'Tech Sector Correction',
      type: 'Hypothetical',
      description: 'Major technology sector decline',
      impact: -15.2,
      recovery_time: '12 months',
      icon: TestTube,
      color_class: 'text-purple-500'
    },
  ]);

  const [stressResults, setStressResults] = useState<Record<string, StressTestResult>>({});
  const [customScenario, setCustomScenario] = useState({
    name: '',
    market_shock: '',
    duration: '',
    type: 'Hypothetical' as 'Historical' | 'Hypothetical'
  });
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [positionData, setPositionData] = useState<any[]>([]);

  const { positions, fetchPortfolio } = usePortfolioStore();

  const runStressTest = async (scenarioName: string) => {
    setLoading(true);
    try {
      const data = await analyticsApi.runStressTest({
        scenario: scenarioName
      });
      setStressResults(prev => ({
        ...prev,
        [scenarioName]: data
      }));

      // Convert position impacts for table
      const positionsList = Object.entries(data.position_impacts || {}).map(([ticker, impact]) => ({
        ticker,
        impact,
        change: impact
      }));
      setPositionData(positionsList);
    } catch (error) {
      console.error('Failed to run stress test:', error);
    } finally {
      setLoading(false);
    }
  };

  const runCustomStressTest = async () => {
    if (!customScenario.name || !customScenario.market_shock) {
      alert('Please fill in all required fields');
      return;
    }

    setLoading(true);
    try {
      const data = await analyticsApi.runStressTest({
        scenario: `Custom: ${customScenario.name}`,
        tickers: positions.map(p => p.ticker)
      });
      
      // Add custom scenario to list
      const newScenario: Scenario = {
        name: customScenario.name,
        type: customScenario.type,
        description: `${customScenario.market_shock}% shock over ${customScenario.duration || '30'} days`,
        impact: data.portfolio_impact || -10,
        recovery_time: `${data.recovery_time || 'N/A'}`,
        icon: TestTube,
        color_class: 'text-green-500'
      };
      
      setScenarios(prev => [...prev, newScenario]);
      setStressResults(prev => ({
        ...prev,
        [customScenario.name]: data
      }));
      
      setShowCustomForm(false);
      setCustomScenario({ name: '', market_shock: '', duration: '', type: 'Hypothetical' });
    } catch (error) {
      console.error('Failed to run custom stress test:', error);
    } finally {
      setLoading(false);
    }
  };

  // Run stress tests on component mount for predefined scenarios
  useEffect(() => {
    fetchPortfolio();
  }, []);

  useEffect(() => {
    if (positions.length > 0) {
      // Run a few stress tests on load
      scenarios.slice(0, 2).forEach(scenario => {
        runStressTest(scenario.name);
      });
    }
  }, [positions]);

  const formatPercentage = (value: number | undefined | null, decimals = 1) => {
    if (value === undefined || value === null || isNaN(value)) {
      return 'N/A';
    }
    const pct = Math.abs(value) <= 1.0 && value !== 0 ? value * 100 : value;
    return `${pct.toFixed(decimals)}%`;
  };

  const getImpactColor = (impact: number): string => {
    const pct = Math.abs(impact) <= 1.0 && impact !== 0 ? impact * 100 : impact;
    if (pct < -15) return 'text-red-600 dark:text-red-400';
    if (pct < -10) return 'text-orange-600 dark:text-orange-400';
    if (pct < -5) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-green-600 dark:text-green-400';
  };

  const getImpactBgColor = (impact: number): string => {
    if (impact < -15) return 'bg-red-100 dark:bg-red-900/20 border-red-200 dark:border-red-800';
    if (impact < -10) return 'bg-orange-100 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800';
    if (impact < -5) return 'bg-yellow-100 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800';
    return 'bg-green-100 dark:bg-green-900/20 border-green-200 dark:border-green-800';
  };

  // Position impact table columns
  const positionColumns = [
    {
      header: 'Ticker',
      accessorKey: 'ticker',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className="font-medium text-gray-900 dark:text-white">
            {data.ticker}
          </div>
        );
      },
    },
    {
      header: 'Impact',
      accessorKey: 'impact',
      cell: ({ row }: any) => {
        const data = row.original || row;
        return (
          <div className={`font-medium ${getImpactColor(data.impact)}`}>
            {formatPercentage(data.impact)}
          </div>
        );
      },
    },
    {
      header: 'Severity',
      accessorKey: 'severity_level',
      cell: ({ row }: any) => {
        const data = row.original || row;
        const rawImpact = data.impact ?? 0;
        const impactVal = Math.abs(rawImpact) <= 1.0 && rawImpact !== 0 ? rawImpact * 100 : rawImpact;
        const severity = impactVal < -25 ? 'Critical' : impactVal < -15 ? 'High' : impactVal < -5 ? 'Medium' : 'Low';
        const colorClass = severity === 'Critical' ? 'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-300' :
                          severity === 'High' ? 'bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-300' :
                          severity === 'Medium' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-300' :
                          'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-300';
        return (
          <span className={`px-2 py-1 text-xs rounded-full font-medium ${colorClass}`}>
            {severity}
          </span>
        );
      },
    },
  ];

  const handleExportCSV = () => {
    if (!positionData || positionData.length === 0) return;
    const headers = 'Ticker,Impact,Severity\n';
    const rows = positionData
      .map(p => `${p.ticker},${(p.impact * 100).toFixed(2)}%,${Math.abs(p.impact) > 0.25 ? 'High' : Math.abs(p.impact) > 0.15 ? 'Medium' : 'Low'}`)
      .join('\n');
    const blob = new Blob([headers + rows], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `stress-impact-analysis.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Calculate summary metrics
  const stressTestResults = Object.values(stressResults);
  const worstCase = stressTestResults.length > 0 ? Math.min(...stressTestResults.map(r => r.portfolio_impact)) : 0;
  const bestCase = stressTestResults.length > 0 ? Math.max(...stressTestResults.map(r => r.portfolio_impact)) : 0;
  const avgImpact = stressTestResults.length > 0 ? (stressTestResults.reduce((sum: number, r: StressTestResult) => sum + r.portfolio_impact, 0) / stressTestResults.length) : 0;

  return (
    <div className="space-y-6">
      {/* Hero Section */}
      <div className="bg-gradient-to-r from-orange-600 to-red-600 rounded-lg p-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">Stress Testing</h1>
            <p className="text-orange-100">
              Portfolio stress testing scenarios and impact analysis
            </p>
            <div className="flex items-center mt-2 space-x-4">
              <div className="text-orange-200 text-sm">
                Scenarios tested: {stressTestResults.length} of {scenarios.length}
              </div>
              <div className="text-orange-200 text-sm">
                Portfolio positions: {positions.length}
              </div>
            </div>
          </div>
          <div className="hidden md:flex items-center space-x-2">
            <button
              onClick={() => setShowCustomForm(!showCustomForm)}
              className="bg-white/20 hover:bg-white/30 rounded-lg p-2 transition-colors"
            >
              <Plus className="w-5 h-5" />
            </button>
            <TestTube className="w-16 h-16 text-orange-200" />
          </div>
        </div>
      </div>

      {/* Custom Scenario Builder */}
      {showCustomForm && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Create Custom Stress Test
            </h3>
            <button
              onClick={() => setShowCustomForm(false)}
              className="text-gray-500 hover:text-gray-700"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Scenario Name *
              </label>
              <input
                type="text"
                value={customScenario.name}
                onChange={(e) => setCustomScenario(prev => ({ ...prev, name: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md 
                         bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                placeholder="Custom scenario name"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Market Shock (%) *
              </label>
              <input
                type="number"
                value={customScenario.market_shock}
                onChange={(e) => setCustomScenario(prev => ({ ...prev, market_shock: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md 
                         bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                placeholder="-20"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Duration (days)
              </label>
              <input
                type="number"
                value={customScenario.duration}
                onChange={(e) => setCustomScenario(prev => ({ ...prev, duration: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md 
                         bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                placeholder="30"
              />
            </div>
            <div className="flex items-end space-x-2">
              <button
                onClick={runCustomStressTest}
                disabled={loading}
                className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md 
                         transition-colors duration-200 disabled:opacity-50"
              >
                {loading ? 'Running...' : 'Run Test'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Worst Case Scenario"
          value={worstCase !== 0 ? formatPercentage(worstCase) : 'N/A'}
          icon={AlertTriangle}
          loading={loading && stressTestResults.length === 0}
        />
        <MetricCard
          title="Best Case Scenario"
          value={bestCase !== 0 ? formatPercentage(bestCase) : 'N/A'}
          icon={TrendingDown}
          loading={loading && stressTestResults.length === 0}
        />
        <MetricCard
          title="Average Impact"
          value={avgImpact !== 0 ? formatPercentage(avgImpact) : 'N/A'}
          icon={Activity}
          loading={loading && stressTestResults.length === 0}
        />
        <MetricCard
          title="Scenarios Tested"
          value={`${stressTestResults.length} of ${scenarios.length}`}
          icon={TestTube}
          loading={loading}
        />
      </div>

      {/* Stress Test Scenarios */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {scenarios.map((scenario) => {
          const result = stressResults[scenario.name];
          const Icon = scenario.icon;
          
          return (
            <div
              key={scenario.name}
              className={`bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border transition-colors ${
                result ? getImpactBgColor(result.portfolio_impact) : 'border-gray-200 dark:border-gray-700'
              }`}
            >
              <div className="flex items-center mb-4">
                <Icon className={`w-6 h-6 mr-2 ${scenario.color_class}`} />
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  {scenario.name}
                </h3>
                {result && (
                  <span className={`ml-auto px-2 py-1 text-xs rounded-full font-medium ${
                    getImpactColor(result.portfolio_impact)
                  }`}>
                    {formatPercentage(result.portfolio_impact)}
                  </span>
                )}
              </div>
              
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-sm text-gray-600 dark:text-gray-400">Scenario Type</span>
                  <span className="text-sm font-medium text-gray-900 dark:text-white">{scenario.type}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-gray-600 dark:text-gray-400">Description</span>
                  <span className="text-sm font-medium text-gray-900 dark:text-white text-right max-w-32 truncate">
                    {scenario.description}
                  </span>
                </div>
                
                {result ? (
                  <>
                    <div className="flex justify-between">
                      <span className="text-sm text-gray-600 dark:text-gray-400">Portfolio Impact</span>
                      <span className={`text-sm font-medium ${getImpactColor(result.portfolio_impact)}`}>
                        {formatPercentage(result.portfolio_impact)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm text-gray-600 dark:text-gray-400">Recovery Time</span>
                      <span className="text-sm font-medium text-gray-900 dark:text-white">
                        {result.recovery_time} months
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm text-gray-600 dark:text-gray-400">Confidence Level</span>
                      <span className="text-sm font-medium text-gray-900 dark:text-white">
                        {result.confidence_level ? (result.confidence_level < 1 ? (result.confidence_level * 100).toFixed(0) : result.confidence_level) : 95}%
                      </span>
                    </div>
                  </>
                ) : (
                  <button
                    onClick={() => runStressTest(scenario.name)}
                    disabled={loading}
                    className="w-full mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md 
                             transition-colors duration-200 disabled:opacity-50 flex items-center justify-center"
                  >
                    <Play className="w-4 h-4 mr-2" />
                    {loading ? 'Running...' : 'Run Test'}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Position Impact Analysis */}
      {positionData.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-700">
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Position-Level Impact Analysis
              </h3>
              <div className="flex items-center space-x-2">
                <button
                  onClick={handleExportCSV}
                  className="flex items-center px-3 py-2 text-sm bg-gray-100 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-500 transition-colors"
                >
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

      {/* Stress Test Insights */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Stress Testing Insights
        </h3>
        <div className="space-y-4">
          {worstCase < -20 && (
            <div className="flex items-start space-x-3">
              <AlertTriangle className="w-5 h-5 text-red-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">High Vulnerability</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Portfolio shows vulnerability to severe market stress scenarios, with worst-case impact of {formatPercentage(worstCase)}.
                </p>
              </div>
            </div>
          )}

          {stressTestResults.length > 0 && (
            <div className="flex items-start space-x-3">
              <Activity className="w-5 h-5 text-blue-600 mt-0.5" />
              <div>
                <h4 className="font-medium text-gray-900 dark:text-white">Recovery Analysis</h4>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Average recovery time across scenarios: {(stressTestResults.reduce((sum, r) => sum + (r.recovery_time || 0), 0) / stressTestResults.length).toFixed(1)} months.
                </p>
              </div>
            </div>
          )}

          <div className="flex items-start space-x-3">
            <TestTube className="w-5 h-5 text-green-600 mt-0.5" />
            <div>
              <h4 className="font-medium text-gray-900 dark:text-white">Testing Methodology</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Stress tests use historical market data and hypothetical scenarios to assess portfolio resilience under adverse conditions.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}