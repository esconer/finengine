/**
 * A modal is a promise: focus moves into it, Tab stays in it, and focus returns
 * to the control that opened it. Six dashboard modals declared
 * `aria-modal="true"` as a bare attribute on a `<div role="dialog">` and
 * implemented none of it — the first Tab keypress behind the overlay moved
 * focus into the page underneath, and closing dropped focus on `<body>`, so the
 * next Tab restarted from the top of the document. One of the six
 * (factor-exposure) declared not even the role, which is why it survived every
 * audit that grepped for `role="dialog"`.
 *
 * These assertions cover the two halves that were previously unobservable:
 * where focus is *after* opening, and where it is *after* closing. Nothing
 * else in `src/test/` reads `document.activeElement`, so this file is the only
 * thing standing between this migration and the defect coming back.
 *
 * Escape is fired on `document`, not `window`: Radix listens on `document`,
 * and a `window` dispatch never reaches it.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  getForecastRisk: vi.fn(),
  getFactorExposure: vi.fn(),
  getConcentrationMetrics: vi.fn(),
  getLiquidityMetrics: vi.fn(),
  runStressTest: vi.fn(),
  getFullProfile: vi.fn(),
  getShareholding: vi.fn(),
  getConcalls: vi.fn(),
  getAiMemoPrompt: vi.fn(),
  getFinancialStatements: vi.fn(),
  fetchPortfolio: vi.fn(),
  getPortfolio: vi.fn(),
  getTearSheet: vi.fn(),
  getVolatilitySizing: vi.fn(),
  rebalancePortfolio: vi.fn(),
  getRegime: vi.fn(),
  getRiskContribution: vi.fn(),
  // risk-studio is a COMPOSITE of four raw `apiClient.get` calls rather than an
  // `analyticsApi` method, so it needs the module's default export mocked too.
  apiClientGet: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getForecastRisk: mocks.getForecastRisk,
    getFactorExposure: mocks.getFactorExposure,
    getConcentrationMetrics: mocks.getConcentrationMetrics,
    getLiquidityMetrics: mocks.getLiquidityMetrics,
    runStressTest: mocks.runStressTest,
    getTearSheet: mocks.getTearSheet,
    getVolatilitySizing: mocks.getVolatilitySizing,
    getRegime: mocks.getRegime,
    getRiskContribution: mocks.getRiskContribution,
  },
  default: { get: mocks.apiClientGet },
  portfolioApi: {
    getPortfolio: mocks.getPortfolio,
    rebalancePortfolio: mocks.rebalancePortfolio,
  },
  equityResearchApi: {
    getFullProfile: mocks.getFullProfile,
    getShareholding: mocks.getShareholding,
    getConcalls: mocks.getConcalls,
    getAiMemoPrompt: mocks.getAiMemoPrompt,
    getAiForensicPrompt: vi.fn(),
    downloadExcelModel: vi.fn(),
  },
  companyDataApi: { getFinancialStatements: mocks.getFinancialStatements },
}));

const positions = [
  { ticker: 'AAA.NS', weight: 0.6, quantity: 10, last_price: 100, market_value: 600, sector: 'Bank' },
  { ticker: 'BBB.NS', weight: 0.4, quantity: 5, last_price: 200, market_value: 400, sector: 'Auto' },
];

vi.mock('@/lib/store', () => {
  const useUIStore = Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }),
    { getState: () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }) },
  );
  return {
    usePortfolioStore: () => ({
      positions,
      fetchPortfolio: mocks.fetchPortfolio,
      isLoading: false,
      error: null,
      totalValue: 1000,
      currency: 'INR',
      setCurrency: vi.fn(),
    }),
    useUIStore,
  };
});

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(''),
  usePathname: () => '/dashboard/forecast-risk',
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const profile = {
  symbol: 'RELIANCE',
  ticker: 'RELIANCE.NS',
  name: 'Reliance Industries Limited',
  sector: 'Energy',
  industry_group: 'Oil & Gas',
  industry: 'Refining',
  sub_industry: 'Integrated',
  indices: ['NIFTY 50'],
  current_price: 2900.0,
  market_cap_cr: 1900000.0,
  stock_pe: 24.5,
  roce: 16.2,
  roe: 14.5,
  book_value: 1200.0,
  dividend_yield: 0.4,
  custom_ratios: {
    piotroski_score: 7,
    graham_number: 3250.0,
    graham_upside_pct: 12.0,
    enterprise_value_cr: 1950000.0,
    ev_to_ebitda: 12.4,
    interest_coverage: 8.5,
    cfo_to_pat_ratio: 1.15,
  },
  cons: [],
  pros: [],
  peers: [],
  concall_count: 0,
  annual_reports: [],
  credit_ratings: [],
};

/**
 * Each case dynamically imports and renders a whole dashboard page, which
 * transforms the module and mounts recharts. Under a full-suite run that can
 * outlast vitest's default 5s budget without anything being wrong.
 */
const PAGE_TIMEOUT = 20_000;

/**
 * Opens `opener` and asserts focus landed inside the dialog; closes with
 * Escape and asserts focus went back to the opener.
 *
 * The "focus is inside" half is asserted as containment rather than identity:
 * Radix autofocuses the first *tabbable* descendant (the close button), not the
 * panel itself, so `activeElement === dialog` is the wrong expectation even when
 * the behaviour is correct. What matters is that focus is inside the modal and
 * nowhere else.
 */
const assertFocusIsManaged = async (opener: HTMLElement) => {
  // jsdom does not focus on click the way a browser does, and Radix restores to
  // whatever was focused at mount time — so give it the real-browser starting
  // state explicitly.
  opener.focus();
  expect(document.activeElement).toBe(opener);

  fireEvent.click(opener);
  const dialog = await screen.findByRole('dialog');

  // Modality. Radix does NOT set `aria-modal` — it enforces the same promise
  // by marking everything outside the dialog `aria-hidden`, which is the
  // mechanism `aria-modal="true"` emulates. Assert the effect, not the
  // attribute. factor-exposure's panel had neither, and it was not portalled,
  // so it escaped every audit that grepped for `role="dialog"`.
  expect(dialog).toHaveAccessibleName();
  expect(document.body.firstElementChild).toHaveAttribute('aria-hidden', 'true');

  // RED without a focus trap: focus is still on the opener behind the overlay.
  expect(dialog.contains(document.activeElement)).toBe(true);
  expect(document.activeElement).not.toBe(opener);

  fireEvent.keyDown(document, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

  await waitFor(() => expect(document.activeElement).toBe(opener));
};

/** The first `<button>` named `name` on a page that ships several. */
const firstNamedButton = async (name: string): Promise<HTMLElement> => {
  const buttons = await screen.findAllByRole('button', { name });
  return buttons[0] as HTMLElement;
};

describe('hand-rolled dashboard modals manage focus (Radix Dialog contract)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchPortfolio.mockResolvedValue(undefined);
    mocks.getForecastRisk.mockResolvedValue({
      model: 'garch',
      horizon: 10,
      portfolio: {},
      positions: { 'AAA.NS': { volatility_forecast: 0.42, var_forecast: -0.031 } },
      latest_observation_date: '2025-12-31',
    });
    mocks.getFactorExposure.mockResolvedValue({
      portfolio: { alpha: 0.0004, annualized_alpha: 0.1, market: 1.05 },
      r_squared: 0.42,
      positions: { 'AAA.NS': { market: 1.45, alpha: 0.0006, is_limited_history: false } },
      latest_observation_date: '2025-12-31',
    });
    mocks.getConcentrationMetrics.mockResolvedValue({
      positions: positions.map((p) => ({
        ticker: p.ticker,
        weight: p.weight,
        hhi_contribution: 0.18,
        effective_positions: 4.2,
      })),
      latest_observation_date: '2025-12-31',
    });
    mocks.getLiquidityMetrics.mockResolvedValue({
      overall_score: 8.2,
      liquidation_time_days: '1-2',
      risk_level: 'Low',
      by_position: {
        'AAA.NS': {
          score: 8.5,
          category: 'High',
          avg_volume: 5000000,
          avg_turnover: 1000000000,
          market_cap: 1000000000000,
          spread: 0.0004,
          liquidation_days: '1-2',
        },
      },
      volume_stats: {
        avg_volume: 5000000,
        total_portfolio_volume: 5000000,
        high_volume_pct: 100,
        medium_volume_pct: 0,
        low_volume_pct: 0,
      },
    });
    mocks.runStressTest.mockResolvedValue({
      scenario: 'Market Crash',
      max_drawdown: -0.08,
      portfolio_impact: -0.12,
      position_impacts: { 'AAA.NS': -0.185 },
      recovery_time: 3,
      confidence_level: 0.8,
      latest_observation_date: '2025-12-31',
    });
    mocks.getFullProfile.mockResolvedValue(profile);
    mocks.getShareholding.mockResolvedValue({ ticker: 'RELIANCE.NS', quarterly: {}, yearly: {} });
    mocks.getConcalls.mockResolvedValue({ ticker: 'RELIANCE.NS', count: 0, concalls: [] });
    mocks.getAiMemoPrompt.mockResolvedValue({ prompt: 'prompt body' });
    mocks.getFinancialStatements.mockResolvedValue({});

    // portfolio/manage renders its rows from `portfolioApi.getPortfolio`; the
    // store mock above supplies the positions it edits.
    mocks.getPortfolio.mockResolvedValue({
      positions,
      total_value: 1000,
      total_positions: 2,
      total_weight: 1,
      sectors: [{ sector: 'Bank', value: 0.6 }],
      currency: 'INR',
    });
    // volatility-sizing: a fully funded target, so `Execute Rebalance` is live.
    mocks.getVolatilitySizing.mockResolvedValue({
      current_weights: { 'AAA.NS': 0.6, 'BBB.NS': 0.4 },
      recommended_weights: { 'AAA.NS': 0.55, 'BBB.NS': 0.45 },
      trades: {
        'AAA.NS': { shares_delta: -5, amount: -5000, status: 'executable', reason: null },
        'BBB.NS': { shares_delta: 5, amount: 5000, status: 'executable', reason: null },
      },
      target_volatility: 0.15,
      current_volatility: 0.18,
      volatilities: { 'AAA.NS': 0.22, 'BBB.NS': 0.14 },
      execution: {
        normalization_rule: 'divide_all_legs_by_gross_exposure',
        normalization_mode: 'fully_funded',
        weights_normalized: false,
        gross_exposure: 1.0,
        net_cash_weight: 0.0,
        financing_required: false,
        execution_eligible: true,
        block_reasons: [],
        block_reason: null,
      },
      data_status: 'available',
    });
    mocks.rebalancePortfolio.mockResolvedValue({
      success: true,
      dry_run: true,
      message: 'Simulation completed',
      total_portfolio_value: 1000,
      total_buy_inr: 500,
      total_sell_inr: 500,
    });
    mocks.getTearSheet.mockResolvedValue({
      window: { start: '2025-09-08', end: '2026-09-07' },
      holdings: { 'AAA.NS': 1 },
      metrics: { total_return: 0.2648, max_drawdown: -0.1424 },
      full_history: null,
      relative_vs_nifty: {},
      monthly_returns: {},
      underwater: [],
      methodology: 'test',
    });
    mocks.getRegime.mockResolvedValue({
      as_of: '2026-09-07',
      current_regime: 'Calm',
      stability_pct: 74.0,
      regime_probabilities: { Calm: 75, Bull: 13, Crisis: 12 },
      realtime_ewma_vol: 0.103,
      realtime_parkinson_vol: 0.112,
      states: [
        { regime: 'Calm', ann_ret: 0.046, ann_vol: 0.103, historical_days_pct: 75 },
        { regime: 'Bull', ann_ret: 0.183, ann_vol: 0.148, historical_days_pct: 13 },
        { regime: 'Crisis', ann_ret: -0.288, ann_vol: 0.193, historical_days_pct: 12 },
      ],
      recent_history: [
        { date: '2026-09-04', regime: 'Calm' },
        { date: '2026-09-05', regime: 'Calm' },
        { date: '2026-09-07', regime: 'Calm' },
      ],
      observations: 1500,
    });
    mocks.getRiskContribution.mockResolvedValue({
      window: { start: '2025-09-08', end: '2026-09-07' },
      portfolio_volatility_annualized: 0.182,
      portfolio_var_95_daily: -0.0091,
      portfolio_cvar_95_daily: -0.0142,
      positions: {
        volatility: { 'AAA.NS': 0.62, 'BBB.NS': 0.38 },
        cvar_tail: { 'AAA.NS': 0.71, 'BBB.NS': 0.29 },
      },
      sector_rollup: { volatility: { Bank: 0.6, Auto: 0.4 }, cvar_tail: { Bank: 0.66, Auto: 0.34 } },
      latest_observation_date: '2026-09-07',
    });
    // risk-studio reads four raw endpoints through `apiClient.get`; one shared
    // empty payload is enough because every figure it renders is null-guarded.
    mocks.apiClientGet.mockResolvedValue({ data: {} });
  });

  it('forecast-risk: the VaR explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/forecast-risk/page');
    render(<Page />);

    await assertFocusIsManaged(
      await screen.findByRole('button', { name: 'Learn about Value at Risk (VaR 95%)' })
    );
  }, PAGE_TIMEOUT);

  it('factor-exposure: the explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/factor-exposure/page');
    render(<Page />);

    await assertFocusIsManaged(await firstNamedButton('Help'));
  }, PAGE_TIMEOUT);

  it('concentration: the explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/concentration/page');
    render(<Page />);

    await assertFocusIsManaged(await firstNamedButton('Help'));
  }, PAGE_TIMEOUT);

  it('stress-testing: the explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/stress-testing/page');
    render(<Page />);

    await assertFocusIsManaged(await firstNamedButton('Help'));
  }, PAGE_TIMEOUT);

  it('liquidity: the explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/liquidity/page');
    render(<Page />);

    await assertFocusIsManaged(await firstNamedButton('Explainer info'));
  }, PAGE_TIMEOUT);

  it('equity-research: the AI prompt modal takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/equity-research/page');
    render(<Page />);

    await assertFocusIsManaged(await screen.findByRole('button', { name: 'AI Memo' }));
  }, PAGE_TIMEOUT);

  // `manage`'s confirm and tear-sheet's explainer are the two remaining
  // hand-rolled panels; both declared `aria-modal="true"` over markup that
  // implemented none of it.
  it('portfolio/manage: the delete confirm takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/portfolio/manage/page');
    render(<Page />);

    await assertFocusIsManaged(
      await screen.findByRole('button', { name: 'Delete AAA.NS' })
    );
  });

  it('dashboard/tear-sheet: the Total Return explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/tear-sheet/page');
    render(<Page />);

    await assertFocusIsManaged(await firstNamedButton('Explainer info'));
  }, PAGE_TIMEOUT);

  // volatility-sizing ships BOTH shapes: a per-column explainer and a two-mode
  // rebalance ticket. Neither trapped focus, and the ticket held a second,
  // independent `window` Escape path.
  it('volatility-sizing: the column explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/volatility-sizing/page');
    render(<Page />);

    await assertFocusIsManaged(await firstNamedButton('Explainer info'));
  }, PAGE_TIMEOUT);

  it('volatility-sizing: the rebalance ticket takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/volatility-sizing/page');
    render(<Page />);

    await assertFocusIsManaged(
      await screen.findByRole('button', { name: 'Execute Rebalance' })
    );
  }, PAGE_TIMEOUT);

  // The last three hand-rolled explainers. None of them declared even
  // `role="dialog"`, so each one was invisible to every grep-based audit this
  // project owns — the 57-rule export gate, the formatter net, the `row.original`
  // source net and the `role="dialog"` sweep that found the previous batch.
  it('regime: the explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/regime/page');
    render(<Page />);

    await assertFocusIsManaged(await firstNamedButton('Explainer info'));
  }, PAGE_TIMEOUT);

  it('risk-contribution: the explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/risk-contribution/page');
    render(<Page />);

    await assertFocusIsManaged(await firstNamedButton('Explainer info'));
  }, PAGE_TIMEOUT);

  it('risk-studio: the explainer takes focus and gives it back', async () => {
    const { default: Page } = await import('@/app/dashboard/risk-studio/page');
    render(<Page />);

    await assertFocusIsManaged(await firstNamedButton('Explainer info'));
  }, PAGE_TIMEOUT);
});
