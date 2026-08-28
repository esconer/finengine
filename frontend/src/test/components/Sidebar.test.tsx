import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { Sidebar } from '@/components/layout/Sidebar';

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
}));

describe('Sidebar Component', () => {
  it('renders navigation links', () => {
    render(<Sidebar />);
    expect(screen.getByText('Summary')).toBeDefined();
    expect(screen.getByText('Equity Research')).toBeDefined();
    expect(screen.getByText('Screener Studio')).toBeDefined();
    expect(screen.getByText('Realized Risk')).toBeDefined();
    expect(screen.getByText('Forecast Risk')).toBeDefined();
  });
});
