/**
 * SectionProvenance is mounted on every analytics section page, and these are
 * the assertions that make the mount real rather than decorative.
 *
 * The disclosure this component renders was already on the wire — `as_of` /
 * `as_of_semantics`, `universe_coverage.missing_tickers`, `warnings` — and was
 * read by no page except regime and india-flows. A user therefore could not
 * tell a stale risk number from a live one, and a holding silently dropped from
 * a computation left no on-screen trace. These tests hold each page to stating
 * that.
 *
 * Four properties, in the order they break things:
 *
 *  1. EVERY page in the list below renders the line. One shared test cannot
 *     prove this, because a component that renders nothing looks exactly like a
 *     page nobody mounted — so the page list is the fixture and the loop is the
 *     assertion.
 *  2. The NULL case is asserted per page, and that is the one that matters.
 *     `N/A — no measurement date published` is a correct answer; today's date
 *     is a fabrication; an empty line is indistinguishable from no mount.
 *  3. A missing ticker is NAMED. "Coverage incomplete" is not actionable;
 *     `GHOST.NS` is.
 *  4. `as_of_semantics` renders wherever the backend publishes it, so a section
 *     cannot regress to a bare, meaning-free date.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

import {
  NO_MEASUREMENT_DATE,
  SectionProvenance,
  sectionCoverage,
} from '@/components/provenance/SectionProvenance';

// ---------------------------------------------------------------------------
// Module mocks. Every page is mounted against the same mocked API module, so
// the per-page fixtures below are the only thing that varies.
// ---------------------------------------------------------------------------

const mocks = vi.hoisted(() => ({
  api: {
    getRealizedRisk: vi.fn(),
    getForecastRisk: vi.fn(),
    getFactorExposure: vi.fn(),
    getConcentrationMetrics: vi.fn(),
    getLiquidityMetrics: vi.fn(),
    runStressTest: vi.fn(),
    getTearSheet: vi.fn(),
    getRiskContribution: vi.fn(),
    runOptimization: vi.fn(),
    runMonteCarlo: vi.fn(),
    getVolatilitySizing: vi.fn(),
  },
  // Risk Studio and Pairs call `apiClient.get(...)`/`api.get(...)` by URL.
  httpGet: vi.fn(),
  rebalancePortfolio: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: mocks.api,
  portfolioApi: { rebalancePortfolio: mocks.rebalancePortfolio },
  default: { get: (...args: unknown[]) => mocks.httpGet(...(args as [])) },
  apiClient: {
    get: (...args: unknown[]) => mocks.httpGet(...(args as [])),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('@/lib/store', () => {
  // Several pages call `useUIStore.getState().updateLastUpdated()` OUTSIDE a
  // component body, so the mock has to be a callable hook carrying its own
  // `getState` — a plain object return made `getState` undefined and every such
  // page's fetch threw before it could render anything.
  const useUIStore = Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }),
    { getState: () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }) },
  );
  return {
    usePortfolioStore: () => ({
      positions: [
        { ticker: 'AAA.NS', weight: 0.6, quantity: 10, last_price: 100, market_value: 600, sector: 'Bank' },
        { ticker: 'BBB.NS', weight: 0.4, quantity: 5, last_price: 200, market_value: 400, sector: 'Auto' },
      ],
      fetchPortfolio: vi.fn().mockResolvedValue(undefined),
      isLoading: false,
      error: null,
      totalValue: 1000,
    }),
    useUIStore,
  };
});

vi.mock('@/hooks/useAnalytics', () => ({
  usePortfolioAnalytics: () => ({
    data: {
      summary: null,
      // The hook is what feeds realized-risk; bind it to the same fixture the
      // API mock returns so one payload drives both entry points.
      realizedRisk: mocks.api.getRealizedRisk(),
      forecastRisk: mocks.api.getForecastRisk(),
      factorExposure: mocks.api.getFactorExposure(),
      concentration: mocks.api.getConcentrationMetrics(),
      liquidity: mocks.api.getLiquidityMetrics(),
      riskScore: null,
    },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
  usePerformanceData: () => ({ performanceData: [], loading: false, freshness: null }),
  useSectorAllocation: () => [],
}));

import RealizedRiskPage from '@/app/dashboard/realized-risk/page';
import ForecastRiskPage from '@/app/dashboard/forecast-risk/page';
import FactorExposurePage from '@/app/dashboard/factor-exposure/page';
import ConcentrationPage from '@/app/dashboard/concentration/page';
import LiquidityPage from '@/app/dashboard/liquidity/page';
import StressTestingPage from '@/app/dashboard/stress-testing/page';
import TearSheetPage from '@/app/dashboard/tear-sheet/page';
import RiskContributionPage from '@/app/dashboard/risk-contribution/page';
import RiskStudioPage from '@/app/dashboard/risk-studio/page';
import OptimizePage from '@/app/dashboard/optimize/page';
import MonteCarloPage from '@/app/dashboard/monte-carlo/page';
import PairsPage from '@/app/dashboard/pairs/page';
import VolatilitySizingPage from '@/app/dashboard/volatility-sizing/page';

// ---------------------------------------------------------------------------
// Payload fragments. Each is shaped from what the route actually publishes
// (backend/app/api/analytics.py), including the three coverage states the
// backend's own `_universe_coverage` distinguishes.
// ---------------------------------------------------------------------------

/** Requested two, delivered one: `GHOST.NS` is the named gap. */
const coverageWithGap = {
  requested_tickers: ['AAA.NS', 'GHOST.NS'],
  available_tickers: ['AAA.NS'],
  covered_tickers: ['AAA.NS'],
  missing_tickers: ['GHOST.NS'],
  requested_count: 2,
  available_count: 1,
  coverage_ratio: 0.5,
  complete: false,
  status: 'partial',
};

/** Measured complete: the zero case, which must read differently from no block. */
const coverageComplete = { ...coverageWithGap, missing_tickers: [], complete: true, status: 'complete' };

/** Coverage measured as unknown — `missing_tickers: null`, not `[]`. */
const coverageUnknown = { ...coverageWithGap, missing_tickers: null, status: 'unknown' };

const AS_OF = '2026-09-07';

const buildPayloads = (options: {
  withDate: boolean;
  withGap: boolean;
  semantics?: string | null;
}) => {
  const asOf = options.withDate ? AS_OF : null;
  const coverage = options.withGap ? coverageWithGap : coverageComplete;
  return {
    realizedRisk: {
      portfolio: { max_drawdown: -0.02, var_95: -0.01, cvar_95: -0.015, hit_ratio: 0.5, sharpe_ratio: 0.4 },
      positions: { 'AAA.NS': { annual_volatility: 0.2, weight: 1, data_points: 250, is_limited_history: false, history_warning: null, annual_return: 0.1, sharpe_ratio: 0.4, max_drawdown: -0.02, var_95: -0.01, return_observations: 250, annualized: true, analytics_start: null, analytics_start_source: null, stored_added_on: null, buy_price_inferred: null } },
      instrument_risk: { portfolio: {}, positions: {} },
      warnings: [],
      data_range: { start: '2025-09-08', end: AS_OF },
      latest_observation_date: asOf,
      as_of_semantics: options.semantics ?? null,
      universe_coverage: coverage,
      history_coverage: {},
      methodology: 'test',
    },
    forecastRisk: {
      model: 'GARCH', horizon: 1,
      portfolio: { volatility_forecast: 0.18, var_forecast: -0.02, cvar_forecast: -0.03 },
      positions: {},
      warnings: [],
      latest_observation_date: asOf,
      as_of_semantics: options.semantics ?? null,
      universe_coverage: coverage,
    },
    factorExposure: {
      portfolio: { alpha: 0.01, market: 0.02, beta: 0.9 },
      positions: {},
      warnings: [],
      r_squared: 0.4, adjusted_r_squared: 0.38,
      data_range: { start: '2025-09-08', end: AS_OF },
      lookback_days: 252,
      latest_observation_date: asOf,
      as_of_semantics: options.semantics ?? null,
      universe_coverage: coverage,
    },
    concentration: {
      largest_position: 0.6, top_3: 0.9, top_5: 1, top_10: 1,
      herfindahl_index: 0.52, effective_positions: 1.92,
      diversification_ratio: 1, diversification_score: 40,
      by_weight: { 'AAA.NS': 0.6, 'BBB.NS': 0.4 },
      by_sector: { Bank: 0.6, Auto: 0.4 },
      methodology: 'test',
      as_of: asOf,
      as_of_semantics: options.semantics ?? null,
      warnings: [],
      universe_coverage: coverage,
    },
    liquidity: {
      overall_score: 8.2, liquidation_time_days: '1-2', risk_level: 'Low',
      by_position: {}, volume_stats: { avg_volume: 1, total_portfolio_volume: 1, high_volume_pct: 1, medium_volume_pct: 0, low_volume_pct: 0 },
      methodology: 'test',
      latest_observation_date: asOf,
      as_of_semantics: options.semantics ?? null,
      warnings: [],
      universe_coverage: coverage,
    },
    stressTest: {
      scenario: 'Market Crash',
      max_drawdown: -0.2, portfolio_impact: -0.2,
      position_impacts: { 'AAA.NS': -0.2 },
      recovery_time: 3,
      latest_observation_date: asOf,
      universe_coverage: coverage,
      warnings: [],
    },
    tearSheet: {
      window: { start: '2025-09-08', end: AS_OF },
      holdings: { 'AAA.NS': 0.6, 'BBB.NS': 0.4 },
      metrics: { total_return: 0.12, sharpe: 1.1 },
      relative_vs_nifty: {}, monthly_returns: {}, underwater: [],
      methodology: 'test',
      latest_observation_date: asOf,
      as_of_semantics: options.semantics ?? null,
      universe_coverage: coverage,
    },
    riskContribution: {
      window: { start: '2025-09-08', end: AS_OF },
      positions: { volatility: { 'AAA.NS': 0.6 }, cvar_tail: { 'AAA.NS': 0.55 } },
      sector_rollup: { volatility: { Bank: 0.6 }, cvar_tail: { Bank: 0.55 } },
      portfolio_volatility_annualized: 0.18,
      portfolio_var_95_daily: -0.02,
      portfolio_cvar_95_daily: -0.03,
      methodology: 'test',
      latest_observation_date: asOf,
      as_of_semantics: options.semantics ?? null,
      universe_coverage: coverage,
    },
    riskStudio: {
      riskContribution: { latest_observation_date: asOf, universe_coverage: coverage, warnings: [] },
      tailRisk: { as_of: asOf, universe_coverage: coverage, warnings: [] },
      volCone: { latest_observation_date: asOf, universe_coverage: coverage },
      correlation: { as_of: asOf, universe_coverage: coverage },
    },
    optimize: {
      strategy: 'hrp',
      weights: { 'AAA.NS': 0.6, 'BBB.NS': 0.4 },
      expected_annual_return: 0.1, expected_annual_volatility: 0.15, expected_sharpe: 0.8,
      solver: 'hrp', universe: ['AAA.NS', 'BBB.NS'],
      current_weights: { 'AAA.NS': 0.5, 'BBB.NS': 0.5 },
      trades_required: {},
      disclaimer: 'test',
      latest_observation_date: asOf,
      as_of_semantics: options.semantics ?? null,
      universe_coverage: coverage,
    },
    monteCarlo: {
      method: 'student_t', initial_value: 1000, target_value: 2000, horizon_years: 5,
      num_paths: 1000, prob_success: 0.42,
      terminal_percentiles: { p5: 900, p25: 1100, p50: 1300, p75: 1600, p95: 2100 },
      fan: [], expected_shortfall_vs_target: 0.1,
      historical_mu_annual: 0.1, historical_sigma_annual: 0.18,
      student_t_df: 4, disclaimer: 'test',
      latest_observation_date: asOf,
      as_of_semantics: options.semantics ?? null,
      universe_coverage: coverage,
    },
    pairs: {
      as_of: asOf,
      // The pairs scan publishes a real `as_of_semantics` by default (as does
      // `/correlation-stability`, on both its branches), and it is the one that
      // swaps it for `request_end_no_usable_price_data` when the scan had no
      // usable price.
      as_of_semantics: options.semantics ?? 'latest_available_observation',
      pairs: [],
      missing_tickers: coverage.missing_tickers,
      universe_coverage: coverage,
      warnings: [],
    },
    volatilitySizing: {
      current_weights: { 'AAA.NS': 0.5, 'BBB.NS': 0.5 },
      recommended_weights: { 'AAA.NS': 0.6, 'BBB.NS': 0.4 },
      trades: {}, target_volatility: 0.15,
      current_volatility: 0.18,
      latest_observation_date: asOf,
      as_of_semantics: options.semantics ?? null,
      universe_coverage: coverage,
      sizing_basis: {
        sizing_price: { 'AAA.NS': 100, 'BBB.NS': 200 },
        sizing_price_as_of: asOf,
        price_currency: 'INR', price_currency_provenance: 'declared', status: 'measured',
        missing_tickers: coverage.missing_tickers,
        price_freshness: {
          sizing_price_as_of: asOf,
          latest_delivered_observation: asOf,
          sizing_price_calendar_days_behind: 0,
          sizing_price_as_of_status: 'measured',
          rule: 'sizing_price is the last close delivered inside the sizing window',
        },
      },
    },
  };
};

/**
 * Each page, and how to make it render the given payload.
 *
 * `run` returns after the page has resolved its own fetch, so the assertions
 * that follow are synchronous and do not race the mount.
 */
const PAGES: Array<{
  name: string;
  Page: React.ComponentType;
  run: () => Promise<void>;
}> = [
  {
    name: 'realized-risk',
    Page: RealizedRiskPage,
    run: async () => {
      render(<RealizedRiskPage />);
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'forecast-risk',
    Page: ForecastRiskPage,
    run: async () => {
      render(<ForecastRiskPage />);
      await waitFor(() => expect(mocks.api.getForecastRisk).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'factor-exposure',
    Page: FactorExposurePage,
    run: async () => {
      render(<FactorExposurePage />);
      await waitFor(() => expect(mocks.api.getFactorExposure).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'concentration',
    Page: ConcentrationPage,
    run: async () => {
      render(<ConcentrationPage />);
      await waitFor(() => expect(mocks.api.getConcentrationMetrics).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'liquidity',
    Page: LiquidityPage,
    run: async () => {
      render(<LiquidityPage />);
      await waitFor(() => expect(mocks.api.getLiquidityMetrics).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'stress-testing',
    Page: StressTestingPage,
    run: async () => {
      render(<StressTestingPage />);
      await waitFor(() => expect(mocks.api.runStressTest).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'tear-sheet',
    Page: TearSheetPage,
    run: async () => {
      render(<TearSheetPage />);
      await waitFor(() => expect(mocks.api.getTearSheet).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'risk-contribution',
    Page: RiskContributionPage,
    run: async () => {
      render(<RiskContributionPage />);
      await waitFor(() => expect(mocks.api.getRiskContribution).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'risk-studio',
    Page: RiskStudioPage,
    run: async () => {
      render(<RiskStudioPage />);
      await waitFor(() => expect(mocks.httpGet).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'optimize',
    Page: OptimizePage,
    run: async () => {
      const { fireEvent } = await import('@testing-library/react');
      render(<OptimizePage />);
      fireEvent.click(screen.getByRole('button', { name: /Run HRP/i }));
      await waitFor(() => expect(mocks.api.runOptimization).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'monte-carlo',
    Page: MonteCarloPage,
    run: async () => {
      const { fireEvent } = await import('@testing-library/react');
      render(<MonteCarloPage />);
      fireEvent.click(screen.getByRole('button', { name: /simulate|run/i }));
      await waitFor(() => expect(mocks.api.runMonteCarlo).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'pairs',
    Page: PairsPage,
    run: async () => {
      render(<PairsPage />);
      await waitFor(() => expect(mocks.httpGet).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
  {
    name: 'volatility-sizing',
    Page: VolatilitySizingPage,
    run: async () => {
      render(<VolatilitySizingPage />);
      await waitFor(() => expect(mocks.api.getVolatilitySizing).toHaveBeenCalled());
      await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    },
  },
];

/**
 * Route each mock at its fixture.
 *
 * `realized-risk` is read through the analytics hook, which is itself mocked,
 * so the hook returns the same fixture the API mock would serve. Risk Studio
 * and Pairs go through `httpGet` and are dispatched by URL.
 */
const wireMocks = (payloads: ReturnType<typeof buildPayloads>) => {
  mocks.api.getRealizedRisk.mockReturnValue(payloads.realizedRisk as never);
  mocks.api.getForecastRisk.mockResolvedValue(payloads.forecastRisk as never);
  mocks.api.getFactorExposure.mockResolvedValue(payloads.factorExposure as never);
  mocks.api.getConcentrationMetrics.mockResolvedValue(payloads.concentration as never);
  mocks.api.getLiquidityMetrics.mockResolvedValue(payloads.liquidity as never);
  mocks.api.runStressTest.mockResolvedValue(payloads.stressTest as never);
  mocks.api.getTearSheet.mockResolvedValue(payloads.tearSheet as never);
  mocks.api.getRiskContribution.mockResolvedValue(payloads.riskContribution as never);
  mocks.api.runOptimization.mockResolvedValue(payloads.optimize as never);
  mocks.api.runMonteCarlo.mockResolvedValue(payloads.monteCarlo as never);
  mocks.api.getVolatilitySizing.mockResolvedValue(payloads.volatilitySizing as never);

  mocks.httpGet.mockImplementation((url: string) => {
    if (url.includes('/analytics/risk-contribution')) {
      return Promise.resolve({ data: payloads.riskStudio.riskContribution });
    }
    if (url.includes('/analytics/tail-dependence')) {
      return Promise.resolve({ data: payloads.riskStudio.tailRisk });
    }
    if (url.includes('/analytics/vol-cone')) {
      return Promise.resolve({ data: payloads.riskStudio.volCone });
    }
    if (url.includes('/analytics/correlation-stability')) {
      return Promise.resolve({ data: payloads.riskStudio.correlation });
    }
    if (url.includes('/analytics/coint')) {
      return Promise.resolve({ data: payloads.pairs });
    }
    return Promise.resolve({ data: {} });
  });
};

describe('SectionProvenance — one component, mounted on every section page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wireMocks(buildPayloads({ withDate: true, withGap: true }));
  });

  // Requirement: a test PER PAGE asserting the provenance line is on screen.
  describe.each(PAGES)('$name', ({ name, run }) => {
    it('renders the provenance line', async () => {
      await run();
      expect(screen.getByTestId('section-provenance'), `${name} has no provenance line`).toBeDefined();
    });

    // The negative case, and the one that matters. A component that renders
    // nothing when the date is missing looks identical to a page that was
    // never mounted, so the null path is asserted for every page.
    it(`states "${NO_MEASUREMENT_DATE}" rather than rendering nothing when as_of is null`, async () => {
      wireMocks(buildPayloads({ withDate: false, withGap: true }));
      await run();
      expect(screen.getByTestId('section-provenance'), `${name} has no provenance line`).toBeDefined();
      expect(
        screen.getByText(NO_MEASUREMENT_DATE),
        `${name} did not state the absent measurement date`,
      ).toBeDefined();
    });

    // The fabrication this whole task exists to remove. Asserted against the
    // REAL clock rather than a faked one: fake timers would freeze `waitFor`'s
    // polling and turn every page's mount into a timeout, which is a test-harness
    // artefact, not a product signal.
    it('never substitutes today for an absent measurement date', async () => {
      const today = new Date().toISOString().slice(0, 10);
      wireMocks(buildPayloads({ withDate: false, withGap: true }));
      await run();
      const line = screen.getByTestId('section-provenance').textContent ?? '';
      expect(line).toContain(NO_MEASUREMENT_DATE);
      expect(line, `${name} fell back to today's date`).not.toContain(today);
    });
  });
});

describe('SectionProvenance — a missing ticker is NAMED, not counted', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('names every missing ticker on realized-risk', async () => {
    wireMocks(buildPayloads({ withDate: true, withGap: true }));
    render(<RealizedRiskPage />);
    await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());

    const coverage = screen.getByTestId('provenance-coverage').textContent ?? '';
    expect(coverage).toContain('GHOST.NS');
    // Actionable, not a bare count.
    expect(coverage).toMatch(/incomplete/i);
  });

  it('names a missing ticker on the pairs scan, which publishes real as_of_semantics', async () => {
    wireMocks(buildPayloads({ withDate: true, withGap: true }));
    render(<PairsPage />);
    await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    expect(screen.getByTestId('provenance-coverage').textContent ?? '').toContain('GHOST.NS');
  });

  it('distinguishes zero missing from no coverage block', async () => {
    // Zero missing — a MEASURED claim that everything participated.
    wireMocks(buildPayloads({ withDate: true, withGap: false }));
    render(<RealizedRiskPage />);
    await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    const completeLine = screen.getByTestId('provenance-coverage').textContent ?? '';
    expect(completeLine).toMatch(/complete/i);
    expect(completeLine).not.toContain('GHOST.NS');

    // No coverage block at all — a DIFFERENT fact, and it must read differently.
    const absent = render(
      <SectionProvenance section="X" coverage={sectionCoverage(undefined)} />,
    );
    const absentLine = screen.getAllByTestId('provenance-coverage').at(-1)?.textContent ?? '';
    expect(absentLine).toMatch(/no coverage block/i);
    expect(absentLine).not.toBe(completeLine);
    absent.unmount();
  });

  it('renders coverage unknown (missing_tickers null) differently from zero missing', () => {
    render(<SectionProvenance section="X" coverage={sectionCoverage(coverageUnknown)} />);
    const line = screen.getByTestId('provenance-coverage').textContent ?? '';
    expect(line).toMatch(/unmeasured|unknown/i);
    expect(line).not.toMatch(/0 missing/);
  });
});

describe('SectionProvenance — as_of_semantics renders wherever the backend publishes it', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the declared semantics token verbatim on the pairs scan', async () => {
    wireMocks(buildPayloads({ withDate: true, withGap: true, semantics: 'latest_available_observation' }));
    render(<PairsPage />);
    await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    expect(screen.getByTestId('provenance-as-of-semantics').textContent ?? '')
      .toContain('latest_available_observation');
  });

  it('renders the alternate semantics when the scan had no usable price data', async () => {
    wireMocks(buildPayloads({
      withDate: true,
      withGap: true,
      semantics: 'request_end_no_usable_price_data',
    }));
    render(<PairsPage />);
    await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
    const line = screen.getByTestId('provenance-as-of-semantics').textContent ?? '';
    expect(line).toContain('request_end_no_usable_price_data');
    // Not the other one: the two semantics mean different things and the line
    // must not blur them into a generic "freshness".
    expect(line).not.toContain('latest_available_observation');
  });

  /**
   * `/analytics/coint` and `/correlation-stability` are the routes that publish
   * a non-null `as_of_semantics` — verified against
   * `backend/app/api/analytics.py` (the sole `"as_of_semantics"` key between the
   * realized-risk and vol-cone routes is concentration's always-null one,
   * `CointScannerResponse` declares
   * `as_of_semantics: str = "latest_available_observation"`, and
   * `CorrelationStabilityResponse` sets a token on BOTH its branches —
   * `request_end_universe_too_small_for_pairwise_correlation` at
   * analytics.py:11025 and `latest_available_observation` at
   * correlation_service.py:263 — so it is no longer a sole publisher).
   *
   * None of the four routes exercised below is one of them, so the inverse is
   * pinned here: a route that publishes NO semantics must not be made to look as
   * though it did. Fabricating a label in the frontend to fill the gap would be a
   * second, drifting copy of the backend's vocabulary.
   */
  it.each([
    ['realized-risk', RealizedRiskPage],
    ['liquidity', LiquidityPage],
    ['tear-sheet', TearSheetPage],
    ['monte-carlo', MonteCarloPage],
  ] as const)(
    '%s states that no semantics is declared instead of showing a bare date',
    async (name, Page) => {
      // The fixture carries NO semantics token, matching the real wire shape.
      wireMocks(buildPayloads({ withDate: true, withGap: true, semantics: null }));
      const entry = PAGES.find((candidate) => candidate.name === name);
      // Monte-carlo holds no payload until the simulation is run, so reuse the
      // page's own run step rather than assuming a bare render is enough.
      if (name === 'monte-carlo') {
        await entry!.run();
      } else {
        render(<Page />);
        await waitFor(() => expect(screen.getByTestId('section-provenance')).toBeDefined());
      }
      const line = screen.getByTestId('provenance-as-of-semantics').textContent ?? '';
      expect(line, `${name} claimed semantics it does not publish`).toMatch(
        /declares no semantics/i,
      );
      // The date is still shown; it is the MEANING that is stated as missing.
      expect(screen.getByTestId('provenance-as-of').textContent ?? '').toContain(AS_OF);
    },
  );

  it('renders a published semantics token verbatim wherever one is sent', () => {
    // Component-level: whatever token arrives is rendered untranslated.
    wireMocks(buildPayloads({
      withDate: true,
      withGap: true,
      semantics: 'last_delivered_daily_close_date',
    }));
    render(
      <SectionProvenance
        section="X"
        asOf={AS_OF}
        asOfSemantics="last_delivered_daily_close_date"
      />,
    );
    expect(screen.getByTestId('provenance-as-of-semantics').textContent ?? '')
      .toContain('last_delivered_daily_close_date');
  });

  it('says so plainly when a section publishes no semantics, instead of showing a bare date', () => {
    render(<SectionProvenance section="X" asOf={AS_OF} />);
    const line = screen.getByTestId('provenance-as-of-semantics').textContent ?? '';
    expect(line).toMatch(/declares no semantics/i);
    // The date is still shown; it is the MEANING that is stated as missing.
    expect(screen.getByTestId('provenance-as-of').textContent ?? '').toContain(AS_OF);
  });
});

describe('SectionProvenance — the null case and the semantics contract', () => {
  it('treats an empty-string date as absent, not as a date', () => {
    render(<SectionProvenance section="X" asOf="   " />);
    expect(screen.getByTestId('provenance-as-of').textContent ?? '').toContain(NO_MEASUREMENT_DATE);
  });

  it('renders a code-keyed warning record, which has no message', () => {
    render(
      <SectionProvenance
        section="X"
        warnings={[{ code: 'forecast_precision_leg_refit_declined', message: null }]}
      />,
    );
    expect(screen.getByTestId('provenance-warnings').textContent ?? '')
      .toContain('forecast_precision_leg_refit_declined');
  });

  it('renders a structured per-position warning as ticker + message', () => {
    render(
      <SectionProvenance
        section="X"
        warnings={[{ ticker: 'OLD.NS', data_points: 24, message: 'limited history' } as never]}
      />,
    );
    const line = screen.getByTestId('provenance-warnings').textContent ?? '';
    expect(line).toContain('OLD.NS');
    expect(line).toContain('limited history');
  });

  it('omits the warnings block entirely when there are none', () => {
    render(<SectionProvenance section="X" warnings={[]} />);
    expect(screen.queryByTestId('provenance-warnings')).toBeNull();
  });

  it('drops a blank warning rather than rendering an empty list item', () => {
    render(<SectionProvenance section="X" warnings={['   ', '']} />);
    expect(screen.queryByTestId('provenance-warnings')).toBeNull();
  });

  it('sectionCoverage maps a published block to its missing list and an absent block to null', () => {
    expect(sectionCoverage(coverageWithGap)).toEqual({ missingTickers: ['GHOST.NS'] });
    expect(sectionCoverage(coverageComplete)).toEqual({ missingTickers: [] });
    expect(sectionCoverage(coverageUnknown)).toEqual({ missingTickers: null });
    // No block at all is NOT the same as a block reporting zero missing.
    expect(sectionCoverage(undefined)).toBeNull();
    expect(sectionCoverage(null)).toBeNull();
  });
});
