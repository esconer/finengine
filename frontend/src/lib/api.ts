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
  EquityResearchProfile,
  ShareholdingDataResponse,
  ConcallItem,
  CustomRatiosDataResponse,
  ScreenerStrategyResponse,
  ScreenerStrategyMeta,
  AIContextResponse,
  AIContextDetail,
} from '@/types';

// Create axios instance
const apiClient: AxiosInstance = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Typed error carrying HTTP status + raw detail so callers can branch on it
export class AppError extends Error {
  status?: number;
  detail?: unknown;

  constructor(message: string, options: { status?: number; detail?: unknown } = {}) {
    super(message);
    this.name = 'AppError';
    this.status = options.status;
    this.detail = options.detail;
  }
}

// Pure message builder (unit-tested): reads FastAPI `{detail}` for ALL statuses,
// string detail → message; array detail (422 shape) → joined; else message/error/HTTP.
export function buildApiErrorMessage(status: number, data: unknown): string {
  const body = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>;

  const { detail, message, error } = body;
  if (detail !== undefined && detail !== null && detail !== '') {
    if (Array.isArray(detail)) {
      const formatted = detail
        .map((err) => `${err?.loc?.[err.loc.length - 1]}: ${err?.msg}`)
        .join(', ');
      if (formatted) return formatted;
    } else if (typeof detail === 'string') {
      return detail;
    }
  }

  if (typeof message === 'string' && message) return message;
  if (typeof error === 'string' && error) return error;

  if (status === 422) return 'Validation failed. Please check your input data.';
  if (status === 409) return 'This ticker already exists in your portfolio';
  return `HTTP ${status}`;
}

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
    let status: number | undefined;
    let detail: unknown;

    if (error.response) {
      status = error.response.status;
      detail = error.response.data?.detail;
      errorMessage = buildApiErrorMessage(error.response.status, error.response.data);
    } else if (error.message) {
      errorMessage = error.message;
    }

    console.error('API Error:', {
      status,
      url: error.config?.url,
      message: errorMessage,
      data: error.response?.data
    });

    return Promise.reject(new AppError(errorMessage, { status, detail }));
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

// Performance history wire shapes. Declared locally: the endpoint keeps its
// bare-row default and only wraps the rows when `include_metadata=true`, so
// both responses must typecheck. A row carries the measured portfolio value.
export interface PerformanceHistoryRow {
  date: string;
  portfolio_value: number;
  benchmark_value?: number;
  return?: number;
  [key: string]: unknown;
}

export interface PerformanceHistoryCoverage {
  requested_start?: string | null;
  requested_end?: string | null;
  requested_days?: number | null;
  delivered_start?: string | null;
  delivered_end?: string | null;
  observation_count?: number | null;
  expected_observation_count?: number | null;
  first_observation?: string | null;
  last_observation?: string | null;
  coverage_ratio?: number | null;
  truncated?: boolean | null;
  stale?: boolean | null;
  status?: string | null;
}

export interface PerformanceHistoryEnvelope {
  data: PerformanceHistoryRow[];
  data_status?: 'available' | 'partial' | 'unavailable';
  as_of?: string | null;
  as_of_semantics?: string | null;
  history_coverage?: PerformanceHistoryCoverage | null;
  warnings?: string[] | null;
}

// Realized-risk wire shape. Declared locally, mirroring the performance-history
// shapes above: the endpoint returns an ENVELOPE of blocks, and the per-block
// `number | null` contract (a withheld ratio is absent, never 0) only holds at
// the block level. Mirrors `backend/app/api/analytics.py:4526-4660`.
//
// The envelope was previously typed as a flat metrics block that carried only
// the *portfolio* field list — every `portfolio` / `positions` /
// `instrument_risk` access on the envelope then failed to compile, so the hook
// erased the whole response to `any` and the null contract was never checked.
// A duplicate of that flat block in `src/types` was removed rather than kept
// beside this one: two declarations of one payload drift, and this is the one
// the hook and the pages actually consume.

/** Holding-window position row (analytics.py:4588-4603 + provenance). */
export interface RealizedRiskPositionRow {
  annual_return: number | null;
  annual_volatility: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  var_95: number | null;
  sortino_ratio?: number | null;
  weight: number;
  data_points: number;
  return_observations: number | null;
  is_limited_history: boolean;
  history_warning: string | null;
  /** Set by the route's own annualization gate, independent of the engine's. */
  annualized: boolean;
  analytics_start: string | null;
  analytics_start_source: string | null;
  stored_added_on: string | null;
  buy_price_inferred: string | null;
}

/** Full-exchange-history position row (analytics.py:4490-4496). */
export interface InstrumentRiskPositionRow {
  annual_volatility: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  total_return: number | null;
  data_points: number;
  annualized: boolean;
}

/** Portfolio block: the metrics the route publishes under `portfolio` and
 *  under `instrument_risk.portfolio` (analytics.py:4467-4475, 4526-4542). */
export interface RealizedRiskPortfolioBlock {
  annual_return: number | null;
  annual_volatility: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  skewness?: number | null;
  kurtosis?: number | null;
  max_drawdown: number | null;
  var_95: number | null;
  cvar_95: number | null;
  hit_ratio: number | null;
  annualized?: boolean;
  /** Only present on `instrument_risk.portfolio` (analytics.py:4474). */
  days?: number;
}

/** Per-ticker coverage row, as published under `history_coverage.tickers`. */
export interface RealizedRiskTickerCoverage {
  effective_start?: string | null;
  analytics_start?: string | null;
  analytics_start_source?: string | null;
  stored_added_on?: string | null;
  buy_price_inferred?: string | null;
  return_observations?: number | null;
  data_points?: number | null;
  is_limited_history?: boolean;
  limited_history?: boolean;
}

export interface RealizedRiskCoverage {
  requested_start?: string | null;
  effective_start?: string | null;
  intersection_start?: string | null;
  oldest_holding?: string | null;
  covered_days?: number | null;
  truncated?: boolean;
  annualized?: boolean;
  full_history_days?: number | null;
  full_history_start?: string | null;
  effective_start_source?: string | null;
  intersection_start_source?: string | null;
  inferred_start_tickers?: string[];
  tickers?: Record<string, RealizedRiskTickerCoverage>;
}

/** One withheld-measurement warning (analytics.py:4582-4587). */
export interface RealizedRiskWarning {
  ticker: string;
  data_points?: number | null;
  return_observations?: number | null;
  message?: string | null;
}

export interface RealizedRiskEnvelope {
  portfolio: RealizedRiskPortfolioBlock;
  positions: Record<string, RealizedRiskPositionRow>;
  instrument_risk: {
    portfolio?: RealizedRiskPortfolioBlock;
    positions?: Record<string, InstrumentRiskPositionRow>;
  };
  universe_coverage?: Record<string, unknown>;
  data_status?: 'available' | 'partial' | 'unavailable';
  warnings: RealizedRiskWarning[];
  data_range?: { start: string | null; end: string | null };
  latest_observation_date?: string | null;
  history_coverage?: RealizedRiskCoverage;
  methodology?: string;
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
    added_on?: string;
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

  // Rebalance portfolio (live or dry-run simulation)
  //
  // The workflow applies the same normalization rule the volatility-sizing
  // engine publishes (`divide_all_legs_by_gross_exposure`) and REJECTS a
  // target whose gross exposure exceeds 100 % with HTTP 400, because
  // normalization cannot create the financing it requires. `weight_normalization`
  // is the audit trail for the target that was accepted.
  async rebalancePortfolio(
    new_weights: Record<string, number>,
    dry_run = false
  ): Promise<{
    success: boolean;
    dry_run?: boolean;
    message: string;
    total_portfolio_value: number;
    total_portfolio_value_currency?: string;
    total_turnover_pct?: number;
    total_buy_inr?: number;
    total_sell_inr?: number;
    weights?: Record<string, number>;
    simulated_weights?: Record<string, number>;
    weight_normalization?: {
      normalization_rule: string;
      normalization_mode: string;
      weights_normalized: boolean;
      /** Gross exposure of the submitted target, before normalization. */
      submitted_gross_exposure: number;
      /** Gross exposure actually executed; 1.0 for an accepted target. */
      gross_exposure: number;
      execution_eligible: boolean;
      financing_required: boolean;
      net_cash_weight: number;
    };
    orders?: Array<{
      ticker: string;
      current_weight: number;
      target_weight: number;
      weight_delta: number;
      current_quantity: number;
      target_quantity: number;
      shares_delta: number;
      price: number;
      price_currency?: string;
      value_currency?: string;
      cash_delta: number;
      action: string;
    }>;
  }> {
    const response = await apiClient.post('/portfolio/rebalance', { new_weights, dry_run });
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

  // Get API config (includes user-selected primary data source)
  async getConfig(): Promise<{
    primary_source: 'bfinance' | 'yfinance';
    cache_ttl_minutes: number;
    enable_cache: boolean;
  }> {
    const response = await apiClient.get('/data/config');
    return response.data;
  },

  // Update API config (primary_source swaps the vendor cascade order)
  async updateConfig(data: {
    primary_source?: 'bfinance' | 'yfinance';
    cache_ttl_minutes?: number;
    enable_cache?: boolean;
  }): Promise<{ primary_source: 'bfinance' | 'yfinance'; cache_ttl_minutes: number; enable_cache: boolean }> {
    const response = await apiClient.put('/data/config', null, { params: data });
    return response.data;
  },

  // Purge cached market data (timeseries, analytics, NSE microstructure,
  // fetch logs + in-process memo caches). Portfolio holdings are preserved
  // server-side and never touched.
  async clearCache(): Promise<{
    cleared: Record<string, number>;
    total_rows_cleared: number;
    portfolio_preserved: boolean;
    message?: string;
  }> {
    const response = await apiClient.post('/data/cache/clear');
    return response.data;
  },
};

// Company Data API
export const companyDataApi = {
  // Get company fundamentals
  async getFundamentals(ticker: string): Promise<Record<string, any>> {
    const response = await apiClient.get(`/data/fundamentals/${encodeURIComponent(ticker)}`);
    return response.data;
  },

  // Get financial statements (10-13Y Ind AS statements)
  async getFinancialStatements(
    ticker: string,
    statement: string = 'income',
    freq: string = 'annual'
  ): Promise<any> {
    const response = await apiClient.get(`/data/financials/${encodeURIComponent(ticker)}`, {
      params: { statement, freq },
    });
    return response.data;
  },

  // Get insider transactions
  async getInsiderTransactions(ticker: string): Promise<{ ticker: string; count: number; transactions: any[] }> {
    const response = await apiClient.get(`/data/insider/${encodeURIComponent(ticker)}`);
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
  }): Promise<RealizedRiskEnvelope> {
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

  // Get historical performance.
  // Default response is the bare row array. `include_metadata=true` opts into
  // the disclosure envelope: { data, data_status, as_of, as_of_semantics,
  // history_coverage, warnings } so a short delivery is measurable instead of
  // being presented as a complete chart.
  async getPerformanceHistory(params?: {
    days?: number;
    tickers?: string;
    include_metadata?: boolean;
  }): Promise<PerformanceHistoryEnvelope | PerformanceHistoryRow[]> {
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

// AI context API
export const aiContextApi = {
  async getContext(params: {
    format?: 'json' | 'markdown';
    detail?: AIContextDetail;
    include?: string[];
    baseCurrency?: 'INR' | 'USD';
    forecastModel?: 'GARCH' | 'EGARCH' | 'EWMA';
    forecastHorizon?: number;
    factorLookbackDays?: number;
    optimizationStrategy?: 'hrp' | 'min_vol' | 'max_sharpe' | 'min_cvar' | 'black_litterman';
    monteCarloMethod?: 'gbm' | 'student_t' | 'bootstrap';
    monteCarloHorizonYears?: number;
    monteCarloTargetValue?: number;
    monteCarloSeed?: number;
  } = {}): Promise<AIContextResponse | string> {
    const response = await apiClient.get('/ai/context', {
      timeout: 600000,
      responseType: params.format === 'markdown' ? 'text' : 'json',
      params: {
        format: params.format ?? 'json',
        detail: params.detail ?? 'summary',
        include: params.include?.join(','),
        base_currency: params.baseCurrency,
        forecast_model: params.forecastModel,
        forecast_horizon: params.forecastHorizon,
        factor_lookback_days: params.factorLookbackDays,
        optimization_strategy: params.optimizationStrategy,
        monte_carlo_method: params.monteCarloMethod,
        monte_carlo_horizon_years: params.monteCarloHorizonYears,
        monte_carlo_target_value: params.monteCarloTargetValue,
        monte_carlo_seed: params.monteCarloSeed,
      },
    });
    return response.data;
  },
};

// Equity Research API (bfinance integration)
export const equityResearchApi = {
  async getFullProfile(ticker: string): Promise<EquityResearchProfile> {
    const response = await apiClient.get(`/company/${encodeURIComponent(ticker)}/full-profile`);
    return response.data;
  },

  async getShareholding(ticker: string): Promise<ShareholdingDataResponse> {
    const response = await apiClient.get(`/company/${encodeURIComponent(ticker)}/shareholding`);
    return response.data;
  },

  async getConcalls(ticker: string): Promise<{ ticker: string; count: number; concalls: ConcallItem[] }> {
    const response = await apiClient.get(`/company/${encodeURIComponent(ticker)}/concalls`);
    return response.data;
  },

  async getCustomRatios(ticker: string): Promise<CustomRatiosDataResponse> {
    const response = await apiClient.get(`/company/${encodeURIComponent(ticker)}/custom-ratios`);
    return response.data;
  },

  async getAiMemoPrompt(ticker: string, customInstructions?: string): Promise<{ ticker: string; prompt: string }> {
    const response = await apiClient.get(`/company/${encodeURIComponent(ticker)}/ai-memo-prompt`, {
      params: customInstructions ? { custom_instructions: customInstructions } : undefined,
    });
    return response.data;
  },

  async getAiForensicPrompt(ticker: string): Promise<{ ticker: string; prompt: string }> {
    const response = await apiClient.get(`/company/${encodeURIComponent(ticker)}/ai-forensic-prompt`);
    return response.data;
  },

  async getAiDossier(ticker: string, format: string = 'markdown'): Promise<{ ticker: string; format: string; content?: string; data?: any }> {
    const response = await apiClient.get(`/company/${encodeURIComponent(ticker)}/ai-dossier`, {
      params: { format },
    });
    return response.data;
  },

  async downloadExcelModel(ticker: string): Promise<Blob> {
    const response = await apiClient.get(`/company/${encodeURIComponent(ticker)}/export-excel`, {
      responseType: 'blob',
    });
    return response.data;
  },
};

// Screener API
export const screenerApi = {
  async getStrategies(): Promise<ScreenerStrategyMeta[]> {
    const response = await apiClient.get('/screens');
    return response.data;
  },

  async runScreen(strategy: string, maxStocks: number = 50): Promise<ScreenerStrategyResponse> {
    const response = await apiClient.get(`/screens/${encodeURIComponent(strategy)}`, {
      params: { max_stocks: maxStocks },
    });
    return response.data;
  },

  async runCustomScreen(criteria: {
    min_roce?: number;
    min_roe?: number;
    max_pe?: number;
    min_mcap_cr?: number;
    min_div_yield?: number;
    max_stocks?: number;
  }): Promise<ScreenerStrategyResponse> {
    const response = await apiClient.post('/screens/custom', criteria);
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