"""
Pydantic schemas for Daisy Risk Engine
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator


# Portfolio Schemas
class PortfolioPositionBase(BaseModel):
    """Base portfolio position schema with comprehensive validation"""
    ticker: str = Field(..., min_length=1, max_length=20, description="Stock ticker symbol")
    weight: float = Field(..., gt=0, le=1, description="Portfolio weight (0-1)")
    quantity: float = Field(..., gt=0, description="Number of shares/units held - must be > 0")
    buy_price: float = Field(..., gt=0, description="Price per share at time of purchase - must be > 0")
    region: str = Field(default="US", description="Region code")
    custom_name: Optional[str] = Field(default=None, max_length=100, description="Custom position name")
    
    @validator('ticker')
    def ticker_must_be_uppercase(cls, v):
        if not v or not v.strip():
            raise ValueError('Ticker cannot be empty')
        return v.upper().strip()
    
    @validator('weight')
    def weight_must_be_valid(cls, v):
        if not (0 < v <= 1):
            raise ValueError('Weight must be between 0 and 1 (exclusive of 0, inclusive of 1)')
        return v
    
    @validator('quantity')
    def quantity_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Quantity must be greater than 0')
        return v
    
    @validator('buy_price')
    def buy_price_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Buy price must be greater than 0')
        return v


class PortfolioPositionCreate(PortfolioPositionBase):
    """Schema for creating portfolio position"""
    pass


class PortfolioPositionUpdate(BaseModel):
    """Schema for updating portfolio position"""
    weight: Optional[float] = Field(None, gt=0, le=1)
    quantity: Optional[float] = Field(None, gt=0)
    buy_price: Optional[float] = Field(None, gt=0)
    custom_name: Optional[str] = Field(None, max_length=100)


class PortfolioPositionResponse(BaseModel):
    """Schema for portfolio position response"""
    id: int
    ticker: str
    weight: float
    quantity: float
    buy_price: float
    last_price: float
    market_value: float
    sector: str
    industry: str
    custom_name: Optional[str]
    added_on: datetime
    updated_on: Optional[datetime] = None
    # Calculated fields
    total_cost: float
    unrealized_gain_loss: float
    unrealized_gain_loss_pct: float
    current_value: float
    
    class Config:
        from_attributes = True


class PortfolioSummaryResponse(BaseModel):
    """Schema for portfolio summary"""
    positions: List[PortfolioPositionResponse]
    total_value: float
    total_positions: int
    total_weight: float
    sectors: Dict[str, float]


# Stock Data Schemas
class StockDataBase(BaseModel):
    """Base stock data schema"""
    ticker: str
    date: datetime
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


class StockDataResponse(StockDataBase):
    """Schema for stock data response"""
    pass


class StockTimeseriesResponse(BaseModel):
    """Schema for timeseries response matching instructions specification"""
    ticker: str
    data: List[StockDataResponse]
    source: str
    from_cache: bool
    metadata: Dict[str, str] = {}
    
    class Config:
        from_attributes = True


class StockQuoteResponse(BaseModel):
    """Schema for stock quote response"""
    ticker: str
    current_price: float
    volume: int
    market_cap: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    pe_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None


class BatchStockDataRequest(BaseModel):
    """Schema for batch stock data request"""
    tickers: List[str] = Field(..., min_items=1)
    start: Optional[str] = None
    end: Optional[str] = None
    force_refresh: bool = False


class BatchStockDataResponse(BaseModel):
    """Schema for batch stock data response"""
    data: Dict[str, List[StockDataResponse]]
    failed_tickers: List[str]


class ValidateTickerRequest(BaseModel):
    """Schema for ticker validation request"""
    ticker: str = Field(..., min_length=1, max_length=10)


class ValidateTickerResponse(BaseModel):
    """Schema for ticker validation response"""
    valid: bool
    message: str


# Analytics Schemas
class RealizedRiskMetrics(BaseModel):
    """Schema for realized risk metrics"""
    annual_return: float
    annual_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    skewness: float
    kurtosis: float
    max_drawdown: float
    var_95: float
    cvar_95: float
    hit_ratio: float
    beta_vs_benchmark: Optional[float] = None
    up_capture: Optional[float] = None
    down_capture: Optional[float] = None


class ForecastRiskMetrics(BaseModel):
    """Schema for forecast risk metrics"""
    model: str
    horizon: int
    volatility_forecast: float
    var_forecast: float
    cvar_forecast: float
    confidence_interval: List[float]
    model_params: Dict[str, Any]


class FactorExposure(BaseModel):
    """Schema for factor exposure"""
    alpha: float
    market: float
    r_squared: float
    adjusted_r_squared: float


class ConcentrationMetrics(BaseModel):
    """Schema for concentration metrics"""
    largest_position: float
    top_3: float
    top_5: float
    top_10: float
    herfindahl_index: float
    effective_positions: float
    diversification_ratio: float
    by_sector: Dict[str, float]


class LiquidityMetrics(BaseModel):
    """Schema for liquidity metrics"""
    overall_score: float
    liquidation_time_days: str
    risk_level: str
    by_position: Dict[str, Dict[str, Any]]
    volume_stats: Dict[str, Any]


class RiskScore(BaseModel):
    """Schema for risk score"""
    overall_score: float
    risk_level: str
    change: int
    components: Dict[str, float]
    alerts: List[str]


class StressTestRequest(BaseModel):
    """Schema for stress test request"""
    scenario: str
    tickers: Optional[List[str]] = None


class StressTestResponse(BaseModel):
    """Schema for stress test response"""
    scenario: str
    max_drawdown: float
    portfolio_impact: float
    position_impacts: Dict[str, float]
    recovery_time: Optional[int] = None


class VolatilitySizingRequest(BaseModel):
    """Schema for volatility sizing request"""
    model: Optional[str] = "EWMA"
    target_volatility: Optional[float] = 0.15


class VolatilitySizingResponse(BaseModel):
    """Schema for volatility sizing response"""
    current_weights: Dict[str, float]
    recommended_weights: Dict[str, float]
    trades: Dict[str, Dict[str, Any]]
    target_volatility: float


# Error Response
class ErrorResponse(BaseModel):
    """Schema for error responses"""
    error: str
    message: str
    status_code: int


# Success Response
class SuccessResponse(BaseModel):
    """Schema for success responses"""
    success: bool
    message: str
    data: Optional[Any] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Bulk Operations
class BulkAddRequest(BaseModel):
    """Schema for bulk portfolio add"""
    positions: List[PortfolioPositionBase]
    auto_normalize: bool = True


class BulkAddResponse(BaseModel):
    """Schema for bulk add response"""
    added: int
    failed: int
    normalized: bool
    positions: List[PortfolioPositionResponse]


# API Configuration
class APIConfigResponse(BaseModel):
    """Schema for API configuration"""
    primary_source: str
    cache_ttl_minutes: int
    enable_cache: bool


# Correlation Stability Schemas
class CorrelationDataPoint(BaseModel):
    """Single date point for rolling correlation history"""
    date: str
    avg_correlation: float
    threshold_90th: Optional[float] = None
    threshold_75th: Optional[float] = None


class CorrelationStabilityResponse(BaseModel):
    """Schema for rolling 60-day correlation stability and regime break response"""
    as_of: str
    current_avg_correlation: float
    historical_threshold_90th: float
    historical_threshold_75th: float
    historical_median: float
    is_regime_break: bool
    alert_level: str  # "CRITICAL", "ELEVATED", "NORMAL"
    message: str
    series: List[CorrelationDataPoint]


# Cointegration Scanner Schemas
class CointPairResult(BaseModel):
    """Schema for a single cointegrated pair analysis result"""
    ticker_a: str
    ticker_b: str
    engle_granger_pvalue: float
    engle_granger_tstat: float
    is_cointegrated: bool
    hedge_ratio_beta: float
    intercept_alpha: float
    ou_half_life_days: Optional[float] = None
    ou_reversion_speed_theta: Optional[float] = None
    current_spread_zscore: Optional[float] = None
    johansen_cointegrated: bool
    last_price_a: float
    last_price_b: float
    signal: str
    spread_series: Optional[List[Dict[str, Any]]] = None


class CointScannerResponse(BaseModel):
    """Schema for cointegration scanner response"""
    as_of: str
    universe_size: int
    scanned_pairs_count: int
    cointegrated_pairs_count: int
    pairs: List[CointPairResult]


# Volatility Term Structure & Cone Schemas
class VolConeWindow(BaseModel):
    """Realized volatility quantiles for a single rolling window"""
    window_days: int
    min: float
    p25: float
    median: float
    p75: float
    max: float
    current_realized: float
    percentile_rank: Optional[float] = None


class VolForecastOverlay(BaseModel):
    """Volatility forecast overlay with valuation positioning"""
    model: str
    annualized_vol: float
    horizon_days: int
    percentile_rank: float
    valuation: str  # "cheap" | "normal" | "rich"


class VolConeResponse(BaseModel):
    """Schema for volatility cone analytics response"""
    symbol: str
    as_of: str
    windows: List[VolConeWindow]
    current_forecast: VolForecastOverlay


# Tail Risk & EVT / Copula Schemas
class EVTPOTVarMetrics(BaseModel):
    """EVT Peaks-Over-Threshold 99% VaR and Expected Shortfall metrics"""
    confidence_level: float = 0.99
    evt_pot_var_99: float
    evt_pot_es_99: float
    historical_var_99: float
    historical_es_99: float
    threshold_u: float
    gpd_shape_xi: float
    gpd_scale_beta: float
    exceedances_count: int
    total_observations: int
    is_fat_tailed: bool


class HighTailRiskPair(BaseModel):
    """Pairwise lower-tail dependence risk detail"""
    pair: List[str]
    lower_tail_lambda: float
    linear_correlation: float
    degrees_of_freedom: float
    risk_category: str  # "VERY_HIGH" | "HIGH" | "MODERATE" | "LOW"


class TailDependenceMatrix(BaseModel):
    """Pairwise Student-t copula lower-tail dependence matrix"""
    tickers: List[str]
    matrix: List[List[float]]
    high_tail_risk_pairs: List[HighTailRiskPair]


class TailRiskResponse(BaseModel):
    """Schema for EVT tail risk and copula lower-tail dependence response"""
    as_of: str
    evt_var: EVTPOTVarMetrics
    tail_dependence_matrix: TailDependenceMatrix


# Equity Research & Screener Schemas
class CustomRatiosSchema(BaseModel):
    """Custom forensic and valuation ratios"""
    piotroski_score: int
    graham_number: Optional[float] = None
    graham_upside_pct: Optional[float] = None
    enterprise_value_cr: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    interest_coverage: Optional[float] = None
    cfo_to_pat_ratio: Optional[float] = None


class PeerStockSchema(BaseModel):
    """Peer comparison row"""
    rank: Optional[int] = None
    name: str
    symbol: Optional[str] = None
    cmp: Optional[float] = None
    pe: Optional[float] = None
    market_cap_cr: Optional[float] = None
    dividend_yield: Optional[float] = None
    roce: Optional[float] = None


class ConcallSchema(BaseModel):
    """Earnings conference call record"""
    date: str
    quarter: Optional[str] = None
    title: str
    transcript_url: Optional[str] = None
    audio_url: Optional[str] = None
    presentation_url: Optional[str] = None


class EquityResearchProfileResponse(BaseModel):
    """Complete equity research profile response"""
    symbol: str
    ticker: str
    name: str
    about: Optional[str] = ""
    website: Optional[str] = None
    bse_code: Optional[str] = None
    nse_symbol: Optional[str] = None
    sector: Optional[str] = None
    industry_group: Optional[str] = None
    industry: Optional[str] = None
    sub_industry: Optional[str] = None
    indices: List[str] = []
    current_price: float
    market_cap_cr: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    stock_pe: Optional[float] = None
    book_value: Optional[float] = None
    dividend_yield: Optional[float] = None
    roce: Optional[float] = None
    roe: Optional[float] = None
    face_value: Optional[float] = None
    debt_to_equity: Optional[float] = None
    peg_ratio: Optional[float] = None
    eps_ttm: Optional[float] = None
    promoter_holding: Optional[float] = None
    promoter_pledged: Optional[float] = None
    custom_ratios: CustomRatiosSchema
    cagrs: Dict[str, Dict[str, str]] = {}
    pros: List[str] = []
    cons: List[str] = []
    peers: List[Dict[str, Any]] = []
    concall_count: int = 0
    annual_reports: List[Dict[str, str]] = []
    credit_ratings: List[Dict[str, str]] = []


class ShareholdingBlock(BaseModel):
    """Shareholding pattern data block"""
    periods: List[str] = []
    rows: Dict[str, List[Any]] = {}
    chart_series: List[Dict[str, Any]] = []


class ShareholdingResponse(BaseModel):
    """Dual institutional shareholding response"""
    ticker: str
    quarterly: ShareholdingBlock
    yearly: ShareholdingBlock


class CustomRatiosResponse(BaseModel):
    """Custom ratios response"""
    ticker: str
    piotroski_score: int
    graham_number: Optional[float] = None
    graham_upside_pct: Optional[float] = None
    enterprise_value_cr: float = 0.0
    ev_to_ebitda: Optional[float] = None
    interest_coverage: Optional[float] = None
    cfo_to_pat_ratio: Optional[float] = None
    current_price: float
    ratios_history: Dict[str, Any] = {}


class ScreenerStockItem(BaseModel):
    """Stock item returned by screener"""
    symbol: str
    ticker: str
    name: str
    price: float
    market_cap_cr: float
    pe_ratio: Optional[float] = None
    roce_pct: Optional[float] = None
    roe_pct: Optional[float] = None
    dividend_yield_pct: Optional[float] = None
    book_value: Optional[float] = None


class ScreenerResponse(BaseModel):
    """Screener result response"""
    strategy: str
    name: str
    description: str
    count: int
    stocks: List[ScreenerStockItem]


class CustomScreenRequest(BaseModel):
    """Request schema for custom screener filters"""
    min_roce: Optional[float] = None
    min_roe: Optional[float] = None
    max_pe: Optional[float] = None
    min_mcap_cr: Optional[float] = None
    min_div_yield: Optional[float] = None
    max_stocks: Optional[int] = 50

