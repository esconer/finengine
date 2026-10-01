/**
 * Every interactive control on these four pages must carry an accessible name.
 *
 * A `<label>` with no `htmlFor` whose control has no `id` names nothing, and a
 * placeholder is not a name (it vanishes on focus and several screen readers
 * skip it). An icon-only button with no text child and no `aria-label` is
 * announced as just "button".
 *
 * The wording is copied from what the tree already publishes, not invented:
 * `Edit ${ticker}` / `Delete ${ticker}` from the sibling edit/delete buttons,
 * `Close explainer` from volatility-sizing's identical explainer close, and
 * the visible label text for each form control.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  getFactorExposure: vi.fn(),
  getForecastRisk: vi.fn(),
  runStressTest: vi.fn(),
  getPortfolio: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    getFactorExposure: mocks.getFactorExposure,
    getForecastRisk: mocks.getForecastRisk,
    runStressTest: mocks.runStressTest,
    getForecastRiskByPortfolio: vi.fn(),
  },
  portfolioApi: {
    getPortfolio: mocks.getPortfolio,
    addPosition: vi.fn(),
    updatePosition: vi.fn(),
    deletePosition: vi.fn(),
    rebalancePortfolio: vi.fn(),
  },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

const positions = [
  { ticker: 'AAA.NS', weight: 0.6, quantity: 10, last_price: 100, market_value: 600, sector: 'Bank', name: 'Alpha Bank' },
  { ticker: 'BBB.NS', weight: 0.4, quantity: 5, last_price: 200, market_value: 400, sector: 'Auto', name: 'Beta Motors' },
];

vi.mock('@/lib/store', () => {
  const useUIStore = Object.assign(
    () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }),
    { getState: () => ({ lastUpdated: null, updateLastUpdated: vi.fn() }) },
  );
  return {
    usePortfolioStore: () => ({
      positions,
      fetchPortfolio: vi.fn().mockResolvedValue(undefined),
      isLoading: false,
      error: null,
      totalValue: 1000,
      currency: 'INR',
      setCurrency: vi.fn(),
    }),
    useUIStore,
  };
});

/**
 * The accessible name a control exposes: aria-label, aria-labelledby, the
 * text of its associated `<label>`, or its own text content. Returns '' when
 * the control names nothing at all.
 */
// `manage/page.tsx` renders inside `DashboardLayout` → `Sidebar`, which calls
// `usePathname()`. Outside a Next router that returns null and `isActiveRoute`
// dereferences it — a harness gap in the layout, not a defect in this page.
vi.mock('next/navigation', () => ({
  usePathname: () => '/portfolio/manage',
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const accessibleName = (el: Element, doc: Document): string => {
  const ariaLabel = el.getAttribute('aria-label');
  if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

  const labelledBy = el.getAttribute('aria-labelledby');
  if (labelledBy) {
    const text = labelledBy
      .split(/\s+/)
      .map((id) => doc.getElementById(id)?.textContent ?? '')
      .join(' ')
      .trim();
    if (text) return text;
  }

  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) {
    if (el.labels && el.labels.length > 0) {
      const text = Array.from(el.labels).map((l) => l.textContent ?? '').join(' ').trim();
      if (text) return text;
    }
  }

  const ownText = (el.textContent ?? '').trim();
  if (ownText) return ownText;

  // Last fallback in the accname computation: `title`. Weak (no visible name,
  // silent on touch) but it IS a name, so these controls are not unnamed.
  const title = el.getAttribute('title');
  if (title && title.trim()) return title.trim();

  return '';
};

/** Every control in the current document that has no accessible name. */
const unnamedControls = (): string[] => {
  const doc = document;
  return Array.from(doc.querySelectorAll('input, select, textarea, button, a[href]'))
    .filter((el) => {
      // A disabled control is not announced as interactive.
      if (el instanceof HTMLButtonElement && el.disabled) return false;
      return accessibleName(el, doc) === '';
    })
    .map((el) => `${el.tagName.toLowerCase()} :: ${el.outerHTML.slice(0, 220)}`);
};

describe('dashboard + portfolio controls carry accessible names', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getFactorExposure.mockResolvedValue({
      portfolio: { alpha: 0.0004, annualized_alpha: 0.1, market: 1.05 },
      r_squared: 0.42,
      positions: { 'AAA.NS': { market: 1.45, alpha: 0.0006, is_limited_history: false } },
      latest_observation_date: '2025-12-31',
    });
    mocks.getForecastRisk.mockResolvedValue({
      model: 'garch',
      horizon: 10,
      portfolio: {},
      positions: { 'AAA.NS': { volatility_forecast: 0.42, var_forecast: -0.031 } },
      latest_observation_date: '2025-12-31',
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
    mocks.getPortfolio.mockResolvedValue({
      positions,
      total_value: 1000,
      currency: 'INR',
    });
  });

  it('factor-exposure: no control is left unnamed', async () => {
    const { default: Page } = await import('@/app/dashboard/factor-exposure/page');
    render(<Page />);
    await screen.findByText('AAA.NS');
    expect(unnamedControls()).toEqual([]);
  });

  it('factor-exposure: the explainer close button has the sibling wording', async () => {
    const { default: Page } = await import('@/app/dashboard/factor-exposure/page');
    render(<Page />);

    // Opens the explainer modal, whose close button is the icon-only one.
    const help = await screen.findAllByRole('button', { name: 'Help' });
    expect(help.length).toBeGreaterThan(0);
    help[0].click();

    const close = await screen.findByRole('button', { name: 'Close explainer' });
    expect(close).toBeTruthy();
  });

  it('forecast-risk: the horizon slider is named and states its unit', async () => {
    const { default: Page } = await import('@/app/dashboard/forecast-risk/page');
    render(<Page />);

    const slider = await screen.findByRole('slider');
    // Named by the associated <label> via htmlFor/id, not by a placeholder.
    expect(accessibleName(slider, document)).toContain('Custom Horizon');
    expect(slider.getAttribute('id')).toBeTruthy();

    // A bare position ("1".."30") is not a value a screen reader can speak.
    expect(slider.getAttribute('aria-valuetext')).toBeTruthy();
    expect(slider.getAttribute('aria-valuetext')).toMatch(/\d+ days?/);
    // The value text must track the slider's own position, not a fixed string.
    const current = Number(slider.getAttribute('value'));
    expect(slider.getAttribute('aria-valuetext')).toContain(String(current));
  });

  it('forecast-risk: no control is left unnamed', async () => {
    const { default: Page } = await import('@/app/dashboard/forecast-risk/page');
    render(<Page />);
    await screen.findByRole('slider');
    expect(unnamedControls()).toEqual([]);
  });

  it('stress-testing: both custom-scenario fields are named by their labels', async () => {
    const { default: Page } = await import('@/app/dashboard/stress-testing/page');
    render(<Page />);

    // The custom form is collapsed until requested.
    const open = await screen.findByRole('button', { name: /Custom Shock/i });
    open.click();

    const name = await screen.findByLabelText(/Scenario Name/);
    expect(name.getAttribute('id')).toBeTruthy();
    expect(name).toHaveProperty('type', 'text');

    const shock = await screen.findByLabelText(/Market Shock/);
    expect(shock.getAttribute('id')).toBeTruthy();
    expect(shock).toHaveProperty('type', 'number');

    expect(unnamedControls()).toEqual([]);
  });

  it('portfolio/manage: no control is left unnamed', async () => {
    const { default: Page } = await import('@/app/portfolio/manage/page');
    render(<Page />);

    // Row actions carry the ticker, so two rows never announce identically.
    expect(await screen.findByRole('button', { name: 'Edit AAA.NS' })).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Delete AAA.NS' })).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Delete BBB.NS' })).toBeTruthy();

    // The search box is named; its placeholder is not.
    const search = screen.getByPlaceholderText(/Search by ticker/);
    expect(accessibleName(search, document)).toBeTruthy();

    expect(unnamedControls()).toEqual([]);
  });

  it('portfolio/manage: the inline-edit save and cancel buttons name their ticker', async () => {
    const { default: Page } = await import('@/app/portfolio/manage/page');
    render(<Page />);

    // Entering edit mode swaps Edit2 for Check+X; those two replace each other,
    // so the audit above (which runs in read mode) never saw them.
    fireEvent.click(await screen.findByRole('button', { name: 'Edit AAA.NS' }));

    expect(await screen.findByRole('button', { name: 'Save AAA.NS' })).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Cancel editing AAA.NS' })).toBeTruthy();

    // No unnamed BUTTON in edit mode either. The four edit-row `<input>`s are
    // deliberately excluded: they belong to the inline edit flow, which is out
    // of scope for this task (reported, not changed).
    const unnamedButtons = Array.from(document.querySelectorAll('button'))
      .filter((b) => !(b instanceof HTMLButtonElement && b.disabled))
      .filter((b) => accessibleName(b, document) === '')
      .map((b) => b.outerHTML.slice(0, 160));
    expect(unnamedButtons).toEqual([]);
  });

  it('portfolio/manage: the Import CSV button keeps a visible focus ring', async () => {
    const { default: Page } = await import('@/app/portfolio/manage/page');
    render(<Page />);

    const importBtn = await screen.findByRole('button', { name: /Import CSV/ });
    const cls = importBtn.getAttribute('class') ?? '';

    // `focus:outline-none` with no ring replacement leaves keyboard users with
    // no visible focus indicator at all.
    if (cls.includes('outline-none')) {
      expect(cls).toMatch(/ring-/);
    }
    expect(cls).toContain('focus:ring-2');
  });
});