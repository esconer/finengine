/**
 * Enhanced hooks for real-time updates and auto-refresh functionality
 */

import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { useRealTimeAnalytics } from '@/lib/websocket';
import { usePortfolioStore, useAnalyticsStore, useUIStore } from '@/lib/store';

// Enhanced auto-refresh hook
export function useAutoRefresh(enabled: boolean = true, interval: number = 300000) {
    const liveDataMode = useUIStore(state => state.liveDataMode);
    const fetchPortfolio = usePortfolioStore(state => state.fetchPortfolio);
    const updateRealTimeData = useAnalyticsStore(state => state.updateRealTimeData);
    const intervalRef = useRef<NodeJS.Timeout | null>(null);
    const isRefreshingRef = useRef(false);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

    const performRefresh = useCallback(async () => {
        if (isRefreshingRef.current) return;

        isRefreshingRef.current = true;
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

            setTimeout(() => {
                updateRealTimeData('analytics', {
                    refreshing: false,
                    timestamp: new Date().toISOString()
                });
                isRefreshingRef.current = false;
                setIsRefreshing(false);
            }, 1000);
        } catch (error) {
            console.error('Auto-refresh failed:', error);
            isRefreshingRef.current = false;
            setIsRefreshing(false);
            updateRealTimeData('analytics', {
                refreshing: false,
                error: error instanceof Error ? error.message : 'Unknown error'
            });
        }
    }, [fetchPortfolio, updateRealTimeData]);

    useEffect(() => {
        // Stop existing interval
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }

        // Start new interval if enabled and live data mode is on
        if (enabled && liveDataMode) {
            intervalRef.current = setInterval(performRefresh, interval);
        }

        return () => {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
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
    const realTimeData = useAnalyticsStore(state => state.realTimeData);
    const fetchPortfolio = usePortfolioStore(state => state.fetchPortfolio);
    const { portfolioData, analyticsData, marketData, lastUpdate, isConnected, subscribe, unsubscribe } = useRealTimeAnalytics();
    const liveDataMode = useUIStore(state => state.liveDataMode);
    const [dataFreshness, setDataFreshness] = useState<'fresh' | 'stale' | 'outdated'>('fresh');
    const [dataAge, setDataAge] = useState<number>(0);

    // Sync analytics store only when actual WebSocket data arrives
    useEffect(() => {
        if (portfolioData) {
            useAnalyticsStore.getState().updateRealTimeData('portfolio', portfolioData);
        }
    }, [portfolioData]);

    useEffect(() => {
        if (analyticsData) {
            useAnalyticsStore.getState().updateRealTimeData('analytics', analyticsData);
        }
    }, [analyticsData]);

    useEffect(() => {
        if (marketData) {
            useAnalyticsStore.getState().updateRealTimeData('market_data', marketData);
        }
    }, [marketData]);

    // Check data freshness periodically without busy re-renders
    useEffect(() => {
        const currentUpdate = lastUpdate || realTimeData.lastUpdate;
        if (!currentUpdate) {
            setDataFreshness('outdated');
            setDataAge(0);
            return;
        }

        const checkFreshness = () => {
            const now = new Date();
            const lastUpdateDate = new Date(currentUpdate);
            const ageMinutes = (now.getTime() - lastUpdateDate.getTime()) / (1000 * 60);

            setDataAge(ageMinutes);

            if (ageMinutes < 1) {
                setDataFreshness('fresh');
            } else if (ageMinutes < 5) {
                setDataFreshness('stale');
            } else {
                setDataFreshness('outdated');
            }
        };

        checkFreshness();
        const freshnessTimer = setInterval(checkFreshness, 30000);
        return () => clearInterval(freshnessTimer);
    }, [lastUpdate, realTimeData.lastUpdate]);

    const refreshData = useCallback(() => {
        fetchPortfolio();
    }, [fetchPortfolio]);

    const mergedPortfolio = useMemo(() => ({
        ...realTimeData.portfolioData,
        ...(portfolioData || {})
    }), [realTimeData.portfolioData, portfolioData]);

    const mergedAnalytics = useMemo(() => ({
        ...realTimeData.analyticsData,
        ...(analyticsData || {})
    }), [realTimeData.analyticsData, analyticsData]);

    const mergedMarket = useMemo(() => ({
        ...realTimeData.marketData,
        ...(marketData || {})
    }), [realTimeData.marketData, marketData]);

    return useMemo(() => ({
        portfolioData: mergedPortfolio,
        analyticsData: mergedAnalytics,
        marketData: mergedMarket,
        lastUpdate: lastUpdate || realTimeData.lastUpdate,
        isConnected: isConnected || realTimeData.isConnected,
        dataFreshness,
        dataAge,
        isLive: liveDataMode,
        refreshData,
        connectionStatus: (isConnected || realTimeData.isConnected) ? ('connected' as const) : ('disconnected' as const),
    }), [
        mergedPortfolio,
        mergedAnalytics,
        mergedMarket,
        lastUpdate,
        realTimeData.lastUpdate,
        isConnected,
        realTimeData.isConnected,
        dataFreshness,
        dataAge,
        liveDataMode,
        refreshData
    ]);
}

export interface Notification {
    id: string;
    type: 'success' | 'error' | 'warning' | 'info';
    title: string;
    message: string;
    timestamp: Date;
    autoHide?: boolean;
    duration?: number;
}

// Module-level shared store for notifications to prevent duplicate state and re-render loops
let globalNotifications: Notification[] = [];
const notificationListeners = new Set<() => void>();

function notifyNotificationListeners() {
    notificationListeners.forEach(listener => listener());
}

// Notification hook for alerts and updates
export function useNotifications() {
    const [notifications, setNotifications] = useState<Notification[]>(globalNotifications);

    useEffect(() => {
        const listener = () => {
            setNotifications([...globalNotifications]);
        };
        notificationListeners.add(listener);
        return () => {
            notificationListeners.delete(listener);
        };
    }, []);

    const removeNotification = useCallback((id: string) => {
        globalNotifications = globalNotifications.filter(n => n.id !== id);
        notifyNotificationListeners();
    }, []);

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

        globalNotifications = [...globalNotifications, notification];
        notifyNotificationListeners();

        // Auto-hide notification if enabled
        if (autoHide) {
            setTimeout(() => {
                globalNotifications = globalNotifications.filter(n => n.id !== id);
                notifyNotificationListeners();
            }, duration);
        }

        return id;
    }, []);

    const clearAll = useCallback(() => {
        globalNotifications = [];
        notifyNotificationListeners();
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

export interface ExportJob {
    id: string;
    filename: string;
    progress: number;
    status: 'pending' | 'processing' | 'completed' | 'error';
    error?: string;
    startedAt: Date;
    completedAt?: Date;
}

let globalExportJobs: Record<string, ExportJob> = {};
const exportListeners = new Set<() => void>();

function notifyExportListeners() {
    exportListeners.forEach(l => l());
}

// Export progress tracking hook
export function useExportProgress() {
    const [exportJobs, setExportJobs] = useState<Record<string, ExportJob>>(globalExportJobs);

    useEffect(() => {
        const listener = () => {
            setExportJobs({ ...globalExportJobs });
        };
        exportListeners.add(listener);
        return () => {
            exportListeners.delete(listener);
        };
    }, []);

    const startExport = useCallback((filename: string, format: string) => {
        const id = `export_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        globalExportJobs = {
            ...globalExportJobs,
            [id]: {
                id,
                filename: `${filename}.${format}`,
                progress: 0,
                status: 'pending',
                startedAt: new Date()
            }
        };
        notifyExportListeners();

        return id;
    }, []);

    const updateExportProgress = useCallback((id: string, progress: number) => {
        if (!globalExportJobs[id]) return;
        globalExportJobs = {
            ...globalExportJobs,
            [id]: {
                ...globalExportJobs[id],
                progress,
                status: progress >= 100 ? 'completed' : 'processing'
            }
        };
        notifyExportListeners();

        // Mark as completed
        if (progress >= 100) {
            setTimeout(() => {
                if (globalExportJobs[id]) {
                    globalExportJobs = {
                        ...globalExportJobs,
                        [id]: {
                            ...globalExportJobs[id],
                            status: 'completed',
                            completedAt: new Date()
                        }
                    };
                    notifyExportListeners();
                }
            }, 500);
        }
    }, []);

    const completeExport = useCallback((id: string, error?: string) => {
        if (!globalExportJobs[id]) return;
        globalExportJobs = {
            ...globalExportJobs,
            [id]: {
                ...globalExportJobs[id],
                status: error ? 'error' : 'completed',
                progress: error ? globalExportJobs[id].progress : 100,
                error,
                completedAt: new Date()
            }
        };
        notifyExportListeners();
    }, []);

    const removeExport = useCallback((id: string) => {
        const { [id]: removed, ...rest } = globalExportJobs;
        globalExportJobs = rest;
        notifyExportListeners();
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