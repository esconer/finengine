/**
 * Export utilities for dashboard data
 */

import { jsPDF } from 'jspdf';
import * as XLSX from 'xlsx';
import { saveAs } from 'file-saver';

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

    constructor() {
        this.doc = new jsPDF();
        this.pageHeight = this.doc.internal.pageSize.height;
    }

    addTitle(title: string, fontSize: number = 18): void {
        this.doc.setFontSize(fontSize);
        this.doc.setFont('helvetica', 'bold');
        this.doc.text(title, this.margin, this.currentY);
        this.currentY += fontSize * 0.5 + 10;
    }

    addSubtitle(subtitle: string): void {
        this.doc.setFontSize(12);
        this.doc.setFont('helvetica', 'normal');
        this.doc.text(subtitle, this.margin, this.currentY);
        this.currentY += 10;
    }

    addTable(data: any[], columns?: string[]): void {
        if (!data.length) return;

        const headers = columns || Object.keys(data[0]);
        const colWidth = (this.doc.internal.pageSize.width - 2 * this.margin) / headers.length;
        const rowHeight = 8;

        // Add headers
        this.doc.setFontSize(10);
        this.doc.setFont('helvetica', 'bold');

        headers.forEach((header, i) => {
            this.doc.text(header, this.margin + i * colWidth, this.currentY);
        });

        this.currentY += rowHeight;
        this.doc.setFont('helvetica', 'normal');

        // Add data rows
        data.forEach(row => {
            this.checkPageBreak(rowHeight);

            headers.forEach((header, i) => {
                const value = this.formatCellValue(row[header]);
                this.doc.text(value.toString(), this.margin + i * colWidth, this.currentY);
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
        this.doc.text('Chart Image', this.margin + 60, this.currentY + 40);
        this.currentY += 90;
    }

    addMetadata(metadata: Record<string, any>): void {
        this.addSubtitle('Generated Information:');
        this.doc.setFontSize(8);

        Object.entries(metadata).forEach(([key, value]) => {
            this.doc.text(`${key}: ${value}`, this.margin, this.currentY);
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

    private formatCellValue(value: any): string {
        if (value === null || value === undefined) return '';
        if (typeof value === 'number') {
            return value.toLocaleString('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            });
        }
        return String(value).substring(0, 20); // Truncate long values
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
            headers.join(','),
            ...data.map(row =>
                headers.map(header => {
                    const value = row[header];
                    // Escape values that contain commas or quotes
                    if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
                        return `"${value.replace(/"/g, '""')}"`;
                    }
                    return value;
                }).join(',')
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
    static exportChart(
        chartElement: HTMLElement,
        options: ChartExportOptions
    ): Promise<Blob> {
        return new Promise((resolve, reject) => {
            try {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');

                if (!ctx) {
                    reject(new Error('Cannot get canvas context'));
                    return;
                }

                const rect = chartElement.getBoundingClientRect();
                canvas.width = rect.width;
                canvas.height = rect.height;

                // Add background if specified
                if (options.background) {
                    ctx.fillStyle = options.background;
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                }

                // Convert SVG to canvas if needed
                if (chartElement.tagName === 'svg') {
                    const svgData = new XMLSerializer().serializeToString(chartElement);
                    const img = new Image();
                    const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
                    const url = URL.createObjectURL(svgBlob);

                    img.onload = () => {
                        ctx.drawImage(img, 0, 0);
                        URL.revokeObjectURL(url);
                        canvas.toBlob(blob => {
                            if (blob) resolve(blob);
                            else reject(new Error('Failed to create blob'));
                        }, `image/${options.format}`, options.quality);
                    };

                    img.onerror = () => reject(new Error('Failed to load SVG image'));
                    img.src = url;
                } else {
                    // For HTML canvas elements
                    canvas.toBlob(blob => {
                        if (blob) resolve(blob);
                        else reject(new Error('Failed to create blob'));
                    }, `image/${options.format}`, options.quality);
                }
            } catch (error) {
                reject(error);
            }
        });
    }
}

// Main Export Service
export class ExportService {
    static async exportPDF(data: ExportableData[], filename: string): Promise<void> {
        const pdf = new PDFExporter();

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

    static exportInstitutionalReviewPDF(portfolioData: {
        positions: any[];
        totalValue: number;
        currency: string;
        riskMetrics?: any;
    }, filename: string = 'Daisy_Portfolio_Risk_Review'): void {
        const doc = new jsPDF();
        const margin = 15;
        let y = 20;

        // Header
        doc.setFillColor(15, 23, 42); // slate-900
        doc.rect(0, 0, doc.internal.pageSize.width, 35, 'F');

        doc.setTextColor(255, 255, 255);
        doc.setFontSize(18);
        doc.setFont('helvetica', 'bold');
        doc.text('DAISY RISK ENGINE', margin, y);

        doc.setFontSize(10);
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(148, 163, 184); // slate-400
        doc.text('Institutional Quantitative Risk & Portfolio Review', margin, y + 7);

        doc.setFontSize(9);
        doc.text(`Generated: ${new Date().toLocaleString()}`, doc.internal.pageSize.width - margin - 55, y);

        y = 48;
        doc.setTextColor(30, 41, 59);

        // Portfolio Summary Box
        doc.setFontSize(13);
        doc.setFont('helvetica', 'bold');
        doc.text('Portfolio Executive Summary', margin, y);
        y += 8;

        doc.setFontSize(10);
        doc.setFont('helvetica', 'normal');
        doc.text(`Total Portfolio Value: ${portfolioData.currency === 'INR' ? 'INR ' : '$'}${portfolioData.totalValue.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`, margin, y);
        doc.text(`Active Holdings: ${portfolioData.positions.length} Equities`, margin + 100, y);
        y += 12;

        // Holdings Table
        doc.setFontSize(12);
        doc.setFont('helvetica', 'bold');
        doc.text('Holdings & Asset Allocation', margin, y);
        y += 6;

        const headers = ['Ticker', 'Quantity', 'Buy Price', 'Last Price', 'Market Value', 'Weight', 'Sector'];
        const colWidths = [28, 22, 25, 25, 32, 18, 30];
        
        doc.setFillColor(241, 245, 249);
        doc.rect(margin, y, 180, 7, 'F');
        doc.setFontSize(9);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(51, 65, 85);

        let currentX = margin + 2;
        headers.forEach((h, idx) => {
            doc.text(h, currentX, y + 5);
            currentX += colWidths[idx];
        });
        y += 9;

        doc.setFont('helvetica', 'normal');
        doc.setTextColor(30, 41, 59);

        portfolioData.positions.forEach(p => {
            currentX = margin + 2;
            const values = [
                String(p.ticker || ''),
                String(p.quantity || 0),
                String(p.buy_price ? p.buy_price.toFixed(1) : '0'),
                String(p.last_price ? p.last_price.toFixed(1) : '0'),
                String(p.market_value ? p.market_value.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '0'),
                `${((p.weight || 0) * 100).toFixed(1)}%`,
                String(p.sector || 'General')
            ];

            values.forEach((v, idx) => {
                doc.text(v, currentX, y + 4);
                currentX += colWidths[idx];
            });

            doc.setDrawColor(226, 232, 240);
            doc.line(margin, y + 6, margin + 180, y + 6);
            y += 7;
        });

        y += 10;

        // Risk Attributions
        doc.setFontSize(12);
        doc.setFont('helvetica', 'bold');
        doc.text('Quantitative Risk & Microstructure Summary', margin, y);
        y += 8;

        doc.setFontSize(9);
        doc.setFont('helvetica', 'normal');
        doc.text('• Euler Decomposition: Volatility and CVaR tail shares calculated against multi-asset empirical covariance.', margin, y);
        y += 5;
        doc.text('• Extreme Value Theory: 99% EVT-POT Generalized Pareto VaR accounts for fat-tailed crash probabilities.', margin, y);
        y += 5;
        doc.text('• Market Microstructure: ADV Liquidity Sizing ensures liquidation horizon within 10%-20% market volume.', margin, y);
        y += 15;

        // Disclaimer Footer
        doc.setFontSize(8);
        doc.setTextColor(148, 163, 184);
        doc.text('CONFIDENTIAL — Generated for internal investment management purposes only. Daisy Risk Engine.', margin, 280);

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
    return value.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
};

export const formatPercentage = (value: number, decimals: number = 2): string => {
    return `${formatNumber(value * 100, decimals)}%`;
};

export const formatCurrency = (value: number, currency: string = 'USD'): string => {
    return value.toLocaleString('en-US', {
        style: 'currency',
        currency
    });
};

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