/**
 * Enhanced hooks for real-time updates and auto-refresh functionality
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { useRealTimeAnalytics } from '@/lib/websocket';
import { usePortfolioStore, useAnalyticsStore, useUIStore } from '@/lib/store';

// Enhanced auto-refresh hook
export function useAutoRefresh(enabled: boolean = true, interval: number = 300000) {
    const { liveDataMode } = useUIStore();
    const { fetchPortfolio } = usePortfolioStore();
    const { updateRealTimeData } = useAnalyticsStore();
    const intervalRef = useRef<NodeJS.Timeout | null>(null);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

    const performRefresh = useCallback(async () => {
        if (isRefreshing) return;

        setIsRefreshing(true);
        try {
            // Update portfolio
            await fetchPortfolio();

            // Update real-time analytics data
            updateRealTimeData('analytics', {
                refreshing: true,
                timestamp: new Date().toISOString()
            });

            setLastRefresh(new Date());

            // Simulate API call delay
            setTimeout(() => {
                updateRealTimeData('analytics', {
                    refreshing: false,
                    timestamp: new Date().toISOString()
                });
                setIsRefreshing(false);
            }, 1000);
        } catch (error) {
            console.error('Auto-refresh failed:', error);
            setIsRefreshing(false);
            updateRealTimeData('analytics', {
                refreshing: false,
                error: error instanceof Error ? error.message : 'Unknown error'
            });
        }
    }, [fetchPortfolio, updateRealTimeData, isRefreshing]);

    useEffect(() => {
        // Stop existing interval
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
        }

        // Start new interval if enabled and live data mode is on
        if (enabled && liveDataMode) {
            intervalRef.current = setInterval(performRefresh, interval);
        }

        return () => {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
            }
        };
    }, [enabled, liveDataMode, interval, performRefresh]);

    const refresh = useCallback(() => {
        performRefresh();
    }, [performRefresh]);

    return {
        isRefreshing,
        lastRefresh,
        refresh,
        isEnabled: enabled && liveDataMode
    };
}

// Enhanced real-time analytics hook with automatic updates
export function useEnhancedRealTimeAnalytics() {
    const { realTimeData } = useAnalyticsStore();
    const { portfolioData, analyticsData, marketData, lastUpdate, isConnected, subscribe, unsubscribe } = useRealTimeAnalytics();
    const { liveDataMode } = useUIStore();
    const [dataFreshness, setDataFreshness] = useState<'fresh' | 'stale' | 'outdated'>('fresh');
    const [dataAge, setDataAge] = useState<number>(0);

    // Update analytics store when WebSocket data changes
    useEffect(() => {
        if (portfolioData) {
            useAnalyticsStore.getState().updateRealTimeData('portfolio', portfolioData);
        }
        if (analyticsData) {
            useAnalyticsStore.getState().updateRealTimeData('analytics', analyticsData);
        }
        if (marketData) {
            useAnalyticsStore.getState().updateRealTimeData('market_data', marketData);
        }
    }, [portfolioData, analyticsData, marketData]);

    // Check data freshness
    useEffect(() => {
        if (!lastUpdate) {
            setDataFreshness('outdated');
            setDataAge(0);
            return;
        }

        const now = new Date();
        const lastUpdateDate = new Date(lastUpdate);
        const ageMinutes = (now.getTime() - lastUpdateDate.getTime()) / (1000 * 60);

        setDataAge(ageMinutes);

        if (ageMinutes < 1) {
            setDataFreshness('fresh');
        } else if (ageMinutes < 5) {
            setDataFreshness('stale');
        } else {
            setDataFreshness('outdated');
        }
    }, [lastUpdate]);

    // Auto-subscribe to topics when live mode is enabled
    useEffect(() => {
        if (liveDataMode && isConnected) {
            subscribe('analytics');
            subscribe('market_data');
            subscribe('portfolio');

            // Ping every 30 seconds to keep connection alive
            const pingInterval = setInterval(() => {
                if (isConnected) {
                    // Send ping via WebSocket
                    console.log('Sending WebSocket ping');
                }
            }, 30000);

            return () => {
                clearInterval(pingInterval);
                unsubscribe('analytics');
                unsubscribe('market_data');
                unsubscribe('portfolio');
            };
        }
    }, [liveDataMode, isConnected, subscribe, unsubscribe]);

    return {
        // Data
        portfolioData: { ...realTimeData.portfolioData, ...portfolioData },
        analyticsData: { ...realTimeData.analyticsData, ...analyticsData },
        marketData: { ...realTimeData.marketData, ...marketData },
        lastUpdate: lastUpdate || realTimeData.lastUpdate,
        isConnected: isConnected || realTimeData.isConnected,

        // Status
        dataFreshness,
        dataAge,
        isLive: liveDataMode,

        // Actions
        refreshData: useCallback(() => {
            // Trigger manual refresh
            console.log('Manual data refresh triggered');
        }, []),

        // Connection status
        connectionStatus: isConnected ? 'connected' : 'disconnected',
    };
}

// Notification hook for alerts and updates
export function useNotifications() {
    interface Notification {
        id: string;
        type: 'success' | 'error' | 'warning' | 'info';
        title: string;
        message: string;
        timestamp: Date;
        autoHide?: boolean;
        duration?: number;
    }

    const [notifications, setNotifications] = useState<Notification[]>([]);

    const addNotification = useCallback((
        type: 'success' | 'error' | 'warning' | 'info',
        title: string,
        message: string,
        autoHide: boolean = true,
        duration: number = 5000
    ) => {
        const id = `notification_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        const notification: Notification = {
            id,
            type,
            title,
            message,
            timestamp: new Date(),
            autoHide,
            duration
        };

        setNotifications(prev => [...prev, notification]);

        // Auto-hide notification if enabled
        if (autoHide) {
            setTimeout(() => {
                removeNotification(id);
            }, duration);
        }

        return id;
    }, []);

    const removeNotification = useCallback((id: string) => {
        setNotifications(prev => prev.filter(n => n.id !== id));
    }, []);

    const clearAll = useCallback(() => {
        setNotifications([]);
    }, []);

    // Risk alerts
    const showRiskAlert = useCallback((riskLevel: string, details: any) => {
        const type = riskLevel === 'high' ? 'error' : riskLevel === 'medium' ? 'warning' : 'info';
        addNotification(
            type,
            `Risk Alert: ${riskLevel.toUpperCase()}`,
            details.message || 'Portfolio risk metrics have changed significantly',
            true,
            riskLevel === 'high' ? 10000 : 5000
        );
    }, [addNotification]);

    // Connection alerts
    const showConnectionAlert = useCallback((connected: boolean) => {
        if (connected) {
            addNotification(
                'success',
                'Real-time Updates Connected',
                'Live data feeds are now active',
                true,
                3000
            );
        } else {
            addNotification(
                'warning',
                'Real-time Updates Disconnected',
                'Falling back to manual refresh mode',
                true,
                5000
            );
        }
    }, [addNotification]);

    return {
        notifications,
        addNotification,
        removeNotification,
        clearAll,
        showRiskAlert,
        showConnectionAlert
    };
}

// Export progress tracking hook
export function useExportProgress() {
    interface ExportJob {
        id: string;
        filename: string;
        progress: number;
        status: 'pending' | 'processing' | 'completed' | 'error';
        error?: string;
        startedAt: Date;
        completedAt?: Date;
    }

    const [exportJobs, setExportJobs] = useState<Record<string, ExportJob>>({});

    const startExport = useCallback((filename: string, format: string) => {
        const id = `export_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        setExportJobs(prev => ({
            ...prev,
            [id]: {
                id,
                filename: `${filename}.${format}`,
                progress: 0,
                status: 'pending',
                startedAt: new Date()
            }
        }));

        return id;
    }, []);

    const updateExportProgress = useCallback((id: string, progress: number) => {
        setExportJobs(prev => ({
            ...prev,
            [id]: {
                ...prev[id],
                progress,
                status: progress >= 100 ? 'completed' : 'processing'
            }
        }));

        // Mark as completed
        if (progress >= 100) {
            setTimeout(() => {
                setExportJobs(prev => ({
                    ...prev,
                    [id]: {
                        ...prev[id],
                        status: 'completed',
                        completedAt: new Date()
                    }
                }));
            }, 500);
        }
    }, []);

    const completeExport = useCallback((id: string, error?: string) => {
        setExportJobs(prev => ({
            ...prev,
            [id]: {
                ...prev[id],
                status: error ? 'error' : 'completed',
                progress: error ? prev[id].progress : 100,
                error,
                completedAt: new Date()
            }
        }));
    }, []);

    const removeExport = useCallback((id: string) => {
        setExportJobs(prev => {
            const { [id]: removed, ...rest } = prev;
            return rest;
        });
    }, []);

    const getActiveExports = useCallback(() => {
        return Object.values(exportJobs).filter(exp =>
            exp.status === 'pending' || exp.status === 'processing'
        );
    }, [exportJobs]);

    return {
        exports: exportJobs,
        startExport,
        updateExportProgress,
        completeExport,
        removeExport,
        getActiveExports
    };
}

// Dashboard preferences hook
export function useDashboardPreferences() {
    const [preferences, setPreferences] = useState({
        autoRefresh: true,
        refreshInterval: 300000, // 5 minutes
        notifications: true,
        darkMode: false,
        compactView: false,
        showRealTimeIndicators: true,
        defaultChartType: 'line',
        decimalPlaces: 2,
        currency: 'USD',
        dateFormat: 'MM/dd/yyyy',
        timeFormat: '12h',
    });

    useEffect(() => {
        // Load preferences from localStorage
        const saved = localStorage.getItem('daisy_dashboard_preferences');
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                setPreferences(prev => ({ ...prev, ...parsed }));
            } catch (error) {
                console.error('Failed to load dashboard preferences:', error);
            }
        }
    }, []);

    const updatePreference = useCallback((key: string, value: any) => {
        setPreferences(prev => {
            const updated = { ...prev, [key]: value };
            localStorage.setItem('daisy_dashboard_preferences', JSON.stringify(updated));
            return updated;
        });
    }, []);

    const resetToDefaults = useCallback(() => {
        const defaults = {
            autoRefresh: true,
            refreshInterval: 300000,
            notifications: true,
            darkMode: false,
            compactView: false,
            showRealTimeIndicators: true,
            defaultChartType: 'line',
            decimalPlaces: 2,
            currency: 'USD',
            dateFormat: 'MM/dd/yyyy',
            timeFormat: '12h',
        };
        setPreferences(defaults);
        localStorage.setItem('daisy_dashboard_preferences', JSON.stringify(defaults));
    }, []);

    return {
        preferences,
        updatePreference,
        resetToDefaults
    };
}

// Date range selection hook
export function useDateRangeSelection() {
    const [dateRange, setDateRange] = useState({
        start: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000), // 90 days ago
        end: new Date(),
        preset: '3M' // '1D', '1W', '1M', '3M', '6M', '1Y', 'ALL'
    });

    const [isSelecting, setIsSelecting] = useState(false);

    const presets: Record<string, () => { start: Date; end: Date; preset: string }> = {
        '1D': () => ({
            start: new Date(Date.now() - 24 * 60 * 60 * 1000),
            end: new Date(),
            preset: '1D'
        }),
        '1W': () => ({
            start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
            end: new Date(),
            preset: '1W'
        }),
        '1M': () => ({
            start: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000),
            end: new Date(),
            preset: '1M'
        }),
        '3M': () => ({
            start: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000),
            end: new Date(),
            preset: '3M'
        }),
        '6M': () => ({
            start: new Date(Date.now() - 180 * 24 * 60 * 60 * 1000),
            end: new Date(),
            preset: '6M'
        }),
        '1Y': () => ({
            start: new Date(Date.now() - 365 * 24 * 60 * 60 * 1000),
            end: new Date(),
            preset: '1Y'
        }),
        'ALL': () => ({
            start: new Date('2020-01-01'),
            end: new Date(),
            preset: 'ALL'
        })
    };

    const setPreset = useCallback((preset: string) => {
        if (presets[preset]) {
            setDateRange(presets[preset]());
        }
    }, []);

    const setCustomRange = useCallback((start: Date, end: Date) => {
        setDateRange(prev => ({
            ...prev,
            start,
            end,
            preset: 'CUSTOM'
        }));
    }, []);

    const formatDateRange = useCallback(() => {
        return {
            start: dateRange.start.toISOString().split('T')[0],
            end: dateRange.end.toISOString().split('T')[0]
        };
    }, [dateRange]);

    return {
        dateRange,
        isSelecting,
        setIsSelecting,
        setPreset,
        setCustomRange,
        formatDateRange
    };
}