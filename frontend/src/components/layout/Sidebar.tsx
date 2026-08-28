/**
 * Sidebar navigation component for the Daisy Risk Engine dashboard
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
}

const navigation: NavigationItem[] = [
    {
        name: 'Summary',
        href: '/dashboard',
        icon: LayoutDashboard,
        description: 'Portfolio overview and key metrics'
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
        description: 'Historical risk metrics and performance'
    },
    {
        name: 'Forecast Risk',
        href: '/dashboard/forecast-risk',
        icon: TrendingUp,
        description: 'Future risk projections and VaR forecasts'
    },
    {
        name: 'Factor Exposure',
        href: '/dashboard/factor-exposure',
        icon: Target,
        description: 'Multi-factor risk analysis'
    },
    {
        name: 'Stress Testing',
        href: '/dashboard/stress-testing',
        icon: TestTube,
        description: 'Portfolio stress testing scenarios'
    },
    {
        name: 'Concentration',
        href: '/dashboard/concentration',
        icon: BarChart3,
        description: 'Portfolio concentration metrics'
    },
    {
        name: 'Liquidity',
        href: '/dashboard/liquidity',
        icon: Droplets,
        description: 'Liquidity analysis and metrics'
    },
    {
        name: 'Volatility Sizing',
        href: '/dashboard/volatility-sizing',
        icon: Zap,
        description: 'Dynamic position sizing based on volatility'
    },
    {
        name: 'Tear-Sheet',
        href: '/dashboard/tear-sheet',
        icon: Newspaper,
        description: 'Full performance suite vs NIFTY 50'
    },
    {
        name: 'Risk Contribution',
        href: '/dashboard/risk-contribution',
        icon: PieChart,
        description: 'Which positions drive your risk'
    },
    {
        name: 'Risk Studio',
        href: '/dashboard/risk-studio',
        icon: Zap,
        description: 'Consolidated multi-model risk canvas'
    },
    {
        name: 'Optimizer',
        href: '/dashboard/optimize',
        icon: SlidersHorizontal,
        description: 'Rebalance within your holdings'
    },
    {
        name: 'Market Regime',
        href: '/dashboard/regime',
        icon: Radar,
        description: 'HMM state of NIFTY and your book'
    },
    {
        name: 'Goal Probability',
        href: '/dashboard/monte-carlo',
        icon: Target,
        description: 'Monte Carlo odds of hitting a target'
    },
    {
        name: 'Pairs Scanner',
        href: '/dashboard/pairs',
        icon: Radar,
        description: 'Cointegration & statistical arbitrage scanner'
    },
    {
        name: 'India Microstructure',
        href: '/dashboard/india-flows',
        icon: Zap,
        description: 'NSE delivery spikes & institutional flows'
    },
    {
        name: 'Portfolio Management',
        href: '/portfolio/manage',
        icon: BarChart3,
        description: 'Manage your investment portfolio'
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
                            Daisy Risk Engine
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
                {navigation.map((item) => {
                    const isActive = isActiveRoute(item.href);
                    const Icon = item.icon;

                    return (
                        <Link
                            key={item.name}
                            href={item.href}
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
            {!isCollapsed && (
                <div className="p-4 border-t border-gray-200 dark:border-gray-700">
                    <Link
                        href="/dashboard/settings"
                        className="group flex items-center rounded-lg px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white transition-colors"
                    >
                        <Settings className="w-5 h-5 text-gray-500 dark:text-gray-400 group-hover:text-gray-700 dark:group-hover:text-gray-300" />
                        <span className="ml-3">Settings</span>
                    </Link>
                </div>
            )}
        </aside>
    );
}

export default Sidebar;