import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import EquityResearchPage from '@/app/dashboard/equity-research/page';
import * as api from '@/lib/api';

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
    getFullProfile: vi.fn().mockResolvedValue({
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
    }),
    getShareholding: vi.fn().mockResolvedValue({
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
    getConcalls: vi.fn().mockResolvedValue({
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
    getCustomRatios: vi.fn().mockResolvedValue({
      ticker: 'RELIANCE.NS',
      piotroski_score: 7,
      graham_number: 3250.0,
      enterprise_value_cr: 1950000.0,
      current_price: 2900.0,
      ratios_history: { periods: [], rows: {} },
    }),
    downloadExcelModel: vi.fn().mockResolvedValue(new Blob()),
    getAiMemoPrompt: vi.fn().mockResolvedValue({ ticker: 'RELIANCE.NS', prompt: 'Memo prompt' }),
    getAiForensicPrompt: vi.fn().mockResolvedValue({ ticker: 'RELIANCE.NS', prompt: 'Forensic prompt' }),
  },
  companyDataApi: {
    getFinancialStatements: vi.fn().mockResolvedValue({
      columns: ['2025'],
      data: { Sales: { '2025': 900000 } },
    }),
  },
}));

describe('EquityResearchPage', () => {
  it('renders research terminal and stock profile', async () => {
    render(<EquityResearchPage />);
    expect(screen.getByText('Equity Research Terminal')).toBeDefined();

    await waitFor(() => {
      expect(screen.getByText('Reliance Industries Limited')).toBeDefined();
    });

    expect(screen.getByText('Piotroski F-Score')).toBeDefined();
    expect(screen.getByText('7/9')).toBeDefined();
    expect(screen.getByText('8-Tab Excel Model')).toBeDefined();
  });
});
