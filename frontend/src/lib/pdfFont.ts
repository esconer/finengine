/**
 * The font the PDF exports are written in, and the glyph guard that goes with it.
 *
 * WHY THIS EXISTS
 * ---------------
 * jsPDF's built-in Helvetica is a base-14 font: it is WinAnsi-encoded and has
 * no U+20B9. Writing a rupee sign through it does NOT throw. jsPDF emits the
 * character's low byte, `0xB9`, which WinAnsi renders as `¹`. The export
 * "succeeds" and a document stamped CONFIDENTIAL prints `¹12,34,567.89`.
 * A silent wrong symbol in a financial document is worse than an exception,
 * because nothing goes red.
 *
 * So the font is embedded, and — because embedding alone would only move the
 * failure to a different glyph — every string is checked against the font's
 * REAL cmap before it reaches the page. A character the font cannot draw is an
 * explicit error, never a substituted one.
 *
 * THE FONT
 * --------
 * Noto Sans, SIL Open Font License 1.1 (`/fonts/OFL.txt`, shipped alongside).
 * Subset with fontTools to the characters these exports can print: ASCII,
 * Latin-1 supplement, general punctuation (– — ' ' " " … and the U+202F
 * narrow no-break space newer ICU emits before en-US/en-IN dayparts), the
 * currency-symbols block U+20A0–U+20C0 (₹ is U+20B9) and the true minus.
 *
 * Two real weights, because the document uses bold for its headings and
 * registering a regular-outline program under a bold style would be its own
 * silent lie.
 *
 * WHY `public/` AND A LAZY `import()`
 * -----------------------------------
 * A URL string is not a bundle entry. The 53 KB of TTF is fetched the first
 * time somebody exports a PDF and never enters the JavaScript bundle, so
 * readers who never export never download it. The module is reached only
 * through `await import('./pdfFont')` from the export path.
 */

import type { jsPDF } from 'jspdf';

export const PDF_FONT_FAMILY = 'DaisyExport';

export type PdfFontStyle = 'normal' | 'bold';

interface FontAsset {
    /** The name the bytes are filed under in jsPDF's virtual file system. */
    readonly vfsName: string;
    /** Where the bytes are served from. Never bundled. */
    readonly url: string;
    readonly style: PdfFontStyle;
}

const FONT_ASSETS: readonly FontAsset[] = [
    { vfsName: 'DaisyExport-Regular.ttf', url: '/fonts/DaisyExport-Regular.ttf', style: 'normal' },
    { vfsName: 'DaisyExport-Bold.ttf', url: '/fonts/DaisyExport-Bold.ttf', style: 'bold' },
];

export interface PdfFont {
    /**
     * The family name to hand `setFont`. Carried on the font rather than
     * imported separately at each call site, so a caller can never set a
     * family that does not match the bytes it just registered.
     */
    readonly family: string;
    /** Base64 TTF per style, the exact form `addFileToVFS` takes. */
    readonly base64: Readonly<Record<PdfFontStyle, string>>;
    /**
     * Every codepoint the embedded program can actually draw, read out of its
     * own cmap table rather than declared here, so the guard can never drift
     * away from the bytes that get embedded.
     */
    readonly covered: ReadonlySet<number>;
    /** Put the font into jsPDF's virtual FS and register both styles. */
    register(doc: jsPDF): void;
    /**
     * Throw unless every character of `text` is one the font can draw.
     * `where` names the part of the document, so the message points at the
     * field to fix rather than at the font. Carried on the font so the check
     * cannot be bypassed by reaching for `doc.text` from a new call site.
     */
    assertRenders(text: string, where: string): void;
}

// ---------------------------------------------------------------------------
// cmap reader
// ---------------------------------------------------------------------------

/**
 * Walk one cmap format-4 subtable (TrueType's Unicode BMP encoding) into
 * `covered`. Codepoints whose glyph id is 0 are .notdef — the reader would
 * draw nothing or a box, which is not the same as drawing the character, so
 * they count as uncovered.
 */
function readFormat4Subtable(view: DataView, offset: number, covered: Set<number>): void {
    const segCountX2 = view.getUint16(offset + 6);
    const segCount = segCountX2 / 2;
    const endBase = offset + 14;
    const startBase = endBase + segCountX2 + 2;
    const deltaBase = startBase + segCountX2;
    const rangeBase = deltaBase + segCountX2;

    for (let seg = 0; seg < segCount; seg += 1) {
        const end = view.getUint16(endBase + seg * 2);
        const start = view.getUint16(startBase + seg * 2);
        const delta = view.getUint16(deltaBase + seg * 2);
        const rangeOffset = view.getUint16(rangeBase + seg * 2);
        if (start === 0xffff || start > end) continue;
        for (let code = start; code <= end && code !== 0x10000; code += 1) {
            let glyph: number;
            if (rangeOffset === 0) {
                glyph = (code + delta) & 0xffff;
            } else {
                const at = rangeBase + seg * 2 + rangeOffset + (code - start) * 2;
                if (at + 1 >= view.byteLength) continue;
                glyph = view.getUint16(at);
                if (glyph !== 0) glyph = (glyph + delta) & 0xffff;
            }
            if (glyph !== 0) covered.add(code);
        }
    }
}

/**
 * The codepoints this TTF can draw, from its `cmap`.
 *
 * Only the subtables jsPDF itself consults are counted. jsPDF's TTF reader
 * (`jspdf.es.js`, `CmapEntry.isUnicode`) walks format 4 only, and treats a
 * subtable as Unicode when it is (3,1) or (0,*). A glyph reachable only
 * through, say, a format-12 subtable would not be found when the text is
 * written, so counting it here would promise coverage the export does not have.
 */
export function readCoveredCodepoints(font: Uint8Array): Set<number> {
    const covered = new Set<number>();
    if (font.byteLength < 12) return covered;
    const view = new DataView(font.buffer, font.byteOffset, font.byteLength);
    const numTables = view.getUint16(4);

    let cmapOffset = -1;
    for (let i = 0; i < numTables; i += 1) {
        const record = 12 + i * 16;
        if (record + 16 > font.byteLength) break;
        const tag = String.fromCharCode(
            font[record], font[record + 1], font[record + 2], font[record + 3],
        );
        if (tag === 'cmap') cmapOffset = view.getUint32(record + 8);
    }
    if (cmapOffset < 0) return covered;

    const subtableCount = view.getUint16(cmapOffset + 2);
    for (let i = 0; i < subtableCount; i += 1) {
        const record = cmapOffset + 4 + i * 8;
        const platformId = view.getUint16(record);
        const encodingId = view.getUint16(record + 2);
        const subtable = cmapOffset + view.getUint32(record + 4);
        if (view.getUint16(subtable) !== 4) continue;
        if (!((platformId === 3 && encodingId === 1) || platformId === 0)) continue;
        readFormat4Subtable(view, subtable, covered);
    }
    return covered;
}

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------

function bytesToBase64(bytes: Uint8Array): string {
    let binary = '';
    // Chunked: String.fromCharCode(...bytes) blows the argument limit on a
    // font-sized buffer.
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
        binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
    }
    return btoa(binary);
}

async function fetchFontBytes(asset: FontAsset): Promise<Uint8Array> {
    const response = await fetch(asset.url);
    if (!response.ok) {
        throw new Error(
            `PDF font ${asset.url} could not be loaded (HTTP ${response.status}). ` +
                'Refusing to export: without it, jsPDF falls back to a font that silently ' +
                'prints a different character for the rupee sign.'
        );
    }
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength === 0) {
        throw new Error(`PDF font ${asset.url} loaded as 0 bytes.`);
    }
    return bytes;
}

/**
 * Fetch both weights and work out what they can draw.
 *
 * Deliberately not memoised: an export is a user-initiated one-shot behind a
 * button, the browser HTTP-caches the TTF anyway, and a module-level cache
 * would be a stale-font trap in tests for no measurable gain.
 */
export async function loadPdfFont(): Promise<PdfFont> {
    const base64 = {} as Record<PdfFontStyle, string>;
    // Coverage is kept PER STYLE, not unioned. A style is what actually draws
    // a run, so unioning would let a glyph present only in the bold outline be
    // promised to a normal-weight run. The two subsets come from one codepoint
    // list; the equality is checked here rather than assumed.
    const perStyle = {} as Record<PdfFontStyle, Set<number>>;

    for (const asset of FONT_ASSETS) {
        const bytes = await fetchFontBytes(asset);
        perStyle[asset.style] = readCoveredCodepoints(bytes);
        base64[asset.style] = bytesToBase64(bytes);
    }

    const regular = perStyle[FONT_ASSETS[0].style];
    const bold = perStyle[FONT_ASSETS[1].style];
    for (const code of regular) {
        if (!bold.has(code)) {
            throw new Error(
                'The embedded PDF font weights cover different characters at U+' +
                    code.toString(16).toUpperCase() +
                    '. Refusing to export rather than print a substituted glyph.'
            );
        }
    }
    if (regular.size !== bold.size) {
        throw new Error(
            'The embedded PDF font weights cover different numbers of characters (' +
                regular.size + ' vs ' + bold.size +
                '). Refusing to export rather than print a substituted glyph.'
        );
    }
    const covered = regular;

    if (!covered.has(0x20b9)) {
        throw new Error(
            'The embedded PDF font has no U+20B9 (₹) glyph. Refusing to export a document ' +
                'whose currency amounts would be printed with a substituted character.'
        );
    }

    const font: PdfFont = {
        family: PDF_FONT_FAMILY,
        base64,
        covered,
        register(doc) {
            for (const asset of FONT_ASSETS) {
                doc.addFileToVFS(asset.vfsName, base64[asset.style]);
                doc.addFont(asset.vfsName, PDF_FONT_FAMILY, asset.style);
            }
            // Default so a text call that forgets to set a style still writes
            // with the embedded font rather than Helvetica.
            doc.setFont(PDF_FONT_FAMILY, 'normal');
        },
        assertRenders(text, where) {
            assertPdfFontRenders(font, text, where);
        },
    };
    return font;
}

// ---------------------------------------------------------------------------
// The guard
// ---------------------------------------------------------------------------

export function unrenderableCodepoints(font: PdfFont, text: string): number[] {
    const missing = new Set<number>();
    for (const character of text) {
        const code = character.codePointAt(0);
        if (code === undefined || !font.covered.has(code)) missing.add(code ?? 0);
    }
    return [...missing].sort((a, b) => a - b);
}

function describeCodepoint(code: number): string {
    const hex = code.toString(16).toUpperCase().padStart(4, '0');
    return `U+${hex} ${JSON.stringify(String.fromCodePoint(code))}`;
}

/**
 * Refuse to write a character the embedded font cannot draw.
 *
 * `where` names the part of the document, so the message points at the field
 * to fix rather than at the font.
 */
export function assertPdfFontRenders(font: PdfFont, text: string, where: string): void {
    const missing = unrenderableCodepoints(font, text);
    if (missing.length === 0) return;
    throw new Error(
        `PDF export cannot print ${missing.map(describeCodepoint).join(', ')} in the ${where}. ` +
            'The embedded font has no glyph for it, and jsPDF\'s built-in Helvetica would print ' +
            'a different character for some of these rather than fail. Refusing to export.'
    );
}
