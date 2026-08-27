/**
 * Main dashboard layout component for Daisy Risk Engine
 * Provides responsive layout with sidebar navigation and header
 */

'use client';

import React, { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { useUIStore } from '@/lib/store';
import { cn } from '@/lib/utils';

interface DashboardLayoutProps {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  className?: string;
}

const routeTitles: Record<string, { title: string; subtitle?: string }> = {
  '/dashboard': {
    title: 'Portfolio Summary',
    subtitle: 'Overview of your portfolio performance and key metrics'
  },
  '/dashboard/realized-risk': {
    title: 'Realized Risk',
    subtitle: 'Historical risk metrics and portfolio performance analysis'
  },
  '/dashboard/forecast-risk': {
    title: 'Forecast Risk',
    subtitle: 'Future risk projections and Value-at-Risk forecasts'
  },
  '/dashboard/factor-exposure': {
    title: 'Factor Exposure',
    subtitle: 'Multi-factor risk analysis and exposure metrics'
  },
  '/dashboard/stress-testing': {
    title: 'Stress Testing',
    subtitle: 'Portfolio stress testing scenarios and impact analysis'
  },
  '/dashboard/concentration': {
    title: 'Concentration',
    subtitle: 'Portfolio concentration metrics and diversification analysis'
  },
  '/dashboard/liquidity': {
    title: 'Liquidity',
    subtitle: 'Portfolio liquidity analysis and trading constraints'
  },
  '/dashboard/volatility-sizing': {
    title: 'Volatility Sizing',
    subtitle: 'Dynamic position sizing based on volatility models'
  },
  '/dashboard/tear-sheet': {
    title: 'Performance Tear-Sheet',
    subtitle: 'Your portfolio against NIFTY 50 via the quantstats suite'
  },
  '/dashboard/risk-contribution': {
    title: 'Risk Contribution',
    subtitle: 'Euler decomposition of risk per position and tail attribution'
  },
  '/dashboard/risk-studio': {
    title: 'Risk Studio',
    subtitle: 'Consolidated Euler attribution, EVT tail risk, Copula matrix & Vol Cones'
  },
  '/dashboard/optimize': {
    title: 'Portfolio Optimizer',
    subtitle: 'Rebalance within your holdings across four strategies'
  },
  '/dashboard/regime': {
    title: 'Market Regime',
    subtitle: 'Hidden-Markov state of NIFTY and your portfolio inside it'
  },
  '/dashboard/monte-carlo': {
    title: 'Goal Probability',
    subtitle: 'Monte Carlo odds of hitting a target from your own return history'
  },
  '/dashboard/pairs': {
    title: 'Cointegration & Pairs Scanner',
    subtitle: 'Engle-Granger & Johansen rank tests with OU half-life estimates'
  },
  '/dashboard/india-flows': {
    title: 'India Flows & Microstructure',
    subtitle: 'NSE delivery % spikes, institutional cash flows, and ADV limits'
  },
  '/dashboard/settings': {
    title: 'Settings',
    subtitle: 'Configure dashboard preferences and data sources'
  }
};

export function DashboardLayout({ 
  children, 
  title: customTitle, 
  subtitle: customSubtitle, 
  className 
}: DashboardLayoutProps) {
  const pathname = usePathname();
  const { sidebarOpen, toggleSidebar, darkMode } = useUIStore();
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

  // Handle responsive behavior
  useEffect(() => {
    const checkScreenSize = () => {
      const mobile = window.innerWidth < 1024; // lg breakpoint
      setIsMobile(mobile);
      
      if (!mobile) {
        setMobileSidebarOpen(false);
      }
    };

    checkScreenSize();
    window.addEventListener('resize', checkScreenSize);
    
    return () => window.removeEventListener('resize', checkScreenSize);
  }, []);

  // Handle overlay click on mobile
  const handleOverlayClick = () => {
    setMobileSidebarOpen(false);
  };

  // Get route info
  const routeInfo = routeTitles[pathname] || { title: 'Dashboard', subtitle: undefined };
  const displayTitle = customTitle || routeInfo.title;
  const displaySubtitle = customSubtitle || routeInfo.subtitle;

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      {/* Mobile sidebar overlay */}
      {isMobile && mobileSidebarOpen && (
        <div 
          className="fixed inset-0 z-40 bg-black bg-opacity-50 lg:hidden"
          onClick={handleOverlayClick}
        />
      )}

      {/* Sidebar */}
      <div className={cn(
        'fixed inset-y-0 left-0 z-50 transform transition-transform duration-300 ease-in-out lg:relative lg:translate-x-0',
        mobileSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
      )}>
        <Sidebar
          isCollapsed={!isMobile && !sidebarOpen}
          onToggleCollapse={!isMobile ? toggleSidebar : undefined}
          className="h-full"
        />
      </div>

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <Header
          title={displayTitle}
          subtitle={displaySubtitle}
          onMenuClick={() => setMobileSidebarOpen(true)}
        />

        {/* Page content */}
        <main className={cn(
          'flex-1 overflow-y-auto p-4 lg:p-6',
          className
        )}>
          <div className="mx-auto max-w-7xl">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

export default DashboardLayout;