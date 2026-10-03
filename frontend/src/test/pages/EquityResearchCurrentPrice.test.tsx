import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import EquityResearchPage from '@/app/dashboard/equity-research/page';
import type { EquityResearchProfile, CustomRatiosDataResponse } from '@/types';

// `current_price` upstream is `Optional[float] = None`
// (EquityResearchProfileResponse / CustomRatiosResponse), so it reaches the
// browser either present-and-null or omitted entirely. Both shapes are
// asserted here as *type-legal payloads* and as *rendered output*.

const navMocks = vi.hoisted(() => ({ search: '' }));

const mocks = vi.hoisted(() => {
  const baseProfile = {
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
    pros: ['Company is almost debt free'],
    cons: ['Stock trading high'],
    peers: [],
    concall_count: 1,
    annual_reports: [],
    credit_ratings: [],
  };
  return {
    baseProfile,
    getFullProfile: vi.fn(),
    getShareholding: vi.fn(),
    getConcalls: vi.fn(),
    getCustomRatios: vi.fn(),
    downloadExcelModel: vi.fn(),
    getAiMemoPrompt: vi.fn(),
    getAiForensicPrompt: vi.fn(),
    getFinancialStatements: vi.fn(),
  };
});

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(navMocks.search),
}));

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  AreaChart: ({ children }: any) => <div>{children}</div>,
  Area: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
  CartesianGrid: () => <div />,
  Tooltip: () => <div />,
  Legend: () => <div />,
}));

vi.mock('@/lib/api', () => ({
  equityResearchApi: {
    getFullProfile: mocks.getFullProfile.mockResolvedValue(mocks.baseProfile),
    getShareholding: mocks.getShareholding.mockResolvedValue({
      ticker: 'RELIANCE.NS',
      quarterly: {
        periods: ['2025-09-30'],
        rows: { Promoters: [50.3] },
        chart_series: [{ period: '2025-09-30', promoters: 50.3 }],
      },
      yearly: {
        periods: ['2025'],
        rows: { Promoters: [50.3] },
        chart_series: [{ period: '2025', promoters: 50.3 }],
      },
    }),
    getConcalls: mocks.getConcalls.mockResolvedValue({
      ticker: 'RELIANCE.NS',
      count: 1,
      concalls: [
        {
          date: '2026-01-20',
          quarter: 'Q3 FY26',
          title: 'Q3 FY26 Call',
          audio_url: 'https://example.com/audio.mp3',
        },
      ],
    }),
    getCustomRatios: mocks.getCustomRatios.mockResolvedValue({
      ticker: 'RELIANCE.NS',
      piotroski_score: 7,
      graham_number: 3250.0,
      enterprise_value_cr: 1950000.0,
      current_price: 2900.0,
      ratios_history: { periods: [], rows: {} },
    }),
    downloadExcelModel: mocks.downloadExcelModel.mockResolvedValue(new Blob()),
    getAiMemoPrompt: mocks.getAiMemoPrompt.mockResolvedValue({ ticker: 'RELIANCE.NS', prompt: 'Memo prompt' }),
    getAiForensicPrompt: mocks.getAiForensicPrompt.mockResolvedValue({ ticker: 'RELIANCE.NS', prompt: 'Forensic prompt' }),
  },
  companyDataApi: {
    getFinancialStatements: mocks.getFinancialStatements.mockResolvedValue({
      columns: ['2025'],
      data: { Sales: { '2025': 900000 } },
    }),
  },
}));

beforeEach(() => {
  navMocks.search = '';
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Type-level: the payloads the backend can now legally emit.
// Declared against the real exported types, so `bun x tsc --noEmit` is the
// assertion — these four consts are the red/green signal for `?:` and `| null`.
// ---------------------------------------------------------------------------

const minimalProfile = {
  symbol: 'RELIANCE',
  ticker: 'RELIANCE.NS',
  name: 'Reliance Industries Limited',
  indices: ['NIFTY 50'],
  custom_ratios: { piotroski_score: 7 },
  cagrs: {},
  pros: [],
  cons: [],
  peers: [],
  concall_count: 1,
  annual_reports: [],
  credit_ratings: [],
};

/** bfinance published no price: the field is present and explicitly null. */
const profilePriceNull: EquityResearchProfile = { ...minimalProfile, current_price: null };

/** Omission is the other half of `Optional[...] = None`; `?:` is what allows it. */
const profilePriceOmitted: EquityResearchProfile = { ...minimalProfile };

const minimalRatios = {
  ticker: 'RELIANCE.NS',
  piotroski_score: 7,
  enterprise_value_cr: 1950000.0,
  ratios_history: { periods: [], rows: {} },
};

const ratiosPriceNull: CustomRatiosDataResponse = { ...minimalRatios, current_price: null };
const ratiosPriceOmitted: CustomRatiosDataResponse = { ...minimalRatios };

describe('current_price is Optional[float] = None upstream', () => {
  it('accepts null and omission under both equity-research types', () => {
    expect(profilePriceNull.current_price).toBeNull();
    expect(profilePriceOmitted.current_price).toBeUndefined();
    expect('current_price' in profilePriceOmitted).toBe(false);

    expect(ratiosPriceNull.current_price).toBeNull();
    expect(ratiosPriceOmitted.current_price).toBeUndefined();
    expect('current_price' in ratiosPriceOmitted).toBe(false);
  });

  it('renders the real price when one is published (guard is load-bearing)', async () => {
    render(<EquityResearchPage />);
    await waitFor(() => {
      expect(screen.getByText('Reliance Industries Limited')).toBeDefined();
    });

    // `52W Low: N/A` (the fixture publishes no 52W range) uniquely identifies
    // the span; its grandparent is the price block.
    const priceBlock = screen.getByText('52W Low: N/A').parentElement?.parentElement;
    expect(priceBlock?.textContent).toContain('₹2,900.00');
    expect(priceBlock?.textContent).not.toContain('N/A\n');
  });

  it('renders N/A, never a fabricated ₹0.00, when current_price is null', async () => {
    mocks.getFullProfile.mockResolvedValueOnce({
      ...mocks.baseProfile,
      current_price: null,
    });

    render(<EquityResearchPage />);
    await waitFor(() => {
      expect(screen.getByText('Reliance Industries Limited')).toBeDefined();
    });

    const priceBlock = screen.getByText('52W Low: N/A').parentElement?.parentElement;
    // No rupee glyph at all => absence was not laundered into a price.
    expect(priceBlock?.textContent).toContain('N/A');
    expect(priceBlock?.textContent).not.toContain('₹');
    expect(screen.queryByText('₹0.00')).toBeNull();
  });

  it('renders N/A when current_price is absent from the payload entirely', async () => {
    const { current_price: _omitted, ...withoutPrice } = mocks.baseProfile;
    mocks.getFullProfile.mockResolvedValueOnce(withoutPrice);

    render(<EquityResearchPage />);
    await waitFor(() => {
      expect(screen.getByText('Reliance Industries Limited')).toBeDefined();
    });

    const priceBlock = screen.getByText('52W Low: N/A').parentElement?.parentElement;
    expect(priceBlock?.textContent).toContain('N/A');
    expect(priceBlock?.textContent).not.toContain('₹');
  });
});