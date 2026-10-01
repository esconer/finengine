/**
 * The `row.original || row` fallback must not come back.
 *
 * `constructRow` (table-core/dist/core/rows/constructRow.js:30) assigns
 * `row.original = original` unconditionally, from a required positional
 * parameter, and `Row.original` is a non-optional `TData`
 * (coreRowsFeature.types.d.ts:37). The row's data therefore lives under
 * `original` and nowhere else. The only producer of a `Row` is `accessRows()`
 * in `createCoreRowModel.js:35`, which passes the element straight out of the
 * `data` array — and every one of these pages builds that array with `.map()`
 * over object literals, so `original` is always a truthy object.
 *
 * That makes `row.original || row` pure downside: the right-hand side never
 * fires, so it protects nothing, and it makes `data.ticker` / `data.weight`
 * type-check as `any` when the read slips onto the wrapper. That slip is UA-01
 * (358fb49) — `undefined` formatted into a published-looking figure.
 *
 * The rendering halves of this rule live in `pages/DataTableRowOriginal.test.tsx`
 * (other pages) and in the `liquidity` / `concentration` / `volatility-sizing`
 * blocks of `pages/AbsentValueRendering.test.tsx`. THIS file is the net that
 * catches a new column cell being added without the knowledge of any of them:
 * it reads the page sources, because the failure mode is a source pattern, not a
 * rendered value.
 *
 * Scoped to these pages deliberately. A repo-wide sweep would fail on any page
 * not yet migrated, which turns this net into noise people have to work around
 * rather than a signal. Every page carrying the pattern belongs here; when the
 * last one lands, widen it.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/** The pages whose column cells were migrated off the `|| row` fallback. */
const PAGES = [
  'src/app/dashboard/liquidity/page.tsx',
  'src/app/dashboard/concentration/page.tsx',
  'src/app/dashboard/volatility-sizing/page.tsx',
  // The last two pages to carry the pattern. `dashboard/page.tsx` is the one
  // that needed its column array typed to make the point at all, and
  // `screener-studio/page.tsx` is the one whose row action must keep reading
  // `data.ticker` (the EXCHANGE SUFFIXED field) — a wrapper read there would
  // render `What would undefined do to your portfolio?`.
  'src/app/dashboard/page.tsx',
  'src/app/dashboard/screener-studio/page.tsx',
] as const;

/**
 * The data fields each page's table actually carries, read from its own column
 * declarations rather than from a hand-written list. `constructRow` writes only
 * `original`, `id`, `index`, `depth`, `parentId` and `subRows` onto the row, so
 * EVERY `accessorKey` below names a field the wrapper does not have — reading
 * one off the wrapper yields `undefined`, which is UA-01 (358fb49).
 *
 * Deriving the list is what makes this net durable: a column added tomorrow
 * contributes its own `accessorKey` and is covered automatically, with no edit
 * here.
 */
const ROW_METADATA_FIELDS = ['id', 'index', 'depth', 'parentId', 'subRows', 'original'];

/** The fallback in any spelling: `|| row`, `|| row.original`, `?? row`, … */
const fallbackToWrapper = /\brow\.original\s*(?:\|\||\?\?)\s*row\b/;

/** `cell: ({ row }: any)` — the `any` is half the trap: it silences the error. */
const untypedCellParam = /cell:\s*\(\s*\{\s*row\s*\}\s*:\s*any\s*\)/;

const sources = PAGES.map(path => {
  const source = readFileSync(resolve(process.cwd(), path), 'utf8')
    // Comments are stripped: these files carry comments that DISCUSS the
    // fallback by name, and a naive search would flag its own explanation as
    // the regression it guards against. Same approach as `globals-font.test.ts`.
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
  const dataFields = [...source.matchAll(/accessorKey:\s*['"]([A-Za-z_$][\w$]*)['"]/g)]
    .map(match => match[1])
    // A column legitimately keyed on a real row property is not a defect.
    .filter(field => !ROW_METADATA_FIELDS.includes(field));
  return { path, source, dataFields };
});

/** `row.<field>` for one of this page's data fields — always a wrapper read. */
const wrapperFieldRead = (dataFields: string[]) => {
  const pattern = new RegExp(String.raw`\brow\.(${dataFields.join('|')})\b`);
  return (line: string) => pattern.test(line);
};

describe('row.original — no cell renderer falls back to the row wrapper', () => {
  it(`carries no \`row.original || row\` fallback in any of the ${PAGES.length} pages`, () => {
    const offenders = sources
      .filter(({ source }) => fallbackToWrapper.test(source))
      .map(({ path }) => path);
    expect(
      offenders,
      `These pages read the row wrapper instead of row.original. The right-hand\n` +
      `side of || never fires — row.original is a non-optional TData assigned\n` +
      `unconditionally by constructRow — so it protects nothing and hides the\n` +
      `read. Offenders:\n  ${offenders.join('\n  ')}`
    ).toEqual([]);
  });

  it('reads no page-data field off the `row` wrapper', () => {
    for (const { path, source, dataFields } of sources) {
      // A page with no accessorKey declares no table columns, so there is
      // nothing to check — and nothing for the reader to believe was checked.
      expect(
        dataFields.length,
        `${path} declares no accessorKey, so this assertion would be vacuous.`
      ).toBeGreaterThan(0);
      const isWrapperRead = wrapperFieldRead(dataFields);
      source.split('\n').forEach((line, index) => {
        expect(
          isWrapperRead(line),
          `${path}:${index + 1} reads a table data field off the row wrapper:\n` +
          `  ${line.trim()}\n` +
          `The row wrapper carries only ${ROW_METADATA_FIELDS.join(', ')} — the data\n` +
          `lives under \`original\`. This is UA-01 (358fb49): the read yields\n` +
          `undefined, which the page then formats into a published figure.`
        ).toBe(false);
      });
    }
  });

  it('types every `cell` row parameter instead of falling back to `any`', () => {
    // `DataTableColumn<RealRow>[]` makes `row.original` statically typed, so a
    // falsy `original` is a compile error AT THE DATA ARRAY rather than a
    // runtime NaN%. `: any` deletes that protection and re-opens the trap.
    for (const { path, source } of sources) {
      expect(
        untypedCellParam.test(source),
        `${path} declares \`cell: ({ row }: any)\`. Drop the \`: any\` so the ` +
        `column's declared row type carries through to the cell renderer.`
      ).toBe(false);
    }
  });
});

/**
 * The three cases above are only worth reading if they CAN fail. Each detector
 * is therefore exercised against a synthetic sample carrying the pattern it
 * exists to catch — otherwise a typo in a regex would turn a whole describe
 * block into three permanently-green assertions, which is worse than having no
 * test at all.
 */
describe('row.original — the detectors above can actually fail', () => {
  it('flags every spelling of the fallback, and only the fallback', () => {
    const mustFlag = [
      'const data = row.original || row;',
      'const data = row.original ?? row;',
      'const data = row.original||row;',
    ];
    for (const sample of mustFlag) {
      expect(fallbackToWrapper.test(sample), `should flag: ${sample}`).toBe(true);
    }
    // The clean binding must NOT be flagged, or the net is pure noise.
    expect(fallbackToWrapper.test('const data = row.original;')).toBe(false);
  });

  it('flags a data-field read off the wrapper, but not a legal row read', () => {
    // Built from liquidity's real accessorKeys, so this is the same detector the
    // assertion above runs — not a paraphrase of it that could drift.
    const isWrapperRead = wrapperFieldRead(['ticker', 'score', 'category']);
    expect(isWrapperRead('const t = row.ticker;')).toBe(true);
    expect(isWrapperRead('return <div>{formatCurrency(row.market_cap)}</div>')).toBe(false);
    expect(isWrapperRead('return <div>{formatCurrency(data.market_cap)}</div>')).toBe(false);
    // Row metadata and the row API are legal reads and must not be flagged, or
    // the net produces noise nobody will keep running.
    expect(isWrapperRead('const o = row.original;')).toBe(false);
    expect(isWrapperRead('const i = row.index;')).toBe(false);
    expect(isWrapperRead('return <div>{row.getValue("ticker")}</div>')).toBe(false);
  });

  it('flags an `any`-typed cell parameter but not a typed one', () => {
    expect(untypedCellParam.test('cell: ({ row }: any) => {')).toBe(true);
    expect(untypedCellParam.test('cell: ({ row }) => {')).toBe(false);
  });
});