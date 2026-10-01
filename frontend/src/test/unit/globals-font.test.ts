/**
 * Substitute verification for a change that has no visual test.
 *
 * The app downloads Geist through `next/font` and exposes it as
 * `--font-geist-sans`; `globals.css` maps that onto `--font-sans`, and
 * Tailwind's preflight resolves `html { font-family }` from
 * `--default-font-family` -> `--font-sans`. That chain is the whole reason the
 * webfont exists.
 *
 * `body { font-family: Arial, Helvetica, sans-serif }` broke it, and nothing
 * went red: a type selector on `body` beats *inheritance*, so the body and
 * every descendant without its own font declaration rendered Arial while the
 * font was downloaded and thrown away. The failure is silent, so the invariant
 * is asserted against the stylesheet source rather than against a screenshot.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// process.cwd() is the frontend package root under vitest, matching the
// convention in the PDF suites.
const rawCss = readFileSync(resolve(process.cwd(), 'src/app/globals.css'), 'utf8');
// Read, never written: the variable has to exist for the chain above to close.
const layout = readFileSync(resolve(process.cwd(), 'src/app/layout.tsx'), 'utf8');

/**
 * Comments are stripped before matching. The rules in this file carry comments
 * that DISCUSS font-family by name, and a naive substring search would flag its
 * own explanation as the regression it is guarding against. The check has to
 * look at declarations, not at prose about them.
 */
const css = rawCss.replace(/\/\*[\s\S]*?\*\//g, '');

describe('globals.css — the app renders the webfont it downloads', () => {
  it('declares no font-family on body that would beat the --font-sans chain', () => {
    const bodyRule = /\bbody\s*\{[^}]*\}/.exec(css);
    expect(bodyRule, 'globals.css must still style body').not.toBeNull();
    // The specific regression, named, so a re-introduction is unambiguous.
    expect(css).not.toMatch(/font-family\s*:\s*Arial/);
    // And the general form: ANY font-family on body outranks inheritance, so
    // the chain stays broken whichever family gets hardcoded there.
    expect(bodyRule?.[0]).not.toMatch(/font-family/);
    // The body rule must still be doing its actual job, or the check above
    // would pass by the file having been gutted.
    expect(bodyRule?.[0]).toMatch(/background:\s*var\(--background\)/);
    expect(bodyRule?.[0]).toMatch(/color:\s*var\(--foreground\)/);
  });

  it('points --font-sans at the next/font variable, and the variable exists', () => {
    expect(css).toMatch(/--font-sans\s*:\s*var\(--font-geist-sans\)/);
    // Without this the chain dead-ends and the whole assertion is vacuous.
    expect(layout).toMatch(/variable:\s*"--font-geist-sans"/);
  });
});
