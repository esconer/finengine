/**
 * Zustand store for Daisy Risk Engine state management
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { portfolioApi, analyticsApi, dataApi } from './api';
import { WebSocketClient } from './websocket';

// Types
export interface PortfolioPosition {
    id: number;
    ticker: string;
    weight: number;
    last_price: number;
    market_value: number;
    sector: string;
    industry: string;
    custom_name?: string;
    added_on: string;
    updated_on: string;
}

export interface PortfolioStore {
    positions: PortfolioPosition[];
    selectedTickers: string[];
    isLoading: boolean;
    error: string | null;
    totalValue: number;
    totalWeight: number;

    // Actions
    fetchPortfolio: () => Promise<void>;
    addPosition: (position: {
        ticker: string;
        weight: number;
        region?: string;
        custom_name?: string;
    }) => Promise<void>;
    bulkAddPositions: (positions: Array<{
        ticker: string;
        weight: number;
        region?: string;
        custom_name?: string;
    }>, autoNormalize?: boolean) => Promise<void>;
    updatePosition: (ticker: string, updates: {
        weight?: number;
        custom_name?: string;
    }) => Promise<void>;
    removePosition: (ticker: string) => Promise<void>;
    setSelectedTickers: (tickers: string[]) => void;
    clearError: () => void;
    clearPositions: () => void;
}

export interface UIStore {
    darkMode: boolean;
    sidebarOpen: boolean;
    liveDataMode: boolean;
    lastUpdated: string | null;

    // Actions
    toggleDarkMode: () => void;
    toggleSidebar: () => void;
    toggleLiveDataMode: () => void;
    updateLastUpdated: () => void;
}

export interface AnalyticsStore {
    cache: Map<string, any>;
    isCalculating: boolean;
    realTimeData: {
        analyticsData: any;
        marketData: any;
        portfolioData: any;
        lastUpdate: string | null;
        isConnected: boolean;
    };

    // Actions
    setCachedData: (key: string, data: any) => void;
    getCachedData: (key: string) => any;
    clearCache: () => void;
    clearCacheKey: (key: string) => void;
    updateRealTimeData: (type: string, data: any) => void;
    setWebSocketConnection: (connected: boolean) => void;
}

// Portfolio Store
export const usePortfolioStore = create<PortfolioStore>()(
    persist(
        (set, get) => ({
            positions: [],
            selectedTickers: [],
            isLoading: false,
            error: null,
            totalValue: 0,
            totalWeight: 0,

            fetchPortfolio: async () => {
                set({ isLoading: true, error: null });
                try {
                    const data = await portfolioApi.getPortfolio();
                    set({
                        positions: data.positions || [],
                        totalValue: data.total_value || 0,
                        totalWeight: data.total_weight || 0,
                        isLoading: false,
                    });
                } catch (error: any) {
                    set({
                        error: error.response?.data?.detail || error.message || 'Failed to fetch portfolio',
                        isLoading: false,
                    });
                }
            },

            addPosition: async (positionData) => {
                set({ isLoading: true, error: null });
                try {
                    const newPosition = await portfolioApi.addPosition(positionData);
                    const currentPositions = get().positions;
                    set({
                        positions: [...currentPositions, newPosition],
                        isLoading: false,
                    });
                    // Refresh portfolio to get updated totals
                    await get().fetchPortfolio();
                } catch (error: any) {
                    set({
                        error: error.response?.data?.detail || error.message || 'Failed to add position',
                        isLoading: false,
                    });
                }
            },

            bulkAddPositions: async (positions, autoNormalize = true) => {
                set({ isLoading: true, error: null });
                try {
                    const result = await portfolioApi.bulkAddPositions({
                        positions,
                        auto_normalize: autoNormalize,
                    });
                    set({ isLoading: false });
                    // Refresh portfolio to get updated data
                    await get().fetchPortfolio();
                } catch (error: any) {
                    set({
                        error: error.response?.data?.detail || error.message || 'Failed to add positions',
                        isLoading: false,
                    });
                }
            },

            updatePosition: async (ticker, updates) => {
                set({ isLoading: true, error: null });
                try {
                    await portfolioApi.updatePosition(ticker, updates);
                    // Refresh portfolio to get updated data
                    await get().fetchPortfolio();
                } catch (error: any) {
                    set({
                        error: error.response?.data?.detail || error.message || 'Failed to update position',
                        isLoading: false,
                    });
                }
            },

            removePosition: async (ticker) => {
                set({ isLoading: true, error: null });
                try {
                    await portfolioApi.deletePosition(ticker);
                    const currentPositions = get().positions;
                    set({
                        positions: currentPositions.filter(p => p.ticker !== ticker),
                        isLoading: false,
                    });
                    // Refresh portfolio to get updated totals
                    await get().fetchPortfolio();
                } catch (error: any) {
                    set({
                        error: error.response?.data?.detail || error.message || 'Failed to remove position',
                        isLoading: false,
                    });
                }
            },

            setSelectedTickers: (tickers) => {
                set({ selectedTickers: tickers });
            },

            clearError: () => {
                set({ error: null });
            },

            clearPositions: () => {
                set({
                    positions: [],
                    selectedTickers: [],
                    totalValue: 0,
                    totalWeight: 0,
                    error: null,
                });
            },
        }),
        {
            name: 'portfolio-store',
            partialize: (state) => ({
                positions: state.positions,
                selectedTickers: state.selectedTickers,
            }),
        }
    )
);

// UI Store
export const useUIStore = create<UIStore>()(
    persist(
        (set) => ({
            darkMode: false,
            sidebarOpen: true,
            liveDataMode: true,
            lastUpdated: null,

            toggleDarkMode: () => {
              set((state) => {
                const newDarkMode = !state.darkMode;
                // Apply dark mode to document
                if (typeof document !== 'undefined') {
                  document.documentElement.classList.toggle('dark', newDarkMode);
                }
                return { darkMode: newDarkMode };
              });
            },

            toggleSidebar: () => {
                set((state) => ({ sidebarOpen: !state.sidebarOpen }));
            },

            toggleLiveDataMode: () => {
                set((state) => ({ liveDataMode: !state.liveDataMode }));
            },

            updateLastUpdated: () => {
                set({ lastUpdated: new Date().toISOString() });
            },
        }),
        {
            name: 'ui-store',
            partialize: (state) => ({
                darkMode: state.darkMode,
                sidebarOpen: state.sidebarOpen,
                liveDataMode: state.liveDataMode,
            }),
        }
    )
);

// Analytics Store
export const useAnalyticsStore = create<AnalyticsStore>((set, get) => ({
    cache: new Map(),
    isCalculating: false,
    realTimeData: {
        analyticsData: {},
        marketData: {},
        portfolioData: {},
        lastUpdate: null,
        isConnected: false,
    },

    setCachedData: (key, data) => {
        const currentCache = get().cache;
        currentCache.set(key, {
            data,
            timestamp: Date.now(),
        });
        set({ cache: new Map(currentCache) });
    },

    getCachedData: (key) => {
        const cache = get().cache;
        const cached = cache.get(key);

        if (!cached) return null;

        // Check if cache is expired (5 minutes TTL)
        const isExpired = Date.now() - cached.timestamp > 5 * 60 * 1000;
        if (isExpired) {
            cache.delete(key);
            set({ cache: new Map(cache) });
            return null;
        }

        return cached.data;
    },

    clearCache: () => {
        set({ cache: new Map() });
    },

    clearCacheKey: (key) => {
        const cache = get().cache;
        cache.delete(key);
        set({ cache: new Map(cache) });
    },

    updateRealTimeData: (type, data) => {
        const currentRealTimeData = get().realTimeData;
        
        switch (type) {
            case 'analytics':
                set({
                    realTimeData: {
                        ...currentRealTimeData,
                        analyticsData: { ...currentRealTimeData.analyticsData, ...data },
                        lastUpdate: new Date().toISOString(),
                    }
                });
                break;
            case 'market_data':
                set({
                    realTimeData: {
                        ...currentRealTimeData,
                        marketData: data,
                        lastUpdate: new Date().toISOString(),
                    }
                });
                break;
            case 'portfolio':
                set({
                    realTimeData: {
                        ...currentRealTimeData,
                        portfolioData: data,
                        lastUpdate: new Date().toISOString(),
                    }
                });
                break;
        }
    },

    setWebSocketConnection: (connected) => {
        const currentRealTimeData = get().realTimeData;
        set({
            realTimeData: {
                ...currentRealTimeData,
                isConnected: connected,
            }
        });
    },
}));

// Hook for auto-refresh functionality
export const useAutoRefresh = (enabled: boolean = true, interval: number = 300000) => {
    const { liveDataMode } = useUIStore();
    const { fetchPortfolio } = usePortfolioStore();
    const { updateRealTimeData } = useAnalyticsStore();
    
    // This would be implemented with useEffect in a React component
    // For now, this is a placeholder for the hook structure
    return {
        start: () => console.log('Auto-refresh started'),
        stop: () => console.log('Auto-refresh stopped'),
        refreshAnalytics: () => {
            // Trigger analytics refresh
            updateRealTimeData('analytics', { refreshing: true });
            setTimeout(() => {
                updateRealTimeData('analytics', { refreshing: false });
            }, 1000);
        },
    };
};

// Hook for CSV export functionality
export const useCSVExport = <T>(data: T[], filename: string) => {
    const exportData = () => {
        if (!data || data.length === 0) {
            console.warn('No data to export');
            return;
        }

        // Convert data to CSV
        const csvContent = convertToCSV(data);
        downloadCSV(csvContent, `${filename}.csv`);
    };

    return { export: exportData };
};

// Helper functions
const convertToCSV = (data: any[]): string => {
    if (data.length === 0) return '';

    const headers = Object.keys(data[0]);
    const csvRows = [
        headers.join(','), // Header row
        ...data.map(row =>
            headers.map(header => {
                const value = row[header];
                // Handle values that might contain commas
                if (typeof value === 'string' && value.includes(',')) {
                    return `"${value}"`;
                }
                return value;
            }).join(',')
        )
    ];

    return csvRows.join('\n');
};

const downloadCSV = (content: string, filename: string) => {
    const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');

    if (link.download !== undefined) {
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
};