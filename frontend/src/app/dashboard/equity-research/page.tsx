'use client';

import React, { useState, useEffect } from 'react';
import {
  Search,
  Download,
  Sparkles,
  ShieldAlert,
  TrendingUp,
  Volume2,
  FileText,
  Building,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  ChevronRight,
  RefreshCw,
  Copy,
  Check,
  BarChart2,
  PieChart as PieChartIcon,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  Play,
  Pause,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';

import { equityResearchApi, companyDataApi } from '@/lib/api';
import {
  EquityResearchProfile,
  ShareholdingDataResponse,
  ConcallItem,
  CustomRatiosDataResponse,
} from '@/types';
import { formatCurrency, formatPercent, formatIndianRupees } from '@/lib/utils';

export default function EquityResearchPage() {
  const [tickerInput, setTickerInput] = useState('RELIANCE');
  const [activeTicker, setActiveTicker] = useState('RELIANCE');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [profile, setProfile] = useState<EquityResearchProfile | null>(null);
  const [shareholding, setShareholding] = useState<ShareholdingDataResponse | null>(null);
  const [concalls, setConcalls] = useState<ConcallItem[]>([]);
  const [customRatios, setCustomRatios] = useState<CustomRatiosDataResponse | null>(null);
  const [financials, setFinancials] = useState<any>(null);

  const [activeTab, setActiveTab] = useState<
    'overview' | 'shareholding' | 'concalls' | 'financials' | 'ai-dossier'
  >('overview');
  const [shareholdingFreq, setShareholdingFreq] = useState<'quarterly' | 'yearly'>('quarterly');
  const [financialStmt, setFinancialStmt] = useState<'income' | 'balance' | 'cashflow'>('income');
  const [financialFreq, setFinancialFreq] = useState<'annual' | 'quarterly'>('annual');

  const [exportingExcel, setExportingExcel] = useState(false);
  const [aiModalOpen, setAiModalOpen] = useState(false);
  const [aiModalTitle, setAiModalTitle] = useState('');
  const [aiPromptContent, setAiPromptContent] = useState('');
  const [copiedPrompt, setCopiedPrompt] = useState(false);

  // Audio player state
  const [activeAudioUrl, setActiveAudioUrl] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  const fetchAllData = async (ticker: string) => {
    setLoading(true);
    setError(null);
    try {
      const [profData, shData, concallData, ratioData] = await Promise.allSettled([
        equityResearchApi.getFullProfile(ticker),
        equityResearchApi.getShareholding(ticker),
        equityResearchApi.getConcalls(ticker),
        equityResearchApi.getCustomRatios(ticker),
      ]);

      if (profData.status === 'fulfilled') {
        setProfile(profData.value);
      } else {
        throw new Error(profData.reason?.response?.data?.detail || 'Failed to fetch company profile');
      }

      if (shData.status === 'fulfilled') {
        setShareholding(shData.value);
      }
      if (concallData.status === 'fulfilled') {
        setConcalls(concallData.value.concalls || []);
      }
      if (ratioData.status === 'fulfilled') {
        setCustomRatios(ratioData.value);
      }

      // Also pull 10-year statements
      try {
        const stmtData = await companyDataApi.getFinancialStatements(ticker, financialStmt, financialFreq);
        setFinancials(stmtData);
      } catch (e) {
        console.warn('Statements load warning:', e);
      }
    } catch (err: any) {
      console.error('Error fetching equity research:', err);
      setError(err.message || 'Error loading equity research data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAllData(activeTicker);
  }, [activeTicker]);

  useEffect(() => {
    // Refetch financial statement when statement or freq changes
    const fetchStmt = async () => {
      try {
        const stmtData = await companyDataApi.getFinancialStatements(activeTicker, financialStmt, financialFreq);
        setFinancials(stmtData);
      } catch (e) {
        console.warn('Statement switch failed:', e);
      }
    };
    if (activeTab === 'financials') {
      fetchStmt();
    }
  }, [financialStmt, financialFreq, activeTab, activeTicker]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (tickerInput.trim()) {
      setActiveTicker(tickerInput.trim().toUpperCase());
    }
  };

  const handleExportExcel = async () => {
    if (!profile) return;
    setExportingExcel(true);
    try {
      const blob = await equityResearchApi.downloadExcelModel(profile.ticker);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${profile.symbol}_financial_model.xlsx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      console.error('Failed to export Excel:', err);
      alert('Failed to export Excel model. Please try again.');
    } finally {
      setExportingExcel(false);
    }
  };

  const handleOpenAiMemo = async () => {
    try {
      const res = await equityResearchApi.getAiMemoPrompt(activeTicker);
      setAiModalTitle(`AI Investment Memo Prompt: ${activeTicker}`);
      setAiPromptContent(res.prompt);
      setAiModalOpen(true);
      setCopiedPrompt(false);
    } catch (err) {
      console.error(err);
    }
  };

  const handleOpenAiForensic = async () => {
    try {
      const res = await equityResearchApi.getAiForensicPrompt(activeTicker);
      setAiModalTitle(`AI Forensic Audit Prompt: ${activeTicker}`);
      setAiPromptContent(res.prompt);
      setAiModalOpen(true);
      setCopiedPrompt(false);
    } catch (err) {
      console.error(err);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedPrompt(true);
    setTimeout(() => setCopiedPrompt(false), 2500);
  };

  const formatCr = (num?: number | null) => {
    if (num === null || num === undefined) return 'N/A';
    if (num >= 100000) {
      return `₹${(num / 100000).toFixed(2)} L Cr`;
    }
    return `₹${Number(num).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 lg:p-6 space-y-6">
      {/* Top Search & Actions Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900/80 backdrop-blur border border-slate-800 p-4 rounded-xl shadow-lg">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-blue-600/20 text-blue-400 rounded-lg border border-blue-500/30">
            <Building className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
              Equity Research Terminal
              <span className="px-2 py-0.5 text-xs font-medium bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded">
                bfinance 10-13Y Ind AS
              </span>
            </h1>
            <p className="text-xs text-slate-400">
              Institutional fundamentals, 12Q/11Y shareholding, concall MP3s & 8-tab Excel modeling
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <form onSubmit={handleSearch} className="relative flex items-center">
            <input
              type="text"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value)}
              placeholder="Search ticker (e.g. RELIANCE, TCS, INFY)"
              className="bg-slate-950 border border-slate-700 text-slate-100 pl-9 pr-20 py-2 rounded-lg text-sm focus:outline-none focus:border-blue-500 w-64 md:w-72"
            />
            <Search className="w-4 h-4 text-slate-400 absolute left-3" />
            <button
              type="submit"
              className="absolute right-1.5 px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-semibold transition-colors"
            >
              Search
            </button>
          </form>

          <button
            onClick={handleExportExcel}
            disabled={exportingExcel || !profile}
            className="flex items-center gap-2 px-3.5 py-2 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-500/40 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            {exportingExcel ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            <span>8-Tab Excel Model</span>
          </button>

          <button
            onClick={handleOpenAiMemo}
            className="flex items-center gap-1.5 px-3 py-2 bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/40 rounded-lg text-sm font-medium transition-colors"
          >
            <Sparkles className="w-4 h-4" />
            <span>AI Memo</span>
          </button>

          <button
            onClick={handleOpenAiForensic}
            className="flex items-center gap-1.5 px-3 py-2 bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 border border-amber-500/40 rounded-lg text-sm font-medium transition-colors"
          >
            <ShieldAlert className="w-4 h-4" />
            <span>Forensic Audit</span>
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex flex-col items-center justify-center py-20 space-y-4">
          <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
          <p className="text-sm text-slate-400">Loading comprehensive equity research for {activeTicker}...</p>
        </div>
      )}

      {error && (
        <div className="bg-red-950/40 border border-red-800 text-red-200 p-4 rounded-xl flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
          <div>
            <h4 className="font-semibold">Error Loading Equity Research</h4>
            <p className="text-sm text-red-300">{error}</p>
          </div>
        </div>
      )}

      {!loading && profile && (
        <>
          {/* Header Banner: 4-Level Taxonomy, Price & Ratios Grid */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg space-y-4">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 border-b border-slate-800">
              <div className="space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-2xl font-bold text-white tracking-tight">{profile.name}</h2>
                  <span className="px-2 py-0.5 bg-slate-800 border border-slate-700 text-slate-300 rounded font-mono text-xs font-semibold">
                    {profile.symbol}
                  </span>
                  {profile.bse_code && (
                    <span className="px-2 py-0.5 bg-slate-800/80 text-slate-400 rounded text-xs">
                      BSE: {profile.bse_code}
                    </span>
                  )}
                  {profile.website && (
                    <a
                      href={profile.website}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-blue-400 hover:underline flex items-center gap-1"
                    >
                      Website <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>

                {/* 4-Level Sector Taxonomy */}
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
                  {profile.sector && (
                    <span className="text-indigo-300 font-medium">{profile.sector}</span>
                  )}
                  {profile.industry_group && (
                    <>
                      <ChevronRight className="w-3 h-3 text-slate-600" />
                      <span>{profile.industry_group}</span>
                    </>
                  )}
                  {profile.industry && (
                    <>
                      <ChevronRight className="w-3 h-3 text-slate-600" />
                      <span className="text-slate-300 font-medium">{profile.industry}</span>
                    </>
                  )}
                  {profile.sub_industry && (
                    <>
                      <ChevronRight className="w-3 h-3 text-slate-600" />
                      <span className="text-slate-400">{profile.sub_industry}</span>
                    </>
                  )}
                </div>

                {/* Indices */}
                {profile.indices && profile.indices.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1">
                    {profile.indices.map((idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 bg-blue-950/60 text-blue-300 border border-blue-800/60 rounded-full text-[10px] font-medium"
                      >
                        {idx}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Live Price & Range */}
              <div className="flex items-baseline lg:items-end flex-col">
                <div className="text-3xl font-extrabold text-emerald-400 tracking-tight font-mono">
                  ₹{profile.current_price?.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div className="text-xs text-slate-400 flex items-center gap-2 mt-1">
                  <span>52W Low: ₹{profile.low_52w?.toLocaleString('en-IN')}</span>
                  <span>•</span>
                  <span>52W High: ₹{profile.high_52w?.toLocaleString('en-IN')}</span>
                </div>
              </div>
            </div>

            {/* Quick Metrics Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
              <div className="bg-slate-950/80 p-3 rounded-lg border border-slate-800/80">
                <div className="text-[11px] text-slate-400 font-medium">Market Cap</div>
                <div className="text-sm font-bold text-white mt-1 font-mono">
                  {formatCr(profile.market_cap_cr)}
                </div>
              </div>

              <div className="bg-slate-950/80 p-3 rounded-lg border border-slate-800/80">
                <div className="text-[11px] text-slate-400 font-medium">Stock P/E</div>
                <div className="text-sm font-bold text-white mt-1 font-mono">
                  {profile.stock_pe ? `${profile.stock_pe.toFixed(1)}x` : 'N/A'}
                </div>
              </div>

              <div className="bg-slate-950/80 p-3 rounded-lg border border-slate-800/80">
                <div className="text-[11px] text-slate-400 font-medium">ROCE</div>
                <div className="text-sm font-bold text-emerald-400 mt-1 font-mono">
                  {profile.roce ? `${profile.roce.toFixed(1)}%` : 'N/A'}
                </div>
              </div>

              <div className="bg-slate-950/80 p-3 rounded-lg border border-slate-800/80">
                <div className="text-[11px] text-slate-400 font-medium">ROE</div>
                <div className="text-sm font-bold text-emerald-400 mt-1 font-mono">
                  {profile.roe ? `${profile.roe.toFixed(1)}%` : 'N/A'}
                </div>
              </div>

              <div className="bg-slate-950/80 p-3 rounded-lg border border-slate-800/80">
                <div className="text-[11px] text-slate-400 font-medium">Book Value</div>
                <div className="text-sm font-bold text-white mt-1 font-mono">
                  ₹{profile.book_value?.toFixed(1) || 'N/A'}
                </div>
              </div>

              <div className="bg-slate-950/80 p-3 rounded-lg border border-slate-800/80">
                <div className="text-[11px] text-slate-400 font-medium">Div. Yield</div>
                <div className="text-sm font-bold text-cyan-300 mt-1 font-mono">
                  {profile.dividend_yield !== undefined && profile.dividend_yield !== null
                    ? `${(profile.dividend_yield > 1 ? profile.dividend_yield : profile.dividend_yield * 100).toFixed(2)}%`
                    : 'N/A'}
                </div>
              </div>
            </div>

            {/* Forensic & Quantitative Ratios Ribbon */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-2">
              {/* Piotroski Score */}
              <div className="bg-gradient-to-br from-slate-900 to-slate-950 p-3.5 rounded-lg border border-slate-700/60 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-slate-300">Piotroski F-Score</div>
                  <div className="text-[11px] text-slate-400">9-point financial health</div>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2.5 py-1 text-sm font-bold rounded-md font-mono ${
                      (profile.custom_ratios.piotroski_score || 0) >= 7
                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                        : (profile.custom_ratios.piotroski_score || 0) >= 4
                        ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                        : 'bg-red-500/20 text-red-300 border border-red-500/40'
                    }`}
                  >
                    {profile.custom_ratios.piotroski_score || 0}/9
                  </span>
                </div>
              </div>

              {/* Graham Number */}
              <div className="bg-gradient-to-br from-slate-900 to-slate-950 p-3.5 rounded-lg border border-slate-700/60 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-slate-300">Graham Fair Value</div>
                  <div className="text-[11px] text-slate-400">
                    {profile.custom_ratios.graham_upside_pct !== null && profile.custom_ratios.graham_upside_pct !== undefined ? (
                      <span
                        className={
                          profile.custom_ratios.graham_upside_pct >= 0 ? 'text-emerald-400' : 'text-red-400'
                        }
                      >
                        {profile.custom_ratios.graham_upside_pct >= 0 ? '+' : ''}
                        {profile.custom_ratios.graham_upside_pct}% Margin
                      </span>
                    ) : (
                      'Intrinsic value'
                    )}
                  </div>
                </div>
                <div className="text-sm font-bold text-white font-mono">
                  {profile.custom_ratios.graham_number
                    ? `₹${profile.custom_ratios.graham_number.toFixed(0)}`
                    : 'N/A'}
                </div>
              </div>

              {/* EV / EBITDA */}
              <div className="bg-gradient-to-br from-slate-900 to-slate-950 p-3.5 rounded-lg border border-slate-700/60 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-slate-300">EV / EBITDA</div>
                  <div className="text-[11px] text-slate-400">Enterprise multiple</div>
                </div>
                <div className="text-sm font-bold text-white font-mono">
                  {profile.custom_ratios.ev_to_ebitda
                    ? `${profile.custom_ratios.ev_to_ebitda.toFixed(1)}x`
                    : 'N/A'}
                </div>
              </div>

              {/* CFO / PAT */}
              <div className="bg-gradient-to-br from-slate-900 to-slate-950 p-3.5 rounded-lg border border-slate-700/60 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-slate-300">CFO / PAT Ratio</div>
                  <div className="text-[11px] text-slate-400">Earnings cash conversion</div>
                </div>
                <div className="text-sm font-bold text-emerald-400 font-mono">
                  {profile.custom_ratios.cfo_to_pat_ratio
                    ? `${profile.custom_ratios.cfo_to_pat_ratio.toFixed(2)}`
                    : 'N/A'}
                </div>
              </div>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="flex border-b border-slate-800 gap-2 overflow-x-auto pb-1">
            {[
              { id: 'overview', label: 'Overview & Analysis', icon: Layers },
              { id: 'shareholding', label: 'Shareholding (12Q/11Y)', icon: PieChartIcon },
              {
                id: 'concalls',
                label: `Concalls & Audio (${profile.concall_count || concalls.length})`,
                icon: Volume2,
              },
              { id: 'financials', label: '10-Year Audited Statements', icon: BarChart2 },
              { id: 'ai-dossier', label: 'AI Dossier & Prompts', icon: Sparkles },
            ].map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as any)}
                  className={`flex items-center gap-2 px-4 py-2.5 font-medium text-sm rounded-t-lg transition-all border-b-2 whitespace-nowrap ${
                    active
                      ? 'bg-slate-900 text-blue-400 border-blue-500 shadow'
                      : 'text-slate-400 border-transparent hover:text-slate-200 hover:bg-slate-900/40'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>

          {/* Tab 1: Overview & Growth Matrix */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {profile.about && (
                <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl">
                  <h3 className="text-sm font-bold text-white uppercase tracking-wider mb-2">About Company</h3>
                  <p className="text-sm text-slate-300 leading-relaxed">{profile.about}</p>
                </div>
              )}

              {/* Pros & Cons */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl">
                  <h3 className="text-sm font-bold text-emerald-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4" /> Pros
                  </h3>
                  {profile.pros && profile.pros.length > 0 ? (
                    <ul className="space-y-2">
                      {profile.pros.map((p, i) => (
                        <li key={i} className="text-xs text-slate-300 flex items-start gap-2">
                          <span className="text-emerald-400 mt-0.5">•</span>
                          <span>{p}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-slate-500 italic">No specific strengths cataloged.</p>
                  )}
                </div>

                <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl">
                  <h3 className="text-sm font-bold text-amber-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4" /> Cons & Key Risks
                  </h3>
                  {profile.cons && profile.cons.length > 0 ? (
                    <ul className="space-y-2">
                      {profile.cons.map((c, i) => (
                        <li key={i} className="text-xs text-slate-300 flex items-start gap-2">
                          <span className="text-amber-400 mt-0.5">•</span>
                          <span>{c}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-slate-500 italic">No specific risks cataloged.</p>
                  )}
                </div>
              </div>

              {/* Compounded Growth Matrix */}
              {profile.cagrs && Object.keys(profile.cagrs).length > 0 && (
                <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl">
                  <h3 className="text-sm font-bold text-white uppercase tracking-wider mb-4">
                    Compounded Growth & Return Matrix
                  </h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    {Object.entries(profile.cagrs).map(([cagrTitle, cagrValues]) => (
                      <div key={cagrTitle} className="bg-slate-950 p-4 rounded-lg border border-slate-800">
                        <div className="text-xs font-semibold text-blue-400 mb-2 border-b border-slate-800 pb-1">
                          {cagrTitle}
                        </div>
                        <div className="space-y-1 text-xs">
                          {Object.entries(cagrValues).map(([period, val]) => (
                            <div key={period} className="flex justify-between items-center text-slate-300">
                              <span className="text-slate-400">{period.replace(':', '')}</span>
                              <span className="font-mono font-bold text-white">{val}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Peer Comparison Table */}
              {profile.peers && profile.peers.length > 0 && (
                <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
                  <div className="p-4 border-b border-slate-800">
                    <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                      Industry Peer Comparison ({profile.industry || profile.sector})
                    </h3>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs text-left text-slate-300">
                      <thead className="bg-slate-950 text-slate-400 uppercase font-mono border-b border-slate-800">
                        <tr>
                          <th className="py-2.5 px-4">#</th>
                          <th className="py-2.5 px-4">Company</th>
                          <th className="py-2.5 px-4 text-right">CMP (₹)</th>
                          <th className="py-2.5 px-4 text-right">P/E</th>
                          <th className="py-2.5 px-4 text-right">Mar Cap (Cr)</th>
                          <th className="py-2.5 px-4 text-right">ROCE (%)</th>
                          <th className="py-2.5 px-4 text-right">Div Yld (%)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800">
                        {profile.peers.map((peer, idx) => (
                          <tr
                            key={idx}
                            className={`hover:bg-slate-800/40 transition-colors ${
                              peer.symbol === profile.symbol ? 'bg-blue-950/30 font-semibold' : ''
                            }`}
                          >
                            <td className="py-2.5 px-4 text-slate-400">{peer.rank || idx + 1}</td>
                            <td className="py-2.5 px-4">
                              <button
                                onClick={() => setActiveTicker(peer.symbol || peer.name)}
                                className="text-blue-400 hover:underline text-left font-medium"
                              >
                                {peer.name}
                              </button>
                            </td>
                            <td className="py-2.5 px-4 text-right font-mono">
                              ₹{peer.cmp?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                            </td>
                            <td className="py-2.5 px-4 text-right font-mono">{peer.pe?.toFixed(1) || '-'}</td>
                            <td className="py-2.5 px-4 text-right font-mono">{formatCr(peer.market_cap_cr)}</td>
                            <td className="py-2.5 px-4 text-right font-mono text-emerald-400">
                              {peer.roce ? `${peer.roce.toFixed(1)}%` : '-'}
                            </td>
                            <td className="py-2.5 px-4 text-right font-mono text-cyan-300">
                              {peer.dividend_yield ? `${peer.dividend_yield.toFixed(2)}%` : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Tab 2: Shareholding Trends (12Q / 11Y) */}
          {activeTab === 'shareholding' && shareholding && (
            <div className="space-y-6">
              <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl shadow-lg space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                      Institutional Shareholding Pattern Trends
                    </h3>
                    <p className="text-xs text-slate-400">
                      Promoters, Foreign Institutional Investors (FIIs), Domestic Institutions (DIIs) & Public
                    </p>
                  </div>
                  <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-800 self-start">
                    <button
                      onClick={() => setShareholdingFreq('quarterly')}
                      className={`px-3 py-1 text-xs font-semibold rounded ${
                        shareholdingFreq === 'quarterly'
                          ? 'bg-blue-600 text-white'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      Quarterly (12Q)
                    </button>
                    <button
                      onClick={() => setShareholdingFreq('yearly')}
                      className={`px-3 py-1 text-xs font-semibold rounded ${
                        shareholdingFreq === 'yearly'
                          ? 'bg-blue-600 text-white'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      Yearly (11Y)
                    </button>
                  </div>
                </div>

                {/* Stacked Area Chart */}
                <div className="h-72 w-full pt-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart
                      data={
                        shareholdingFreq === 'quarterly'
                          ? shareholding.quarterly.chart_series
                          : shareholding.yearly.chart_series
                      }
                      margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis dataKey="period" stroke="#64748b" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#64748b" tick={{ fontSize: 11 }} domain={[0, 100]} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#0f172a',
                          borderColor: '#334155',
                          borderRadius: '8px',
                          color: '#f8fafc',
                        }}
                      />
                      <Legend />
                      <Area
                        type="monotone"
                        dataKey="promoters"
                        name="Promoters %"
                        stackId="1"
                        stroke="#3b82f6"
                        fill="#3b82f6"
                        fillOpacity={0.7}
                      />
                      <Area
                        type="monotone"
                        dataKey="fiis"
                        name="FIIs %"
                        stackId="1"
                        stroke="#10b981"
                        fill="#10b981"
                        fillOpacity={0.7}
                      />
                      <Area
                        type="monotone"
                        dataKey="diis"
                        name="DIIs %"
                        stackId="1"
                        stroke="#f59e0b"
                        fill="#f59e0b"
                        fillOpacity={0.7}
                      />
                      <Area
                        type="monotone"
                        dataKey="government"
                        name="Govt %"
                        stackId="1"
                        stroke="#8b5cf6"
                        fill="#8b5cf6"
                        fillOpacity={0.7}
                      />
                      <Area
                        type="monotone"
                        dataKey="public"
                        name="Public %"
                        stackId="1"
                        stroke="#64748b"
                        fill="#64748b"
                        fillOpacity={0.7}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Detailed Breakdown Table */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
                <div className="p-4 border-b border-slate-800">
                  <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
                    Historical Shareholding Breakdown Table
                  </h4>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left text-slate-300">
                    <thead className="bg-slate-950 text-slate-400 font-mono border-b border-slate-800">
                      <tr>
                        <th className="py-2.5 px-4">Holder Category</th>
                        {(shareholdingFreq === 'quarterly'
                          ? shareholding.quarterly.periods
                          : shareholding.yearly.periods
                        ).map((p) => (
                          <th key={p} className="py-2.5 px-3 text-right">
                            {p}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 font-mono">
                      {Object.entries(
                        shareholdingFreq === 'quarterly'
                          ? shareholding.quarterly.rows
                          : shareholding.yearly.rows
                      ).map(([cat, values]) => (
                        <tr key={cat} className="hover:bg-slate-800/40">
                          <td className="py-2 px-4 font-sans font-medium text-slate-200">{cat}</td>
                          {values.map((v, i) => (
                            <td key={i} className="py-2 px-3 text-right">
                              {v !== null && v !== undefined ? `${v}%` : '-'}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* Tab 3: Earnings Concalls & Audio Player */}
          {activeTab === 'concalls' && (
            <div className="space-y-6">
              {/* Active Audio Player Floating Bar */}
              {activeAudioUrl && (
                <div className="bg-gradient-to-r from-blue-900 to-indigo-900 border border-blue-500/50 p-4 rounded-xl shadow-xl flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 bg-blue-500/20 text-blue-300 rounded-full animate-pulse">
                      <Volume2 className="w-6 h-6" />
                    </div>
                    <div>
                      <div className="text-sm font-bold text-white">Streaming Earnings Call Audio (MP3)</div>
                      <div className="text-xs text-blue-200 truncate max-w-md">{activeAudioUrl}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <audio src={activeAudioUrl} controls autoPlay className="h-10 rounded-lg max-w-sm" />
                    <button
                      onClick={() => setActiveAudioUrl(null)}
                      className="px-3 py-1.5 bg-slate-900/80 hover:bg-slate-900 text-xs font-semibold text-slate-300 rounded-lg"
                    >
                      Close
                    </button>
                  </div>
                </div>
              )}

              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
                <div className="p-4 border-b border-slate-800 flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                      Quarterly Earnings Conference Calls ({concalls.length})
                    </h3>
                    <p className="text-xs text-slate-400">
                      Direct access to verified BSE audio MP3s, analyst transcripts, and investor presentations
                    </p>
                  </div>
                </div>

                {concalls.length === 0 ? (
                  <div className="p-10 text-center text-slate-400 text-sm">
                    No conference call recordings available for this ticker.
                  </div>
                ) : (
                  <div className="divide-y divide-slate-800">
                    {concalls.map((call, idx) => (
                      <div
                        key={idx}
                        className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-slate-800/30 transition-colors"
                      >
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 bg-blue-950 text-blue-300 border border-blue-800 rounded text-xs font-semibold font-mono">
                              {call.quarter || call.date}
                            </span>
                            <h4 className="text-sm font-bold text-white">{call.title || `Earnings Call - ${call.date}`}</h4>
                          </div>
                          <div className="text-xs text-slate-400 flex items-center gap-2">
                            <span>Date: {call.date}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 flex-wrap">
                          {call.audio_url && (
                            <button
                              onClick={() => setActiveAudioUrl(call.audio_url || null)}
                              className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border border-indigo-500/40 rounded-lg text-xs font-semibold transition-colors"
                            >
                              <Play className="w-3.5 h-3.5" />
                              <span>Listen MP3</span>
                            </button>
                          )}
                          {call.transcript_url && (
                            <a
                              href={call.transcript_url}
                              target="_blank"
                              rel="noreferrer"
                              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-medium transition-colors"
                            >
                              <FileText className="w-3.5 h-3.5 text-blue-400" />
                              <span>Transcript</span>
                            </a>
                          )}
                          {call.presentation_url && (
                            <a
                              href={call.presentation_url}
                              target="_blank"
                              rel="noreferrer"
                              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-medium transition-colors"
                            >
                              <ExternalLink className="w-3.5 h-3.5 text-emerald-400" />
                              <span>PPT</span>
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Tab 4: 10-Year Audited Financial Statements */}
          {activeTab === 'financials' && (
            <div className="space-y-4">
              <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl shadow-lg flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400 font-semibold uppercase">Statement:</span>
                  <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-800">
                    <button
                      onClick={() => setFinancialStmt('income')}
                      className={`px-3 py-1 text-xs font-semibold rounded ${
                        financialStmt === 'income' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      Income Statement
                    </button>
                    <button
                      onClick={() => setFinancialStmt('balance')}
                      className={`px-3 py-1 text-xs font-semibold rounded ${
                        financialStmt === 'balance' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      Balance Sheet
                    </button>
                    <button
                      onClick={() => setFinancialStmt('cashflow')}
                      className={`px-3 py-1 text-xs font-semibold rounded ${
                        financialStmt === 'cashflow' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      Cash Flow
                    </button>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400 font-semibold uppercase">Frequency:</span>
                  <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-800">
                    <button
                      onClick={() => setFinancialFreq('annual')}
                      className={`px-3 py-1 text-xs font-semibold rounded ${
                        financialFreq === 'annual' ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      Annual (10-13 Years)
                    </button>
                    <button
                      onClick={() => setFinancialFreq('quarterly')}
                      className={`px-3 py-1 text-xs font-semibold rounded ${
                        financialFreq === 'quarterly' ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      Quarterly (12-16Q)
                    </button>
                  </div>
                </div>
              </div>

              {financials && financials.data ? (
                <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
                  <div className="p-4 border-b border-slate-800 flex justify-between items-center">
                    <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                      {financialStmt.toUpperCase()} STATEMENT ({financialFreq.toUpperCase()}) — In ₹ Cr
                    </h4>
                    <button
                      onClick={handleExportExcel}
                      className="text-xs text-emerald-400 hover:underline flex items-center gap-1 font-medium"
                    >
                      <Download className="w-3 h-3" /> Export to Excel
                    </button>
                  </div>
                  <div className="overflow-x-auto max-h-[600px]">
                    <table className="w-full text-xs text-left text-slate-300">
                      <thead className="bg-slate-950 text-slate-400 font-mono border-b border-slate-800 sticky top-0">
                        <tr>
                          <th className="py-2.5 px-4 bg-slate-950 sticky left-0 z-10">Line Item</th>
                          {(financials.columns || []).map((col: string) => (
                            <th key={col} className="py-2.5 px-3 text-right whitespace-nowrap">
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800 font-mono">
                        {Object.entries(financials.data).map(([metric, values]: [string, any]) => (
                          <tr key={metric} className="hover:bg-slate-800/40">
                            <td className="py-2 px-4 font-sans font-medium text-slate-200 bg-slate-900/90 sticky left-0">
                              {metric}
                            </td>
                            {(financials.columns || []).map((col: string) => {
                              const val = values[col];
                              return (
                                <td key={col} className="py-2 px-3 text-right">
                                  {val !== null && val !== undefined
                                    ? typeof val === 'number'
                                      ? Number(val).toLocaleString('en-IN', { maximumFractionDigits: 1 })
                                      : val
                                    : '-'}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="bg-slate-900 p-8 text-center text-slate-400 text-sm rounded-xl">
                  Loading statement records...
                </div>
              )}
            </div>
          )}

          {/* Tab 5: AI Dossier & Prompts */}
          {activeTab === 'ai-dossier' && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl space-y-3">
                  <div className="flex items-center gap-2 text-indigo-400">
                    <Sparkles className="w-5 h-5" />
                    <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                      Initiation Coverage Memo
                    </h3>
                  </div>
                  <p className="text-xs text-slate-400">
                    Institutional prompt containing 10-year audited metrics, CAGR trends, and qualitative analysis
                    ready for feeding to Claude 3.7 / ChatGPT o3.
                  </p>
                  <button
                    onClick={handleOpenAiMemo}
                    className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition-colors"
                  >
                    View & Copy Memo Prompt
                  </button>
                </div>

                <div className="bg-slate-900 border border-slate-800 p-5 rounded-xl space-y-3">
                  <div className="flex items-center gap-2 text-amber-400">
                    <ShieldAlert className="w-5 h-5" />
                    <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                      Forensic Accounting Audit
                    </h3>
                  </div>
                  <p className="text-xs text-slate-400">
                    Specialized prompt designed to scan for working capital distortion, aggressive revenue recognition,
                    and contingent liability red flags.
                  </p>
                  <button
                    onClick={handleOpenAiForensic}
                    className="w-full py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-semibold transition-colors"
                  >
                    View & Copy Forensic Prompt
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* AI Prompt Modal */}
      {aiModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col shadow-2xl">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <h3 className="font-bold text-white text-sm flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-indigo-400" />
                {aiModalTitle}
              </h3>
              <button
                onClick={() => setAiModalOpen(false)}
                className="text-slate-400 hover:text-white text-sm font-bold"
              >
                ✕
              </button>
            </div>
            <div className="p-4 overflow-y-auto flex-1 font-mono text-xs text-slate-300 bg-slate-950 whitespace-pre-wrap select-all">
              {aiPromptContent}
            </div>
            <div className="p-4 border-t border-slate-800 flex justify-between items-center bg-slate-900">
              <span className="text-xs text-slate-400">
                Paste directly into Claude 3.7 Sonnet, DeepSeek R1, or ChatGPT o3.
              </span>
              <button
                onClick={() => copyToClipboard(aiPromptContent)}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold transition-colors"
              >
                {copiedPrompt ? <Check className="w-4 h-4 text-emerald-300" /> : <Copy className="w-4 h-4" />}
                <span>{copiedPrompt ? 'Copied to Clipboard!' : 'Copy Prompt'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
