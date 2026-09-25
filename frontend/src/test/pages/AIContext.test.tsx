import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import AIContextPage from '@/app/dashboard/ai-context/page';

const getContextMock = vi.fn();

vi.mock('@/lib/api', () => ({
  aiContextApi: {
    getContext: (...args: unknown[]) => getContextMock(...(args as [])),
  },
}));

const response = {
  schema_version: '1.0',
  export_id: 'test',
  generated_at: '2026-09-25T12:00:00Z',
  base_currency: 'INR' as const,
  currency_policy: 'Portfolio section uses the requested base_currency; analytics sections retain endpoint units.',
  detail: 'summary' as const,
  scope: ['portfolio', 'realized_risk'],
  environment: { primary_source: 'bfinance' },
  sections: {
    portfolio: {
      key: 'portfolio',
      title: 'Portfolio Management',
      route: '/portfolio/manage',
      status: 'available' as const,
      detail: 'summary' as const,
      generated_at: '2026-09-25T12:00:00Z',
      as_of: null,
      inputs: {},
      data: { total_value: 1000 },
      omitted_fields: [],
      warnings: [],
    },
    realized_risk: {
      key: 'realized_risk',
      title: 'Realized Risk',
      route: '/dashboard/realized-risk',
      status: 'partial' as const,
      detail: 'summary' as const,
      generated_at: '2026-09-25T12:00:00Z',
      as_of: null,
      inputs: {},
      data: null,
      omitted_fields: [],
      warnings: ['Short history'],
      error: 'Partial result',
    },
  },
  warnings: [],
};

describe('AI context export page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getContextMock.mockResolvedValue(response);
  });

  it('generates a JSON context and shows section status', async () => {
    render(<AIContextPage />);

    fireEvent.click(screen.getByTestId('generate-ai-context'));

    await waitFor(() => expect(getContextMock).toHaveBeenCalledWith({ format: 'json', detail: 'summary' }));
    expect(await screen.findByText('Export status')).toBeDefined();
    expect(screen.getByText('Portfolio Management')).toBeDefined();
    expect(screen.getAllByText('partial').length).toBeGreaterThan(0);
    expect(screen.getByText(/AI context generated/)).toBeDefined();
  });

  it('passes the selected full-detail and Markdown options to the API', async () => {
    getContextMock.mockResolvedValue('# Markdown context');
    render(<AIContextPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Full detail' }));
    fireEvent.click(screen.getByRole('button', { name: 'Markdown' }));
    fireEvent.click(screen.getByTestId('generate-ai-context'));

    await waitFor(() => expect(getContextMock).toHaveBeenCalledWith({ format: 'markdown', detail: 'full' }));
    expect(await screen.findByText(/# Markdown context/)).toBeDefined();
    expect(screen.getByRole('button', { name: 'Download' })).toBeDefined();
  });
});
