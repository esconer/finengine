import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { formatCurrency } from '@/lib/utils';
import { MetricCard } from '@/components/ui/MetricCard';

describe('format invariants (en-IN + N/A)', () => {
  it('formats INR with Indian digit grouping, never en-US grouping', () => {
    const lakh = formatCurrency(125000, 'INR');
    expect(lakh).toContain('1,25,000');
    expect(lakh).not.toContain('125,000');

    const crore = formatCurrency(10000000, 'INR');
    expect(crore).toContain('1,00,00,000');
    expect(crore).not.toContain('10,000,000');
  });

  it('renders N/A for null, undefined, and NaN — never ₹0 or 0', () => {
    expect(formatCurrency(null)).toBe('N/A');
    expect(formatCurrency(undefined)).toBe('N/A');
    expect(formatCurrency(NaN)).toBe('N/A');
  });

  it('still formats a valid zero as a real zero', () => {
    const zero = formatCurrency(0, 'INR');
    expect(zero).not.toBe('N/A');
    expect(zero).toContain('0.00');
  });

  it('MetricCard renders N/A for NaN and null values, never 0', () => {
    render(
      <MetricCard title="NaN Card" value={Number.NaN} />
    );
    expect(screen.getByText('N/A')).toBeInTheDocument();
    expect(screen.queryByText('0.00')).toBeNull();
  });

  it('MetricCard renders N/A for null values, never 0', () => {
    render(
      <MetricCard title="Null Card" value={null as unknown as number} />
    );
    expect(screen.getByText('N/A')).toBeInTheDocument();
    expect(screen.queryByText('0.00')).toBeNull();
  });
});
