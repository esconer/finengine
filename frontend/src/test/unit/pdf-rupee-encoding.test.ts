import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { inflateSync } from 'node:zlib';
import { jsPDF } from 'jspdf';
import { ExportService, PDFExporter } from '@/lib/export';
import {
  PDF_FONT_FAMILY,
  readCoveredCodepoints,
  unrenderableCodepoints,
} from '@/lib/pdfFont';

// ===========================================================================
// WHY THIS FILE DOES NOT MOCK jspdf
// ===========================================================================
//
// The defect is a BYTE defect. jsPDF's base-14 Helvetica is WinAnsi-encoded
// and has no U+20B9: writing a rupee sign through it does not throw, it emits
// the character's low byte 0xB9, which WinAnsi renders as a superscript one.
// A double that records `doc.text` arguments cannot see this at all: it sees
// the correct JS string and passes, while the PDF says something else.
//
// `node_modules/canvas` is not installed, so `getContext('2d')` returns null
// in jsdom and pixel assertions are impossible. A test that pretends to check
// them passes without checking anything. These assertions read the serialised
// PDF instead, which is stronger: they read what a reader will actually see.
//
// The only thing faked is where the finished bytes GO. `API.save` is copied
// onto every jsPDF instance as an own property (there is no prototype to spy
// on) and, depending on which build vitest resolves, it either downloads via
// an anchor or writes through `node:fs`. Subclassing the real jsPDF and
// replacing only `save` keeps the whole document pipeline real: font
// embedding, glyph encoding, content streams, the lot.
//
// Everything below decodes the PDF from its own bytes, through its own
// /ToUnicode CMap. No glyph id is hardcoded, so the test does not depend on
// how this particular font happens to number its glyphs.
// ===========================================================================

const captured = vi.hoisted(() => ({ documents: [] as Uint8Array[] }));

vi.mock('jspdf', async (importOriginal) => {
  const actual = await importOriginal<typeof import('jspdf')>();
  class CapturingJsPDF extends actual.jsPDF {
    constructor(options?: unknown) {
      super(options as never);
      // Assigned as an OWN property on purpose: jsPDF copies its API methods
      // onto every instance, so a prototype override would be shadowed and
      // never called.
      (this as { save: (filename?: string) => unknown }).save = () => {
        const out = this.output('arraybuffer') as ArrayBuffer;
        captured.documents.push(new Uint8Array(out.slice(0)));
        return this;
      };
    }
  }
  return { ...actual, jsPDF: CapturingJsPDF };
});

const FONT_DIR = resolve(process.cwd(), 'public', 'fonts');
const REGULAR = readFileSync(resolve(FONT_DIR, 'DaisyExport-Regular.ttf'));
const BOLD = readFileSync(resolve(FONT_DIR, 'DaisyExport-Bold.ttf'));

/** Serves the real asset bytes at the real URLs the loader asks for. */
function stubFontFetch(ok = true, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(
        typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      );
      const bytes = url.endsWith('-Bold.ttf') ? BOLD : url.endsWith('-Regular.ttf') ? REGULAR : null;
      if (!ok || !bytes) {
        return { ok: false, status, arrayBuffer: async () => new ArrayBuffer(0) } as Response;
      }
      const copy = new Uint8Array(bytes.byteLength);
      copy.set(bytes);
      return { ok: true, status: 200, arrayBuffer: async () => copy.buffer } as Response;
    })
  );
}

// ---------------------------------------------------------------------------
// PDF readers
// ---------------------------------------------------------------------------

/** The page content streams: Flate-or-raw streams that contain a text object. */
function pageContentStreams(pdf: Buffer): Buffer[] {
  const raw = pdf.toString('latin1');
  const streams: Buffer[] = [];
  for (const m of raw.matchAll(/<<([\s\S]*?)>>\s*stream\r?\n/g)) {
    const start = m.index + m[0].length;
    const end = raw.indexOf('endstream', start);
    if (end < 0) continue;
    let data = pdf.subarray(start, end);
    if (/FlateDecode/.test(m[1])) {
      try {
        data = inflateSync(data);
      } catch {
        continue;
      }
    }
    const text = data.toString('latin1');
    if (/\bBT\b/.test(text) && /(Tj|TJ)/.test(text)) streams.push(data);
  }
  return streams;
}

/** glyph id -> unicode, read out of the PDF's own /ToUnicode CMap. */
function parseToUnicode(pdf: Buffer): Map<number, number> {
  const map = new Map<number, number>();
  const raw = pdf.toString('latin1');
  for (const block of raw.match(/beginbfchar[\s\S]*?endbfchar/g) ?? []) {
    for (const m of block.matchAll(/<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>/g)) {
      map.set(parseInt(m[1], 16), parseInt(m[2], 16));
    }
  }
  return map;
}

interface PdfTextRun {
  /** The characters a reader will see. */
  text: string;
  /** Raw bytes of the content stream the operator lived in. */
  stream: Buffer;
  /** True when written as Identity-H hex rather than a base-14 literal. */
  hex: boolean;
}

/**
 * Every text run in the document, decoded.
 *
 * Both encodings are handled, and the difference between them is the whole
 * point of this file:
 *  - Identity-H hex `<010d..> Tj`: two-byte glyph ids into the embedded font.
 *  - WinAnsi literal `(...) Tj`: one byte per character, base-14 font. jsPDF
 *    writes an unencodable character's low byte here. That is the bug.
 */
function readTextRuns(pdf: Buffer): PdfTextRun[] {
  const toUnicode = parseToUnicode(pdf);
  const runs: PdfTextRun[] = [];

  for (const stream of pageContentStreams(pdf)) {
    const raw = stream.toString('latin1');
    for (const m of raw.matchAll(/<([0-9A-Fa-f\s]+)>\s*Tj/g)) {
      const compact = m[1].replace(/\s+/g, '');
      let text = '';
      for (let i = 0; i + 3 < compact.length; i += 4) {
        const gid = parseInt(compact.slice(i, i + 4), 16);
        const code = toUnicode.get(gid);
        text += code === undefined ? '�' : String.fromCodePoint(code);
      }
      runs.push({ text, stream, hex: true });
    }
    for (const m of raw.matchAll(/\(((?:\\.|[^()\\])*)\)\s*Tj/g)) {
      const bytes = Buffer.from(m[1], 'latin1');
      let text = '';
      for (let i = 0; i < bytes.length; i += 1) {
        // jsPDF pads base-14 runs to two bytes per character in some paths.
        if (bytes[i] === 0 && i + 1 < bytes.length) {
          text += String.fromCharCode(bytes[i + 1]);
          i += 1;
        } else {
          text += String.fromCharCode(bytes[i]);
        }
      }
      runs.push({ text, stream, hex: false });
    }
  }
  return runs;
}

/**
 * The PostScript name of every font the content stream actually selects.
 *
 * A `Tf` operator names a page resource key (`/F16`), not a font, so each key
 * is resolved through the page's `/Font` resource dictionary to the font
 * object's `/BaseFont`. This matters because jsPDF writes the fourteen
 * base-14 font descriptors whether or not anything uses them, so their mere
 * presence in the file proves nothing about what the text is drawn with.
 */
function selectedBaseFonts(pdf: Buffer): Set<string> {
  const raw = pdf.toString('latin1');
  const used = new Set([...raw.matchAll(/\/(\S+)\s+[\d.]+\s+Tf/g)].map((m) => m[1]));
  const resolved = new Set<string>();
  for (const dict of raw.matchAll(/\/Font\s*<<([\s\S]*?)>>/g)) {
    for (const entry of dict[1].matchAll(/\/(\S+)\s+(\d+)\s+0\s+R/g)) {
      if (!used.has(entry[1])) continue;
      const object = new RegExp('[^0-9]' + entry[2] + ' 0 obj\\s*<<([\\s\\S]*?)>>').exec(raw);
      const baseFont = object ? /\/BaseFont\s*\/([^\s/>\]]+)/.exec(object[1]) : null;
      resolved.add(baseFont ? baseFont[1] : 'unresolved(' + entry[1] + ')');
    }
  }
  return resolved;
}

function allText(pdf: Buffer): string {
  return readTextRuns(pdf)
    .map((r) => r.text)
    .join('\n');
}

/** The bytes of the last document the real export saved. */
function lastDocument(): Buffer {
  const bytes = captured.documents[captured.documents.length - 1];
  if (!bytes) throw new Error('the export never saved a document');
  return Buffer.from(bytes);
}

beforeEach(() => {
  captured.documents.length = 0;
  stubFontFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ===========================================================================
// The asset itself
// ===========================================================================
describe('the embedded font asset', () => {
  it('really contains U+20B9, read from the cmap of the file on disk', () => {
    // Not taken on trust from whatever produced the subset: parsed here,
    // independently, so a font swapped in without the glyph fails the build
    // rather than the reader.
    expect(readCoveredCodepoints(new Uint8Array(REGULAR)).has(0x20b9)).toBe(true);
    expect(readCoveredCodepoints(new Uint8Array(BOLD)).has(0x20b9)).toBe(true);
  });

  it('carries two real, distinct weights', () => {
    expect(REGULAR.byteLength).toBeGreaterThan(1024);
    expect(BOLD.byteLength).toBeGreaterThan(1024);
    // If Bold were Regular, the headings would silently lose their weight
    // while the PDF still declared a bold style.
    expect(Buffer.compare(REGULAR, BOLD)).not.toBe(0);
  });

  it('covers the characters the export actually prints', () => {
    const covered = readCoveredCodepoints(new Uint8Array(REGULAR));
    // Grouped en-IN digits and separators.
    for (const character of '0123456789,.'.split('')) {
      expect(covered.has(character.codePointAt(0)!)).toBe(true);
    }
    // The currency symbol, the punctuation used as literals in export.ts, the
    // daypart separators newer ICU emits, and the other currency symbols
    // `formatCurrency` can produce for a non-INR book.
    for (const character of ['₹', '—', '–', '·', '%', '−', '$', '€', '£', '¥']) {
      expect(covered.has(character.codePointAt(0)!)).toBe(true);
    }
    // U+202F NARROW NO-BREAK SPACE and U+00A0 NO-BREAK SPACE: Chrome's ICU
    // puts one of these before an en-US/en-IN daypart, and several currencies
    // (AED, CHF, SGD) format as "AED 1,234.50" with an NBSP.
    expect(covered.has(0x202f)).toBe(true);
    expect(covered.has(0x00a0)).toBe(true);
  });

  it('ships its licence next to it', () => {
    const ofl = readFileSync(resolve(FONT_DIR, 'OFL.txt'), 'utf8');
    expect(ofl).toMatch(/SIL Open Font License, Version 1\.1/);
    expect(ofl).toMatch(/Noto Project Authors/);
  });
});

// ===========================================================================
// The bug, and the fix, at the byte level
// ===========================================================================
describe('the rupee sign survives serialisation to PDF bytes', () => {
  const POSITIONS = [
    {
      ticker: 'INFY.NS', quantity: 40, buy_price: 1523.4, last_price: 1890.25,
      market_value: 75610, weight: 0.42, sector: 'Information Technology',
    },
    {
      ticker: 'TATAMOTORS.NS', quantity: 120, buy_price: 640.1, last_price: 712.85,
      market_value: 85542, weight: 0.58, sector: 'Consumer Cyclical',
    },
  ];

  async function exportDoc() {
    await ExportService.exportInstitutionalReviewPDF({
      positions: POSITIONS,
      totalValue: 161152,
      currency: 'INR',
    });
    return lastDocument();
  }

  it('writes the currency amounts with U+20B9, as an embedded-font glyph', async () => {
    const pdf = await exportDoc();
    const body = allText(pdf);

    // The reader sees a rupee sign, in the total and in every money cell.
    expect(body).toContain('Total Portfolio Value: ₹1,61,152.00');
    expect(body).toContain('₹1,890.25');
    expect(body).toContain('₹1,523.40');
    expect(body).toContain('₹75,610.00');

    // And it is an embedded-font glyph, not a base-14 byte: every run is
    // Identity-H hex, and the PDF maps a glyph id back to U+20B9 itself.
    const runs = readTextRuns(pdf);
    expect(runs.length).toBeGreaterThan(0);
    expect(runs.every((r) => r.hex)).toBe(true);
    expect([...parseToUnicode(pdf)].some(([, code]) => code === 0x20b9)).toBe(true);
  });

  it('contains no 0xB9 byte in any page content stream', async () => {
    // THE FAILURE SIGNATURE. jsPDF writes an unencodable character's low byte
    // into a base-14 run, and 0xB9 is a superscript one in WinAnsi. If this
    // byte is absent from every content stream, the document cannot be
    // printing a superscript one where the rupee belongs.
    const pdf = await exportDoc();
    const streams = pageContentStreams(pdf);
    expect(streams.length).toBeGreaterThan(0);
    for (const stream of streams) {
      expect(stream.includes(0xb9)).toBe(false);
    }
  });

  it('leaves a value with no rupee sign alone (a blanket re-encode fails this)', async () => {
    // The control. The fix must not have re-encoded the whole document: the
    // plain text cells must still read back exactly as they were written.
    const pdf = await exportDoc();
    const body = allText(pdf);
    expect(body).toContain('DAISY RISK ENGINE');
    expect(body).toContain('Holdings & Asset Allocation');
    expect(body).toContain('INFY.NS');
    expect(body).toContain('Active Holdings: 2 Equities');
    // And no cell grew a symbol it was not given.
    expect(body).not.toMatch(/₹\s*₹/);
    expect(body).not.toContain('INR ');
  });

  it('prints the en-IN timestamp through the same embedded font', async () => {
    const pdf = await exportDoc();
    const stamp = readTextRuns(pdf).find((r) => r.text.startsWith('Generated:'));
    expect(stamp).toBeDefined();
    expect(stamp!.hex).toBe(true);
    // Whatever separator ICU's en-IN daypart uses, it round-trips rather than
    // collapsing into a stray 0xB9.
    expect(stamp!.text).toMatch(/^Generated: \d{1,2}\/\d{1,2}\/\d{4}, /);
    expect(stamp!.stream.includes(0xb9)).toBe(false);
  });

  it('draws every run with the embedded family, never a base-14 one', async () => {
    const pdf = await exportDoc();
    const raw = pdf.toString('latin1');
    // An embedded TrueType program behind a composite Identity-H font.
    expect(raw).toContain('/FontFile2');
    expect(raw).toContain('Identity-H');
    expect(raw).toContain('/Type0');

    const selected = selectedBaseFonts(pdf);
    expect(selected.size).toBeGreaterThan(0);
    for (const name of selected) {
      expect(name).toBe('DaisyExport');
    }
  });

  it('embeds two distinct font programs, so the headings are genuinely bold', async () => {
    const pdf = await exportDoc();
    const programs = pdf.toString('latin1').match(/\/FontFile2/g) ?? [];
    expect(programs.length).toBe(2);
  });
});

// ===========================================================================
// The control experiment: what the old code produced
// ===========================================================================
describe('the failure the guard exists to prevent', () => {
  it('base-14 Helvetica turns U+20B9 into 0xB9, a superscript one, silently', () => {
    // Deliberately the wrong font, pinning the signature the assertions above
    // are written against. If jsPDF ever stops doing this the guard is still
    // correct and only this characterisation test needs revisiting.
    const doc = new jsPDF();
    doc.setFont('helvetica', 'normal');
    doc.text('Total: ₹1,23,45,678.00', 10, 10);
    const pdf = Buffer.from(doc.output('arraybuffer') as ArrayBuffer);

    expect(pageContentStreams(pdf).some((s) => s.includes(0xb9))).toBe(true);
    expect(allText(pdf)).toContain('¹');
    expect(allText(pdf)).not.toContain('₹');
  });

  it('the embedded font produces no 0xB9 for the same string', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const doc = new jsPDF();
    (await loadPdfFont()).register(doc);
    doc.text('Total: ₹1,23,45,678.00', 10, 10);
    const pdf = Buffer.from(doc.output('arraybuffer') as ArrayBuffer);

    expect(pageContentStreams(pdf).some((s) => s.includes(0xb9))).toBe(false);
    expect(allText(pdf)).toContain('₹1,23,45,678.00');
  });
});

// ===========================================================================
// The guard
// ===========================================================================
describe('an unrenderable character is an explicit error', () => {
  it('accepts everything the export prints', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const pdfFont = await loadPdfFont();
    expect(() => pdfFont.assertRenders('₹1,890.25', 'holdings table')).not.toThrow();
    expect(() => pdfFont.assertRenders('INFY.NS: Volatility share 31.00%', 'risk section'))
      .not.toThrow();
    expect(unrenderableCodepoints(pdfFont, '₹1,890.25 — 44.00% ·')).toEqual([]);
    expect(unrenderableCodepoints(pdfFont, '₹')).toEqual([]);
  });

  it('names the codepoint and the section rather than printing a substitute', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const pdfFont = await loadPdfFont();
    // U+6F22 is a CJK ideograph: in no Latin subset, and exactly the kind of
    // character a base-14 font silently mangles.
    expect(() => pdfFont.assertRenders('A 漢 B', 'the holdings table')).toThrow(/U\+6F22/);
    try {
      pdfFont.assertRenders('A 漢 B', 'the holdings table');
      expect.unreachable('assertRenders should have thrown');
    } catch (error) {
      const message = (error as Error).message;
      expect(message).toContain('U+6F22');
      expect(message).toContain('the holdings table');
      expect(message).toMatch(/refusing to export/i);
    }
  });

  it('reports exactly the codepoints the font cannot draw', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const pdfFont = await loadPdfFont();
    expect(unrenderableCodepoints(pdfFont, '₹1,890.25 — 44.00% ·')).toEqual([]);
    expect(unrenderableCodepoints(pdfFont, 'A漢B')).toEqual([0x6f22]);
  });

  it('refuses to load a font with no rupee glyph rather than trusting the name', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    // A structurally valid sfnt header with no table directory: it parses, has
    // no cmap, and therefore no U+20B9.
    const headerOnly = new Uint8Array(REGULAR.subarray(0, 12));
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        arrayBuffer: async () => headerOnly.buffer.slice(0),
      }) as Response)
    );
    await expect(loadPdfFont()).rejects.toThrow(/no U\+20B9/);
  });

  it('refuses when the two weights do not cover the same characters', async () => {
    // A style is what actually draws a run, so coverage is checked per weight
    // rather than unioned. Serving a bold weight with an empty cmap makes the
    // two disagree, which must stop the export rather than let a normal-weight
    // glyph be promised to a bold run (or the reverse).
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const emptyCmap = new Uint8Array(REGULAR.subarray(0, 12));
    const regular = new Uint8Array(REGULAR.byteLength);
    regular.set(REGULAR);
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(
          typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        );
        const bytes = url.endsWith('-Bold.ttf') ? emptyCmap : regular;
        return { ok: true, status: 200, arrayBuffer: async () => bytes.buffer.slice(0) } as Response;
      })
    );
    await expect(loadPdfFont()).rejects.toThrow(/weights cover different/);
  });

  it('refuses rather than falling back when the asset cannot be fetched', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    stubFontFetch(false, 404);
    await expect(loadPdfFont()).rejects.toThrow(/HTTP 404/);
  });
});

// ===========================================================================
// The other PDF path in the same file
// ===========================================================================
describe('PDFExporter is on the same font', () => {
  it('cannot be constructed without one', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    await loadPdfFont();
    // The constructor takes the font rather than defaulting to it: any default
    // would be the base-14 font, which is the defect.
    const Unconstructable = PDFExporter as unknown as new (font?: unknown) => PDFExporter;
    expect(() => new Unconstructable()).toThrow();
  });

  it('writes its table through the embedded font', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const pdfFont = await loadPdfFont();
    expect(pdfFont.family).toBe(PDF_FONT_FAMILY);

    const exporter = new PDFExporter(pdfFont);
    exporter.addTitle('Sector report');
    exporter.addTable([{ Sector: 'Technology', Weight: 0.42 }]);
    const pdf = Buffer.from(await exporter.getBlob().arrayBuffer());

    expect(allText(pdf)).toContain('Sector report');
    expect(allText(pdf)).toContain('Technology');
    expect(readTextRuns(pdf).every((r) => r.hex)).toBe(true);
    expect(pageContentStreams(pdf).some((s) => s.includes(0xb9))).toBe(false);
  });

  it('throws rather than printing a substituted glyph in a table cell', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const pdfFont = await loadPdfFont();
    const exporter = new PDFExporter(pdfFont);
    // U+6578 is a CJK ideograph.
    expect(() => exporter.addTable([{ Sector: '數', Weight: 1 }])).toThrow(/U\+6578/);
  });
});

// ===========================================================================
// A table cell is not a place to quietly lose characters
// ===========================================================================
//
// `formatCellValue` used to cut a cell at 20 characters, so `Information
// Technology` printed as `Information Technolo` with nothing on the page saying
// anything had been dropped. Same defect class as the rupee sign printing as a
// superscript one: the export succeeds, the document states something the data
// did not say, and nothing goes red.
//
// The fix is wrapping, not a disclosed cap, so the assertion is that every
// character reaches the page. The text runs are read back through the PDF's own
// /ToUnicode CMap, so this reads what a reader sees rather than what was
// passed to `doc.text`.
describe('a table cell prints its value whole', () => {
  /** What the page actually shows, wrap points removed. */
  async function printedText(exporter: PDFExporter): Promise<string> {
    const pdf = Buffer.from(await exporter.getBlob().arrayBuffer());
    return readTextRuns(pdf)
      .map((r) => r.text)
      .join(' ');
  }

  it('does not cut a long value at 20 characters', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const exporter = new PDFExporter(await loadPdfFont());

    // 22 characters, and the cut fell mid-word: `Information Technolo`.
    exporter.addTable([{ Sector: 'Information Technology', Weight: 0.42 }]);

    const text = await printedText(exporter);
    expect(text).toContain('Information');
    expect(text).toContain('Technology');
    // The whole value, once the wrap points are put back together.
    expect(text.replace(/\s+/g, ' ')).toContain('Information Technology');
    // The exact string the old truncation produced must not be what is printed.
    expect(text).not.toContain('Information Technolo ');
  });

  it('wraps rather than overflowing, so a long value is drawn on a second line', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const exporter = new PDFExporter(await loadPdfFont());

    // Seven columns is the shape that actually squeezes a cell: the equal
    // column width is ~79pt, so a long sector name cannot fit on one line.
    exporter.addTable(
      [
        {
          Ticker: 'INFY.NS',
          Quantity: 40,
          BuyPrice: 1500,
          LastPrice: 1610,
          MarketValue: 64400,
          Weight: 0.18,
          Sector: 'Information Technology',
        },
      ],
      ['Ticker', 'Quantity', 'BuyPrice', 'LastPrice', 'MarketValue', 'Weight', 'Sector']
    );

    const pdf = Buffer.from(await exporter.getBlob().arrayBuffer());
    const runs = readTextRuns(pdf).map((r) => r.text);
    // More than one run carries the sector name, i.e. it was wrapped onto
    // separate lines rather than run off the edge of its column.
    const sectorRuns = runs.filter((run) => /Information|Technology|Technolog/.test(run));
    expect(sectorRuns.length).toBeGreaterThan(1);
    expect(sectorRuns.join(' ')).toMatch(/Information\s+Technolog(y)?/);

    // Still drawn with the embedded font, and still no substituted glyph.
    expect(runs.every((r) => r !== '')).toBe(true);
    expect(pageContentStreams(pdf).some((s) => s.includes(0xb9))).toBe(false);
  });

  it('keeps the page-break ladder honest about the taller row a wrap creates', async () => {
    const { loadPdfFont } = await import('@/lib/pdfFont');
    const exporter = new PDFExporter(await loadPdfFont());

    // Enough wrapped rows to cross a page boundary. The break check runs against
    // the row's REAL height, so this must produce more than one page rather than
    // drawing past the bottom margin.
    const rows = Array.from({ length: 120 }, (_, i) => ({
      Ticker: `TICK${i}.NS`,
      Sector: 'Information Technology',
    }));
    exporter.addTable(rows, ['Ticker', 'Sector']);

    const pdf = Buffer.from(await exporter.getBlob().arrayBuffer());
    const raw = pdf.toString('latin1');
    const pageCount = (raw.match(/\/Type\s*\/Page[^s]/g) ?? []).length;
    expect(pageCount).toBeGreaterThan(1);

    // Every row's ticker reached the document: nothing was dropped to make the
    // layout fit.
    const text = readTextRuns(pdf)
      .map((r) => r.text)
      .join(' ');
    for (const ticker of ['TICK0.NS', 'TICK60.NS', 'TICK119.NS']) {
      expect(text).toContain(ticker);
    }
  });
});
