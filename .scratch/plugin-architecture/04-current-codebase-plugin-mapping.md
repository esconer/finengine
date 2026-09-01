# 04. Current Codebase to Plugin Mapping

## 1. Inventory of Current FinEngine Mathematical Services

All major services in [`backend/app/services/`](file:///c:/es/coding/finengine/backend/app/services) map 1-to-1 into self-contained plugins:

| Current Service File | Core Libraries | Target Plugin Package | Description |
| :--- | :--- | :--- | :--- |
| `optimization_service.py` | `cvxpy`, `scipy.cluster` | `plugins/quant-optimization/` | HRP, Min Volatility, Max Sharpe, Min CVaR |
| `regime_service.py` | `hmmlearn`, `scikit-learn` | `plugins/quant-regime/` | 3-State Gaussian HMM regime detection |
| `volatility_service.py` | `arch`, `statsmodels` | `plugins/quant-volatility/` | Multi-window Vol Cone & GARCH forecasts |
| `cointegration_service.py` | `statsmodels` | `plugins/quant-cointegration/` | Engle-Granger, Johansen & OU half-life |
| `tail_risk_service.py` | `scipy.stats` (genpareto, t-copula) | `plugins/quant-tail-risk/` | EVT POT 99% VaR/ES & Copula Tail Matrix |
| `india_data_service.py` | `aiohttp`, `yfinance` | `plugins/data-india-flows/` | NSE Bhavcopy, 2σ delivery accumulation |
| `indicators_service.py` | `stockstats` | `plugins/indicators-technical/` | RSI, MACD, Bollinger Bands, ATR |
| `ai_dossier_service.py` | `bfinance` | `plugins/research-ai-dossier/` | Company financials & AI company dossiers |
| `export.ts` | `jspdf` | `frontend/src/plugins/report-pdf/` | Institutional tear-sheet PDF generator |

---

## 2. Directory Layout When Unbundled

```
finengine/
├── backend/
│   ├── app/
│   │   ├── core/           # Kernel: Database, Auth, PluginLoader
│   │   ├── sdk/            # FinEnginePlugin, BaseQuantModel interfaces
│   │   └── api/portfolio.py # Core position CRUD
│   └── plugins/
│       ├── quant-optimization/
│       │   ├── plugin.py
│       │   └── math.py     # Transferred from optimization_service.py
│       ├── quant-regime/
│       │   ├── plugin.py
│       │   └── hmm.py      # Transferred from regime_service.py
│       └── quant-cointegration/
│           ├── plugin.py
│           └── coint.py    # Transferred from cointegration_service.py
│
└── frontend/
    ├── src/
    │   ├── components/layout/ # Dynamic Sidebar & Header
    │   └── lib/sdk/           # Shared Tailwind tokens, Lucide, Chart Kit
    └── src/plugins/
        ├── cointegration/     # /dashboard/pairs & SpreadChart
        └── volatility/        # /dashboard/forecast-risk & VolConeChart
```