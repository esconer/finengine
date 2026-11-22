/**
 * The explainer panels are read off the response, not off a string constant.
 *
 * The defect this pins: every one of these five pages carried an
 * `ExplainerContent.benchmark` string and rendered it under a "Quantitative
 * Benchmark" heading ("Target Benchmark:" on `liquidity`). Three of those strings
 * named REAL HOLDINGS beside figures no route ever measured —
 *
 *   tear-sheet:82   'Current Portfolio: 1.26 vs NIFTY 50: -0.20.'
 *   tear-sheet:105  '28.51% indicates massive active outperformance …
 *                    (MCX, Motherson, Redington).'
 *   tear-sheet:175  'Check largest weights (Motherson 13.6%, JuniorBees 12.8%,
 *                    Midcap ETF 10.5%)…'
 *
 * — so a user read a fabricated return for their own book, next to the tickers
 * they actually hold. `risk-studio` had been partly defabricated by prefixing
 * `e.g.`, which is the softening that `remediation-09` did and why the finding
 * kept recurring: the string is still a constant, identical for every book on
 * every load.
 *
 * Two properties are asserted here, and the second is the one that makes the
 * fix durable:
 *
 *   1. NO STATIC PROVENANCE — the `benchmark` field and its heading are gone
 *      from all five sources, and so is every named-holding / invented-figure
 *      pair. A structural net, because a rendering test cannot see a constant
 *      that happens to agree with the payload.
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
  getTearSheet: vi.fn(),
  getRiskContribution: vi.fn(),
  getRegime: vi.fn(),
  getLiquidityMetrics: vi.fn(),
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
  analyticsApi: Object.assign(
    {
      getTearSheet: mocks.getTearSheet,
      getRiskContribution: mocks.getRiskContribution,
      getRegime: mocks.getRegime,
      getLiquidityMetrics: mocks.getLiquidityMetrics,
    } as Record<string, ReturnType<typeof vi.fn>>,
    {}
  ),
  portfolioApi: { rebalancePortfolio: vi.fn(), exportCSV: vi.fn(), getPortfolio: vi.fn() },
  default: { get: mocks.apiGet },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [];
  mocks.apiGet.mockResolvedValue({ data: {} });
});

/** The measured box inside the open explainer panel. */
async function measuredOf(buttonIndex: number): Promise<string> {
  const buttons = await screen.findAllByRole('button', { name: 'Explainer info' });
  fireEvent.click(buttons[buttonIndex]);
  const box = await screen.findByTestId('explainer-measured');
  return box.textContent ?? '';
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
 * Every `HelpBtn` on all five pages carries the same accessible name, and the
 * panels that render conditionally shift the indices, so the panels under test
 * are located by what they SAY rather than by position. Fails loudly when no
 * panel matches, which is itself the signal that a panel went missing.
 */
async function measuredOfPanel(marker: string): Promise<string> {
  const buttons = await screen.findAllByRole('button', { name: 'Explainer info' });
  for (const button of buttons) {
    fireEvent.click(button);
    const text = (await screen.findByTestId('explainer-measured')).textContent ?? '';
    if (text.includes(marker)) return text;
    await closeExplainer();
  }
  throw new Error(`no explainer panel reported ${marker}`);
}

// The heaviest of the five routes to import under a parallel full-suite run, so
// each case carries an explicit timeout rather than relying on vitest's 5s
// default. These are load budgets, not relaxed assertions.
const PAGE_TIMEOUT = 30_000;

// ---------------------------------------------------------------------------
// tear-sheet — the panel used to print "Current Portfolio: 1.26 vs NIFTY 50:
// -0.20." regardless of what the route returned.
// ---------------------------------------------------------------------------
const TEAR_SHEET_PAYLOAD = {
  window: { start: '2025-01-01', end: '2026-01-01' },
  holdings: { 'AAA.NS': 0.6, 'BBB.NS': 0.4 },
  metrics: {
    total_return: 0.11,
    cagr: 0.11,
    sharpe: 0.41,
    max_drawdown: -0.09,
    sortino: 0.5,
    calmar: 1.2,
    omega: 1.1,
    tail_ratio: 1.02,
    skew: 0.1,
    kurtosis: 2.0,
    volatility: 0.22,
    days: 250,
  },
  relative_vs_nifty: {
    beta_vs_nifty: 0.94,
    alpha_annualized: 0.031,
    benchmark_sharpe: 0.93,
    benchmark_volatility: 0.14,
  },
  monthly_returns: { '2026': { '1': 0.02, '2': -0.01 } },
  underwater: [{ date: '2026-01-02', drawdown: -0.09 }],
  methodology: 'test',
};

describe('tear-sheet — the explainer panel moves with the metric', () => {
  it('renders the Sharpe panel from the response, and changes when Sharpe changes', async () => {
    const { default: TearSheetPage } = await import('@/app/dashboard/tear-sheet/page');

    mocks.getTearSheet.mockResolvedValue(TEAR_SHEET_PAYLOAD);
    const first = render(<TearSheetPage />);
    const before = await measuredOf(2);
    expect(before).toContain('Portfolio Sharpe 0.41');
    expect(before).toContain('NIFTY 50 Sharpe 0.93');
    first.unmount();

    // Same page, different metric. The panel must follow it.
    mocks.getTearSheet.mockResolvedValue({
      ...TEAR_SHEET_PAYLOAD,
      metrics: { ...TEAR_SHEET_PAYLOAD.metrics, sharpe: 1.77 },
      relative_vs_nifty: { ...TEAR_SHEET_PAYLOAD.relative_vs_nifty, benchmark_sharpe: 0.28 },
    });
    const second = render(<TearSheetPage />);
    const after = await measuredOf(2);
    expect(after).toContain('Portfolio Sharpe 1.77');
    expect(after).toContain('NIFTY 50 Sharpe 0.28');
    expect(after).not.toBe(before);
    second.unmount();
  }, PAGE_TIMEOUT);

  it('says "Not measured" for a metric the route withheld, instead of a plausible number', async () => {
    const { default: TearSheetPage } = await import('@/app/dashboard/tear-sheet/page');
    mocks.getTearSheet.mockResolvedValue({
      ...TEAR_SHEET_PAYLOAD,
      metrics: { ...TEAR_SHEET_PAYLOAD.metrics, sharpe: null },
      relative_vs_nifty: {},
    });

    render(<TearSheetPage />);
    const measured = await measuredOf(2);

    expect(measured).toContain('Not measured');
    // The withdrawn value is not backfilled with the number the old constant
    // printed for every book in the app.
    expect(measured).not.toMatch(/1\.26/);
    expect(measured).not.toMatch(/-0\.20/);
  }, PAGE_TIMEOUT);

  it('renders the alpha panel with the measured alpha and no named holdings', async () => {
    const { default: TearSheetPage } = await import('@/app/dashboard/tear-sheet/page');
    mocks.getTearSheet.mockResolvedValue(TEAR_SHEET_PAYLOAD);

    render(<TearSheetPage />);
    // The alpha explainer: first the section heading's button, then the Alpha card's.
    const measured = await measuredOf(6);

    expect(measured).toContain('α (annualized) 3.10%');
    expect(measured).toContain('β vs NIFTY 50 0.94');
    for (const holding of ['MCX', 'Motherson', 'Redington', '28.51']) {
      expect(measured).not.toContain(holding);
    }
  }, PAGE_TIMEOUT);

  it('renders the weights panel from the payload\'s own holdings', async () => {
    const { default: TearSheetPage } = await import('@/app/dashboard/tear-sheet/page');
    mocks.getTearSheet.mockResolvedValue(TEAR_SHEET_PAYLOAD);

    render(<TearSheetPage />);
    const measured = await measuredOfPanel('BBB.NS 40.0%');

    expect(measured).toContain('AAA.NS 60.0%');
    expect(measured).toContain('BBB.NS 40.0%');
    // The old copy named three holdings and three weights of its own.
    for (const fabrication of ['Motherson', '13.6%', 'JuniorBees', '12.8%', 'Midcap ETF']) {
      expect(measured).not.toContain(fabrication);
    }
  }, PAGE_TIMEOUT);
});

// ---------------------------------------------------------------------------
// risk-contribution — the ratio explainer answered with named holdings
// ("Redington (1.70x)… JuniorBees (0.77x)… Cipla (0.44x)…") for a ratio this
// route cannot compute: it publishes risk shares, not capital weights.
// ---------------------------------------------------------------------------
const RISK_CONTRIBUTION_PAYLOAD = {
  window: { start: '2025-01-01', end: '2026-01-01' },
  positions: {
    volatility: { 'AAA.NS': 0.62, 'BBB.NS': 0.38 },
    cvar_tail: { 'AAA.NS': 0.71, 'BBB.NS': 0.29 },
  },
  sector_rollup: { volatility: { Tech: 1.0 }, cvar_tail: { Tech: 1.0 } },
  portfolio_volatility_annualized: 0.2123,
  portfolio_var_95_daily: -0.0177,
  portfolio_cvar_95_daily: -0.0253,
  methodology: 'Euler decomposition',
};

describe('risk-contribution — the panel follows the decomposition, or admits it cannot', () => {
  it('renders the volatility panel from the payload and changes with it', async () => {
    const { default: RiskContributionPage } = await import(
      '@/app/dashboard/risk-contribution/page'
    );

    mocks.getRiskContribution.mockResolvedValue(RISK_CONTRIBUTION_PAYLOAD);
    const first = render(<RiskContributionPage />);
    const before = await measuredOf(0);
    expect(before).toContain('Annualized portfolio volatility 21.23%');
    first.unmount();

    mocks.getRiskContribution.mockResolvedValue({
      ...RISK_CONTRIBUTION_PAYLOAD,
      portfolio_volatility_annualized: 0.0871,
    });
    const second = render(<RiskContributionPage />);
    const after = await measuredOf(0);
    expect(after).toContain('Annualized portfolio volatility 8.71%');
    expect(after).not.toBe(before);
    second.unmount();
  }, PAGE_TIMEOUT);

  it('says "Not measured" for the risk-to-weight ratio the route cannot compute', async () => {
    const { default: RiskContributionPage } = await import(
      '@/app/dashboard/risk-contribution/page'
    );
    mocks.getRiskContribution.mockResolvedValue(RISK_CONTRIBUTION_PAYLOAD);

    render(<RiskContributionPage />);
    // `risk_budgeting_ratio` is not wired to a HelpBtn at all today, so the walk
    // below usually finds nothing and the SOURCE carries the assertion: the
    // answer must not exist anywhere on the page. If a button is ever wired up,
    // the walk finds it and the same claim is checked on the rendering too.
    let ratioText: string | null = null;
    try {
      ratioText = await measuredOfPanel('capital weights');
    } catch {
      ratioText = null;
    }

    const source = readFileSync(
      resolve(process.cwd(), 'src', 'app', 'dashboard', 'risk-contribution', 'page.tsx'),
      'utf8'
    );
    expect(source).not.toMatch(/Redington|JuniorBees|Cipla|1\.70x|0\.77x|0\.44x/);
    expect(source).toContain('this route publishes risk shares, not the capital weights');

    if (ratioText !== null) {
      expect(ratioText).toContain('Not measured');
    }
  }, PAGE_TIMEOUT);
});

// ---------------------------------------------------------------------------
// risk-studio — four endpoints; the copula panel used to name "Motilal Oswal &
// JuniorBees: 0.335" and the correlation panels a fixed "0.158 < 0.382".
// ---------------------------------------------------------------------------
describe('risk-studio — the panel reads the composite, not a constant', () => {
  it('renders the portfolio-volatility panel from the response and changes with it', async () => {
    const { default: RiskStudioPage } = await import('@/app/dashboard/risk-studio/page');

    mocks.apiGet.mockImplementation((url: string) => {
      if (url.includes('risk-contribution')) {
        return Promise.resolve({
          data: {
            positions: { volatility: { 'AAA.NS': 1 }, cvar_tail: { 'AAA.NS': 1 } },
            portfolio_volatility_annualized: 0.2411,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const first = render(<RiskStudioPage />);
    const before = await measuredOf(0);
    expect(before).toContain('Annualized portfolio volatility 24.11%');
    first.unmount();

    mocks.apiGet.mockImplementation((url: string) => {
      if (url.includes('risk-contribution')) {
        return Promise.resolve({
          data: {
            positions: { volatility: { 'AAA.NS': 1 }, cvar_tail: { 'AAA.NS': 1 } },
            portfolio_volatility_annualized: 0.0904,
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    const second = render(<RiskStudioPage />);
    const after = await measuredOf(0);
    expect(after).toContain('Annualized portfolio volatility 9.04%');
    expect(after).not.toBe(before);
    second.unmount();
  }, PAGE_TIMEOUT);

  it('renders the copula panel from the highest MEASURED pair, never a named one', async () => {
    const { default: RiskStudioPage } = await import('@/app/dashboard/risk-studio/page');
    mocks.apiGet.mockImplementation((url: string) => {
      if (url.includes('tail-dependence')) {
        return Promise.resolve({
          data: {
            tail_dependence_matrix: {
              tickers: ['AAA.NS', 'BBB.NS', 'CCC.NS'],
              matrix: [
                [1, 0.112, null],
                [0.112, 1, 0.44],
                [null, 0.44, 1],
              ],
            },
          },
        });
      }
      if (url.includes('risk-contribution')) {
        return Promise.resolve({ data: { positions: { volatility: {}, cvar_tail: {} } } });
      }
      return Promise.resolve({ data: {} });
    });

    render(<RiskStudioPage />);
    const copulaText = await measuredOfPanel('BBB.NS / CCC.NS');

    expect(copulaText).toContain('λL 0.440');
    // The withheld pair must not be promoted into the reading.
    expect(copulaText).not.toContain('AAA.NS / CCC.NS');
    expect(copulaText).not.toMatch(/Motilal|JuniorBees|0\.335/);
  }, PAGE_TIMEOUT);

  it('renders the correlation panel from the measured average and threshold', async () => {
    const { default: RiskStudioPage } = await import('@/app/dashboard/risk-studio/page');
    mocks.apiGet.mockImplementation((url: string) => {
      if (url.includes('correlation-stability')) {
        return Promise.resolve({
          data: { current_avg_correlation: 0.61, historical_threshold_90th: 0.44 },
        });
      }
      return Promise.resolve({ data: { positions: { volatility: {}, cvar_tail: {} } } });
    });

    render(<RiskStudioPage />);
    const text = await measuredOfPanel('Avg pairwise correlation');

    expect(text).toContain('Avg pairwise correlation (60D) 0.610');
    expect(text).toContain('Historical 90th-percentile threshold 0.440');
    expect(text).not.toMatch(/0\.158|0\.382/);
  }, PAGE_TIMEOUT);
});

// ---------------------------------------------------------------------------
// regime — the panel used to publish a whole invented state distribution
// ("Crisis exhibits negative returns (-28.8%)… Calm … (4.6%, 10.3% vol)") and an
// invented portfolio ("+45.3%").
// ---------------------------------------------------------------------------
describe('regime — the panel renders the fitted states, not an invented distribution', () => {
  it('renders each fitted state from the payload and changes with it', async () => {
    const { default: RegimePage } = await import('@/app/dashboard/regime/page');

    mocks.getRegime.mockResolvedValue({
      as_of: '2026-10-01',
      current_regime: 'state_0',
      stability_pct: 74.0,
      regime_probabilities: { state_0: 62.5, state_1: 37.5 },
      states: [
        { regime: 'state_0', ann_ret: 0.046, ann_vol: 0.103, historical_days_pct: 60 },
        { regime: 'state_1', ann_ret: -0.288, ann_vol: 0.193, historical_days_pct: 40 },
      ],
      recent_history: [{ date: '2026-09-30', regime: 'state_0' }],
      observations: 100,
    });

    const first = render(<RegimePage />);
    const before = await measuredOf(0);
    expect(before).toContain('Active state State_0');
    expect(before).toContain('as of 2026-10-01');
    first.unmount();

    mocks.getRegime.mockResolvedValue({
      as_of: '2026-10-05',
      current_regime: 'state_2',
      stability_pct: 12.5,
      regime_probabilities: { state_2: 100 },
      states: [
        { regime: 'state_2', ann_ret: 0.301, ann_vol: 0.412, historical_days_pct: 5 },
        { regime: 'state_0', ann_ret: 0.01, ann_vol: 0.05, historical_days_pct: 95 },
      ],
      recent_history: [],
      observations: 250,
    });

    const second = render(<RegimePage />);
    const after = await measuredOf(0);
    expect(after).toContain('Active state State_2');
    expect(after).toContain('as of 2026-10-05');
    expect(after).not.toBe(before);
    second.unmount();
  }, PAGE_TIMEOUT);

  it('renders the three-state panel from the fitted states', async () => {
    const { default: RegimePage } = await import('@/app/dashboard/regime/page');
    mocks.getRegime.mockResolvedValue({
      as_of: '2026-10-01',
      current_regime: 'state_0',
      stability_pct: 74.0,
      states: [
        { regime: 'state_0', ann_ret: 0.046, ann_vol: 0.103, historical_days_pct: 60 },
        { regime: 'state_1', ann_ret: -0.288, ann_vol: 0.193, historical_days_pct: 40 },
      ],
      recent_history: [],
      observations: 100,
    });

    render(<RegimePage />);
    const text = await measuredOfPanel('State_1');

    expect(text).toContain('State_0 return 4.60% · vol 10.30%');
    expect(text).toContain('State_1 return -28.80% · vol 19.30%');
  }, PAGE_TIMEOUT);
});

// ---------------------------------------------------------------------------
// regime — an UNOCCUPIED state withholds `ann_ret` / `ann_vol` (null, not 0.0).
// `null * 100` renders "0.00%", which is the strongest number this table can
// print, for a state that captured no trading days — so the N/A has to be the
// N/A, and the route's own method token has to say why.
// ---------------------------------------------------------------------------
describe('regime — an unoccupied state is N/A, never a 0.00% return', () => {
  const payloadWith = (annRet: number | null, annVol: number | null) => ({
    as_of: '2026-10-01',
    current_regime: 'calm',
    stability_pct: 80.0,
    regime_probabilities: { calm: 100 },
    states: [
      {
        regime: 'calm',
        ann_ret: 0.04,
        ann_vol: 0.09,
        ann_ret_method: 'geometric_cagr_from_compounded_state_returns',
        historical_days_pct: 100,
      },
      {
        regime: 'crisis',
        ann_ret: annRet,
        ann_vol: annVol,
        ann_ret_method: 'no_observations',
        historical_days_pct: 0,
      },
    ],
    recent_history: [],
    observations: 100,
  });

  it('renders the withheld state as N/A with the route\'s method, not as 0.00%', async () => {
    const { default: RegimePage } = await import('@/app/dashboard/regime/page');
    mocks.getRegime.mockResolvedValue(payloadWith(null, null));

    render(<RegimePage />);
    await screen.findByText('The Three States the Model Found');

    const body = document.body.textContent ?? '';
    // The empty state reads N/A in both cells…
    expect(body).toContain('N/A');
    // …and says why, in the reader's words.
    expect(body).toContain('no observations — this state captured no trading days');
    // The measured state next to it is still a real number.
    expect(body).toContain('4.0%');
    // And nothing anywhere claims the empty state returned zero.
    expect(body).not.toMatch(/0\.00%/);
  }, PAGE_TIMEOUT);

  it('exports N/A for the empty state, never a "0.00%" cell in the CSV', async () => {
    const { default: RegimePage } = await import('@/app/dashboard/regime/page');
    mocks.getRegime.mockResolvedValue(payloadWith(null, null));

    const clicked: HTMLAnchorElement[] = [];
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this);
      });

    try {
      render(<RegimePage />);
      fireEvent.click(await screen.findByText('Export CSV'));

      expect(clicked).toHaveLength(1);
      const csv = decodeURIComponent(clicked[0].getAttribute('href')!);
      expect(csv).toContain('"Crisis",N/A,N/A,0.0%');
      expect(csv).not.toContain('"Crisis",0.00%');
    } finally {
      clickSpy.mockRestore();
    }
  }, PAGE_TIMEOUT);
});

// ---------------------------------------------------------------------------
// liquidity — the panel used to name holdings ("like NTPC, CIPLA, MOTHERSON…
// like ARROWGREEN or JKIL") under a "Target Benchmark" heading.
// ---------------------------------------------------------------------------
describe('liquidity — the panel ranks the payload\'s own positions', () => {
  it('renders the top scored positions from the payload and changes with it', async () => {
    const { default: LiquidityPage } = await import('@/app/dashboard/liquidity/page');

    mocks.getLiquidityMetrics.mockResolvedValue({
      overall_score: 7.4,
      liquidation_time_days: '3 days',
      risk_level: 'Medium',
      by_position: {
        'AAA.NS': { score: 9.1, category: 'High', liquidation_days: '1 day' },
        'BBB.NS': { score: 4.2, category: 'Low', liquidation_days: '9 days' },
      },
      volume_stats: {
        avg_volume: 1e6,
        total_portfolio_volume: 2e6,
        high_volume_pct: 0.5,
        medium_volume_pct: 0,
        low_volume_pct: 0.5,
      },
    });

    const first = render(<LiquidityPage />);
    const before = await measuredOf(4);
    expect(before).toContain('AAA.NS 9.1/10');
    first.unmount();

    mocks.getLiquidityMetrics.mockResolvedValue({
      overall_score: 3.1,
      liquidation_time_days: '19 days',
      risk_level: 'High',
      by_position: {
        'ZZZ.NS': { score: 1.4, category: 'Low', liquidation_days: '40 days' },
        'AAA.NS': { score: 9.1, category: 'High', liquidation_days: '1 day' },
      },
      volume_stats: {
        avg_volume: 1e6,
        total_portfolio_volume: 2e6,
        high_volume_pct: 0,
        medium_volume_pct: 0,
        low_volume_pct: 1,
      },
    });

    const second = render(<LiquidityPage />);
    const after = await measuredOf(4);
    expect(after).toContain('AAA.NS 9.1/10');
    expect(after).toContain('ZZZ.NS 1.4/10');
    expect(after).not.toBe(before);
    second.unmount();
  }, PAGE_TIMEOUT);
});

// ---------------------------------------------------------------------------
// The structural net. A rendering test cannot see a constant that happens to
// agree with the payload, so the removed shape is pinned at the source: no
// `benchmark` field, no "Quantitative Benchmark"/"Target Benchmark" heading, and
// none of the invented ticker+figure pairs anywhere in the five files.
// ---------------------------------------------------------------------------
const EXPLAINER_PAGES = [
  'tear-sheet',
  'risk-studio',
  'risk-contribution',
  'regime',
  'liquidity',
] as const;

describe('the five explainer pages carry no static provenance', () => {
  for (const page of EXPLAINER_PAGES) {
    it(`${page}: no benchmark field, no benchmark heading, no invented ticker+figure`, () => {
      const source = readFileSync(
        resolve(process.cwd(), 'src', 'app', 'dashboard', page, 'page.tsx'),
        'utf8'
      );

      // The field, and the render that read it.
      expect(source).not.toMatch(/benchmark\??:/);
      expect(source).not.toContain('info.benchmark');
      // The headings that gave the constants a home.
      expect(source).not.toContain('Quantitative Benchmark:');
      expect(source).not.toContain('Target Benchmark:');
      // The measured box replaced them.
      expect(source).toContain('explainer-measured');
      expect(source).toContain('Measured On This Book:');
      expect(source).toContain('Not measured');
    });
  }

  it('none of the five names a holding beside a figure any more', () => {
    // Every one of these shipped in a string that named real holdings next to a
    // figure no route measured.
    const namedHoldings = [
      /Motherson/i,
      /Redington/i,
      /JuniorBees/i,
      /Motilal/i,
      /Midcap ETF/i,
      /\bMCX\b/,
      /\bCipla\b/i,
      /\bCIPLA\b/,
      /\bNTPC\b/,
      /ARROWGREEN/i,
      /\bJKIL\b/i,
    ];
    // …and every one of those figures. Each was a number the page printed as
    // though the route had measured it for this book.
    const inventedFigures = [
      // tear-sheet
      '1.26',
      '-0.20',
      '-2.6%',
      '+28.4%',
      '25.75',
      '14.24',
      '25.98',
      '1.82',
      '1.06',
      // risk-studio
      '18.08',
      '0.158',
      '0.382',
      '-3.59%',
      '-3.99%',
      '0.335',
      '19.9%',
      '9.9%',
      '11.3%',
      // risk-contribution
      '-1.82%',
      '-2.53%',
      '13.6%',
      '1.70x',
      '0.77x',
      '0.44x',
      '28.4%',
      '23.1%',
      // regime
      '~75%',
      '~13%',
      '~12%',
      '74.0%',
      '10.3%',
      '15.5%',
      '-28.8%',
      '19.3%',
      '4.6%',
      '+45.3%',
    ];

    for (const page of EXPLAINER_PAGES) {
      const source = readFileSync(
        resolve(process.cwd(), 'src', 'app', 'dashboard', page, 'page.tsx'),
        'utf8'
      );
      for (const holding of namedHoldings) {
        expect(source, `${page}: ${holding}`).not.toMatch(holding);
      }
      for (const figure of inventedFigures) {
        expect(source, `${page}: ${figure}`).not.toContain(figure);
      }
    }
  });
});