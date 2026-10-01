import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  ExportService,
  ChartExporter,
  buildRiskStatements,
  buildRiskContributionSeries,
  exportDevicePixelRatio,
  rasterSize,
  MAX_EXPORT_DPR,
  assertExportSvg,
  resolveExportChartSize,
  countExportChartMarks,
  assertExportChartHasMarks,
  isRechartsSurface,
  svgToPngDataUrl,
  renderExportRiskChart,
  EXPORT_CHART_SERIES,
  EXPORT_CHART_WIDTH,
  EXPORT_CHART_HEIGHT,
  EXPORT_CHART_MAX_BARS,
  type RiskMetricsSnapshot,
  type RiskContributionDatum,
} from '@/lib/export';

// ===========================================================================
// jsPDF double. The only thing worth asserting about a PDF is what was handed
// to jsPDF, so the double records every call verbatim.
//
// It also has to know about the embedded font: the real exporter now calls
// `addFileToVFS` / `addFont` before any text, and `setFont` is what it uses to
// select the embedded family instead of a base-14 one. Both are recorded so a
// regression to Helvetica shows up here rather than only in the byte-level
// suite (src/test/unit/pdf-rupee-encoding.test.ts, which runs the real jsPDF).
// ===========================================================================
const recorder = vi.hoisted(() => ({
  texts: [] as string[],
  images: [] as unknown[][],
  addPageCount: 0,
  saves: [] as string[],
  vfsFiles: [] as string[],
  registeredFonts: [] as string[],
  selectedFonts: [] as string[],
}));

vi.mock('jspdf', () => {
  // A real class, not vi.fn(): the module under test does `new jsPDF()`.
  class FakeJsPDF {
    internal = { pageSize: { width: 210, height: 297 }, scaleFactor: 1 };
    text(value: unknown) { recorder.texts.push(String(value)); return this; }
    rect() { return this; }
    line() { return this; }
    setFillColor() { return this; }
    setDrawColor() { return this; }
    setTextColor() { return this; }
    setFont(family: string, style: string) {
      recorder.selectedFonts.push(`${family}/${style}`);
      return this;
    }
    setFontSize() { return this; }
    addFileToVFS(name: string) { recorder.vfsFiles.push(name); return this; }
    addFont(file: string, family: string, style: string) {
      recorder.registeredFonts.push(`${file}->${family}/${style}`);
      return this;
    }
    addPage() { recorder.addPageCount += 1; return this; }
    addImage(...args: unknown[]) { recorder.images.push(args); return this; }
    output() { return new ArrayBuffer(0); }
    save(name: string) { recorder.saves.push(name); return this; }
  }
  return { jsPDF: FakeJsPDF };
});

// ===========================================================================
// Canvas/Image shim.
//
// jsdom has NO 2D backend: `getContext('2d')` returns null, `toBlob` never
// calls back, and `new Image()` with a blob URL never fires `onload`
// (`HTMLCanvasElement-impl.js` calls notImplementedMethod for all three).
// Rather than add a seam to production code purely so a test can get past
// them, the environment is shimmed and the REAL code path runs unchanged.
// The shim records what the drawing code did, and hands back a real PNG.
// ===========================================================================
const REAL_PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

function base64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const binary = atob(b64);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

const pngBytes = base64ToBytes(REAL_PNG_BASE64);

interface DrawLog {
  scale: unknown[][];
  fillRect: unknown[][];
  drawImage: unknown[][];
  canvasWidths: number[];
  canvasHeights: number[];
}

let drawLog: DrawLog;
let canvasShim: 'working' | 'no-context' | 'zero-byte' | 'null-blob';

function installCanvasShim() {
  drawLog = { scale: [], fillRect: [], drawImage: [], canvasWidths: [], canvasHeights: [] };

  // The shim replaces members the DOM lib types as overloaded; the record
  // keeps the shim honest without loosening the whole file to `any`.
  const proto = window.HTMLCanvasElement.prototype as unknown as Record<string, unknown>;
  const realGetContext = window.HTMLCanvasElement.prototype.getContext.bind(
    window.HTMLCanvasElement.prototype
  );

  proto.getContext = function getContext(this: HTMLCanvasElement, type: string) {
    if (type !== '2d') return realGetContext(type as '2d');
    if (canvasShim === 'no-context') return null;
    return {
      fillStyle: '',
      scale: (...a: unknown[]) => { drawLog.scale.push(a); },
      fillRect: (...a: unknown[]) => { drawLog.fillRect.push(a); },
      drawImage: (...a: unknown[]) => { drawLog.drawImage.push(a); },
    };
  };

  proto.toBlob = function toBlob(this: HTMLCanvasElement, cb: (b: Blob | null) => void) {
    if (canvasShim === 'null-blob') { cb(null); return; }
    // toBlob on a 0x0 canvas RESOLVES an empty blob rather than rejecting.
    const empty = canvasShim === 'zero-byte' || this.width === 0 || this.height === 0;
    cb(new Blob([empty ? new Uint8Array(new ArrayBuffer(0)) : pngBytes], { type: 'image/png' }));
  };

  // jsdom never decodes a blob URL into an <img>; fire onload so the drawing
  // code proceeds.
  class FakeImage {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    private _src = '';
    get src() { return this._src; }
    set src(value: string) {
      this._src = value;
      queueMicrotask(() => this.onload?.());
    }
  }
  vi.stubGlobal('Image', FakeImage);
}

// ===========================================================================
// Font asset fetch.
//
// The real exporter embeds a Unicode TTF (jsPDF's base-14 Helvetica has no
// U+20B9 and silently prints a superscript one instead). It loads the bytes
// with `fetch` from /fonts, so the global fetch double has to serve them.
// The bytes come off disk, so the coverage the guard computes is the coverage
// of the real asset, not a hand-written stand-in.
// ===========================================================================
function installFontFetch() {
  const dir = resolve(process.cwd(), 'public', 'fonts');
  const files = new Map<string, Uint8Array>([
    ['/fonts/DaisyExport-Regular.ttf', new Uint8Array(readFileSync(resolve(dir, 'DaisyExport-Regular.ttf')))],
    ['/fonts/DaisyExport-Bold.ttf', new Uint8Array(readFileSync(resolve(dir, 'DaisyExport-Bold.ttf')))],
  ]);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(
        typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      );
      const bytes = files.get(url);
      if (!bytes) {
        return { ok: false, status: 404, arrayBuffer: async () => new ArrayBuffer(0) } as Response;
      }
      const copy = new Uint8Array(bytes.byteLength);
      copy.set(bytes);
      return { ok: true, status: 200, arrayBuffer: async () => copy.buffer } as Response;
    })
  );
}

beforeEach(() => {
  recorder.texts.length = 0;
  recorder.images.length = 0;
  recorder.addPageCount = 0;
  recorder.saves.length = 0;
  recorder.vfsFiles.length = 0;
  recorder.registeredFonts.length = 0;
  recorder.selectedFonts.length = 0;
  canvasShim = 'working';
  installCanvasShim();
  installFontFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = '';
});

// ===========================================================================
// Fixtures
// ===========================================================================
const POSITIONS = [
  {
    ticker: 'INFY.NS', quantity: 40, buy_price: 1523.4, last_price: 1890.25,
    market_value: 75610, weight: 0.42, sector: 'Information Technology',
  },
  {
    ticker: 'TATAMOTORS.NS', quantity: 120, buy_price: 640.1, last_price: 712.85,
    market_value: 85542, weight: 0.58, sector: 'Consumer Cyclical',
  },
  {
    // No sector: unclassified, not "General".
    ticker: 'DXYZ.NS', quantity: 10, buy_price: 100, last_price: 250,
    market_value: 2500, weight: 0,
  },
];

const FULL_METRICS: RiskMetricsSnapshot = {
  riskContribution: {
    positions: {
      volatility: { 'INFY.NS': 0.31, 'TATAMOTORS.NS': 0.69 },
      cvar_tail: { 'INFY.NS': 0.44, 'TATAMOTORS.NS': 0.56 },
    },
    portfolio_volatility_annualized: 18.42,
    portfolio_var_95_daily: -0.0234,
    portfolio_cvar_95_daily: -0.0411,
    window: { start: '2025-09-30', end: '2026-09-30' },
    data_status: 'complete',
  },
  liquidityLimits: {
    portfolio_weighted_days_to_liquidate_10pct: 0.62,
    portfolio_weighted_days_to_liquidate_20pct: 0.31,
    data_status: 'complete',
  },
  liquidity: {
    liquidation_time_days: '1-2',
    overall_score: 8.4,
    risk_level: 'low',
  },
};

const CHART_ROWS: RiskContributionDatum[] = [
  { ticker: 'INFY.NS', volatility: 0.31, cvarTail: 0.44 },
  { ticker: 'TATAMOTORS.NS', volatility: 0.69, cvarTail: 0.56 },
];

function contentSvg() {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  el.setAttribute('width', '360');
  el.setAttribute('height', '200');
  el.innerHTML = '<g><rect class="recharts-rectangle"/><text>INFY.NS</text></g>';
  return el;
}

/**
 * Runs the real export and returns a SNAPSHOT of what reached jsPDF.
 *
 * `positions` is typed by the export's own contract, so a fixture may supply a
 * null for a field the engine never recorded — which is exactly the case the
 * absent-marker tests need to construct.
 */
async function exportWith(
  metrics?: RiskMetricsSnapshot | null,
  positions: Parameters<typeof ExportService.exportInstitutionalReviewPDF>[0]['positions'] = POSITIONS
) {
  // Reset per call: the recorder is shared across the whole file, so a
  // snapshot taken without a reset would silently include the previous run.
  recorder.texts.length = 0;
  recorder.images.length = 0;
  recorder.addPageCount = 0;
  recorder.saves.length = 0;
  recorder.vfsFiles.length = 0;
  recorder.registeredFonts.length = 0;
  recorder.selectedFonts.length = 0;
  await ExportService.exportInstitutionalReviewPDF({
    positions,
    totalValue: positions.reduce((s, p) => s + (p.market_value ?? 0), 0),
    currency: 'INR',
    riskMetrics: metrics,
  });
  return {
    texts: [...recorder.texts],
    images: recorder.images.map((args) => [...args]),
    addPageCount: recorder.addPageCount,
    saves: [...recorder.saves],
    vfsFiles: [...recorder.vfsFiles],
    registeredFonts: [...recorder.registeredFonts],
    selectedFonts: [...recorder.selectedFonts],
  };
}

// ===========================================================================
describe('buildRiskStatements — a sentence exists iff its own field does', () => {
  it('produces nothing at all when no metrics were supplied', () => {
    expect(buildRiskStatements(undefined)).toEqual([]);
    expect(buildRiskStatements(null)).toEqual([]);
    expect(buildRiskStatements({})).toEqual([]);
  });

  it('produces one statement per present field, each quoting that field', () => {
    const statements = buildRiskStatements(FULL_METRICS);
    const byLabel = Object.fromEntries(statements.map((s) => [s.label, s.value]));

    expect(byLabel['Portfolio volatility, annualised']).toBe('18.42%');
    expect(byLabel['Portfolio VaR 95%, daily return threshold']).toBe('-2.34%');
    expect(byLabel['Portfolio CVaR 95%, daily mean tail return']).toBe('-4.11%');
    expect(byLabel['Weighted days to liquidate at 10% of ADV']).toBe('0.62 days');
    expect(byLabel['Weighted days to liquidate at 20% of ADV']).toBe('0.31 days');
    expect(byLabel['Liquidity-scored liquidation band']).toBe('1-2');
  });

  it('drops the sentence for each field that is null, NaN or missing — never a default', () => {
    const statements = buildRiskStatements({
      riskContribution: {
        positions: {},
        portfolio_volatility_annualized: null,
        portfolio_var_95_daily: null,
        portfolio_cvar_95_daily: Number.NaN,
      },
      liquidityLimits: {
        portfolio_weighted_days_to_liquidate_10pct: null,
        portfolio_weighted_days_to_liquidate_20pct: undefined,
      },
      liquidity: { liquidation_time_days: '   ' },
    });
    expect(statements).toEqual([]);
  });

  it('does not borrow one route’s figure to fill another route’s sentence', () => {
    const onlyLimits = buildRiskStatements({
      liquidityLimits: { portfolio_weighted_days_to_liquidate_10pct: 0.62 },
    });
    expect(onlyLimits).toHaveLength(1);
    expect(onlyLimits[0].label).toContain('10% of ADV');
    expect(onlyLimits.some((s) => s.label.includes('liquidation band'))).toBe(false);
  });

  it('formats an already-percent volatility as a percent, not as a fraction of a percent', () => {
    // 18.42 is the backend's `portfolio_volatility_annualized` (already a
    // percent). formatPercentage's documented input is a fraction, so routing
    // this through it would print "1842.00%".
    const [statement] = buildRiskStatements({
      riskContribution: { portfolio_volatility_annualized: 18.42 },
    });
    expect(statement.value).toBe('18.42%');
  });
});

describe('buildRiskContributionSeries', () => {
  it('returns [] when either model map is missing (never cross-fills)', () => {
    expect(buildRiskContributionSeries(undefined)).toEqual([]);
    expect(
      buildRiskContributionSeries({ riskContribution: { positions: { volatility: { A: 1 } } } })
    ).toEqual([]);
    expect(
      buildRiskContributionSeries({ riskContribution: { positions: { cvar_tail: { A: 1 } } } })
    ).toEqual([]);
  });

  it('drops a ticker measurable under only one model rather than plotting it at zero', () => {
    const rows = buildRiskContributionSeries({
      riskContribution: {
        positions: { volatility: { A: 0.5, B: 0.5 }, cvar_tail: { A: 1 } },
      },
    });
    expect(rows.map((r) => r.ticker)).toEqual(['A']);
  });

  it('sorts by volatility share descending, then ticker, for byte-stable output', () => {
    const rows = buildRiskContributionSeries({
      riskContribution: {
        positions: {
          volatility: { B: 0.2, A: 0.5, C: 0.3 },
          cvar_tail: { A: 0.5, B: 0.2, C: 0.3 },
        },
      },
    });
    expect(rows.map((r) => r.ticker)).toEqual(['A', 'C', 'B']);
  });
});

// ===========================================================================
describe('DPR arithmetic (pure)', () => {
  it('caps at 2 and treats a missing/zero/NaN ratio as 1', () => {
    expect(exportDevicePixelRatio(3)).toBe(2);
    expect(MAX_EXPORT_DPR).toBe(2);
    expect(exportDevicePixelRatio(1.5)).toBe(1.5);
    expect(exportDevicePixelRatio(1)).toBe(1);
    expect(exportDevicePixelRatio(0)).toBe(1);
    expect(exportDevicePixelRatio(undefined)).toBe(1);
    expect(exportDevicePixelRatio(null)).toBe(1);
    expect(exportDevicePixelRatio(Number.NaN)).toBe(1);
  });

  it('rect.width 360 at dpr 2 is a 720px backing store', () => {
    expect(rasterSize(360, 200, 2)).toEqual({
      cssWidth: 360, cssHeight: 200, pixelWidth: 720, pixelHeight: 400, dpr: 2,
    });
  });

  it('a 3x display is rasterised at 2x, not 3x', () => {
    expect(rasterSize(360, 200, 3).pixelWidth).toBe(720);
  });
});

// ===========================================================================
describe('the SVG guard (inverted)', () => {
  it('rejects null, undefined and a non-svg element', () => {
    expect(() => assertExportSvg(null)).toThrow(/null/i);
    expect(() => assertExportSvg(undefined)).toThrow(/null/i);
    expect(() => assertExportSvg(document.createElement('div'))).toThrow(/must be an <svg>/);
  });

  it('ChartExporter.exportChart REJECTS a div instead of resolving a blank PNG', async () => {
    // This is the live bug: a ResponsiveContainer ref is a div, and the old
    // else-branch called toBlob on a never-drawn canvas, which resolves a
    // perfectly valid white PNG.
    await expect(
      ChartExporter.exportChart(document.createElement('div'), { filename: 'chart', format: 'png' })
    ).rejects.toThrow(/must be an <svg>/);
  });

  it('ChartExporter.exportChart REJECTS null', async () => {
    await expect(
      ChartExporter.exportChart(null as unknown as HTMLElement, { filename: 'chart', format: 'png' })
    ).rejects.toThrow(/null/i);
  });

  it('ChartExporter.exportChart refuses a non-raster format it cannot honour', async () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    // The parameter stays `HTMLElement` for ExportPanel's benefit; the check
    // is a runtime one, which is what the test above proves.
    await expect(
      ChartExporter.exportChart(svg as unknown as HTMLElement, {
        filename: 'chart', format: 'pdf',
      })
    ).rejects.toThrow(/raster 'png' only/);
  });
});

describe('resolveExportChartSize — 0x0 is an error, not a default', () => {
  function svgWith(attrs: Record<string, string>) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [k, v] of Object.entries(attrs)) svg.setAttribute(k, v);
    return svg;
  }

  it('reads width/height attributes when the layout rect is 0x0', () => {
    const svg = svgWith({ width: '720', height: '300' });
    expect(svg.getBoundingClientRect().width).toBe(0);
    expect(resolveExportChartSize(svg)).toEqual({ width: 720, height: 300 });
  });

  it('falls back to the viewBox only when the attributes are unusable', () => {
    expect(resolveExportChartSize(svgWith({ viewBox: '0 0 640 480' })))
      .toEqual({ width: 640, height: 480 });
  });

  it('THROWS when there is no positive size anywhere — no 0x0 default', () => {
    expect(() => resolveExportChartSize(svgWith({ width: '0', height: '0' })))
      .toThrow(/no measurable size/i);
    expect(() => resolveExportChartSize(svgWith({})))
      .toThrow(/no measurable size/i);
    expect(() => resolveExportChartSize(svgWith({ width: '720', height: '0' })))
      .toThrow(/no measurable size/i);
  });
});

describe('isRechartsSurface — an svg is not enough', () => {
  it('accepts the surface recharts actually forwards the ref to', () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'recharts-surface recharts-wrapper');
    expect(isRechartsSurface(svg)).toBe(true);
  });

  it('rejects a plain inline <svg> — the mis-wired-ref case', () => {
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    icon.setAttribute('class', 'lucide lucide-file-down');
    icon.innerHTML = '<path d="M0 0"/>';
    expect(isRechartsSurface(icon)).toBe(false);
  });

  it('rejects a class that merely contains the token as a substring', () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'recharts-surface-wrapper');
    expect(isRechartsSurface(svg)).toBe(false);
  });

  it('rejects a div, a canvas, and null', () => {
    expect(isRechartsSurface(document.createElement('div'))).toBe(false);
    expect(isRechartsSurface(document.createElement('canvas'))).toBe(false);
    expect(isRechartsSurface(null)).toBe(false);
    expect(isRechartsSurface(undefined)).toBe(false);
  });
});

describe('assertExportChartHasMarks — axes without bars is rejected', () => {
  function svg(inner: string) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    el.innerHTML = inner;
    return el;
  }

  it('accepts a chart with data marks', () => {
    const el = svg('<g><rect class="recharts-rectangle"/></g><text>INFY.NS</text>');
    expect(assertExportChartHasMarks(el).marks).toBe(1);
  });

  it('rejects an axes-only chart (the "visually fine, semantically empty" case)', () => {
    const el = svg('<g><line class="recharts-cartesian-axis-line"/><text>INFY.NS</text><text>0%</text></g>');
    expect(countExportChartMarks(el).texts).toBe(2);
    expect(countExportChartMarks(el).marks).toBe(0);
    expect(() => assertExportChartHasMarks(el)).toThrow(/no data marks/);
  });

  it('rejects a completely empty surface', () => {
    expect(() => assertExportChartHasMarks(svg(''))).toThrow(/no content at all/);
  });
});

describe('svgToPngDataUrl', () => {
  it('scales the context by dpr BEFORE drawing, and draws at the CSS size', async () => {
    await svgToPngDataUrl(contentSvg(), { dpr: 2 });
    // scale is the only context mutation, and it precedes the single draw.
    expect(drawLog.scale).toEqual([[2, 2]]);
    expect(drawLog.drawImage).toHaveLength(1);
    expect(drawLog.drawImage[0].length).toBe(3); // 2-arg form: (img, 0, 0)
  });

  it('gives the canvas a dpr-scaled backing store', async () => {
    const canvases: HTMLCanvasElement[] = [];
    const realCreate = document.createElement.bind(document);
    const spy = vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = realCreate(tag);
      if (tag === 'canvas') canvases.push(el as HTMLCanvasElement);
      return el;
    }) as typeof document.createElement);

    await svgToPngDataUrl(contentSvg(), { dpr: 2 });
    spy.mockRestore();
    expect(canvases[0].width).toBe(720);
    expect(canvases[0].height).toBe(400);
  });

  it('returns a non-empty image/png data URL carrying the real PNG bytes', async () => {
    const url = await svgToPngDataUrl(contentSvg(), { dpr: 1 });
    expect(url.startsWith('data:image/png;base64,')).toBe(true);
    expect(url.split(',')[1]).toBe(REAL_PNG_BASE64);
    expect(atob(url.split(',')[1]).length).toBe(pngBytes.length);
  });

  it('rejects a non-svg input', async () => {
    await expect(svgToPngDataUrl(document.createElement('div'))).rejects.toThrow(/must be an <svg>/);
  });

  it('rejects a 0x0 surface instead of embedding a 0-byte PNG', async () => {
    const empty = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    empty.setAttribute('width', '0');
    empty.setAttribute('height', '0');
    empty.innerHTML = '<rect class="recharts-rectangle"/>';
    await expect(svgToPngDataUrl(empty)).rejects.toThrow(/no measurable size/i);
  });

  it('rejects a 0-byte PNG rather than passing it on to addImage', async () => {
    canvasShim = 'zero-byte';
    await expect(svgToPngDataUrl(contentSvg())).rejects.toThrow(/0-byte PNG/);
  });

  it('rejects when the browser has no 2D context', async () => {
    canvasShim = 'no-context';
    await expect(svgToPngDataUrl(contentSvg())).rejects.toThrow(/2D canvas context/);
  });
});

// ===========================================================================
describe('renderExportRiskChart — the real recharts mount', () => {
  it('the ref resolves to the recharts <svg> surface, not a div or null', async () => {
    const result = await renderExportRiskChart(CHART_ROWS);
    expect(result.error).toBeNull();
    expect(result.svg).toBeInstanceOf(SVGElement);
    expect(result.svg?.tagName.toLowerCase()).toBe('svg');
    expect(result.svg?.getAttribute('class')).toContain('recharts-surface');
    expect(isRechartsSurface(result.svg)).toBe(true);
  });

  it('the serialised SVG has substance: real data marks and tick text', async () => {
    const result = await renderExportRiskChart(CHART_ROWS);
    expect(result.markup).toBeTruthy();
    // 2 series x 2 holdings
    expect(result.marks?.marks).toBe(4);
    expect(result.marks?.texts).toBeGreaterThan(0);
    expect(result.markup).toContain('recharts-rectangle');
    expect(result.markup).toContain('<text');
  });

  it('embeds a non-empty PNG payload', async () => {
    const result = await renderExportRiskChart(CHART_ROWS, { dpr: 2 });
    expect(result.dataUrl?.startsWith('data:image/png;base64,')).toBe(true);
    expect(result.dataUrl?.split(',')[1]).toBe(REAL_PNG_BASE64);
    expect(drawLog.scale).toEqual([[2, 2]]);
  });

  it('lays the chart out at the declared fixed size', async () => {
    const result = await renderExportRiskChart(CHART_ROWS);
    expect(resolveExportChartSize(result.svg!)).toEqual({
      width: EXPORT_CHART_WIDTH, height: EXPORT_CHART_HEIGHT,
    });
  });

  it('removes the offscreen host from the document afterwards', async () => {
    await renderExportRiskChart(CHART_ROWS);
    expect(document.querySelectorAll('[data-export-chart]')).toHaveLength(0);
  });

  it('reports, rather than throws, when there is nothing to plot', async () => {
    const result = await renderExportRiskChart([]);
    expect(result.dataUrl).toBeNull();
    expect(result.error).toMatch(/nothing|measurable/i);
  });

  it('reports, rather than throws, when rasterisation is impossible', async () => {
    canvasShim = 'no-context';
    const result = await renderExportRiskChart(CHART_ROWS);
    expect(result.dataUrl).toBeNull();
    expect(result.error).toMatch(/2D canvas context/);
    // The surface and its serialised markup are still reported for diagnosis.
    expect(result.svg).toBeInstanceOf(SVGElement);
    expect(result.markup).toContain('recharts-rectangle');
  });
});

// ===========================================================================
describe('exportInstitutionalReviewPDF — the risk section tracks the input', () => {
  it('the document body DIFFERS with and without riskMetrics', async () => {
    const withMetrics = await exportWith(FULL_METRICS);
    const without = await exportWith(undefined);

    expect(withMetrics.texts).not.toEqual(without.texts);

    // With metrics: the measured figures are present.
    const rich = withMetrics.texts.join('\n');
    expect(rich).toContain('18.42%');
    expect(rich).toContain('-2.34%');
    expect(rich).toContain('-4.11%');
    expect(rich).toContain('0.62 days');
    expect(rich).toContain('0.31 days');
    expect(rich).toContain('1-2');

    // Without: not a single one of them, and no section header either.
    const bare = without.texts.join('\n');
    for (const figure of ['18.42%', '-2.34%', '0.62 days', '1-2']) {
      expect(bare).not.toContain(figure);
    }
    expect(without.texts).not.toContain('Quantitative Risk & Microstructure Summary');
  });

  it('never emits the three hardcoded methodology strings, at any input', async () => {
    const bodies: string[] = [];
    bodies.push((await exportWith(FULL_METRICS)).texts.join('\n'));
    bodies.push((await exportWith(undefined)).texts.join('\n'));
    bodies.push((await exportWith({})).texts.join('\n'));
    bodies.push((await exportWith({ riskContribution: { positions: {} } })).texts.join('\n'));

    for (const body of bodies) {
      // Not reworded variants: nothing in the output may claim a methodology,
      // because no code path in this module computes any of them.
      expect(body).not.toMatch(/Euler/i);
      expect(body).not.toMatch(/EVT/i);
      expect(body).not.toMatch(/Generalized Pareto/i);
      expect(body).not.toMatch(/empirical covariance/i);
      expect(body).not.toMatch(/fat-tail/i);
      expect(body).not.toMatch(/ADV Liquidity Sizing ensures/i);
    }
  });

  it('states plainly when there is no risk data, rather than describing a method', async () => {
    const { texts } = await exportWith(undefined);
    expect(texts.join('\n')).toContain('no risk metrics were available for this export');
  });

  it('prints a partial risk section without padding it out to the full set', async () => {
    const { texts } = await exportWith({
      riskContribution: { portfolio_volatility_annualized: 12.5, positions: {} },
    });
    const body = texts.join('\n');
    expect(body).toContain('12.50%');
    // VaR, CVaR and both ADV horizons were NOT supplied: absent, not zeroed.
    expect(body).not.toContain('VaR');
    expect(body).not.toContain('CVaR');
    expect(body).not.toContain('days');
  });
});

describe('exportInstitutionalReviewPDF — currency, sector, prices', () => {
  it('never fabricates a sector label for an unclassified holding', async () => {
    const { texts } = await exportWith(FULL_METRICS);
    expect(texts).not.toContain('General');
    expect(texts).toContain('Information Technology');
    expect(texts).toContain('Consumer Cyclical');
    expect(texts).toContain('—');
  });

  it('prints a currency symbol on every money cell, and no bare toFixed(1) price', async () => {
    const { texts } = await exportWith(FULL_METRICS);
    expect(texts).toContain('₹1,890.25');   // last price
    expect(texts).toContain('₹1,523.40');   // buy price
    expect(texts).toContain('₹75,610.00');  // market value
    expect(texts.some((t) => t.startsWith('Total Portfolio Value: ₹'))).toBe(true);

    for (const cell of texts) {
      expect(cell).not.toMatch(/INR \d/);       // the old ASCII-code form
      // A whole cell that is just `1890.3` is the old un-symbolised price.
      expect(cell).not.toMatch(/^\d[\d,]*\.\d$/);
    }
  });

  it('does not print a $ sign for a non-dollar book (no unconverted FX)', async () => {
    const { texts } = await exportWith(FULL_METRICS);
    for (const cell of texts) expect(cell).not.toContain('$');
  });

  it('preserves the grouped en-IN market-value column', async () => {
    const { texts } = await exportWith(undefined, [
      { ...POSITIONS[0], market_value: 12345678 },
    ]);
    expect(texts).toContain('₹1,23,45,678.00');
  });

  it('renders a non-INR book in its own currency, without an FX claim', async () => {
    await ExportService.exportInstitutionalReviewPDF({
      positions: [{ ...POSITIONS[0], market_value: 1000 }], totalValue: 1000, currency: 'USD',
    });
    const total = recorder.texts.find((t) => t.startsWith('Total Portfolio Value:'));
    expect(total).toBe('Total Portfolio Value: $1,000.00');
  });
});

// ===========================================================================
// The holdings table's numeric columns.
//
// A CONFIDENTIAL document is the last place a fabricated zero should survive.
// `String(p.quantity || 0)` published "0" and `(p.weight || 0) * 100` published
// "0.0%" for a holding whose quantity and weight were never recorded — the
// reader cannot tell that apart from a holding that is genuinely worth nothing.
//
// The marker is the em dash already used in this same table (the sector column,
// `nonEmptyString(p.sector) ?? '—'`) rather than a new glyph: `write()` runs
// every string through `pdfFont.assertRenders`, and the em dash is already in
// the subset's general-punctuation range AND already proven renderable by the
// test above ("never fabricates a sector label" asserts '—' reaches the page).
// Introducing a fresh codepoint here would be a claim about the font that
// nothing in this repo has verified.
// ===========================================================================
describe('exportInstitutionalReviewPDF — an unrecorded holding is not a 0.0% holding', () => {
  it('writes the absent marker for a quantity and a weight that were never recorded', async () => {
    const { texts } = await exportWith(undefined, [
      {
        ticker: 'A.NS', quantity: null, buy_price: 100, last_price: 200,
        market_value: 5000, weight: null, sector: 'Tech',
      },
    ]);

    // Absent, not "0" and not "0.0%".
    expect(texts).toContain('—');
    expect(texts).not.toContain('0.0%');
    // The holding itself and its real money are untouched.
    expect(texts).toContain('A.NS');
    expect(texts).toContain('₹5,000.00');
  });

  it('still prints a MEASURED zero quantity and a MEASURED 0.0% weight', async () => {
    // The other half of the rule. A holding that is genuinely zero-weighted is a
    // real measurement; a guard written as `p.weight || '—'` would erase it.
    const { texts } = await exportWith(undefined, [
      {
        ticker: 'A.NS', quantity: 0, buy_price: 100, last_price: 200,
        market_value: 0, weight: 0, sector: 'Tech',
      },
    ]);

    expect(texts).toContain('0.0%');
    // money() already renders a measured 0 as a real ₹0.00, so the money column
    // must not have picked up the absent marker either.
    expect(texts).toContain('₹0.00');
    expect(texts).not.toContain('N/A');
    expect(texts).not.toContain('—');
  });

  it('leaves a real fractional weight on its own scale, unchanged', async () => {
    // No published figure may move: 0.4213 is 42.1%, before and after.
    const { texts } = await exportWith(undefined, [
      {
        ticker: 'A.NS', quantity: 40, buy_price: 100, last_price: 200,
        market_value: 8426, weight: 0.4213, sector: 'Tech',
      },
    ]);

    expect(texts).toContain('42.1%');
    expect(texts).toContain('40');
    expect(texts).not.toContain('—');
  });
});

describe('exportInstitutionalReviewPDF — addImage contract', () => {
  it('embeds a non-empty PNG with the format and compression passed explicitly', async () => {
    const { images } = await exportWith(FULL_METRICS);

    expect(images).toHaveLength(1);
    const [payload, format, x, , w, h, alias, compression] = images[0] as [
      string, string, number, number, number, number, undefined, string,
    ];

    expect(typeof payload).toBe('string');
    expect(payload.startsWith('data:image/png;base64,')).toBe(true);
    // Non-empty: real PNG bytes, not a zero-length or truncated body.
    expect(atob(payload.split(',')[1]).length).toBe(pngBytes.length);

    // 'PNG' explicit: jsPDF's canvas switch defaults to image/jpeg, the lossy
    // codec, for any format other than PNG/WEBP.
    expect(format).toBe('PNG');
    expect(compression).toBe('FAST');
    expect(alias).toBeUndefined();
    expect(typeof x).toBe('number');
    expect(typeof w).toBe('number');
    expect(h).toBeGreaterThan(0);
  });

  it('emits no image at all when there is no chartable data', async () => {
    const { images } = await exportWith(undefined);
    expect(images).toHaveLength(0);
  });

  it('emits no image, and says why in words, when rasterisation fails', async () => {
    canvasShim = 'no-context';
    const { images, texts } = await exportWith(FULL_METRICS);
    expect(images).toHaveLength(0);
    expect(texts.some((t) => t.startsWith('Chart could not be rendered:'))).toBe(true);
  });
});

describe('exportInstitutionalReviewPDF — document integrity', () => {
  it('saves under the given filename and keeps the CONFIDENTIAL stamp', async () => {
    const { saves, texts } = await exportWith(FULL_METRICS);
    expect(saves).toEqual(['Daisy_Portfolio_Risk_Review.pdf']);
    expect(texts.some((t) => t.startsWith('CONFIDENTIAL'))).toBe(true);
  });

  it('breaks the page rather than overflowing, for a long book', async () => {
    const many = Array.from({ length: 90 }, (_, i) => ({
      ticker: `T${i}.NS`, quantity: 1, buy_price: 10, last_price: 20,
      market_value: 200, weight: 1 / 90, sector: 'Tech',
    }));
    const { addPageCount } = await exportWith(undefined, many);
    expect(addPageCount).toBeGreaterThan(0);
  });

  it('names the chart series in the text layer, since the SVG has no legend', async () => {
    const { texts } = await exportWith(FULL_METRICS);
    const caption = texts.find((t) => t.startsWith('Chart series:'));
    expect(caption).toBeTruthy();
    for (const series of EXPORT_CHART_SERIES) {
      expect(caption).toContain(series.label);
    }
  });

  it('prints the per-holding shares it charts, from the same rows', async () => {
    const { texts } = await exportWith(FULL_METRICS);
    const body = texts.join('\n');
    expect(body).toContain('INFY.NS: Volatility share 31.00% · CVaR-tail share 44.00%');
    expect(body).toContain('TATAMOTORS.NS: Volatility share 69.00% · CVaR-tail share 56.00%');
  });
});

// ===========================================================================
describe('the document is written in the embedded Unicode font, not Helvetica', () => {
  // jsPDF's base-14 Helvetica is WinAnsi-encoded and has no U+20B9. Writing a
  // rupee sign through it does not throw: it emits 0xB9, which WinAnsi renders
  // as a superscript one. The bytes this wiring produces are asserted for real
  // in pdf-rupee-encoding.test.ts; these are the wiring assertions.
  it('puts both weights into the virtual FS and registers them under one family', async () => {
    const { vfsFiles, registeredFonts } = await exportWith(FULL_METRICS);
    expect(vfsFiles).toContain('DaisyExport-Regular.ttf');
    expect(vfsFiles).toContain('DaisyExport-Bold.ttf');
    expect(registeredFonts).toContain('DaisyExport-Regular.ttf->DaisyExport/normal');
    expect(registeredFonts).toContain('DaisyExport-Bold.ttf->DaisyExport/bold');
  });

  it('never selects a base-14 family, on any path through the document', async () => {
    for (const [metrics, label] of [
      [FULL_METRICS, 'with risk metrics'],
      [undefined, 'without risk metrics'],
      [{}, 'with empty metrics'],
    ] as const) {
      const { selectedFonts } = await exportWith(metrics);
      expect(selectedFonts.length).toBeGreaterThan(0);
      for (const selection of selectedFonts) {
        expect(selection, `${label} selected ${selection}`).toMatch(/^DaisyExport\//);
      }
    }
  });

  it('sets the font before every money cell, the timestamp and the risk lines', async () => {
    // The header, the total, the holdings table, the risk statements, the
    // per-holding shares, the chart caption and the disclaimer all go through
    // the same guarded writer, so the font is selected before each of them.
    const { selectedFonts, texts } = await exportWith(FULL_METRICS);
    expect(selectedFonts.length).toBeGreaterThanOrEqual(7);
    expect(texts.join('\n')).toContain('₹');
  });

  it('refuses to export rather than print a character the font cannot draw', async () => {
    // A CJK ideograph in a sector name: in no Latin subset. The old code would
    // have printed something for it without complaint.
    await expect(
      ExportService.exportInstitutionalReviewPDF({
        positions: [{ ...POSITIONS[0], sector: '數' }],
        totalValue: 1,
        currency: 'INR',
      })
    ).rejects.toThrow(/U\+6578/);
  });

  it('refuses to export at all when the font asset cannot be loaded', async () => {
    // Falling back to Helvetica here is precisely the silent-wrong-symbol
    // failure, so a missing asset must stop the export instead.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 404,
        arrayBuffer: async () => new ArrayBuffer(0),
      }) as Response)
    );
    await expect(
      ExportService.exportInstitutionalReviewPDF({
        positions: POSITIONS,
        totalValue: 1,
        currency: 'INR',
      })
    ).rejects.toThrow(/HTTP 404/);
  });
});

describe('EXPORT_CHART_SERIES is the single source of series identity', () => {
  it('defines every series a complete pair, with a distinct colour', () => {
    expect(EXPORT_CHART_SERIES.map((s) => s.key)).toEqual(['volatility', 'cvarTail']);
    expect(new Set(EXPORT_CHART_SERIES.map((s) => s.fill)).size).toBe(EXPORT_CHART_SERIES.length);
  });

  it('discloses the bar cap rather than truncating silently', async () => {
    const positions = {
      volatility: {} as Record<string, number>,
      cvar_tail: {} as Record<string, number>,
    };
    for (let i = 0; i < EXPORT_CHART_MAX_BARS + 4; i += 1) {
      const t = `T${String(i).padStart(2, '0')}.NS`;
      positions.volatility[t] = 1 / (i + 1);
      positions.cvar_tail[t] = 1 / (i + 1);
    }
    const { texts } = await exportWith({ riskContribution: { positions } });
    const body = texts.join('\n');
    expect(body).toContain('4 further holding(s) omitted');
    expect(body).toContain(`top ${EXPORT_CHART_MAX_BARS} by volatility share`);
  });
});
