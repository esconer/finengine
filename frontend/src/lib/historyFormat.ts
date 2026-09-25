/**
 * Holding-window disclosure vocabulary (shared by Realized Risk, Tear Sheet
 * and — via `lib/store` re-exports — any other consumer).
 *
 * Two rules, both learned from the v3 AI-context audit:
 *
 * 1. **A window start is only ever shown with its provenance.** The date the
 *    user actually stored (`added_on`) and the date we reconstructed from the
 *    buy price are different facts. Render the reconstructed one as an
 *    "inferred analytics start"; never as "held since", which claims a
 *    holding date that was never entered. When the backend has not published
 *    a source yet, the fallback derives it from data the app already holds (a
 *    start that predates the stored `added_on` cannot be the stored date) and
 *    otherwise reports the date as an analytics start of unknown provenance.
 *
 * 2. **A position's history status comes from that position's own measured
 *    return observations.** Portfolio-level and global counts must never make
 *    a 20-observation leg look like full history, and full-history
 *    instrument metrics may be named only as exchange-history measurements
 *    that do not lengthen the holding window.
 *
 * Mirrors `backend/app/utils/holdings.py` (ANALYTICS_START_SOURCES,
 * position_limited_history, analytics_start_claim, position_history_note).
 */

/** Below this many own return observations, annualized ratios stay suppressed. */
export const MIN_ANNUALIZE_OBSERVATIONS = 30;

export type AnalyticsStartSource =
  | 'stored_added_on'
  | 'buy_price_inferred'
  | 'unknown';

export const ANALYTICS_START_SOURCES: readonly AnalyticsStartSource[] = [
  'stored_added_on',
  'buy_price_inferred',
  'unknown',
];

export interface TickerHistoryCoverage {
  effective_start?: string | null;
  analytics_start?: string | null;
  analytics_start_source?: string | null;
  stored_added_on?: string | null;
  buy_price_inferred?: string | null;
  raw_days?: number | null;
  masked_days?: number | null;
  return_observations?: number | null;
  limited_history?: boolean;
  coverage_reason?: string | null;
}

export interface HistoryCoverage {
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
  tickers?: Record<string, TickerHistoryCoverage>;
}

export interface HistoryWarning {
  ticker: string;
  data_points?: number | null;
  message?: string | null;
}

/** The measured-history fields a position row carries. */
export interface HistoryObservationRow {
  return_observations?: number | null;
  data_points?: number | null;
  is_limited_history?: boolean;
  history_warning?: string | null;
}

export interface TickerStart {
  start: string | null;
  source: AnalyticsStartSource;
  storedAddedOn: string | null;
  buyPriceInferred: string | null;
}

function isoDate(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return /^\d{4}-\d{2}-\d{2}/.test(trimmed) ? trimmed.slice(0, 10) : null;
}

/** Coerce any payload value onto the documented provenance vocabulary. */
export function normalizeStartSource(value: unknown): AnalyticsStartSource {
  return ANALYTICS_START_SOURCES.includes(value as AnalyticsStartSource)
    ? (value as AnalyticsStartSource)
    : 'unknown';
}

/**
 * Resolve one ticker's window start and how it is known. A declared
 * `analytics_start_source` always wins; otherwise the stored import date the
 * app already carries (`positions[].added_on`) decides — a start that predates
 * it can only be the buy-price inference.
 */
export function resolveTickerStart(
  entry?: TickerHistoryCoverage | null,
  storedAddedOn?: string | null,
): TickerStart {
  const stored = isoDate(entry?.stored_added_on) ?? isoDate(storedAddedOn);
  const inferred = isoDate(entry?.buy_price_inferred);
  const start =
    isoDate(entry?.analytics_start) ?? isoDate(entry?.effective_start);
  const declared = normalizeStartSource(entry?.analytics_start_source);
  if (declared !== 'unknown') return { start, source: declared, storedAddedOn: stored, buyPriceInferred: inferred };
  if (start && stored) {
    return {
      start,
      source: start < stored ? 'buy_price_inferred' : 'stored_added_on',
      storedAddedOn: stored,
      buyPriceInferred: inferred,
    };
  }
  return { start, source: 'unknown', storedAddedOn: stored, buyPriceInferred: inferred };
}

/**
 * One honest phrase for how a window start is known. Same wording as
 * `app.utils.holdings.analytics_start_claim`.
 */
export function analyticsStartClaim(
  start: string | null | undefined,
  source: AnalyticsStartSource,
  storedAddedOn?: string | null,
): string {
  if (!start) return 'holding start unknown';
  if (source === 'stored_added_on') return `held since ${start} (stored import date)`;
  if (source === 'buy_price_inferred') {
    const stamp = storedAddedOn ? ` (import stamp ${storedAddedOn})` : '';
    return `analytics start ${start} is inferred from the buy price; no holding date was stored${stamp}`;
  }
  return `analytics start ${start} (provenance not reported)`;
}

/** Short inline qualifier for headlines; stored and unknown starts add nothing. */
export function startQualifier(source: AnalyticsStartSource): string {
  return source === 'buy_price_inferred' ? ' (inferred analytics start)' : '';
}

/** A ticker's own measured return observations (never a portfolio count). */
export function observationsOf(row?: HistoryObservationRow | null): number | null {
  const own = row?.return_observations;
  if (typeof own === 'number' && Number.isFinite(own)) return own;
  const points = row?.data_points;
  if (typeof points === 'number' && Number.isFinite(points)) return points;
  return null;
}

/**
 * Is THIS position's own history too short to annualize? A portfolio- or
 * global-sized sample never lifts a short leg into "full history".
 */
export function isOwnHistoryLimited(row?: HistoryObservationRow | null): boolean {
  const own = observationsOf(row);
  if (own !== null) return own < MIN_ANNUALIZE_OBSERVATIONS;
  return row?.is_limited_history === true;
}

/** "20 own return observations" — counted for this position alone. */
export function describeOwnHistory(row?: HistoryObservationRow | null): string {
  const own = observationsOf(row);
  if (own === null) return 'own return observations were not measured';
  return `${own} own return observation${own === 1 ? '' : 's'}`;
}

/** Tooltip for a position row's limited-history badge. */
export function positionHistoryTooltip(
  ticker: string,
  row?: HistoryObservationRow | null,
  start?: TickerStart | null,
): string {
  const parts = [`${ticker}: ${describeOwnHistory(row)}`];
  if (start) {
    parts.push(analyticsStartClaim(start.start, start.source, start.storedAddedOn));
  }
  if (isOwnHistoryLimited(row)) {
    parts.push(`annualized ratios are suppressed below ${MIN_ANNUALIZE_OBSERVATIONS} own observations`);
  }
  return `${parts.join('; ')}.`;
}

export interface HoldingWindowHeadlineInput {
  coveredDays?: number | null;
  start?: string | null;
  source?: AnalyticsStartSource;
  heldLonger?: number | null;
  total?: number | null;
  fullDays?: number | null;
}

/** The single summary sentence for the holding-window banner. */
export function holdingWindowHeadline({
  coveredDays,
  start,
  source = 'unknown',
  heldLonger = null,
  total = null,
  fullDays = null,
}: HoldingWindowHeadlineInput): string {
  const days = coveredDays ?? '?';
  const since = start
    ? ` since ${start}${startQualifier(source)}`
    : startQualifier(source).trim();
  const longer =
    heldLonger !== null ? ` — ${heldLonger} of ${total ?? 0} positions held longer` : '';
  const instrument = fullDays ? `; instrument risk uses full ${fullDays}d` : '';
  return `Realized P&L covers ${days} trading days${since}${longer}${instrument}`;
}

/** Compact window marker under the headline; unchanged disclosure, new fields. */
export function holdingWindowCaption(
  start?: string | null,
  fullDays?: number | null,
): string | null {
  if (!start || !fullDays) return null;
  return `{${start} · ${fullDays}d raw}`;
}

export interface ProvenanceInput {
  coverage?: HistoryCoverage | null;
  storedAddedOnByTicker?: Record<string, string | null | undefined>;
}

/**
 * Provenance of the PORTFOLIO window start (the holding intersection). The
 * intersection is the newest per-ticker start, so its provenance is that of
 * whichever ticker carries that date; a declared `effective_start_source` from
 * the route always wins.
 */
export function resolveWindowStart({
  coverage,
  storedAddedOnByTicker,
}: ProvenanceInput): TickerStart {
  const intersection = isoDate(coverage?.intersection_start) ?? isoDate(coverage?.effective_start);
  const declared = normalizeStartSource(
    coverage?.effective_start_source ?? coverage?.intersection_start_source,
  );
  if (declared !== 'unknown' && intersection) {
    const owners = Object.keys(coverage?.tickers ?? {}).filter(
      (t) => resolveTickerStart(coverage?.tickers?.[t], storedAddedOnByTicker?.[t]).start === intersection,
    );
    return {
      start: intersection,
      source: declared,
      storedAddedOn: owners.map((t) => isoDate(storedAddedOnByTicker?.[t])).find(Boolean) ?? null,
      buyPriceInferred: null,
    };
  }
  const entries = coverage?.tickers ?? {};
  const owner = Object.keys(entries)
    .sort()
    .find((t) => resolveTickerStart(entries[t], storedAddedOnByTicker?.[t]).start === intersection);
  if (owner) return resolveTickerStart(entries[owner], storedAddedOnByTicker?.[owner]);
  return { start: intersection, source: 'unknown', storedAddedOn: null, buyPriceInferred: null };
}

/** Positions whose window start is a buy-price inference, not a stored date. */
export function inferredStartTickers({
  coverage,
  storedAddedOnByTicker,
}: ProvenanceInput): { ticker: string; start: TickerStart }[] {
  const entries = coverage?.tickers ?? {};
  const out: { ticker: string; start: TickerStart }[] = [];
  for (const ticker of Object.keys(entries).sort()) {
    const start = resolveTickerStart(entries[ticker], storedAddedOnByTicker?.[ticker]);
    if (start.source === 'buy_price_inferred' && start.start) {
      out.push({ ticker, start });
    }
  }
  return out;
}

/**
 * Extra banner line naming every inferred analytics start. `null` when nothing
 * is inferred, so the banner stays unchanged for stored-date portfolios.
 */
export function provenanceNote(input: ProvenanceInput): string | null {
  const inferred = inferredStartTickers(input);
  if (!inferred.length) return null;
  return inferred
    .map(
      ({ ticker, start }) =>
        `${ticker}: ${analyticsStartClaim(start.start, start.source, start.storedAddedOn)}`,
    )
    .join(' ');
}

/**
 * Per-ticker detail sentence used when the route published no message of its
 * own. Own observation count, exchange coverage reason and start provenance —
 * no portfolio or global count can appear here. Leads with the ticker, like
 * the route's own messages, so callers never prefix it twice.
 */
export function perTickerDetail(
  ticker: string,
  coverage?: TickerHistoryCoverage | null,
  row?: HistoryObservationRow | null,
  storedAddedOn?: string | null,
): string {
  const start = resolveTickerStart(coverage, storedAddedOn);
  const parts = [describeOwnHistory(row ?? coverage)];
  if (coverage?.coverage_reason) parts.push(`Exchange coverage: ${coverage.coverage_reason}`);
  parts.push(analyticsStartClaim(start.start, start.source, start.storedAddedOn));
  return `${ticker}: ${parts.join('; ')}.`;
}
