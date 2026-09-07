import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import MonteCarloPage from '@/app/dashboard/monte-carlo/page';

const runMonteCarloMock = vi.fn();

vi.mock('@/lib/api', () => ({
  analyticsApi: {
    runMonteCarlo: (...args: unknown[]) => runMonteCarloMock(...(args as [])),
  },
}));

describe('MonteCarloPage — honest calibration copy', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not claim a full two years of cached closes', () => {
    render(<MonteCarloPage />);

    expect(screen.getByText(/up to two years of cached closes/)).toBeDefined();
    expect(screen.getByText(/limited by cache depth/)).toBeDefined();
    // Old drift copy claimed an unconditional "two years of cached closes"
    expect(screen.queryByText(/Returns calibrated on two years/)).toBeNull();
  });
});
