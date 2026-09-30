'use client';

/**
 * MarginalImpactPanel — "what would this trade do to my book?"
 *
 * This is the instrument that closes the gap between a screener row and a
 * decision. The screener finds candidates; every other analytics route
 * describes the portfolio as it IS. `POST /analytics/marginal-trade-impact` is
 * the one route that takes a hypothetical and publishes the DELTA it would
 * make. This component is its renderer, and it is built to hold four rules that
 * a fabricated number would each break.
 *
 * 1. THE DELTA IS THE ANSWER. "HHI 0.58 → 0.41" is a decision; "HHI 0.41" is
 *    a fact about a book the reader does not hold. The delta is rendered as the
 *    dominant cell of its row, and the levels beside it as context. Nothing
 *    here promotes an `after` to a headline.
 *
 * 2. A REFUSAL IS A FIRST-CLASS ANSWER. The endpoint publishes a `state` on
 *    every block and on every figure. A block that is `unmeasurable` or
 *    `not_attempted` renders its reason, names the floor, and renders NO metric
 *    table at all — not a table of zeros, and not a spinner that resolves to
 *    one. A screen full of "cannot assess" is a correct product; smoothing that
 *    over would be the bug. This is the same posture the backend takes in
 *    `analytics.py:12935-12938`.
 *
 * 3. NEVER RENDER A NULL AS A NUMBER. Every figure goes through the shared
 *    formatters in `@/lib/utils`, which own the absent-value guard (pinned by
 *    `test/unit/format-invariants.test.tsx`, which sweeps the module namespace).
 *    There is no `?? 0` and no falsy-guard here: a falsy-guard would pass the
 *    null test and silently turn a MEASURED 0 into `N/A`, which is the same
 *    fabrication in the opposite direction.
 *
 * 4. NO FABRICATED PROVENANCE. The proposed weight is an instruction from the
 *    reader, not an observation, and the panel says so in both the pre-filled
 *    and the reader-set case. It also states which funding rule it applied,
 *    because "buy X at 5%" does not say where the 5% comes from and silently
 *    picking a rule is exactly the rescaling the reader did not ask for.
 *
 * Deliberately NOT coloured good/bad. A rise in VaR is a loss and a rise in
 * diversification is a gain, so a red/green delta would encode a judgement the
 * endpoint never makes. The direction is shown by the sign the backend computed.
 *
 * Reusable by construction: it takes a ticker and a target weight and owns no
 * page state. The screener studio mounts it per row; the optimize and portfolio
 * pages can mount it for any proposed leg without changing anything here.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, RefreshCw, Scale, ShieldAlert, X } from 'lucide-react';
import { analyticsApi } from '@/lib/api';
import type {
  MarginalBlock,
  MarginalFundingRule,
  MarginalStatistic,
  MarginalTradeImpactResponse,
} from '@/lib/api';
import { formatLargeNumber, formatPercentage } from '@/lib/utils';

export interface MarginalImpactPanelProps {
  /**
   * The ticker being assessed, already exchange-suffixed (`TCS.NS`, `500112.BO`).
   *
   * Pass the field the caller actually holds suffixed — a screener row's
   * `ticker`, not its bare `symbol`. `screener_service._screen_ticker` stamps
   * the suffix on the way out and `ProposedLegRequest.normalize_ticker` only
   * uppercases and trims, so an unsuffixed symbol reaches the analytics layer
   * as a ticker that does not resolve.
   */
  ticker: string;
  /** Pre-filled target weight as a FRACTION of 1 (0.05 = 5%). */
  defaultTargetWeight?: number;
  /** Which funding rule to send. Stated on screen once the answer arrives. */
  funding?: MarginalFundingRule;
  /** Days of history the risk half measures over. */
  historyDays?: number;
  /** Show the weight input. Default true; pass false for a read-only reading. */
  editableWeight?: boolean;
  /** Subject line for the heading, e.g. "Screened candidate". */
  subject?: string;
  onClose?: () => void;
}

/**
 * Human labels for the metrics the endpoint publishes. A key with no entry
 * falls back to the raw key: an unlabelled row still names itself rather than
 * rendering blank, which would be indistinguishable from an absent row.
 */
const METRIC_LABELS: Record<string, string> = {
  herfindahl_index: 'Herfindahl index (HHI)',
  effective_positions: 'Effective positions',
  top_3: 'Top 3 weight',
  diversification_score: 'Diversification score',
  annual_volatility: 'Annual volatility',
  var_95: 'VaR 95%',
  cvar_95: 'CVaR 95%',
  sharpe_ratio: 'Sharpe ratio',
};

/** Render order, so the concentration and risk halves read the same way. */
const METRIC_ORDER = [
  'herfindahl_index',
  'effective_positions',
  'top_3',
  'diversification_score',
  'annual_volatility',
  'var_95',
  'cvar_95',
  'sharpe_ratio',
];

/**
 * The formatter is chosen from the endpoint's OWN `units` string, not from a
 * parallel table here: any figure the backend labels `*_fraction_*` renders as
 * a percentage and everything else as a decimal index. A new metric therefore
 * formats correctly the day the backend publishes it, with no edit on this side
 * to forget. Both branches are existing shared formatters, so neither invents
 * an absent-value path.
 */
const formatterFor = (units?: string) =>
  typeof units === 'string' && units.includes('fraction') ? formatPercentage : formatLargeNumber;

/** Absent is a real state here and is never coerced to a number. */
const isAbsent = (value: unknown): boolean =>
  value === null || value === undefined || Number.isNaN(value as number);

const STATE_LABEL: Record<string, string> = {
  measured: 'Measured',
  unmeasurable: 'Not measurable',
  not_attempted: 'Not attempted',
};

/** Metric keys in the order the reader should see them, extras appended sorted. */
const orderedKeys = (metrics: Record<string, MarginalStatistic>): string[] => {
  const present = Object.keys(metrics);
  return [
    ...METRIC_ORDER.filter((key) => present.includes(key)),
    ...present.filter((key) => !METRIC_ORDER.includes(key)).sort(),
  ];
};

// ---------------------------------------------------------------------------
// One block of figures, or its refusal. Never both.
// ---------------------------------------------------------------------------

const DeltaBlock: React.FC<{
  block: MarginalBlock;
  blockName: string;
  title: string;
  subtitle: string;
  sharedSessions?: number | null;
  minimumSharedSessions?: number | null;
}> = ({ block, blockName, title, subtitle, sharedSessions, minimumSharedSessions }) => {
  // A refused block publishes no measured table. Rendering one anyway would be
  // the failure this component exists to prevent.
  if (block.state !== 'measured') {
    return (
      <div
        data-testid={`marginal-refusal-${blockName}`}
        data-state={block.state}
        data-role="refusal"
        className="rounded-lg border border-amber-700/50 bg-amber-950/20 p-3 space-y-1"
      >
        <p className="text-xs font-bold text-amber-300 flex items-center gap-1.5">
          <ShieldAlert className="w-3.5 h-3.5" />
          {title}: {STATE_LABEL[block.state] ?? block.state}
        </p>
        <p className="text-[11px] text-amber-200/90 leading-relaxed">
          {block.reason ?? 'No reason published for this refusal.'}
        </p>
        <p className="text-[11px] text-amber-200/70">
          No {title.toLowerCase()} delta is published, because none was measured. An absent
          change is not a change of zero.
        </p>
        {sharedSessions !== undefined && (
          <p className="text-[11px] text-amber-200/70">
            Shared sessions: {formatLargeNumber(sharedSessions)}
            {minimumSharedSessions !== undefined && minimumSharedSessions !== null
              ? ` against a floor of ${formatLargeNumber(minimumSharedSessions)}`
              : ''}
          </p>
        )}
      </div>
    );
  }

  const keys = orderedKeys(block.metrics);

  return (
    <section className="space-y-2" data-testid={`marginal-block-${blockName}`} data-state={block.state}>
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h4 className="text-xs font-bold text-white">{title}</h4>
        <p className="text-[11px] text-slate-400">{subtitle}</p>
      </div>

      <table data-testid={`marginal-metrics-${blockName}`} className="w-full text-[11px]">
        <thead>
          <tr className="text-slate-500 uppercase font-mono text-[10px]">
            <th className="text-left py-1 font-normal">Figure</th>
            <th className="text-right py-1 font-normal">Before → after</th>
            <th className="text-right py-1 font-normal">Change</th>
            <th className="text-left py-1 pl-3 font-normal">State</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {keys.map((key) => {
            const entry = block.metrics[key];
            const fmt = formatterFor(entry.units);
            return (
              <tr key={key} data-state={entry.state}>
                <td className="py-1.5 pr-2 text-slate-300">
                  {METRIC_LABELS[key] ?? key}
                  {entry.units ? (
                    <span className="block text-[10px] text-slate-500 font-mono">{entry.units}</span>
                  ) : null}
                </td>
                {/* Levels: present, and visibly context. Not the headline. */}
                <td
                  data-testid={`marginal-levels-${key}`}
                  data-role="level"
                  className="py-1.5 px-2 text-right font-mono text-slate-400 whitespace-nowrap"
                >
                  <span data-role="level-before">{fmt(entry.before)}</span>
                  <span aria-hidden="true" className="mx-1 text-slate-600">→</span>
                  <span data-role="level-after">{fmt(entry.after)}</span>
                </td>
                {/* The delta: dominant, bold, and separate from the levels. */}
                <td
                  data-testid={`marginal-delta-${key}`}
                  data-role="delta"
                  className="py-1.5 px-2 text-right font-mono text-sm font-bold text-cyan-200 whitespace-nowrap"
                >
                  {isAbsent(entry.delta) ? 'N/A' : <>Δ {fmt(entry.delta)}</>}
                </td>
                <td
                  data-testid={`marginal-state-${key}`}
                  data-role="state"
                  className="py-1.5 pl-3 text-slate-400"
                >
                  {entry.state === 'measured' ? (
                    <>
                      <span className="text-emerald-400">measured</span>
                      {isAbsent(entry.observations) ? null : (
                        <span className="text-slate-500"> · n={formatLargeNumber(entry.observations)}</span>
                      )}
                    </>
                  ) : (
                    <>
                      <span className="text-amber-400">
                        {STATE_LABEL[entry.state] ?? entry.state}
                      </span>
                      {entry.reason ? (
                        <span className="block text-slate-500 leading-snug">{entry.reason}</span>
                      ) : null}
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
};

// ---------------------------------------------------------------------------

export const MarginalImpactPanel: React.FC<MarginalImpactPanelProps> = ({
  ticker,
  defaultTargetWeight,
  funding = 'sell_and_rebalance',
  historyDays = 365,
  editableWeight = true,
  subject = 'Candidate',
  onClose,
}) => {
  // The input is edited in percent (what a person reads) and SENT as a
  // fraction (what the endpoint accepts: `target_weight` is `ge=0.0, le=1.0`).
  const [weightPct, setWeightPct] = useState<string>(() => {
    if (isAbsent(defaultTargetWeight)) return '';
    return String(Number((Number(defaultTargetWeight) * 100).toFixed(4)));
  });
  const [weightTouched, setWeightTouched] = useState(false);

  // Every answer is stored WITH the question that produced it, and is only
  // rendered when the two still match. A stale reading can therefore never sit
  // on screen answering a question the reader has since changed, and clearing
  // it needs no state write inside the effect.
  const [result, setResult] = useState<{
    key: string;
    data: MarginalTradeImpactResponse;
  } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);

  const targetFraction = Number(weightPct) / 100;
  const weightValid =
    weightPct.trim() !== '' &&
    Number.isFinite(targetFraction) &&
    targetFraction >= 0 &&
    targetFraction <= 1;

  const requestKey = `${ticker}::${weightPct}::${funding}::${historyDays}`;

  useEffect(() => {
    const fraction = Number(weightPct) / 100;
    // An out-of-range weight is not sent, and nothing is rendered for it. The
    // endpoint accepts a fraction of 1 between 0.0 and 1.0; guessing a clamp
    // would answer a question nobody asked.
    if (
      weightPct.trim() === '' ||
      !Number.isFinite(fraction) ||
      fraction < 0 ||
      fraction > 1
    ) {
      return;
    }

    let cancelled = false;

    analyticsApi
      .getMarginalTradeImpact({
        legs: [{ ticker, target_weight: fraction }],
        funding,
        history_days: historyDays,
      })
      .then((response) => {
        if (cancelled) return;
        setResult({ key: `${ticker}::${weightPct}::${funding}::${historyDays}`, data: response });
        setFailure(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setResult(null);
        setFailure({
          key: `${ticker}::${weightPct}::${funding}::${historyDays}`,
          message:
            err instanceof Error && err.message
              ? err.message
              : 'The assessment could not be completed.',
        });
      });

    return () => {
      cancelled = true;
    };
  }, [ticker, weightPct, funding, historyDays]);

  // Derived, not stored: what is on screen is a function of what was asked and
  // what came back, so a stale answer cannot masquerade as a fresh one.
  const data = weightValid && result?.key === requestKey ? result.data : null;
  const loadError = weightValid && failure?.key === requestKey ? failure.message : null;
  const loading = weightValid && !data && !loadError;

  const fundingRuleKey =
    data?.disclosure?.weight_derivation?.funding ?? funding;
  const fundingRuleText = data?.funding_rule ?? data?.disclosure?.funding_rule ?? null;

  const cashWeight = data ? data.cash_weight : null;
  const fundingResidual = data ? data.funding_residual : null;

  const shortHistoryLegs = useMemo(
    () => data?.risk?.tickers_below_minimum_sample ?? [],
    [data]
  );

  return (
    <section
      data-testid="marginal-impact-panel"
      aria-label={`Marginal impact for ${ticker}`}
      className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4 shadow-lg"
    >
      {/* Header. Rendered before any answer exists, so the reader can see WHAT
          is being assessed while it is still in flight. */}
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Scale className="w-4 h-4 text-cyan-400" />
            {subject}
            <span
              data-testid="marginal-subject-ticker"
              className="px-1.5 py-0.5 bg-slate-950 text-cyan-300 border border-cyan-800 rounded font-mono text-xs"
            >
              {ticker}
            </span>
          </h3>
          <p className="text-[11px] text-slate-400">
            What this trade does to your book — before, after, and the change between them.
          </p>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close impact panel"
            className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        ) : null}
      </div>

      {/* The weight. Asked visibly, and its provenance stated either way. */}
      <div className="flex flex-wrap items-end gap-4">
        {editableWeight ? (
          <div>
            <label htmlFor="marginal-target-weight" className="block text-[11px] text-slate-300 font-semibold mb-1">
              Target weight (% of book after the trade)
            </label>
            <input
              id="marginal-target-weight"
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={weightPct}
              onChange={(e) => {
                setWeightTouched(true);
                setWeightPct(e.target.value);
              }}
              className="w-28 bg-slate-950 border border-slate-700 text-white px-2.5 py-1.5 rounded-lg text-xs font-mono focus:outline-none focus:border-cyan-500"
            />
          </div>
        ) : null}

        {/* Rule 4: never let a typed weight read as a measurement. */}
        <p data-testid="marginal-weight-origin" className="text-[11px] text-amber-300/90 leading-relaxed max-w-md">
          {weightTouched ? (
            <>
              You set this weight. It is user-supplied and not measured — it was not
              observed on any price feed, and every figure below inherits that provenance.
            </>
          ) : (
            <>
              Pre-filled by this panel. The weight is user-supplied and not measured — it
              was not observed on any price feed, and every figure below inherits that
              provenance.
            </>
          )}
        </p>
      </div>

      {!weightValid ? (
        <p data-testid="marginal-weight-error" className="text-[11px] text-amber-300">
          Target weight must be between 0 and 100. The endpoint accepts a fraction of 1
          between 0.0 and 1.0, and nothing has been sent.
        </p>
      ) : null}

      {loading ? (
        <div
          data-testid="marginal-loading"
          className="flex items-center gap-2 text-[11px] text-slate-400 py-6 justify-center"
        >
          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          Assessing — measuring before and after over the same sessions. No figure is
          published until both sides exist.
        </div>
      ) : loadError ? (
        <p
          data-testid="marginal-error"
          className="text-xs text-red-300 bg-red-950/40 border border-red-800 rounded-lg p-3 flex items-center gap-2"
        >
          <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
          {loadError}
        </p>
      ) : null}

      {data && !loading && !loadError ? (
        data.error ? (
          // The route refused outright: no book, or nothing fundable. Both halves
          // are `not_attempted` with empty metrics, so nothing is rendered as a
          // number anywhere below this point.
          <div
            data-testid="marginal-refusal"
            data-state="not_attempted"
            data-role="refusal"
            className="rounded-lg border border-amber-700/50 bg-amber-950/20 p-3 space-y-1"
          >
            <p className="text-xs font-bold text-amber-300 flex items-center gap-1.5">
              <ShieldAlert className="w-3.5 h-3.5" />
              No impact assessment was attempted
            </p>
            <p className="text-[11px] text-amber-200/90 leading-relaxed">{data.error}</p>
            <p className="text-[11px] text-amber-200/70">
              No figure is shown because none was measured. This is a refusal, not a change
              of zero.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Which rule funded the proposal. Stated, never implied — "buy X at
                5%" does not say where the 5% comes from. */}
            <div
              data-testid="marginal-funding-rule"
              className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-1"
            >
              <p className="text-[11px] text-slate-300">
                <span className="font-semibold text-white">Funding rule applied:</span>{' '}
                <code className="font-mono text-cyan-300">{fundingRuleKey}</code>
              </p>
              {fundingRuleText ? (
                <p className="text-[11px] text-slate-400 leading-relaxed">{fundingRuleText}</p>
              ) : null}
              <p className="text-[11px] text-slate-400">
                Cash held after the trade:{' '}
                <span data-testid="marginal-cash-weight" className="font-mono text-slate-200">
                  {formatPercentage(cashWeight)}
                </span>
                {' · residual vs a closed book: '}
                <span className="font-mono text-slate-200">{formatPercentage(fundingResidual)}</span>
              </p>
            </div>

            <p
              data-testid="marginal-proposal-provenance"
              className="text-[11px] text-amber-300/90 leading-relaxed"
            >
              {data.proposal_provenance}
            </p>

            <DeltaBlock
              block={data.concentration}
              blockName="concentration"
              title="Concentration"
              subtitle="Arithmetic on the weights alone — no price history is read."
            />

            <DeltaBlock
              block={data.risk}
              blockName="risk"
              title="Risk"
              subtitle="Both books over the same shared sessions, so this is a delta and not two samples."
              sharedSessions={data.risk.shared_sessions}
              minimumSharedSessions={data.risk.minimum_shared_sessions_required}
            />

            {shortHistoryLegs.length > 0 ? (
              <p
                data-testid="marginal-short-history"
                className="text-[11px] text-amber-300/90"
              >
                Below the per-leg minimum sample: {shortHistoryLegs.join(', ')}. These are
                named rather than averaged into a book-level number.
              </p>
            ) : null}
          </div>
        )
      ) : null}

      {/* Per-leg contribution, when the concentration half measured the book. */}
      {data && !loading && !loadError && !data.error && data.concentration.state === 'measured' ? (
        <details className="text-[11px]">
          <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
            Per-leg weight share and what the proposal did to it
          </summary>
          <ul className="mt-2 space-y-1">
            {Object.entries(data.concentration.by_leg).map(([legTicker, entry]) => {
              const fmt = formatterFor(entry.contribution_units);
              return (
                <li key={legTicker} className="flex items-center justify-between gap-3">
                  <span className="font-mono text-slate-300">
                    {legTicker}
                    <span
                      className={`ml-2 px-1 py-0.5 rounded text-[10px] ${
                        entry.weight_provenance === 'proposed'
                          ? 'bg-amber-950 text-amber-300 border border-amber-800'
                          : 'bg-slate-800 text-slate-400 border border-slate-700'
                      }`}
                    >
                      {entry.weight_provenance ?? 'unlabelled'}
                    </span>
                  </span>
                  <span className="font-mono text-slate-400">
                    <span data-role="level">{fmt(entry.before)}</span>
                    <span aria-hidden="true" className="mx-1 text-slate-600">→</span>
                    <span data-role="level">{fmt(entry.after)}</span>
                    <span className="mx-2 font-bold text-cyan-200">
                      {isAbsent(entry.delta) ? 'N/A' : `Δ ${fmt(entry.delta)}`}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </details>
      ) : null}

      {data && !loading && !loadError && !data.error ? (
        <p className="text-[10px] text-slate-500 leading-relaxed">
          Data status: {data.data_status}. Nothing on this panel was written to your
          portfolio — a proposed position is not a holding.
        </p>
      ) : null}
    </section>
  );
};

export default MarginalImpactPanel;
