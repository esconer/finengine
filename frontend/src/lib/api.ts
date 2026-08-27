/**
 * API client for Daisy Risk Engine
 * Provides typed API calls to the FastAPI backend
 */

import axios, { AxiosInstance, AxiosResponse } from 'axios';
import {
  PortfolioPosition,
  PortfolioSummary,
  PortfolioCreateRequest,
  PortfolioUpdateRequest,
  PortfolioBulkAddRequest,
  StockData,
  RealizedRiskMetrics,
  ForecastRiskResponse,
  FactorExposureResponse,
  ConcentrationMetrics,
  LiquidityResponse,
  RiskScore,
  StressTestResponse,
  VolatilitySizingResponse,
  TearSheetResponse,
  RiskContributionResponse,
  OptimizationResponse,
  RegimeResponse,
  MonteCarloResponse,
} from '@/types';

// Create axios instance
const apiClient: AxiosInstance = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
apiClient.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error)
);

// Response interceptor
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    let errorMessage = 'Unknown API error';

    if (error.response) {
      const { status, data } = error.response;

      if (status === 422) {
        // Handle validation errors specifically
        if (data.detail) {
          if (Array.isArray(data.detail)) {
            // FastAPI validation error format: [{field, msg}]
            errorMessage = data.detail.map((err: any) => `${err.loc?.[err.loc.length - 1]}: ${err.msg}`).join(', ');
          } else if (typeof data.detail === 'string') {
            errorMessage = data.detail;
          }
        } else if (data.message) {
          errorMessage = data.message;
        } else if (data.error) {
          errorMessage = data.error;
        } else {
          errorMessage = 'Validation failed. Please check your input data.';
        }
      } else if (status === 409) {
        // Handle duplicate ticker errors specifically
        if (data.detail) {
          errorMessage = data.detail;
        } else if (data.message) {
          errorMessage = data.message;
        } else if (data.error) {
          errorMessage = data.error;
        } else {
          errorMessage = 'This ticker already exists in your portfolio';
        }
      } else if (data?.message) {
        errorMessage = data.message;
      } else if (data?.error) {
        errorMessage = data.error;
      } else {
        errorMessage = `HTTP ${status}: ${error.message}`;
      }
    } else if (error.message) {
      errorMessage = error.message;
    }

    console.error('API Error:', {
      status: error.response?.status,
      url: error.config?.url,
      message: errorMessage,
      data: error.response?.data
    });

    return Promise.reject(new Error(errorMessage));
  }
);

// Types
export interface APIResponse<T> {
  data: T;
  success: boolean;
  message?: string;
  timestamp: string;
}

export interface ErrorResponse {
  error: string;
  message: string;
  status_code: number;
}

// Portfolio API
export const portfolioApi = {
  // Get portfolio summary (defaults to INR currency for Indian market)
  async getPortfolio(params?: {
    region?: string;
    sector?: string;
    currency?: string;  // Default to INR for Indian market
  }): Promise<PortfolioSummary> {
    const defaultParams = {
      currency: 'INR',  // Indian default
      ...params
    };
    const response = await apiClient.get('/portfolio', { params: defaultParams });
    return response.data;
  },

  // Add position
  async addPosition(data: PortfolioCreateRequest): Promise<PortfolioPosition> {
    const response = await apiClient.post('/portfolio/add', data);
    return response.data;
  },

  // Bulk add positions
  async bulkAddPositions(data: PortfolioBulkAddRequest): Promise<{
    success: boolean;
    added: number;
    failed: number;
    normalized: boolean;
    positions: PortfolioPosition[];
  }> {
    const response = await apiClient.post('/portfolio/bulk_add', data);
    return response.data;
  },

  // Get position
  async getPosition(ticker: string): Promise<PortfolioPosition> {
    const response = await apiClient.get(`/portfolio/${ticker}`);
    return response.data;
  },

  // Update position
  async updatePosition(ticker: string, data: {
    weight?: number;
    quantity?: number;
    buy_price?: number;
    custom_name?: string;
  }): Promise<PortfolioPosition> {
    const response = await apiClient.put(`/portfolio/${ticker}`, data);
    return response.data;
  },

  // Delete position
  async deletePosition(ticker: string): Promise<{ success: boolean; message: string; data?: { weights_renormalized: boolean } }> {
    const response = await apiClient.delete(`/portfolio/${ticker}`);
    return response.data;
  },

  // Export CSV
  async exportCSV(): Promise<string> {
    const response = await apiClient.get('/portfolio/export/csv');
    return response.data;
  },

  // Normalize weights
  async normalizeWeights(method = 'proportional'): Promise<{ success: boolean; message: string; method: string }> {
    const response = await apiClient.post('/portfolio/normalize', null, {
      params: { method },
    });
    return response.data;
  },
};

// Data API
export const dataApi = {
  // Get stock data
  async getStockData(ticker: string, params?: {
    start?: string;
    end?: string;
    force_refresh?: boolean;
  }): Promise<StockData[]> {
    const response = await apiClient.get(`/data/${ticker}`, { params });
    return response.data;
  },

  // Get stock quote
  async getStockQuote(ticker: string): Promise<{ current_price: number; sector?: string; industry?: string; company_name?: string }> {
    const response = await apiClient.get(`/data/quote/${ticker}`);
    return response.data;
  },

  // Get batch stock data
  async getBatchStockData(data: {
    tickers: string[];
    start?: string;
    end?: string;
    force_refresh?: boolean;
  }): Promise<{ data: Record<string, StockData[]>; failed_tickers: string[] }> {
    const response = await apiClient.post('/data/batch', data);
    return response.data;
  },

  // Validate ticker
  async validateTicker(ticker: string): Promise<{ valid: boolean; symbol?: string; name?: string }> {
    const response = await apiClient.post('/data/validate', { ticker });
    return response.data;
  },

  // Refresh data
  async refreshData(tickers: string[]): Promise<{ refreshed: string[]; failed: string[] }> {
    const response = await apiClient.post('/data/refresh', tickers);
    return response.data;
  },

  // Get API config
  async getConfig(): Promise<{ cache_ttl_minutes: number; enable_cache: boolean }> {
    const response = await apiClient.get('/data/config');
    return response.data;
  },

  // Update API config
  async updateConfig(data: {
    cache_ttl_minutes?: number;
    enable_cache?: boolean;
  }): Promise<{ cache_ttl_minutes: number; enable_cache: boolean }> {
    const response = await apiClient.put('/data/config', null, { params: data });
    return response.data;
  },
};

// Analytics API
export const analyticsApi = {
  // Get realized risk metrics
  async getRealizedRisk(params?: {
    tickers?: string;
    start?: string;
    end?: string;
  }): Promise<RealizedRiskMetrics & { by_position?: Record<string, RealizedRiskMetrics> }> {
    const response = await apiClient.get('/analytics/realized-risk', { params });
    return response.data;
  },

  // Get forecast risk metrics
  async getForecastRisk(params?: {
    model?: string;
    horizon?: number;
    tickers?: string;
  }): Promise<ForecastRiskResponse> {
    const response = await apiClient.get('/analytics/forecast-risk', { params });
    return response.data;
  },

  // Get factor exposure
  async getFactorExposure(params?: {
    tickers?: string;
    lookback_days?: number;
  }): Promise<FactorExposureResponse> {
    const response = await apiClient.get('/analytics/factor-exposure', { params });
    return response.data;
  },

  // Get concentration metrics
  async getConcentrationMetrics(): Promise<ConcentrationMetrics> {
    const response = await apiClient.get('/analytics/concentration');
    return response.data;
  },

  // Get liquidity metrics
  async getLiquidityMetrics(): Promise<LiquidityResponse> {
    const response = await apiClient.get('/analytics/liquidity');
    return response.data;
  },

  // Get risk score
  async getRiskScore(): Promise<RiskScore> {
    const response = await apiClient.get('/analytics/risk-score');
    return response.data;
  },

  // Run stress test
  async runStressTest(data: {
    scenario: string;
    tickers?: string[];
  }): Promise<StressTestResponse> {
    const response = await apiClient.post('/analytics/stress-test', data);
    return response.data;
  },

  // Get volatility sizing
  async getVolatilitySizing(params?: {
    model?: string;
    target_volatility?: number;
    portfolio_value?: number;
  }): Promise<VolatilitySizingResponse> {
    const response = await apiClient.get('/analytics/volatility-sizing', { params });
    return response.data;
  },

  // Get analytics summary
  async getSummary(): Promise<Record<string, unknown>> {
    const response = await apiClient.get('/analytics/summary');
    return response.data;
  },

  // Get historical performance
  async getPerformanceHistory(params?: {
    days?: number;
    tickers?: string;
  }): Promise<Array<{ date: string; value: number; benchmark?: number }>> {
    const response = await apiClient.get('/analytics/performance-history', { params });
    return response.data;
  },

  // Get quantstats tear-sheet vs NIFTY
  async getTearSheet(params?: {
    tickers?: string;
    start?: string;
    end?: string;
  }): Promise<TearSheetResponse> {
    const response = await apiClient.get('/analytics/tear-sheet', { params });
    return response.data;
  },

  // Euler risk decomposition per position
  async getRiskContribution(params?: {
    tickers?: string;
  }): Promise<RiskContributionResponse> {
    const response = await apiClient.get('/analytics/risk-contribution', { params });
    return response.data;
  },

  // Portfolio optimization (hrp | min_vol | max_sharpe | min_cvar)
  async runOptimization(data: {
    strategy?: string;
    risk_free_rate?: number;
    tickers?: string[];
  }): Promise<OptimizationResponse> {
    const response = await apiClient.post('/analytics/optimize/run', data);
    return response.data;
  },

  // HMM market-regime classification
  async getRegime(params?: {
    lookback_days?: number;
    with_portfolio?: boolean;
  }): Promise<RegimeResponse> {
    const response = await apiClient.get('/analytics/regime', { params });
    return response.data;
  },

  // Monte Carlo goal-probability simulation
  async runMonteCarlo(data: {
    target_value: number;
    horizon_years: number;
    initial_value?: number;
    method?: 'gbm' | 'student_t' | 'bootstrap';
    num_paths?: number;
    seed?: number;
  }): Promise<MonteCarloResponse> {
    const response = await apiClient.post('/analytics/monte-carlo', data);
    return response.data;
  },
};

// Health check
export const healthApi = {
  async check(): Promise<{ status: string; timestamp: string; services?: Record<string, string> }> {
    const response = await apiClient.get('/health');
    return response.data;
  },
};

export default apiClient;