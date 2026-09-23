/**
 * Export panel component with all export options
 */

import React, { useState, useCallback } from 'react';
import { Download, FileText, FileSpreadsheet, Table, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { ExportService, ExportableData } from '@/lib/export';
import { useExportProgress, useNotifications } from '@/hooks/useRealTime';

interface ExportPanelProps {
    data: ExportableData[];
    chartElement?: HTMLElement;
    filename?: string;
    className?: string;
}

/**
 * Subscribing child: reads the store job so progress ticks re-render only this
 * view, not the button grid (05-B11, 05-O5).
 */
const ExportProgressView: React.FC<{ exportId: string }> = ({ exportId }) => {
    const { exports } = useExportProgress();
    const job = exports[exportId];
    if (!job) return null;

    const isDone = job.status === 'completed';
    const isError = job.status === 'error';
    const pct = Math.round(job.progress);

    return (
        <div className="mb-6">
            <div className="flex justify-between text-sm text-gray-600 mb-2">
                <span>
                    {isError ? 'Export Failed' : isDone ? 'Export Complete' : 'Export Progress'}
                </span>
                <span>{pct}%</span>
            </div>
            <div
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct}
                aria-label="Export progress"
                className="w-full bg-gray-200 rounded-full h-2"
            >
                <div
                    className={`${isError ? 'bg-red-600' : 'bg-blue-600'} h-2 rounded-full transition-all duration-300`}
                    style={{ width: `${job.progress}%` }}
                />
            </div>
            {isError && (
                <p className="mt-2 text-sm text-red-600 flex items-center">
                    <AlertCircle className="w-4 h-4 mr-1 shrink-0" />
                    {job.error || 'Export failed'}
                </p>
            )}
            {isDone && (
                <p className="mt-2 text-sm text-green-600 flex items-center">
                    <CheckCircle2 className="w-4 h-4 mr-1 shrink-0" />
                    {job.filename} is ready
                </p>
            )}
        </div>
    );
};

const exportOptions = [
    {
        id: 'pdf' as const,
        label: 'PDF Report',
        description: 'Comprehensive PDF with charts and data',
        icon: FileText,
        color: 'text-red-600 bg-red-50 hover:bg-red-100'
    },
    {
        id: 'excel' as const,
        label: 'Excel File',
        description: 'Detailed spreadsheet with multiple sheets',
        icon: FileSpreadsheet,
        color: 'text-green-600 bg-green-50 hover:bg-green-100'
    },
    {
        id: 'csv' as const,
        label: 'CSV Data',
        description: 'Raw data for external analysis',
        icon: Table,
        color: 'text-blue-600 bg-blue-50 hover:bg-blue-100'
    },
    {
        id: 'all' as const,
        label: 'All Formats',
        description: 'Export in all available formats',
        icon: Download,
        color: 'text-purple-600 bg-purple-50 hover:bg-purple-100'
    }
];

const ExportOptionsGrid = React.memo<{
    isExporting: boolean;
    onExport: (format: 'pdf' | 'excel' | 'csv' | 'all') => void;
}>(function ExportOptionsGrid({ isExporting, onExport }) {
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {exportOptions.map((option) => {
                const Icon = option.icon;
                return (
                    <button
                        key={option.id}
                        onClick={() => onExport(option.id)}
                        disabled={isExporting}
                        className={`p-4 rounded-lg border-2 border-transparent transition-all duration-200 text-left ${option.color} disabled:opacity-50 disabled:cursor-not-allowed`}
                    >
                        <div className="flex items-start space-x-3">
                            <Icon className="w-6 h-6 mt-1 flex-shrink-0" />
                            <div className="flex-1">
                                <h4 className="font-medium">{option.label}</h4>
                                <p className="text-sm opacity-75 mt-1">{option.description}</p>
                            </div>
                        </div>
                    </button>
                );
            })}
        </div>
    );
});

const ExportPanelImpl: React.FC<ExportPanelProps> = ({
    data,
    chartElement,
    filename = 'dashboard_export',
    className = ''
}) => {
    const { startExport, updateExportProgress, completeExport } = useExportProgress();
    const { addNotification } = useNotifications();
    const [isExporting, setIsExporting] = useState(false);
    const [activeExportId, setActiveExportId] = useState<string | null>(null);

    const handleExport = useCallback(async (format: 'pdf' | 'excel' | 'csv' | 'all') => {
        if (isExporting) return;

        setIsExporting(true);
        const exportId = startExport(`${filename}_${format}`, format);
        setActiveExportId(exportId);

        try {
            if (format === 'pdf') {
                updateExportProgress(exportId, 20);
                await ExportService.exportPDF(data, `${filename}_report`);
                updateExportProgress(exportId, 100);
            } else if (format === 'excel') {
                updateExportProgress(exportId, 30);
                await ExportService.exportExcel(data, `${filename}_data`);
                updateExportProgress(exportId, 100);
            } else if (format === 'csv') {
                updateExportProgress(exportId, 50);
                const csvData = data[0]?.data || [];
                await ExportService.exportCSV(csvData, `${filename}_summary`);
                updateExportProgress(exportId, 100);
            } else if (format === 'all') {
                const formats: Array<'pdf' | 'excel' | 'csv'> = ['pdf', 'excel', 'csv'];
                let completed = 0;

                for (const fmt of formats) {
                    const id = startExport(`${filename}_${fmt}`, fmt);

                    if (fmt === 'pdf') {
                        updateExportProgress(id, 20);
                        await ExportService.exportPDF(data, `${filename}_report`);
                    } else if (fmt === 'excel') {
                        updateExportProgress(id, 30);
                        await ExportService.exportExcel(data, `${filename}_data`);
                    } else if (fmt === 'csv') {
                        updateExportProgress(id, 50);
                        const csvData = data[0]?.data || [];
                        await ExportService.exportCSV(csvData, `${filename}_summary`);
                    }

                    updateExportProgress(id, 100);
                    completed++;
                    updateExportProgress(exportId, (completed / formats.length) * 100);
                }
            }

            // Add chart export if available
            if (chartElement && (format === 'pdf' || format === 'all')) {
                try {
                    await ExportService.exportChart(chartElement, {
                        filename: `${filename}_chart`,
                        format: 'png',
                        quality: 0.9
                    });
                } catch (error) {
                    console.warn('Chart export failed:', error);
                }
            }

            completeExport(exportId);
            addNotification('success', 'Export Complete', `${filename}_${format} is ready`);
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Unknown error';
            completeExport(exportId, message);
            addNotification('error', 'Export Failed', message);
        } finally {
            setIsExporting(false);
        }
    }, [isExporting, filename, data, chartElement, startExport, updateExportProgress, completeExport, addNotification]);

    return (
        <div className={`bg-white rounded-lg border p-6 ${className}`}>
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h3 className="text-lg font-semibold text-gray-900">Export Data</h3>
                    <p className="text-sm text-gray-600">
                        Export dashboard data in multiple formats for reporting and analysis
                    </p>
                </div>
                {isExporting && (
                    <div className="flex items-center space-x-2 text-blue-600">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span className="text-sm">Exporting...</span>
                    </div>
                )}
            </div>

            {activeExportId && <ExportProgressView exportId={activeExportId} />}

            <ExportOptionsGrid isExporting={isExporting} onExport={handleExport} />
        </div>
    );
};

export const ExportPanel = React.memo(ExportPanelImpl);

// Quick export buttons for individual datasets
export const QuickExportButtons: React.FC<{
    data: any[];
    filename: string;
    className?: string;
}> = ({ data, filename, className = '' }) => {
    const { addNotification } = useNotifications();
    const [isBusy, setIsBusy] = useState(false);

    const handleQuickExport = async (format: 'csv' | 'excel') => {
        if (isBusy) return;
        setIsBusy(true);
        try {
            if (format === 'csv') {
                await ExportService.exportCSV(data, filename);
            } else {
                const exportData: ExportableData = {
                    title: filename,
                    data,
                    metadata: {
                        generatedAt: new Date().toISOString(),
                    }
                };
                await ExportService.exportExcel([exportData], filename);
            }
            addNotification('success', 'Export Complete', `${filename}.${format === 'csv' ? 'csv' : 'xlsx'} is ready`);
        } catch (error) {
            addNotification(
                'error',
                'Export Failed',
                error instanceof Error ? error.message : 'Unknown error'
            );
        } finally {
            setIsBusy(false);
        }
    };

    if (!data.length) return null;

    return (
        <div className={`flex space-x-2 ${className}`}>
            <button
                onClick={() => handleQuickExport('csv')}
                disabled={isBusy}
                className="inline-flex items-center px-3 py-1 text-xs font-medium text-blue-700 bg-blue-50 rounded-md hover:bg-blue-100 transition-colors disabled:opacity-50"
            >
                {isBusy ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Table className="w-3 h-3 mr-1" />}
                CSV
            </button>
            <button
                onClick={() => handleQuickExport('excel')}
                disabled={isBusy}
                className="inline-flex items-center px-3 py-1 text-xs font-medium text-green-700 bg-green-50 rounded-md hover:bg-green-100 transition-colors disabled:opacity-50"
            >
                {isBusy ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <FileSpreadsheet className="w-3 h-3 mr-1" />}
                Excel
            </button>
        </div>
    );
};
