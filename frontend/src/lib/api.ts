/**
 * API client for Daisy Risk Engine
 * Provides typed API calls to the FastAPI backend
 */

import axios, { AxiosInstance, AxiosResponse } from 'axios';
import { PortfolioCreateRequest, PortfolioUpdateRequest, PortfolioBulkAddRequest } from '@/types';

// Create axios instance
const apiClient: AxiosInstance = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
apiClient.interceptors.request.use(
  (config) => {
    console.log(`API Request: ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor
apiClient.interceptors.response.use(
  (response) => {
    console.log(`API Response: ${response.status} ${response.config.url}`);
    return response;
  },
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
  }): Promise<any> {
    const defaultParams = {
      currency: 'INR',  // Indian default
      ...params
    };
    const response = await apiClient.get('/portfolio', { params: defaultParams });
    return response.data;
  },

  // Add position
  async addPosition(data: PortfolioCreateRequest): Promise<any> {
    console.log('📤 API: Adding position with data:', data);
    const response = await apiClient.post('/portfolio/add', data);
    console.log('📥 API: Position added successfully:', response.data);
    return response.data;
  },

  // Bulk add positions
  async bulkAddPositions(data: PortfolioBulkAddRequest): Promise<any> {
    console.log('📤 API: Bulk adding positions with data:', data);
    const response = await apiClient.post('/portfolio/bulk_add', data);
    console.log('📥 API: Bulk positions added successfully:', response.data);
    return response.data;
  },

  // Get position
  async getPosition(ticker: string): Promise<any> {
    const response = await apiClient.get(`/portfolio/${ticker}`);
    return response.data;
  },

  // Update position
  async updatePosition(ticker: string, data: {
    weight?: number;
    custom_name?: string;
  }): Promise<any> {
    const response = await apiClient.put(`/portfolio/${ticker}`, data);
    return response.data;
  },

  // Delete position
  async deletePosition(ticker: string): Promise<any> {
    const response = await apiClient.delete(`/portfolio/${ticker}`);
    return response.data;
  },

  // Export CSV
  async exportCSV(): Promise<string> {
    const response = await apiClient.get('/portfolio/export/csv');
    return response.data;
  },

  // Normalize weights
  async normalizeWeights(method = 'proportional'): Promise<any> {
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
  }): Promise<any> {
    const response = await apiClient.get(`/data/${ticker}`, { params });
    return response.data;
  },

  // Get stock quote
  async getStockQuote(ticker: string): Promise<any> {
    const response = await apiClient.get(`/data/quote/${ticker}`);
    return response.data;
  },

  // Get batch stock data
  async getBatchStockData(data: {
    tickers: string[];
    start?: string;
    end?: string;
    force_refresh?: boolean;
  }): Promise<any> {
    const response = await apiClient.post('/data/batch', data);
    return response.data;
  },

  // Validate ticker
  async validateTicker(ticker: string): Promise<any> {
    const response = await apiClient.post('/data/validate', { ticker });
    return response.data;
  },

  // Refresh data
  async refreshData(tickers: string[]): Promise<any> {
    const response = await apiClient.post('/data/refresh', tickers);
    return response.data;
  },

  // Get API config
  async getConfig(): Promise<any> {
    const response = await apiClient.get('/data/config');
    return response.data;
  },

  // Update API config
  async updateConfig(data: {
    cache_ttl_minutes?: number;
    enable_cache?: boolean;
  }): Promise<any> {
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
  }): Promise<any> {
    const response = await apiClient.get('/analytics/realized-risk', { params });
    return response.data;
  },

  // Get forecast risk metrics
  async getForecastRisk(params?: {
    model?: string;
    horizon?: number;
    tickers?: string;
  }): Promise<any> {
    const response = await apiClient.get('/analytics/forecast-risk', { params });
    return response.data;
  },

  // Get factor exposure
  async getFactorExposure(params?: {
    tickers?: string;
    lookback_days?: number;
  }): Promise<any> {
    const response = await apiClient.get('/analytics/factor-exposure', { params });
    return response.data;
  },

  // Get concentration metrics
  async getConcentrationMetrics(): Promise<any> {
    const response = await apiClient.get('/analytics/concentration');
    return response.data;
  },

  // Get liquidity metrics
  async getLiquidityMetrics(): Promise<any> {
    const response = await apiClient.get('/analytics/liquidity');
    return response.data;
  },

  // Get risk score
  async getRiskScore(): Promise<any> {
    const response = await apiClient.get('/analytics/risk-score');
    return response.data;
  },

  // Run stress test
  async runStressTest(data: {
    scenario: string;
    tickers?: string[];
  }): Promise<any> {
    const response = await apiClient.post('/analytics/stress-test', data);
    return response.data;
  },

  // Get volatility sizing
  async getVolatilitySizing(params?: {
    model?: string;
    target_volatility?: number;
  }): Promise<any> {
    const response = await apiClient.get('/analytics/volatility-sizing', { params });
    return response.data;
  },

  // Get analytics summary
  async getSummary(): Promise<any> {
    const response = await apiClient.get('/analytics/summary');
    return response.data;
  },
};

// Health check
export const healthApi = {
  async check(): Promise<any> {
    const response = await apiClient.get('/health');
    return response.data;
  },
};

export default apiClient;