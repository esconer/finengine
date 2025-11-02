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
export interface FactorExposure {
  alpha: number;
  market: number;
  momentum: number;
  size: number;
  value: number;
  min_vol: number;
  quality: number;
  rates: number;
  volatility: number;
  meme: number;
  ai: number;
  r_squared: number;
  adjusted_r_squared: number;
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
  by_sector: Record<string, number>;
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
  cache: Map<string, any>;
  isCalculating: boolean;
  
  // Actions
  setCachedData: (key: string, data: any) => void;
  getCachedData: (key: string) => any;
  clearCache: () => void;
}