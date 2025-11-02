/**
 * Export panel component with all export options
 */

import React, { useState } from 'react';
import { Download, FileText, FileSpreadsheet, Table, Image, Loader2 } from 'lucide-react';
import { ExportService, ExportableData } from '@/lib/export';
import { useExportProgress } from '@/hooks/useRealTime';
import { LoadingState } from './LoadingState';

interface ExportPanelProps {
    data: ExportableData[];
    chartElement?: HTMLElement;
    filename?: string;
    className?: string;
}

export const ExportPanel: React.FC<ExportPanelProps> = ({
    data,
    chartElement,
    filename = 'dashboard_export',
    className = ''
}) => {
    const { startExport, updateExportProgress, completeExport, getActiveExports } = useExportProgress();
    const [isExporting, setIsExporting] = useState(false);
    const [selectedFormat, setSelectedFormat] = useState<'pdf' | 'excel' | 'csv' | 'all'>('pdf');
    const [exportProgress, setExportProgress] = useState<number>(0);

    const activeExports = getActiveExports();

    const handleExport = async (format: 'pdf' | 'excel' | 'csv' | 'all') => {
        if (isExporting) return;

        setIsExporting(true);
        setExportProgress(0);

        const exportId = startExport(`${filename}_${format}`, format);

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
                // Export all formats
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

                    // Update main progress
                    setExportProgress((completed / formats.length) * 100);
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

        } catch (error) {
            console.error('Export failed:', error);
            completeExport(exportId, error instanceof Error ? error.message : 'Unknown error');
        } finally {
            setIsExporting(false);
            setExportProgress(0);
        }
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

            {isExporting && (
                <div className="mb-6">
                    <div className="flex justify-between text-sm text-gray-600 mb-2">
                        <span>Export Progress</span>
                        <span>{Math.round(exportProgress)}%</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2">
                        <div
                            className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                            style={{ width: `${exportProgress}%` }}
                        />
                    </div>
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {exportOptions.map((option) => {
                    const Icon = option.icon;
                    return (
                        <button
                            key={option.id}
                            onClick={() => handleExport(option.id)}
                            disabled={isExporting}
                            className={`p-4 rounded-lg border-2 border-transparent transition-all duration-200 text-left ${option.color} disabled:opacity-50 disabled:cursor-not-allowed ${selectedFormat === option.id ? 'border-current' : ''}`}
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

            {/* Export History */}
            {activeExports.length > 0 && (
                <div className="mt-6">
                    <h4 className="text-sm font-medium text-gray-900 mb-3">Active Exports</h4>
                    <div className="space-y-2">
                        {activeExports.map((exportJob: any) => (
                            <div key={exportJob.id} className="bg-gray-50 rounded-lg p-3">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm font-medium text-gray-900">
                                        {exportJob.filename}
                                    </span>
                                    <span className="text-xs text-gray-500">
                                        {exportJob.progress}%
                                    </span>
                                </div>
                                <div className="w-full bg-gray-200 rounded-full h-1">
                                    <div
                                        className="bg-blue-600 h-1 rounded-full transition-all duration-300"
                                        style={{ width: `${exportJob.progress}%` }}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Export Settings */}
            <div className="mt-6 pt-6 border-t border-gray-200">
                <h4 className="text-sm font-medium text-gray-900 mb-3">Export Settings</h4>
                <div className="space-y-3">
                    <label className="flex items-center">
                        <input
                            type="checkbox"
                            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            defaultChecked
                        />
                        <span className="ml-2 text-sm text-gray-700">
                            Include metadata and generation timestamp
                        </span>
                    </label>
                    <label className="flex items-center">
                        <input
                            type="checkbox"
                            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            defaultChecked
                        />
                        <span className="ml-2 text-sm text-gray-700">
                            Compress large datasets
                        </span>
                    </label>
                    {chartElement && (
                        <label className="flex items-center">
                            <input
                                type="checkbox"
                                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                defaultChecked
                            />
                            <span className="ml-2 text-sm text-gray-700">
                                Include charts and visualizations
                            </span>
                        </label>
                    )}
                </div>
            </div>
        </div>
    );
};

// Quick export buttons for individual datasets
export const QuickExportButtons: React.FC<{
    data: any[];
    filename: string;
    className?: string;
}> = ({ data, filename, className = '' }) => {
    const handleQuickExport = async (format: 'csv' | 'excel') => {
        try {
            if (format === 'csv') {
                await ExportService.exportCSV(data, filename);
            } else if (format === 'excel') {
                const exportData: ExportableData = {
                    title: filename,
                    data,
                    metadata: {
                        generatedAt: new Date().toISOString(),
                    }
                };
                await ExportService.exportExcel([exportData], filename);
            }
        } catch (error) {
            console.error('Quick export failed:', error);
        }
    };

    if (!data.length) return null;

    return (
        <div className={`flex space-x-2 ${className}`}>
            <button
                onClick={() => handleQuickExport('csv')}
                className="inline-flex items-center px-3 py-1 text-xs font-medium text-blue-700 bg-blue-50 rounded-md hover:bg-blue-100 transition-colors"
            >
                <Table className="w-3 h-3 mr-1" />
                CSV
            </button>
            <button
                onClick={() => handleQuickExport('excel')}
                className="inline-flex items-center px-3 py-1 text-xs font-medium text-green-700 bg-green-50 rounded-md hover:bg-green-100 transition-colors"
            >
                <FileSpreadsheet className="w-3 h-3 mr-1" />
                Excel
            </button>
        </div>
    );
};