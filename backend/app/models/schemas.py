"""
Pydantic schemas for Daisy Risk Engine
"""

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
import math
from pydantic import BaseModel, Field, model_serializer, validator


# Portfolio Schemas
class PortfolioPositionBase(BaseModel):
    """Base portfolio position schema with comprehensive validation"""
    ticker: str = Field(..., min_length=1, max_length=20, pattern=r"^[A-Z0-9\-\&\.]{1,20}$", description="Stock ticker symbol")
    weight: float = Field(..., gt=0, le=1, description="Portfolio weight (0-1)")
    quantity: float = Field(..., gt=0, description="Number of shares/units held - must be > 0")
    buy_price: float = Field(..., gt=0, description="Price per share at time of purchase - must be > 0")
    region: Optional[str] = Field(default=None, description="Region code; inferred from ticker when omitted")
    custom_name: Optional[str] = Field(default=None, max_length=100, description="Custom position name")
    added_on: Optional[date] = Field(default=None, description="Purchase date (YYYY-MM-DD); defaults to today. Must not be in the future.")

    # pre=True so uppercasing happens BEFORE the pattern check (lowercase
    # input like "infy.ns" stays legal; "BAD TICKER!" is rejected at schema level)
    @validator('ticker', pre=True)
    def ticker_must_be_uppercase(cls, v):
        if not isinstance(v, str):
            return v
        if not v.strip():
            raise ValueError('Ticker cannot be empty')
        return v.upper().strip()

    @validator('weight')
    def weight_must_be_valid(cls, v):
        if not (0 < v <= 1):
            raise ValueError('Weight must be between 0 and 1 (exclusive of 0, inclusive of 1)')
        return v

    @validator('quantity')
    def quantity_must_be_positive(cls, v):
        if not math.isfinite(float(v)) or v <= 0:
            raise ValueError('Quantity must be finite and greater than 0')
        return v

    @validator('buy_price')
    def buy_price_must_be_positive(cls, v):
        if not math.isfinite(float(v)) or v <= 0:
            raise ValueError('Buy price must be finite and greater than 0')
        return v

    @validator('added_on')
    def added_on_not_in_future(cls, v):
        if v is not None and v > date.today():
            raise ValueError('added_on cannot be in the future')
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
    added_on: Optional[date] = Field(None, description="Purchase date (YYYY-MM-DD). Must not be in the future.")

    @validator('added_on')
    def added_on_not_in_future(cls, v):
        if v is not None and v > date.today():
            raise ValueError('added_on cannot be in the future')
        return v

    @validator('weight', 'quantity', 'buy_price')
    def finite_positive_values(cls, v):
        if v is not None and not math.isfinite(float(v)):
            raise ValueError('numeric portfolio values must be finite')
        return v


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
    region: Optional[str] = None
    custom_name: Optional[str]
    added_on: datetime
    updated_on: Optional[datetime] = None
    # Calculated fields
    total_cost: float
    unrealized_gain_loss: float
    unrealized_gain_loss_pct: float
    current_value: float
    # Explicit monetary-unit contract. Legacy calculated fields above remain
    # native-unit values for backward compatibility; *_base fields are the
    # values converted into the envelope's requested base currency.
    native_currency: Optional[str] = None
    value_currency: Optional[str] = None
    fx_rate: Optional[float] = None
    fx_provenance: Optional[Dict[str, Any]] = None
    market_value_base: Optional[float] = None
    buy_price_base: Optional[float] = None
    last_price_base: Optional[float] = None
    current_value_base: Optional[float] = None
    total_cost_base: Optional[float] = None
    unrealized_gain_loss_base: Optional[float] = None
    unrealized_gain_loss_pct_base: Optional[float] = None

    class Config:
        from_attributes = True


class PortfolioSummaryResponse(BaseModel):
    """Schema for portfolio summary"""
    positions: List[PortfolioPositionResponse]
    total_value: float
    total_positions: int
    total_weight: float
    sectors: Dict[str, float]


class AIContextSection(BaseModel):
    """One page-level result in the portfolio AI context export."""
    key: str
    title: str
    route: str
    status: Literal["available", "partial", "unavailable"]
    detail: Literal["summary", "full"]
    generated_at: datetime
    as_of: Optional[str] = None
    # Which declared field produced `as_of` (e.g. `latest_observation_date`,
    # `last_updated`, or `oldest_component_observation` for a composite page
    # whose value is its stalest measured component). Absent when the section
    # measured no freshness at all.
    as_of_semantics: Optional[str] = None
    currency: Optional[str] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    coverage: Optional[Dict[str, Any]] = None
    data: Optional[Any] = None
    omitted_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class AIContextResponse(BaseModel):
    """Stable JSON envelope consumed by AI clients."""
    schema_version: str
    export_id: str
    generated_at: datetime
    completed_at: datetime
    snapshot_consistency: Literal["best_effort", "frozen"]
    # Declared here, not added at runtime by the exporter, for the reason
    # CointScannerResponse spells out below: FastAPI re-serialises against the
    # DECLARED response_model, so a key the route only adds is dropped from the
    # HTTP wire while the in-process exporter still sees it -- the audited path
    # and the wire disagree. `snapshot_consistency` is the collection-mode claim
    # (best_effort / frozen); this is the measured evidence beside it, per AD-16.
    snapshot_consistency_measured: Optional[Dict[str, Any]] = None
    base_currency: Literal["INR", "USD"]
    currency_policy: str
    detail: Literal["summary", "full"]
    scope: List[str]
    environment: Dict[str, Any] = Field(default_factory=dict)
    sections: Dict[str, AIContextSection]
    warnings: List[str] = Field(default_factory=list)


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
    """Schema for stock quote response, including provider provenance."""
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
    previous_close: Optional[float] = None
    change_percent: Optional[float] = None
    currency: Optional[str] = None
    exchange: Optional[str] = None
    is_indian: Optional[bool] = None
    source: Optional[str] = None
    timestamp: Optional[datetime] = None


class BatchStockDataRequest(BaseModel):
    """Schema for batch stock data request"""
    tickers: List[str] = Field(..., min_length=1)
    start: Optional[str] = None
    end: Optional[str] = None
    force_refresh: bool = False


class BatchStockDataResponse(BaseModel):
    """Schema for batch stock data response"""
    data: Dict[str, List[StockDataResponse]]
    failed_tickers: List[str]


class ValidateTickerRequest(BaseModel):
    """Schema for ticker validation request"""
    ticker: str = Field(..., min_length=1, max_length=20, pattern=r"^[A-Z0-9\-\&\.]{1,20}$")

    @validator('ticker', pre=True)
    def ticker_uppercase(cls, v):
        # Mirror portfolio._TICKER_PATTERN semantics: match against uppercased input
        return v.upper().strip() if isinstance(v, str) else v


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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
#: The only token `CorrelationDataPoint.measurement_status` can carry. Named at
#: module level so the vocabulary has one name rather than a literal repeated at
#: the publication site and in the tests that pin it. See the field's
#: `description` for the token -> meaning mapping; it is a free-form `str`, so
#: that prose is the only machine-readable place the vocabulary exists.
CORRELATION_ALL_PAIRS_MEASURABLE = "all_pairs_measurable"


class CorrelationDataPoint(BaseModel):
    """Single date point for rolling correlation history.

    `avg_correlation` is the mean over ALL C = N(N-1)/2 pairs, which is only a
    measurement of the book's average pairwise correlation on a date where
    every one of them was measurable. The two fields below publish WHY a point
    exists: `pairs_contributing` is the denominator that number was taken over,
    so a reader can see the book it was measured on rather than inferring it,
    and `measurement_status` names the condition that admitted the date.

    Both are ADDITIVE and defaulted. A payload built without them still
    constructs and still serialises, and `None` means the denominator was NOT
    recorded - never "some pairs were measured".
    """
    date: str
    avg_correlation: float
    threshold_90th: Optional[float] = None
    threshold_75th: Optional[float] = None
    pairs_contributing: Optional[int] = Field(
        default=None,
        description=(
            "How many of the book's N*(N-1)/2 pairs were measurable on this "
            "date, i.e. the denominator `avg_correlation` was taken over. "
            "The prefactor in the documented formula is 1/C, so the figure is "
            "the book's average only when this equals C; a date short of it is "
            "not published at all rather than averaged over the pairs that "
            "survived. Equal to C on every point a measurement service emits."
        ),
    )
    measurement_status: Optional[str] = Field(
        default=None,
        description=(
            "Why this date was publishable. 'all_pairs_measurable' = all "
            "C = N*(N-1)/2 pairs had enough pairwise-complete observations in "
            "the trailing window, so the published figure is the book-wide "
            "average and not a mean over a subset. null means no denominator "
            "was recorded for this point (a caller that built the model "
            "without one); it is never a default, and no token for a partial "
            "measurement exists because a partial measurement is refused."
        ),
    )


class CorrelationStabilityResponse(BaseModel):
    """Schema for rolling 60-day correlation stability and regime break response.

    Pairwise correlation is undefined for a single holding; the nullable
    fields preserve that fact instead of publishing a fabricated 1.0.

    `as_of_semantics` is a free-form `str` - no enum, no Literal - so nothing
    machine-checks the token and this docstring is where its vocabulary lives:
    `latest_available_observation` (a real, newest delivered bar; the default on
    `CointScannerResponse`), `request_end_no_usable_price_data` (price series
    were requested and none came back) and
    `request_end_universe_too_small_for_pairs` (fewer than two names, so no pair
    was ever tested). The fewer-than-two-holdings branch of
    `/correlation-stability` publishes its own
    `request_end_universe_too_small_for_pairwise_correlation` beside those
    three rather than borrowing a sibling's token for a different cause.

    `None` means the label was NOT recorded, never "no observation": it is what
    a caller that built this model without naming one produces. Both branches of
    `/correlation-stability` now set one, so null is not a state this route can
    publish - the fewer-than-two-holdings branch with its own token above, and
    the measured branch with `latest_available_observation`, because its `as_of`
    is the newest delivered bar of the rolling series rather than a request end.
    """
    as_of: str
    as_of_semantics: Optional[str] = None
    current_avg_correlation: Optional[float] = None
    historical_threshold_90th: Optional[float] = None
    historical_threshold_75th: Optional[float] = None
    # AD-9 made the regime test two-sided, so the LOWER bound is now one of the
    # two comparisons that can fire `is_regime_break`. It has to be a field
    # rather than prose inside `message`: a consumer that cannot read the bound
    # that triggered the alert has to parse English to find out why it fired.
    historical_threshold_10th: Optional[float] = None
    historical_median: Optional[float] = None
    is_regime_break: bool
    # `alert_level` is a SEVERITY and cannot say which way the book moved:
    # "ELEVATED" is emitted by the 75th-percentile branch (co-movement RISING)
    # and by the 10th-percentile branch (co-movement COLLAPSED), and those mean
    # opposite things about diversification. So the same string is now reachable
    # from two readings a consumer cannot tell apart, and the one on the live
    # book is the falling one. `alert_level` keeps its string — it is consumed —
    # and this field carries the sign, taken from the same comparisons that set
    # the level. See the `description` for the token -> meaning mapping.
    alert_level: str  # "CRITICAL", "ELEVATED", "NORMAL"
    alert_direction: Optional[str] = Field(
        default=None,
        description=(
            "Which comparison fired, and what it means for the diversification "
            "benefit this score credits. Closed set of four: "
            "'lower_tail_collapse' = current is at or below the 10th percentile; "
            "co-movement has COLLAPSED, the positions have stopped moving "
            "together rather than moving together more, so the historical "
            "diversification benefit may not be available in this regime and "
            "estimates that assumed the median correlation no longer describe "
            "this book. A regime change, not a reassurance. "
            "'upper_tail_elevation' = current is at or above the 75th percentile "
            "and below the 90th; co-movement is RISING from this book's own "
            "history, the direction in which diversification erodes. "
            "'upper_tail_critical' = current is at or above the 90th percentile; "
            "co-movement is at the top of its own history, a diversification "
            "breakdown. "
            "'within_band' = current is between the 10th and 75th percentiles; "
            "no tail fired, so this section neither supports nor contradicts the "
            "diversification benefit. "
            "null means no comparison ran at all (a single holding has undefined "
            "pairwise correlation and therefore no percentile to rank against); "
            "it is never a default, and every arm that sets `alert_level` also "
            "sets a direction."
        ),
    )
    message: str
    series: List[CorrelationDataPoint]
    requested_tickers: List[str] = Field(default_factory=list)
    available_tickers: List[str] = Field(default_factory=list)
    missing_tickers: List[str] = Field(default_factory=list)
    data_status: str = "available"
    universe_coverage: Optional[Dict[str, Any]] = None


# Cointegration Scanner Schemas
#: Fields of `CointScannerResponse` that the pairs route supplies at call time
#: rather than at construction. They are declared (so FastAPI's `response_model`
#: keeps them on the wire) but omitted from the dump while they still hold their
#: default, so the route can pass them without colliding with the base payload.
_COINT_ROUTE_FILLED_DISCLOSURES: Tuple[str, ...] = (
    "currency",
    "currency_provenance",
    "currency_basis",
    "warnings",
)


class CointPairResult(BaseModel):
    """Schema for a single cointegrated pair analysis result.

    Every field added after the original contract is ``Optional[...] = None``
    on purpose: ``CointegrationService._get_cached_pair`` reconstructs this
    model from DB cache rows written by older builds, and a required or
    defaulted (non-None) field would either fail that load or silently publish
    a value the row never carried. Absent means "not recorded", not "zero".
    """
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
    # OLS standard errors for the spread regression that produced
    # `hedge_ratio_beta` and `intercept_alpha`. The slope drives a trade
    # instruction, so publishing it with no standard error gives that
    # instruction false precision. Optional-with-None for the same reason as
    # every other field here: absent means "not recorded", never 0.0.
    hedge_ratio_beta_std_error: Optional[float] = None
    intercept_alpha_std_error: Optional[float] = None
    hedge_regression_observations: Optional[int] = None
    hedge_regression_std_error_basis: Optional[str] = None
    # The Johansen diagnostic's verdict, or None when the test could not be
    # computed. Not a defaulted bool: a required `bool` makes a degraded or
    # failed computation indistinguishable from a measured one, and a
    # `bool = False` default fabricates a measurement the row never made.
    # None means "no verdict" - the test did not answer - which is a
    # different claim from False, which means "the test answered: no".
    # `build_pair_signal` blocks on both, but publishes a different reason.
    johansen_cointegrated: Optional[bool] = None
    last_price_a: float
    last_price_b: float
    observation_date_a: Optional[str] = None
    observation_date_b: Optional[str] = None
    overlap_start: Optional[str] = None
    overlap_end: Optional[str] = None
    overlap_observations: Optional[int] = None
    price_basis: str = "adjusted_close_when_available"
    signal: str
    spread_series: Optional[List[Dict[str, Any]]] = None
    # Dual-test roles: `is_cointegrated` is the published decision and comes
    # from Engle-Granger; Johansen is a diagnostic cross-check that never
    # changes the decision.
    decision_test: Optional[str] = None
    johansen_role: Optional[str] = None
    johansen_agrees_with_decision: Optional[bool] = None
    # Depth bookkeeping, filled by the scan (not by the single-pair analysis)
    # because the reference is the deepest pair of the same scan.
    depth_ratio: Optional[float] = None
    depth_status: Optional[str] = None
    # --- Stationarity: the precondition cointegration is defined on --------
    # `is_cointegrated` is `engle_granger_pvalue < threshold` and stays exactly
    # that. What these three carry is WHY the pair is or is not actionable on
    # top of that verdict: Engle-Granger tests a relationship between two I(1)
    # series, so a low p-value between two already-stationary series is a
    # regression of stationarity on stationarity.
    #
    # Each leg dict holds `verdict` (`i1` / `stationary` / `undetermined`),
    # `reason`, both p-values, the resolved lag counts and the `lag_rule` the
    # p-values were produced under. `stationarity_gate` is the pair-level
    # outcome: `both_legs_i1` (the p-value is about a relationship),
    # `spurious_regression_rejected` (a leg tested stationary), or
    # `i1_not_established_on_both_legs` (a leg's stationarity was never
    # established - an absent measurement, which is NOT the same as a
    # stationary one and is published with its reason rather than a verdict
    # nobody ran).
    #
    # Optional-with-None for the same reason as every other field here: a
    # cached row written before this gate existed must still load, and an
    # absent gate means "not recorded", never "passed".
    stationarity_leg_a: Optional[Dict[str, Any]] = None
    stationarity_leg_b: Optional[Dict[str, Any]] = None
    stationarity_gate: Optional[Dict[str, Any]] = None


class CointScannerResponse(BaseModel):
    """Schema for cointegration scanner response.

    The monetary-unit and degradation declarations below are declared here, not
    smuggled in as `extra="allow"` fields. FastAPI re-serializes a route's
    response against the DECLARED `response_model`, so anything the route only
    adds at runtime is dropped from the HTTP wire even though the in-process
    exporter (which calls `model_dump()`) can see it — the AI path is audited,
    the direct API path is not. Declaring them is what makes the two agree.
    """
    as_of: str
    as_of_semantics: str = "latest_available_observation"
    latest_observation_date: Optional[str] = None
    universe_size: int
    scanned_pairs_count: int
    cointegrated_pairs_count: int
    pairs: List[CointPairResult]
    requested_tickers: List[str] = Field(default_factory=list)
    available_tickers: List[str] = Field(default_factory=list)
    missing_tickers: List[str] = Field(default_factory=list)
    requested_universe_size: int = 0
    analyzed_pairs_count: int = 0
    returned_pairs_count: int = 0
    returned_cointegrated_pairs_count: int = 0
    returned_non_cointegrated_pairs_count: int = 0
    unpairable_tickers: List[str] = Field(default_factory=list)
    data_status: str = "available"
    universe_coverage: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    # --- Pairs depth + universe semantics (V3-14) ----------------------
    # `universe_scope` is route-owned: only the caller knows whether the
    # universe was the holdings alone or holdings plus watchlist. It stays
    # None until the route declares it.
    universe_scope: Optional[str] = None
    test_roles: Optional[Dict[str, str]] = None
    usable_observations_by_ticker: Optional[Dict[str, int]] = None
    minimum_pair_observations: Optional[int] = None
    minimum_depth_ratio: Optional[float] = None
    reference_pair_observations: Optional[int] = None
    depth_status: Optional[str] = None
    depth_limited_pair_count: Optional[int] = None
    shallow_tickers: Optional[List[str]] = None
    # --- Monetary unit + degradation, on the wire (D-07) ---------------
    # `last_price_a`, `last_price_b` and the price-space `intercept_alpha` are
    # all monetary, so a payload that publishes them owes the reader a unit.
    # The provenance and the basis ship with the unit: a unit derived from the
    # scrips' exchange suffix is a property of the inputs, not a field read off
    # a quote, and must not be presented as if it were measured on a tick.
    currency: Optional[str] = None
    currency_provenance: Optional[str] = None
    currency_basis: Optional[str] = None
    # Degradation reasons. `Field(default_factory=list)` (never `Optional`) so
    # a consumer can always iterate it and the exporter's warning collector
    # never has to guard against a null.
    warnings: List[str] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def _serialize_route_filled_disclosure(
        self, handler: Any
    ) -> Dict[str, Any]:
        """Keep a still-unset disclosure out of the dump.

        The pairs route fills these four in by handing them to the constructor
        after it has already dumped the base payload, so a *declared* field
        still sitting at its default would be in that dump and collide with the
        route's own value (`TypeError: got multiple values for keyword
        argument`). Omitting a field nobody filled in is also the house rule for
        this payload — `error` is dropped the same way, and a scan that is
        clean should not publish an empty `currency: null` or `warnings: []`.

        So a disclosure is emitted only once the route has actually declared
        it. This keeps the wire byte-identical to the pre-declaration shape
        (nothing to strip) while the declaration itself is what stops FastAPI
        dropping the real value.
        """
        data = handler(self)
        fields = type(self).model_fields
        for name in _COINT_ROUTE_FILLED_DISCLOSURES:
            if name not in data:
                continue
            if data[name] == fields[name].get_default(call_default_factory=True):
                data.pop(name)
        return data


# Volatility Term Structure & Cone Schemas
class VolConeWindow(BaseModel):
    """Realized volatility quantiles for a single rolling window.

    Quantiles are Optional: the service honestly returns None on
    insufficient history (volatility_service short-window path).
    """
    window_days: int
    min: Optional[float] = None
    p25: Optional[float] = None
    median: Optional[float] = None
    p75: Optional[float] = None
    max: Optional[float] = None
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
    """EVT POT metrics with confidence-neutral primary fields.

    ``evt_pot_var``/``evt_pot_es`` and the historical counterparts describe the
    requested ``confidence_level``.  The legacy ``*_99`` names remain optional
    compatibility aliases and are only populated by the service for an actual
    99% request; arbitrary confidence values must not be mislabelled as 99%.
    """
    confidence_level: float = 0.99
    evt_pot_var: Optional[float] = None
    evt_pot_es: Optional[float] = None
    historical_var: Optional[float] = None
    historical_es: Optional[float] = None
    evt_pot_var_99: Optional[float] = None
    evt_pot_es_99: Optional[float] = None
    historical_var_99: Optional[float] = None
    historical_es_99: Optional[float] = None
    threshold_u: float
    gpd_shape_xi: Optional[float] = None
    gpd_scale_beta: Optional[float] = None
    gpd_shape_xi_raw: Optional[float] = None
    gpd_shape_xi_constrained: Optional[float] = None
    gpd_scale_beta_raw: Optional[float] = None
    gpd_scale_beta_constrained: Optional[float] = None
    evt_pot_var_unconstrained: Optional[float] = None
    evt_pot_es_unconstrained: Optional[float] = None
    constraint_applied: Optional[bool] = None
    metrics_constrained: Optional[bool] = None
    metrics_valid: Optional[bool] = None
    raw_fit_valid: Optional[bool] = None
    constrained_metrics_valid: Optional[bool] = None
    constraint_reason: Optional[str] = None
    model_fitted: bool = True
    exceedances_count: int
    total_observations: int
    # RL-2: the service can now WITHHOLD this verdict, so `null` is a reachable
    # value and a bare `bool` was a type lie. It happens when the fitted GPD
    # shape contradicts the other fatness signals: the section will not assert
    # "fat tailed" beside a bounded shape, and will not report `false` either,
    # because false would read as a measurement when nothing was classified.
    # The two new fields carry the reason and the basis. Optional-with-default
    # rather than required, matching this file's convention that absent means
    # "not recorded" and never "zero".
    is_fat_tailed: Optional[bool] = None
    is_fat_tailed_basis: Optional[Dict[str, Any]] = None
    is_fat_tailed_withheld_reason: Optional[str] = None


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
    # NULLABLE, and that is the whole point of the change. `current_price` is
    # whatever the provider resolved - `r.current_price or info["currentPrice"]`
    # - so it is genuinely absent for a name the provider did not price. The
    # producer now stops at None instead of substituting 0.0; a non-Optional
    # float turned that honest null into a pydantic ValidationError and a 500 on
    # `/company/{symbol}/full-profile`. `0.0` would have been a fabricated share
    # price sitting beside the valuation ratios derived from it.
    #
    # Distinct from `StockQuoteResponse.current_price` (above), a different
    # producer that always has a quote. Widen this one; leave that one.
    current_price: Optional[float] = None
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
    # Nullable for the same reason as the profile response's `current_price`:
    # this is the SAME measurement, carried through from the profile, so it is
    # absent exactly when the profile's is. Declaring it non-nullable here made
    # `/company/{symbol}/custom-ratios` a 500 on the honest null rather than
    # publishing it.
    current_price: Optional[float] = None
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


class ScreenerUnscored(BaseModel):
    """Which names the screen could not score, and what they were missing.

    A fundamental the provider did not return cannot satisfy a constraint on
    that fundamental, so the name is EXCLUDED rather than judged on a stand-in.
    That exclusion is a false negative against the user - the name may well have
    passed - so it has to be visible rather than silent. Measured on 75 live
    Indian symbols: 92% carried the fundamentals and 8% did not, and the
    absence is all-or-nothing per ticker (a name either resolved or it did not),
    so this list is short.

    `symbols` maps each dropped ticker to the SIDE-CHANNEL keys it was missing -
    `roce`, `roe`, `pe`, `market_cap`, `dividend_yield` - which are the
    `ScreenerService.run_custom_screen` names, not the provider's own field
    names. The shape is the service's, declared here rather than invented.

    Before this model existed the service published this block and pydantic v2's
    default `extra='ignore'` dropped it on the wire: the channel was observable
    at the service layer and invisible to every client.
    """
    count: int = 0
    symbols: Dict[str, List[str]] = {}


class ScreenerResponse(BaseModel):
    """Screener result response.

    `unscored` is ADDITIVE and defaulted, so a screen that makes no such claim
    (every prebuilt strategy) still constructs and still serialises - at null.
    Null means "this screen does not report unscored names", NOT "nothing was
    dropped": only the custom screen can drop a name for missing fundamentals,
    and it reports every drop it made.
    """
    strategy: str
    name: str
    description: str
    count: int
    stocks: List[ScreenerStockItem]
    unscored: Optional[ScreenerUnscored] = None


class CustomScreenRequest(BaseModel):
    """Request schema for custom screener filters.

    Bounds mirror the prebuilt route's Query(ge=5, le=100) on max_stocks;
    ratios are percentages (0-100), P/E and market cap are non-negative.
    """
    min_roce: Optional[float] = Field(default=None, ge=0, le=100)
    min_roe: Optional[float] = Field(default=None, ge=0, le=100)
    max_pe: Optional[float] = Field(default=None, ge=0, le=1000)
    min_mcap_cr: Optional[float] = Field(default=None, ge=0)
    min_div_yield: Optional[float] = Field(default=None, ge=0, le=100)
    max_stocks: Optional[int] = Field(default=50, ge=5, le=100)


# ---------------------------------------------------------------------------
# Marginal trade impact: what a PROPOSED change does to the book
# ---------------------------------------------------------------------------
# Everything published so far describes the portfolio as it IS. This request
# describes a change the user is contemplating, so every weight it carries is
# an instruction rather than a measurement, and the response has to say so.
#
# `target_weight` is a TARGET, not a trade size: 0.05 means "this position
# should be 5% of the book after the change". That is the only form in which
# "buy X at 5%" is unambiguous - a trade size in currency needs a portfolio
# value this endpoint does not have and does not ask for. The funding rule is
# named, never inferred (see `funding`).
MARGINAL_FUNDING_SELL_AND_REBALANCE = "sell_and_rebalance"
MARGINAL_FUNDING_CASH_RESIDUAL = "cash_residual"
MARGINAL_FUNDING_RULES = (
    MARGINAL_FUNDING_SELL_AND_REBALANCE,
    MARGINAL_FUNDING_CASH_RESIDUAL,
)

#: The one funding rule, stated as the arithmetic a reader can redo by hand.
MARGINAL_FUNDING_RULE = {
    MARGINAL_FUNDING_SELL_AND_REBALANCE: (
        "A named leg's `target_weight` is its weight in the book AFTER the "
        "change, funded by selling down the legs you did not name in "
        "proportion to their current weights. A named leg that is not currently "
        "held has no weight to sell, so the whole book is scaled by "
        "(1 - target_weight) and the named leg takes exactly `target_weight`: "
        "'buy X at 5%' leaves every existing position at 95% of its current "
        "weight. Named legs are applied first, so their sum may not exceed "
        "what the unnamed book can release."
    ),
    MARGINAL_FUNDING_CASH_RESIDUAL: (
        "A named leg's `target_weight` is its weight in the book AFTER the "
        "change, funded by holding the difference as cash rather than "
        "reallocating it. A leg you did not name keeps its current weight "
        "exactly, and any weight the book no longer spends is published as "
        "`cash_weight`; the sum of every leg plus `cash_weight` is 1.0. Use "
        "this when the money is genuinely leaving the book - otherwise "
        "`sell_and_rebalance` is the rule you want, because cash is not a "
        "diversifying asset."
    ),
}


class ProposedLegRequest(BaseModel):
    """One proposed position: a ticker and the weight it should carry after.

    `target_weight` is user-SUPPLIED. It is a target, so the response tags
    every figure derived from it `proposed` provenance rather than letting it
    read as a measurement of the book.
    """

    ticker: str = Field(..., min_length=1, max_length=20)
    target_weight: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)

    @validator("ticker", pre=True)
    def normalize_ticker(cls, value):
        return str(value or "").strip().upper()


class MarginalTradeImpactRequest(BaseModel):
    """A hypothetical change to the book, scored for what it does to risk.

    Nothing here is persisted: a proposed position is not a holding, and a
    holding written for a hypothetical would be given an `added_on` that moves
    the whole book's effective start.
    """

    legs: List[ProposedLegRequest] = Field(..., min_length=1, max_length=50)
    # Named rather than defaulted. "Buy X at 5%" does not say where the 5%
    # comes from, and silently picking a funding rule is exactly the rescaling
    # the caller did not ask for. `cash_residual` for money leaving the book.
    funding: str = Field(default=MARGINAL_FUNDING_SELL_AND_REBALANCE)
    history_days: int = Field(default=365, ge=30, le=3650)

    @validator("funding", pre=True)
    def normalize_funding(cls, value):
        normalized = str(value or "").strip().lower()
        if normalized not in MARGINAL_FUNDING_RULES:
            raise ValueError(
                f"funding must be one of {', '.join(MARGINAL_FUNDING_RULES)}"
            )
        return normalized

    @validator("legs")
    def unique_leg_tickers(cls, legs):
        tickers = [leg.ticker for leg in legs]
        duplicates = sorted({t for t in tickers if tickers.count(t) > 1})
        if duplicates:
            raise ValueError(
                f"a ticker may appear at most once in a proposal: "
                f"{', '.join(duplicates)}"
            )
        return legs


class MarginalTradeImpactResponse(BaseModel):
    """Before / after / delta for a PROPOSED change, with refusals named.

    A level is never the answer: every figure carries `before`, `after` and
    `delta`. Every figure also carries a `state` from the closed vocabulary
    `measured` / `unmeasurable` / `not_attempted` and, when it is not
    `measured`, a `reason`. An absent value is `null` plus a reason; it is
    never a zero and never a stand-in number.
    """

    proposal_provenance: str
    funding_rule: str
    current_weights: Dict[str, float]
    proposed_weights: Dict[str, float]
    cash_weight: Optional[float] = None
    funding_residual: Optional[float] = None
    concentration: Dict[str, Any]
    risk: Dict[str, Any]
    disclosure: Dict[str, Any]
    universe_coverage: Dict[str, Any]
    data_status: str = "available"
    error: Optional[str] = None


