/**
 * Export utilities for dashboard data
 */

import React, { createElement } from 'react';
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { jsPDF } from 'jspdf';
import * as XLSX from 'xlsx';
import { saveAs } from 'file-saver';
import { escapeCsvCell, formatCurrency } from './utils';
// Type-only: the font module is reached exclusively through `await import()`
// so neither it nor the 53 KB of TTF it fetches is in the main bundle.
import type { PdfFont, PdfFontStyle } from './pdfFont';

// Types for export data
export interface ExportableData {
    title: string;
    data: any[];
    columns?: string[];
    metadata?: {
        generatedAt: string;
        filters?: Record<string, any>;
        summary?: Record<string, any>;
    };
}

// Chart export types
export interface ChartExportOptions {
    filename: string;
    format: 'png' | 'svg' | 'pdf';
    quality?: number;
    background?: string;
}

// PDF Export Utilities
export class PDFExporter {
    protected doc: jsPDF;
    protected currentY: number = 20;
    private pageHeight: number;
    private margin: number = 20;
    private readonly font: PdfFont;
    /** Names the part of the document a glyph error should point at. */
    private section: string = 'report';

    /**
     * `font` is required, not optional: without an embedded Unicode font
     * jsPDF writes through WinAnsi Helvetica, which has no U+20B9 and silently
     * prints `¹` (0xB9) in place of `₹`. There is no default that is safe.
     */
    constructor(font: PdfFont) {
        this.font = font;
        this.doc = new jsPDF();
        font.register(this.doc);
        this.pageHeight = this.doc.internal.pageSize.height;
    }

    /** Guarded `doc.text`: a character the font cannot draw is an error. */
    protected write(value: string, x: number, y: number): void {
        this.font.assertRenders(value, this.section);
        this.doc.text(value, x, y);
    }

    /** Select a style of the embedded font, never a base-14 one. */
    protected selectFont(style: PdfFontStyle): void {
        this.doc.setFont(this.font.family, style);
    }

    addTitle(title: string, fontSize: number = 18): void {
        this.section = 'report title';
        this.doc.setFontSize(fontSize);
        this.selectFont('bold');
        this.write(title, this.margin, this.currentY);
        this.currentY += fontSize * 0.5 + 10;
    }

    addSubtitle(subtitle: string): void {
        this.section = 'report subtitle';
        this.doc.setFontSize(12);
        this.selectFont('normal');
        this.write(subtitle, this.margin, this.currentY);
        this.currentY += 10;
    }

    addTable(data: any[], columns?: string[]): void {
        if (!data.length) return;

        this.section = 'table';
        const headers = columns || Object.keys(data[0]);
        const tableWidth = this.doc.internal.pageSize.width - 2 * this.margin;
        const colWidth = tableWidth / headers.length;
        // Text is set at 10pt, so 4pt of leading leaves the baselines clear of
        // each other. A single-line row is therefore `lineHeight + rowPadding`
        // tall, which is the 8pt this table has always used.
        const lineHeight = 4;
        const rowPadding = 4;
        // 2pt of gutter, so a cell's text cannot touch the next column's.
        const cellWidth = Math.max(colWidth - 2, 1);

        // Add headers
        this.doc.setFontSize(10);
        this.selectFont('bold');

        headers.forEach((header, i) => {
            this.write(header, this.margin + i * colWidth, this.currentY);
        });

        this.currentY += 8;
        this.selectFont('normal');

        // Add data rows
        data.forEach(row => {
            // Wrap BEFORE the page-break check, so the break reserves the height
            // the row really needs rather than a fixed one it may exceed.
            // `splitTextToSize` is declared as returning `any` upstream; it
            // returns one string per line. Annotated here so the row height and
            // the write below are checked rather than assumed.
            const cells: string[][] = headers.map((header) =>
                this.doc.splitTextToSize(this.formatCellValue(row[header]), cellWidth)
            );
            const rowHeight =
                Math.max(...cells.map((lines) => lines.length)) * lineHeight + rowPadding;

            this.checkPageBreak(rowHeight);

            cells.forEach((lines, i) => {
                lines.forEach((line, lineIndex) => {
                    this.write(line, this.margin + i * colWidth, this.currentY + lineIndex * lineHeight);
                });
            });

            this.currentY += rowHeight;
        });

        this.currentY += 10;
    }

    addChart(chartData: any, title: string): void {
        // Convert chart to image and add to PDF
        // This would typically involve getting a canvas or SVG from the chart
        // For now, we'll add a placeholder
        this.addSubtitle(`Chart: ${title}`);
        this.doc.setDrawColor(200, 200, 200);
        this.doc.rect(this.margin, this.currentY, 150, 80);
        this.write('Chart Image', this.margin + 60, this.currentY + 40);
        this.currentY += 90;
    }

    addMetadata(metadata: Record<string, any>): void {
        this.addSubtitle('Generated Information:');
        this.doc.setFontSize(8);
        this.section = 'metadata';

        Object.entries(metadata).forEach(([key, value]) => {
            this.write(`${key}: ${value}`, this.margin, this.currentY);
            this.currentY += 6;
        });

        this.currentY += 10;
    }

    private checkPageBreak(rowHeight: number): void {
        if (this.currentY + rowHeight > this.pageHeight - this.margin) {
            this.doc.addPage();
            this.currentY = this.margin;
        }
    }

    /**
     * A cell's printed text.
     *
     * A string is printed WHOLE. It used to be cut at 20 characters, which
     * silently shortened `Information Technology` to `Information Technolo` in
     * an exported document with nothing saying so — a silent data alteration,
     * the same defect class as the rupee sign printing as a superscript one.
     * `addTable` wraps the result across lines instead, so nothing is dropped;
     * the neighbouring institutional-review path does the same thing for the
     * same reason, and where it does cap (`EXPORT_CHART_MAX_BARS`) it prints
     * the count it omitted rather than quietly losing the rows.
     */
    private formatCellValue(value: any): string {
        if (value === null || value === undefined) return '';
        if (typeof value === 'number') {
            return value.toLocaleString('en-IN', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
        }
        return String(value);
    }

    save(filename: string): void {
        this.doc.save(filename);
    }

    getBlob(): Blob {
        return this.doc.output('blob');
    }

    addPage(): void {
        this.doc.addPage();
    }

    resetYPosition(): void {
        this.currentY = 20;
    }
}

// Excel Export Utilities
export class ExcelExporter {
    static exportToExcel(data: ExportableData[], filename: string): void {
        const workbook = XLSX.utils.book_new();

        data.forEach((sheetData, index) => {
            const worksheet = XLSX.utils.json_to_sheet(sheetData.data, {
                header: sheetData.columns
            });

            // Add sheet name
            const sheetName = sheetData.title.substring(0, 31); // Excel sheet name limit
            XLSX.utils.book_append_sheet(workbook, worksheet, sheetName);

            // Add metadata sheet if available
            if (sheetData.metadata) {
                const metadataSheet = XLSX.utils.json_to_sheet([
                    { key: 'title', value: sheetData.title },
                    { key: 'generatedAt', value: sheetData.metadata.generatedAt },
                    ...Object.entries(sheetData.metadata.filters || {}).map(([key, value]) => ({
                        key: `filter_${key}`,
                        value: JSON.stringify(value)
                    })),
                    ...Object.entries(sheetData.metadata.summary || {}).map(([key, value]) => ({
                        key: `summary_${key}`,
                        value: JSON.stringify(value)
                    }))
                ]);
                XLSX.utils.book_append_sheet(workbook, metadataSheet, `${sheetName}_metadata`);
            }
        });

        const excelBuffer = XLSX.write(workbook, { bookType: 'xlsx', type: 'array' });
        const excelBlob = new Blob([excelBuffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        saveAs(excelBlob, `${filename}.xlsx`);
    }

    static exportSingleSheet(data: any[], filename: string, sheetName: string = 'Data'): void {
        const worksheet = XLSX.utils.json_to_sheet(data);
        const workbook = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(workbook, worksheet, sheetName);

        const excelBuffer = XLSX.write(workbook, { bookType: 'xlsx', type: 'array' });
        const excelBlob = new Blob([excelBuffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        saveAs(excelBlob, `${filename}.xlsx`);
    }
}

// CSV Export Utilities
export class CSVExporter {
    static exportToCSV(data: any[], filename: string): void {
        if (!data.length) return;

        const headers = Object.keys(data[0]);
        const csvContent = [
            headers.map(escapeCsvCell).join(','),
            ...data.map(row =>
                headers.map(header => escapeCsvCell(row[header])).join(',')
            )
        ].join('\n');

        const csvBlob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        saveAs(csvBlob, `${filename}.csv`);
    }

    static exportMultipleSheets(data: ExportableData[], filename: string): void {
        // For multiple CSV files, create individual files
        data.forEach((sheetData, index) => {
            const sheetFilename = `${filename}_${index + 1}_${sheetData.title.replace(/\s+/g, '_')}`;
            this.exportToCSV(sheetData.data, sheetFilename);
        });
    }
}

// Chart Export Utilities
export class ChartExporter {
    /**
     * Rasterise a live chart surface to a PNG blob.
     *
     * The parameter stays `HTMLElement` because `ExportPanel` passes one, but
     * only an `<svg>` is accepted. A non-svg input used to fall into a branch
     * that called `toBlob` on a canvas nothing had ever drawn on, which
     * resolves a perfectly valid white PNG — the caller then saved a blank
     * image under a chart's name with no error anywhere. An input that cannot
     * be a chart surface is now rejected.
     */
    static async exportChart(
        chartElement: HTMLElement,
        options: ChartExportOptions
    ): Promise<Blob> {
        if (options.format !== 'png') {
            throw new Error(
                `Chart export supports raster 'png' only; received '${options.format}'. ` +
                    'A canvas cannot carry PDF or SVG bytes through a blob typed image/<format>.'
            );
        }
        const svg = assertExportSvg(chartElement);
        const dataUrl = await svgToPngDataUrl(svg, {
            background: options.background,
        });
        return dataUrlToBlob(dataUrl);
    }
}

// ---------------------------------------------------------------------------
// Risk metrics snapshot
// ---------------------------------------------------------------------------
//
// Declared here rather than in `@/types` because that file is owned by another
// workstream. Every field is optional AND nullable on purpose: the three
// analytics routes below publish `null` for a quantity they declined to
// measure, and a PDF sentence that quotes a `null` is exactly the fabrication
// this section used to emit.

/** `GET /analytics/risk-contribution` — the subset this document may quote. */
export interface RiskContributionSnapshot {
    positions?: {
        volatility?: Record<string, number> | null;
        cvar_tail?: Record<string, number> | null;
    } | null;
    /** Already a percentage (e.g. 18.4), NOT a fraction. */
    portfolio_volatility_annualized?: number | null;
    /** Already a fraction of return (e.g. -0.0234), 5th percentile. */
    portfolio_var_95_daily?: number | null;
    /** Already a fraction of return; mean of the tail days. */
    portfolio_cvar_95_daily?: number | null;
    window?: { start?: string | null; end?: string | null } | null;
    data_status?: string | null;
}

/** `GET /analytics/liquidity-limits` — participation-based liquidation horizon. */
export interface LiquidityLimitsSnapshot {
    portfolio_weighted_days_to_liquidate_10pct?: number | null;
    portfolio_weighted_days_to_liquidate_20pct?: number | null;
    data_status?: string | null;
}

/** `GET /analytics/liquidity` — scored band, not a measurement of a horizon. */
export interface LiquiditySnapshot {
    liquidation_time_days?: string | null;
    overall_score?: number | null;
    overall_band?: string | null;
    risk_level?: string | null;
    data_status?: string | null;
}

export interface RiskMetricsSnapshot {
    riskContribution?: RiskContributionSnapshot | null;
    liquidityLimits?: LiquidityLimitsSnapshot | null;
    liquidity?: LiquiditySnapshot | null;
}

/** One printed `label  value` row. Never constructed from a missing field. */
export interface RiskStatement {
    label: string;
    value: string;
}

function finiteNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function nonEmptyString(value: unknown): string | null {
    return typeof value === 'string' && value.trim() !== '' ? value.trim() : null;
}

/**
 * The risk sentences, as a pure function of what the caller was handed.
 *
 * A statement exists if and only if its own field is present and finite. The
 * list is never padded, never reordered into a claim the data does not carry,
 * and never back-filled from another route: an empty list is a valid, correct
 * answer and means "this document quotes no risk figure".
 */
export function buildRiskStatements(metrics?: RiskMetricsSnapshot | null): RiskStatement[] {
    if (!metrics) return [];
    const statements: RiskStatement[] = [];

    const contribution = metrics.riskContribution;
    if (contribution) {
        // `portfolio_volatility_annualized` is already a percentage, so it is
        // formatted with a plain grouped number and a literal `%` rather than
        // through `formatPercentage`, whose documented input is a fraction.
        const annualVol = finiteNumber(contribution.portfolio_volatility_annualized);
        if (annualVol !== null) {
            statements.push({
                label: 'Portfolio volatility, annualised',
                value: `${formatNumber(annualVol, 2)}%`,
            });
        }
        // VaR/CVaR 95% are the 5th percentile and the mean of the tail days of
        // a RETURN series, so they are fractions and take the fraction contract.
        const var95 = finiteNumber(contribution.portfolio_var_95_daily);
        if (var95 !== null) {
            statements.push({
                label: 'Portfolio VaR 95%, daily return threshold',
                value: formatPercentage(var95, 2),
            });
        }
        const cvar95 = finiteNumber(contribution.portfolio_cvar_95_daily);
        if (cvar95 !== null) {
            statements.push({
                label: 'Portfolio CVaR 95%, daily mean tail return',
                value: formatPercentage(cvar95, 2),
            });
        }
    }

    const limits = metrics.liquidityLimits;
    if (limits) {
        const days10 = finiteNumber(limits.portfolio_weighted_days_to_liquidate_10pct);
        if (days10 !== null) {
            statements.push({
                label: 'Weighted days to liquidate at 10% of ADV',
                value: `${formatNumber(days10, 2)} days`,
            });
        }
        const days20 = finiteNumber(limits.portfolio_weighted_days_to_liquidate_20pct);
        if (days20 !== null) {
            statements.push({
                label: 'Weighted days to liquidate at 20% of ADV',
                value: `${formatNumber(days20, 2)} days`,
            });
        }
    }

    const liquidity = metrics.liquidity;
    if (liquidity) {
        const band = nonEmptyString(liquidity.liquidation_time_days);
        if (band !== null) {
            statements.push({
                label: 'Liquidity-scored liquidation band',
                value: band,
            });
        }
    }

    return statements;
}

/** One ticker's share of each risk model, as the chart and the table print it. */
export interface RiskContributionDatum {
    ticker: string;
    volatility: number;
    cvarTail: number;
}

/**
 * Tickers measurable under BOTH models, as a share of each model's total.
 *
 * A ticker the volatility model covers but the tail model does not is dropped
 * rather than drawn at zero: a zero bar asserts "this ticker contributes no
 * tail risk", which is the opposite of what the route's exclusion means.
 */
export function buildRiskContributionSeries(
    metrics?: RiskMetricsSnapshot | null
): RiskContributionDatum[] {
    const positions = metrics?.riskContribution?.positions;
    const volatility = positions?.volatility;
    const cvarTail = positions?.cvar_tail;
    if (!volatility || !cvarTail) return [];

    const rows: RiskContributionDatum[] = [];
    for (const ticker of Object.keys(volatility)) {
        const vol = finiteNumber(volatility[ticker]);
        const cvar = finiteNumber(cvarTail[ticker]);
        if (vol === null || cvar === null) continue;
        rows.push({ ticker, volatility: vol, cvarTail: cvar });
    }
    // Sorted by volatility share, descending, so the PDF table and the chart
    // agree on reading order and the output is byte-stable across runs.
    rows.sort((a, b) => b.volatility - a.volatility || a.ticker.localeCompare(b.ticker));
    return rows;
}

// ---------------------------------------------------------------------------
// Chart rasterisation
// ---------------------------------------------------------------------------

/** Rasterised embed area scales with DPR squared; past 2x it is invisible. */
export const MAX_EXPORT_DPR = 2;

export function exportDevicePixelRatio(raw?: number | null): number {
    const dpr = typeof raw === 'number' && Number.isFinite(raw) && raw > 0 ? raw : 1;
    return Math.min(dpr, MAX_EXPORT_DPR);
}

export interface RasterSize {
    cssWidth: number;
    cssHeight: number;
    pixelWidth: number;
    pixelHeight: number;
    dpr: number;
}

export function rasterSize(cssWidth: number, cssHeight: number, rawDpr?: number | null): RasterSize {
    const dpr = exportDevicePixelRatio(rawDpr);
    return {
        cssWidth,
        cssHeight,
        pixelWidth: Math.round(cssWidth * dpr),
        pixelHeight: Math.round(cssHeight * dpr),
        dpr,
    };
}

/**
 * The one place that decides an export target is an SVG surface.
 *
 * A `ResponsiveContainer` ref is a `div`, and with fixed-number dimensions it
 * is permanently `null`; recharts 3 forwards a chart ref to the root
 * `svg.recharts-surface`. Both used to fall through to a never-drawn canvas,
 * whose `toBlob` resolves a valid white PNG. Anything that is not a
 * non-zero-size `svg` is now an error.
 */
export function assertExportSvg(node: unknown): SVGSVGElement {
    if (node === null || node === undefined) {
        throw new Error(
            'Chart export target is null. Attach the ref to the chart component, not to its ResponsiveContainer.'
        );
    }
    if (!(node instanceof SVGElement) || node.tagName.toLowerCase() !== 'svg') {
        const actual = (node as { tagName?: string } | null)?.tagName ?? typeof node;
        throw new Error(
            `Chart export target must be an <svg> element, received <${String(actual).toLowerCase()}>. ` +
                'A wrapper element carries no chart geometry.'
        );
    }
    return node as SVGSVGElement;
}

/**
 * Is this the recharts surface, specifically?
 *
 * recharts 3 forwards a chart ref to the root `svg.recharts-surface` (the v3
 * breaking change: "we no longer use CategoricalChartWrapper, and the ref now
 * refers to the main SVG element"). "Is it an svg" is not enough — the app is
 * full of inline icon `<svg>`s, and a ref mis-wired onto one of those would
 * satisfy an svg check while carrying no chart geometry at all. Matched on a
 * whole class token, not a substring, so `recharts-surface-wrapper` fails.
 */
export function isRechartsSurface(node: unknown): node is SVGSVGElement {
    if (node === null || node === undefined) return false;
    if (!(node instanceof SVGElement) || node.tagName.toLowerCase() !== 'svg') return false;
    return (node.getAttribute('class') ?? '').split(/\s+/).includes('recharts-surface');
}

/**
 * The size the chart was actually drawn at, in CSS pixels.
 *
 * A laid-out surface answers from its rect. An offscreen or not-yet-laid-out
 * one reports `0x0`, which is NOT a usable measurement — `toBlob` on a 0x0
 * canvas resolves a 0-byte blob rather than rejecting — so the SVG's own
 * width/height attributes (then its viewBox) are read instead. When neither
 * source yields a positive size this throws instead of returning a default.
 */
export function resolveExportChartSize(svg: SVGSVGElement): { width: number; height: number } {
    const rect = typeof svg.getBoundingClientRect === 'function' ? svg.getBoundingClientRect() : null;
    if (rect && rect.width > 0 && rect.height > 0) {
        return { width: rect.width, height: rect.height };
    }

    const attrWidth = Number.parseFloat(svg.getAttribute('width') ?? '');
    const attrHeight = Number.parseFloat(svg.getAttribute('height') ?? '');
    if (attrWidth > 0 && attrHeight > 0) {
        return { width: attrWidth, height: attrHeight };
    }

    const viewBox = (svg.getAttribute('viewBox') ?? '').trim().split(/[\s,]+/).map(Number);
    if (viewBox.length === 4 && viewBox.every(Number.isFinite) && viewBox[2] > 0 && viewBox[3] > 0) {
        return { width: viewBox[2], height: viewBox[3] };
    }

    throw new Error(
        'Export chart has no measurable size: 0x0 layout rect and no usable width/height/viewBox. ' +
            'Refusing to embed a blank image.'
    );
}

// Class selectors, not element+class: a recharts bar carries BOTH
// `recharts-rectangle` and `recharts-bar-rectangle`, and an element-qualified
// list would count the same node twice.
const MARK_SELECTOR = [
    'path.recharts-curve',
    '.recharts-rectangle',
    '.recharts-dot',
].join(', ');

export interface ExportChartMarks {
    marks: number;
    texts: number;
}

export function countExportChartMarks(svg: SVGSVGElement): ExportChartMarks {
    return {
        marks: svg.querySelectorAll(MARK_SELECTOR).length,
        texts: svg.querySelectorAll('text').length,
    };
}

/**
 * A chart that drew its axes and nothing else is the failure the whole
 * pipeline exists to prevent: visually fine, semantically empty. Axes-only is
 * rejected separately from fully-empty because the two call for different
 * fixes and the reader is told which one happened.
 */
export function assertExportChartHasMarks(svg: SVGSVGElement): ExportChartMarks {
    const { marks, texts } = countExportChartMarks(svg);
    if (marks === 0 && texts === 0) {
        throw new Error('Export chart rendered no content at all (no axes, no data marks).');
    }
    if (marks === 0) {
        throw new Error(
            'Export chart rendered axes but no data marks. The embed would be a blank chart with a live-looking frame.'
        );
    }
    return { marks, texts };
}

export interface SvgRasterOptions {
    /** Overrides the display's `devicePixelRatio`. Capped at 2 regardless. */
    dpr?: number | null;
    background?: string;
}

function bytesToPngDataUrl(bytes: Uint8Array): string {
    let binary = '';
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
        binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
    }
    return `data:image/png;base64,${btoa(binary)}`;
}

function dataUrlToBlob(dataUrl: string): Blob {
    const [meta, base64] = dataUrl.split(',');
    const mime = /:(image\/[a-z+]+)/.exec(meta)?.[1] ?? 'image/png';
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: mime });
}

/**
 * Rasterise an SVG surface to a PNG data URL.
 *
 * The PNG is handed to `addImage` already encoded rather than as a live
 * canvas: jsPDF's canvas overload calls `toDataURL` again internally
 * (`jspdf.es.js` `extractImageData`), which re-encodes from whatever the
 * switch above it chose — and that switch defaults to `image/jpeg`, the lossy
 * codec, for any format other than PNG/WEBP. Encoding once, here, with
 * `toBlob(cb, 'image/png')`, pins the format at the point it can actually be
 * wrong. The bytes are identical; the re-encode and the default are not.
 */
export async function svgToPngDataUrl(
    node: unknown,
    options: SvgRasterOptions = {}
): Promise<string> {
    const svg = assertExportSvg(node);
    assertExportChartHasMarks(svg);
    const { width: cssWidth, height: cssHeight } = resolveExportChartSize(svg);
    const { pixelWidth, pixelHeight, dpr } = rasterSize(cssWidth, cssHeight, options.dpr);

    const canvas = document.createElement('canvas');
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
        throw new Error('Cannot get a 2D canvas context for chart export.');
    }
    if (options.background) {
        ctx.fillStyle = options.background;
        ctx.fillRect(0, 0, pixelWidth, pixelHeight);
    }
    // Scale BEFORE drawing: every subsequent draw is expressed in CSS pixels
    // and lands on a dpr-sized backing store, so thin antialiased strokes and
    // 10px tick text survive the embed.
    ctx.scale(dpr, dpr);

    const markup = new XMLSerializer().serializeToString(svg);
    const svgUrl = URL.createObjectURL(new Blob([markup], { type: 'image/svg+xml;charset=utf-8' }));
    try {
        const image = new Image();
        await new Promise<void>((resolve, reject) => {
            image.onload = () => resolve();
            image.onerror = () => reject(new Error('Failed to load the chart SVG for rasterisation.'));
            image.src = svgUrl;
        });
        ctx.drawImage(image, 0, 0);
    } finally {
        URL.revokeObjectURL(svgUrl);
    }

    const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((result) => {
            if (result) resolve(result);
            else reject(new Error('Canvas produced no blob for the chart embed.'));
        }, 'image/png');
    });
    const bytes = new Uint8Array(await blob.arrayBuffer());
    if (bytes.byteLength === 0) {
        throw new Error(
            'Chart rasterised to a 0-byte PNG (the export surface had no drawable area). Refusing to embed it.'
        );
    }
    return bytesToPngDataUrl(bytes);
}

// ---------------------------------------------------------------------------
// The offscreen export chart
// ---------------------------------------------------------------------------

export const EXPORT_CHART_WIDTH = 720;
export const EXPORT_CHART_HEIGHT = 300;
/** Bars beyond this do not fit the page width legibly. */
export const EXPORT_CHART_MAX_BARS = 12;

/**
 * Single source of truth for the export chart's series. The chart's `<Bar>`
 * elements and the caption printed beneath the image are both built from this
 * list, so a series can never be drawn without being named — recharts 3
 * renders `<Legend>` through a portal into an HTML `div` OUTSIDE the `<svg>`,
 * so an SVG capture of a legend-bearing chart has no legend at all and the
 * colour key would be the only (unprintable) identity.
 */
export const EXPORT_CHART_SERIES = [
    { key: 'volatility', label: 'Volatility share', fill: '#4338ca' },
    { key: 'cvarTail', label: 'CVaR-tail share', fill: '#b45309' },
] as const;

function nextFrame(): Promise<void> {
    return new Promise((resolve) => {
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(() => resolve());
        } else {
            setTimeout(resolve, 0);
        }
    });
}

export interface ExportRiskChartResult {
    /** The recharts surface, when the chart mounted at all. */
    svg: SVGSVGElement | null;
    /** `XMLSerializer` output of the surface, when it mounted. */
    markup: string | null;
    marks: ExportChartMarks | null;
    /** PNG payload for `addImage`, or null when rasterisation failed. */
    dataUrl: string | null;
    /** Why the chart could not be produced, in words fit to print. Null on success. */
    error: string | null;
}

/**
 * Mount a purpose-built chart offscreen, rasterise it, and always tear it down.
 *
 * Deliberately not "capture whatever chart is on screen": that races the
 * chart's own loading/empty state, can read a stale render, and can measure a
 * `0x0` rect — all of which produce a visually fine, semantically empty PDF.
 * This chart is fed the same rows the PDF table prints and is laid out at a
 * fixed size, so the two cannot disagree.
 *
 * Never throws. The caller must be able to print the reason next to the
 * missing chart, which is the whole point: a blank chart with no error is
 * worse than a PDF that says it could not render one.
 */
export async function renderExportRiskChart(
    data: RiskContributionDatum[],
    options: SvgRasterOptions = {}
): Promise<ExportRiskChartResult> {
    const failed = (error: string): ExportRiskChartResult => ({
        svg: null, markup: null, marks: null, dataUrl: null, error,
    });

    if (data.length === 0) {
        return failed('no holding has a risk share measurable under both models.');
    }

    const host = document.createElement('div');
    host.setAttribute('data-export-chart', 'risk-contribution');
    host.setAttribute('aria-hidden', 'true');
    // position:fixed (not display:none, which would skip layout entirely) and
    // pushed off-viewport so the export never flashes on screen.
    host.style.cssText =
        `position:fixed;left:-10000px;top:0;width:${EXPORT_CHART_WIDTH}px;` +
        `height:${EXPORT_CHART_HEIGHT}px;pointer-events:none;opacity:0;`;
    document.body.appendChild(host);

    const ref = React.createRef<SVGSVGElement>();
    const root = createRoot(host);
    // Kept outside the try so a late failure (rasterisation) still reports the
    // surface it failed on, which is what makes the printed reason diagnosable.
    let mounted: SVGSVGElement | null = null;
    let markup: string | null = null;
    let marks: ExportChartMarks | null = null;
    try {
        const tree = createElement(
            BarChart,
            {
                ref,
                width: EXPORT_CHART_WIDTH,
                height: EXPORT_CHART_HEIGHT,
                data,
                margin: { top: 8, right: 16, bottom: 24, left: 8 },
                style: { fontFamily: 'Inter, system-ui, sans-serif', fontSize: 11 },
            },
            createElement(CartesianGrid, { strokeDasharray: '3 3' }),
            createElement(XAxis, { dataKey: 'ticker', tick: { fontSize: 10 } }),
            createElement(YAxis, {
                tick: { fontSize: 10 },
                width: 44,
                tickFormatter: (value: number) => `${Math.round(value * 100)}%`,
            }),
            ...EXPORT_CHART_SERIES.map((series) =>
                createElement(Bar, {
                    key: series.key,
                    dataKey: series.key,
                    name: series.label,
                    fill: series.fill,
                    isAnimationActive: false,
                })
            )
        );
        flushSync(() => root.render(tree));
        await nextFrame();

        const svg = ref.current;
        if (!svg) {
            return failed(
                'the chart forwarded no ref. The ref must sit on the chart component so recharts forwards it to <svg class="recharts-surface">.'
            );
        }
        // Read before the guard: `isRechartsSurface` is a type predicate, so
        // inside its negative branch `svg` is already narrowed to `never`.
        const tagName = svg.tagName.toLowerCase();
        if (!isRechartsSurface(svg)) {
            return failed(
                `the forwarded ref is <${tagName}> rather than the recharts surface, so it holds no chart geometry.`
            );
        }

        mounted = svg;
        marks = countExportChartMarks(svg);
        markup = new XMLSerializer().serializeToString(svg);
        try {
            assertExportChartHasMarks(svg);
        } catch (error) {
            return {
                svg, markup, marks,
                dataUrl: null,
                error: error instanceof Error ? error.message : String(error),
            };
        }

        const dataUrl = await svgToPngDataUrl(svg, options);
        return { svg, markup, marks, dataUrl, error: null };
    } catch (error) {
        return {
            svg: mounted,
            markup,
            marks,
            dataUrl: null,
            error: error instanceof Error ? error.message : String(error),
        };
    } finally {
        flushSync(() => root.unmount());
        host.remove();
    }
}

// ---------------------------------------------------------------------------
// Main Export Service
// ---------------------------------------------------------------------------

export class ExportService {
    static async exportPDF(data: ExportableData[], filename: string): Promise<void> {
        // Dynamic import, so the font module (and the TTF it fetches) stay out
        // of the bundle for anyone who never exports a PDF.
        const { loadPdfFont } = await import('./pdfFont');
        const pdf = new PDFExporter(await loadPdfFont());

        data.forEach((sheetData, index) => {
            if (index > 0) {
                pdf.addPage();
                pdf.resetYPosition();
            }

            pdf.addTitle(sheetData.title);
            pdf.addTable(sheetData.data, sheetData.columns);

            if (sheetData.metadata) {
                pdf.addMetadata(sheetData.metadata);
            }
        });

        pdf.save(filename);
    }

    static exportExcel(data: ExportableData[], filename: string): void {
        ExcelExporter.exportToExcel(data, filename);
    }

    static exportCSV(data: any[], filename: string): void {
        CSVExporter.exportToCSV(data, filename);
    }

    static async exportChart(chartElement: HTMLElement, options: ChartExportOptions): Promise<void> {
        try {
            const blob = await ChartExporter.exportChart(chartElement, options);
            saveAs(blob, `${options.filename}.${options.format}`);
        } catch (error) {
            console.error('Chart export failed:', error);
            throw error;
        }
    }

    /**
     * The institutional review tear-sheet.
     *
     * Every sentence and every figure below is derived from `portfolioData`.
     * A field the caller did not supply produces NO sentence — not a softened
     * one, not one borrowed from a neighbouring section, not a default. That
     * is the whole contract: this document is stamped CONFIDENTIAL, so a
     * sentence asserting a methodology the export never ran is worse than a
     * shorter document.
     */
    static async exportInstitutionalReviewPDF(portfolioData: {
        positions: any[];
        totalValue: number;
        currency: string;
        riskMetrics?: RiskMetricsSnapshot | null;
    }, filename: string = 'Daisy_Portfolio_Risk_Review'): Promise<void> {
        const doc = new jsPDF();
        // Embedded BEFORE any text is written. jsPDF's base-14 Helvetica is
        // WinAnsi-encoded and has no U+20B9: writing a rupee sign through it
        // does not throw, it emits 0xB9, which WinAnsi renders as a superscript
        // one. A CONFIDENTIAL document would then print the wrong symbol where
        // the reader expects a currency, with nothing reporting it.
        //
        // Dynamic import: the module and the TTF it fetches stay out of the
        // bundle for anyone who never exports a PDF.
        const { loadPdfFont } = await import('./pdfFont');
        const pdfFont = await loadPdfFont();
        pdfFont.register(doc);

        /** Which part of the document is being written, for glyph errors. */
        let section = 'header';
        /** The only path to `doc.text` in this document. */
        const write = (value: string, x: number, y: number): void => {
            pdfFont.assertRenders(value, section);
            doc.text(value, x, y);
        };
        /** Never a base-14 family: only the embedded one can draw a rupee. */
        const selectFont = (style: PdfFontStyle): void => {
            doc.setFont(pdfFont.family, style);
        };

        const margin = 15;
        let y = 20;
        const currency = portfolioData.currency || 'INR';
        // One formatter for the whole document, so no column can end up with a
        // bare number next to a symbolised one. `formatCurrency` gives the
        // rupee sign and en-IN grouping for INR and an explicit symbol for
        // anything else — no `$` is printed for a book that is not in dollars.
        const money = (value: unknown) =>
            formatCurrency(typeof value === 'number' && Number.isFinite(value) ? value : null, currency);

        // Header
        doc.setFillColor(15, 23, 42); // slate-900
        doc.rect(0, 0, doc.internal.pageSize.width, 35, 'F');

        doc.setTextColor(255, 255, 255);
        doc.setFontSize(18);
        selectFont('bold');
        write('DAISY RISK ENGINE', margin, y);

        doc.setFontSize(10);
        selectFont('normal');
        doc.setTextColor(148, 163, 184); // slate-400
        write('Institutional Quantitative Risk & Portfolio Review', margin, y + 7);

        doc.setFontSize(9);
        // 'en-IN' is passed explicitly: a bare toLocaleString() follows the
        // reader's machine locale, so two identical portfolios exported from
        // two desks produced two different documents.
        write(`Generated: ${new Date().toLocaleString('en-IN')}`, doc.internal.pageSize.width - margin - 55, y);

        y = 48;
        doc.setTextColor(30, 41, 59);

        // Portfolio Summary Box
        section = 'portfolio summary';
        doc.setFontSize(13);
        selectFont('bold');
        write('Portfolio Executive Summary', margin, y);
        y += 8;

        doc.setFontSize(10);
        selectFont('normal');
        write(`Total Portfolio Value: ${money(portfolioData.totalValue)}`, margin, y);
        write(`Active Holdings: ${portfolioData.positions.length} Equities`, margin + 100, y);
        y += 12;

        // Holdings Table
        section = 'holdings table';
        doc.setFontSize(12);
        selectFont('bold');
        write('Holdings & Asset Allocation', margin, y);
        y += 6;

        const headers = ['Ticker', 'Quantity', 'Buy Price', 'Last Price', 'Market Value', 'Weight', 'Sector'];
        const colWidths = [28, 22, 25, 25, 32, 18, 30];
        
        doc.setFillColor(241, 245, 249);
        doc.rect(margin, y, 180, 7, 'F');
        doc.setFontSize(9);
        selectFont('bold');
        doc.setTextColor(51, 65, 85);

        let currentX = margin + 2;
        headers.forEach((h, idx) => {
            write(h, currentX, y + 5);
            currentX += colWidths[idx];
        });
        y += 9;

        selectFont('normal');
        doc.setTextColor(30, 41, 59);

        const pageBottom = () => doc.internal.pageSize.height - margin;
        const checkBreak = (rowH: number) => {
            if (y + rowH > pageBottom()) {
                doc.addPage();
                y = margin;
            }
        };

        portfolioData.positions.forEach(p => {
            checkBreak(7);
            currentX = margin + 2;
            const values = [
                String(p.ticker || ''),
                String(p.quantity || 0),
                money(p.buy_price),
                money(p.last_price),
                // Market value keeps en-IN lakh/crore grouping; the symbol comes
                // from the same formatter as the price columns.
                money(p.market_value),
                `${((p.weight || 0) * 100).toFixed(1)}%`,
                // A holding with no sector is unclassified. "General" was a
                // label this document invented and stamped as fact.
                nonEmptyString(p.sector) ?? '—'
            ];

            values.forEach((v, idx) => {
                write(v, currentX, y + 4);
                currentX += colWidths[idx];
            });

            doc.setDrawColor(226, 232, 240);
            doc.line(margin, y + 6, margin + 180, y + 6);
            y += 7;
        });

        y += 10;
        checkBreak(60);

        // ---- Risk section -------------------------------------------------
        // Header only when there is something to put under it.
        section = 'risk section';
        const statements = buildRiskStatements(portfolioData.riskMetrics);
        const series = buildRiskContributionSeries(portfolioData.riskMetrics);
        if (statements.length > 0 || series.length > 0) {
            doc.setFontSize(12);
            selectFont('bold');
            write('Quantitative Risk & Microstructure Summary', margin, y);
            y += 8;

            doc.setFontSize(9);
            selectFont('normal');
            if (statements.length === 0) {
                doc.setTextColor(148, 163, 184);
                write('No risk metrics were returned for this portfolio.', margin, y);
                y += 12;
            } else {
                statements.forEach((statement) => {
                    checkBreak(6);
                    write(`${statement.label}: ${statement.value}`, margin, y);
                    y += 5;
                });
                y += 6;
            }
        } else {
            // The section is absent, not restated as prose: there is no
            // measured quantity to introduce, and inventing a description of
            // the methodology is what produced the three sentences this
            // replaces.
            doc.setFontSize(9);
            selectFont('normal');
            doc.setTextColor(148, 163, 184);
            write('Quantitative risk: no risk metrics were available for this export.', margin, y);
            y += 12;
            doc.setTextColor(30, 41, 59);
        }

        // Per-ticker shares, the same rows the chart below is drawn from.
        if (series.length > 0) {
            checkBreak(20);
            const plotted = series.slice(0, EXPORT_CHART_MAX_BARS);
            const omitted = series.length - plotted.length;

            doc.setFontSize(9);
            selectFont('bold');
            write('Risk contribution by holding (share of model total)', margin, y);
            y += 6;

            selectFont('normal');
            doc.setTextColor(30, 41, 59);
            plotted.forEach((row) => {
                checkBreak(6);
                write(
                    `${row.ticker}: ${EXPORT_CHART_SERIES[0].label} ${formatPercentage(row.volatility, 2)} · ` +
                        `${EXPORT_CHART_SERIES[1].label} ${formatPercentage(row.cvarTail, 2)}`,
                    margin,
                    y
                );
                y += 5;
            });
            if (omitted > 0) {
                // The cap is disclosed rather than left as a silent truncation.
                doc.setTextColor(148, 163, 184);
                write(`${omitted} further holding(s) omitted; the table and chart show the top ${plotted.length} by volatility share.`, margin, y);
                y += 5;
                doc.setTextColor(30, 41, 59);
            }
            y += 8;

            // ---- Chart -----------------------------------------------------
            // Rasterise from a chart mounted for this purpose, not from
            // whatever happens to be on screen. On failure the document says
            // so in words; it never reserves blank space that reads as a
            // chart that had nothing to show.
            checkBreak(EXPORT_CHART_HEIGHT * 0.25 + 16);
            const chart = await renderExportRiskChart(plotted, { background: '#ffffff' });
            if (chart.dataUrl) {
                const chartWidth = 180;
                const chartHeight = chartWidth * (EXPORT_CHART_HEIGHT / EXPORT_CHART_WIDTH);
                doc.addImage(
                    chart.dataUrl,
                    'PNG',
                    margin,
                    y,
                    chartWidth,
                    chartHeight,
                    undefined,
                    'FAST'
                );
                y += chartHeight + 4;
                // Series identity, printed. recharts 3 renders <Legend> through
                // a portal into an HTML div outside the <svg>, so the raster
                // above contains no legend and the colour key is unreachable.
                section = 'chart caption';
                doc.setFontSize(8);
                doc.setTextColor(100, 116, 139);
                write(
                    `Chart series: ${EXPORT_CHART_SERIES.map((s) => s.label).join(' · ')} (left bar, right bar per holding).`,
                    margin,
                    y
                );
                y += 10;
                doc.setTextColor(30, 41, 59);
            } else {
                section = 'chart failure notice';
                doc.setFontSize(8);
                doc.setTextColor(148, 163, 184);
                write(`Chart could not be rendered: ${chart.error}`, margin, y);
                y += 10;
                doc.setTextColor(30, 41, 59);
            }
        }

        // Disclaimer on the last page (not a fixed y=280 that overlaps mid-table)
        section = 'disclaimer';
        checkBreak(16);
        doc.setFontSize(8);
        doc.setTextColor(148, 163, 184);
        write('CONFIDENTIAL — Generated for internal investment management purposes only. Daisy Risk Engine.', margin, Math.min(y + 8, pageBottom() - 4));

        doc.save(`${filename}.pdf`);
    }
}

// Export progress tracking
export class ExportProgress {
    private progressCallbacks: Map<string, (progress: number) => void> = new Map();

    setProgress(id: string, progress: number): void {
        const callback = this.progressCallbacks.get(id);
        if (callback) {
            callback(Math.min(100, Math.max(0, progress)));
        }
    }

    onProgress(id: string, callback: (progress: number) => void): void {
        this.progressCallbacks.set(id, callback);
    }

    removeProgress(id: string): void {
        this.progressCallbacks.delete(id);
    }
}

// Utility functions for data formatting
export const formatNumber = (value: number, decimals: number = 2): string => {
    return value.toLocaleString('en-IN', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
};

export const formatPercentage = (value: number, decimals: number = 2): string => {
    return `${formatNumber(value * 100, decimals)}%`;
};

// Single en-IN/INR-correct implementation lives in utils.ts (04-B8);
// USD formatting still routes through utils with an explicit 'USD' argument.
export { formatCurrency } from './utils';

// Data transformation utilities
export const transformTableData = (data: any[], columnMap?: Record<string, string>): any[] => {
    if (!columnMap) return data;

    return data.map(row => {
        const transformed: any = {};
        Object.entries(columnMap).forEach(([key, label]) => {
            transformed[label] = row[key];
        });
        return transformed;
    });
};

export const generateMetadata = (
    title: string,
    filters?: Record<string, any>,
    summary?: Record<string, any>
): ExportableData['metadata'] => ({
    generatedAt: new Date().toISOString(),
    filters,
    summary
});