import { describe, it, expect, beforeEach, vi } from 'vitest';
import { usePortfolioStore, useUIStore, useAnalyticsStore } from '@/lib/store';
import { portfolioApi } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  portfolioApi: {
    getPortfolio: vi.fn(),
    addPosition: vi.fn(),
    bulkAddPositions: vi.fn(),
    updatePosition: vi.fn(),
    deletePosition: vi.fn(),
  },
  analyticsApi: {},
  dataApi: {},
}));

const emptySummary = {
  positions: [],
  total_value: 0,
  total_weight: 0,
  total_positions: 0,
  sectors: {},
};

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

describe('fetchPortfolio success contract (04-B10)', () => {
  beforeEach(() => {
    vi.mocked(portfolioApi.getPortfolio).mockReset();
    usePortfolioStore.setState({ error: null, isLoading: false });
  });

  it('returns true on success', async () => {
    vi.mocked(portfolioApi.getPortfolio).mockResolvedValueOnce(emptySummary);
    const ok = await usePortfolioStore.getState().fetchPortfolio();
    expect(ok).toBe(true);
    expect(usePortfolioStore.getState().error).toBeNull();
  });

  it('returns false and surfaces the message on failure — callers must not stamp freshness', async () => {
    vi.mocked(portfolioApi.getPortfolio).mockRejectedValueOnce(new Error('service down'));
    const ok = await usePortfolioStore.getState().fetchPortfolio();
    expect(ok).toBe(false);
    expect(usePortfolioStore.getState().error).toBe('service down');
  });
});

describe('bulkAddPositions partial failure surfacing (04-B13)', () => {
  beforeEach(() => {
    vi.mocked(portfolioApi.bulkAddPositions).mockReset();
    vi.mocked(portfolioApi.getPortfolio).mockReset();
    vi.mocked(portfolioApi.getPortfolio).mockResolvedValue(emptySummary);
    usePortfolioStore.setState({ error: null, isLoading: false, positions: [] });
  });

  it('sets store.error with the failed count when result.failed > 0', async () => {
    vi.mocked(portfolioApi.bulkAddPositions).mockResolvedValueOnce({
      success: false,
      added: 8,
      failed: 2,
      normalized: false,
      positions: [],
    });

    await usePortfolioStore.getState().bulkAddPositions([
      { ticker: 'A.NS', weight: 0.5, quantity: 1, buy_price: 100 },
      { ticker: 'B.NS', weight: 0.5, quantity: 1, buy_price: 100 },
    ]);

    expect(usePortfolioStore.getState().error).toMatch(/2 of 10 positions failed/);
  });

  it('defaults region to IN for an INR/NSE-first product (04-B16)', async () => {
    vi.mocked(portfolioApi.bulkAddPositions).mockResolvedValueOnce({
      success: true,
      added: 1,
      failed: 0,
      normalized: true,
      positions: [],
    });

    await usePortfolioStore.getState().bulkAddPositions([
      { ticker: 'INFY.NS', weight: 1, quantity: 1, buy_price: 100 },
    ]);

    const sent = vi.mocked(portfolioApi.bulkAddPositions).mock.calls[0][0];
    expect(sent.positions[0].region).toBe('IN');
    expect(usePortfolioStore.getState().error).toBeNull();
  });

  it('does not set error when every row succeeds', async () => {
    vi.mocked(portfolioApi.bulkAddPositions).mockResolvedValueOnce({
      success: true,
      added: 2,
      failed: 0,
      normalized: true,
      positions: [],
    });

    await usePortfolioStore.getState().bulkAddPositions([
      { ticker: 'A.NS', weight: 0.5, quantity: 1, buy_price: 100 },
      { ticker: 'B.NS', weight: 0.5, quantity: 1, buy_price: 100 },
    ]);

    expect(usePortfolioStore.getState().error).toBeNull();
  });
});
