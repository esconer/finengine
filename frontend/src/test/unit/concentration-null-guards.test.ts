/**
 * An absent measurement is `null` on this wire, so an absent value is tested
 * with `== null` / `!= null` — never with `!== undefined`, never with
 * truthiness.
 *
 * `get_concentration_metrics` publishes `herfindahl_index: None` for a book with
 * no holdings (`analytics.py`, both the route's own empty branch and
 * `_empty_concentration()` in the engine, which the route's MEASURED branch still
 * forwards through `.get("herfindahl_index", 0.0)` — `.get` returns the stored
 * `None` because the key IS present, so the default never applies). `0.0` there
 * was never reachable as a measurement: HHI = Σw² ≥ 1/n > 0 for every non-empty
 * book, so it could only ever mean "unmeasured", while `risk_scoring` was feeding
 * it straight into `min(30, herfindahl_index * 100)` and scoring the refusal as
 * the SAFEST book there is.
 *
 * Two wrong spellings of "is this measured?", both of which this net pins shut:
 *
 *   1. `field !== undefined` — `null !== undefined` is `true`, so a null walks
 *      into the MEASURED branch and gets formatted. This is the site the four
 *      metric cards carried. The damage is latent rather than visible: both
 *      `formatPercentage` and `formatRatio` open with their own
 *      `value === null` check, so the call happens to return `N/A` anyway. What
 *      the wrong operator buys is the removal of the site's OWN refusal — the
 *      reason the call cannot throw is a coincidence of two local helpers, and
 *      `formatRatio`'s signature invites the total-on-`number` rewrite that turns
 *      `null.toFixed()` into a page crash. The guard is the contract; the
 *      formatter's tolerance is not.
 *
 *   2. `field && …` — `0` is falsy, so it DROPS a measured zero. `0.0` is a real
 *      measurement in this domain (a single-holding book measures
 *      `diversification_score: 0.0`), which is exactly why a truthiness guard is
 *      the same fabrication as the null one, reversed.
 *
 * The rendering half lives in `pages/ConcentrationHerfindahlNull.test.tsx`:
 * a null HHI renders `N/A`, and a measured zero still renders its number. THIS
 * file is the net for a guard ADDED to this page without that knowledge — the
 * failure mode is a source pattern, not a rendered value, so it is checked
 * against the source.
 *
 * Scoped to `concentration/page.tsx` deliberately, like
 * `row-original-fallback.test.ts`: a repo-wide sweep fails on pages that have not
 * been swept, which turns the net into noise. Widen it when those pages land.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/** The page under the net, and the two declarations that describe its wire. */
const PAGE = 'src/app/dashboard/concentration/page.tsx';
const TYPES = 'src/types/index.ts';

/**
 * Comments are blanked, not deleted: these files carry comments that DISCUSS the
 * guards by name, and a naive search would flag its own explanation as the
 * regression it guards against — while a deleted comment would shift every line
 * number and make the failure message point somewhere the reader cannot look.
 * Same approach as `row-original-fallback.test.ts`.
 */
const read = (path: string): string =>
  readFileSync(resolve(process.cwd(), path), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, block => block.replace(/[^\n]/g, ' '))
    .replace(/(^|[^:])\/\/[^\n]*/gm, (match, prefix) => prefix + ' '.repeat(match.length - prefix.length));

const page = read(PAGE);
const types = read(TYPES);

/**
 * The MEASUREMENT fields `ConcentrationData` declares, read from the interface
 * rather than from a hand-written list: a field added tomorrow is covered
 * automatically, with no edit here.
 *
 * Only fields whose declared type is a scalar `number`. A string or map field
 * guarded with `data.error || '…'` or `data.by_weight || {}` is a MISSING COPY
 * with a literal stand-in, not a refused measurement, and flagging those would
 * make this net noise nobody keeps running. The rule this file is about is "a
 * number the engine refused is not a number", and that is only true of a scalar
 * measurement field — hence the anchored `:\s*number`, which excludes
 * `by_weight: Record<string, number | null>`.
 */
const CONCENTRATION_DATA_BODY = page.match(/interface ConcentrationData \{([\s\S]*?)\n\}/)?.[1] ?? '';
const measurementFields = [...CONCENTRATION_DATA_BODY.matchAll(/^\s{2}(\w+)\??\s*:\s*number[^;]*;/gm)]
  .map(m => m[1]);

/** `field && …` / `field || …` — a truthiness guard on a measurement field. */
const truthinessGuard = (source: string, field: string): boolean =>
  new RegExp(String.raw`\b${field}\s*(&&|\|\|)`).test(source);

/**
 * `!== undefined` used as an absent-value test.
 *
 * Only the `!==` direction. `=== undefined` inside a helper that DECLARES
 * `value: number | undefined | null` (`formatPercentage`, `formatRatio`) is
 * normalization inside the helper, not a site guard, and is left alone. What this
 * net is about is a site deciding "this field was measured" — and that decision
 * can never be `!== undefined`, because the backend publishes absence as `null`.
 */
const undefinedComparison = (source: string): boolean => /!==\s*undefined\b/.test(source);

/** The declaration of one field inside an interface body. */
const declaration = (source: string, body: RegExp, field: string): string | null =>
  source.match(body)?.[0].match(new RegExp(String.raw`^\s*${field}\??\s*:[^;]*;`, 'm'))?.[0].trim() ?? null;

describe('concentration — an absent value is tested with == null, never with undefined', () => {
  it('reads the page, and found the measurement fields to check', () => {
    // A regex typo that emptied this list would turn every assertion below
    // into a permanently-green no-op, which is worse than no test at all.
    expect(page.length).toBeGreaterThan(0);
    expect(measurementFields.length).toBeGreaterThan(0);
    expect(measurementFields).toContain('herfindahl_index');
    expect(measurementFields).toContain('largest_position');
    expect(measurementFields).toContain('diversification_score');
    // A non-numeric field must NOT be swept in: `data.error || '…'` is a missing
    // COPY with a literal stand-in, not a refused measurement — and neither is a
    // map field, whose null lives in its VALUES (handled by `finiteOrNull`).
    expect(measurementFields).not.toContain('error');
    expect(measurementFields).not.toContain('methodology');
    expect(measurementFields).not.toContain('by_weight');
  });

  it('carries no `!== undefined` absent-value test', () => {
    const offenders = page
      .split('\n')
      .map((line, index) => ({ line: line.trim(), at: index + 1 }))
      .filter(({ line }) => undefinedComparison(line));
    expect(
      offenders,
      `The backend publishes absent measurements as \`null\`, and \`null !== undefined\`\n` +
      `is \`true\`, so this walks a null into the MEASURED branch and formats it.\n` +
      `Use \`== null\` / \`!= null\`, as every other read on this page already does.\n` +
      `Offenders:\n` +
      offenders.map(o => `  ${PAGE}:${o.at}  ${o.line}`).join('\n')
    ).toEqual([]);
  });

  it('guards no measurement field with truthiness', () => {
    const offenders = measurementFields.filter(field => truthinessGuard(page, field));
    expect(
      offenders,
      `These fields are guarded by truthiness, so a MEASURED 0 is dropped exactly as a\n` +
      `null would be:\n  ${offenders.join('\n  ')}\n` +
      `A single-holding book measures \`diversification_score: 0.0\`, and the repo's own\n` +
      `invariant is that it must strictly render 0%. Use \`!= null\`.`
    ).toEqual([]);
  });

  it('declares herfindahl_index as `number | null` in BOTH wire declarations', () => {
    // The page reads the response as `as ConcentrationData`, and
    // `lib/api.ts` types the endpoint as `ConcentrationMetrics`, so the payload
    // is checked against NEITHER at the call site. A wrong declaration here is
    // therefore silent: `tsc` cannot catch it, which is why it is pinned here.
    const pageDecl = declaration(page, /interface ConcentrationData \{[\s\S]*?\n\}/, 'herfindahl_index');
    const typesDecl = declaration(types, /interface ConcentrationMetrics \{[\s\S]*?\n\}/, 'herfindahl_index');
    expect(pageDecl, `${PAGE} declares no herfindahl_index`).not.toBeNull();
    expect(typesDecl, `${TYPES} declares no herfindahl_index`).not.toBeNull();
    for (const [where, decl] of [[PAGE, pageDecl], [TYPES, typesDecl]] as const) {
      expect(
        decl,
        `${where} declares \`${decl}\`. The route publishes \`herfindahl_index: None\`\n` +
        `for a book with no holdings, so \`number\` describes a wire shape that does not\n` +
        `exist — and it is the null that \`!= null\` guards read.`
      ).toBe('herfindahl_index: number | null;');
    }
  });
});

/**
 * The four assertions above are only worth reading if they CAN fail. Each
 * detector is therefore exercised against a synthetic sample carrying the
 * pattern it exists to catch.
 */
describe('concentration — the detectors above can actually fail', () => {
  it('flags `!== undefined`, and only that comparison', () => {
    for (const sample of [
      'concentrationData?.herfindahl_index !== undefined ? f() : "N/A"',
      'concentrationData?.top_3 !== undefined',
      'if (data.effective_positions !== undefined) {}',
    ]) {
      expect(undefinedComparison(sample), `should flag: ${sample}`).toBe(true);
    }
    // The nullish comparisons this page actually uses must NOT be flagged, or
    // the net produces noise nobody keeps running.
    for (const sample of [
      'concentrationData?.herfindahl_index != null ? f() : "N/A"',
      'concentrationData?.herfindahl_index == null ? "N/A" : g()',
      // A helper that DECLARES `number | undefined | null` normalizing its own
      // input is not a site guard, and there are two of them on this page.
      'if (value === undefined || value === null || isNaN(value)) return "N/A";',
      'value: number | undefined;',
      'value: concentrationData?.largest_position,',
    ]) {
      expect(undefinedComparison(sample), `should NOT flag: ${sample}`).toBe(false);
    }
  });

  it('flags a truthiness guard on a wire field, and not a real boolean test', () => {
    expect(truthinessGuard('{a.herfindahl_index && a.herfindahl_index < 0.2 && (', 'herfindahl_index')).toBe(true);
    expect(truthinessGuard('{a.diversification_score || 0}', 'diversification_score')).toBe(true);
    // Measured values compared against a threshold are legal — the threshold is
    // a REAL number, so `0.05 < 0.10` is a false claim and must still evaluate.
    expect(truthinessGuard('a.largest_position > 0.15', 'largest_position')).toBe(false);
    expect(truthinessGuard('a.top_3 != null && a.top_3 < 0.5', 'top_3')).toBe(false);
    expect(truthinessGuard('a.effective_positions == null', 'effective_positions')).toBe(false);
    // A different field's name must not trip this field's detector.
    expect(truthinessGuard('a.herfindahl_index && x', 'effective_positions')).toBe(false);
  });

  it('reports a wrong declaration rather than a missing one', () => {
    const body = (decl: string) => `interface ConcentrationMetrics {\n  herfindahl_index: ${decl};\n}\n`;
    const src = body('number');
    const found = declaration(src, /interface ConcentrationMetrics \{[\s\S]*?\n\}/, 'herfindahl_index');
    expect(found).toBe('herfindahl_index: number;');
    expect(found).not.toBe('herfindahl_index: number | null;');
  });
});
