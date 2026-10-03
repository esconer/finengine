/**
 * A refused HHI renders `N/A`; a MEASURED zero keeps its number.
 *
 * `get_concentration_metrics` publishes `herfindahl_index: None` for a book with
 * no holdings — the route's own empty branch, and `_empty_concentration()` in
 * the engine, which the route's MEASURED branch still forwards through
 * `.get("herfindahl_index", 0.0)` (`.get` hands back the stored `None`, because
 * the key is present; the `0.0` default is dead). `0.0` was never a reachable
 * measurement: HHI = Σw² ≥ 1/n > 0 for every non-empty book.
 *
 * The page's Herfindahl card tested it with `!== undefined`, and `null !==
 * undefined` is `true` — so a refusal walked into the MEASURED branch and was
 * formatted. The rendered string happens to be `N/A` either way, because
 * `formatRatio` opens with its own `value === null` check; what the wrong
 * operator removes is the SITE's own refusal, which is the only thing standing
 * between a null and a formatter that assumes `number`.
 *
 * So the null cases here are a rendering contract, and the MEASURED-ZERO cases
 * are the ones that catch an over-broad fix: `0` is falsy, and a single-holding
 * book measures `diversification_score: 0.0`, which the repo's own invariant
 * requires to render as 0% — never `N/A`. A `score && …` or `score || …`
 * rewrite passes every null case below and erases every real zero.
 *
 * The source-pattern half (no `!== undefined`, no truthiness guard) is in
 * `unit/concentration-null-guards.test.ts`.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  positions: [] as Record<string, unknown>[],
  getConcentrationMetrics: vi.fn(),
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
    fetchPortfolio: vi.fn().mockResolvedValue(undefined),
    isLoading: false,
    error: null,
    totalValue: 30000,
  }),
  useUIStore: Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: vi.fn(), liveDataMode: true }),
    { getState: () => ({ updateLastUpdated: vi.fn() }) }
  ),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: { getConcentrationMetrics: mocks.getConcentrationMetrics },
  portfolioApi: {},
  default: { get: vi.fn().mockResolvedValue({ data: {} }) },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.positions = [];
});

/** One holding at full weight: HHI measures exactly 1.0 and the score 0.0. */
const holding = (ticker: string) => ({
  id: 1,
  ticker,
  weight: 1,
  quantity: 10,
  buy_price: 1500,
  last_price: 1500,
  market_value: 15000,
  sector: 'IT',
});

/**
 * Serves one concentration payload and renders the page against `positions`.
 * The module is imported lazily so each case pays the module cost on its own
 * budget rather than the file's first-import budget (same note in
 * `AbsentValueRendering.test.tsx`).
 */
const renderPage = async (
  payload: Record<string, unknown>,
  positions: Record<string, unknown>[],
): Promise<HTMLElement> => {
  mocks.positions = positions;
  mocks.getConcentrationMetrics.mockResolvedValue(payload);
  const { default: ConcentrationPage } = await import('@/app/dashboard/concentration/page');
  const { container } = render(<ConcentrationPage />);
  // Wait for the fetch to land AND for the loading skeleton to clear, so a card
  // is never asserted while it is still rendering its placeholder.
  await waitFor(() => {
    expect(screen.getByRole('heading', { name: 'Herfindahl Index' })).toBeDefined();
  });
  return container;
};

/** The `MetricCard` with this title, and the string it renders as its figure. */
const cardValue = (title: string): string => {
  const card = screen
    .getByRole('heading', { name: title })
    .closest('[data-testid="metric-card"]');
  expect(card, `no metric card titled "${title}"`).not.toBeNull();
  return card!.querySelector('p')?.textContent ?? '';
};

const RENDER_TIMEOUT = 60_000;

describe('concentration — a refused HHI is N/A, never a formatted null', () => {
  it('renders N/A on the Herfindahl card for a null payload', async () => {
    const container = await renderPage(
      {
        largest_position: 1,
        top_3: 1,
        top_5: 1,
        top_10: 1,
        herfindahl_index: null,
        effective_positions: 1,
        diversification_score: 0,
        diversification_ratio: 1,
        by_weight: { 'A.NS': 1 },
        by_sector: { it: 1 },
      },
      [holding('A.NS')],
    );

    // BEFORE the fix this branch was taken (`null !== undefined` is `true`) and
    // called `formatRatio(null)`; it returned 'N/A' only because `formatRatio`
    // opens with its own null check. The site now states the refusal itself.
    expect(cardValue('Herfindahl Index')).toBe('N/A');
    // The failure the wrong operator invites: a null reaching a `toFixed()`.
    expect(container.textContent).not.toContain('NaN');
  }, RENDER_TIMEOUT);

  it('states HHI = N/A in the risk sentence instead of a number', async () => {
    await renderPage(
      {
        largest_position: 1,
        top_3: 1,
        top_5: 1,
        top_10: 1,
        herfindahl_index: null,
        effective_positions: 1,
        diversification_score: 0,
        diversification_ratio: 1,
        by_weight: { 'A.NS': 1 },
        by_sector: { it: 1 },
      },
      [holding('A.NS')],
    );

    // The same field, read by a SIBLING that already guards correctly. It must
    // agree with the card: a page that says `HHI = 0.00` in its prose while its
    // own card says N/A has two answers to one measurement.
    expect(screen.getByText(/HHI = N\/A\)/)).toBeDefined();
  }, RENDER_TIMEOUT);

  it('does not claim the refusal is a well-diversified book', async () => {
    await renderPage(
      {
        largest_position: 1,
        top_3: 1,
        top_5: 1,
        top_10: 1,
        herfindahl_index: null,
        effective_positions: 1,
        diversification_score: 0,
        diversification_ratio: 1,
        by_weight: { 'A.NS': 1 },
        by_sector: { it: 1 },
      },
      [holding('A.NS')],
    );

    // The "Good Diversification" insight is gated on the index. With no
    // measurement there is nothing to call good, and calling it good is the
    // claim this whole change exists to stop making.
    expect(screen.queryByText('Good Diversification')).toBeNull();
  }, RENDER_TIMEOUT);
});

describe('concentration — a MEASURED zero keeps its number', () => {
  it('renders 0% diversification for a single-holding book, not N/A', async () => {
    // THE assertion that catches an over-broad fix. A one-holding book measures
    // `herfindahl_index: 1.0` and `diversification_score: 0.0`; the repo's own
    // invariant is that this renders strictly as 0%. A `score && …` guard, or a
    // `?? fallback` that stops at a falsy zero, passes every null case above and
    // turns this into N/A.
    await renderPage(
      {
        largest_position: 1,
        top_3: 1,
        top_5: 1,
        top_10: 1,
        herfindahl_index: 1,
        effective_positions: 1,
        diversification_score: 0,
        diversification_ratio: 1,
        by_weight: { 'A.NS': 1 },
        by_sector: { it: 1 },
      },
      [holding('A.NS')],
    );

    const hero = screen.getByText('Diversification Score:').parentElement!;
    expect(hero.textContent).toContain('0%');
    expect(hero.textContent).not.toContain('N/A');
    // The measured index itself is not erased by the same fix.
    expect(cardValue('Herfindahl Index')).toBe('1.00');
    // …and its measured value still drives the insight: HHI = 1.0 is the most
    // concentrated book there is, so the page must NOT call it good.
    expect(screen.queryByText('Good Diversification')).toBeNull();
  }, RENDER_TIMEOUT);

  it('renders a measured 0.0 diversification_score on a multi-holding book', async () => {
    // n = 1 short-circuits the score to 0.0 on the page, so it cannot tell a
    // `??` guard from a truthiness guard. n = 2 reads the PUBLISHED
    // `diversification_score`, which is 0.0 here — `0.0 ?? fallback` is 0.0,
    // `0.0 && fallback` is nothing at all.
    await renderPage(
      {
        largest_position: 0.8,
        top_3: 1,
        top_5: 1,
        top_10: 1,
        herfindahl_index: 0.68,
        effective_positions: 1.47,
        diversification_score: 0,
        diversification_ratio: 0.74,
        by_weight: { 'A.NS': 0.8, 'B.NS': 0.2 },
        by_sector: { it: 1 },
      },
      [
        { ...holding('A.NS'), weight: 0.8, market_value: 24000 },
        { ...holding('B.NS'), id: 2, weight: 0.2, market_value: 6000 },
      ],
    );

    const hero = screen.getByText('Diversification Score:').parentElement!;
    expect(hero.textContent).toContain('0%');
    expect(hero.textContent).not.toContain('N/A');
    // …while the measured index and effective count keep their own numbers.
    expect(cardValue('Herfindahl Index')).toBe('0.68');
  }, RENDER_TIMEOUT);

  it('does not drop a measured herfindahl_index of 0 to a truthiness guard', async () => {
    // HHI = Σw² ≥ 1/n > 0 for every non-empty book, so the engine cannot
    // publish 0 — which is exactly why this pins the GUARD and not a reachable
    // product state: `field && …` cannot tell that refusal from a measurement,
    // and the day a leg measures 0 the measurement would silently vanish.
    await renderPage(
      {
        largest_position: 0.5,
        top_3: 1,
        top_5: 1,
        top_10: 1,
        herfindahl_index: 0,
        effective_positions: 0,
        diversification_score: 0,
        diversification_ratio: 1,
        by_weight: { 'A.NS': 0.5, 'B.NS': 0.5 },
        by_sector: { it: 1 },
      },
      [
        { ...holding('A.NS'), weight: 0.5, market_value: 15000 },
        { ...holding('B.NS'), id: 2, weight: 0.5, market_value: 15000 },
      ],
    );

    // RED on the shipped code: `concentrationData?.herfindahl_index && …` is
    // falsy at 0, so the measured branch was never reached.
    expect(cardValue('Herfindahl Index')).toBe('0.00');
    expect(screen.getByText('Good Diversification')).toBeDefined();
  }, RENDER_TIMEOUT);
});

describe('concentration — an unchanged measured book is untouched', () => {
  it('still renders the index, the effective count and the published score', async () => {
    const container = await renderPage(
      {
        largest_position: 0.4,
        top_3: 0.8,
        top_5: 1,
        top_10: 1,
        herfindahl_index: 0.52,
        effective_positions: 1.92,
        diversification_score: 40,
        diversification_ratio: 0.96,
        by_weight: { 'A.NS': 0.4, 'B.NS': 0.4, 'C.NS': 0.2 },
        by_sector: { it: 1 },
      },
      [
        { ...holding('A.NS'), weight: 0.4, market_value: 12000 },
        { ...holding('B.NS'), id: 2, weight: 0.4, market_value: 12000 },
        { ...holding('C.NS'), id: 3, weight: 0.2, market_value: 6000 },
      ],
    );

    expect(cardValue('Herfindahl Index')).toBe('0.52');
    expect(cardValue('Effective Positions')).toBe('1.92');
    expect(screen.getByText('Diversification Score:').parentElement!.textContent).toContain('40%');
    expect(container.textContent).not.toContain('N/A%');
    // A MEASURED 0.52 is still above the 0.20 the insight is gated on, so the
    // page must keep withholding it. The negative control for the `!= null`
    // fix: widening the guard must not turn the insight on for everyone.
    expect(screen.queryByText('Good Diversification')).toBeNull();
  }, RENDER_TIMEOUT);

  it('still renders the good-diversification insight for a measured low index', async () => {
    // The other direction: `!= null` must not have broken the positive branch.
    // Ten equal holdings measure HHI = 1/10 = 0.10, comfortably under 0.20.
    await renderPage(
      {
        largest_position: 0.1,
        top_3: 0.3,
        top_5: 0.5,
        top_10: 1,
        herfindahl_index: 0.1,
        effective_positions: 10,
        diversification_score: 100,
        diversification_ratio: 1,
        by_weight: { 'A.NS': 0.1, 'B.NS': 0.1, 'C.NS': 0.1 },
        by_sector: { it: 1 },
      },
      [
        { ...holding('A.NS'), weight: 0.1, market_value: 3000 },
        { ...holding('B.NS'), id: 2, weight: 0.1, market_value: 3000 },
        { ...holding('C.NS'), id: 3, weight: 0.1, market_value: 3000 },
      ],
    );

    expect(screen.getByText('Good Diversification')).toBeDefined();
    expect(screen.getByText(/Herfindahl Index of 0\.10/)).toBeDefined();
    expect(screen.getByText('Diversification Score:').parentElement!.textContent).toContain('100%');
  }, RENDER_TIMEOUT);
});
