/**
 * Utility function for conditionally joining class names together and resolving
 * conflicting Tailwind utilities in favour of the last one.
 */

import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Combines class names conditionally, then merges conflicting Tailwind
 * utilities so the LAST one wins.
 *
 * clsx alone only concatenates: `cn('p-2', 'p-4')` yields `"p-2 p-4"`, and
 * which padding applies is then decided by the order of the utilities in the
 * generated stylesheet rather than by the call. A caller writing `p-4` last
 * gets `p-2`. twMerge is what makes the call site decide: `px-2 py-1` + `p-4`
 * collapses to `p-4`, because `p-4` supersedes the `px-2` it conflicts with
 * while `py-1` is untouched.
 *
 * @param inputs - Class names to combine
 * @returns Combined class names string, conflicting utilities merged
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format currency values
 * @param value - Numeric value to format
 * @param currency - Currency code (default: 'INR' for Indian market)
 * @returns Formatted currency string with Indian formatting for INR
 */
export function formatCurrency(
  value: number | null | undefined,
  currency: string = 'INR'
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'N/A';
  }
  if (currency === 'INR') {
    // Indian formatting for INR with ₹ symbol and Indian number system
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  }
  // Default USD formatting
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Format percentage values
 * @param value - Numeric value to format as percentage (null/undefined/NaN = unmeasured)
 * @param decimals - Number of decimal places (default: 2)
 * @param unavailableReason - Optional explanation of WHY the value is unmeasured.
 *   Rendered after the dash, e.g. "N/A — no persisted prior score". Omit it at
 *   call sites that have no reason to give; the bare "N/A" is the house default.
 * @returns Formatted percentage string, or 'N/A' when unmeasured
 * Input contract: FRACTION — 0.12 renders as "12.00%". Do not pass
 * already-percent fields (e.g. backend `*_pct` values like 6.67).
 *
 * Absent-value rule (N/A-never-0, pinned by format-invariants.test.tsx): a null
 * or undefined measurement renders as 'N/A', never as "0.00%" — a fabricated
 * zero is indistinguishable from a real one. A *measured* 0 still renders as
 * "0.00%". Guard mirrors formatCurrency exactly so the two formatters cannot
 * drift apart.
 */
export function formatPercentage(
  value: number | null | undefined,
  decimals: number = 2,
  unavailableReason?: string | null
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return unavailableReason ? `N/A — ${unavailableReason}` : 'N/A';
  }
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Escape a single CSV cell (shared by all CSV builders).
 * Neutralizes Excel/LibreOffice formula injection (OWASP CSV Injection):
 * cells starting with =, +, -, @, CR or TAB get a leading `'`.
 * Always quotes and doubles embedded `"` so commas/newlines survive.
 */
export function escapeCsvCell(value: unknown): string {
  let s = value === null || value === undefined ? '' : String(value);
  if (/^[=+\-@\r\t]/.test(s)) {
    s = `'${s}`;
  }
  return `"${s.replace(/"/g, '""')}"`;
}

/**
 * Format a Date as YYYY-MM-DD from LOCAL calendar components
 * (toISOString converts to UTC and can shift the day for IST users).
 */
export function toDateOnlyString(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export const formatPercent = formatPercentage;

/**
 * Format Indian Rupees in Cr / L notation or standard INR
 * @param value - Numeric value in rupees (null/undefined/NaN = unmeasured)
 * @returns Formatted Indian Rupee string, or 'N/A' when unmeasured
 * An absent value falls through both scale branches (null >= 1e7 is false) and
 * is delegated to formatCurrency, which owns the N/A guard.
 */
export function formatIndianRupees(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'N/A';
  }
  if (value >= 1e7) {
    return `₹${(value / 1e7).toFixed(2)} Cr`;
  }
  if (value >= 1e5) {
    return `₹${(value / 1e5).toFixed(2)} L`;
  }
  return formatCurrency(value, 'INR');
}

/**
 * Format large numbers with K, M, B suffixes
 * @param value - Numeric value to format (null/undefined/NaN = unmeasured)
 * @returns Formatted number string, or 'N/A' when unmeasured
 * The sub-1e3 fallback calls value.toFixed(2), which throws on null — so the
 * absent-value guard is load-bearing here, not cosmetic.
 */
export function formatLargeNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'N/A';
  }
  if (value >= 1e9) {
    return `${(value / 1e9).toFixed(1)}B`;
  }
  if (value >= 1e6) {
    return `${(value / 1e6).toFixed(1)}M`;
  }
  if (value >= 1e3) {
    return `${(value / 1e3).toFixed(1)}K`;
  }
  return value.toFixed(2);
}

/**
 * Generate a random ID
 * @param prefix - Optional prefix for the ID
 * @returns Random ID string
 */
export function generateId(prefix?: string): string {
  const id = Math.random().toString(36).substr(2, 9);
  return prefix ? `${prefix}-${id}` : id;
}

/**
 * Debounce function
 * @param func - Function to debounce
 * @param wait - Wait time in milliseconds
 * @returns Debounced function
 */
export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: NodeJS.Timeout;
  return (...args: Parameters<T>) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}

/**
 * Sleep utility for delays
 * @param ms - Milliseconds to sleep
 * @returns Promise that resolves after the specified time
 */
export function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Check if a value is not null or undefined
 * @param value - Value to check
 * @returns True if value is not null/undefined
 */
export function isNotNull<T>(value: T | null | undefined): value is T {
  return value !== null && value !== undefined;
}

/**
 * Capitalize the first letter of a string
 * @param str - String to capitalize
 * @returns Capitalized string
 */
export function capitalize(str: string): string {
  if (!str) return str;
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Convert camelCase to title case
 * @param str - camelCase string
 * @returns Title case string
 */
export function camelToTitle(str: string): string {
  return str
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, (str) => str.toUpperCase())
    .trim();
}

/**
 * Truncate text to a specified length
 * @param text - Text to truncate
 * @param length - Maximum length
 * @returns Truncated text
 */
export function truncate(text: string, length: number): string {
  if (text.length <= length) return text;
  return text.substring(0, length) + '...';
}

/**
 * Generate color based on string input
 * @param str - String to generate color from
 * @returns HSL color string
 */
export function stringToColor(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  
  const hue = hash % 360;
  return `hsl(${hue}, 70%, 60%)`;
}