import { describe, it, expect, beforeEach } from 'vitest';
import { usePortfolioStore, useUIStore, useAnalyticsStore } from '@/lib/store';

describe('useUIStore', () => {
  beforeEach(() => {
    useUIStore.setState({
      darkMode: true,
      sidebarOpen: true,
      liveDataMode: true,
      lastUpdated: null,
    });
  });

  it('toggles dark mode', () => {
    expect(useUIStore.getState().darkMode).toBe(true);
    useUIStore.getState().toggleDarkMode();
    expect(useUIStore.getState().darkMode).toBe(false);
  });

  it('toggles sidebar open state', () => {
    expect(useUIStore.getState().sidebarOpen).toBe(true);
    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarOpen).toBe(false);
  });

  it('toggles live data mode', () => {
    expect(useUIStore.getState().liveDataMode).toBe(true);
    useUIStore.getState().toggleLiveDataMode();
    expect(useUIStore.getState().liveDataMode).toBe(false);
  });

  it('updates last updated timestamp', () => {
    useUIStore.getState().updateLastUpdated();
    expect(useUIStore.getState().lastUpdated).toBeTruthy();
  });
});

describe('useAnalyticsStore', () => {
  beforeEach(() => {
    useAnalyticsStore.getState().clearCache();
  });

  it('sets and gets cached data', () => {
    useAnalyticsStore.getState().setCachedData('risk:INFY.NS', { vol: 0.22 });
    const cached = useAnalyticsStore.getState().getCachedData('risk:INFY.NS');
    expect(cached).toEqual({ vol: 0.22 });
  });

  it('clears specific cache key', () => {
    useAnalyticsStore.getState().setCachedData('key1', 'val1');
    useAnalyticsStore.getState().setCachedData('key2', 'val2');
    useAnalyticsStore.getState().clearCacheKey('key1');
    expect(useAnalyticsStore.getState().getCachedData('key1')).toBeNull();
    expect(useAnalyticsStore.getState().getCachedData('key2')).toBe('val2');
  });
});

describe('usePortfolioStore selection and clear', () => {
  beforeEach(() => {
    usePortfolioStore.setState({
      positions: [
        {
          id: 1,
          ticker: 'INFY.NS',
          weight: 0.5,
          last_price: 1114.0,
          market_value: 111400.0,
          sector: 'Technology',
          industry: 'IT Services',
          added_on: '2025-01-01',
          updated_on: '2025-01-01',
        },
      ],
      selectedTickers: [],
      isLoading: false,
      error: null,
      totalValue: 111400.0,
      totalWeight: 0.5,
    });
  });

  it('sets selected tickers', () => {
    usePortfolioStore.getState().setSelectedTickers(['INFY.NS']);
    expect(usePortfolioStore.getState().selectedTickers).toEqual(['INFY.NS']);
  });

  it('clears error', () => {
    usePortfolioStore.setState({ error: 'Some error' });
    expect(usePortfolioStore.getState().error).toBe('Some error');
    usePortfolioStore.getState().clearError();
    expect(usePortfolioStore.getState().error).toBeNull();
  });

  it('clears positions', () => {
    usePortfolioStore.getState().clearPositions();
    expect(usePortfolioStore.getState().positions).toEqual([]);
    expect(usePortfolioStore.getState().totalValue).toBe(0);
    expect(usePortfolioStore.getState().totalWeight).toBe(0);
  });
});
