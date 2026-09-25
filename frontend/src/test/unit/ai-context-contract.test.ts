// Contract fixtures for the AI context export (docs/ai-context.md).
//
// The `satisfies` annotations and the `@ts-expect-error` guards are the real
// assertions here: `tsc --noEmit` fails if the documented vocabularies, the
// conditional `weight_basis`, or the error-omission rule drift. The runtime
// assertions guard the invariants a JS consumer must not break.
import { describe, expect, it } from 'vitest';
import type {
  AIDataStatus,
  AIContextCoverage,
  AIContextCoverageStatus,
  AIContextResponse,
  AIContextSection,
  AIContextStatus,
  AIContextWeightBasis,
  IndiaFlowsResponse,
} from '@/types';

const COVERAGE_STATUSES: readonly AIContextCoverageStatus[] = [
  'complete',
  'partial',
  'unavailable',
  'unknown',
];
const DATA_STATUSES: readonly AIDataStatus[] = ['available', 'partial', 'unavailable'];
const SECTION_STATUSES: readonly AIContextStatus[] = [
  'available',
  'partial',
  'unavailable',
];
const WEIGHT_BASES: readonly AIContextWeightBasis[] = [
  'active_weights_renormalized_to_100_percent',
];

// Complete coverage: every requested ticker reached the result, nothing dropped.
const completeCoverage = {
  requested_tickers: ['RELIANCE.NS', 'TCS.NS', 'INFY.NS'],
  available_tickers: ['RELIANCE.NS', 'TCS.NS', 'INFY.NS'],
  covered_tickers: ['RELIANCE.NS', 'TCS.NS', 'INFY.NS'],
  missing_tickers: [],
  requested_count: 3,
  available_count: 3,
  coverage_ratio: 1,
  complete: true,
  status: 'complete',
} satisfies AIContextCoverage;

// Partial coverage: one leg was unmeasurable. `available_tickers` is sorted
// (the exporter unions result maps) while requested/covered/missing keep the
// stable request order — consumers must derive ordering from requested_tickers.
const partialCoverage = {
  requested_tickers: ['RELIANCE.NS', 'TCS.NS', 'INFY.NS'],
  available_tickers: ['INFY.NS', 'RELIANCE.NS', 'TCS.NS'],
  raw_available_tickers: ['INFY.NS', 'RELIANCE.NS', 'TCS.NS'],
  covered_tickers: ['RELIANCE.NS', 'TCS.NS'],
  missing_tickers: ['INFY.NS'],
  requested_count: 3,
  available_count: 2,
  coverage_ratio: 0.666667,
  complete: false,
  status: 'partial',
} satisfies AIContextCoverage;

// Unavailable coverage: the requested universe produced nothing measurable.
const unavailableCoverage = {
  requested_tickers: ['RELIANCE.NS', 'TCS.NS'],
  available_tickers: [],
  covered_tickers: [],
  missing_tickers: ['RELIANCE.NS', 'TCS.NS'],
  requested_count: 2,
  available_count: 0,
  coverage_ratio: 0,
  complete: false,
  status: 'unavailable',
} satisfies AIContextCoverage;

// Unknown coverage: the endpoint does not report a result universe. Count
// fields are omitted, `complete` is null, and — crucially — no `weight_basis`
// is claimed, because nothing was renormalized.
const unknownCoverage = {
  requested_tickers: ['RELIANCE.NS'],
  available_tickers: null,
  missing_tickers: null,
  coverage_ratio: null,
  complete: null,
  status: 'unknown',
} satisfies AIContextCoverage;

// Renormalized active weights: emitted only when an active leg was dropped.
const renormalizedCoverage = {
  requested_tickers: ['RELIANCE.NS', 'TCS.NS'],
  available_tickers: ['RELIANCE.NS'],
  covered_tickers: ['RELIANCE.NS'],
  missing_tickers: ['TCS.NS'],
  requested_count: 2,
  available_count: 1,
  coverage_ratio: 0.5,
  complete: false,
  status: 'partial',
  weight_basis: 'active_weights_renormalized_to_100_percent',
} satisfies AIContextCoverage;

const baseSection = {
  key: 'concentration',
  title: 'Concentration',
  route: '/dashboard/concentration',
  status: 'available',
  detail: 'summary',
  generated_at: '2026-09-25T12:00:05Z',
  as_of: null,
  currency: null,
  inputs: { tickers: ['RELIANCE.NS', 'TCS.NS', 'INFY.NS'] },
  coverage: completeCoverage,
  data: { herfindahl_index: 0.41 },
  omitted_fields: [],
  warnings: [],
} satisfies AIContextSection;

const response = {
  schema_version: '1.1',
  export_id: 'portfolio-abc123',
  generated_at: '2026-09-25T12:00:00Z',
  completed_at: '2026-09-25T12:00:11Z',
  snapshot_consistency: 'best_effort',
  base_currency: 'INR',
  currency_policy:
    'Portfolio section uses the requested base_currency; analytics sections retain their endpoint-declared monetary units.',
  detail: 'summary',
  scope: ['concentration', 'liquidity', 'optimizer', 'pairs', 'india_flows'],
  environment: { primary_source: 'bfinance' },
  sections: {
    // Success: no `error` key at all, and no `weight_basis` claim.
    concentration: baseSection,
    // Partial with a dropped leg: warns, and renormalized weights are declared.
    liquidity: {
      ...baseSection,
      key: 'liquidity',
      title: 'Liquidity',
      route: '/dashboard/liquidity',
      status: 'partial',
      as_of: '2026-09-25T11:58:00Z',
      currency: 'INR',
      coverage: renormalizedCoverage,
      data: { overall_score: 62, by_position: { 'RELIANCE.NS': { score: 62 } } },
      warnings: ['Result coverage is missing requested ticker(s): TCS.NS'],
    } satisfies AIContextSection,
    // Failure: `error` is a non-empty string and data is null.
    optimizer: {
      ...baseSection,
      key: 'optimization',
      title: 'Optimizer',
      route: '/dashboard/optimize',
      status: 'unavailable',
      coverage: unavailableCoverage,
      data: null,
      warnings: ['Solver returned no feasible portfolio'],
      error: 'Solver returned no feasible portfolio',
    } satisfies AIContextSection,
    // Weightless analysis (pair scan): coverage measured, no allocation basis.
    pairs: {
      ...baseSection,
      key: 'pairs',
      title: 'Pairs Scanner',
      route: '/dashboard/pairs',
      coverage: partialCoverage,
      data: { pairs: [], data_status: 'unavailable' },
      warnings: ['Insufficient overlapping history for 1 requested ticker(s)'],
    } satisfies AIContextSection,
    // Component payload: normalized data_status, categories split by leg.
    india_flows: {
      ...baseSection,
      key: 'india_flows',
      title: 'India Market Microstructure',
      route: '/dashboard/india-flows',
      coverage: null,
      data: {
        data_status: 'partial',
        available_categories: ['delivery_spikes', 'adv_liquidity'],
        missing_categories: ['institutional_flows'],
        institutional_flows: { fii_net_cr: null, dii_net_cr: null, date: '2026-09-24' },
      },
    } satisfies AIContextSection,
  },
  warnings: [],
} satisfies AIContextResponse;

// `satisfies` keeps the fixtures narrow (which is what proves no field is
// silently required), so widen them here to read the documented optional keys.
const envelope: AIContextResponse = response;
const concentration: AIContextSection = envelope.sections.concentration;
const complete: AIContextCoverage = completeCoverage;
const partial: AIContextCoverage = partialCoverage;
const unknown: AIContextCoverage = unknownCoverage;

describe('AI context export contract', () => {
  it('pins the three independent status vocabularies', () => {
    expect(COVERAGE_STATUSES).toEqual(['complete', 'partial', 'unavailable', 'unknown']);
    expect(DATA_STATUSES).toEqual(['available', 'partial', 'unavailable']);
    expect(SECTION_STATUSES).toEqual(['available', 'partial', 'unavailable']);
  });

  it('keeps coverage status distinct from the public data_status vocabulary', () => {
    // `partial` is legitimately shared; the axes diverge on the rest.
    // Coverage-only: complete / unknown. data_status-only: available.
    const shared: AIContextCoverageStatus & AIDataStatus = 'partial';
    const coverageOnly: AIContextCoverageStatus = 'complete';
    const dataStatusOnly: AIDataStatus = 'available';

    expect(COVERAGE_STATUSES).toContain(shared);
    expect(DATA_STATUSES).toContain(shared);
    expect(COVERAGE_STATUSES).toContain(coverageOnly);
    expect(DATA_STATUSES).not.toContain(coverageOnly);
    expect(DATA_STATUSES).toContain(dataStatusOnly);
    expect(COVERAGE_STATUSES).not.toContain(dataStatusOnly);
  });

  it('omits the error key on successful sections instead of nulling it', () => {
    const failure = envelope.sections.optimizer;

    expect('error' in concentration).toBe(false);
    expect(concentration.error).toBeUndefined();
    expect(concentration.status).toBe('available');
    expect(concentration.warnings).toEqual([]);

    expect(failure.error).toBe('Solver returned no feasible portfolio');
    expect(failure.status).toBe('unavailable');
    expect(failure.data).toBeNull();
  });

  it('declares weight_basis only when an active leg was actually dropped', () => {
    expect(WEIGHT_BASES).toEqual(['active_weights_renormalized_to_100_percent']);

    const renormalized = envelope.sections.liquidity.coverage!;
    expect(renormalized.weight_basis).toBe('active_weights_renormalized_to_100_percent');
    expect(renormalized.missing_tickers).toEqual(['TCS.NS']);
    expect(renormalized.status).toBe('partial');

    // Weightless / unrenormalized sections must not claim an allocation basis.
    for (const key of ['concentration', 'pairs', 'optimizer'] as const) {
      const coverage = envelope.sections[key].coverage!;
      expect('weight_basis' in coverage).toBe(false);
      expect(coverage.weight_basis).toBeUndefined();
    }
  });

  it('keeps ticker ordering deterministic and request-ordered', () => {
    const requested = ['RELIANCE.NS', 'TCS.NS', 'INFY.NS'];

    // Repeated exports of the same universe keep the same request order.
    expect(complete.requested_tickers).toEqual(requested);
    expect(concentration.inputs.tickers).toEqual(requested);

    // covered/missing derive from requested order, not from the sorted
    // available_tickers the exporter emitted for union-style sections.
    expect(partial.available_tickers).toEqual([...partial.available_tickers!].sort());
    expect(partial.available_tickers).not.toEqual(partial.requested_tickers);
    expect(partial.covered_tickers).toEqual(['RELIANCE.NS', 'TCS.NS']);
    expect(partial.missing_tickers).toEqual(['INFY.NS']);
    expect(partial.raw_available_tickers).toEqual(partial.available_tickers);

    // Unmeasured coverage is null, not an empty list and not false.
    expect(unknown.available_tickers).toBeNull();
    expect(unknown.missing_tickers).toBeNull();
    expect(unknown.complete).toBeNull();
    expect(unknown.coverage_ratio).toBeNull();
    expect(unknown.requested_count).toBeUndefined();
    expect(unknown.available_count).toBeUndefined();
    expect(unknown.covered_tickers).toBeUndefined();
  });

  it('never inherits the envelope base_currency as a section unit', () => {
    // Nothing declared a unit -> null (unknown unit), even though the envelope
    // is INR. Never a silent INR assumption.
    expect(envelope.base_currency).toBe('INR');
    expect(concentration.currency).toBeNull();

    // Declared units are explicit and uppercase.
    expect(envelope.sections.liquidity.currency).toBe('INR');
  });

  it('separates collection time from observation freshness', () => {
    // as_of null means unknown freshness, not "fresh".
    expect(concentration.as_of).toBeNull();
    expect(concentration.generated_at).toBe('2026-09-25T12:00:05Z');
    expect(envelope.generated_at).toBe('2026-09-25T12:00:00Z');
    expect(envelope.sections.liquidity.as_of).toBe('2026-09-25T11:58:00Z');
  });

  it('never folds an unmeasured institutional leg into a measured zero', () => {
    const flows = envelope.sections.india_flows.data as IndiaFlowsResponse;

    expect(flows.data_status).toBe('partial');
    expect(flows.available_categories).toEqual(['delivery_spikes', 'adv_liquidity']);
    expect(flows.missing_categories).toEqual(['institutional_flows']);
    expect(flows.institutional_flows.fii_net_cr).toBeNull();
    expect(flows.institutional_flows.dii_net_cr).toBeNull();
    // No ticker universe -> coverage is null, not a fabricated empty universe.
    expect(envelope.sections.india_flows.coverage).toBeNull();
  });

  it('orders sections by the resolved request order', () => {
    expect(Object.keys(envelope.sections)).toEqual(envelope.scope);
  });
});

// Compile-time guards: `tsc --noEmit` fails if the contract drifts.
describe('AI context export contract — compile-time guards', () => {
  it('rejects statuses outside the documented vocabularies', () => {
    // @ts-expect-error `complete` is a coverage status, never a section status.
    const badSectionStatus: AIContextStatus = 'complete';
    // @ts-expect-error `unknown` is coverage, never a public data_status.
    const badDataStatus: AIDataStatus = 'unknown';
    // @ts-expect-error `available` is a section status, never a coverage status.
    const badCoverageStatus: AIContextCoverageStatus = 'available';
    // @ts-expect-error weight_basis is a single literal, not free text.
    const badWeightBasis: AIContextWeightBasis = 'renormalized';

    void badSectionStatus;
    void badDataStatus;
    void badCoverageStatus;
    void badWeightBasis;
  });

  it('rejects a null error sentinel on a section', () => {
    // @ts-expect-error success omits `error`; publishing null is not the contract.
    const nullError: AIContextSection['error'] = null;
    void nullError;
  });
});
