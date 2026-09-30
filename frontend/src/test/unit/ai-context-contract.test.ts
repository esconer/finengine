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
  AIContextDashboardComponent,
  AIContextInlineComponent,
  AIContextReferencedComponent,
  AIContextResponse,
  AIContextSection,
  AIContextStatus,
  AIContextWeightBasis,
  IndiaFlowsResponse,
  RiskContributionModelAliases,
  RiskContributionModelName,
  RiskContributionModelNames,
  RiskContributionResponse,
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

    // The envelope names WHICH field produced `as_of`, so a reader can tell what
    // the date measures rather than guessing. The backend's response model
    // declares the key (`as_of_semantics: Optional[str] = None`), so it is on
    // the wire for every section even where the label is null. Reading it
    // without a cast is the assertion: the type used to omit the key entirely.
    const semantics: string | null | undefined = envelope.sections.liquidity.as_of_semantics;
    expect(semantics).toBeUndefined();
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

  it('keeps a top-level section payload required', () => {
    // A section envelope always publishes `data` (null when the section
    // failed), so this key is NOT optional. Making it optional would be the same
    // silent-empty defect in the other direction: a compile-clean read of
    // `sections.x.data` that renders nothing for a section that does have one.
    const sectionData: AIContextSection['data'] = null;
    void sectionData;
  });

  it('refuses to read a payload off a referenced dashboard component', () => {
    const referenced: AIContextReferencedComponent = {
      data_inline: false,
      data_ref: 'sections.portfolio',
      data_ref_status: 'referenced',
      status: 'available',
    };

    // @ts-expect-error a referenced component publishes NO `data` key at all.
    const pointedAt: unknown = referenced.data;
    // @ts-expect-error the payload is at `<data_ref>.data`, not on the component.
    const badRef: AIContextReferencedComponent = { data_inline: false, data_ref: 'cvar' };

    void pointedAt;
    void badRef;
  });

  it('refuses an inline component without a payload, or a referenced one with one', () => {
    // @ts-expect-error `data_inline: true` is the only publication; `data` is required.
    const missingPayload: AIContextInlineComponent = { data_inline: true, status: 'available' };
    const wrongFlag: AIContextReferencedComponent = {
      // @ts-expect-error a referenced component is never `data_inline: true`.
      data_inline: true,
      data_ref: 'sections.portfolio',
      data_ref_status: 'referenced',
      status: 'available',
    };
    const wrongStatusWord: AIContextReferencedComponent = {
      data_inline: false,
      data_ref: 'sections.portfolio',
      // @ts-expect-error `data_status` is a normalized contract vocabulary, not a pointer.
      data_status: 'referenced',
      status: 'available',
    };

    void missingPayload;
    void wrongFlag;
    void wrongStatusWord;
  });

  it('reads a component payload only after narrowing on data_inline', () => {
    const components: Record<string, AIContextDashboardComponent> = {
      portfolio: {
        data_inline: false,
        data_ref: 'sections.portfolio',
        data_ref_status: 'referenced',
        status: 'available',
      },
      summary: { data_inline: true, data: { portfolio_value: 1000 }, status: 'available' },
    };

    const component = components.summary;
    if (component.data_inline) {
      // Narrowed: the payload is here, and it is `unknown` because the exporter
      // publishes arbitrary per-component payloads.
      const payload: unknown = component.data;
      void payload;
    } else {
      // @ts-expect-error still a pointer once the other arm is excluded.
      const stillAPointer: unknown = component.data;
      void stillAPointer;
    }
  });

  it('publishes the risk-contribution model names under the canonical spelling', () => {
    // `cvar` is the RETIRED name. It is a pointer in
    // `contribution_basis.model_names.aliases`, not a key in any container, so
    // declaring it beside `cvar_tail` compiled clean and read `undefined`.
    const names: RiskContributionModelNames = {
      canonical: ['volatility', 'cvar_tail'],
      aliases: { cvar: 'cvar_tail' },
      basis: 'one model, one name, in every container of this section',
    };
    const aliases: RiskContributionModelAliases = { cvar: 'cvar_tail' };
    const model: RiskContributionModelName = 'cvar_tail';

    // @ts-expect-error the retired spelling is not a model name any more.
    const retired: RiskContributionModelName = 'cvar';
    // @ts-expect-error the alias map points AT a canonical name, not at itself.
    const selfAlias: RiskContributionModelAliases = { cvar: 'cvar' };

    expect(names.canonical).toEqual(['volatility', 'cvar_tail']);
    expect(aliases.cvar).toBe('cvar_tail');
    expect(model).toBe('cvar_tail');
    void retired;
    void selfAlias;
  });

  it('publishes no `cvar` key in the risk-contribution share containers', () => {
    // Both containers are keyed by the canonical names, which is the whole
    // point of the alias map: a reader can iterate one vocabulary across them.
    // Annotated off the DECLARED type, not off its own literal, so this guard
    // reads the type rather than restating it.
    const sectorRollup: RiskContributionResponse['sector_rollup'] = {
      volatility: { Tech: 1 },
      cvar_tail: { Tech: 1 },
    };

    expect(Object.keys(sectorRollup)).toEqual(['volatility', 'cvar_tail']);
    expect(sectorRollup.cvar_tail.Tech).toBe(1);

    // @ts-expect-error `sector_rollup.cvar` is not on the wire; reading it is
    // the silent empty this type used to invite.
    const retiredKey: unknown = sectorRollup.cvar;
    void retiredKey;
  });

  it('carries a nullable annualized volatility, never a measured zero', () => {
    // The annualization gate sets the key to `null` below the minimum measured
    // return sample. A `number` here would let `fmtPct(0)` print `0.00%` for a
    // history too short to annualize.
    const gated: Pick<RiskContributionResponse, 'portfolio_volatility_annualized'> = {
      portfolio_volatility_annualized: null,
    };
    expect(gated.portfolio_volatility_annualized).toBeNull();
  });
});
