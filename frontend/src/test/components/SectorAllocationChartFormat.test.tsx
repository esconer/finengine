/**
 * A page-local formatter is still a formatter: it publishes numbers, and an
 * absent value published as `0.0%` is a fabricated measurement.
 *
 * `SectorAllocationChart` carries its OWN `formatPercentage` rather than the
 * shared one, and that is deliberate — its scale contract is a FRACTION
 * multiplied by 100 at one decimal (`0.123 -> "12.3%"`), which is not the same
 * contract as `utils.ts`'s. Swapping in the shared formatter, or borrowing the
 * local one for a caller that already has percentages, would multiply
 * displayed shares by 100. This file pins the local formatter's own contract
 * and its absent-state guard in isolation, so the scale cannot drift while the
 * guard is added.
 */

import { describe, it, expect } from 'vitest';
import { formatPercentage } from '@/components/charts/SectorAllocationChart';

describe('SectorAllocationChart local formatPercentage', () => {
  it('renders the absent state, never 0.0%', () => {
    // `(null * 100).toFixed(1)` is "0.0": an absent share that reads exactly
    // like a holding measured at zero.
    expect(formatPercentage(null)).toBe('N/A');
    expect(formatPercentage(undefined)).toBe('N/A');
    expect(formatPercentage(Number.NaN)).toBe('N/A');
  });

  it('still renders a MEASURED 0 as a real 0.0%', () => {
    // A holding that genuinely is worth 0 of the book is a measurement, and
    // `value || 'N/A'` would erase it.
    expect(formatPercentage(0)).toBe('0.0%');
  });

  it('keeps its own scale contract: a FRACTION, one decimal, times 100', () => {
    // If this ever changes, the call sites in this component change with it.
    expect(formatPercentage(0.123)).toBe('12.3%');
    expect(formatPercentage(1)).toBe('100.0%');
    // Guard against being "fixed" into a double-100 by routing through the
    // shared formatter, whose contract is a fraction but with a different
    // default precision and absent-marker wiring.
    expect(formatPercentage(0.005)).toBe('0.5%');
  });
});
