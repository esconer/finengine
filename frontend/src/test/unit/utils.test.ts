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
} from '@/lib/utils';

describe('Frontend Utils', () => {
  describe('cn', () => {
    it('merges class names correctly', () => {
      expect(cn('px-2 py-1', 'bg-blue-500')).toBe('px-2 py-1 bg-blue-500');
      expect(cn('px-2', false && 'hidden', 'text-white')).toBe('px-2 text-white');
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
