/**
 * Sidebar navigation component for the FinEngine dashboard
 * Features responsive design with collapsible sidebar and proper navigation highlighting
 */

'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
    LayoutDashboard,
    TrendingDown,
    TrendingUp,
    Target,
    TestTube,
    BarChart3,
    Droplets,
    Zap,
    ChevronLeft,
    ChevronRight,
    Settings,
    Newspaper,
    PieChart,
    SlidersHorizontal,
    Radar,
    BookOpen,
    Filter,
} from 'lucide-react';

import { cn } from '@/lib/utils';

interface NavigationItem {
    name: string;
    href: string;
    icon: React.ComponentType<{ className?: string }>;
    description?: string;
    title?: string;
    subtitle?: string;
    footer?: boolean;
}

export const navigation: NavigationItem[] = [
    {
        name: 'Summary',
        href: '/dashboard',
        icon: LayoutDashboard,
        description: 'Portfolio overview and key metrics',
        title: 'Portfolio Summary',
        subtitle: 'Overview of your portfolio performance and key metrics'
    },
    {
        name: 'Equity Research',
        href: '/dashboard/equity-research',
        icon: BookOpen,
        description: 'Bloomberg-grade equity terminal, concall audio & financial models'
    },
    {
        name: 'Screener Studio',
        href: '/dashboard/screener-studio',
        icon: Filter,
        description: 'Coffee Can, Magic Formula & compounder screens'
    },
    {
        name: 'Realized Risk',
        href: '/dashboard/realized-risk',
        icon: TrendingDown,
        description: 'Historical risk metrics and performance',
        subtitle: 'Historical risk metrics and portfolio performance analysis'
    },
    {
        name: 'Forecast Risk',
        href: '/dashboard/forecast-risk',
        icon: TrendingUp,
        description: 'Future risk projections and VaR forecasts',
        subtitle: 'Future risk projections and Value-at-Risk forecasts'
    },
    {
        name: 'Factor Exposure',
        href: '/dashboard/factor-exposure',
        icon: Target,
        description: 'Multi-factor risk analysis',
        subtitle: 'Multi-factor risk analysis and exposure metrics'
    },
    {
        name: 'Stress Testing',
        href: '/dashboard/stress-testing',
        icon: TestTube,
        description: 'Portfolio stress testing scenarios',
        subtitle: 'Portfolio stress testing scenarios and impact analysis'
    },
    {
        name: 'Concentration',
        href: '/dashboard/concentration',
        icon: BarChart3,
        description: 'Portfolio concentration metrics',
        subtitle: 'Portfolio concentration metrics and diversification analysis'
    },
    {
        name: 'Liquidity',
        href: '/dashboard/liquidity',
        icon: Droplets,
        description: 'Liquidity analysis and metrics',
        subtitle: 'Portfolio liquidity analysis and trading constraints'
    },
    {
        name: 'Volatility Sizing',
        href: '/dashboard/volatility-sizing',
        icon: Zap,
        description: 'Dynamic position sizing based on volatility',
        subtitle: 'Dynamic position sizing based on volatility models'
    },
    {
        name: 'Tear-Sheet',
        href: '/dashboard/tear-sheet',
        icon: Newspaper,
        description: 'Full performance suite vs NIFTY 50',
        title: 'Performance Tear-Sheet',
        subtitle: 'Your portfolio against NIFTY 50 via the quantstats suite'
    },
    {
        name: 'Risk Contribution',
        href: '/dashboard/risk-contribution',
        icon: PieChart,
        description: 'Which positions drive your risk',
        subtitle: 'Euler decomposition of risk per position and tail attribution'
    },
    {
        name: 'Risk Studio',
        href: '/dashboard/risk-studio',
        icon: Zap,
        description: 'Consolidated multi-model risk canvas',
        subtitle: 'Consolidated Euler attribution, EVT tail risk, Copula matrix & Vol Cones'
    },
    {
        name: 'Optimizer',
        href: '/dashboard/optimize',
        icon: SlidersHorizontal,
        description: 'Rebalance within your holdings',
        title: 'Portfolio Optimizer',
        subtitle: 'Rebalance within your holdings across four strategies'
    },
    {
        name: 'Market Regime',
        href: '/dashboard/regime',
        icon: Radar,
        description: 'HMM state of NIFTY and your book',
        subtitle: 'Hidden-Markov state of NIFTY and your portfolio inside it'
    },
    {
        name: 'Goal Probability',
        href: '/dashboard/monte-carlo',
        icon: Target,
        description: 'Monte Carlo odds of hitting a target',
        subtitle: 'Monte Carlo odds of hitting a target from your own return history'
    },
    {
        name: 'Pairs Scanner',
        href: '/dashboard/pairs',
        icon: Radar,
        description: 'Cointegration & statistical arbitrage scanner',
        title: 'Cointegration & Pairs Scanner',
        subtitle: 'Engle-Granger & Johansen rank tests with OU half-life estimates'
    },
    {
        name: 'India Microstructure',
        href: '/dashboard/india-flows',
        icon: Zap,
        description: 'NSE delivery spikes & institutional flows',
        title: 'India Flows & Microstructure',
        subtitle: 'NSE delivery % spikes, institutional cash flows, and ADV limits'
    },
    {
        name: 'Portfolio Management',
        href: '/portfolio/manage',
        icon: BarChart3,
        description: 'Manage your investment portfolio'
    },
    {
        name: 'Settings',
        href: '/dashboard/settings',
        icon: Settings,
        description: 'Configure dashboard preferences and data sources',
        subtitle: 'Configure dashboard preferences and data sources',
        footer: true
    }
];

interface SidebarProps {
    isCollapsed?: boolean;
    onToggleCollapse?: () => void;
    className?: string;
}

export function Sidebar({ isCollapsed = false, onToggleCollapse, className }: SidebarProps) {
    const pathname = usePathname();

    const isActiveRoute = (href: string) => {
        if (href === '/dashboard') {
            return pathname === '/dashboard' || pathname === '/dashboard/';
        }
        return pathname.startsWith(href);
    };

    return (
        <aside
            className={cn(
                'relative flex flex-col bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 transition-all duration-300 ease-in-out',
                isCollapsed ? 'w-16' : 'w-64',
                className
            )}
        >
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
                {!isCollapsed && (
                    <div className="flex items-center space-x-2">
                        <div className="flex items-center justify-center w-8 h-8 bg-blue-600 rounded-lg">
                            <BarChart3 className="w-5 h-5 text-white" />
                        </div>
                        <span className="text-lg font-semibold text-gray-900 dark:text-white">
                            FinEngine
                        </span>
                    </div>
                )}

                {onToggleCollapse && (
                    <button
                        onClick={onToggleCollapse}
                        className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                        aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                    >
                        {isCollapsed ? (
                            <ChevronRight className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                        ) : (
                            <ChevronLeft className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                        )}
                    </button>
                )}
            </div>

            {/* Navigation */}
            <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
                {navigation.filter((item) => !item.footer).map((item) => {
                    const isActive = isActiveRoute(item.href);
                    const Icon = item.icon;

                    return (
                        <Link
                            key={item.name}
                            href={item.href}
                            aria-current={isActive ? 'page' : undefined}
                            className={cn(
                                'group flex items-center rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200',
                                isActive
                                    ? 'bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300'
                                    : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white',
                                isCollapsed ? 'justify-center' : 'justify-start'
                            )}
                            title={isCollapsed ? item.name : undefined}
                        >
                            <Icon
                                className={cn(
                                    'flex-shrink-0 w-5 h-5 transition-colors',
                                    isActive
                                        ? 'text-blue-700 dark:text-blue-300'
                                        : 'text-gray-500 dark:text-gray-400 group-hover:text-gray-700 dark:group-hover:text-gray-300'
                                )}
                            />

                            {!isCollapsed && (
                                <div className="ml-3 min-w-0">
                                    <span className="block text-sm font-medium truncate">
                                        {item.name}
                                    </span>
                                    {item.description && (
                                        <span className="block text-xs text-gray-500 dark:text-gray-400 truncate">
                                            {item.description}
                                        </span>
                                    )}
                                </div>
                            )}
                        </Link>
                    );
                })}
            </nav>

            {/* Footer */}
            <div className="p-4 border-t border-gray-200 dark:border-gray-700">
                {navigation.filter((item) => item.footer).map((item) => {
                    const isActive = isActiveRoute(item.href);
                    const Icon = item.icon;

                    return (
                        <Link
                            key={item.name}
                            href={item.href}
                            aria-current={isActive ? 'page' : undefined}
                            className={cn(
                                'group flex items-center rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                                isActive
                                    ? 'bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300'
                                    : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white',
                                isCollapsed && 'justify-center px-0'
                            )}
                            title={isCollapsed ? item.name : undefined}
                        >
                            <Icon className="w-5 h-5 flex-shrink-0 text-gray-500 dark:text-gray-400 group-hover:text-gray-700 dark:group-hover:text-gray-300" />
                            {!isCollapsed && <span className="ml-3">{item.name}</span>}
                        </Link>
                    );
                })}
            </div>
        </aside>
    );
}

export default Sidebar;