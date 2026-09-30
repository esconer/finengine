import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import * as utils from '@/lib/utils';
import {
  formatCurrency,
  formatPercentage,
  formatPercent,
  formatIndianRupees,
  formatLargeNumber,
} from '@/lib/utils';
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

// ---------------------------------------------------------------------------
// formatPercentage was the one shared formatter outside this file's net. It had
// no absent-value guard, so `formatPercentage(null)` evaluated
// `(null * 100).toFixed(2)` and returned "0.00%" — a fabricated zero, shipped
// to every call site that passes a nullable field straight through. A net that
// only covers the formatters someone remembered is the same class of defect as
// the bug, so every exported formatter is covered explicitly below AND swept
// automatically at the bottom of this file.
// ---------------------------------------------------------------------------

describe('formatPercentage — absent never renders as a fabricated zero', () => {
  it('renders N/A for null, undefined, and NaN', () => {
    expect(formatPercentage(null)).toBe('N/A');
    expect(formatPercentage(undefined)).toBe('N/A');
    expect(formatPercentage(Number.NaN)).toBe('N/A');
  });

  // The bug in its original form. Pinned separately so the failure names the
  // exact regression rather than surfacing as a generic N/A mismatch.
  it('never turns a null into "0.00%"', () => {
    expect(formatPercentage(null)).not.toContain('0.00');
    expect(formatPercentage(undefined)).not.toContain('NaN');
  });

  // The other half of the rule, and the one people forget: a MEASURED zero is
  // a real number and must survive as one. Guarding with `value || 'N/A'` or a
  // truthiness test would pass the test above and silently fail this one.
  it('still formats a measured zero as a real zero', () => {
    expect(formatPercentage(0)).toBe('0.00%');
    expect(formatPercentage(0)).not.toBe('N/A');
    expect(formatPercentage(0, 1)).toBe('0.0%');
  });

  it('leaves every measured value byte-identical to the unguarded version', () => {
    expect(formatPercentage(0.1234)).toBe('12.34%');
    expect(formatPercentage(0.05, 1)).toBe('5.0%');
    expect(formatPercentage(1.0)).toBe('100.00%');
    expect(formatPercentage(-0.031)).toBe('-3.10%');
    expect(formatPercentage(0.123456, 3)).toBe('12.346%');
  });

  it('carries a caller-supplied reason on the unmeasured state only', () => {
    expect(formatPercentage(null, 2, 'no persisted prior score')).toBe(
      'N/A — no persisted prior score'
    );
    // A reason must never leak onto a measured value.
    expect(formatPercentage(0.5, 2, 'no persisted prior score')).toBe('50.00%');
    // No reason supplied → the bare house default.
    expect(formatPercentage(null)).toBe('N/A');
  });

  it('formatPercent is the same guarded function, not a second copy', () => {
    expect(formatPercent).toBe(formatPercentage);
    expect(formatPercent(null)).toBe('N/A');
    expect(formatPercent(0)).toBe('0.00%');
  });
});

describe('every exported formatter guards the absent state', () => {
  it('formatIndianRupees renders N/A for null/undefined/NaN, and 0 as ₹0.00', () => {
    expect(formatIndianRupees(null)).toBe('N/A');
    expect(formatIndianRupees(undefined)).toBe('N/A');
    expect(formatIndianRupees(Number.NaN)).toBe('N/A');
    expect(formatIndianRupees(0)).not.toBe('N/A');
    expect(formatIndianRupees(0)).toContain('0.00');
    // Scales are untouched for present values.
    expect(formatIndianRupees(1e7)).toContain('Cr');
    expect(formatIndianRupees(1e5)).toContain('L');
  });

  it('formatLargeNumber renders N/A for null/undefined/NaN, and 0 as 0.00', () => {
    // This one used to THROW ("Cannot read properties of null (reading
    // 'toFixed')") rather than fabricate — the guard is load-bearing.
    expect(() => formatLargeNumber(null)).not.toThrow();
    expect(formatLargeNumber(null)).toBe('N/A');
    expect(formatLargeNumber(undefined)).toBe('N/A');
    expect(formatLargeNumber(Number.NaN)).toBe('N/A');
    expect(formatLargeNumber(0)).toBe('0.00');
    expect(formatLargeNumber(0)).not.toBe('N/A');
    expect(formatLargeNumber(1.5e9)).toBe('1.5B');
    expect(formatLargeNumber(2.5e6)).toBe('2.5M');
    expect(formatLargeNumber(3.5e3)).toBe('3.5K');
  });

  it('formatCurrency covers both halves too, on a measured zero', () => {
    expect(formatCurrency(0, 'INR')).not.toBe('N/A');
    expect(formatCurrency(0, 'USD')).not.toBe('N/A');
  });
});

// ---------------------------------------------------------------------------
// The net itself.
//
// Registration alone would only fail when someone remembers to edit it, which
// is the same failure mode as the original bug. So this sweeps the module
// namespace: any `format*` export — present today or added tomorrow — is called
// with null, undefined and NaN and must answer with the absent marker instead of
// a number, and must still answer a MEASURED zero with a number. A new
// unguarded formatter fails here without being registered anywhere.
// ---------------------------------------------------------------------------

const ABSENT_MARKER = /N\/A|—/;
// A string that is only digits, grouping and unit symbols claims to be a
// measurement. This is what a fabricated zero looks like from the outside.
const LOOKS_LIKE_A_MEASUREMENT = /^[\s₹$+\-]*[\d,.]+\s*[%KMBLCr]?\s*$/;

type Formatter = (value: unknown, ...rest: unknown[]) => string;

function formatterExports(): [string, Formatter][] {
  return Object.entries(utils)
    .filter(([name]) => name.startsWith('format'))
    .map(([name, fn]) => [name, fn as unknown as Formatter]);
}

describe('formatter net — no exported formatter may fabricate an absent value', () => {
  it('discovers at least the four formatters under contract', () => {
    // A sweep that silently matches nothing would pass forever. Pin the floor.
    const names = formatterExports().map(([name]) => name).sort();
    expect(names).toEqual([
      'formatCurrency',
      'formatIndianRupees',
      'formatLargeNumber',
      'formatPercent',
      'formatPercentage',
    ]);
  });

  it.each(formatterExports())('%s answers the absent state with a marker, never a number', (name, fn) => {
    for (const absent of [null, undefined, Number.NaN]) {
      let out: string;
      try {
        out = fn(absent);
      } catch (e) {
        throw new Error(
          `${name}(${String(absent)}) threw instead of rendering the absent state: ${(e as Error).message}`
        );
      }
      expect(out, `${name}(${String(absent)}) must not look like a measurement`).not.toMatch(
        LOOKS_LIKE_A_MEASUREMENT
      );
      expect(out, `${name}(${String(absent)}) must carry the absent marker`).toMatch(ABSENT_MARKER);
    }
  });

  it.each(formatterExports())('%s still renders a MEASURED zero as a number', (_name, fn) => {
    const zero = fn(0);
    expect(zero).not.toMatch(ABSENT_MARKER);
    expect(zero).toMatch(/\d/);
  });
});
