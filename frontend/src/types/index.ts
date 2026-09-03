// Portfolio Position Type
export interface PortfolioPosition {
  id: number;
  ticker: string;
  weight: number;
  quantity: number;
  buy_price: number;
  region: string;
  primary_source: string;
  fallback_source?: string;
  last_validated_source: string;
  last_price: number;
  market_value: number;
  sector: string;
  industry: string;
  custom_name?: string;
  added_on: string;
  updated_on: string;
  // Calculated fields
  total_cost: number;
  unrealized_gain_loss: number;
  unrealized_gain_loss_pct: number;
  current_value: number;
  // Risk metrics
  volatility_forecast?: number;
  var_forecast?: number;
  risk_level?: 'Low' | 'Medium' | 'High';
}

// Stock OHLCV Data Type
export interface StockData {
  ticker: string;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adj_close: number;
  volume: number;
}

// Portfolio Summary Type
export interface PortfolioSummary {
  positions: PortfolioPosition[];
  total_value: number;
  total_positions: number;
  total_weight: number;
  sectors: Record<string, number>;
}

// Realized Risk Metrics Type
export interface RealizedRiskMetrics {
  annual_return: number;
  annual_volatility: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  skewness: number;
  kurtosis: number;
  max_drawdown: number;
  var_95: number;
  cvar_95: number;
  hit_ratio: number;
  beta_vs_benchmark?: number;
  up_capture?: number;
  down_capture?: number;
}

// Forecast Risk Metrics Type
export interface ForecastRiskMetrics {
  model: "EWMA" | "GARCH" | "EGARCH";
  horizon: number;
  volatility_forecast: number;
  var_forecast: number;
  cvar_forecast: number;
  confidence_interval: [number, number];
  model_params: Record<string, any>;
}

// Factor Exposure Type
export interface FactorExposureResponse {
  portfolio: Record<string, number>;
  positions: Record<string, Record<string, number>>;
  r_squared: number;
  adjusted_r_squared: number;
  data_range?: {
    start: string;
    end: string;
  };
  lookback_days: number;
  methodology?: string;
}

// Concentration Metrics Type
export interface ConcentrationMetrics {
  largest_position: number;
  top_3: number;
  top_5: number;
  top_10: number;
  herfindahl_index: number;
  effective_positions: number;
  diversification_ratio: number;
  by_weight: Record<string, number>;
  by_sector: Record<string, number>;
  methodology?: string;
}

// Liquidity Metrics Type
export interface LiquidityMetrics {
  overall_score: number;
  liquidation_time_days: string;
  risk_level: string;
  by_position: Record<string, {
    score: number;
    spread: number;
    avg_volume: number;
    category: string;
  }>;
  volume_stats: {
    avg_volume: number;
    total_portfolio_volume: number;
    high_volume_pct: number;
    medium_volume_pct: number;
    low_volume_pct: number;
  };
}

// Risk Score Type
export interface RiskScore {
  overall_score: number;
  risk_level: string;
  change: number;
  components: {
    concentration: number;
    volatility: number;
    correlation: number;
    factor_risk: number;
    stress_test: number;
    market_risk: number;
  };
  alerts: string[];
}

// API Response Types
export interface APIResponse<T> {
  data: T;
  success: boolean;
  message?: string;
  timestamp: string;
}

export interface BatchStockDataResponse {
  data: Record<string, StockData[]>;
  failed_tickers: string[];
}

export interface PortfolioCreateRequest {
  ticker: string;
  weight: number;
  quantity: number;
  buy_price: number;
  region: string;
  custom_name?: string;
}

export interface PortfolioUpdateRequest {
  weight?: number;
  quantity?: number;
  buy_price?: number;
  custom_name?: string;
}

export interface PortfolioBulkAddRequest {
  positions: Omit<PortfolioCreateRequest, "id">[];
  auto_normalize: boolean;
}

// Chart Data Types
export interface ChartDataPoint {
  date: string;
  value: number;
  label?: string;
}

export interface PieChartData {
  name: string;
  value: number;
  percentage?: number;
}

export interface CorrelationMatrix {
  symbols: string[];
  matrix: number[][];
}

// Currency Types
export type Currency = 'USD' | 'INR';

export interface CurrencyInfo {
  code: Currency;
  symbol: string;
  name: string;
}

export interface ExchangeRate {
  from: Currency;
  to: Currency;
  rate: number;
  last_updated: string;
}

export interface CurrencyContextType {
  currentCurrency: Currency;
  exchangeRate: number;
  setCurrency: (currency: Currency) => void;
  formatCurrency: (amount: number, currency?: Currency) => string;
  convertCurrency: (amount: number, from: Currency, to: Currency) => number;
}

// UI Component Props
export interface MetricCardProps {
  title: string;
  value: number | string;
  change?: number;
  changeType?: 'positive' | 'negative' | 'neutral';
  icon?: React.ComponentType;
  loading?: boolean;
}

export interface DataTableColumn<T> {
  key: keyof T;
  header: string;
  sortable?: boolean;
  formatter?: (value: any) => string | number;
}

export interface DataTableProps<T> {
  data: T[];
  columns: DataTableColumn<T>[];
  loading?: boolean;
  onSort?: (key: keyof T, direction: 'asc' | 'desc') => void;
  onExport?: () => void;
}

// Store Types (Zustand)
export interface PortfolioStore {
  positions: PortfolioPosition[];
  selectedTickers: string[];
  isLoading: boolean;
  error: string | null;
  
  // Actions
  addPosition: (position: PortfolioCreateRequest) => Promise<void>;
  updatePosition: (id: number, updates: Partial<PortfolioPosition>) => Promise<void>;
  removePosition: (id: number) => Promise<void>;
  setSelectedTickers: (tickers: string[]) => void;
  fetchPortfolio: () => Promise<void>;
  clearError: () => void;
}

export interface UIStore {
  darkMode: boolean;
  sidebarOpen: boolean;
  liveDataMode: boolean;
  
  // Actions
  toggleDarkMode: () => void;
  toggleSidebar: () => void;
  toggleLiveDataMode: () => void;
}

export interface AnalyticsStore {
  cache: Map<string, unknown>;
  isCalculating: boolean;
  
  // Actions
  setCachedData: (key: string, data: unknown) => void;
  getCachedData: (key: string) => unknown;
  clearCache: () => void;
}

// Quantitative Analytics Response Types
export interface ForecastRiskResponse {
  model: string;
  horizon: number;
  portfolio: {
    volatility_forecast?: number | null;
    var_forecast?: number | null;
    cvar_forecast?: number | null;
    confidence_interval?: [number, number];
  };
  positions: Record<string, {
    volatility_forecast?: number | null;
    var_forecast?: number | null;
  }>;
  model_params?: Record<string, any>;
}

export interface LiquidityResponse {
  overall_score: number;
  liquidation_time_days: string;
  risk_level: string;
  by_position: Record<string, {
    score: number;
    category: string;
    liquidation_days: string;
    spread?: number;
    avg_volume?: number;
  }>;
  volume_stats: {
    avg_volume: number;
    total_portfolio_volume: number;
    high_volume_pct: number;
    medium_volume_pct: number;
    low_volume_pct: number;
  };
  methodology?: string;
}

export interface OptimizationResponse {
  strategy: string;
  weights: Record<string, number>;
  expected_annual_return: number;
  expected_annual_volatility: number;
  expected_sharpe: number | null;
  solver: string;
  universe: string[];
  current_weights: Record<string, number>;
  trades_required: Record<
    string,
    { current_weight: number; recommended_weight: number; weight_delta: number }
  >;
  disclaimer: string;
}

export interface RegimeResponse {
  as_of: string;
  current_regime: string;
  stability_pct: number;
  states: {
    regime: string;
    ann_ret: number;
    ann_vol: number;
    historical_days_pct: number;
  }[];
  recent_history: { date: string; regime: string }[];
  observations: number;
  label_overrides?: { crash_veto_days: number; crash_veto_threshold: number };
  portfolio_in_current_regime?: { days: number; ann_ret: number; ann_vol: number };
}

export interface RiskContributionResponse {
  window: { start: string; end: string };
  positions: {
    volatility: Record<string, number>;
    cvar_tail: Record<string, number>;
  };
  sector_rollup: {
    volatility: Record<string, number>;
    cvar: Record<string, number>;
  };
  portfolio_volatility_annualized: number;
  portfolio_var_95_daily: number;
  portfolio_cvar_95_daily: number | null;
  methodology: string;
}

export interface StressTestResponse {
  scenario: string;
  max_drawdown: number;
  portfolio_impact: number;
  position_impacts: Record<string, number>;
  recovery_time: number;
  confidence_level: number;
  methodology?: string;
}

export interface VolatilitySizingResponse {
  current_weights: Record<string, number>;
  recommended_weights: Record<string, number>;
  trades: Record<string, {
    shares_delta: number;
    amount: number;
  }>;
  target_volatility: number;
  current_volatility?: number;
  volatilities?: Record<string, number>;
  model_params?: Record<string, any>;
  methodology?: string;
}

export interface TearSheetResponse {
  window: { start: string; end: string };
  holdings: Record<string, number>;
  metrics: Record<string, number | null>;
  relative_vs_nifty: Record<string, number | null>;
  monthly_returns: Record<string, Record<string, number>>;
  underwater: { date: string; drawdown: number }[];
  methodology: string;
}

export interface MonteCarloResponse {
  method: string;
  initial_value: number;
  target_value: number;
  horizon_years: number;
  num_paths: number;
  prob_success: number;
  terminal_percentiles: { p5: number; p25: number; p50: number; p75: number; p95: number };
  fan: { year: number; p5: number; p25: number; p50: number; p75: number; p95: number }[];
  expected_shortfall_vs_target: number;
  historical_mu_annual: number;
  historical_sigma_annual: number;
  student_t_df: number | null;
  disclaimer: string;
}

export interface VolConeResponse {
  cones: Record<string, { min: number; p25: number; p50: number; p75: number; max: number; current: number }>;
  garch_forecast: number;
  ewma_forecast: number;
}

export interface TailRiskResponse {
  evt_pot_var_99: number;
  evt_pot_es_99: number;
  student_t_tail_matrix: {
    tickers: string[];
    matrix: number[][];
  };
}

export interface CorrelationStabilityResponse {
  rolling_60d_avg_corr: number;
  p90_historical_corr: number;
  regime_alert: boolean;
  history: Array<{ date: string; avg_correlation: number }>;
}

export interface CointegrationResponse {
  pairs: Array<{
    pair: [string, string];
    p_value: number;
    half_life_days: number;
    z_score: number;
    is_cointegrated: boolean;
  }>;
}

export interface IndiaFlowsResponse {
  delivery_spikes: Array<{ ticker: string; delivery_pct: number; avg_delivery_pct: number; spike: boolean }>;
  institutional_flows: { fii_net_cr: number; dii_net_cr: number; date: string };
  adv_liquidity: Record<string, { adv_shares: number; days_to_liquidate_10pct: number; days_to_liquidate_20pct: number }>;
}

// Equity Research Types
export interface EquityResearchProfile {
  symbol: string;
  ticker: string;
  name: string;
  about?: string;
  website?: string;
  bse_code?: string;
  nse_symbol?: string;
  sector?: string;
  industry_group?: string;
  industry?: string;
  sub_industry?: string;
  indices: string[];
  current_price: number;
  market_cap_cr?: number;
  high_52w?: number;
  low_52w?: number;
  stock_pe?: number;
  book_value?: number;
  dividend_yield?: number;
  roce?: number;
  roe?: number;
  face_value?: number;
  debt_to_equity?: number;
  peg_ratio?: number;
  eps_ttm?: number;
  promoter_holding?: number;
  promoter_pledged?: number;
  custom_ratios: {
    piotroski_score: number;
    graham_number?: number;
    graham_upside_pct?: number;
    enterprise_value_cr?: number;
    ev_to_ebitda?: number;
    interest_coverage?: number;
    cfo_to_pat_ratio?: number;
  };
  cagrs: Record<string, Record<string, string>>;
  pros: string[];
  cons: string[];
  peers: Array<{
    rank?: number;
    name: string;
    symbol?: string;
    cmp?: number;
    pe?: number;
    market_cap_cr?: number;
    dividend_yield?: number;
    roce?: number;
  }>;
  concall_count: number;
  annual_reports: Array<{ year: string; url: string }>;
  credit_ratings: Array<{ agency: string; rating: string }>;
}

export interface ShareholdingBlock {
  periods: string[];
  rows: Record<string, number[]>;
  chart_series: Array<{
    period: string;
    promoters?: number;
    fiis?: number;
    diis?: number;
    government?: number;
    public?: number;
    others?: number;
    [key: string]: any;
  }>;
}

export interface ShareholdingDataResponse {
  ticker: string;
  quarterly: ShareholdingBlock;
  yearly: ShareholdingBlock;
}

export interface ConcallItem {
  date: string;
  quarter?: string;
  title: string;
  transcript_url?: string;
  audio_url?: string;
  presentation_url?: string;
}

export interface CustomRatiosDataResponse {
  ticker: string;
  piotroski_score: number;
  graham_number?: number;
  graham_upside_pct?: number;
  enterprise_value_cr: number;
  ev_to_ebitda?: number;
  interest_coverage?: number;
  cfo_to_pat_ratio?: number;
  current_price: number;
  ratios_history: {
    periods: string[];
    rows: Record<string, number[]>;
  };
}

export interface ScreenerStock {
  symbol: string;
  ticker: string;
  name: string;
  price: number;
  market_cap_cr: number;
  pe_ratio?: number;
  roce_pct?: number;
  roe_pct?: number;
  dividend_yield_pct?: number;
  book_value?: number;
}

export interface ScreenerStrategyResponse {
  strategy: string;
  name: string;
  description: string;
  count: number;
  stocks: ScreenerStock[];
}

export interface ScreenerStrategyMeta {
  key: string;
  name: string;
  description: string;
}
