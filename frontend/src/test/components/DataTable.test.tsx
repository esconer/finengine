import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

  it('shows "No results" instead of "Showing 1 to 0" when empty', () => {
    render(<DataTable data={[]} columns={columns} />);
    expect(screen.getByText('No results')).toBeDefined();
    expect(screen.queryByText(/Showing 1 to/)).toBeNull();
  });

  it('updates the title count after filtering', () => {
    const data: SampleRow[] = [
      { ticker: 'INFY.NS', weight: 0.6 },
      { ticker: 'HDFCBANK.NS', weight: 0.4 },
    ];
    render(<DataTable data={data} columns={columns} title="Positions" />);
    expect(screen.getByText('Positions (2)')).toBeDefined();
    fireEvent.change(screen.getByLabelText('Search table'), { target: { value: 'INFY' } });
    expect(screen.getByText('Positions (1)')).toBeDefined();
    expect(screen.getByText('Showing 1 to 1 of 1 results')).toBeDefined();
  });

  it('exposes sortable headers as buttons with aria-sort', () => {
    render(
      <DataTable
        data={[{ ticker: 'INFY.NS', weight: 0.6 }]}
        columns={columns}
      />
    );
    const btn = screen.getByRole('button', { name: 'Sort by Ticker' });
    expect(btn.closest('th')!.getAttribute('aria-sort')).toBeNull();
    fireEvent.click(btn);
    expect(btn.closest('th')!.getAttribute('aria-sort')).toBe('ascending');
    fireEvent.click(btn);
    expect(btn.closest('th')!.getAttribute('aria-sort')).toBe('descending');
  });
});
