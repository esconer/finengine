'use client';

import React, { useState, useRef } from 'react';
import { UploadCloud, FileText, CheckCircle2, AlertCircle, X, Loader2 } from 'lucide-react';
import apiClient from '@/lib/api';

interface ParsedRow {
    ticker: string;
    quantity: number;
    buy_price: number;
    custom_name?: string;
    sector?: string;
}

interface PortfolioDropzoneProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

export function PortfolioDropzone({ isOpen, onClose, onSuccess }: PortfolioDropzoneProps) {
    const [isDragging, setIsDragging] = useState(false);
    const [fileName, setFileName] = useState<string | null>(null);
    const [parsedRows, setParsedRows] = useState<ParsedRow[]>([]);
    const [parseError, setParseError] = useState<string | null>(null);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    if (!isOpen) return null;

    const normalizeTicker = (raw: string): string => {
        let t = raw.trim().toUpperCase();
        if (t.includes(':')) {
            t = t.split(':')[1];
        }
        if (!t.endsWith('.NS') && !t.endsWith('.BO') && !t.startsWith('^') && !t.endsWith('=X')) {
            t = `${t}.NS`;
        }
        return t;
    };

    const parseCSVText = (text: string) => {
        setParseError(null);
        const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
        if (lines.length < 2) {
            setParseError('File appears to be empty or missing header row.');
            return;
        }

        const headerLine = lines[0].toLowerCase();
        const headers = headerLine.split(',').map(h => h.trim().replace(/^["']|["']$/g, ''));

        // Identify column indices
        let tickerIdx = headers.findIndex(h => 
            h === 'ticker' || h === 'symbol' || h === 'instrument' || h === 'stock name' || h === 'scrip name'
        );
        let qtyIdx = headers.findIndex(h => 
            h === 'quantity' || h === 'qty' || h === 'qty.' || h === 'shares' || h === 'total qty' || h === 'units'
        );
        let priceIdx = headers.findIndex(h => 
            h === 'buy_price' || h === 'avg. cost' || h === 'avg cost' || h === 'average price' || h === 'avg price' || h === 'buy price' || h === 'price'
        );

        // Default positional fallback if no matching headers found
        if (tickerIdx === -1) tickerIdx = 0;
        if (qtyIdx === -1) qtyIdx = 1;
        if (priceIdx === -1) priceIdx = 2;

        const results: ParsedRow[] = [];
        for (let i = 1; i < lines.length; i++) {
            const cols = lines[i].split(',').map(c => c.trim().replace(/^["']|["']$/g, ''));
            if (cols.length <= Math.max(tickerIdx, qtyIdx, priceIdx)) continue;

            const rawTicker = cols[tickerIdx];
            const rawQty = parseFloat(cols[qtyIdx]?.replace(/,/g, ''));
            const rawPrice = parseFloat(cols[priceIdx]?.replace(/,/g, ''));

            if (rawTicker && !isNaN(rawQty) && rawQty > 0 && !isNaN(rawPrice) && rawPrice > 0) {
                results.push({
                    ticker: normalizeTicker(rawTicker),
                    quantity: rawQty,
                    buy_price: rawPrice,
                    custom_name: rawTicker.replace('.NS', '').replace('.BO', '')
                });
            }
        }

        if (results.length === 0) {
            setParseError('Could not parse any valid position rows from the CSV. Expected format: Ticker, Quantity, Buy Price');
        } else {
            setParsedRows(results);
        }
    };

    const handleFile = (file: File) => {
        setFileName(file.name);
        const reader = new FileReader();
        reader.onload = (e) => {
            const content = e.target?.result as string;
            if (content) {
                parseCSVText(content);
            }
        };
        reader.onerror = () => {
            setParseError('Failed to read file.');
        };
        reader.readAsText(file);
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            handleFile(e.dataTransfer.files[0]);
        }
    };

    const handleSubmit = async () => {
        if (parsedRows.length === 0) return;
        try {
            setIsSubmitting(true);
            setParseError(null);

            const payload = {
                positions: parsedRows.map(r => ({
                    ticker: r.ticker,
                    quantity: r.quantity,
                    buy_price: r.buy_price,
                    weight: 1.0 / parsedRows.length,
                    custom_name: r.custom_name,
                    region: 'IN'
                }))
            };

            await apiClient.post('/portfolio/bulk_add', payload);
            onSuccess();
            onClose();
        } catch (err: any) {
            const msg = err.response?.data?.detail || err.message || 'Failed to import positions';
            setParseError(typeof msg === 'string' ? msg : JSON.stringify(msg));
        } finally {
            setIsSubmitting(false);
        }
    };

    const totalEstimatedCost = parsedRows.reduce((acc, r) => acc + r.quantity * r.buy_price, 0);

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-200">
            <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/50">
                    <div className="flex items-center space-x-2">
                        <UploadCloud className="h-5 w-5 text-blue-400" />
                        <h2 className="text-lg font-semibold text-white">Import Portfolio (CSV / Excel)</h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Body */}
                <div className="p-6 space-y-4 overflow-y-auto flex-1">
                    {/* Supported brokers notice */}
                    <div className="p-3 bg-blue-950/40 border border-blue-800/60 rounded-lg text-xs text-blue-300">
                        <span className="font-semibold text-blue-200">Supported Formats:</span> Direct exports from <strong>Zerodha Kite</strong> (Holdings CSV), <strong>Groww</strong>, <strong>AngelOne</strong>, <strong>Upstox</strong>, or generic 3-column CSV (<code className="bg-blue-900/50 px-1 py-0.5 rounded">ticker,quantity,buy_price</code>).
                    </div>

                    {/* Dropzone Area */}
                    <div
                        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                        onDragLeave={() => setIsDragging(false)}
                        onDrop={handleDrop}
                        onClick={() => fileInputRef.current?.click()}
                        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition flex flex-col items-center justify-center space-y-3 ${
                            isDragging
                                ? 'border-blue-500 bg-blue-500/10'
                                : 'border-slate-700 hover:border-slate-500 bg-slate-800/40 hover:bg-slate-800/70'
                        }`}
                    >
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".csv,.txt"
                            className="hidden"
                            onChange={(e) => {
                                if (e.target.files && e.target.files.length > 0) {
                                    handleFile(e.target.files[0]);
                                }
                            }}
                        />
                        <div className="p-3 bg-blue-500/10 text-blue-400 rounded-full">
                            <UploadCloud className="h-8 w-8" />
                        </div>
                        <div>
                            <p className="text-sm font-medium text-white">
                                {fileName ? `Selected: ${fileName}` : 'Click to upload or drag and drop tradebook CSV'}
                            </p>
                            <p className="text-xs text-slate-400 mt-1">UTF-8 formatted CSV or text file</p>
                        </div>
                    </div>

                    {/* Error message */}
                    {parseError && (
                        <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-lg flex items-center space-x-2 text-xs text-red-300">
                            <AlertCircle className="h-4 w-4 text-red-400 shrink-0" />
                            <span>{parseError}</span>
                        </div>
                    )}

                    {/* Preview Table */}
                    {parsedRows.length > 0 && (
                        <div className="space-y-2">
                            <div className="flex items-center justify-between text-xs text-slate-400">
                                <span className="flex items-center space-x-1 text-emerald-400 font-medium">
                                    <CheckCircle2 className="h-4 w-4" />
                                    <span>Detected {parsedRows.length} valid positions</span>
                                </span>
                                <span>Est. Cost: <strong className="text-white">₹{totalEstimatedCost.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</strong></span>
                            </div>
                            <div className="max-h-48 overflow-y-auto border border-slate-800 rounded-lg bg-slate-950/60">
                                <table className="w-full text-left text-xs">
                                    <thead className="bg-slate-800/80 text-slate-300 sticky top-0">
                                        <tr>
                                            <th className="py-2 px-3">Ticker</th>
                                            <th className="py-2 px-3 text-right">Quantity</th>
                                            <th className="py-2 px-3 text-right">Buy Price</th>
                                            <th className="py-2 px-3 text-right">Total Invested</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-800 text-slate-200">
                                        {parsedRows.map((r, i) => (
                                            <tr key={i} className="hover:bg-slate-800/30">
                                                <td className="py-2 px-3 font-mono font-medium text-blue-300">{r.ticker}</td>
                                                <td className="py-2 px-3 text-right">{r.quantity}</td>
                                                <td className="py-2 px-3 text-right">₹{r.buy_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                                                <td className="py-2 px-3 text-right text-slate-300">₹{(r.quantity * r.buy_price).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="flex items-center justify-end space-x-3 px-6 py-4 border-t border-slate-800 bg-slate-900/50">
                    <button
                        onClick={onClose}
                        disabled={isSubmitting}
                        className="px-4 py-2 text-xs font-medium text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg transition disabled:opacity-50"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSubmit}
                        disabled={parsedRows.length === 0 || isSubmitting}
                        className="flex items-center space-x-2 px-4 py-2 text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition disabled:opacity-50 shadow-lg shadow-blue-500/20"
                    >
                        {isSubmitting ? (
                            <>
                                <Loader2 className="h-4 w-4 animate-spin" />
                                <span>Importing...</span>
                            </>
                        ) : (
                            <>
                                <UploadCloud className="h-4 w-4" />
                                <span>Import {parsedRows.length} Positions</span>
                            </>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
}
