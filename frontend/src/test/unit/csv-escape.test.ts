import { describe, it, expect } from 'vitest';
import { escapeCsvCell } from '@/lib/utils';

describe('escapeCsvCell (CSV injection + quoting — 04-B6/04-B5)', () => {
  it('prefixes formula-trigger characters with a single quote', () => {
    expect(escapeCsvCell("=cmd|'/c calc'!A0")).toBe(`"'=cmd|'/c calc'!A0"`);
    expect(escapeCsvCell('+1')).toBe(`"'+1"`);
    expect(escapeCsvCell('-1')).toBe(`"'-1"`);
    expect(escapeCsvCell('@SUM(A1)')).toBe(`"'@SUM(A1)"`);
    expect(escapeCsvCell('\r=cmd')).toBe(`"'\r=cmd"`);
    expect(escapeCsvCell('\tx')).toBe(`"'\tx"`);
  });

  it('always quotes and doubles embedded quotes', () => {
    expect(escapeCsvCell('say "hi"')).toBe('"say ""hi"""');
  });

  it('keeps commas and newlines inside quotes', () => {
    expect(escapeCsvCell('a,b')).toBe('"a,b"');
    expect(escapeCsvCell('line1\nline2')).toBe('"line1\nline2"');
  });

  it('renders null/undefined as empty cell; passes plain text/numbers through', () => {
    expect(escapeCsvCell(null)).toBe('""');
    expect(escapeCsvCell(undefined)).toBe('""');
    expect(escapeCsvCell('INFY.NS')).toBe('"INFY.NS"');
    expect(escapeCsvCell(42)).toBe('"42"');
  });
});
