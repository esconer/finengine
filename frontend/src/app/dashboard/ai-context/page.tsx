'use client';

import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clipboard,
  Download,
  FileJson,
  FileText,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { aiContextApi } from '@/lib/api';
import type { AIContextDetail, AIContextResponse, AIContextStatus } from '@/types';

const STATUS_STYLES: Record<AIContextStatus, string> = {
  available: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800',
  partial: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800',
  unavailable: 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800',
  not_requested: 'bg-gray-50 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700',
};

function isAIContextResponse(value: AIContextResponse | string): value is AIContextResponse {
  return typeof value !== 'string';
}

function statusLabel(status: AIContextStatus) {
  return status.replace('_', ' ');
}

export default function AIContextPage() {
  const [detail, setDetail] = useState<AIContextDetail>('summary');
  const [format, setFormat] = useState<'json' | 'markdown'>('json');
  const [result, setResult] = useState<AIContextResponse | string | null>(null);
  const [resultFormat, setResultFormat] = useState<'json' | 'markdown'>('json');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const response = result && isAIContextResponse(result) ? result : null;
  const content = useMemo(() => {
    if (!result) return '';
    return typeof result === 'string' ? result : JSON.stringify(result, null, 2);
  }, [result]);

  const statusCounts = useMemo(() => {
    const counts: Record<AIContextStatus, number> = {
      available: 0,
      partial: 0,
      unavailable: 0,
      not_requested: 0,
    };
    Object.values(response?.sections || {}).forEach((section) => {
      counts[section.status] = (counts[section.status] || 0) + 1;
    });
    return counts;
  }, [response]);

  const generate = async () => {
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const next = await aiContextApi.getContext({ format, detail });
      setResult(next);
      setResultFormat(format);
      setNotice(`AI context generated at ${new Date().toLocaleTimeString('en-IN')}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not generate AI context');
    } finally {
      setLoading(false);
    }
  };

  const download = () => {
    if (!content) return;
    const mime = resultFormat === 'markdown' ? 'text/markdown;charset=utf-8' : 'application/json;charset=utf-8';
    const extension = resultFormat === 'markdown' ? 'md' : 'json';
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `finengine-portfolio-ai-context.${extension}`;
    link.click();
    URL.revokeObjectURL(url);
    setNotice(`Downloaded ${extension.toUpperCase()} context.`);
  };

  const copy = async () => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setNotice('AI context copied to the clipboard.');
    } catch {
      setError('Clipboard access is unavailable in this browser.');
    }
  };

  return (
    <div className="space-y-8 pb-16 max-w-6xl">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-blue-600 dark:text-blue-400">
            <Bot className="h-4 w-4" />
            AI-ready portfolio context
          </div>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-gray-900 dark:text-white">
            Export Portfolio Analytics
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-400">
            Generate one structured snapshot of every portfolio analytics page for an AI client.
            Equity Research and Screener Studio are intentionally excluded.
          </p>
        </div>
        <button
          type="button"
          onClick={generate}
          disabled={loading}
          data-testid="generate-ai-context"
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {loading ? 'Generating…' : 'Generate context'}
        </button>
      </div>

      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div className="grid gap-5 md:grid-cols-2">
          <fieldset>
            <legend className="text-sm font-semibold text-gray-900 dark:text-white">Detail level</legend>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Summary keeps the export token-dense. Full retains raw chart and history series.
            </p>
            <div className="mt-3 flex gap-2">
              {(['summary', 'full'] as const).map((level) => (
                <button
                  key={level}
                  type="button"
                  onClick={() => setDetail(level)}
                  className={`rounded-md border px-3 py-2 text-sm font-medium transition ${
                    detail === level
                      ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
                      : 'border-gray-200 text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-700'
                  }`}
                >
                  {level === 'summary' ? 'Summary' : 'Full detail'}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend className="text-sm font-semibold text-gray-900 dark:text-white">Output format</legend>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              JSON is canonical. Markdown is rendered from the same snapshot.
            </p>
            <div className="mt-3 flex gap-2">
              {(['json', 'markdown'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setFormat(value)}
                  className={`inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition ${
                    format === value
                      ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
                      : 'border-gray-200 text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-700'
                  }`}
                >
                  {value === 'json' ? <FileJson className="h-4 w-4" /> : <FileText className="h-4 w-4" />}
                  {value === 'json' ? 'JSON' : 'Markdown'}
                </button>
              ))}
            </div>
          </fieldset>
        </div>
      </section>

      {error && (
        <div data-testid="ai-context-error" className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {notice && !error && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
          <CheckCircle2 className="h-4 w-4" />
          {notice}
        </div>
      )}

      {result && !response && (
        <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Markdown preview</h2>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={copy}
                className="inline-flex items-center gap-2 rounded-md border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                <Clipboard className="h-4 w-4" />
                Copy
              </button>
              <button
                type="button"
                onClick={download}
                className="inline-flex items-center gap-2 rounded-md bg-gray-900 px-3 py-2 text-sm font-semibold text-white hover:bg-black dark:bg-white dark:text-gray-900 dark:hover:bg-gray-200"
              >
                <Download className="h-4 w-4" />
                Download
              </button>
            </div>
          </div>
          <pre className="mt-4 max-h-[42rem] overflow-auto rounded-lg bg-gray-950 p-4 text-xs leading-5 text-gray-100">
            {content}
          </pre>
        </section>
      )}

      {response && (
        <>
          <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Export status</h2>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  {response.generated_at} · base currency {response.base_currency} · schema {response.schema_version}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={copy}
                  className="inline-flex items-center gap-2 rounded-md border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-700"
                >
                  <Clipboard className="h-4 w-4" />
                  Copy
                </button>
                <button
                  type="button"
                  onClick={download}
                  className="inline-flex items-center gap-2 rounded-md bg-gray-900 px-3 py-2 text-sm font-semibold text-white hover:bg-black dark:bg-white dark:text-gray-900 dark:hover:bg-gray-200"
                >
                  <Download className="h-4 w-4" />
                  Download
                </button>
              </div>
            </div>

            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {(Object.keys(statusCounts) as AIContextStatus[]).map((status) => (
                <div key={status} className="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
                  <div className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">{statusLabel(status)}</div>
                  <div className="mt-1 text-xl font-semibold text-gray-900 dark:text-white">{statusCounts[status]}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Included pages</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Object.values(response.sections).map((section) => (
                <div key={section.key} className="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-medium text-gray-900 dark:text-white">{section.title}</div>
                      <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">{section.route}</div>
                    </div>
                    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLES[section.status]}`}>
                      {statusLabel(section.status)}
                    </span>
                  </div>
                  {section.error && <p className="mt-2 text-xs text-rose-600 dark:text-rose-300">{section.error}</p>}
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">AI payload preview</h2>
              <span className="text-xs text-gray-500 dark:text-gray-400">{content.length.toLocaleString()} characters</span>
            </div>
            <pre className="mt-4 max-h-[32rem] overflow-auto rounded-lg bg-gray-950 p-4 text-xs leading-5 text-gray-100">
              {content}
            </pre>
          </section>
        </>
      )}

      {!result && !loading && (
        <section className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-10 text-center dark:border-gray-700 dark:bg-gray-800/50">
          <FileText className="mx-auto h-8 w-8 text-gray-400" />
          <h2 className="mt-3 font-semibold text-gray-900 dark:text-white">No context generated yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-gray-500 dark:text-gray-400">
            Choose a detail level and generate a snapshot. The export will include the portfolio,
            risk, performance, optimization, simulation, and India market-context pages.
          </p>
        </section>
      )}
    </div>
  );
}
