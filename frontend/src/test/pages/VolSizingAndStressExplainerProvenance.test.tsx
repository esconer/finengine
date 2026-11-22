/**
 * The last two carriers of the fabricated-explainer-benchmark defect class that
 * was cleared from five other pages (`FabricatedExplainerBenchmarks.test.tsx`).
 *
 *   volatility-sizing:48   `benchmark?: string;` on `ExplainerContent`
 *   volatility-sizing:58   'Standard equity risk budget benchmark: 15.0%
 *                           annualized volatility.'  ← an invented benchmark
 *   volatility-sizing:66   'Ideally aligned within ±1.0% of your target
 *                           volatility.'              ← an invented tolerance
 *   volatility-sizing:122  'Positions with low volatility (e.g. NIFTYIETF,
 *                           CIPLA)… (e.g. ELECTCAST, ARROWGREEN)…'
 *                           ← four REAL holdings the route never named
 *   volatility-sizing:234  rendered under "Quantitative Guideline:" — the
 *                           THIRD label for the same carrier (the five cleared
 *                           pages used "Quantitative Benchmark:" and "Target
 *                           Benchmark:")
 *
 *   stress-testing:315     'Defensive utility and pharmaceutical stocks
 *                           (NTPC, CIPLA) limit drawdowns to -18% to -25%.'
 *
 * Both fields were string constants, identical on every load for every book,
 * sitting directly beside the tickers the user actually holds.
 *
 * Two properties are asserted per file, and the second is the one that makes
 * the fix durable:
 *
 *   1. NO STATIC PROVENANCE — the field, its heading, the named holdings and
 *      the invented figures are gone from the SOURCE. A structural net, because
 *      a rendering test cannot see a constant that happens to agree with the
 *      payload.
 *   2. DATA-DRIVEN — the panel's text CHANGES when the underlying metric
 *      changes, and an absent metric renders an explicit not-measured state
 *      rather than a plausible number. Against the old code every one of these
 *      fails: there is no measured box to read at all.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import React from 'react';

const mocks = vi.hoisted(() => ({
  positions: [] as Record<string, unknown>[],
  fetchPortfolio: vi.fn().mockResolvedValue(undefined),
  updateLastUpdated: vi.fn(),
  getVolatilitySizing: vi.fn(),
  runStressTest: vi.fn(),
  apiGet: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock('@/lib/store', () => ({
  usePortfolioStore: () => ({
    positions: mocks.positions,
    fetchPortfolio: mocks.fetchPortfolio,
    setPortfolioSnapshot: vi.fn(),
    setPositionCount: vi.fn(),
    isLoading: false,
    error: null,
    totalValue: 0,
  }),
  useUIStore: Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: mocks.updateLastUpdated, liveDataMode: true }),
    { getState: () => ({ updateLastUpdated: mocks.updateLastUpdated }) }
  ),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getVolatilitySizing: mocks.getVolatilitySizing,
    runStressTest: mocks.runStressTest,
  } as Record<string, ReturnType<typeof vi.fn>>,
  portfolioApi: { rebalancePortfolio: vi.fn(), exportCSV: vi.fn(), getPortfolio: vi.fn() },
  default: { get: mocks.apiGet },
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [];
  mocks.apiGet.mockResolvedValue({ data: {} });
});

const VOL_PAGE = resolve(process.cwd(), 'src/app/dashboard/volatility-sizing/page.tsx');
const STRESS_PAGE = resolve(process.cwd(), 'src/app/dashboard/stress-testing/page.tsx');

/**
 * The measured box inside the open explainer panel.
 *
 * The card explainers render before the sizing response arrives and the position
 * TABLE renders only once it does, so the table's nine column explainers are
 * absent from a list taken too early. Waiting on a table header is what makes
 * the column panels addressable at all.
 */
async function allExplainerButtons() {
  await screen.findByText('Recommended Weight');
  return screen.findAllByRole('button', { name: 'Explainer info' });
}

async function closeExplainer() {
  fireEvent.click(screen.getByRole('button', { name: 'Close explainer' }));
  await waitFor(() => {
    expect(screen.queryByTestId('explainer-measured')).toBeNull();
  });
}

/**
 * The measured text of whichever panel names `marker`.
 *
 * Every `HelpBtn` on this page carries the same accessible name and the panels
 * that render conditionally shift the indices, so the panel under test is
 * located by what it SAYS rather than by position. Fails loudly when no panel
 * matches, which is itself the signal that a panel went missing.
 */
async function measuredOfPanel(marker: string): Promise<string> {
  const count = (await allExplainerButtons()).length;
  for (let index = 0; index < count; index++) {
    // Re-acquire the button every pass: opening and closing the Radix dialog
    // re-renders the table, so a node captured before the first click can be
    // detached by the time its turn comes.
    const buttons = await screen.findAllByRole('button', { name: 'Explainer info' });
    fireEvent.click(buttons[index]);
    const text = (await screen.findByTestId('explainer-measured')).textContent ?? '';
    if (text.includes(marker)) return text;
    await closeExplainer();
  }
  throw new Error(`no explainer panel reported ${marker}`);
}

// These routes are heavy to import under a parallel full-suite run, so each case
// carries an explicit timeout rather than relying on vitest's 5s default. These
// are load budgets, not relaxed assertions.
const PAGE_TIMEOUT = 30_000;

/** The `volatility_sizing` success payload, per `analytics.py:8215` / engine `:5264`. */
const SIZING_PAYLOAD = {
  current_weights: { 'AAA.NS': 0.6, 'BBB.NS': 0.4 },
  recommended_weights: { 'AAA.NS': 0.45, 'BBB.NS': 0.55 },
  trades: {
    'AAA.NS': {
      shares_delta: -120,
      amount: -60000,
      amount_currency: 'INR',
      sizing_price: 500,
      rounding_residual: 0,
      status: 'executable',
    },
    'BBB.NS': {
      shares_delta: 40,
      amount: 60000,
      amount_currency: 'INR',
      sizing_price: 1500,
      rounding_residual: 0,
      status: 'executable',
    },
  },
  target_volatility: 0.15,
  current_volatility: 0.1832,
  achieved_volatility: 0.1425,
  scale_factor: 0.9021,
  volatilities: { 'AAA.NS': 0.241, 'BBB.NS': 0.118 },
  volatility_sources: { 'AAA.NS': 'EWMA', 'BBB.NS': 'EWMA' },
  sizing_history: {
    model: 'EWMA',
    window_start: '2025-10-01',
    window_end: '2026-09-30',
    return_observations: 248,
    per_ticker_return_observations: { 'AAA.NS': 248, 'BBB.NS': 248 },
    min_return_observations: 2,
    max_return_observations: 248,
    latest_observation: '2026-09-30',
    minimum_observations_required: 60,
    meets_minimum_sample: true,
    minimum_sample_status: 'sufficient',
    tickers_below_minimum_sample: [],
  },
  universe_coverage: {
    requested_tickers: ['AAA.NS', 'BBB.NS'],
    available_tickers: ['AAA.NS', 'BBB.NS'],
    missing_tickers: [],
    requested_count: 2,
    available_count: 2,
  },
  data_status: 'complete',
  currency: 'INR',
  base_currency: 'INR',
  portfolio_value: 1_000_000,
  portfolio_value_currency: 'INR',
};

describe('volatility-sizing — the panel moves with the metric', () => {
  it('renders the risk-budget panel from the response, and changes when the metric changes', async () => {
    const { default: VolatilitySizingPage } = await import(
      '@/app/dashboard/volatility-sizing/page'
    );

    mocks.getVolatilitySizing.mockResolvedValue(SIZING_PAYLOAD);
    const first = render(<VolatilitySizingPage />);
    const before = await measuredOfPanel('Risk budget requested');
    // The requested budget, and the two volatilities the engine measured beside
    // it. The withdrawn 'Standard equity risk budget benchmark: 15.0%' claimed
    // a standard this route does not publish.
    expect(before).toContain('Risk budget requested 15.00%');
    expect(before).toContain('Modelled portfolio volatility 18.32%');
    expect(before).toContain('Recommended book volatility 14.25%');
    first.unmount();

    // Same page, different metric. The panel must follow it.
    mocks.getVolatilitySizing.mockResolvedValue({
      ...SIZING_PAYLOAD,
      target_volatility: 0.25,
      current_volatility: 0.3111,
      achieved_volatility: 0.2402,
      scale_factor: 1.5502,
    });
    const second = render(<VolatilitySizingPage />);
    const after = await measuredOfPanel('Risk budget requested');
    expect(after).toContain('Risk budget requested 25.00%');
    expect(after).toContain('Modelled portfolio volatility 31.11%');
    expect(after).toContain('Recommended book volatility 24.02%');
    expect(after).not.toBe(before);
    second.unmount();
  }, PAGE_TIMEOUT);

  it('says "Not measured" for a withheld metric instead of the invented 15.0% benchmark', async () => {
    const { default: VolatilitySizingPage } = await import(
      '@/app/dashboard/volatility-sizing/page'
    );
    mocks.getVolatilitySizing.mockResolvedValue({
      ...SIZING_PAYLOAD,
      current_volatility: null,
      achieved_volatility: null,
      scale_factor: null as unknown as number,
    });

    render(<VolatilitySizingPage />);
    // The panel whose withdrawn benchmark read "Ideally aligned within ±1.0% of
    // your target volatility" — an alignment tolerance no route publishes.
    // With both volatilities withheld its only line is the reason.
    const measured = await measuredOfPanel('published no portfolio volatility');

    expect(measured).toContain('Not measured');
    // The withdrawn value is not backfilled with the constant the old
    // benchmark string printed for every book in the app.
    expect(measured).not.toContain('Standard equity risk budget');
    expect(measured).not.toContain('15.0% annualized');
    expect(measured).not.toContain('Ideally aligned');
    expect(measured).not.toContain('±1.0%');
    // Nor coerced into a plausible 0%: the withheld state renders no number.
    expect(measured).not.toMatch(/\d+\.\d+%/);
  }, PAGE_TIMEOUT);

  it('renders the recommended-weight panel with the measured volatility, and no named holdings', async () => {
    const { default: VolatilitySizingPage } = await import(
      '@/app/dashboard/volatility-sizing/page'
    );
    mocks.getVolatilitySizing.mockResolvedValue(SIZING_PAYLOAD);

    render(<VolatilitySizingPage />);
    // The column explainer: the panel that used to read "Positions with low
    // volatility (e.g. NIFTYIETF, CIPLA) receive higher weights".
    const measured = await measuredOfPanel('Measured annualized volatility');

    expect(measured).toContain('Measured annualized volatility 2 of 2 positions');
    // The four real holdings the old copy named, and the fabricated benchmark
    // numbers, are gone from the rendered panel.
    for (const fabrication of [
      'NIFTYIETF',
      'CIPLA',
      'ELECTCAST',
      'ARROWGREEN',
      'Quantitative Guideline',
      'Standard equity risk budget',
    ]) {
      expect(measured).not.toContain(fabrication);
    }
  }, PAGE_TIMEOUT);

  it('reads the model panel off sizing_history, so it moves with the model', async () => {
    const { default: VolatilitySizingPage } = await import(
      '@/app/dashboard/volatility-sizing/page'
    );

    mocks.getVolatilitySizing.mockResolvedValue(SIZING_PAYLOAD);
    const first = render(<VolatilitySizingPage />);
    const before = await measuredOfPanel('Model EWMA');
    expect(before).toContain('248 return observations');
    expect(before).toContain('2025-10-01');
    first.unmount();

    mocks.getVolatilitySizing.mockResolvedValue({
      ...SIZING_PAYLOAD,
      sizing_history: {
        ...SIZING_PAYLOAD.sizing_history,
        model: 'GARCH',
        return_observations: 133,
      },
    });
    const second = render(<VolatilitySizingPage />);
    const after = await measuredOfPanel('Model GARCH');
    expect(after).toContain('Model GARCH');
    expect(after).toContain('133 return observations');
    expect(after).not.toBe(before);
    second.unmount();
  }, PAGE_TIMEOUT);

  /**
   * The structural net. A rendering test cannot see a constant that happens to
   * agree with the payload, and these two strings were identical for every
   * book on every load — so the source itself has to be asserted.
   */
  it('carries no benchmark field, no third-label heading, and no named holdings', () => {
    const src = readFileSync(VOL_PAGE, 'utf8');

    // The carrier itself.
    expect(src).not.toContain('benchmark?:');
    expect(src).not.toContain('info.benchmark');
    // The third label for it.
    expect(src).not.toContain('Quantitative Guideline:');
    // The two invented figures, verbatim.
    expect(src).not.toContain('Standard equity risk budget');
    expect(src).not.toContain('15.0% annualized volatility');
    expect(src).not.toContain('Ideally aligned within');
    // The four real holdings named as low/high-volatility examples.
    for (const holding of ['NIFTYIETF', 'CIPLA', 'ELECTCAST', 'ARROWGREEN']) {
      expect(src).not.toContain(holding);
    }
    // The data-driven box is present and keyed the way the five cleared pages
    // key theirs, so a future carrier cannot quietly return under a new label.
    expect(src).toContain('data-testid="explainer-measured"');
    expect(src).toContain('Not measured —');
  });
});

// ---------------------------------------------------------------------------
// stress-testing — the market-crash explainer named two real holdings beside a
// drawdown band the engine never published. `analytics_engine.py:4311-4319`
// publishes `market_shock: -0.35`, a `sector_elasticity_table` and a per-ticker
// `volatility_adjustment`; the -18% to -25% band and the 24-month recovery were
// page prose. The recovery figure IS published (`recovery_time`, basis
// `configured_recovery_estimate_not_simulated`) and rendered on the card, so the
// copy points at the card rather than restating the number.
// ---------------------------------------------------------------------------
const STRESS_PAYLOAD = {
  scenario: 'Market Crash',
  scenario_description: 'engine-authored: Market Crash',
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
    sector_elasticity_table: { Utilities: 0.5, Healthcare: 0.55, 'Consumer Cyclical': 1.55 },
    sector_elasticity_basis: 'static_configured_table',
    position_impact_clip: [-0.75, -0.02],
    position_impact_clip_basis: 'configured_bounds_not_simulated',
    unclassified_bucket_member_count: 2,
    volatility_adjustment: {
      basis: 'measured_annualized_volatility_over_reference',
      reference_annualized_volatility: 0.22,
    },
  },
  methodology: 'Deterministic factor shock proxy; no path sampling and no simulation.',
};

describe('stress-testing — the market-crash explainer claims nothing about this book', () => {
  beforeEach(() => {
    mocks.positions = [
      { id: 1, ticker: 'AAA.NS', weight: 1, quantity: 1, last_price: 100, market_value: 100 },
    ];
    mocks.runStressTest.mockResolvedValue(STRESS_PAYLOAD);
  });

  it('names no holdings and no unpublished drawdown band in the market-crash panel', async () => {
    const { default: StressTestingPage } = await import('@/app/dashboard/stress-testing/page');
    render(<StressTestingPage />);

    // Open the market-crash explainer. This page's `HelpBtn` is named "Help",
    // not "Explainer info", so the panels are found by accessible name here.
    const buttons = await screen.findAllByRole('button', { name: 'Help' });
    let panelText = '';
    for (const button of buttons) {
      fireEvent.click(button);
      const dialog = await screen.findByRole('dialog');
      if (dialog.textContent?.includes('Market Crash / 2008 Financial Crisis Scenario')) {
        panelText = dialog.textContent ?? '';
        break;
      }
      fireEvent.click(screen.getByRole('button', { name: 'Close' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    }

    expect(panelText).not.toBe('');
    expect(panelText).toContain('2008 Financial Crisis Scenario');

    // The two real holdings and the band that was attached to them.
    for (const fabrication of ['NTPC', 'CIPLA', '-18% to -25%', '-40% and -50%']) {
      expect(panelText).not.toContain(fabrication);
    }
    // The recovery duration restated as prose; the card carries the published
    // figure and its own basis string.
    expect(panelText).not.toContain('approximately 24 months');
    expect(panelText).toContain('configured month estimate');
  }, PAGE_TIMEOUT);

  /**
   * The structural net, for the same reason: the withdrawn strings were
   * constants that agreed with the payload's `recovery_time: 24`, so a
   * rendering test alone cannot see them.
   */
  it('the source carries no named holdings and no invented drawdown band', () => {
    const src = readFileSync(STRESS_PAGE, 'utf8');

    expect(src).not.toContain('NTPC');
    expect(src).not.toContain('CIPLA');
    expect(src).not.toContain('-18% to -25%');
    expect(src).not.toContain('between -40% and -50%');
    expect(src).not.toContain('approximately 24 months');
    // The rule the page's own `howToInterpret` now asserts survives, so this is
    // a deletion of the claims rather than of the panel.
    expect(src).toContain('sector_elasticity_table');
  });

  it('renders the published recovery figure on the card, and it moves with the payload', async () => {
    const { default: StressTestingPage } = await import('@/app/dashboard/stress-testing/page');

    const first = render(<StressTestingPage />);
    await screen.findByTestId('stress-basis-disclosure');
    // `recovery_time` is rendered as `${value} months` inside one span, so the
    // node carries the whole string rather than the bare number.
    await waitFor(() =>
      expect(screen.getAllByText('24 months').length).toBeGreaterThan(0)
    );
    first.unmount();

    // The same page with a different configured recovery. The card must follow
    // the payload; the explainer prose no longer asserts a month count at all.
    mocks.runStressTest.mockResolvedValue({ ...STRESS_PAYLOAD, recovery_time: 7 });
    const second = render(<StressTestingPage />);
    await screen.findByTestId('stress-basis-disclosure');
    await waitFor(() => expect(screen.getAllByText('7 months').length).toBeGreaterThan(0));
    expect(screen.queryByText('24 months')).toBeNull();
    second.unmount();
  }, PAGE_TIMEOUT);
});
