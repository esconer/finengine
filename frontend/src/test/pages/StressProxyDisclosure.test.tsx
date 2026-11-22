/**
 * The stress engine names how it produced every figure it publishes, and the
 * names say the result is a proxy:
 *
 *   `analytics_engine.py:4736` `"max_drawdown_basis": "derived_from_shock_proxy"`
 *   `:4739`               `"impact_basis": "deterministic_factor_proxy"`
 *   `:4742`               `"recovery_time_basis": "configured_recovery_estimate_not_simulated"`
 *   `:4744`               `"confidence_basis": "nominal_label_not_simulated"`
 *   `:4745`               `"shock_inputs"`
 *   `:4751`               `"methodology"`
 *
 * `stress-testing/page.tsx` rendered NONE of that while labelling itself a
 * "Multi-Factor Simulation Engine", calling a table column "Simulated Impact"
 * and a button "Run Simulation". Two of the basis tokens contain the words
 * `not_simulated`. These cases pin the disclosure to the payload: it has to
 * appear, it has to carry the engine's own strings, and no copy may reintroduce
 * the word the response contradicts.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import React from 'react';

const mocks = vi.hoisted(() => ({
  positions: [] as any[],
  fetchPortfolio: vi.fn().mockResolvedValue(undefined),
  runStressTest: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard/stress-testing',
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: mocks.positions,
    fetchPortfolio: mocks.fetchPortfolio,
    isLoading: false,
    error: null,
    totalValue: 0,
  }),
  useUIStore: Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: vi.fn(), liveDataMode: true }),
    { getState: () => ({ updateLastUpdated: vi.fn() }) }
  ),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: { runStressTest: mocks.runStressTest },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

import StressTestingPage from '@/app/dashboard/stress-testing/page';

const PAGE = resolve(process.cwd(), 'src/app/dashboard/stress-testing/page.tsx');

/** The payload shape `analytics_engine.py:4732-4752` returns on success. */
const FULL_PAYLOAD = {
  scenario: 'Market Crash',
  scenario_description: 'Global Financial Crisis / Severe Market Crash (-35% NIFTY shock)',
  max_drawdown: -0.09,
  max_drawdown_basis: 'derived_from_shock_proxy',
  max_drawdown_formula: 'portfolio_impact * 1.15',
  portfolio_impact: -0.078,
  impact_basis: 'deterministic_factor_proxy',
  position_impacts: { 'AAA.NS': -0.1 },
  recovery_time: 24,
  recovery_time_basis: 'configured_recovery_estimate_not_simulated',
  confidence_level: 0.95,
  confidence_basis: 'nominal_label_not_simulated',
  shock_inputs: {
    market_shock: -0.35,
    market_shock_basis: 'scenario_config_row',
    sector_elasticity_table: { Technology: 1.1 },
    sector_elasticity_basis: 'static_configured_table',
    position_impact_clip: [-0.75, -0.02],
    position_impact_clip_basis: 'configured_bounds_not_simulated',
    unclassified_bucket_member_count: 2,
    bucket_disclosure: "'Exchange Traded Fund' is this engine's UNCLASSIFIED sector.",
    co_movement: {
      basis: 'equal_weighted_mean_of_the_other_holdings_returns',
      is_applied_to_the_shock: false,
    },
    volatility_adjustment: {
      basis: 'measured_annualized_volatility_over_reference',
      reference_annualized_volatility: 0.22,
    },
  },
  methodology:
    'Deterministic factor shock proxy; no path sampling and no simulation.',
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [{ id: 1, ticker: 'AAA.NS', weight: 1, quantity: 1, last_price: 100, market_value: 100 }];
  mocks.runStressTest.mockResolvedValue(FULL_PAYLOAD);
});

describe('stress-testing renders the basis the engine already publishes', () => {
  it('shows methodology and all four *_basis tokens verbatim', async () => {
    render(<StressTestingPage />);

    const panel = await screen.findByTestId('stress-basis-disclosure');

    // `methodology` was declared on the response type and read nowhere. It is
    // the engine's own account of the computation, ~15 lines of prose.
    expect(panel.textContent).toContain(FULL_PAYLOAD.methodology);

    // The four basis fields. Each names the derivation of a figure that is on
    // screen at the same time, which is what makes the copy above it readable.
    expect(panel.textContent).toContain('derived_from_shock_proxy');
    expect(panel.textContent).toContain('deterministic_factor_proxy');
    expect(panel.textContent).toContain('configured_recovery_estimate_not_simulated');
    expect(panel.textContent).toContain('nominal_label_not_simulated');
    expect(panel.textContent).toContain('portfolio_impact * 1.15');
  }, 20000);

  it('shows the shock_inputs scalars, including the clip the impacts are held inside', async () => {
    render(<StressTestingPage />);

    const panel = await screen.findByTestId('stress-basis-disclosure');

    // -0.35 as a signed fraction return → "-35.0%" through the page's own single
    // fraction→percent conversion (`units.market_shock`, engine :4697).
    expect(panel.textContent).toContain('-35.0%');
    expect(panel.textContent).toContain('scenario_config_row');
    // The clip is the disclosure that a -1% request still publishes -2.00%.
    expect(panel.textContent).toContain('-75.0% to -2.0%');
    expect(panel.textContent).toContain('configured_bounds_not_simulated');
    expect(panel.textContent).toContain('static_configured_table');
    // Measured co-movement is published AND explicitly not applied to the shock.
    expect(panel.textContent).toContain('NOT applied to the shock');
    expect(panel.textContent).toContain('measured_annualized_volatility_over_reference');
  }, 20000);

  it('prints "not published by this response" for an omitted basis, never a default string', async () => {
    // `_empty_stress_test()` (:7094-7112) mirrors the success payload key-for-key
    // with nulls. A hardcoded fallback here would be the page inventing the
    // engine's wording, which is the defect the disclosure exists to stop.
    mocks.runStressTest.mockResolvedValue({
      scenario: 'Market Crash',
      max_drawdown: null,
      portfolio_impact: -0.05,
      position_impacts: { 'AAA.NS': -0.05 },
      recovery_time: null,
      max_drawdown_basis: null,
      impact_basis: null,
      recovery_time_basis: null,
      confidence_basis: null,
      shock_inputs: null,
      methodology: null,
    });

    render(<StressTestingPage />);

    const panel = await screen.findByTestId('stress-basis-disclosure');
    expect(panel.textContent).toContain('not published by this response');
    expect(panel.textContent).not.toContain('deterministic_factor_proxy');
    expect(panel.textContent).not.toContain('not_simulated');
  }, 20000);

  it('never substitutes a basis when the whole disclosure block is missing', async () => {
    mocks.runStressTest.mockResolvedValue({
      scenario: 'Market Crash',
      max_drawdown: -0.05,
      portfolio_impact: -0.05,
      position_impacts: { 'AAA.NS': -0.05 },
      recovery_time: 24,
    });

    render(<StressTestingPage />);

    await waitFor(() => {
      expect(mocks.runStressTest).toHaveBeenCalled();
    });
    const panel = await screen.findByTestId('stress-basis-disclosure');
    expect(panel.textContent).toContain('not published by this response');
    // The shock rows are driven off `shock_inputs`, so an absent object renders
    // none of them rather than an empty band.
    expect(panel.textContent).not.toContain('Applied market shock');
    expect(panel.textContent).not.toContain('Position impact clip');
  }, 20000);
});

describe('stress-testing copy no longer calls a deterministic proxy a simulation', () => {
  it('renders every basis string the engine sends, so the page has none of its own to assert', async () => {
    render(<StressTestingPage />);
    await screen.findByTestId('stress-basis-disclosure');
    // The page's own figures must be the backend's — the impact cell still reads
    // -0.1 off the payload rather than a fabricated shock.
    expect(screen.getAllByText('AAA.NS').length).toBeGreaterThan(0);
    expect(screen.getAllByText('-10.0%').length).toBeGreaterThan(0);
  }, 20000);

  it('no user-visible "Simulation Engine" / "Run Simulation" / "Simulated Impact" survives', async () => {
    render(<StressTestingPage />);
    await screen.findByTestId('stress-basis-disclosure');

    // Hero badge.
    expect(screen.queryByText('Multi-Factor Simulation Engine')).toBeNull();
    expect(screen.getByText('Multi-Factor Shock Proxy')).toBeDefined();
    // Table column header.
    expect(screen.queryByText('Simulated Impact')).toBeNull();
    expect(screen.getByText('Stress Impact (proxy)')).toBeDefined();
    // Custom-form submit button.
    expect(screen.queryByText('Run Simulation')).toBeNull();
    expect(screen.queryByText('Simulating...')).toBeNull();

    // And in the source, outside comments: the two explainer templates that named
    // a simulation were rewritten to name the proxy.
    const src = readFileSync(PAGE, 'utf8');
    expect(src).not.toContain('Multi-Factor Simulation Engine');
    expect(src).not.toContain("'Simulated Impact'");
    expect(src).not.toContain('Run Simulation');
    expect(src).not.toContain('stress testing simulations');
    expect(src).not.toContain('Stress Simulator');
  });

  it('reads the built-in scenario description from the engine, not from page prose', async () => {
    // The four built-ins used to print hand-typed strings carrying the shock
    // magnitude ("(-35% NIFTY shock)"), so a drift between the page copy and
    // `scenarios_config` (:4308-4379) was invisible. Every card now prefers the
    // engine's `scenario_description`.
    mocks.runStressTest.mockImplementation(async ({ scenario }: { scenario: string }) => ({
      ...FULL_PAYLOAD,
      scenario,
      scenario_description: `engine-authored: ${scenario}`,
    }));

    render(<StressTestingPage />);
    await screen.findByTestId('stress-basis-disclosure');

    await waitFor(() => {
      expect(screen.getAllByText('engine-authored: Market Crash').length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText('engine-authored: Interest Rate Shock').length).toBeGreaterThan(0);
    expect(screen.getAllByText('engine-authored: Volatility Spike').length).toBeGreaterThan(0);
    expect(screen.getAllByText('engine-authored: Tech Sector Correction').length).toBeGreaterThan(0);
  }, 20000);

  it('keeps the seed description only for a scenario that has not run', async () => {
    mocks.runStressTest.mockResolvedValue({
      ...FULL_PAYLOAD,
      // No `scenario_description` at all — the seed is the only text there is.
      scenario_description: undefined,
    });

    render(<StressTestingPage />);
    await screen.findByTestId('stress-basis-disclosure');

    // Seeded without the shock magnitude: the page holds no longer asserts a
    // number the engine owns. `shock_inputs.market_shock` is where it now reads.
    expect(screen.getAllByText('Global financial crisis scenario, 2008').length).toBeGreaterThan(0);
    expect(screen.queryByText(/Recession scenario based on 2008 financial crisis/)).toBeNull();
  }, 20000);
});