import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { DataTable } from '@/components/ui/DataTable';
import { ColumnDef } from '@tanstack/react-table';

interface SampleRow {
  ticker: string;
  weight: number;
}

const columns: ColumnDef<SampleRow, any>[] = [
  {
    accessorKey: 'ticker',
    header: 'Ticker',
    cell: info => info.getValue(),
  },
  {
    accessorKey: 'weight',
    header: 'Weight',
    cell: info => String(info.getValue()),
  },
];

describe('DataTable Component', () => {
  it('renders table header when data is empty', () => {
    render(<DataTable data={[]} columns={columns} />);
    expect(screen.getByText(/Portfolio Positions \(0\)/)).toBeDefined();
    expect(screen.getByText('Ticker')).toBeDefined();
    expect(screen.getByText('Weight')).toBeDefined();
  });

  it('renders rows properly when data is provided', () => {
    const data: SampleRow[] = [
      { ticker: 'INFY.NS', weight: 0.6 },
      { ticker: 'HDFCBANK.NS', weight: 0.4 },
    ];
    render(<DataTable data={data} columns={columns} />);
    expect(screen.getByText('INFY.NS')).toBeDefined();
    expect(screen.getByText('HDFCBANK.NS')).toBeDefined();
    expect(screen.getByText('0.6')).toBeDefined();
    expect(screen.getByText('0.4')).toBeDefined();
  });

  it('renders loading skeleton when loading is true', () => {
    const { container } = render(<DataTable data={[]} columns={columns} loading={true} />);
    const animatedElements = container.querySelectorAll('.animate-pulse');
    expect(animatedElements.length).toBeGreaterThan(0);
  });
});
