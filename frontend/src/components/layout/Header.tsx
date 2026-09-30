/**
 * Header component for the FinEngine dashboard
 * Features user controls, notifications, and responsive mobile navigation
 */

'use client';

import React, { useState } from 'react';
import { 
  Moon, 
  Sun, 
  Menu, 
  RefreshCw,
  Activity,
  FileDown
} from 'lucide-react';
import { useUIStore, usePortfolioStore } from '@/lib/store';
import { ExportService, type RiskMetricsSnapshot } from '@/lib/export';
import api from '@/lib/api';
import { useNotifications } from '@/hooks/useRealTime';
import { formatRelativeTime } from '@/components/ui/LoadingState';
import { cn } from '@/lib/utils';

/**
 * Collect the risk figures the review PDF is allowed to quote.
 *
 * `allSettled` on purpose: these three routes fail independently, and a route
 * that fails leaves its own block `undefined` so the document omits that
 * section's sentences. Nothing is substituted from a neighbouring route and no
 * failure is converted into a number — a PDF that silently drops its risk
 * section is recoverable, one that invents it is not.
 */
async function loadRiskMetrics(): Promise<RiskMetricsSnapshot> {
  const [contribution, limits, liquidity] = await Promise.allSettled([
    api.get<RiskMetricsSnapshot['riskContribution']>('/analytics/risk-contribution'),
    api.get<RiskMetricsSnapshot['liquidityLimits']>('/analytics/liquidity-limits'),
    api.get<RiskMetricsSnapshot['liquidity']>('/analytics/liquidity'),
  ]);

  const snapshot: RiskMetricsSnapshot = {};
  if (contribution.status === 'fulfilled') {
    snapshot.riskContribution = contribution.value?.data ?? null;
  } else {
    console.error('Risk contribution unavailable for PDF export:', contribution.reason);
  }
  if (limits.status === 'fulfilled') {
    snapshot.liquidityLimits = limits.value?.data ?? null;
  } else {
    console.error('Liquidity limits unavailable for PDF export:', limits.reason);
  }
  if (liquidity.status === 'fulfilled') {
    snapshot.liquidity = liquidity.value?.data ?? null;
  } else {
    console.error('Liquidity score unavailable for PDF export:', liquidity.reason);
  }
  return snapshot;
}

interface HeaderProps {
  title?: string;
  subtitle?: string;
  onMenuClick?: () => void;
  className?: string;
}

export function Header({ title, subtitle, onMenuClick, className }: HeaderProps) {
  const darkMode = useUIStore((s) => s.darkMode);
  const toggleDarkMode = useUIStore((s) => s.toggleDarkMode);
  const liveDataMode = useUIStore((s) => s.liveDataMode);
  const toggleLiveDataMode = useUIStore((s) => s.toggleLiveDataMode);
  const lastUpdated = useUIStore((s) => s.lastUpdated);
  const portfolioState = usePortfolioStore((state) => state);
  const { positions, positionCount, fetchPortfolio, isLoading } = portfolioState;
  const { addNotification } = useNotifications();
  const portfolioCount = positionCount || positions.length;
  const [isExportingPdf, setIsExportingPdf] = useState(false);

  const handleRefresh = async () => {
    try {
      const refreshed = await fetchPortfolio();
      if (!refreshed) {
        throw new Error('Portfolio refresh failed');
      }
    } catch (error) {
      console.error('Failed to refresh portfolio:', error);
      addNotification('error', 'Refresh Failed', "Couldn't fetch portfolio data. Try again.");
    }
  };

  const handleExportPdf = async () => {
    setIsExportingPdf(true);
    try {
      const totalVal = positions.reduce(
        (sum, p) => sum + (p.market_value_base ?? p.market_value ?? 0),
        0
      );
      // Fetched here, not read from the store: the three analytics routes are
      // the only source for the figures the review quotes, and the store
      // carries holdings only. A route that fails leaves its block absent and
      // the document drops that section's sentences.
      const riskMetrics = await loadRiskMetrics();
      await ExportService.exportInstitutionalReviewPDF({
        positions,
        totalValue: totalVal,
        currency: 'INR',
        riskMetrics
      });
      addNotification('success', 'PDF Exported', 'Institutional review downloaded.');
    } catch (error) {
      console.error('Failed to export PDF:', error);
      addNotification('error', 'Export Failed', "Couldn't generate the PDF review.");
    } finally {
      setIsExportingPdf(false);
    }
  };

  return (
    <header className={cn(
      'bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 px-4 lg:px-6 py-4',
      className
    )}>
      <div className="flex items-center justify-between">
        {/* Left side - Mobile menu + Title */}
        <div className="flex items-center space-x-4">
          {onMenuClick && (
            <button
              onClick={onMenuClick}
              className="lg:hidden p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              aria-label="Open menu"
            >
              <Menu className="w-5 h-5 text-gray-600 dark:text-gray-400" />
            </button>
          )}
          
          <div>
            {title && (
              <h1 className="text-xl font-semibold text-gray-900 dark:text-white">
                {title}
              </h1>
            )}
            {subtitle && (
              <p className="text-sm text-gray-600 dark:text-gray-400">
                {subtitle}
              </p>
            )}
          </div>
        </div>

        {/* Right side - Controls and user actions */}
        <div className="flex items-center space-x-3">
          {/* Portfolio info */}
          <div className="hidden sm:flex items-center space-x-4 text-sm text-gray-600 dark:text-gray-400">
            <div className="flex items-center space-x-1">
              <Activity className="w-4 h-4" />
              <span>{portfolioCount} positions</span>
            </div>
            <div className="flex items-center space-x-1">
              <span>Last updated: {formatRelativeTime(lastUpdated)}</span>
            </div>
          </div>

          {/* Live data toggle */}
          <button
            onClick={toggleLiveDataMode}
            aria-label="Toggle live data"
            aria-pressed={liveDataMode}
            className={cn(
              'flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              liveDataMode
                ? 'bg-green-100 dark:bg-green-900/20 text-green-700 dark:text-green-300'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300'
            )}
          >
            <RefreshCw className={cn(
              'w-4 h-4',
              liveDataMode && 'animate-spin'
            )} />
            <span className="hidden sm:inline">Live</span>
          </button>

          {/* Export PDF Tear-Sheet */}
          <button
            onClick={handleExportPdf}
            disabled={portfolioCount === 0 || isExportingPdf}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 border border-slate-300 dark:border-slate-700 transition disabled:opacity-50"
            title="Download Institutional PDF Review"
          >
            <FileDown className={cn('w-3.5 h-3.5 text-indigo-500', isExportingPdf && 'animate-spin')} />
            <span className="hidden md:inline">Export PDF</span>
          </button>

          {/* Refresh button */}
          <button
            onClick={handleRefresh}
            disabled={isLoading}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
            aria-label="Refresh data"
          >
            <RefreshCw className={cn(
              'w-5 h-5 text-gray-600 dark:text-gray-400',
              isLoading && 'animate-spin'
            )} />
          </button>

          {/* Dark mode toggle */}
          <button
            onClick={toggleDarkMode}
            aria-label="Toggle dark mode"
            aria-pressed={darkMode}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            {darkMode ? (
              <Sun className="w-5 h-5 text-gray-600 dark:text-gray-400" />
            ) : (
              <Moon className="w-5 h-5 text-gray-600 dark:text-gray-400" />
            )}
          </button>
        </div>
      </div>
    </header>
  );
}

export default Header;