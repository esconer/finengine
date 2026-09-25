import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import IndiaFlowsPage from '@/app/dashboard/india-flows/page';

// Ticket 08 (V3-15): the India page must not invent freshness, must not claim
// "no anomalies"/"no flow" success for an unavailable or unknown component, and
// must render partial coverage as partial (missing cells stay an em dash).
const getMock = vi.fn();

vi.mock('@/lib/api', () => ({
  default: {
    get: (...args: unknown[]) => getMock(...(args as [string])),
  },
}));

const FLOW_URL = '/analytics/india-flows?lookback_days=30';
const DELIVERY_URL = '/analytics/delivery-anomalies';
const LIQUIDITY_URL = '/analytics/liquidity-limits';

function stubRoutes(
  flows: unknown,
  delivery: unknown,
  liquidity: unknown,
): void {
  getMock.mockImplementation((url: string) => {
    const data =
      url === FLOW_URL ? flows : url === DELIVERY_URL ? delivery : liquidity;
    return Promise.resolve({ data });
  });
}

const UNAVAILABLE_FLOWS = {
  flows: [],
  data_status: 'unavailable',
  as_of: null,
  available_categories: [],
  missing_categories: ['FII', 'DII'],
  incomplete_dates: [],
};

const UNAVAILABLE_DELIVERY = {
  anomalies: [],
  data_status: 'unavailable',
  as_of: null,
  requested_symbols: [],
  covered_symbols: [],
  missing_symbols: [],
};

async function renderPage(): Promise<void> {
  render(<IndiaFlowsPage />);
  await waitFor(() => {
    expect(getMock).toHaveBeenCalledWith(FLOW_URL);
    expect(getMock).toHaveBeenCalledWith(DELIVERY_URL);
    expect(getMock).toHaveBeenCalledWith(LIQUIDITY_URL);
  });
  // The page renders from the resolved stubbed responses, so the synchronous
  // getBy* queries below need those microtasks flushed first. Waiting only for
  // the calls to be made leaves this a race whenever the worker is contended.
  await act(async () => {});
}

describe('IndiaFlowsPage — honest component status rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('never claims "no >2σ delivery spikes" when delivery is unavailable', async () => {
    stubRoutes(UNAVAILABLE_FLOWS, UNAVAILABLE_DELIVERY, { data_status: 'unavailable', positions: [] });
    await renderPage();

    expect(screen.getByTestId('delivery-unavailable')).toBeDefined();
    expect(screen.queryByText(/No >2σ delivery spikes detected/)).toBeNull();
    expect(screen.queryByText(/No &gt;2σ delivery spikes detected/)).toBeNull();
  });

  it('never claims "no >2σ delivery spikes" when the status is missing entirely', async () => {
    stubRoutes(
      UNAVAILABLE_FLOWS,
      { anomalies: [], requested_symbols: ['SBIN'], missing_symbols: [] },
      { data_status: 'unavailable', positions: [] },
    );
    await renderPage();

    // An undeclared status is unknown, not "available with nothing to report".
    expect(screen.getByTestId('delivery-unavailable')).toBeDefined();
    expect(screen.queryByText(/delivery spikes detected/)).toBeNull();
  });

  it('renders the no-spike success only for a fully covered empty result', async () => {
    stubRoutes(
      UNAVAILABLE_FLOWS,
      {
        anomalies: [],
        data_status: 'available',
        as_of: '2026-09-24',
        requested_symbols: ['SBIN', 'TCS'],
        covered_symbols: ['SBIN', 'TCS'],
        missing_symbols: [],
      },
      { data_status: 'unavailable', positions: [] },
    );
    await renderPage();

    expect(screen.getByText(/No >2σ delivery spikes detected/)).toBeDefined();
  });

  it('treats an empty-but-incomplete delivery result as partial, naming the gaps', async () => {
    stubRoutes(
      UNAVAILABLE_FLOWS,
      {
        anomalies: [],
        data_status: 'partial',
        as_of: '2026-09-24',
        requested_symbols: ['SBIN', 'TCS', 'INFY'],
        covered_symbols: ['SBIN', 'TCS'],
        missing_symbols: ['INFY'],
      },
      { data_status: 'unavailable', positions: [] },
    );
    await renderPage();

    expect(screen.getByTestId('delivery-partial')).toBeDefined();
    expect(screen.getByTestId('delivery-missing-symbols').textContent).toContain('INFY');
    expect(screen.queryByText(/delivery spikes detected/)).toBeNull();
  });

  it('keeps partial flow rows and shows missing FII/DII as an em dash, not 0', async () => {
    stubRoutes(
      {
        flows: [
          {
            date: '2026-09-22',
            fii_net_crores: -120.5,
            dii_net_crores: null,
            total_net_crores: null,
            available_categories: ['FII'],
          },
        ],
        data_status: 'partial',
        as_of: '2026-09-22',
        available_categories: ['FII'],
        missing_categories: ['DII'],
        incomplete_dates: ['2026-09-22'],
      },
      UNAVAILABLE_DELIVERY,
      { data_status: 'unavailable', positions: [] },
    );
    await renderPage();

    expect(screen.getByTestId('flows-partial')).toBeDefined();
    // The measured FII leg is still rendered…
    expect(screen.getByText('-120.5')).toBeDefined();
    // …while the missing DII leg is a dash, never a fabricated 0.
    expect(screen.getAllByText('\u2014').length).toBeGreaterThan(0);
    expect(screen.queryByText('0')).toBeNull();
    const missing = screen.getByTestId('flows-missing-categories');
    expect(missing.textContent).toContain('DII');
    expect(missing.textContent).toContain('never read as a zero flow');
  });

  it('never shows a zero-flow success for an unavailable flow component', async () => {
    stubRoutes(UNAVAILABLE_FLOWS, UNAVAILABLE_DELIVERY, { data_status: 'unavailable', positions: [] });
    await renderPage();

    expect(screen.getByTestId('flows-unavailable')).toBeDefined();
    expect(screen.queryByText(/No institutional flow records are stored/)).toBeNull();
  });

  it('dates each card from its own stored records, never from the fetch clock', async () => {
    stubRoutes(
      { ...UNAVAILABLE_FLOWS, data_status: 'partial', as_of: '2026-09-22' },
      { ...UNAVAILABLE_DELIVERY, as_of: null },
      {
        data_status: 'available',
        latest_observation_date: '2026-09-24',
        positions: [
          {
            ticker: 'SBIN.NS',
            position_value: 250000,
            adv_30d_rupees: 90000000,
            days_to_liquidate_10pct_adv: 0.28,
            days_to_liquidate_20pct_adv: 0.14,
            liquidity_tier: 'HIGHLY_LIQUID',
            data_status: 'available',
          },
        ],
      },
    );
    await renderPage();

    expect(screen.getByTestId('flow-as-of').textContent).toContain('2026-09-22');
    expect(screen.getByTestId('liquidity-as-of').textContent).toContain('2026-09-24');
    // No server date -> say the records do not provide one, never "now".
    expect(screen.getByTestId('delivery-as-of').textContent).toContain(
      'do not publish an observation date',
    );
    expect(screen.queryByText(/As of \d{1,2}:\d{2}/)).toBeNull();
  });

  it('badges partially and unavailable liquidity rows by their own data_status', async () => {
    stubRoutes(UNAVAILABLE_FLOWS, UNAVAILABLE_DELIVERY, {
      data_status: 'partial',
      latest_observation_date: '2026-09-24',
      positions: [
        {
          ticker: 'TCS.NS',
          position_value: 250000,
          adv_30d_rupees: 90000000,
          days_to_liquidate_10pct_adv: 0.28,
          days_to_liquidate_20pct_adv: 0.14,
          liquidity_tier: 'HIGHLY_LIQUID',
          data_status: 'available',
        },
        {
          ticker: 'INFY.NS',
          position_value: 250000,
          adv_30d_rupees: null,
          days_to_liquidate_10pct_adv: null,
          days_to_liquidate_20pct_adv: null,
          liquidity_tier: 'UNAVAILABLE',
          data_status: 'unavailable',
        },
      ],
    });
    await renderPage();

    expect(screen.getByTestId('liquidity-partial')).toBeDefined();
    // The measured row keeps its own tier…
    expect(screen.getByTestId('liquidity-row-TCS.NS').textContent).toContain('HIGHLY_LIQUID');
    expect(screen.queryByTestId('liquidity-row-status-TCS.NS')).toBeNull();
    // …while the unmeasured row is badged and never shows a 0-day liquidation.
    const partial = screen.getByTestId('liquidity-row-status-INFY.NS');
    expect(partial.textContent).toBe('unavailable');
    const infy = screen.getByTestId('liquidity-row-INFY.NS');
    expect(infy.textContent).toContain('UNAVAILABLE');
    expect(infy.textContent).not.toContain('0d');
  });

  it('surfaces a fetch failure as an error instead of an empty success', async () => {
    getMock.mockRejectedValue(new Error('India microstructure endpoint down'));
    render(<IndiaFlowsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('india-flows-error')).toBeDefined();
    });
    expect(screen.queryByText(/delivery spikes detected/)).toBeNull();
  });
});
