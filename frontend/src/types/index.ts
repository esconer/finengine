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
  // Explicit monetary-unit contract. Legacy calculated fields are native;
  // *_base fields are converted into the response's requested base currency.
  native_currency?: string;
  value_currency?: string;
  fx_rate?: number | null;
  fx_provenance?: Record<string, unknown>;
  market_value_base?: number | null;
  buy_price_base?: number | null;
  last_price_base?: number | null;
  current_value_base?: number | null;
  total_cost_base?: number | null;
  unrealized_gain_loss_base?: number | null;
  unrealized_gain_loss_pct_base?: number | null;
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
  currency?: string;
  base_currency?: string;
  currency_provenance?: Record<string, unknown>;
  position_currencies?: Record<string, string>;
}

// Forecast Risk Metrics Type
// Fabricable metrics are `number | null` — never invent numbers; pages render
// N/A. Optional flags mirror the backend null+flag contract (model_fitted /
// is_limited_history / error) on endpoints without a response_model.
// The realized-risk wire shape has NO declaration here: that endpoint returns an
// ENVELOPE of blocks, not a flat metrics object, so it is declared once in
// `@/lib/api` as `RealizedRiskEnvelope` + `RealizedRiskPortfolioBlock`. A second
// copy of the same payload in two files is the drift hazard this project exists
// to prevent, and it already bit once (a `types` copy typed the envelope as a
// flat block, so every `portfolio` access failed and the hook erased it to `any`).
export interface ForecastRiskMetrics {
  model: "EWMA" | "GARCH" | "EGARCH";
  horizon: number;
  volatility_forecast: number | null;
  var_forecast: number | null;
  cvar_forecast: number | null;
  confidence_interval?: [number, number] | null;
  model_params?: Record<string, any>;
  model_fitted?: boolean;
  is_limited_history?: boolean;
  error?: string;
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
  diversification_score?: number | null;
  error?: string;
  by_weight: Record<string, number>;
  by_sector: Record<string, number>;
  methodology?: string;
  zero_metrics?: boolean;
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
  zero_metrics?: boolean;
  error?: string;
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
  region?: string;
  custom_name?: string;
  added_on?: string;
}

export interface PortfolioUpdateRequest {
  weight?: number;
  quantity?: number;
  buy_price?: number;
  custom_name?: string;
  added_on?: string;
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

// ponytail: phantom contract — no implementation exists anywhere; the UI
// "currency toggle" is symbol-swap only around the same number (04-B14).
// Handoff: implement a real FX source behind this interface or delete it
// and drop the USD toggle's pretense of conversion.
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

/**
 * Did the section produce a usable result at all?
 *
 * A section that was not requested is simply absent from `sections`; it is
 * never serialized as a `not_requested` row, so this union has no such member.
 */
export type AIContextStatus = 'available' | 'partial' | 'unavailable';

/** `summary` shortens bulky chart/history series; `full` retains them. */
export type AIContextDetail = 'summary' | 'full';

/**
 * How much of the requested universe reached the result. A separate axis from
 * `AIContextStatus` and from {@link AIDataStatus}:
 *
 * - `complete`    — every requested ticker is in the result.
 * - `partial`     — some requested tickers are measurably missing.
 * - `unavailable` — the requested universe produced no measurable result.
 * - `unknown`     — the endpoint does not report its result universe, so
 *                   coverage is unmeasured. Not the same as `unavailable`.
 */
export type AIContextCoverageStatus = 'complete' | 'partial' | 'unavailable' | 'unknown';

/**
 * Normalized public `data_status` vocabulary for component payloads. Reports
 * whether measured data exists; it is never `complete`/`unknown`, and the
 * requested-vs-measured universe question stays in `coverage.status`.
 */
export type AIDataStatus = 'available' | 'partial' | 'unavailable';

/**
 * Present ONLY when a weighting calculation actually dropped an unavailable
 * active leg and renormalized the surviving weights to 100%. Omission is
 * meaningful: weightless analyses (correlation/tail matrices, pair scans,
 * regime, calendar-series sections) have no allocation basis and must not
 * claim one. Absence means "not renormalized or not weight-bearing" — never
 * assume the full book was measured.
 */
export type AIContextWeightBasis = 'active_weights_renormalized_to_100_percent';

export interface AIContextCoverage {
  /**
   * Full persisted/request universe, uppercased, de-duplicated, and kept in
   * stable request order. Never sorted, never truncated.
   */
  requested_tickers: string[];
  /**
   * Universe that actually produced the result, or `null` when the endpoint
   * does not report one (status `unknown`). Sections that union several result
   * maps or pair rows (risk contribution, pairs, stress testing) may emit this
   * sorted, so consumers must derive ordering from `requested_tickers`.
   */
  available_tickers: string[] | null;
  /**
   * Requested tickers present in `available_tickers`, in requested order.
   * Omitted when coverage is `unknown`.
   */
  covered_tickers?: string[];
  /** Requested tickers absent from `available_tickers`, in requested order. */
  missing_tickers: string[] | null;
  /**
   * The endpoint's own wider `available_tickers` claim, preserved when the
   * exporter had to subtract declared-missing tickers. Audit trail only.
   */
  raw_available_tickers?: string[];
  /** Size of `requested_tickers`; omitted when coverage is `unknown`. */
  requested_count?: number;
  /**
   * Count of covered tickers, which is not necessarily the length of
   * `available_tickers`. Omitted when coverage is `unknown`.
   */
  available_count?: number;
  /** covered / requested, or `null` when there is no requested universe. */
  coverage_ratio: number | null;
  /** `true` only when nothing is missing; `null` when coverage is unmeasured. */
  complete: boolean | null;
  status: AIContextCoverageStatus;
  weight_basis?: AIContextWeightBasis;
}

export interface AIContextSection {
  key: string;
  title: string;
  route: string;
  status: AIContextStatus;
  detail: AIContextDetail;
  /** Collection time for this section — never a substitute for `as_of`. */
  generated_at: string;
  /**
   * Freshness anchor, or `null` when the endpoint supplied no observation date
   * (unknown freshness, not "fresh"). Inference precedence in the payload:
   * `latest_observation_date`, `as_of`, `last_updated`, `updated_at`; then the
   * same search under a nested `data`; then — for a composite — the OLDEST
   * component timestamp, because a composite is only as fresh as its stalest
   * leg. A composite can therefore be older than its portfolio snapshot.
   * Requested window end dates stay in `inputs` and are never substituted here.
   */
  as_of: string | null;
  /**
   * Which declared field produced `as_of` (e.g. `latest_observation_date`,
   * `liquidity_component_only`, `oldest_component_observation`), or `null`
   * when the section measured no freshness at all. Published on the envelope by
   * every section, so a reader can tell WHAT the date measures instead of
   * guessing — and the backend's response model declares it
   * (`as_of_semantics: Optional[str] = None`), so the key is always on the wire
   * even where the label is null.
   */
  as_of_semantics?: string | null;
  /**
   * Explicitly declared monetary unit, uppercased, or `null` when nothing
   * declared one. Precedence: the section payload's own declaration, then a
   * nested `data` declaration, then component payloads ONLY when every measured
   * component agrees, then the unit recorded in `inputs`. Conflicting component
   * units resolve to `null` and raise a "mixes monetary units" warning, so a
   * composite is never labelled with one arbitrary leg's currency.
   * The envelope `base_currency` is not an implicit fallback: an analytics
   * section reporting `null` has an unknown unit, not INR.
   */
  currency: string | null;
  inputs: Record<string, unknown>;
  /** `null` for sections with no ticker universe. */
  coverage: AIContextCoverage | null;
  data: unknown;
  omitted_fields: string[];
  warnings: string[];
  /**
   * OMITTED ENTIRELY when the section succeeded — the key is absent, never
   * `null`. A successful section must not publish a null-error sentinel, so
   * consumers check `section.error === undefined` (or `'error' in section`)
   * rather than comparing against `null`.
   */
  error?: string;
}

/**
 * The section envelope keys a referenced dashboard component carries beside its
 * pointer. They are COPIES of the referenced section's own values, not
 * independent measurements, so the two paths cannot disagree.
 */
export interface AIContextReferencedComponentMetadata {
  as_of?: string | null;
  as_of_semantics?: string | null;
  currency?: string | null;
  detail?: AIContextDetail;
  inputs?: Record<string, unknown>;
  omitted_fields?: string[];
  warnings?: string[];
  /** Absent on a successful twin, never a null sentinel. */
  error?: string;
}

/**
 * A dashboard component that POINTS at the section holding its payload.
 *
 * The document publishes eight of the dashboard's eleven components as their
 * own top-level sections too, so the exporter does not republish those payloads
 * a second time: a referenced component publishes no `data` key at all and the
 * payload lives at `<data_ref>.data` in the same document. `data_ref_status` is
 * deliberately not named `data_status` — that is a normalized contract
 * vocabulary (`available` / `partial` / `unavailable`) and reusing the name for
 * "this is a pointer" would put a word outside it.
 *
 * There is no `data` on this arm. That is the point: reading `.data` here is a
 * compile error, not an `undefined` that renders as an empty block. Dereference
 * `data_ref` against the response object to reach the payload.
 */
export interface AIContextReferencedComponent extends AIContextReferencedComponentMetadata {
  data_inline: false;
  /** Dot-separated path into this same document, e.g. `sections.portfolio`. */
  data_ref: string;
  data_ref_status: 'referenced';
  status: AIContextStatus;
}

/**
 * A component with no standalone section — `summary`, `risk_score`,
 * `performance_history`. It is the only publication of that payload in the
 * document, so it keeps its own `data` and points at nothing. `data` may still
 * be `null` when the component failed; a null payload is not the same thing as
 * a pointer, and the two are told apart by `data_inline`, not by the presence of
 * `data`.
 */
export interface AIContextInlineComponent extends AIContextReferencedComponentMetadata {
  data_inline: true;
  data: unknown;
  status: AIContextStatus;
}

/**
 * One entry of `sections.dashboard.data.components`.
 *
 * NOT an {@link AIContextSection}, and the two must not be unified: a top-level
 * section always publishes `data`, while a referenced component never does.
 * Typing the component map as the section envelope is what let eight of eleven
 * components be read as though they carried a payload they do not.
 *
 * Component-specific extras beside these keys (`performance_history`'s
 * `history_coverage` and breadth block, for one) are NOT modelled here, so
 * reading them is a compile error rather than a silent `undefined`. Reach them
 * through a narrowed local type, not through this one.
 */
export type AIContextDashboardComponent =
  | AIContextReferencedComponent
  | AIContextInlineComponent;

export interface AIContextResponse {
  schema_version: string;
  export_id: string;
  generated_at: string;
  completed_at: string;
  snapshot_consistency: 'best_effort' | 'frozen';
  /**
   * AD-16: the EVIDENCE beside the collection-mode claim above, not a
   * replacement for it. `snapshot_consistency` says how the export was
   * collected; this says whether the prices that came back actually agreed.
   * The full block, with per-ticker attribution and what it invalidates, lives
   * at `sections.portfolio.data.snapshot_consistency`.
   */
  snapshot_consistency_measured?: {
    status?: 'single_instant' | 'multiple_instants' | 'partial' | 'unmeasured' | string;
    distinct_price_instants?: number | null;
    distinct_delivered_bar_dates?: number | null;
    mark_instant_spread_seconds?: number | null;
    delivered_bar_spread_calendar_days?: number | null;
    per_position_price_as_of_at?: string;
    what_this_invalidates_at?: string;
    detail_at?: string;
    reason?: string;
  };
  base_currency: 'INR' | 'USD';
  currency_policy: string;
  detail: AIContextDetail;
  /** Resolved section keys, in request/catalog order. */
  scope: string[];
  environment: Record<string, unknown>;
  /**
   * Keyed by section key, in `scope` order, so a repeated universe yields a
   * stable request order across exports. A section that was not requested is
   * absent from both `scope` and `sections`; a requested section that failed is
   * present and carries its reason.
   */
  sections: Record<string, AIContextSection>;
  warnings: string[];
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
    model_fitted?: boolean;
    is_limited_history?: boolean;
    error?: string;
  };
  positions: Record<string, {
    volatility_forecast?: number | null;
    var_forecast?: number | null;
  }>;
  model_params?: Record<string, any>;
  model_fitted?: boolean;
  is_limited_history?: boolean;
  error?: string;
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
  zero_metrics?: boolean;
  error?: string;
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
  portfolio_in_current_regime?: {
    days: number;
    ann_ret: number | null;
    ann_vol: number | null;
    total_ret?: number | null;
    annualized?: boolean;
    history_coverage?: {
      effective_start: string | null;
      oldest_holding: string | null;
      covered_days: number;
      truncated: boolean;
      annualized: boolean;
      requested_start: string | null;
    } | null;
  };
}

/**
 * How the risk-contribution section names its two models.
 *
 * ONE NAME PER MODEL, IN EVERY CONTAINER. The backend keys `positions`,
 * `sector_rollup`, `excluded_assets`, `contribution_basis.per_model` and
 * `universe_coverage.model_used_tickers` by these two names, and publishes the
 * retired bare `cvar` as a POINTER in `contribution_basis.model_names.aliases`
 * rather than as a second key in each container.
 *
 * `cvar_tail` is the canonical spelling and the only one on the wire. `cvar` is
 * NOT a field here on purpose: declaring it as a sibling of `cvar_tail` compiles
 * clean and reads `undefined`, which is the silent-empty the alias map exists to
 * prevent. A consumer holding a retired name resolves it through
 * {@link RISK_CONTRIBUTION_MODEL_ALIASES} and reads the canonical key.
 */
export type RiskContributionModelName = 'volatility' | 'cvar_tail';

/** A spelling this section used to publish and no longer does. */
export type RiskContributionRetiredModelName = 'cvar';

/**
 * Retired spelling -> the canonical name that replaced it, mirroring
 * `contribution_basis.model_names.aliases` on the wire. Declared as a type
 * rather than a second field so the two names cannot both be read off one
 * container and a reader cannot mistake the copy for the measurement.
 */
export type RiskContributionModelAliases = Readonly<
  Record<RiskContributionRetiredModelName, RiskContributionModelName>
>;

/** `contribution_basis.model_names`, as the section publishes it. */
export interface RiskContributionModelNames {
  canonical: readonly RiskContributionModelName[];
  aliases: RiskContributionModelAliases;
  basis: string;
}

export interface RiskContributionResponse {
  window: { start: string; end: string };
  positions: {
    volatility: Record<string, number>;
    cvar_tail: Record<string, number>;
  };
  sector_rollup: {
    volatility: Record<string, number>;
    cvar_tail: Record<string, number>;
  };
  /**
   * `null` when the annualization gate declined to publish it — the endpoint
   * sets the key to `null` below the minimum measured return sample rather than
   * annualizing a short history. Not `0`: a zero would be a measured flat book.
   */
  portfolio_volatility_annualized: number | null;
  portfolio_var_95_daily: number;
  /** `null` when the window produced no tail days at all. */
  portfolio_cvar_95_daily: number | null;
  methodology: string;
}

export interface StressTestResponse {
  scenario: string;
  scenario_description?: string;
  max_drawdown: number | null;
  portfolio_impact: number | null;
  position_impacts: Record<string, number>;
  recovery_time: number | null;
  confidence_level: number;
  methodology?: string;
  error?: string;
}

/**
 * Where the one weight-normalization rule (`divide_all_legs_by_gross_exposure`,
 * shared by volatility sizing and rebalance) places a target.
 *
 * - `fully_funded` — gross == 1.0: a normal rebalance, no financing.
 * - `financed_gross_exposure_exceeds_100_percent` — gross > 1.0: borrows
 *   `gross - 1`, NOT executable as a normal rebalance.
 * - `unlevered_long_only_plus_cash` — gross < 1.0: the remainder is cash.
 * - `empty_target` — gross == 0.0: a full exit, not an allocation.
 */
export type VolSizingNormalizationMode =
  | 'fully_funded'
  | 'financed_gross_exposure_exceeds_100_percent'
  | 'unlevered_long_only_plus_cash'
  | 'empty_target';

/**
 * Per-leg instruction status.
 *
 * `below_minimum_notional` is a MATERIAL notional that rounds below one whole
 * share: its amount and `rounding_residual` are published and its
 * `shares_delta` is `0`, so consumers must report the notional rather than
 * render a fabricated "no trade". `unavailable` means the instruction could
 * not be computed (no sizing price, or no portfolio value) — `amount` and
 * `shares_delta` are then `null`, never `0`.
 */
export type VolSizingTradeStatus =
  | 'executable'
  | 'below_minimum_notional'
  | 'immaterial_no_op'
  | 'no_trade_required'
  | 'unavailable';

/** Minimum-sample gate for the history the sizing actually measured. */
export type VolSizingSampleStatus = 'sufficient' | 'insufficient';

/**
 * Financing need of a target. The engine publishes the quantified amount as a
 * scalar and `null` when no portfolio value makes it computable; a richer
 * `{weight, amount, currency}` form is accepted. `null` is never a zero.
 */
export interface VolSizingFinancingRequirement {
  weight?: number | null;
  amount?: number | null;
  currency?: string | null;
}

export interface VolSizingExecutionBlock {
  /** The documented rule both consumers apply. */
  normalization_rule: string;
  normalization_mode: VolSizingNormalizationMode;
  /** False for the analytical sizing target: it keeps its gross exposure. */
  weights_normalized: boolean;
  /** Sum of absolute legs. May exceed 1.0. */
  gross_exposure: number;
  /** `1 - gross_exposure`; negative for a borrowed book. */
  net_cash_weight: number;
  financing_required: boolean;
  financing_requirement: number | VolSizingFinancingRequirement | null;
  financing_requirement_currency: string | null;
  /**
   * The single question this answers: may these weights be applied as a plain
   * rebalance? False whenever gross exposure exceeds 100 %.
   */
  execution_eligible: boolean;
  block_reasons: string[];
  block_reason: string | null;
}

/** Additive exposure roll-up; falls back to `execution` when absent. */
export interface VolSizingExposureBlock {
  gross_exposure: number | null;
  net_exposure: number | null;
  cash_weight: number | null;
  financing_weight: number | null;
  financing_amount: number | null;
  currency: string | null;
  portfolio_value: number | null;
}

/**
 * Additive sizing-basis block. `sizing_price_as_of` is a SINGLE aligned
 * snapshot date, not a per-ticker map: mixing per-ticker "last known" prices
 * would let one leg trade at a stale date behind one freshness claim.
 */
export interface VolSizingBasisBlock {
  sizing_price: Record<string, number> | null;
  sizing_price_as_of: string | null;
  price_currency: string | null;
  price_currency_provenance: string | null;
  status: string;
}

export interface VolSizingHistoryBlock {
  model: string | null;
  window_start: string | null;
  window_end: string | null;
  price_window_start: string | null;
  price_window_end: string | null;
  return_observations: number;
  per_ticker_return_observations: Record<string, number>;
  min_return_observations: number;
  max_return_observations: number;
  latest_observation: string | null;
  minimum_observations_required: number;
  meets_minimum_sample: boolean;
  minimum_sample_status: VolSizingSampleStatus;
  tickers_below_minimum_sample: string[];
}

export interface VolSizingTrade {
  /** `null` when no whole-share instruction exists (V3-04). */
  shares_delta: number | null;
  /** `null` only when no portfolio value made a notional computable. */
  amount: number | null;
  amount_currency: string | null;
  sizing_price: number | null;
  rounding_residual: number | null;
  rounding_tolerance?: number | null;
  below_minimum_notional: boolean;
  status: VolSizingTradeStatus;
  reason: string | null;
}

export interface VolSizingReconciliationBlock {
  rule: string;
  share_rounding_rule: string;
  amount_decimals: number;
  amount_rounding_quantum: number;
  notional_floor: number;
  notional_floor_currency: string | null;
  sizing_price_as_of: string | null;
  sizing_price_provenance: string;
  reconciled: boolean;
  priced_trades: number;
  max_abs_rounding_residual: number | null;
  max_rounding_tolerance: number | null;
  below_minimum_notional_tickers: string[];
  immaterial_no_op_tickers: string[];
  unavailable_tickers: string[];
}

export interface VolatilitySizingResponse {
  current_weights: Record<string, number>;
  recommended_weights: Record<string, number>;
  trades: Record<string, VolSizingTrade>;
  target_volatility: number;
  current_volatility?: number | null;
  volatilities?: Record<string, number>;
  volatility_sources?: Record<string, string>;
  model_params?: Record<string, any>;
  methodology?: string;
  scale_factor?: number;
  /** Signed net cash weight: negative for a borrowed book, never a flat 0. */
  cash_weight?: number;
  leveraged?: boolean;
  achieved_volatility?: number;
  execution?: VolSizingExecutionBlock;
  exposure?: VolSizingExposureBlock;
  sizing_basis?: VolSizingBasisBlock;
  sizing_history?: VolSizingHistoryBlock;
  trade_instructions_status?: 'reconciled' | 'not_reconciled' | 'unavailable';
  trade_reconciliation?: VolSizingReconciliationBlock;
  sizing_price?: Record<string, number>;
  sizing_price_as_of?: string | null;
  sizing_price_currency?: string | null;
  sizing_price_provenance?: string;
  sizing_price_unavailable_reason?: string | null;
  sizing_price_missing_tickers?: string[];
  sizing_price_unpriced_tickers?: string[];
  price_currency_provenance?: string;
  portfolio_value?: number;
  portfolio_value_currency?: string | null;
  currency?: string;
  base_currency?: string;
  universe_coverage?: AIContextCoverage;
  data_status?: AIDataStatus;
  data_unavailable_tickers?: string[];
  weight_basis?: AIContextWeightBasis;
  error?: string;
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
  // Normalized public vocabulary. Requested-vs-measured universe size is
  // reported by the export's `coverage` object, not by this flag.
  data_status?: AIDataStatus;
  error?: string | null;
}

export interface IndiaFlowsResponse {
  delivery_spikes: Array<{ ticker: string; delivery_pct: number; avg_delivery_pct: number; spike: boolean }>;
  institutional_flows: { fii_net_cr: number | null; dii_net_cr: number | null; date: string };
  adv_liquidity: Record<string, { adv_shares: number; days_to_liquidate_10pct: number; days_to_liquidate_20pct: number }>;
  data_status?: AIDataStatus;
  /** Measured institutional-flow legs; an absent leg is never a measured zero. */
  available_categories?: string[];
  missing_categories?: string[];
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
