/**
 * ONE declared scale, ONE threshold set for the forecast-risk surface.
 *
 * Why this is a module and not two page-local helpers: the same two numbers are
 * rendered by two pages, and they had already drifted. `portfolio/manage` read
 * `volatility_forecast` — a DECIMAL — as if it were already a percent
 * (`{value.toFixed(2)}%` → `0.42%` for a 42% forecast) and banded it against
 * percent-space thresholds (`< 20` / `< 40`), which every fraction satisfies, so
 * all three badges were unreachable and every row badged green "Low".
 * `dashboard/forecast-risk` already had it right (`formatPercentage` ×100 and
 * `> 0.35` / `> 0.20`). Two copies of a rule is one copy too many; this is the
 * one both pages must go through.
 *
 * THE SCALE IS DECLARED, NOT GUESSED. The engine publishes it:
 *   `analytics_engine.py:5937` `"volatility_forecast_units": "annualized"` —
 *     and annualized in this engine means the /100 decimal form (:5880
 *     `annualized = np.sqrt(cumulative * 252.0 / steps) / 100.0`), so 0.42 is 42%.
 *   `analytics_engine.py:5921` `"var_units": "1_day_cumulative_return_decimal"`
 *     — a signed decimal, so -0.031 is -3.10%.
 * Both are already in fraction space, the same contract the stress payload
 * declares at `analytics_engine.py:4429-4433`
 * (`"portfolio_impact": "fraction_of_portfolio_value"`).
 *
 * Note there is deliberately no magnitude sniffing here. A
 * `Math.abs(value) <= 1 ? value * 100 : value` helper guesses the unit from the
 * number, so it multiplies exactly the legitimate in-window values and leaves
 * the ones a leveraged book can actually produce unscaled. The scale is a fact
 * about the FIELD, applied once, here.
 *
 * ABSENCE IS PRESERVED, NOT FORMATTED. Every function returns `null` for a value
 * that is absent, non-finite, or otherwise not measured, so the call site can
 * say "N/A" — it can never receive a confident-looking string for a quantity
 * nobody measured. A MEASURED zero is not absent: it returns `'0.00%'`, and a
 * band, exactly as it should.
 */

/** The three bands `portfolio/manage` badges and `forecast-risk` renders. */
export type ForecastRiskLevel = 'Low' | 'Medium' | 'High';

/**
 * Fraction-space thresholds. Both comparisons are STRICT, matching
 * `dashboard/forecast-risk/page.tsx:465`, so a forecast sitting exactly on a
 * boundary belongs to the band below it: 0.20 → Low, 0.35 → Medium.
 */
export const FORECAST_RISK_BANDS = { medium: 0.20, high: 0.35 } as const;

/**
 * A decimal fraction as a percent string, or `null` when there is no
 * measurement to report.
 *
 * `decimals` matches `forecast-risk`'s page-local `formatPercentage` default.
 */
export const formatForecastPercent = (
    value: number | null | undefined,
    decimals = 2,
): string | null => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    return `${(value * 100).toFixed(decimals)}%`;
};

/**
 * The SIGNED form, for a signed return such as `var_forecast` (a loss is
 * negative). The sign is taken from the value, not from its formatted width, so
 * a measured zero keeps the leading `+` the two pages already published.
 *
 * `null` when there is no measurement.
 */
export const formatForecastSignedPercent = (
    value: number | null | undefined,
    decimals = 2,
): string | null => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(decimals)}%`;
};

/**
 * The calibrated risk band for an annualized forward VOLATILITY FRACTION.
 *
 * `null` for an unmeasured forecast — never a band. A row the engine could not
 * forecast has no risk level, and borrowing its neighbour's would be the same
 * fabrication as rendering its number.
 */
export const forecastRiskLevel = (
    volatility: number | null | undefined,
): ForecastRiskLevel | null => {
    if (typeof volatility !== 'number' || !Number.isFinite(volatility)) return null;
    if (volatility > FORECAST_RISK_BANDS.high) return 'High';
    if (volatility > FORECAST_RISK_BANDS.medium) return 'Medium';
    return 'Low';
};