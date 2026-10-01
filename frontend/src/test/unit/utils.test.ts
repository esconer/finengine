import { describe, it, expect } from 'vitest';
import {
  cn,
  formatCurrency,
  formatPercentage,
  formatLargeNumber,
  generateId,
  isNotNull,
  capitalize,
  camelToTitle,
  truncate,
  stringToColor,
  toDateOnlyString,
} from '@/lib/utils';

describe('Frontend Utils', () => {
  describe('cn', () => {
    it('merges class names correctly', () => {
      expect(cn('px-2 py-1', 'bg-blue-500')).toBe('px-2 py-1 bg-blue-500');
      expect(cn('px-2', false && 'hidden', 'text-white')).toBe('px-2 text-white');
    });

    it('resolves a conflicting Tailwind pair to the MERGE winner, not the positional one', () => {
      // clsx alone appends, so `p-2 p-4` leaves the winner to the stylesheet's
      // source order rather than to the call — the caller writes `p-4` last and
      // gets `p-2`. tailwind-merge is what makes the call decide.
      expect(cn('p-2', 'p-4')).toBe('p-4');
      // A broader utility displaces the narrower one it conflicts with, and the
      // unrelated utilities survive. `text-gray-600` is a colour and `text-lg` a
      // font-size — different groups, so the colour is untouched.
      expect(cn('px-2 py-1', 'p-4')).toBe('p-4');
      expect(cn('text-sm text-gray-600', 'text-lg')).toBe('text-gray-600 text-lg');
      // And the merge is positional, not "first wins".
      expect(cn('p-2', 'px-4')).toBe('p-2 px-4');
      expect(cn('px-4', 'p-2')).toBe('p-2');
    });
  });

  describe('formatCurrency', () => {
    it('formats INR correctly', () => {
      const result = formatCurrency(125000, 'INR');
      expect(result).toContain('1,25,000');
    });

    it('formats USD correctly', () => {
      const result = formatCurrency(125000, 'USD');
      expect(result).toContain('125,000');
    });
  });

  describe('formatPercentage', () => {
    it('formats decimal fractions as percentages', () => {
      expect(formatPercentage(0.1234)).toBe('12.34%');
      expect(formatPercentage(0.05, 1)).toBe('5.0%');
      expect(formatPercentage(1.0)).toBe('100.00%');
    });
  });

  describe('toDateOnlyString', () => {
    it('formats from local calendar components, not UTC (04-B20)', () => {
      expect(toDateOnlyString(new Date(2026, 0, 5))).toBe('2026-01-05');
      expect(toDateOnlyString(new Date(2026, 11, 31))).toBe('2026-12-31');
    });
  });

  describe('formatLargeNumber', () => {
    it('formats large numbers with K, M, B suffixes', () => {
      expect(formatLargeNumber(1500000000)).toBe('1.5B');
      expect(formatLargeNumber(2500000)).toBe('2.5M');
      expect(formatLargeNumber(3500)).toBe('3.5K');
      expect(formatLargeNumber(50.5)).toBe('50.50');
    });
  });

  describe('string and object helpers', () => {
    it('generates unique ids', () => {
      const id1 = generateId('prefix');
      const id2 = generateId('prefix');
      expect(id1.startsWith('prefix-')).toBe(true);
      expect(id1).not.toBe(id2);
    });

    it('checks not null', () => {
      expect(isNotNull('hello')).toBe(true);
      expect(isNotNull(null)).toBe(false);
      expect(isNotNull(undefined)).toBe(false);
    });

    it('capitalizes and formats camelCase', () => {
      expect(capitalize('portfolio')).toBe('Portfolio');
      expect(camelToTitle('totalMarketValue')).toBe('Total Market Value');
      expect(truncate('Super long text string here', 10)).toBe('Super long...');
    });

    it('generates deterministic hsl colors', () => {
      const color = stringToColor('INFY.NS');
      expect(color.startsWith('hsl(')).toBe(true);
    });
  });
});
