/**
 * SectionProvenance — the one place the dashboard states WHEN a number was
 * measured, WHAT that date measures, WHICH holdings went into it, and WHAT the
 * endpoint warned about.
 *
 * This component exists because the disclosure was already on the wire and
 * already correct: a freshness date (`as_of` on the routes that declare one,
 * `latest_observation_date` on the rest), `as_of_semantics`,
 * `universe_coverage.missing_tickers` and `warnings` ship on the analytics
 * envelopes. Thirteen section pages read none of them, so a user could not tell a
 * stale risk number from a live one, and a holding silently dropped from a
 * computation left no on-screen trace. Adding the line is a rendering job, not a
 * data job — so nothing here computes, rounds, reformats or falls back.
 *
 * Three rules this component is built to hold, each of which has been broken
 * somewhere in this codebase:
 *
 * 1. NEVER invent a date. A section that publishes no measurement date renders
 *    "N/A — no measurement date published". It does not render today, and it
 *    does not render an empty line: an absent date stated as absent is a correct
 *    answer, while a silent blank is indistinguishable from a page nobody mounted.
 * 2. NEVER show a date without its meaning. `as_of_semantics` is the backend's own
 *    label for what the date measures — a delivered bar date, a quote refresh
 *    instant, the oldest leg of a composite. It is rendered verbatim, so the
 *    screen states the endpoint's meaning rather than a re-typed paraphrase of it
 *    that can drift from the contract. A payload that publishes no label says so
 *    explicitly instead of presenting a bare date as if it were self-describing.
 * 3. NEVER collapse coverage into a count. "Coverage incomplete" is not
 *    actionable; `ABC.NS` is. A section with no coverage block at all is a
 *    different fact from one reporting zero missing, and the two are rendered as
 *    two different sentences.
 */

import React from 'react';

/**
 * One warning as the analytics envelopes publish it.
 *
 * The endpoints are not uniform here and this component does not flatten them:
 * `/analytics/realized-risk`, `/forecast-risk` and `/factor-exposure` emit a
 * structured per-position warning (`RealizedRiskWarning` in `@/lib/api`),
 * `/analytics/concentration`, `/liquidity`, `/volatility-sizing` and `/coint`
 * emit plain sentences, and `/forecast-risk` also emits a `code`-keyed record
 * with no message. All three are rendered; none is dropped as "unrenderable".
 */
export type SectionWarning =
  | string
  | {
      ticker?: string | null;
      code?: string | null;
      message?: string | null;
    };

export interface SectionCoverage {
  /**
   * Requested tickers absent from the computation, verbatim and in request order.
   *
   * `null` is NOT the same as `[]` and is not the same as no `coverage` prop at
   * all. `[]` is a measured "every requested holding participated"; `null` is the
   * endpoint reporting coverage `unknown`, which measured nothing; and no
   * `coverage` prop is a section that publishes no coverage block whatsoever.
   * The backend's own contract separates all three
   * (`AIContextCoverage.missing_tickers: string[] | null`, `coverage: ... | null`),
   * and collapsing them is how "a confident number computed over fewer names than
   * they hold" becomes invisible.
   */
  missingTickers: readonly string[] | null;
}

/**
 * The `universe_coverage` block as the analytics envelopes publish it.
 *
 * Deliberately narrow rather than `Record<string, unknown>`: reading
 * `coverage.missing_tickers` off an untyped map yields `unknown`, and the
 * `unknown` has to be laundered into a string list by hand on every page. This
 * is the one place that cast happens.
 */
export interface AnalyticsCoverageBlock {
  missing_tickers?: readonly string[] | null;
}

/**
 * Bind a section's raw coverage block to the {@link SectionCoverage} prop.
 *
 * `undefined`/`null` in, `null` out — "the section publishes no coverage block"
 * — and a published block keeps its own `missing_tickers`, including a `null`
 * that means coverage `unknown`. The three states survive the trip; that is the
 * whole point of the helper.
 */
export const sectionCoverage = (
  coverage: AnalyticsCoverageBlock | null | undefined,
): SectionCoverage | null =>
  coverage ? { missingTickers: coverage.missing_tickers ?? null } : null;

export interface SectionProvenanceProps {
  /** Which section this describes, shown verbatim as the line's subject. */
  section: string;
  /**
   * The measurement date, exactly as the endpoint published it. `null` and `""`
   * both mean "no measurement date published" and render as such.
   *
   * Bind the field the section actually publishes — `as_of` where it declares one,
   * `latest_observation_date` where that is the declared freshness key. Do not
   * synthesise a field the endpoint never sent.
   */
  asOf?: string | null;
  /**
   * The backend's own label for what `asOf` measures, verbatim. Rendered as
   * published; `null` renders an explicit "no semantics declared" sentence rather
   * than leaving the date looking self-describing.
   */
  asOfSemantics?: string | null;
  /** The section's coverage block, or `null` when it publishes none. */
  coverage?: SectionCoverage | null;
  /** The section's own warnings, rendered as sent. */
  warnings?: readonly SectionWarning[] | null;
}

/**
 * An absent measurement is never a zero and never today's date. Same rule the
 * India page applies to a withheld cell (`MISSING` in `india-flows/page.tsx`).
 */
export const NO_MEASUREMENT_DATE = 'N/A — no measurement date published';

/** What one warning reads as on screen, whichever shape it arrived in. */
const warningText = (warning: SectionWarning): string | null => {
  if (typeof warning === 'string') {
    return warning.trim() ? warning.trim() : null;
  }
  const parts = [warning.ticker, warning.message ?? warning.code]
    .filter((part): part is string => typeof part === 'string' && part.trim().length > 0)
    .map((part) => part.trim());
  return parts.length ? parts.join(' — ') : null;
};

const coverageSentence = (coverage: SectionCoverage | null): string => {
  if (!coverage) {
    return 'Coverage: this section publishes no coverage block, so nothing states which holdings entered the computation.';
  }
  const missing = coverage.missingTickers;
  if (missing === null || missing === undefined) {
    return 'Coverage: unmeasured — the section reports coverage as unknown and names no missing holdings.';
  }
  if (missing.length === 0) {
    return 'Coverage: complete — every requested holding entered this computation (0 missing).';
  }
  // Named, not counted: the actionable form of a gap is the ticker list.
  return `Coverage: incomplete — ${missing.length} requested holding${missing.length === 1 ? '' : 's'} missing from this computation: ${missing.join(', ')}.`;
};

export const SectionProvenance: React.FC<SectionProvenanceProps> = ({
  section,
  asOf,
  asOfSemantics,
  coverage,
  warnings,
}) => {
  const measuredOn = typeof asOf === 'string' && asOf.trim() ? asOf.trim() : null;
  const semantics = typeof asOfSemantics === 'string' && asOfSemantics.trim()
    ? asOfSemantics.trim()
    : null;
  const warningLines = (warnings ?? [])
    .map(warningText)
    .filter((line): line is string => line !== null);

  return (
    <section
      data-testid="section-provenance"
      aria-label={`${section} provenance`}
      className="mt-6 rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-3 text-xs leading-relaxed text-slate-600 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-400"
    >
      <p data-testid="provenance-as-of">
        <span className="font-semibold">{section}</span>
        {measuredOn ? (
          <>
            {' — measured as of '}
            <strong className="font-semibold text-slate-900 dark:text-slate-100">{measuredOn}</strong>
          </>
        ) : (
          <>
            {' — '}
            <strong className="font-semibold text-slate-900 dark:text-slate-100">{NO_MEASUREMENT_DATE}</strong>
          </>
        )}
      </p>

      {/* A date without its meaning is decoration. The label is the endpoint's
          own, rendered verbatim so the screen cannot drift from the contract. */}
      <p data-testid="provenance-as-of-semantics" className="mt-1">
        {semantics ? (
          <>
            {'This date measures: '}
            <code className="font-mono">{semantics}</code>
          </>
        ) : (
          'This section declares no semantics for the date above, so what it measures is unstated.'
        )}
      </p>

      <p data-testid="provenance-coverage" className="mt-1">
        {coverageSentence(coverage ?? null)}
      </p>

      {warningLines.length > 0 && (
        <ul data-testid="provenance-warnings" className="mt-2 list-disc space-y-1 pl-4">
          {warningLines.map((line, index) => (
            <li key={`${index}-${line}`}>{line}</li>
          ))}
        </ul>
      )}
    </section>
  );
};

export default SectionProvenance;
