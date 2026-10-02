/**
 * A withheld copula cell renders as an ABSENCE, not as a zero.
 *
 * `calculate_bivariate_tail_dependence` publishes `matrix[i][j] = null` when
 * Pearson rho is undefined — a zero-dispersion leg (a frozen or single-row
 * series), or a failed marginal Student-t fit. `null` there is not an
 * unfilled cell: `0.0` is the STRONGEST available claim in this domain, "these
 * two never crash together", and it is the exact opposite of unknown.
 *
 * The page's per-cell `copulaMatrix[rowIdx]?.[colIdx] ?? (rowIdx === colIdx ?
 * 1.0 : 0.0)` therefore turned a correct refusal back into a verdict and
 * painted it on the emerald "these two do not crash together" band. The coarse
 * `copulaTickers.length > 0 && copulaMatrix.length > 0` guard did not help: it
 * asks whether the matrix is non-empty, not whether a cell is.
 *
 * Two things must hold, and the second is the one a naive fix erases:
 *
 *   1. an unmeasured off-diagonal cell is `N/A`, carries NO verdict band, and
 *      exports `N/A`;
 *   2. a MEASURED cell — including a measured `0.0`, which is a real λL of
 *      "measured, and the joint lower tail really is negligible" — keeps its
 *      number and its band. A falsy-guard would pass case 1 and silently erase
 *      every independent pair, which is the same fabrication reversed.
 *
 * The diagonal is a third case and is argued in the page itself: λL = 1 for a
 * self-pair is a DEFINITION (a series always fully crashes with itself), not a
 * measurement, so it keeps `1.000` and its deliberately neutral slate band.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  default: { get: mocks.apiGet },
  analyticsApi: {},
  portfolioApi: {},
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.apiGet.mockResolvedValue({ data: {} });
});

/**
 * FLAT is frozen, so every pair it is in is unmeasurable. REAL ↔ DRIFT is a
 * measured 0.07 — a real λL, and it must survive this fix untouched.
 */
const WITHHELD_MATRIX = {
  tickers: ['FLAT.NS', 'REAL.NS', 'DRIFT.NS'],
  matrix: [
    [1.0, null, null],
    [null, 1.0, 0.07],
    [null, 0.07, 1.0],
  ],
  unmeasurable_pairs: [
    { pair: ['FLAT.NS', 'REAL.NS'], reason: 'zero_dispersion_leg' },
    { pair: ['FLAT.NS', 'DRIFT.NS'], reason: 'zero_dispersion_leg' },
  ],
};

/** Installs the copula leg; every other endpoint answers an empty payload. */
const serveTailRisk = (tailDependenceMatrix: unknown) => {
  mocks.apiGet.mockImplementation((url: string) =>
    Promise.resolve({
      data: url.includes('tail-dependence')
        ? { tail_dependence_matrix: tailDependenceMatrix, warnings: [] }
        : {},
    })
  );
};

/**
 * The page has exactly one table: the copula matrix. Indexed off `tBodies`, not
 * `rows`, because `table.rows` also carries the `<thead>` row. Column 0 of a
 * body row is the row label, so data column `col` is `cells[col + 1]`.
 */
const cell = (row: number, col: number): HTMLTableCellElement =>
  ((screen.getByRole('table') as HTMLTableElement).tBodies[0].rows[row]
    .cells[col + 1] as HTMLTableCellElement);

/** The CSV the page hands to a data: URI on "Export CSV". */
const exportCsv = async (): Promise<string> => {
  const clicked: HTMLAnchorElement[] = [];
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });
  try {
    render(await pageUnderTest());
    const exportBtn = await screen.findByText('Export CSV');
    await waitFor(() => {
      expect((exportBtn as HTMLButtonElement).disabled).toBe(false);
    });
    fireEvent.click(exportBtn);
    expect(clicked).toHaveLength(1);
    return decodeURIComponent(clicked[0].getAttribute('href')!);
  } finally {
    clickSpy.mockRestore();
  }
};

/**
 * The page module is imported lazily so each case pays the module cost on its
 * own budget rather than the file's first-import budget (see the same note in
 * `AbsentValueRendering.test.tsx`).
 */
const pageUnderTest = async (): Promise<React.ReactElement> => {
  const mod = await import('@/app/dashboard/risk-studio/page');
  const Page = mod.default;
  return <Page />;
};

const RENDER_TIMEOUT = 30_000;

describe('risk-studio — a withheld copula cell is N/A, never a 0.000 verdict', () => {
  it('renders the withheld off-diagonal as N/A with no colour band', async () => {
    serveTailRisk(WITHHELD_MATRIX);

    render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });

    // RED on the shipped code: `?? (r === c ? 1.0 : 0.0)` published "0.000".
    const withheld = cell(0, 1);
    expect(withheld.textContent).toBe('N/A');
    expect(withheld.textContent).not.toContain('0.000');
    // Emerald says "these two do not crash together"; rose says the opposite.
    // Neither is supported, so the cell takes neither — and no other band that
    // asserts a measurement.
    const cls = withheld.getAttribute('class') ?? '';
    expect(cls).not.toContain('emerald');
    expect(cls).not.toContain('rose');
    expect(cls).not.toContain('amber');
  }, RENDER_TIMEOUT);

  it('withholds BOTH cells of a symmetric pair, not just the upper triangle', async () => {
    serveTailRisk(WITHHELD_MATRIX);

    render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });
    // matrix[1][0] is null too. A fix written as "the upper triangle" would
    // leave the lower triangle still publishing 0.000.
    expect(cell(1, 0).textContent).toBe('N/A');
    expect(cell(0, 2).textContent).toBe('N/A');
    expect(cell(2, 0).textContent).toBe('N/A');
  }, RENDER_TIMEOUT);

  it('still renders a MEASURED off-diagonal cell with its band and its number', async () => {
    serveTailRisk(WITHHELD_MATRIX);

    render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });
    // The other half of the rule. A guard written as `num || 'N/A'` would pass
    // the withheld cases and erase every genuinely independent pair.
    const measured = cell(1, 2);
    expect(measured.textContent).toBe('0.070');
    expect(measured.getAttribute('class')).toContain('emerald');
  }, RENDER_TIMEOUT);

  it('keeps a measured 0.000 as a real number on the emerald band', async () => {
    // A measured λL of exactly 0.0 is a measurement the engine made: it fitted
    // both legs and found no joint lower-tail overlap. It is emphatically NOT
    // the same as a withheld cell, and the two must not render identically.
    serveTailRisk({
      tickers: ['A.NS', 'B.NS', 'C.NS'],
      matrix: [
        [1.0, 0.0, 0.4],
        [0.0, 1.0, null],
        [0.4, null, 1.0],
      ],
      unmeasurable_pairs: [{ pair: ['B.NS', 'C.NS'], reason: 'marginal_t_fit_failed' }],
    });

    render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });
    expect(cell(0, 1).textContent).toBe('0.000');
    expect(cell(1, 0).textContent).toBe('0.000');
    expect(cell(0, 1).getAttribute('class')).toContain('emerald');
    // …while the withheld cell in the SAME matrix stays N/A and uncoloured.
    expect(cell(1, 2).textContent).toBe('N/A');
    expect(cell(2, 1).textContent).toBe('N/A');
    // A measured 0.4 still paints rose.
    expect(cell(0, 2).textContent).toBe('0.400');
    expect(cell(0, 2).getAttribute('class')).toContain('rose');
  }, RENDER_TIMEOUT);

  it('names the withheld pair and the backend\'s reason', async () => {
    serveTailRisk({
      tickers: ['A.NS', 'B.NS'],
      matrix: [[1.0, null], [null, 1.0]],
      unmeasurable_pairs: [{ pair: ['A.NS', 'B.NS'], reason: 'marginal_t_fit_failed' }],
    });

    render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });
    // The backend hands over `reason` so an absent cell is readable. An N/A the
    // reader cannot account for is one they will assume is a bug.
    const note = screen.getByTestId('copula-unmeasurable-pairs');
    expect(note.textContent).toContain('A.NS');
    expect(note.textContent).toContain('B.NS');
    expect(note.textContent).toMatch(/fit/i);
  }, RENDER_TIMEOUT);

  it('keeps the withheld cell N/A when the backend publishes no reason list', async () => {
    // A payload with no `unmeasurable_pairs` (an older engine, or a route that
    // failed to pass it through). The cell is still unmeasured and must still
    // render as an absence — the reason is a nicety, never a precondition for
    // withholding the number.
    serveTailRisk({
      tickers: ['A.NS', 'B.NS'],
      matrix: [[1.0, null], [null, 1.0]],
    });

    render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });
    expect(cell(0, 1).textContent).toBe('N/A');
    expect(cell(0, 1).getAttribute('class')).not.toContain('emerald');
    expect(screen.queryByTestId('copula-unmeasurable-pairs')).toBeNull();
  }, RENDER_TIMEOUT);

  it('keeps a pair with no stated reason in the count rather than dropping it', async () => {
    // The backend always pairs a withheld cell with a reason, but a pair
    // missing one is still a withheld pair. Silently dropping it would
    // under-count the holes in the matrix — the same erasure the N/A exists to
    // stop — so it is counted and its reason shows this file's own em dash.
    serveTailRisk({
      tickers: ['A.NS', 'B.NS', 'C.NS'],
      matrix: [[1.0, null, null], [null, 1.0, 0.2], [null, 0.2, 1.0]],
      unmeasurable_pairs: [
        { pair: ['A.NS', 'B.NS'] },
        { pair: ['A.NS', 'C.NS'], reason: 'zero_dispersion_leg' },
        { not_a_pair: true },
      ],
    });

    render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });
    const note = screen.getByTestId('copula-unmeasurable-pairs');
    // The pair with no stated reason keeps its place in the count and carries
    // this file's own em dash for the missing reason.
    expect(note.textContent).toContain('A.NS ↔ B.NS (—)');
    expect(note.textContent).toContain('A.NS ↔ C.NS (one leg has no dispersion');
    // The malformed entry is not a withheld pair and is not counted.
    expect(note.textContent).toMatch(/withheld for 2\b/);
  }, RENDER_TIMEOUT);

  it('shows no note at all when every pair was measurable', async () => {
    serveTailRisk({
      tickers: ['A.NS', 'B.NS'],
      matrix: [[1.0, 0.31], [0.31, 1.0]],
      unmeasurable_pairs: [],
    });

    render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });
    expect(cell(0, 1).textContent).toBe('0.310');
    expect(screen.queryByTestId('copula-unmeasurable-pairs')).toBeNull();
  }, RENDER_TIMEOUT);
});

describe('risk-studio — the diagonal is a definition, so it keeps 1.000', () => {
  it('prints 1.000 on the self-pair with its neutral band', async () => {
    serveTailRisk(WITHHELD_MATRIX);

    render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });
    // λL(X, X) = 1 is not a measurement: a series always fully crashes with
    // itself, so the claim holds whether or not any fit succeeded. An em-dash
    // there would assert the opposite — that nobody knows whether X crashes
    // with itself — which is false. It is also why the band is deliberately
    // neither rose nor emerald: 1.0 on the shared scale is not a verdict about
    // X crashing with anything else.
    const diag = cell(0, 0);
    expect(diag.textContent).toBe('1.000');
    const cls = diag.getAttribute('class') ?? '';
    expect(cls).not.toContain('emerald');
    expect(cls).not.toContain('rose');
    expect(cell(1, 1).textContent).toBe('1.000');
    expect(cell(2, 2).textContent).toBe('1.000');
  }, RENDER_TIMEOUT);
});

describe('risk-studio — the CSV carries the same absence the table does', () => {
  it('writes N/A for a withheld cell and 1.0000 for the diagonal', async () => {
    serveTailRisk(WITHHELD_MATRIX);

    const csv = await exportCsv();

    // RED on the shipped code: `(… ?? (r === c ? 1.0 : 0.0)).toFixed(4)`
    // published "0.0000" — a 4-decimal, spreadsheet-grade endorsement.
    expect(csv).toContain('"FLAT.NS",1.0000,N/A,N/A');
    expect(csv).toContain('"REAL.NS",N/A,1.0000,0.0700');
    expect(csv).toContain('"DRIFT.NS",N/A,0.0700,1.0000');
    // The measured cell is untouched, and the fabricated four-decimal zero is
    // gone from the export entirely.
    expect(csv).toContain('0.0700');
    expect(csv).not.toContain('0.0000');
  }, RENDER_TIMEOUT);

  it('records the withheld pairs and their reasons in the export too', async () => {
    serveTailRisk({
      tickers: ['A.NS', 'B.NS'],
      matrix: [[1.0, null], [null, 1.0]],
      unmeasurable_pairs: [{ pair: ['A.NS', 'B.NS'], reason: 'marginal_t_fit_failed' }],
    });

    const csv = await exportCsv();

    // A data: URI outlives the page it was downloaded from, so an N/A with no
    // explanation in the file is indistinguishable from a broken export.
    expect(csv).toMatch(/withheld/i);
    expect(csv).toContain('A.NS');
    expect(csv).toMatch(/fit/i);
  }, RENDER_TIMEOUT);

  it('leaves a fully measurable export structurally unchanged', async () => {
    serveTailRisk({
      tickers: ['A.NS', 'B.NS'],
      matrix: [[1.0, 0.31], [0.31, 1.0]],
      unmeasurable_pairs: [],
    });

    const csv = await exportCsv();

    expect(csv).toContain('"A.NS",1.0000,0.3100');
    expect(csv).not.toMatch(/withheld/i);
    expect(csv).not.toContain('N/A,');
  }, RENDER_TIMEOUT);
});

describe('risk-studio — the withheld state is reachable, not dead code', () => {
  it('renders the copula table even when EVERY off-diagonal is withheld', async () => {
    // The coarse guard `copulaTickers.length > 0 && copulaMatrix.length > 0`
    // passes on this payload — the matrix is non-empty — and every real cell in
    // it is null. Nothing may crash and nothing may be fabricated.
    serveTailRisk({
      tickers: ['A.NS', 'B.NS'],
      matrix: [[1.0, null], [null, 1.0]],
      unmeasurable_pairs: [{ pair: ['A.NS', 'B.NS'], reason: 'zero_dispersion_leg' }],
    });

    const { container } = render(await pageUnderTest());

    await waitFor(() => {
      expect(screen.getByRole('table')).toBeDefined();
    });
    expect(within(screen.getByRole('table')).getAllByText('N/A')).toHaveLength(2);
    // The measured diagonal still stands, so the table is not blank.
    expect(cell(0, 0).textContent).toBe('1.000');
    expect(container.textContent).not.toContain('NaN');
  }, RENDER_TIMEOUT);
});