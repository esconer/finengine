# Data & Indicator Libraries — Evaluation for FinEngine

**Scope:** Should FinEngine (FastAPI + Next.js institutional portfolio risk analytics, Indian NSE/BSE markets, yfinance-backed) adopt, partially adopt, or avoid three open-source Python finance libraries?

**Date of research:** 2026-09-27. All dates, versions and file sizes below were observed directly from GitHub, PyPI, or by downloading and parsing the data files. Anything not directly verified is explicitly marked `UNVERIFIED`.

**Method:**
1. **Context7 MCP** (`/jerbouma/financetoolkit`, `/jerbouma/financedatabase`) — 10 narrow, one-concept-per-call queries to ground API signatures, the data/API-key dependency chain, and macro/India support in current versioned docs.
2. **GitHub `LICENSE` / `pyproject.toml` / release pages** — authoritative for licensing, pinned dependencies and maintenance facts (overrides Context7 where they disagree).
3. **Empirical measurement** — downloaded `equities.bz2` (14.58 MB) and parsed it with the repo's own pandas 3.0.6 read-arguments to measure Indian-market coverage rather than trusting the README.
4. **PyPI JSON APIs** for version/upload dates and wheel tags.

**Context7 coverage:** available for FinanceToolkit and FinanceDatabase. **No Context7 entry exists for shashankvemuri/Finance** — two `resolve-library-id` attempts (`shashankvemuri Finance`, `finance-toolkit shashank`) returned only unrelated projects (`/verdenroz/finance-query` Rust, `/ebradyjobory/finance.js`, `/railpath/finance-toolkit` TypeScript). That library therefore falls back to official sources: GitHub `pyproject.toml`, `LICENSE`, `docs/providers.md`, `src/finance/**/*.py`, and the commit history. Context7 also has **no pandas/numpy version documentation** for FinanceToolkit, so `pyproject.toml` is the sole authority for the compatibility claims below.

**Stack context verified locally** (`uv run python` in `backend/`):
Python 3.12.9 · pandas 3.0.6 · numpy 2.5.3 · scipy 1.18.1 · scikit-learn 1.9.1 · yfinance 1.7.0 · stockstats 0.6.8 · bfinance 0.1.3 · arch 8.0.0 · quantstats 0.0.81 · statsmodels 0.15.0 · cvxpy 1.9.3 · hmmlearn 0.3.3 · openpyxl 3.1.5 · requests 2.34.2 · pyyaml 6.0.3

---

## FinanceToolkit

MIT-licensed, actively maintained, **pandas 3.0-native** quantitative toolkit from JerBouma that runs on the same yfinance stack FinEngine already has — and it can be pointed at Yahoo Finance with **no API key**. Adopt its unique scoring/valuation models and macro modules only; ignore its risk/performance/portfolio stack, which duplicates ~4,000 lines of FinEngine code that is already better-tested for our use case.

### Verdict

**ADOPT_PARTIAL**

Adopt the `models` module (Altman Z, Piotroski, Beneish M, Ohlson O, Zmijewski, Springate, Grover, Fulmer, DuPont, WACC, EVA, Tobin's Q, DDM, residual income, Graham number), the `technicals` breadth family, and `economics` (FRED/OECD/GMDB). Do **not** adopt `risk`, `performance`, `portfolio`, `options`, or most of `technicals` — they overlap almost completely with FinEngine's `analytics_engine.py` (4,119 lines), `optimization_service.py`, `tail_risk_service.py`, `volatility_service.py`, and `benchmark_service.py`, and FinEngine's versions carry Indian-market-specific semantics (INR risk-free rate, NSE trading calendar) that the toolkit's US-Treasury-based defaults would silently get wrong. Critical constraint: `enforce_source="YahooFinance"` is mandatory — never let it fall through to FinancialModelingPrep, whose free tier is US-exchange-only.

### License

- **License:** MIT
- **SPDX id:** `MIT`
- **Source:** [`pyproject.toml`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/pyproject.toml) → `license = {text = "MIT"}`; [`LICENSE.txt`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/LICENSE.txt); GitHub API `license.spdx_id = "MIT"`.

> **NOTE — the brief's assumption was wrong.** The task brief said "JerBouma's projects are commonly Apache-2.0 — VERIFY, do not assume." Verified: **both FinanceToolkit and FinanceDatabase are MIT, not Apache-2.0.** (FinEngine's own `indicators_service.py:14` is Apache-2.0 — a different license, and the one people are likely misremembering.)

Clause (verbatim, `LICENSE.txt`):

> ```
> MIT License
> Copyright (c) 2025 Jeroen Bouma
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
> ```

**Commercial impact:** No restriction. Permissive, no copyleft, no field-of-use restriction, no business-source clause, no network-copyleft. Commercial use and redistribution are explicitly allowed.

**Linking vs vendoring:** Either works. MIT requires only that the copyright notice travel with copies/substantial portions. If you `pip install` and `import`, you must ship the notice in your distribution's third-party licenses page. If you vendor source into `app/`, you must retain the header in each vendored file. **Do not mix the licenses** — a vendored MIT file inside an otherwise-Apache-2.0 `indicators_service.py` is fine but must keep both notices distinct.

### Maintenance

**ACTIVE** — the healthiest of the three libraries.

| Signal | Observed value | Source |
|---|---|---|
| Latest release | **v2.2.0**, published **2026-08-18T12:47:06Z** | [releases API](https://api.github.com/repos/JerBouma/FinanceToolkit/releases) |
| Last push to `main` | **2026-09-10T16:10:58Z** | [repo API](https://api.github.com/repos/JerBouma/FinanceToolkit) |
| Open issues | **3** (2 of them third-party "paid API key via `neuforge-pay`" feature requests) | [search API](https://api.github.com/search/issues?q=repo:JerBouma/FinanceToolkit+is:issue+state:open) |
| Release cadence | 13 releases in 2025-2026 alone; ~2-6 week intervals | releases API |
| Stars / forks | 5,384 / 626 | repo API |
| Archived | `false` | repo API |
| Classification | `Development Status :: 5 - Production/Stable` | pyproject.toml |

Note: the maintainer earns an **affiliate commission** on FMP subscriptions through `https://www.jeroenbouma.com/fmp` (disclosed in the README). Not a license problem, but a mild conflict-of-interest reason to prefer the Yahoo path.

### Compatibility

| Requirement | Status | Evidence |
|---|---|---|
| Python 3.12 | ✅ Supported | `requires-python = ">=3.11, <3.16"`; classifiers list 3.11–3.15 |
| pandas 3.0 | ✅ **Native, not just compatible** | `dependencies = ["pandas>=3.0", ...]` — the floor *is* pandas 3.0. The 18 closed "pandas 3" issues on GitHub are all resolved. |
| numpy 2.x | ✅ | Unpinned; inherits pandas 3's numpy 2.x floor |
| Compiled extensions | ❌ None | Wheel is `financetoolkit-2.2.0-py3-none-any.whl` (pure-python tag), 0.97 MB |

**No pandas 3 / numpy 2 blocker found.** This is unusual and decisive — most quant libraries still cap at `pandas<3`. FinanceToolkit has already migrated.

**Undeclared dependency bug (low severity):** `financetoolkit/risk/var_model.py` does `from scipy import stats`, but `scipy` is **not** in `pyproject.toml` dependencies. It resolves today only because `scikit-learn>=1.6` pulls scipy transitively. If FinEngine ever constrains scikit-learn or the resolver changes, `risk` will ImportError. Since we're not adopting `risk`, this is informational.

### Data dependency chain

This is the decisive section. **FinanceToolkit is usable for Indian tickers with zero API keys**, but only via one specific configuration.

```
Toolkit(enforce_source="YahooFinance")
        │
        ├─ get_historical_data  ──► yfinance 1.7.0  ──► Yahoo Finance chart API
        │     (yfinance_model.get_historical_data → yf.Ticker(t).history(auto_adjust=False, repair=...))
        │
        ├─ get_balance_sheet / income / cashflow ──► yfinance 1.7.0
        │     (yfinance_model.get_financial_statement → Ticker.get_income_stmt / get_balance_sheet / get_cash_flow)
        │
        └─ get_statistics_statement ──► Yahoo quoteSummary `financialCurrency` (reporting currency)

Toolkit(api_key=...)  or  Discovery(...)
        └─ FinancialModelingPrep REST API   ◄── 250 req/day (Free), US exchanges only
```

**Primary vs fallback (verbatim from README):**

> "**By default, the Finance Toolkit prioritizes Financial Modeling Prep for data retrieval. If data acquisition from Financial Modeling Prep is unsuccessful (e.g., due to plan restrictions or API key issues), the toolkit automatically switches to Yahoo Finance as a secondary source.** To disable this fallback behavior and exclusively use Financial Modeling Prep, set `enforce_source="FinancialModelingPrep"` during Toolkit initialization. ... Alternatively, you can set `enforce_source="YahooFinance"` to exclusively use Yahoo Finance as the data source."

**API keys required:**

| Module | Key needed? | Notes |
|---|---|---|
| `get_historical_data` | **No** (with `enforce_source="YahooFinance"`) | Works for any yfinance symbol incl. `.NS` / `.BO` |
| `get_income_statement` / `balance` / `cashflow` | **No** (Yahoo path) | Sparse for Indian small/mid-caps — yfinance often has no statements at all |
| `technicals`, `risk`, `performance`, `models`, `ratios` | **No** (all derived from the above two) | Pure functions on retrieved frames |
| `Discovery.*` (all 30 methods incl. `get_stock_screener`) | **Yes — FMP only** | `discovery_model.py` calls `fmp_model.get_financial_data` unconditionally. **No Yahoo fallback exists for Discovery.** |

**Free tier (verbatim from README):**

> "Note that the Free plan is limited to 250 requests each day, 5 years of data and only features companies listed on US exchanges."

**Indian market support — VERIFIED by code inspection, not inference:**

- `yfinance_model.get_historical_data()` calls `yf.Ticker(ticker).history(...)` with no exchange allow-list, no country filter, no symbol validation. Any string yfinance resolves works, including `RELIANCE.NS`, `500112.BO`, `BAJAJ-AUTO.NS`.
- `divide_ohlc_by` parameter exists specifically for instruments quoted in paise/percent, irrelevant here.
- `get_historical_statistics()` hits `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}` and returns Yahoo's `exchangeName` / `currency` / `firstTradeDate` metadata — for `.NS` this returns `NSI` / `INR`.
- **No Indian-specific limitation found.** The only real risk is data *quality* for Indian small/mid-caps via yfinance (empty statements), not a hard block.

**Offline / vendoring feasibility:**

- **Not vendored.** The wheel is 0.97 MB of pure Python with no bundled data — pip-install is the right path.
- `Toolkit` accepts **pre-supplied DataFrames** for `historical`, `balance`, `income`, `cash` (documented as the "external datasets" notebook). **This is the key integration seam:** FinEngine already has a warm SQLite OHLCV cache in `data_service.py`; passing those frames in means the toolkit never touches the network at all, which eliminates rate-limit and staleness risk entirely.
- Built-in **SQLite cache** (`financetoolkit/cache/`) at `%APPDATA%\financetoolkit\financetoolkit_cache.db` on Windows, overridable via `FINANCE_TOOLKIT_CACHE_DB`. ⚠️ This writes to the user's roaming profile by default — in a containerised deploy you must set that env var explicitly or leave caching off.
- ⚠️ **Global mutable cache registry.** `cache_controller.py` holds module-level `_CACHE_REGISTRY` + `_ACTIVE_CACHE` guarded by a `threading.Lock`, published via `set_active_cache()`. In FastAPI this is **process-global shared mutable state** — acceptable (it's a cache) but it means two different `Toolkit` instances with different configs in one worker will fight over the active cache. Instantiate **one** `Toolkit` per process (module-level singleton), not per request.
- GitHub repo `size` field is 311,347 KB (~304 MB), but that is **git history + notebook outputs**, not install size. The installed wheel is 0.97 MB.

### Dependency footprint

**Direct dependencies** (from [PyPI `requires_dist`](https://pypi.org/pypi/financetoolkit/json)):

| Package | Constraint | FinEngine status | Conflict risk |
|---|---|---|---|
| `pandas` | `>=3.0` | 3.0.6 ✅ | **None** — FinEngine is already on 3.0.6 |
| `yfinance` | *(unpinned)* | 1.7.0 ✅ | **None** — same library, shared HTTP/crumb/cookie session behaviour |
| `scikit-learn` | `>=1.6` | 1.9.1 ✅ | **None** |
| `requests` | `>=2.32` | 2.34.2 ✅ | **None** |
| `openpyxl` | `>=3.1` | 3.1.5 ✅ | **None** |
| `pyyaml` | `>=6.0` | 6.0.3 ✅ *(present transitively, NOT declared in FinEngine's pyproject)* | **Low.** Add explicitly to be safe — the version is already resolved |
| `scipy` | *undeclared, used by `risk/`* | 1.18.1 ✅ | **Low** — resolves via scikit-learn today |

**Optional extras (do NOT install):** `econometrics` → `linearmodels>=6.0` (not installed, adds pandas/numpy pin pressure); `mcp` → `fastmcp>=3.4.2`, `mcp[cli]`, `rich`, `tabulate` (irrelevant to FinEngine).

**Net new installs: zero packages.** Every declared dependency is already satisfied at a compatible version. This is the single strongest argument for adoption.

⚠️ Per `AGENTS.md`: after editing `backend/pyproject.toml`, run `uv sync --extra dev --group dev` or tools silently vanish.

### API surface

Real, copyable, verified against the source in `main` @ 2.2.0.

**Constructor** (`toolkit_controller.py`):

```python
from financetoolkit import Toolkit

companies = Toolkit(
    tickers=["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS"],
    api_key="",                          # or omit: defaults to $FINANCIAL_MODELING_PREP_API_KEY
    enforce_source="YahooFinance",       # ◄── MANDATORY for FinEngine. Blocks the FMP fallback.
    benchmark_ticker=None,               # ◄── disable; "SPY" default is meaningless for an INR book
    risk_free_rate="10y",                # ◄── US Treasury. See Risk & caveats.
    start_date="2019-01-01",
    use_cached_data=True,                # SQLite cache, or a path string
    convert_currency=False,              # avoid FMP-plan-dependent conversion
    progress_bar=False,
    fred_api_key="",                     # ◄── see Economics; not needed for India (OECD/GMDB path)
)
```

**Module properties** (lazily built sub-controllers, all sync after init):
`companies.ratios` · `.models` · `.technicals` · `.risk` · `.performance` · `.econometrics` · `.options`

⚠️ **Correction from Context7:** `Economics` and `FixedIncome` are **standalone classes**, not `companies.economics` / `companies.fixedincome`. The README groups them under "Explore the Modules", but the notebooks import them directly and the README says the economics module "can be utilized as a standalone component within the toolkit":
```python
from financetoolkit import Economics, FixedIncome

economics = Economics(start_date="2015-01-01")
fixedincome = FixedIncome(start_date="2012-01-01")
```

**Data** (signatures per Context7; note `period=`, not `interval=`):
```python
companies.get_historical_data()                                # MultiIndex(date, ticker) x [Open High Low Close Adj Close Volume Dividends Return Cumulative Return]
companies.get_historical_data(period="weekly")                 # daily/weekly/monthly/quarterly/yearly
companies.get_balance_sheet_statement()
companies.get_income_statement(growth=True)                    # per-period growth
companies.get_cash_flow_statement()
companies.get_statistics_statement()

# 3-level MultiIndex result: (ticker, line item, period)
balance_sheet = companies.get_balance_sheet_statement()
balance_sheet.loc["AMZN"]["Total Shareholder Equity"]          # .loc[:, "Revenue", :] for cross-ticker
```

**`models` — the highest-ROI surface for FinEngine (all ADOPT).** Signatures verified via Context7 against `examples/Finance Toolkit - 4. Models Module.ipynb`:
```python
companies.models.get_altman_z_score()          # get_piotroski_score, get_beneish_m_score
companies.models.get_ohlson_o_score()          # get_zmijewski_score, get_springate_score
companies.models.get_grover_score()            # get_fulmer_h_score
companies.models.get_dupont_analysis()         # get_extended_dupont_analysis
companies.models.get_enterprise_value_breakdown()             # get_tobins_q_ratio
companies.models.get_weighted_average_cost_of_capital(standardize=True, show_full_results=True)
companies.models.get_weighted_average_cost_of_capital(growth=True, lag=[1, 2, 3])
companies.models.get_economic_value_added()    # get_market_value_added
companies.models.get_intrinsic_valuation(0.05, 0.025, 0.094)   # 3 POSITIONAL args — see Risk #1
companies.models.get_gordon_growth_model()     # get_two_stage_dividend_discount_model
companies.models.get_residual_income()         # get_free_cash_flow_to_firm, get_free_cash_flow_to_equity
companies.models.get_graham_number()
companies.models.get_sustainable_growth_rate() # get_internal_growth_rate
companies.models.get_present_value_of_growth_opportunities()

# Scores return a 3-level MultiIndex (ticker, metric name, period) — the
# middle level is the *display* name, not a snake_case key:
companies.models.get_piotroski_score().loc[:, "Piotroski Score", :]
companies.models.get_altman_z_score().loc["RELIANCE.NS"]
```
⚠️ `get_intrinsic_valuation(0.05, 0.025, 0.094)` is three bare positional floats (risk-free rate, growth rate, cost of equity by position) with no keyword names in the docs. **Read the signature in the installed source before calling it** — passing a US-Treasury rate here silently produces a wrong fair value.

**`technicals` — breadth family is genuinely NEW for FinEngine** (signatures per Context7, `examples/Finance Toolkit - 6. Technicals Module.ipynb`):
```python
# NEW (FinEngine has no equivalent)
companies.technicals.collect_breadth_indicators()      # all breadth at once
companies.technicals.get_mcclellan_oscillator()
companies.technicals.get_advancers_decliners()
companies.technicals.get_new_highs_new_lows(window=60)
companies.technicals.get_trin()                       # Arms Index

# OVERLAPS stockstats — do not adopt
companies.technicals.get_bollinger_bands()
companies.technicals.get_relative_strength_index()
companies.technicals.get_moving_average_convergence_divergence()
companies.technicals.collect_all_indicators()          # 59 indicators in one call
```
✅ **Context7 confirms breadth is cross-sectional, not per-ticker** — this validates the design fit: *"Breadth indicators in the Finance Toolkit differ from other technical categories because they are computed **cross-sectionally across all tickers in the instance** rather than per ticker over time."* FinEngine already builds the multi-ticker price matrix, so this is a near-drop-in.

**`ratios` — 90+ audited methods, ADOPT for the financial-statement ratios FinEngine lacks:**
```python
companies.ratios.get_return_on_invested_capital()   # vs FinEngine's bfinance `roce`
companies.ratios.get_effective_tax_rate()
companies.ratios.get_cash_conversion_cycle()       # get_days_of_sales_outstanding, get_operating_cycle
companies.ratios.get_net_debt_to_ebitda_ratio()    # get_gross_debt_to_ebitda_ratio
companies.ratios.collect_solvency_ratios()
companies.ratios.collect_profitability_ratios()
companies.ratios.collect_all_ratios()
```

🔴 **Two `ratios` methods require a PAID FMP Premium subscription** (verified via Context7, `examples/Finance Toolkit - 3. Ratios Module.ipynb`) — analyst-consensus estimates are not on the free tier:
```python
companies.ratios.get_forward_price_earnings_ratio()        # ◄── Premium FMP only
companies.ratios.get_forward_price_earnings_growth_ratio() # ◄── Premium FMP only
```
Backed by `ratios_controller._get_or_fetch_analyst_estimates`. **Excluded from the adoption scope.**

**`Economics` (standalone) — macro series, NEW for FinEngine, ✅ India confirmed:**
```python
from financetoolkit import Economics

economics = Economics(start_date="2015-01-01")
economics.get_government_expenditure(countries=["Japan", "China", "India"])  # -> column "India"
economics.get_consumer_confidence_index().loc[:, ["United States", "China", "Germany"]]
economics.get_long_term_interest_rate(period="quarterly")
economics.get_gross_domestic_product(inflation_adjusted=True)
economics.get_inflation_rate()
```
- **60+ countries, 50+ indicators**, five categories: Government, Economy, Finance, Environment, Jobs & Society. 73 public methods in `economics_controller.py`.
- ✅ **India is explicitly demonstrated in the official docstring** (`economics.get_government_expenditure(countries=['Japan','China','India'])` returns an `India` column). Backed by **OECD + IMF Global Macro Database** (`oecd_model.py`, `gmdb_model.py`) — neither mentions India in source, so the country list lives in the controller's docstrings/OECD calls.
- ✅ **No FRED key needed for India.** `economics_controller._require_fred_api_key` gates only the **US-specific** FRED series (`get_nonfarm_payrolls`, `get_initial_jobless_claims`, `get_mortgage_rate_30_year`, …). `Toolkit(fred_api_key=…)` / `$FRED_API_KEY` are irrelevant unless those are called.
- Also available: `get_sovereign_debt_crisis()`, `get_currency_crisis()`, `get_banking_crisis()`, `get_yield_curve_slope()`, `get_recession_indicator()` — crisis-gating logic FinEngine has no equivalent of.

**`FixedIncome` (standalone)** — ICE BofA effective yield by credit rating. US/European credit only; **not relevant to an INR corporate book.** Skip.

**`risk` — 50 methods. Do NOT adopt, but note the one genuinely-new capability** (signatures per Context7, `examples/Finance Toolkit - 7. Risk Module.ipynb`):
```python
companies.risk.get_value_at_risk(period="monthly", rolling=12)
#   distribution: 'historical' | 'gaussian' | 'student-t' | 'cornish-fisher' | 'evt'
companies.risk.get_conditional_value_at_risk(period="quarterly")
companies.risk.get_maximum_drawdown(period="quarterly")
companies.risk.get_tail_ratio(period="yearly")
```
`distribution="evt"` (Extreme Value Theory / GPD tail fit) is the one thing `tail_risk_service.py` does not have. If EVaR/EVT is ever wanted, lift `var_model.fit_gpd_tail` logic rather than the whole module.

**Cross-cutting arguments (documented in README) — worth knowing, orthogonal to adoption:**
- `rolling=<n>` / `trailing=<n>` on most `get_`/`collect_` methods
- `growth=True, lag=4` for YoY; `trailing=4, growth=True` = TTM
- `standardize=True` → z-score vs own history (useful for FinEngine's screener ranking)

**✅ The offline seam is officially supported, not a hack.** Context7, `examples/Finance Toolkit - Using External Datasets.ipynb`:
> "The Finance Toolkit is designed to be **data-agnostic**, allowing users to import datasets from **any provider, including Intrinio, OpenBB, Yahoo Finance, and Quandl**."

```python
companies = Toolkit(
    tickers=["RELIANCE.NS"],
    balance=balance_sheets, income=income_statements, cash=cash_flow_statements,
    historical=price_frame,          # ◄── FinEngine's cached OHLCV
    format_location="normalization", # your mapped labels live here
    reverse_dates=False,             # ◄── MUST be chronological left-to-right
    api_key="", enforce_source="YahooFinance",
)
Toolkit("RELIANCE.NS").get_normalization_files()   # emit templates to fill in
```
Normalization CSVs map *your* line-item labels (column A) to the toolkit's internal names (column B); **column B must not be edited.** This is the officially-sanctioned way to hand FinEngine's own SQLite-cached statements to the toolkit with zero network calls.

### Overlap with FinEngine

| FinEngine file / function | FinanceToolkit replacement | Effort | Risk |
|---|---|---|---|
| `services/company_data_service.py:196-205` — `return_on_equity`, `return_on_capital_employed`, `debt_to_equity` (via bfinance `r.roe`/`r.roce`) | `ratios.get_return_on_equity()`, `get_return_on_invested_capital()`, `get_debt_to_equity_ratio()` | **M** | **Med** — bfinance is India-aware and already house-contracted (`market_cap` in ₹, documented at `company_data_service.py:183-186`). Do **not** swap. Use toolkit only for ratios bfinance lacks (cash-conversion-cycle, effective-tax-rate, net-debt/EBITDA). |
| `services/company_data_service.py:201-203` — `piotroski_score`, `graham_number`, `enterprise_value` via `getattr(yf.Ticker, ...)` | `models.get_piotroski_score()`, `get_graham_number()`, `get_enterprise_value_breakdown()` | **S** | **Med** — yfinance's versions are vendor-computed black boxes; the toolkit's are auditable Python. Strong argument to switch *because* transparency is the library's whole thesis. Verify numerically on ~20 Indian names first. |
| *(nothing — FinEngine has no distress/screen model)* | `models.get_altman_z_score()`, `get_beneish_m_score()`, `get_ohlson_o_score()`, `get_zmijewski_score()`, `get_springate_score()`, `get_grover_score()`, `get_fulmer_h_score()` | **M** | **Low** — pure new capability. ⚠️ These are calibrated on US historical datasets; on Indian mid-caps treat scores as **relative** (cross-sectional ranking) not absolute (probability of distress). |
| *(nothing)* | `models.get_dupont_analysis()`, `get_extended_dupont_analysis()` | **S** | **Low** |
| *(nothing)* | `models.get_weighted_average_cost_of_capital()`, `get_economic_value_added()`, `get_market_value_added()`, `get_tobins_q_ratio()` | **M** | **Low** — needs an INR risk-free rate input FinEngine must supply itself. |
| *(nothing)* | `models.get_intrinsic_valuation()`, `get_gordon_growth_model()`, `get_two_stage_dividend_discount_model()`, `get_residual_income()` | **L** | **Med** — needs a defensible cost-of-equity for India (Damodaran ERP, not US MRP). |
| `services/indicators_service.py:34-53` — `SUPPORTED_INDICATORS` (13 indicators: `close_10_ema`, `close_50_sma`, `close_200_sma`, `macd`, `macds`, `macdh`, `rsi`, `boll`, `boll_ub`, `boll_lb`, `atr`, `vwma`, `mfi`) | `technicals.*` (59 indicators) | **M** | **High** — **KEEP stockstats.** FinEngine's service already has non-obvious house contracts: the `mfi × 100` scale fix (`indicators_service.py:154-159`), row-count validation (`:136-137`), and NaN-masking of rows with invalid inputs (`:160-176`). Reimplementing all that per-indicator is regression-prone. `stockstats` alone exposes ~150 indicators for free. |
| *(nothing — market breadth)* | `technicals.get_advancers_decliners()`, `get_new_highs_new_lows()`, `get_mcclellan_oscillator()`, `breadth_model.py` | **S** | **Low** — genuinely new; needs a multi-ticker price matrix which FinEngine already builds. |
| `services/optimization_service.py:53` — `STRATEGIES = ("hrp", "min_vol", "max_sharpe", "min_cvar", "black_litterman")`, `_max_sharpe()`, `_min_cvar()` (Rockafellar-Uryasev LP), `_black_litterman()` | `portfolio` module (`Portfolio` class + `config.yaml`) | **L** | **High** — FinEngine's version is purpose-built for INR, cvxpy constraints and Indian calendars. **DO NOT REPLACE.** |
| `services/analytics_engine.py:1053` `quantstats_ratio_statistics()`, `:1155` `market_model_statistics()`, `:1190` `engine_risk_statistics()` | `performance.get_sharpe_ratio()`, `get_sortino_ratio()`, `get_capital_asset_pricing_model()`, `get_alpha()`, `get_beta()`, `get_fama_and_french_model()` | **L** | **High** — FinEngine's engine does **bootstrap CIs and moving-block uncertainty** (`measure_estimate_uncertainty`, `moving_block_size`, `autocorrelation_disclosure`) around these statistics. The toolkit returns point estimates only. Replacing would be a strict regression. |
| `services/tail_risk_service.py` (500 lines) | `risk.get_value_at_risk()`, `get_conditional_value_at_risk()`, `get_entropic_value_at_risk()`, `get_tail_ratio()`, `get_cvar_model` | **L** | **High** — the toolkit's `var_model.py` also ships EVaR, GPD tail fitting and VaR backtesting, which is attractive, but FinEngine's service is presumably INR/percentile-convention locked. Verify before touching. |
| `services/volatility_service.py:256-259` — GARCH/EGARCH params (`omega`, `beta[1]`, `persistence`) via `arch` 8.0.0 | `risk.get_garch()`, `get_garch_forecast()`, `get_garch_parameters()`, `get_gjr_garch()`, `get_egarch()` | **M** | **Med** — FinEngine already uses `arch` directly (already-installed dep). The toolkit adds GJR-GARCH and forecast. Marginal gain; likely not worth a second GARCH implementation. |
| `services/screener_service.py:182` `run_screen()`, `:300` `run_custom_screen()` | `Discovery.get_stock_screener()` | **S** | **Blocked** — `Discovery` is **FMP-only, no Yahoo fallback**. Free tier excludes non-US exchanges entirely. **NOT USABLE for an India-first screener.** |
| *(nothing — macro)* | `economics` module (FRED / OECD / IMF GMDB, incl. India) | **S** | **Low** — new; useful for the `ai_context_service.py` macro dossier section. |
| `services/data_service.py:577` `fetch_historical_data()`, `:1048` `fetch_ohlcv_batch()` | *(do not replace)* — but **feed** the Toolkit via `Toolkit(historical=<df>)` | **S** | **None if done as a feed** — this is the intended integration and preserves FinEngine's caching, staleness guards (`assert_not_stale`) and provenance. |

### Implementation guide

**Step 1 — dependency (one line, appended to `backend/pyproject.toml` `dependencies = [...]`):**

```toml
    # Transparent fundamental scoring/valuation models (MIT). Runs on our
    # existing yfinance; MUST be constructed with enforce_source="YahooFinance"
    # so it never falls back to FinancialModelingPrep (US-only free tier).
    "financetoolkit>=2.2,<3",
```

Then, per `AGENTS.md`: `uv sync --extra dev --group dev`. Expected new installs: **0** (pyyaml 6.0.3 already resolved).

**Step 2 — files to touch (create new, do not modify existing services):**

| Action | File | Note |
|---|---|---|
| **create** | `backend/app/services/scoring_models_service.py` | New `ScoringModelsService` — the single adapter boundary |
| **create** | `backend/app/services/financetoolkit_client.py` | Process-level `Toolkit` singleton + `lru_cache`d accessor |
| **create** | `backend/tests/test_scoring_models_service.py` | Regression tests per `AGENTS.md` ("prefer permanent unit tests over throwaway debug scripts") |
| **modify (small)** | `backend/app/api/equity_research.py` | Add the new score fields to the existing response schema |
| **KEEP UNTOUCHED** | `indicators_service.py`, `optimization_service.py`, `analytics_engine.py`, `tail_risk_service.py`, `volatility_service.py`, `screener_service.py` | All overlap — see Risk & caveats |

**Step 3 — migration order (each step independently shippable and revertible):**

1. **Spike + numeric parity, no production wiring.** Instantiate `Toolkit(enforce_source="YahooFinance")` against 20 liquid NSE names. Compare every `models.*` output against yfinance's `piotroski_score` / `graham_number` / `enterprise_value` for the 3 that already exist. Record divergences. **Gate: if Altman/Piotroski come back all-NaN for Indian tickers (no yfinance statements), STOP — the whole `models` module is unusable and the library adds nothing.**
2. **Emit and fill the normalization files.** `Toolkit("RELIANCE.NS").get_normalization_files()` → write your own line-item labels into column A of `format_location`, leaving column B untouched. This is the officially documented mechanism for data-agnostic input ("any provider, including Intrinio, OpenBB, Yahoo Finance, and Quandl") and it is what makes step 3 network-free.
3. **Wire the singleton client** with `FINANCE_TOOLKIT_CACHE_DB` set to a path inside FinEngine's data dir, and pre-supplied `historical=`/`income=`/`balance=`/`cash=` frames from `data_service.py` so nothing hits the network on the hot path.
4. **Ship `models` scores** into `equity_research_service.py`'s existing `custom_ratios` block (it already has a `"piotroski_score"` key at `equity_research_service.py:54-55` and `:240` — replace the source, keep the key, so the API contract is unchanged).
5. **Then** `Economics` (standalone class; India confirmed, no FRED key) and `technicals` breadth.
6. **Never** wire `risk`, `performance`, `portfolio`, `Discovery`, `ratios.get_forward_*` (Premium FMP), or `FixedIncome`.

**Keep vs replace, explicitly:**

| Keep FinEngine's | Replace with FinanceToolkit |
|---|---|
| `optimization_service.py` (entire) | `models.get_altman_z_score`, `get_piotroski_score`, `get_beneish_m_score`, `get_ohlson_o_score`, `get_zmijewski_score`, `get_springate_score`, `get_grover_score`, `get_fulmer_h_score` |
| `analytics_engine.py` (entire) | `models.get_dupont_analysis`, `get_extended_dupont_analysis` |
| `tail_risk_service.py` | `models.get_wacc`, `get_economic_value_added`, `get_market_value_added`, `get_tobins_q_ratio` |
| `volatility_service.py` (uses `arch`) | `models.get_intrinsic_valuation`, `get_gordon_growth_model`, `get_two_stage_dividend_discount_model`, `get_residual_income` |
| `indicators_service.py` (uses `stockstats`) | `ratios.get_cash_conversion_cycle`, `get_effective_tax_rate`, `get_net_debt_to_ebitda_ratio`, `get_operating_cycle`, … |
| `screener_service.py` (India universe) | `technicals.get_advancers_decliners`, `get_new_highs_new_lows`, `get_mcclellan_oscillator`, `get_trin` |
| `company_data_service.py` bfinance block | `Economics(...)` standalone — OECD/GMDB India series (no FRED key) |
| `analytics_engine.py` crisis gating | `Economics.get_sovereign_debt_crisis()`, `get_currency_crisis()`, `get_banking_crisis()` |

**Rewritten code example — the adapter, showing all four safety rails:**

```python
# backend/app/services/financetoolkit_client.py
"""Process-level FinanceToolkit singleton.

Why a module-level singleton and not a per-request Toolkit:
`financetoolkit.cache.cache_controller` keeps a process-global `_ACTIVE_CACHE`
published via `set_active_cache()`. Constructing a Toolkit per request inside
FastAPI would have every worker fight over that one global cache.

Why enforce_source is pinned here and never a parameter: the library defaults
to FinancialModelingPrep whenever an API key is present, and the FMP free tier
covers **US exchanges only** — an Indian portfolio would silently come back
empty. The keyword is set in exactly one place so it cannot be forgotten.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from threading import Lock

import pandas as pd

logger = logging.getLogger(__name__)

# Match FinEngine's SQLite home so the toolkit's cache lives with the rest of
# the app instead of roaming into %APPDATA% inside a container.
os.environ.setdefault(
    "FINANCE_TOOLKIT_CACHE_DB",
    str(Path(__file__).resolve().parents[2] / "data" / "financetoolkit_cache.db"),
)

_LOCK = Lock()


@lru_cache(maxsize=32)
def _toolkit_for(tickers: tuple[str, ...], start_date: str) -> "Toolkit":
    from financetoolkit import Toolkit

    return Toolkit(
        list(tickers),
        api_key="",                      # never let an env FMP key leak in
        enforce_source="YahooFinance",   # hard pin — see module docstring
        benchmark_ticker=None,           # "SPY" is meaningless for an INR book
        risk_free_rate="10y",            # ⚠️ still US Treasury; pass INR rf explicitly to models
        start_date=start_date,
        use_cached_data=True,
        convert_currency=False,          # don't depend on an FMP plan tier
        progress_bar=False,
    )


async def get_toolkit(tickers: list[str], start_date: str = "2019-01-01") -> "Toolkit":
    """Return a cached Toolkit, or None when the library cannot serve the request."""
    try:
        with _LOCK:
            return _toolkit_for(tuple(sorted(set(tickers))), start_date)
    except Exception as exc:                       # noqa: BLE001 - boundary
        logger.warning("financetoolkit unavailable for %s: %s", tickers, type(exc).__name__)
        return None
```

```python
# backend/app/services/scoring_models_service.py
"""Fundamental scoring/valuation models.

Every method returns a plain dict of floats-or-None and NEVER raises on missing
data: a missing statement for an Indian small-cap must degrade the response, not
fail the request. Callers treat `None` as "not computable" and must not coerce
it to 0 (that would silently rank a data-less company as the worst in the
universe, which is exactly the failure mode a distress screen must not have).
"""
from __future__ import annotations

from typing import Any

SCORING_METHODS = (
    "get_altman_z_score",
    "get_piotroski_score",
    "get_beneish_m_score",
    "get_ohlson_o_score",
    "get_zmijewski_score",
    "get_springate_score",
    "get_grover_score",
    "get_fulmer_h_score",
    "get_dupont_analysis",
)

# get_piotroski_score() returns a 3-level MultiIndex whose MIDDLE level is the
# display name ("Piotroski Score"), not the snake_case method name. Map method ->
# middle-level label so `.loc` addressing is correct.
SCORE_LABELS = {
    "get_piotroski_score": "Piotroski Score",
    # ... verify each label against the installed version before shipping
}


class ScoringModelsService:
    def __init__(self, toolkit):          # injected; never constructed per request
        self._toolkit = toolkit

    async def scores(self) -> dict[str, Any]:
        if self._toolkit is None:
            return {m: None for m in SCORING_METHODS}
        out: dict[str, Any] = {}
        for name in SCORING_METHODS:
            try:
                frame = getattr(self._toolkit.models, name)()
            except Exception as exc:      # noqa: BLE001
                out[name] = None
                continue
            out[name] = None if frame is None or frame.empty else _first_row(frame)
        return out
```

**Do NOT write this (the trap):**

```python
# ❌ WRONG — FMP-first default; an FMP key in the environment silently sends the
#    request to a US-only free tier and Indian rows come back empty.
companies = Toolkit(tickers=["RELIANCE.NS"], api_key=os.environ["FMP_KEY"])

# ❌ WRONG — "SPY" benchmark on an INR book produces a meaningless beta/alpha
#    and then the result gets published as if it were real.
companies = Toolkit(tickers=["RELIANCE.NS"])   # benchmark_ticker defaults to "SPY"

# ❌ WRONG — computing the model on stale cached prices. FinEngine already
#    refuses this in assert_not_stale(); don't route around it.
prices = await data_service.fetch_historical_data(ticker, end_date="2024-01-01")
sc = Toolkit(["RELIANCE.NS"]).models.get_altman_z_score()   # ignores `prices`
```

### Risk & caveats

1. **🔴 US-Treasury risk-free rate is baked in.** `risk_free_rate` defaults to `"10y"` = **US** Treasury yield, and `risk_free_rate="10y"` is also the default in `FinanceFrame.to_toolkit()`. For an INR book this must be replaced with a G-sec 10Y (~6.5-7% in 2026, not ~4%). Any toolkit metric that consumes it (excess return, WACC, CAPM, DDM) is wrong by default. This is the highest-consequence silent-wrongness risk in the whole library.
2. **🔴 `enforce_source` must be pinned, always.** If an `FINANCIAL_MODELING_PREP_API_KEY` exists anywhere in the environment, the library tries FMP first. FMP's free tier is US-exchange-only, so Indian tickers silently return empty frames rather than raising. A bare `except` then produces a plausible-looking all-`None` response.
3. **🟠 US-calibrated scoring models.** Altman Z, Ohlson O, Zmijewski, Springate, Grover and Fulmer were fitted on US historical samples. On Indian mid-caps their **absolute** values are not comparable to published thresholds — use them for **cross-sectional ranking only**, and say so in the API response (a `"basis": "cross_sectional_rank_only"` field, the way FinEngine already annotates `expected_sharpe_was_the_optimised_objective` in `optimization_service.py:350-362`).
4. **🔴 `ratios.get_forward_price_earnings_ratio()` / `get_forward_price_earnings_growth_ratio()` need a PAID FMP Premium subscription.** Verified via Context7 (`examples/Finance Toolkit - 3. Ratios Module.ipynb`: *"requiring a Premium FMP subscription"*), backed by `ratios_controller._get_or_fetch_analyst_estimates`. These are the **only** two methods in the adopt scope that introduce a hard paid/credentialed dependency. **Excluded from scope — do not call them, and do not surface forward-P/E in any FinEngine response sourced from the toolkit.**
5. **🟠 yfinance statement sparsity in India.** Large caps (RELIANCE, TCS, HDFCBANK) have statements; small/mid-caps frequently do not. Expect a high `None` rate. Do not impute.
5. **🟠 Process-global mutable cache.** `set_active_cache()` + `_CACHE_REGISTRY`. Fine with one singleton; a bug source with several. Also writes to `%APPDATA%` by default — set `FINANCE_TOOLKIT_CACHE_DB`.
6. **🟠 Sibling `curl_cffi`/`yfinance` rate limits are shared.** The toolkit calls the same Yahoo endpoints FinEngine's `data_service.py` does, from a second code path, with its own session. If both run in one process they can trip `YFRateLimitError` for each other. The toolkit catches that and returns an empty frame with a `"YFINANCE RATE LIMIT REACHED"` column — which would sail straight through as "no data". Prefer the pre-supplied-`historical=` seam so the toolkit makes zero network calls.
7. **🟡 Undeclared `scipy` import** in `risk/var_model.py` (informational — we're not adopting `risk`).
8. **🟡 Module size.** `toolkit_controller.py` is 222,684 bytes, `technicals_controller.py` 305,742, `economics_controller.py` 303,898, `performance_controller.py` 195,605. Import time and binary size are non-trivial for a FastAPI worker. Consider importing submodules rather than `from financetoolkit import Toolkit` at module top-level in the hot path.
9. **🟡 Maintainer affiliate link** on FMP subscriptions (disclosed in README). Not a defect; worth a line in any internal write-up so nobody assumes the FMP recommendation is neutral.
10. **🟢 No security/licensing red flags.** MIT, no `eval`, no network calls to non-FMP/Yahoo hosts, no telemetry found in the reviewed modules.

---

## FinanceDatabase

MIT-licensed, **actively maintained with weekly automated database refreshes**, and its Indian symbols use exactly the `.NS`/`.BO` suffixes yfinance expects — but the wheel is only 30 KB of code that downloads a 14.6 MB file at runtime and inflates it to a 187 MB DataFrame, and Indian ISIN coverage is 2.4%. **Vendor the data, don't take the package** — pull `equities.bz2` once as a seed step into FinEngine's SQLite, and never call `Equities()` on a request path.

### Verdict

**ADOPT_PARTIAL (data-only, offline; reject the runtime package)**

Adopt the *dataset* as a build-time seed for FinEngine's existing `backend/data/nse/` SQLite archive, and nothing else. Reject taking `financedatabase` as a runtime dependency: it is a 30 KB wheel that exists only to `requests.get` a 14.6 MB bz2 and materialise a 187 MB in-memory DataFrame, and it hard-depends on `financetoolkit>=2.0.3,<3.0.0` (which FinEngine does not otherwise need), pulling FMP-key logic into the process for no benefit. The decisive data point, measured from the actual file: **NSE coverage is 1,716 symbols versus BSE's 3,793, ISIN is filled for only 2.4% of Indian rows, and `industry` only 33%** — good enough to enrich an existing universe, not good enough to *be* the universe.

### License

- **License:** MIT
- **SPDX id:** `MIT`
- **Source:** [`pyproject.toml`](https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/pyproject.toml) → `license = {text = "MIT"}`; [`LICENSE`](https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/LICENSE); PyPI `info.license = "MIT"`.

> **NOTE:** the file is `LICENSE` (not `LICENSE.txt`) — `LICENSE.txt` 404s. FinanceToolkit uses `LICENSE.txt`. Easy to get wrong when vendoring.

Clause (verbatim, `LICENSE`):

> ```
> MIT License
> Copyright (c) 2023 Jeroen Bouma
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
> ```

**Commercial impact:** None. Permissive, no copyleft, no data-use restriction in the license.

⚠️ **The license does NOT cover the data.** MIT covers the code. The 112,707-row symbol table is compiled by the maintainer from community contributions and upstream vendor data (Bloomberg FIGI, CUSIP, ISIN fields are visibly vendor-derived). The project solicits contributions under the same MIT, and a `CONTRIBUTING.md` exists, but the repo makes no explicit statement about the *provenance/redistribution rights* of the underlying Bloomberg identifiers. For an **internal** Indian analytics platform this is a non-issue. **If FinEngine ever ships a commercial product that redistributes this table to customers, get provenance clarification first** — `UNVERIFIED — needs manual check` (raise with the maintainer or read `CONTRIBUTING.md` in full).

**Linking vs vendoring:** If you vendor the `.bz2` into `backend/data/nse/`, keep the MIT notice in a `LICENSE.financedatabase` file next to it and record the source URL + the commit SHA you pulled. This is a *data* vendoring, which is the recommended shape here.

### Maintenance

**ACTIVE** — and uniquely, the *data* is maintained on a machine cadence.

| Signal | Observed value | Source |
|---|---|---|
| Latest release | **v2.4.0**, published **2026-06-02T14:05:45Z** | [PyPI JSON](https://pypi.org/pypi/financedatabase/json) |
| Last commit to `main` | **2026-09-20** (`d0b95bd` "Update README statistics") | [commits page](https://github.com/JerBouma/FinanceDatabase/commits/main) |
| Data refresh cadence | **Weekly**, automated by `actions-user` — `Update database with new tickers` + `Update Compression Files` seen on **Sep 20, Sep 13, Sep 11, Sep 6, Aug 30, Aug 25, Aug 16, Sep 9, Aug 7** 2026 | commits page |
| Open issues / PRs | **2 open issues, 3 open PRs** | [repo page](https://github.com/JerBouma/FinanceDatabase) |
| Stars / forks | 9,400 / 968 | repo page |
| Total releases | 35 | PyPI JSON |
| Archived | `false` | repo page |

Maintenance is arguably *better* than FinanceToolkit's for our purpose: the data is regenerated weekly by a bot, so a vendored copy is at most 7 days stale, and the diff is reviewable (`git log` on the `compression/` folder shows only data changes).

### Compatibility

| Requirement | Status | Evidence |
|---|---|---|
| Python 3.12 | ✅ Supported | `requires-python = ">=3.10, <3.16"`; classifiers 3.10–3.14 |
| pandas 3.0 | ✅ | Declares **no** pandas pin itself, but hard-depends on `financetoolkit>=2.0.3` which requires `pandas>=3.0` |
| numpy 2.x | ✅ | Transitive via pandas 3 / scikit-learn |
| Compiled extensions | ❌ None | `financedatabase-2.4.0-py3-none-any.whl`, **0.03 MB** |

**No blocker.** Verified locally: the file parses cleanly under **pandas 3.0.6** with the library's own `read_csv` arguments (`compression="bz2", index_col=0, keep_default_na=False, na_values=[""]`) — see the measurement output below.

### Data dependency chain

```
import financedatabase as fd
        │
        └─ fd.Equities()   -> FinanceDatabase.__init__(base_url=DATA_REPO)
                 │
                 │  DATA_REPO = "https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/compression/"
                 │  FILE_NAME = "equities.bz2"
                 │
                 └─ requests.get(the_path, headers=<browser UA>, timeout=60)     # ◄── NETWORK, EVERY TIME
                        └─ pd.read_csv(BytesIO(response.content), compression="bz2", index_col=0, ...)
```

**API keys required: NONE.** This is a pure static-file download from GitHub raw. No registration, no vendor account.

**Free tier: N/A** — the entire dataset is free and unauthenticated. Cost of access is GitHub raw bandwidth only.

**Rate limits:** None published. Practical limits are GitHub raw's anonymous bandwidth/abuse policy and the 60 s client timeout. The library ships no ETag / `If-Modified-Since` / local memoisation — **every `Equities()` re-downloads all 14.6 MB.** In a FastAPI process with a per-request or per-session construction, that is a guaranteed self-inflicted DoS. `use_local_location=True` switches to reading from a `compression/` directory next to the installed package — the intended offline path, and the basis of the recommendation below.

**Bundled asset database size — measured, not estimated:**

| Asset class | File | On-disk (bz2) | Rows (README) |
|---|---|---|---|
| Equities | `equities.bz2` | **14.58 MB** (15,289,215 B) | **112,707** |
| Funds | `funds.bz2` | 1.77 MB | 57,853 |
| Indices | `indices.bz2` | 1.13 MB | 91,181 |
| ETFs | `etfs.bz2` | 1.22 MB | 36,481 |
| Currencies | `currencies.bz2` | 0.04 MB | 2,556 |
| Cryptos | `cryptos.bz2` | 0.03 MB | 3,367 |
| Money Markets | `moneymarkets.bz2` | 0.02 MB | 1,367 |

Measured by HEAD requests against `raw.githubusercontent.com`. **Note the `README` "300.000+ symbols" claim = the sum across asset classes, not equities.** Equities alone is 112,707.

⚠️ **Repo `size` field is misleading.** The GitHub API reports the repo at ~304 MB. That is git history of weekly 15 MB bz2 blobs, **not** the working set. Vendoring one `equities.bz2` costs 14.58 MB.

**⚠️ In-memory cost — the real number:** parsing `equities.bz2` yields a `(112707, 21)` DataFrame consuming **187.0 MB** (`memory_usage(deep=True)`). Every request that touches a screener pays that. For a FastAPI service already running pandas 3 + cvxpy + arch + hmmlearn, a 187 MB resident table is a real memory-budget line item.

**Indian market support — MEASURED by downloading and parsing the file** (not read from the README):

```
SHAPE (112707, 21)   INDEX NAME: symbol
COLUMNS: name, summary, currency, sector, industry_group, industry, exchange,
         mic, market, country, state, city, zipcode, website, market_cap,
         isin, cusip, figi, composite_figi, shareclass_figi, delisted

=== INDIA EQUITIES: 5,680 ===
exchanges: BSE 3793 | NSE 1691 | STU 25 | NSI 25 | FRA 23 | BER 23 | MUN 18 |
           DUS 13 | NYQ 11 | PNK 9 | IOB 8 | LSE 6 | MEX 5 | NMS 5 | VIE 4 |
           HAN 3 | HAM 3 | AMS 3 | SAO 2 | BUE 2 | SGO 2 | NCM 2 | CCS 1 | SES 1 | PCX 1 | ASE 1
markets:   'BSE India', 'National Stock Exchange of India', ...
mic:       'XBOM' (BSE), 'XNSE' (NSE)   ◄── correct ISO 10383 codes
currencies: {'INR': 5482, 'EUR': 114, 'USD': 39, 'MXN': 5, 'GBP': 4, 'BRL': 2, 'ARS': 2, 'CLP': 2, 'SGD': 1}
market_cap: {'Nano Cap': 2822, 'Micro Cap': 992, 'Small Cap': 699, 'Mid Cap': 295, 'Large Cap': 166, 'Mega Cap': 2}
sectors:    Industrials 1108 | Materials 968 | Consumer Discretionary 752 | Financials 730 |
            Consumer Staples 419 | IT 370 | Health Care 305 | Real Estate 201 |
            Communication Services 149 | Energy 101 | Utilities 67
delisted:   {False: 5575, True: 105}
```

**✅ YES, India is covered — and the symbol format is the standout result:**

```
endswith .NS:  1,716        ◄── NSE, exactly yfinance's convention
endswith .BO:  3,793        ◄── BSE, exactly yfinance's convention
distinct company names: 4,059
companies on both NSE and BSE: 1,508   (NSE-only 208, BSE-only 2,285)
samples: 20MICRONS.NS | 3IINFOTECH.NS | A2ZINFRA.NS | AAKASH.NS | AARON.NS | AARTIDRUGS.NS
         543282.BO   | 7TEC.BO      | 21STCENMGM.BO
```

`.NS` / `.BO` match FinEngine's house ticker convention and its AGENTS.md regex (alphanumeric scrip codes `543282.BO`, `7TEC.BO` included) **exactly**. This is the single strongest argument for adoption.

**🔴 Three quality problems that must gate any adoption:**

1. **NSE/BSE asymmetry.** NSE gets 1,716 symbols, BSE gets 3,793, and only 1,508 companies appear on both. Real NSE lists ~2,600 companies. So **NSE coverage is partial and the BSE set is not a superset of it** — a company present only as `.BO` will 404 on a `.NS` yfinance fetch. You cannot treat this as "the Indian universe"; it is a partial, asymmetric enrichment.
2. **ISIN is unusable as a join key for India.** Fill rate measured: **`isin` 2.4%** (137/5,680) vs **27.0% globally**. `cusip` 2.1%. `figi` 15.2%. Any dedup/join on ISIN will silently drop ~97% of Indian rows.
3. **`industry` is only 33% filled for India** (1,874/5,680) vs 64.5% globally, though `sector` (91.0%) and `industry_group` (90.8%) are fine. So 3-level GICS drill-down is unreliable below `industry_group` for Indian names.

Field-by-field India fill rate: `summary` 91.7% · `sector` 91.0% · `industry_group` 90.8% · `market_cap` 87.6% · `city` 33.6% · `industry` 33.0% · `website` 32.0% · `figi` 15.2% · `isin` 2.4% · `state` 0.7%.

Global context: **117 countries, 84 exchanges**; India is the 5th largest by row count (US 29,998 · Canada 10,743 · China 6,961 · Japan 5,862 · **India 5,680**).

**Offline / vendoring feasibility — EXCELLENT, and this is the recommended shape:**
- The data is a **static bz2 CSV** at a stable raw.githubusercontent.com URL on `main`. Pin to a commit SHA rather than `main` for reproducibility.
- `pd.read_csv(path, compression="bz2", index_col=0, keep_default_na=False, na_values=[""])` is the only read path — 3 lines, no dependency on the package at all.
- This maps **directly** onto FinEngine's existing `backend/data/nse/` archive pattern (directory exists, currently empty; `backend/data/daisy.db` is the 16 MB SQLite with `backups/` alongside).
- **Alembic-style seed, not a runtime call.** Add a script that downloads → verifies shape/checksum → writes the India subset into a SQLite table (`ticker`, `name`, `sector`, `industry_group`, `industry`, `market_cap`, `mic`, `delisted`) → records `source_sha` and `fetched_at` for provenance. 5,680 rows is ~1 MB in SQLite, versus 187 MB in a pandas DataFrame.
- ⚠️ Re-run weekly to match upstream's cadence; FinEngine should treat a stale seed as a health-check failure, not silently serve week-old universe data.

### Dependency footprint

**Direct dependencies** (PyPI `requires_dist`):

| Package | Constraint | FinEngine status | Conflict risk |
|---|---|---|---|
| `financetoolkit` | `>=2.0.3,<3.0.0` | not installed | **🔴 HIGH — the whole point.** Taking this package forces FinanceToolkit (and its `pyyaml`, `scikit-learn`, `openpyxl`, `yfinance` chain) into FinEngine for zero runtime benefit. |
| `pandas` | *undeclared* (via financetoolkit → `pandas>=3.0`) | 3.0.6 ✅ | Low |
| `requests` | *undeclared* (in `helpers.py`) | 2.34.2 ✅ | Low |
| `numpy` | *undeclared* | 2.5.3 ✅ | Low |

**This is the decisive argument against the package.** `financedatabase`'s only job is `requests.get` + `pd.read_csv`. The entire value is 14.58 MB of data. Taking a hard dependency on a whole quant toolkit to read a CSV is the wrong trade.

**Net new installs if you take the package:** `financetoolkit` + `pyyaml` (already resolved) + `linearmodels` (if you pull the `econometrics` extra — don't). **Net new installs if you vendor the data: zero, forever.**

### API surface

```python
import financedatabase as fd

equities = fd.Equities()                     # ◄── 14.58 MB download + 187 MB DataFrame, EVERY call
```

**`FinanceDatabase` (base, `helpers.py`) — signatures per Context7 `_autodocs/07-base-classes.md`:**
```python
FinanceDatabase.__init__(base_url: str = "https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/compression/",
                         use_local_location: bool = False)
search(self, **kwargs) -> FinanceFrame
    #   kwargs: <column>=<value>  (substring, case-insensitive by default)
    #   flags:  case_sensitive=False, only_primary_listing=False,
    #           index="\.F"  (substring match on the symbol column -> ".NS" works),
    #           exclude_delisted=True
    equities.search(index='.F')                       # ◄── -> equities.search(index='.NS') for NSE
    equities.search(summary=["Robotics", "Education"], industry_group="Equipment", market='Frankfurt')
    equities.search(name="Apple Inc.", case_sensitive=True)

show_options(selection: str | None = None, base_url: str = DATA_REPO,
             use_local_location: bool = False) -> dict
    #   FREE: does not load the big files. Raises ValueError if selection is None/invalid.
    fd.show_options('equities')      # -> {'currency': array([...]), 'sector': array([...]), ...}
```

✅ **`base_url` is a real constructor parameter** — this is the correct offline path, and better than relying on `use_local_location` alone (Context7, `_autodocs/09-configuration-and-initialization.md`):
```python
equities = fd.Equities(base_url="/path/to/compression/", use_local_location=True)
```
You can point it at FinEngine's own `backend/data/nse/` rather than the installed `site-packages/compression/`.

**Documented schema** (Context7, `_autodocs/08-types-and-data.md`):
```text
Equities.data columns:
- symbol: str              # Index
- name: str
- currency: str            # Trading currency
- sector: str              # GICS sector
- industry_group: str      # GICS industry group
- industry: str            # GICS industry
- exchange: str            # Exchange code
- mic: str                 # ISO 10383 MIC
- market: str              # Market name
- country: str             # ◄── HEADQUARTERS country, not listing venue
- state / city / zipcode: str        (nullable)
- website: str                        (nullable)
- market_cap: str          # Market cap category (a BUCKET, not a number)
- isin / cusip / figi / composite_figi / shareclass_figi: str   (nullable)
- delisted: bool
```
⚠️ **Doc/code drift:** the autodoc schema omits `summary`, but `summary` **is** a real column — I measured `(112707, 21)` and `equities.search(summary=[...])` is an official documented example. Treat the autodoc list as 20 of 21 columns.

⚠️ **`country` is documented as "Headquarters country"**, not the listing venue. That is why `country="India"` returns 5,680 rows spanning LSE/FRA/BER/MUN/NYQ/PNK listings (Vedanta, Azure Power, Yatra Online) alongside genuine `XNSE`/`XBOM` rows — and it is a *second* reason not to treat `country` as an exchange filter. Filter on `mic` or `exchange` instead.

**`Equities.select()` (signature from `financedatabase/Equities.py`):**
```python
equities.select(
    country: str | list | None = None,
    sector: str | list | None = None,
    industry_group: str | list | None = None,
    industry: str | list | None = None,
    currency: str | list | None = None,
    exchange: str | list | None = None,       # 'BSE' / 'NSE' / 'NSI'
    mic: str | list | None = None,             # 'XBOM' / 'XNSE'
    market: str | list | None = None,          # 'BSE India' / 'National Stock Exchange of India'
    market_cap: str | list | None = None,      # 'Nano Cap' … 'Mega Cap'
    only_primary_listing: bool = False,
    exclude_delisted: bool = True,
) -> FinanceFrame                             # subclass of pd.DataFrame
```

**`FinanceFrame.to_toolkit()`** — the integration bridge, **and a trap:**
```python
equities.select(country='Netherlands', industry='Insurance').to_toolkit(api_key=API_KEY)
toolkit = tech_companies.to_toolkit(api_key='YOUR_API_KEY')
historical = toolkit.get_historical_data()
ratios = toolkit.ratios.collect_all_ratios()
```
⚠️ Note the defaults inside it: `risk_free_rate="10y"` (US Treasury) and `benchmark_ticker="SPY"`. Same US-bias trap as FinanceToolkit. **FinEngine must not use this.**

✅ **Mitigating detail found via Context7** (`_autodocs/09-configuration-and-initialization.md`): the FinanceToolkit import is **lazy**, not module-level —
```python
# This requires FinanceToolkit:
toolkit = result.to_toolkit(api_key="YOUR_KEY")

# Error if not installed:
# ImportError: To use the 'to_toolkit' functionality, it requires installation of the FinanceToolkit
```
So a lean runtime (data only, never `to_toolkit`) is *technically* possible even though `pyproject.toml` declares `financetoolkit` as a hard dependency. **This weakens, but does not remove, risk #2** — `pip install financedatabase` still resolves and installs FinanceToolkit, and a leaner path is one more thing to get wrong. The vendored-bz2 approach sidesteps the question entirely.

**Sibling classes:** `fd.ETFs()`, `fd.Funds()`, `fd.Indices()`, `fd.Currencies()`, `fd.Cryptos()`, `fd.Moneymarkets()` — same `FinanceDatabase` base, own `.bz2`.

**What FinEngine actually needs (the three lines that matter):**
```python
import pandas as pd

INSTRUMENTS = pd.read_csv(
    "backend/data/nse/financedatabase_equities.bz2",   # vendored, pinned SHA
    compression="bz2", index_col=0,
    keep_default_na=False, na_values=[""],
)
india = INSTRUMENTS[INSTRUMENTS["country"] == "India"]      # 5,680 rows
nse = india[india["mic"] == "XNSE"]                         # 1,716 rows, symbols already ".NS"
```

### Overlap with FinEngine

| FinEngine file / function | FinanceDatabase replacement | Effort | Risk |
|---|---|---|---|
| `services/screener_service.py:65` `ScreenerService`, `:182` `run_screen()`, `:300` `run_custom_screen()` | `Equities.select(country='India', sector=..., market_cap=...)` | **M** | **Med** — do **not** swap the runtime. The screener already has a DB cache (`_db_cache_keys` at `:40`, `_get_cached_screen` at `:118`, `_set_cached_screen` at `:154`) and a `_universe_cache_token` (`:55`). Replacing with a 187 MB in-memory frame would nuke that. Instead: **seed** the universe table from this dataset once. |
| `services/data_service.py:1117` `validate_ticker()` — India ticker regex per AGENTS.md (`3MINDIA.NS`, `MOTHERSON.NS`, `BAJAJ-AUTO.NS`, `500112.BO`) | `Equities.search(index="\.NS")` as a *known-valid* universe list | **S** | **Low** — the dataset's `.NS`/`.BO` symbols validate identically against FinEngine's existing regex. A membership check is strictly stronger than a regex check. |
| *(nothing — no canonical symbol master)* | `isin` / `mic` / `market_cap` columns | **M** | **🔴 High as a join key** — ISIN is 2.4% filled for India. **Do not use ISIN.** Use `mic` (`XNSE`/`XBOM`, 100% filled) and `delisted` (100% filled) instead. |
| *(nothing — no sector/industry taxonomy)* | `sector` (91.0% India) + `industry_group` (90.8% India), GICS-standard | **S** | **Low** — reliable at those two levels. `industry` (33%) is **not** reliable; do not surface it for India without a fill-rate guard. |
| `services/company_data_service.py:186` — `market_cap` (absolute ₹, house contract documented at `:183-186`) | `market_cap` **bucket** column (`'Nano Cap'`…`'Mega Cap'`) | **S** | **Low** — bucket, not a number. Useful as a screener filter; must never overwrite the ₹ figure. Note the India distribution is skewed (2,822 of 5,680 are `'Nano Cap'`), so it is a weak liquidity proxy. |
| `services/equity_research_service.py:306` + `app/api/equity_res.py:235` | `Equities` `name`, `summary` (91.7% India), `website` (32.0%), `city` (33.6%) | **S** | **Low** — free-text enrichment for the AI dossier (`ai_context_service.py`); `summary` is the only field worth wiring. |
| *(nothing)* | `delisted` flag (105 Indian rows) | **S** | **Low** — genuinely useful. FinEngine should refuse to screen or price a delisted Indian scrip. |
| `services/data_service.py:475` `_get_full_cached_frame()`, `cache_service.py` | *(do not replace — see Risk #2)* | — | **None if done as a seed** |

### Implementation guide

**Recommendation: do NOT add `financedatabase` to `pyproject.toml`.** Vendor the data instead. Exact `pyproject.toml` change: **none** — which is the point.

**Step 1 — add a seed script (new file, no dependency added).**

```python
# backend/scripts/seed_instrument_universe.py
"""One-shot seed of the FinEngine instrument universe from FinanceDatabase data.

Why vendor instead of depending on `financedatabase`:
that package is a 30 KB wheel whose only job is `requests.get` a 14.6 MB bz2
from GitHub raw and materialise a 187 MB in-memory DataFrame on every
Equities() call. It also hard-depends on financetoolkit. Reading the same
bz2 directly is 3 lines of pandas and costs zero dependencies.

Upstream: https://github.com/JerBouma/FinanceDatabase  (MIT, JerBouma)
Pinned data SHA recorded in the DB so a rerun is auditable.

Run: uv run python backend/scripts/seed_instrument_universe.py
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Pin a commit SHA, not `main` — upstream rewrites compression/*.bz2 weekly.
DATA_URL = (
    "https://raw.githubusercontent.com/JerBouma/FinanceDatabase"
    "/main/compression/equities.bz2"
)
DATA_SHA256 = "REPLACE_WITH_PINNED_COMMIT_SHA_OR_FILE_SHA256"
ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "nse"
RAW = ARCHIVE / "financedatabase_equities.bz2"

# Columns worth persisting. Deliberately EXCLUDED: isin (2.4% filled for India
# -> useless as a join key), cusip, figi/composite_figi/shareclass_figi
# (vendor identifiers with unclear redistribution provenance), state (0.7%).
COLUMNS = [
    "name", "summary", "currency", "sector", "industry_group", "industry",
    "exchange", "mic", "market", "country", "market_cap", "website",
    "city", "delisted",
]

EXPECTED_ROWS = 112_707          # sanity gate; upstream grows this over time
EXPECTED_COLUMNS = 21


def main() -> int:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    RAW.parent.mkdir(parents=True, exist_ok=True)

    if not RAW.exists():
        import requests
        response = requests.get(DATA_URL, timeout=120)
        response.raise_for_status()
        RAW.write_bytes(response.content)

    digest = hashlib.sha256(RAW.read_bytes()).hexdigest()
    if digest != DATA_SHA256:
        print(f"checksum drift: {digest} != {DATA_SHA256}; re-pin before seeding",
              file=sys.stderr)
        return 1

    # Exactly financedatabase/helpers.py's read arguments — parity by construction.
    table = pd.read_csv(RAW, compression="bz2", index_col=0,
                        keep_default_na=False, na_values=[""])
    assert table.shape == (EXPECTED_ROWS, EXPECTED_COLUMNS), table.shape

    india = table[table["country"] == "India"][COLUMNS].copy()
    assert india["mic"].isin(["XNSE", "XBOM"]).sum() > 4_000, "India coverage collapsed"

    # Symbols already carry the .NS / .BO suffix yfinance expects — do not
    # transform them, and do not re-derive them from `name`.
    assert india.index.str.endswith((".NS", ".BO")).sum() > 5_000, "suffix convention changed"

    out = india.to_parquet(ARCHIVE / "instruments_india.parquet")
    print(f"wrote {out} rows={len(india)} "
          f"nse={int((india['mic'] == 'XNSE').sum())} bse={int((india['mic'] == 'XBOM').sum())} "
          f"fetched_at={datetime.now(timezone.utc).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 2 — load into SQLite at the existing Alembic migration boundary.** `backend/data/nse/` already exists (currently empty) and `backend/data/daisy.db` is the 16 MB SQLite with a `backups/` convention. Add one migration creating `instrument_universe` with the columns above plus `source_sha256` and `fetched_at`, then `INSERT … SELECT` from the parquet. 5,680 rows is ~1 MB.

**Step 3 — files to touch:**

| Action | File | Note |
|---|---|---|
| **create** | `backend/scripts/seed_instrument_universe.py` | The script above |
| **create** | `backend/alembic/versions/xxxx_seed_instrument_universe.py` | New migration |
| **create** | `backend/tests/test_instrument_universe.py` | Assert India count > 4,000, `.NS`/`.BO` suffix invariant, `delisted` present, `isin` **not** relied upon |
| **modify (tiny)** | `backend/pyproject.toml` | **Nothing.** Deliberately no new dependency. |
| **optional modify** | `backend/app/services/screener_service.py:55` `_universe_cache_token()` | Add the seed's `source_sha256` to the cache token so a data refresh invalidates screen caches |
| **KEEP UNTOUCHED** | `data_service.py`, `cache_service.py` | Existing caching stays authoritative for prices |

**Step 4 — migration order:**

1. Land the seed script + test **with no wiring**. Prove the row counts and suffix invariant.
2. Land the migration; run the seed. Verify `mic` distribution and `sector` fill rate in the DB.
3. Add `delisted` as a hard reject in `screener_service.run_screen()`.
4. Add `sector` / `industry_group` as *optional* screener filters, each guarded by a fill-rate check at query time (`India industry is 33% filled — never let a user filter on it silently`).
5. Wire `summary` into `ai_context_service.py`'s company dossier.
6. Add a weekly scheduled refresh + a staleness health check.

**Keep vs replace:** keep `screener_service.py`'s universe plumbing entirely; **replace only the ad-hoc NSE symbol list** (if one exists) with the seeded table, and only for validation/metadata, never for prices.

**Do NOT write this:**
```python
# ❌ WRONG — 14.58 MB download + 187 MB DataFrame on a request path,
#    plus a financetoolkit import, for a list FinEngine already caches.
@app.get("/api/screener")
async def screen(strategy: str):
    return fd.Equities().select(country="India", sector=sector).to_dict()
```

### Risk & caveats

1. **🔴 Never call `Equities()` on a request path.** 14.58 MB download + 187 MB resident DataFrame, every call, no memoisation, no ETag. This is a self-inflicted DoS in a FastAPI worker.
2. **🔴 The `financetoolkit` hard dependency is the wrong trade.** `financedatabase>=2.4.0` requires `financetoolkit>=2.0.3,<3.0.0`. Adopting it drags in a quant toolkit, an FMP code path, and a `pyyaml` import-time read — for a `read_csv`. (Context7 confirms the *import* is lazy — `ImportError: To use the 'to_toolkit' functionality, it requires installation of the FinanceToolkit` — so a lean install is possible, but `pip install financedatabase` still resolves it, and the vendored-bz2 route avoids the whole question.)
3. **🔴 ISIN is 2.4% filled for India.** Any dedup, cross-reference or corporate-action join keyed on `isin` will silently drop ~97% of Indian rows. **Use `mic` (XNSE/XBOM, 100% filled) instead.** Measured: 137/5,680.
4. **🔴 NSE coverage is partial and asymmetric.** 1,716 `.NS` vs 3,793 `.BO`, with only 1,508 companies on both. A `.BO`-only company has no `.NS` symbol — and FinEngine is `.NS`-first. Do not treat this as the universe of record.
5. **🟠 `industry` is 33% filled for India** (vs 64.5% globally). `sector` (91.0%) and `industry_group` (90.8%) are safe. Guard any `industry` filter with a fill-rate check.
6. **🟠 Data provenance / redistribution rights are not stated.** ISIN/CUSIP/FIGI are visibly vendor-derived. MIT covers the code; the README/CONTRIBUTING do not clearly address the underlying data's redistribution terms. Fine for internal use; **get clarification before shipping this table to customers.** `UNVERIFIED — needs manual check`.
7. **🟠 Weekly data churn means silent drift.** The bot rewrites 5,680+ rows weekly. Without a pinned SHA and a fill-rate assertion, a schema or coverage change lands silently. The seed script's two `assert`s are the guard — do not remove them.
8. **🟠 `use_local_location=True` alone reads from the *installed package* directory**, not a path you choose. On Windows that lands in `site-packages/`, which is not a durable place to keep data. ✅ **Use `base_url=<your dir>` together with it** (Context7 `_autodocs/09-configuration-and-initialization.md`: `fd.Equities(base_url="/path/to/compression/", use_local_location=True)`), or better still, skip the package and read the bz2 directly.
9. **🟡 `select()` raises `ValueError` for an unknown country** (`Equities.py`: `f"The country '{country_actual}' is not available in the database."`) — and calls `show_options()` per filter, which is O(n) over the frame on every filtered call. Fine for a script, wasteful in a loop.
10. **🟡 Sibling asset classes are all US/EU-centric** in practice — no `mic` for India outside equities, and the ETFs/Funds sets are European. Only `equities.bz2` is worth vendoring.
11. **🟢 `delisted` flag is 100% filled and immediately useful** — a cheap, real win.
12. **🟢 No security red flags.** No `eval`, single documented network host, browser UA only to satisfy GitHub raw.

---

## Finance (shashankvemuri)

An unreleased, never-published GitHub-only repo whose data layer is structurally incompatible with Indian tickers — `normalize_ticker` rewrites `RELIANCE.NS` into `RELIANCE-NS`, which yfinance cannot resolve. Its pure indicator functions are decent but `stockstats` (already installed) covers the same ground for free. **Avoid.**

> **⚠️ Naming trap — read this before anything else.** The PyPI project named **`finance`** is **NOT this repo.** It is [`finance` 0.2502 by Niels Henrik Bruun](https://pypi.org/project/finance/), uploaded **2014-03-24**, a Python-2 fixed-income library (`bankdate`, `dateflow`, `timeflow`, Nelson-Siegel yield curves) whose README still contains `print t1 + '3m'` Python-2 syntax. It has one sdist, no wheel, and `requires_python: null`. **This repo is not on PyPI under any name** — `finance-toolkit`, `finance-toolkit-py` and `shashank-finance` all return HTTP 404 on PyPI. Installation is `git clone` + `pip install -e .` only. Anyone who reads "install finance from PyPI" and gets the 2014 package has installed the wrong code.

### Verdict

**AVOID**

The `[data]` layer is Nasdaq/Nasdaq-Trader/Wikipedia-S&P-500/Finviz/TradingView only, and its `normalize_ticker()` turns `RELIANCE.NS` into `RELIANCE-NS` — every Indian ticker is destroyed at the boundary before yfinance ever sees it. The `[indicators]` layer is a set of pure, well-written, correctly-signed functions that *would* accept FinEngine's cached Indian OHLCV, and it covers ~70 indicators against FinEngine's current 13 — but `stockstats` 0.6.8 (already installed) exposes ~150 for free, and the package is at version `0.0.0`, has never been published to any index, and would have to be vendored from a git ref with no semver contract and no release history to pin against.

### License

- **License:** MIT
- **SPDX id:** `MIT`
- **Source:** [`pyproject.toml`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/pyproject.toml) → `license = "MIT"`; [`LICENSE`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/LICENSE); GitHub repo page shows "MIT license".

Clause (verbatim, `LICENSE`):

> ```
> MIT License
> Copyright (c) 2021 Shashank Vemuri
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
> ```

**Commercial impact:** None from the license. The project is `AGPL`-clean MIT with no copyleft, no business-source clause, no field-of-use restriction.

**Linking vs vendoring:** Technically either. But note the stated provenance caveat in its own README:

> "Technical-indicator references include [Stock_Analysis_For_Quant](https://github.com/LastAncientOne/Stock_Analysis_For_Quant) by LastAncientOne."

That upstream is **GPL-3.0**. MIT-minus-attribution for derived indicator logic of unknown provenance is a genuine (if probably low) redistribution risk if vendored into a product. **If you want the indicator math from this repo, reimplement the ~15 formulas you actually need from documented public definitions instead** (Wilder 1978, Hull, Keltner, Chaikin, Elder) — a day's work, no license ambiguity.

### Maintenance

**EVALUATE_LATER / effectively UNRELEASED** — the commit history is bimodal, which is the actual story.

| Signal | Observed value | Source |
|---|---|---|
| Declared version | **`0.0.0`** | `pyproject.toml` → `version = "0.0.0"` |
| Published to PyPI | **Never** (`finance-toolkit` / `finance-toolkit-py` / `shashank-finance` all 404) | [PyPI](https://pypi.org/project/finance/) |
| Last commit | **2026-09-12** (`2079903` — merge PR #69) | [commits page](https://github.com/shashankvemuri/Finance/commits/master) |
| **Gap 1** | **2024-08-20 → 2025-05-12** — ~9 months, only Dependabot bumps | commits page |
| **Gap 2** | **2025-05-12 → 2026-09-07** — **~16 months completely silent** | commits page |
| Current burst | All of 2026-09-07 → 2026-09-12 (7 commits + 3 PR merges) | commits page |
| The rewrite | `bf58f70 feat: add modular quantitative finance research tools (#64)` — the whole `src/finance` tree, `pyproject.toml`, `AGENTS.md` arrived in **one commit on 2026-09-07** | commits page |
| Prior structure | Retired by `8b1af5a refactor: retire audited legacy programs and obsolete bundled assets` | commits page |
| Open issues / PRs | **0 open issues, 3 open PRs** | [repo page](https://github.com/shashankvemuri/Finance) |
| Total commits | 1,279 (the vast majority pre-date the rewrite) | repo page |
| Stars / forks | 4,300 / 373 | repo page |
| Default branch | `master` (**not** `main`) | repo page |
| Archived | `false` | repo page |

**Read: this is a ~3-week-old personal project, not a 4.3k-star library.** The star count and 1,279 commits are inherited from the pre-2025 Streamlit/IBD-era codebase that was deleted in September 2026. The `AGENTS.md`/`CONTRIBUTING.md`/`docs/providers.md` triad and the `codex/*` branch names show the current shape is largely agent-generated. **Treat it as an unreleased 0.0.0 preview, regardless of stars.** Zero open issues on a repo with 4.3k stars is itself a signal that community reporting has not ramped.

### Compatibility

| Requirement | Status | Evidence |
|---|---|---|
| Python 3.12 | ✅ Minimum is 3.12 | `requires-python = ">=3.12"`; `[tool.ruff] target-version = "py312"` |
| pandas 3.0 | ⚠️ **Untested** | `dependencies = ["numpy>=2.0,<3", "pandas>=2.2,<4"]` — the wide `>=2.2,<4` range *admits* pandas 3, but there is no evidence it was ever run against it. Repo was last touched 2026-09-12; no CI-visible pandas-3 run. `UNVERIFIED — needs manual check` |
| numpy 2.x | ⚠️ Untested | `numpy>=2.0,<3` — admits numpy 2.5, no evidence of testing. `UNVERIFIED` |
| Compiled extensions | ❌ None | `hatchling`, `packages = ["src/finance"]`, pure Python |
| Installable | ❌ **`pip install finance` gives the WRONG package** (2014, py2, Niels Henrik Bruun) | [PyPI `finance`](https://pypi.org/project/finance/) |

The wide `pandas>=2.2,<4` / `numpy>=2.0,<3` ranges look permissive but are really a sign the project has not been validated against FinEngine's exact stack (pandas **3.0.6**, numpy **2.5.3**). FinEngine's `AGENTS.md` records that pandas 3.0.6 has already broken plenty of quant libraries; assuming a 3-week-old repo is clean is exactly the assumption to avoid.

### Data dependency chain

```
finance.data.YahooFinance.history(ticker, ...)
        │
        └─ normalize_ticker(ticker)          ◄── 🔴 THE KILLER
               ticker = ticker.strip().upper().replace(".", "-")
               if not re.fullmatch(r"[A-Z0-9^][A-Z0-9^=\-]{0,24}", ticker):
                   raise ValueError(f"invalid ticker: {ticker!r}")
               return ticker
        │
        └─ yf.Ticker("RELIANCE-NS", session=Session(impersonate="chrome"))

    "RELIANCE.NS"  ->  "RELIANCE-NS"     ✗ yfinance 404s
    "500112.BO"    ->  "500112-BO"       ✗ yfinance 404s
    "BAJAJ-AUTO.NS"->  "BAJAJ-AUTO-NS"   ✗ yfinance 404s
    "^NSEI"        ->  "^NSEI"           ✓ (index symbols survive — no dot)
    "AAPL"         ->  "AAPL"            ✓
```

Verified verbatim from [`src/finance/data/normalize.py`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/src/finance/data/normalize.py). The project is not unaware — `docs/providers.md` says so explicitly:

> "`normalize_ticker` handles ordinary Yahoo share-class, index and FX symbols, **not every exchange suffix convention**."

**Indian market support: NO.** Not "partial" — structurally excluded at the ticker-normalisation boundary. Every other data provider in the package is US-only as well:

| Provider | Source | India? |
|---|---|---|
| `YahooFinance` | yfinance via `normalize_ticker` | ❌ `.NS`/`.BO` destroyed |
| `exchange_universe()` | `nasdaqtrader.com/dynamic/SymDir/{nasdaqlisted,otherlisted}.txt` | ❌ Nasdaq only |
| `sp500_constituents()` | Wikipedia `List_of_S%26P_500_companies` (HTML scrape) | ❌ US only |
| `dividend_calendar()` | `api.nasdaq.com/api/calendar/dividends` | ❌ US only |
| `Finviz` | finviz.com screener/company/analyst/insider/news | ❌ US only |
| `TradingView` | undocumented public scanner | ❌ US-only scanner |
| `cot_financial_futures()` | CFTC TFF futures-only positioning | ❌ US futures |
| `reddit_posts` | Reddit anonymous | ❌ n/a — adapter itself 403s |
| `rss_news`, `transcript_index` | Motley Fool transcripts | ❌ US only |
| `Alpaca` (integrations) | Alpaca brokerage | ❌ US brokerage |

The package's own docs are honest about the fragility:

> "These are public/unofficial interfaces, not exchange-grade service contracts: throttling, revisions, schema changes and unavailable fields remain possible. ... There is no automatic cross-provider fallback that could silently mix adjustment bases or currencies. Honor provider terms and data licensing."

**API keys required:** none for the public providers, but `integrations.Alpaca` needs brokerage credentials, and `integrations.notifications` (`send_email` / `send_sms` / `send_webhook`) needs SMTP/Twilio/webhook credentials.

**Rate limits / cost:** no published limits; all endpoints are scraped or unofficial. `docs/providers.md` notes per-client request spacing and a short in-memory cache in the Finviz adapter.

**Offline / vendoring feasibility: technically easy, strategically unwise.** The `[indicators]`, `[analytics]`, `[strategies]`, `[backtesting]` and `[portfolio]` modules are **pure functions over price series with no network access** — the README states "Calculate indicators without any network access." So you *could* vendor `src/finance/indicators/` alone and feed it FinEngine's cached Indian OHLCV, bypassing the broken data layer entirely. That is the only technically viable adoption path, and even then the licensing-provenance note above and the 0.0.0 version argue against it.

### Dependency footprint

**Core (2 packages — the lightest of the three):**
```toml
dependencies = ["numpy>=2.0,<3", "pandas>=2.2,<4"]
```

**Optional extras** (all avoid or already satisfied by FinEngine):

| Extra | Packages | FinEngine status | Risk |
|---|---|---|---|
| `data` | `yfinance>=0.2.65,<2`, `lxml>=5,<7` | yfinance 1.7.0 ✅, lxml ✅ | Low — but this is the Indian-breaking layer |
| `portfolio` | `scipy>=1.14,<2` | 1.18.1 ✅ | None |
| `models` | `scikit-learn>=1.5,<2`, `statsmodels>=0.14.4,<1` | 1.9.1 ✅, 0.15.0 ✅ | None |
| `sentiment` | `vaderSentiment>=3.3.2,<4` | not installed | Adds a dep for a VADER wrapper — not worth it |
| `neural` | `torch>=2.6,<3` | not installed | **~2 GB.** Do not install. |
| `prophet` | `prophet>=1.1.6,<2` | not installed | Heavy; `fbprophet` is unmaintained |
| `apps` | `scipy`, `streamlit>=1.45`, `matplotlib`, `lxml`, `yfinance` | streamlit not installed | UI dep in a backend — no |
| `reports` | `openpyxl>=3.1`, `matplotlib>=3.9` | both ✅ | Low |
| `plot` | `matplotlib>=3.9` | ✅ | Low |
| `dev` | `pytest`, `ruff`, `build`, **`ta>=0.11,<1`** | — | ⚠️ see below |

**🔴 Conflict risk — the widest ranges in the whole study.** `pandas>=2.2,<4` and `numpy>=2.0,<3` are the *loosest* pandas/numpy constraints any of the three libraries declare. FinEngine runs pandas 3.0.6 / numpy 2.5.3; admitting `<4` means a future `pandas 3.1` release lands untested. Combined with `pip install -e .` (no lockfile entry, no wheel), this is the most likely of the three to destabilise a resolved environment. Its own `dev` extra depends on **`ta` 0.11.0** (unmaintained since **2023-11-02**, and a classic pandas-2-only library) — evidence the project itself leans on unmaintained pandas-2-era code.

**Not declared but imported at runtime:** `curl_cffi` (`from curl_cffi.requests import Session` in `YahooFinance._ticker`) — FinEngine already has it ✅, but the `[data]` extra doesn't list it. Another packaging bug.

**Net new installs if vendored: zero** (only numpy + pandas, both present).

### API surface

**Indicators** (pure, no network — the only layer FinEngine could use). All signatures verified from `src/finance/indicators/*.py` @ `master`:

```python
from finance.indicators import rsi, macd, stochastic, williams_r, cci, adx, aroon, roc, tsi

rsi(close: pd.Series, window: int = 14) -> pd.Series
    """Wilder RSI in [0,100]; flat windows are 50; first value follows window changes."""
    changes = series(close).diff()
    up, down = smma(changes.clip(lower=0), window), smma(-changes.clip(upper=0), window)
    total = up + down
    return (100 * up / total.where(total != 0)).mask(total == 0, 50)

stochastic(high, low, close, window=14, smooth_k=1, smooth_d=3) -> pd.DataFrame  # columns k, d
stochastic_rsi(close, window=14, smooth_k=3, smooth_d=3) -> pd.DataFrame
williams_r(high, low, close, window=14) -> pd.Series
macd(close, fast=12, slow=26, signal=9) -> pd.DataFrame   # columns macd, signal, histogram
apo(close, fast=12, slow=26) -> pd.Series
cci(high, low, close, window=20) -> pd.Series
dpo(close, window=20) -> pd.Series
tsi(close, slow=25, fast=13) -> pd.Series
adx(high, low, close, window=14) -> pd.DataFrame
aroon(high, low, close, window=25) -> pd.DataFrame
roc(close, window=10) -> pd.Series
```

**Full `[indicators]` catalogue — 70 functions across 6 modules:**

| Module | Functions |
|---|---|
| **trend** | `sma` `ema` `wma` `smma` `dema` `tema` `trima` `hma` `ribbon` |
| **momentum** | `rsi` `stochastic` `stochastic_rsi` `williams_r` `macd` `apo` `momentum` `roc` `cci` `dpo` `tsi` `ultimate_oscillator` `adx` `aroon` `price_momentum_oscillator` `dynamic_momentum_index` |
| **volatility** | `true_range` `atr` `bollinger_bands` `envelopes` `donchian` `keltner` `acceleration_bands` `natr` `realized_volatility` `relative_volatility_index` `standard_deviation` `supertrend` `variance` |
| **volume** | `vwap` `vwma` `twap` `mfi` `obv` `pvi` `pvt` `accumulation_distribution` `chaikin_money_flow` `chaikin_oscillator` `force_index` `ease_of_movement` `balance_of_power` `vpci` |
| **levels** | `pivot_points` `fibonacci_levels` `confirmed_extrema` `green_line` `breadth` `mcclellan` `arms_index` `ichimoku` `gann_fan` `speed_resistance` `pivot_midpoints` |
| **statistics** | `beta` `correlation` `covariance` `geometric_return` `relative_price` `rolling_regression` `zscore` |

**The claimed-unique ones vs `stockstats` 0.6.8 + `pandas-ta`:**

| This repo | `stockstats` 0.6.8 (installed) | Verdict |
|---|---|---|
| `supertrend`, `natr`, `keltner`, `donchian`, `acceleration_bands`, `supertrend` | `stockstats` has `supertrend`, `atr`, `boll`, `kdjk`, `macds`, `rsi`, `mfi`, `wr`, `cci`, `adx`, `trix` | **Duplicated** |
| `vpci`, `pvt`, `gann_fan`, `speed_resistance`, `green_line`, `arms_index`, `dynamic_momentum_index`, `relative_volatility_index` | `stockstats` has **`vpci`**, `pvt`; lacks Gann, Green Line, Arms Index, DMI, RVI | **Genuinely new — but niche** |
| `ultimate_oscillator`, `ichimoku`, `fibonacci_levels`, `envelopes`, `ribbon`, `brock` | `stockstats` lacks Ichimoku, UO, Fibonacci, Envelopes | **Genuinely new** |

`stockstats` 0.6.8 exposes **~150 indicators** via `StockDataFrame` attribute access. This repo exposes **70**. The delta is real but small, and the genuinely-new items (Ichimoku, Gann fan, Arms Index, Green Line, RVI) are charting/long-cycle tools, not institutional risk analytics.

**Other areas** (all documented above, all US-bound or duplicative): `analytics` (CAPM/OLS, VaR, expected shortfall, Kelly, drawdown, DCF, `Valuation` class, sentiment), `screening` (Minervini, IBD relative strength, Green Line, RSI/trend, growth/ownership, dividend), `strategies` (crossover, MACD trend, Keltner breakout, Ichimoku trend, oscillator reversion, pairs, chronological selection), `backtesting` (`backtest()` with next-open execution, cash accounting, commission/slippage/borrow), `portfolio` (`optimize`, `efficient_frontier`, `simulate_portfolio`, `lump_sum_vs_dca`), `models` (ARIMA, PCA, clustering, cointegration, volatility regimes, Prophet/neural optional), `reports`, `integrations`.

**Realistic usage — the *only* Indian-viable path:**
```python
# ✅ The indicators are pure: skip [data] entirely, feed FinEngine's own OHLCV.
from finance.indicators import rsi, macd, adx, keltner, ichimoku

df = await data_service.fetch_historical_data("RELIANCE.NS")   # FinEngine's own cache
rsi_14 = rsi(df["Close"], window=14)                            # 0-100, same scale as stockstats
macd_df = macd(df["Close"], fast=12, slow=26, signal=9)         # macd / signal / histogram
```

### Overlap with FinEngine

| FinEngine file / function | This repo's replacement | Effort | Risk |
|---|---|---|---|
| `services/indicators_service.py:34-53` `SUPPORTED_INDICATORS` — 13 indicators via `stockstats` (`close_10_ema`, `close_50_sma`, `close_200_sma`, `macd`, `macds`, `macdh`, `rsi`, `boll`, `boll_ub`, `boll_lb`, `atr`, `vwma`, `mfi`) | `finance.indicators.*` — 70 functions | **L** | **🔴 High.** (a) Requires `git clone` + `pip install -e .` from an unreleased `0.0.0`; (b) pandas 3 compatibility unverified; (c) must bypass `[data]` entirely to avoid the `.NS` bug; (d) reintroduces the 10 indicators `stockstats` already provides for free, in a different codebase with different conventions; (e) FinEngine's existing adapter has house contracts (`mfi × 100` scale fix at `:154-159`, row-count assertion at `:136-137`, NaN masking at `:160-176`) that would all need re-verification per indicator. **Net: ~6 new indicators for a full indicator-layer migration. Bad trade.** |
| `services/data_service.py:577` `fetch_historical_data()`, `:1048` `fetch_ohlcv_batch()` | `data.YahooFinance.history()` | **S** | **🔴 BLOCKING** — `normalize_ticker` destroys `.NS`/`.BO`. Also FinEngine's version has caching, staleness guards (`assert_not_stale`) and Alpha Vantage fallback, all of which this lacks. **Not a candidate at any effort level.** |
| `services/screener_service.py:182` `run_screen()`, `:300` `run_custom_screen()` | `screening.*` (Minervini, IBD RS, Green Line, RSI/trend, growth, dividend) | **L** | **🔴 High** — these are **US long-only IBD/IBD-style momentum screens** tuned for US large caps. FinEngine's screener runs on an India universe. Adopting US momentum templates for Indian equities without re-calibration is a correctness risk, not a feature. |
| `services/benchmark_service.py:144` — NSE benchmark, beta/alpha/R² | `analytics.capm()`, `ols()`, `analytics.risk.value_at_risk()` | **M** | **🟠 Med** — `capm`/`ols` are thin; FinEngine's `market_model_statistics()` (`analytics_engine.py:1155`) already covers it against the correct NSE benchmark. No gain. |
| `services/optimization_service.py:838` — `STRATEGIES = ("hrp", "min_vol", "max_sharpe", "min_cvar", "black_litterman")` | `portfolio.optimize()`, `efficient_frontier()`, `random_allocations()`, `discrete_allocation()` | **L** | **🔴 High** — FinEngine's is cvxpy-based, INR-aware, and its min-CVaR is a correct Rockafellar-Uryasev LP (`optimization_service.py:652-666`). Replacing with a scipy-based `optimize()` is a regression. |
| `services/backtest_service.py:237` — next-open execution, drawdowns, Sharpe, Calmar | `backtesting.backtest()`, `completed_trades()`, `trade_statistics()` | **M** | **🟡 Low-Med** — plausible overlap; FinEngine's is small (237 lines) so this *might* be the one interesting swap. But: NSE trading calendar, Indian brokerage cost model and T1/T2 settlement would all have to be re-implemented on top. Given the pandas-3 and 0.0.0 risks, still not worth it. |
| `services/regime_service.py:624` (hmmlearn HMM) | `models.volatility_regimes()` | **S** | **🟡 Low** — `hmmlearn` is already installed and is the better regime tool. |
| `services/cointegration_service.py:1334` | `models.cointegration_pairs()`, `models.partial_correlations()` | **S** | **🟡 Low** — FinEngine's is 1,334 lines; assume it's deeper. |
| *(nothing)* | `integrations.Alpaca`, `send_email`/`send_sms`/`send_webhook` | **S** | **🟠 Med** — US-brokerage-only and would add credential handling to a backend that has none. Skip. |
| *(nothing — 6 genuinely-new indicators)* | `ichimoku`, `ultimate_oscillator`, `fibonacci_levels`, `envelopes`, `gann_fan`, `green_line`, `arms_index`, `relative_volatility_index` | **S** each | **🟢 Low individually** — but the cheapest way to get these is 8 short, well-documented functions in `indicators_service.py` citing public definitions, **not** adopting a 0.0.0 unreleased repo. |

### Implementation guide

**Recommendation: no `pyproject.toml` line. Do not add it.** If the eight genuinely-new indicators are wanted, hand-write them.

**What "adopting" would actually require (for the record):**

```toml
# ⚠️ NOT RECOMMENDED — shown only to document the full cost.
# There is no PyPI release of this project. `pip install finance` installs a
# different, 2014, Python-2 package by a different author.
#
# Requires: git clone + pip install -e .  (no wheel, no lockfile entry)
# Widens pandas to >=2.2,<4 and numpy to >=2.0,<3 — the loosest constraints
# in this study, against FinEngine's pandas 3.0.6 / numpy 2.5.3.
#
# [project.optional-dependencies]
# "finance-data" = ["yfinance>=0.2.65,<2", "lxml>=5,<7"]   # US-only data layer
```

**Files that would have to be touched if it were adopted (not recommended):**
- `backend/pyproject.toml` — git dependency + widened pandas/numpy ranges
- `backend/uv.lock` — regenerate
- `backend/app/services/indicators_service.py:34-53` — replace `SUPPORTED_INDICATORS` and `_compute_sync()`
- `backend/tests/test_indicators*.py` — re-baseline all 13 existing indicators plus the MFI scale fix
- **Would NOT touch:** `data_service.py`, `screener_service.py`, `optimization_service.py` (its data and screening layers are unusable / US-only)

**The recommended alternative — add the 8 missing indicators directly:**

```python
# backend/app/services/indicators_service.py  (additive, ~60 lines, no new dep)
#
# These are the indicators this repo would have contributed that FinEngine
# genuinely lacks. Each is a direct transcription of its public definition
# (Ichimoku 1969; H. M. Wilder; Linda Raschke; J. Welles Wilder; H. D. Gann;
# Stan Walker's IBD Green Line) rather than a dependency on an unreleased repo.
#
# Deliberately NOT added: Donchian/Keltner/TRIX/DPO/ROC/MFI/OBV/CMF/A/D etc.
# stockstats 0.6.8 already covers those — see indicators_service.py:34-53.

def ichimoku_cloud(high, low, close, conversion=9, base=26, span_b=52):
    """Ichimoku Kinko Hyo. Returns (tenkan, kijun, senkou_a, senkou_b)."""
    tenkan = (high.rolling(conversion).max() + low.rolling(conversion).min()) / 2
    kijun = (high.rolling(base).max() + low.rolling(base).min()) / 2
    return tenkan, kijun, (tenkan + kijun) / 2, (high.rolling(span_b).max() + low.rolling(span_b).min()) / 2

def ultimate_oscillator(high, low, close, w1=4, w2=8, w3=14):
    """Larry Williams' Ultimate Oscillator, 0-100."""
    prev_close = close.shift(1)
    bp = close - pd.concat([low, prev_close], axis=1).min(axis=1)
    tr = pd.concat([high, prev_close], axis=1).max(axis=1) - pd.concat([low, prev_close], axis=1).min(axis=1)
    def avg(n):
        return bp.rolling(n).sum() / tr.rolling(n).sum().replace(0, np.nan)
    return 100 * (4 * avg(w1) + 2 * avg(w2) + avg(w3)) / 7

def arms_index(advancing, declining):
    """Stan Walker's Arms Index = (A-D)/(A+D). Requires cross-sectional breadth."""
    total = advancing + declining
    return ((advancing - declining) / total.where(total != 0)).mask(total == 0, np.nan)
```

Add each with a focused regression test against an independent reference series, per `AGENTS.md` ("Prefer adding permanent unit and regression tests in `tests/` over running one-off throwaway debug scripts"). This buys the only thing this repo could have contributed, at ~5% of the cost and with zero license, packaging or compatibility exposure.

**Keep vs replace:** keep **everything**. Replace **nothing**.

### Risk & caveats

1. **🔴 Indian tickers are structurally impossible.** `normalize_ticker` does `.replace(".", "-")` → `RELIANCE.NS` becomes `RELIANCE-NS`, and yfinance 404s. `500112.BO` → `500112-BO`. `BAJAJ-AUTO.NS` → `BAJAJ-AUTO-NS`. This is a hard block on the entire `[data]` layer, verified in source. Only index/FX symbols (no dot) survive.
2. **🔴 `pip install finance` installs the wrong package.** PyPI `finance` 0.2502 (2014, Niels Henrik Bruun, Python 2 fixed-income). This repo is not on PyPI under any name — `finance-toolkit`, `finance-toolkit-py`, `shashank-finance` all 404. Any onboarding doc saying "pip install finance" is actively dangerous.
3. **🔴 Version `0.0.0`, never released.** No wheel, no release, no tag, no changelog, no PyPI artifact. Adoption means tracking `master` HEAD. Unacceptable for a production analytics backend.
4. **🟠 16-month silence, then a full rewrite in one commit.** `2025-05-12 → 2026-09-07` completely silent; `bf58f70` on 2026-09-07 replaced the entire tree. The 4.3k stars / 1,279 commits / old Streamlit-IBD history are **inherited from deleted code** and are not evidence of current maturity. Current code is ~3 weeks old.
5. **🟠 pandas 3.0.6 / numpy 2.5.3 compatibility is UNVERIFIED.** `pandas>=2.2,<4` *admits* pandas 3 but there is no evidence it was ever tested. Its own `dev` extra pins `ta>=0.11,<1` — a library unmaintained since 2023-11-02 and pandas-2-era. `UNVERIFIED — needs manual check`.
6. **🟠 Loosest version constraints of the three.** `pandas>=2.2,<4` and `numpy>=2.0,<3` on an editable install against a lockfile'd environment is how a pandas 3.1 release silently breaks production.
7. **🟠 Indicator-provenance licence ambiguity.** README: *"Technical-indicator references include Stock_Analysis_For_Quant by LastAncientOne"* — that upstream is **GPL-3.0**. MIT-licensing derived indicator logic of unclear provenance is a real (if probably low) risk if vendored into a shipped product.
8. **🟠 US-only screens.** `screening.minervini`, `ibd_relative_strength`, `green_line` are US large-cap momentum templates. Running them over Indian equities without re-calibration produces confidently wrong output — worse than no output.
9. **🟡 Single-maintainer, no release train, no CI-published artifacts.** `AGENTS.md`/`CONTRIBUTING.md` reference `python scripts/check_examples.py --live` and `pytest -m integration`, all "opt-in and excluded from CI". No external verification.
10. **🟡 Missing runtime dependency declaration.** `curl_cffi` is imported in `YahooFinance._ticker` but is not in the `data` extra. FinEngine happens to have it, which masks the bug.
11. **🟡 `[integrations]` adds credentialed US brokerage + SMS/email transports** to a backend that currently has neither. Extra attack surface for zero FinEngine value.
12. **🟢 The `[indicators]` code quality is genuinely good** — explicit input validation, preserved warm-up NaNs, documented units (RSI 0–100 vs returns as fractions), index alignment via an `aligned()` helper, and `normalize_ohlcv` that raises on inconsistent OHLC bounds rather than silently proceeding. That is *better* engineering discipline than most TA libraries. It is simply not needed when `stockstats` already covers 150 indicators.
13. **🟢 No security red flags found** in the reviewed pure modules.

---

## Cross-library comparison

| Dimension | **FinanceToolkit** 2.2.0 | **FinanceDatabase** 2.4.0 | **Finance (shashankvemuri)** master |
|---|---|---|---|
| **Verdict** | **ADOPT_PARTIAL** (models + ratios + breadth + economics) | **ADOPT_PARTIAL — data only, offline** | **AVOID** |
| **License** | **MIT** (`MIT`) ✅ | **MIT** (`MIT`) ✅ | **MIT** (`MIT`) ✅ |
| Non-permissive / BSL / copyleft | ❌ none | ❌ none (code); data provenance unstated | ❌ none; GPL-3.0 upstream attribution ambiguity |
| Copyright holder / year | Jeroen Bouma, 2025 | Jeroen Bouma, 2023 | Shashank Vemuri, 2021 |
| LICENSE filename | `LICENSE.txt` | `LICENSE` | `LICENSE` |
| **Latest version** | **2.2.0** (2026-08-18) | **2.4.0** (2026-06-02) | **`0.0.0` — never released** |
| **On PyPI?** | ✅ | ✅ | ❌ **no.** PyPI `finance` = different 2014 py2 package |
| **Last commit** | 2026-09-10 | **2026-09-20** (+ weekly bot) | 2026-09-12 (after a 16-month gap) |
| **Maintenance** | **ACTIVE** (3 open issues) | **ACTIVE** (weekly data refresh) | **UNRELEASED** (0.0.0; 3-week-old rewrite) |
| Stars / forks | 5,384 / 626 | 9,400 / 968 | 4,300 / 373 *(inherited from deleted code)* |
| Python 3.12 | ✅ `>=3.11,<3.16` | ✅ `>=3.10,<3.16` | ✅ `>=3.12` |
| **pandas 3.0** | ✅ **`pandas>=3.0` floor** | ✅ (transitive) | ⚠️ **UNVERIFIED** (`pandas>=2.2,<4`) |
| **numpy 2.x** | ✅ | ✅ | ⚠️ **UNVERIFIED** (`numpy>=2.0,<3`) |
| Compiled extensions | none (`py3-none-any`) | none (`py3-none-any`, 0.03 MB) | none (hatchling, `src/finance`) |
| **Direct deps** | pandas, yfinance, scikit-learn, requests, openpyxl, **pyyaml** | **financetoolkit** (hard) | **numpy, pandas** (only 2) |
| **Net new installs for FinEngine** | **0** (all satisfied; pyyaml already resolved) | **+financetoolkit** if taken as a package; **0** if data vendored | 0 if vendored (but `pip install -e .` only) |
| **API key required?** | **No** — `enforce_source="YahooFinance"`. **Yes for `Discovery`** (FMP only, no fallback). FRED key only for US-specific `Economics` series — **not** for India. | **No** | No (public providers) |
| Paid tier risk | FMP free = **250 req/day, 5 yr, US exchanges only**. 🔴 `ratios.get_forward_price_earnings_ratio()` / `..._growth_ratio()` require **FMP Premium** (Context7-confirmed) — excluded from scope | none | none (scraped providers) |
| **Indian tickers (`.NS`/`.BO`)** | ✅ **yes** via Yahoo path — no allow-list, no country filter | ✅ **yes** — symbols are natively `.NS` (1,716) / `.BO` (3,793) | ❌ **no** — `normalize_ticker` mangles `.` → `-` |
| Indian fundamentals depth | ⚠️ yfinance statements sparse for small/mid-caps | N/A (metadata only) | ❌ N/A |
| **Data footprint** | 0.97 MB wheel; no bundled data | **14.58 MB** `equities.bz2` → **187 MB** in RAM; weekly churn | 0 (network-only) |
| **Data vendorable offline?** | ✅ yes — accepts `historical=`/`income=`/`balance=`/`cash=` DataFrames | ✅ **yes — best offline story of the three**; static bz2 at a stable URL | ⚠️ indicators yes; data layer unusable for India |
| Notable gap | undeclared `scipy` import in `risk/var_model.py` | **ISIN 2.4% filled for India**; `industry` 33%; NSE 1,716 vs BSE 3,793 | 197 MB-style caveat n/a; **`pip install finance` = wrong package** |
| **Unique value to FinEngine** | Altman/Piotroski/Beneish/Ohlson/Zmijewski/Springate/Grover/Fulmer, DuPont, WACC, EVA, Tobin's Q, DDM, residual income, Graham number; cross-sectional market breadth (`get_trin`, `get_new_highs_new_lows`); `Economics` — **India confirmed**, 60+ countries, 50+ indicators, crisis gates (`get_currency_crisis`, `get_banking_crisis`); 90+ audited statement ratios | symbol master (`sector` 91%, `industry_group` 90.8%, `mic` 100%, `market_cap` bucket, `delisted` 100%, `summary` 91.7%) | ~6–8 indicators beyond `stockstats`; a next-open backtester |
| **Official offline seam** | ✅ documented "data-agnostic… any provider including Intrinio, OpenBB, Yahoo Finance, Quandl"; `get_normalization_files()` + `format_location` | ✅ `base_url=` + `use_local_location=True`; or read the bz2 directly | ⚠️ indicators yes; data layer unusable for India |
| **Overlap with FinEngine** | 🔴 **Very high** — risk/performance/portfolio duplicate `analytics_engine.py` (4,119), `optimization_service.py` (838), `tail_risk_service.py` (500), `volatility_service.py` (457) | 🟡 Medium — overlaps `screener_service.py` universe + `data_service.py` validation | 🔴 High on indicators, portfolio, screening, backtesting |
| Install friction | 🟢 none | 🟡 14.6 MB runtime download per call | 🔴 git clone + `pip install -e .`, no release |

---

## Recommended adoption order

Ranked highest-ROI first. Steps 1 and 2 are independent; 1 needs no new dependency at all.

### 1. 🥇 Vendor FinanceDatabase's `equities.bz2` as a data seed — **no new dependency**
**Effort: S (half a day). Risk: Low. New installs: 0. Value: high and durable.**

The best ROI in the entire study precisely because it costs nothing. `backend/data/nse/` already exists and is empty; `daisy.db` is the SQLite to seed. 5,680 Indian rows, symbols already `.NS`/`.BO`, 91% sector fill, 100% `delisted` and `mic` fill. Pin a commit SHA, assert the shape and the suffix invariant, write ~1 MB into SQLite.

**Why first:** it upgrades FinEngine's ticker validation from a regex to a *membership test* (a regex accepts `RELIANCE.NS` whether or not it exists), gives the screener a real `sector`/`industry_group`/`market_cap` taxonomy, and lets `screener_service` hard-reject the 105 delisted Indian scrips — with zero dependency risk and zero pandas-3 exposure.

**Gate:** verify the two asserts (`mic.isin(["XNSE","XBOM"]).sum() > 4_000` and `.NS`/`.BO` suffix count > 5_000) before wiring anything.

### 2. 🥈 Adopt FinanceToolkit's `models` module — auditable replacement for yfinance's black-box scores
**Effort: M (1-2 days). Risk: Low-Med. New installs: 0. Value: high.**

Install `financetoolkit>=2.2,<3` (one `pyproject.toml` line; every dependency already satisfied). Construct **only** with `enforce_source="YahooFinance"`, `benchmark_ticker=None`, and pre-supplied `historical=`/`income=`/`balance=`/`cash=` frames from `data_service.py` so the hot path makes zero network calls. Then swap the source of `piotroski_score` / `graham_number` / `enterprise_value` (currently `getattr(yf.Ticker, ...)` at `company_data_service.py:201-203`) for the library's auditable Python — same schema keys, so the API contract at `equity_research_service.py:54-55, 240` does not change. Add Altman Z, Beneish M, Ohlson O, Zmijewski, Springate, Grover, Fulmer as **new cross-sectional-ranking-only** fields.

**Why second:** it is the only genuinely missing *institutional* capability across all three libraries, and FinEngine's own README thesis ("Transparent and Efficient Financial Analysis") is the same one. The reason it's not first is the Spike gate below.

**🚦 GATE — do step 2 only if this passes:** instantiate against 20 liquid NSE names and check that `models.get_altman_z_score()` returns non-NaN. If yfinance has no statements for Indian mid-caps, the entire `models` module is dead weight and **stop** — that is the single most likely failure mode.

### 3. 🥉 Add FinanceToolkit's cross-sectional market-breadth indicators + `Economics` (India macro)
**Effort: S. Risk: Low. Value: medium-high.**

`technicals.collect_breadth_indicators()` / `get_advancers_decliners()` / `get_new_highs_new_lows(window=60)` / `get_trin()`. Context7 confirms these are computed **cross-sectionally across all tickers in the instance** — exactly the shape FinEngine's existing multi-ticker price matrix supports, and FinEngine has no breadth capability at all today.

Then the standalone `Economics` class for the `ai_context_service.py` macro dossier: `Economics(start_date=...).get_government_expenditure(countries=["Japan","China","India"])`, `get_inflation_rate()`, `get_yield_curve_slope()`. ✅ **India confirmed** in the official docstring, served by OECD + IMF GMDB, and **no FRED key required** (`_require_fred_api_key` gates only US-specific series). Bonus: `get_currency_crisis()` / `get_banking_crisis()` / `get_sovereign_debt_crisis()` are natural macro-regime gates for a risk platform.

### 4. 🏅 Evaluate FinanceToolkit's `ratios` collection, case by case
**Effort: M. Risk: Med. Value: medium.**

`cash_conversion_cycle`, `operating_cycle`, `days_of_sales_outstanding`, `effective_tax_rate`, `net_debt_to_ebitda_ratio`, `cash_return_on_assets` — the ones bfinance 0.1.3 does not expose. **Do not** replace FinEngine's existing bfinance block: `company_data_service.py:183-186` documents a hard house contract (`market_cap` in absolute ₹) that would break.

### 5. 🏅 Re-evaluate in 6 months, not sooner
- `FinanceDatabase` weekly seed refresh as a scheduled job (unlocks sector/industry screens + delisted rejection).
- FinanceToolkit `technicals` breadth → screener as a strategy preset in `screener_service.run_screen()`.
- FinanceToolkit `economics` India macro → `ai_context_service` dossier section.

### Explicitly not on the list
- FinanceToolkit `risk`, `performance`, `portfolio`, `options`, `fixedincome`, `econometrics`, `Discovery` — all overlap or are FMP-locked.
- FinanceToolkit `Discovery.get_stock_screener()` — **FMP-only, no Yahoo fallback, free tier excludes non-US exchanges.** Unusable.
- shashankvemuri/Finance in any form.

---

## What NOT to adopt, and why

### ❌ 1. FinanceToolkit's `risk`, `performance` and `portfolio` modules — **regression, not an upgrade**
This is the most tempting mistake in the study, because the library is genuinely excellent and the surface area is enormous (50 risk methods, 37 performance methods, 10 GARCH variants, a full Portfolio class with a `config.yaml`).

FinEngine already has all of it, and better, for this use case:
- `analytics_engine.py` (4,119 lines) wraps every ratio statistic in **bootstrap confidence intervals, moving-block resampling sized by autocorrelation, and effective-sample-size disclosure** (`measure_estimate_uncertainty` at `:793`, `moving_block_size` at `:661`, `autocorrelation_disclosure` at `:628`). FinanceToolkit's `performance` returns **point estimates only**. Swapping would be a straight loss of statistical rigour.
- `optimization_service.py` implements `min_cvar` as a correct Rockafellar-Uryasev scenario LP (`:652-666`) and carries explicit provenance metadata — `expected_sharpe_was_the_optimised_objective`, `expected_sharpe_basis` (`:348-362`) — so a reader can never misread a Sharpe as a target rather than a descriptor. That is exactly the honesty discipline the toolkit lacks.
- `risk_free_rate` defaults to the **US 10-year Treasury** in both `Toolkit.__init__` and `FinanceFrame.to_toolkit`. For an INR book this is not a tuning detail, it is a wrong answer shipped silently.

**Verdict: KEEP `analytics_engine.py`, `optimization_service.py`, `tail_risk_service.py`, `volatility_service.py`, `benchmark_service.py` in full. Do not touch them.**

### ❌ 2. FinanceToolkit's `Discovery` module and the two **Premium-FMP** forward ratios — **credential-locked**
All 30 methods in `discovery_model.py` call `fmp_model.get_financial_data()` unconditionally. There is **no Yahoo fallback** for Discovery (unlike the `Toolkit` core, which does fall back). FMP's free tier is 250 requests/day, 5 years, **US exchanges only**. `Discovery.get_stock_screener()` — the single most attractive method — is therefore dead on arrival for an India-first platform. A paid FMP tier would still be a bad fit: FinEngine's `screener_service.py` runs on a cached SQLite universe and would gain nothing from a 250-req/day REST screener.

Separately, Context7 pins down a smaller but sharper trap: `ratios.get_forward_price_earnings_ratio()` and `ratios.get_forward_price_earnings_growth_ratio()` require a **paid FMP Premium subscription** (analyst-consensus estimates are not on the free tier). These are the only two methods in the adopt scope with a hard paid dependency. **Never call them, and never surface a forward-P/E sourced from the toolkit in a FinEngine response** — a silently-empty forward multiple on an Indian mid-cap is indistinguishable from "no analyst covers this name."
All 30 methods in `discovery_model.py` call `fmp_model.get_financial_data()` unconditionally. There is **no Yahoo fallback** for Discovery (unlike the `Toolkit` core, which does fall back). FMP's free tier is 250 requests/day, 5 years, **US exchanges only**. `Discovery.get_stock_screener()` — the single most attractive method — is therefore dead on arrival for an India-first platform. A paid FMP tier would still be a bad fit: FinEngine's `screener_service.py` runs on a cached SQLite universe and would gain nothing from a 250-req/day REST screener.

### ❌ 3. The `financedatabase` **runtime package** — vendor the data instead
It is 30 KB of code whose only function is `requests.get` a 14.6 MB bz2 and build a 187 MB DataFrame, with no memoisation, on every call. It hard-depends on `financetoolkit`, dragging a whole quant toolkit and an FMP code path into a service that needs neither. **Take the 14.58 MB file; leave the 30 KB package.**

### ❌ 4. FinanceDatabase as a **join key** for anything Indian — **ISIN is 2.4% filled**
Measured: `isin` 137/5,680 Indian rows (2.4%) vs 27.0% globally; `cusip` 2.1%; `figi` 15.2%. Any cross-reference, dedup or corporate-action join keyed on ISIN silently drops ~97% of Indian names. Use `mic` (`XNSE`/`XBOM`, 100% filled) and `delisted` (100%) instead. Likewise do not filter on `industry` for India — 33% filled.

### ❌ 5. FinanceDatabase as FinEngine's **universe of record**
1,716 `.NS` symbols vs 3,793 `.BO`, with only 1,508 companies on both. A `.BO`-only company has no `.NS` symbol, and FinEngine is `.NS`-first. This is a *partial, asymmetric enrichment*, not a universe. Keep FinEngine's own NSE listing as the source of truth.

### ❌ 6. `shashankvemuri/Finance` — in any form
- **Indian tickers are structurally impossible**: `normalize_ticker` does `.replace(".", "-")` → `RELIANCE.NS` → `RELIANCE-NS`.
- **`pip install finance` installs the wrong package** — a 2014 Python-2 fixed-income library by a different author. Nothing is published under any usable name.
- **Version `0.0.0`**, never released, 16 months silent then a full rewrite in one commit on 2026-09-07. The 4.3k stars are inherited from deleted code.
- **pandas 3.0.6 compatibility is unverified**; its own dev extra pins `ta` 0.11.0 (unmaintained since 2023-11-02).
- **The only thing it could contribute** — 6–8 indicators `stockstats` lacks (Ichimoku, Ultimate Oscillator, Fibonacci levels, Envelopes, Gann fan, Green Line, Arms Index, RVI) — costs ~60 lines to hand-write from public definitions, with no licence-provenance ambiguity (its README credits a GPL-3.0 upstream).

### ❌ 7. Replacing `indicators_service.py` with **any** of the three
`indicators_service.py` is not a thin wrapper. It encodes house contracts that took real debugging: the `mfi × 100` scale fix (`:154-159`, because installed stockstats returns a 0–1 fraction while the API documents the conventional 0–100 oscillator), a row-count assertion guarding stockstats' lazy `wrap()` (`:136-137`), and NaN-masking of any row with non-finite or non-positive prices (`:160-176`). Reimplementing 13 indicators across any of these three libraries means re-verifying every one of those guards, for a delta of at most a handful of new indicators.

**If FinEngine wants more indicators, extend `SUPPORTED_INDICATORS` in place and keep `stockstats` (which already exposes ~150).**

### ❌ 8. `pip install finance` — actively dangerous
PyPI `finance` 0.2502 is a 2014 Python-2 fixed-income library (`bankdate`, `dateflow`, Nelson-Siegel yield curves) by **Niels Henrik Bruun**, sdist-only, no wheel, `requires_python: null`, and its README still contains `print t1 + '3m'`. The shashankvemuri project is published under **no** PyPI name (`finance-toolkit`, `finance-toolkit-py`, `shashank-finance` all 404). Any onboarding note, Dockerfile or CI step that says `pip install finance` for the shashankvemuri library is installing someone else's abandoned code. Also note the *name* trap in reverse: `financetoolkit` (JerBouma, the library we DO want) vs `finance-toolkit` (shashankvemuri's `project.name`, unpublished) — two different projects, near-identical names.

### ❌ 9. Adopting all three "because they're MIT"
Licensing is a solved problem for all three (all MIT, no copyleft, no BSL, no commercial restriction). That is the *easy* axis and it decided nothing. The decision was made on four others: Indian ticker support, pandas 3.0 compatibility, maintenance reality, and overlap with ~11,000 lines of existing FinEngine services. **MIT was never the binding constraint.**

---

## Appendix — sources

| Claim | Source |
|---|---|
| **Context7 IDs** `/jerbouma/financetoolkit` (384 snippets, High reputation, benchmark 82.5) and `/jerbouma/financedatabase` (524 snippets, High, benchmark 100) | Context7 `resolve-library-id` |
| **No Context7 entry for shashankvemuri/Finance** — 2 attempts (`shashankvemuri Finance`, `finance-toolkit shashank`) returned only `/verdenroz/finance-query` (Rust), `/ebradyjobory/finance.js`, `/railpath/finance-toolkit` (TypeScript) | Context7 `resolve-library-id` |
| **No pandas/numpy version docs in Context7** for FinanceToolkit → `pyproject.toml` is the sole authority for the compatibility table | Context7 `query-docs` (returned "No documentation … matched this query") |
| `Economics` and `FixedIncome` are **standalone** classes, not `companies.economics` / `companies.fixedincome`; "can be utilized as a standalone component" | Context7 → `examples/Finance Toolkit - 9. Economics Module.ipynb`, `10. Fixed Income Module.ipynb` |
| ✅ **India supported by `Economics`**: `get_government_expenditure(countries=['Japan','China','India'])` returns an `India` column | Context7 → `economics_controller.py` docstring; corroborated by grep of the source |
| `Economics` = 60+ countries, 50+ indicators, 5 categories; 73 public methods; `get_currency_crisis`/`get_banking_crisis`/`get_sovereign_debt_crisis` exist | Context7 README; method extraction from `economics_controller.py` |
| FRED key needed **only** for US-specific series (`_require_fred_api_key`); India served by OECD + IMF GMDB | [`economics/fred_model.py`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/financetoolkit/economics/fred_model.py) docstring ("Requires a free FRED API key") + `economics_controller._require_fred_api_key` |
| 🔴 **`ratios.get_forward_price_earnings_ratio()` / `..._growth_ratio()` require FMP Premium** | Context7 → `examples/Finance Toolkit - 3. Ratios Module.ipynb` ("requiring a Premium FMP subscription"); `ratios_controller._get_or_fetch_analyst_estimates` |
| ✅ **Breadth indicators are cross-sectional across all tickers in the instance**, not per-ticker | Context7 → `examples/Finance Toolkit - 6. Technicals Module.ipynb` |
| ✅ **Official offline seam**: "data-agnostic … any provider, including Intrinio, OpenBB, Yahoo Finance, and Quandl"; `get_normalization_files()`, `format_location`, `reverse_dates`, column B must stay unchanged | Context7 → `examples/Finance Toolkit - Using External Datasets.ipynb` |
| `get_historical_data(period="weekly")` uses `period=` not `interval=`; statements return a 3-level MultiIndex `(ticker, line item, period)`; `get_income_statement(growth=True)` | Context7 → `examples/Finance Toolkit - 1. Getting Started.ipynb` |
| `get_intrinsic_valuation(0.05, 0.025, 0.094)` = 3 positional floats; `get_weighted_average_cost_of_capital(standardize=, show_full_results=, growth=, lag=)`; `get_piotroski_score().loc[:, "Piotroski Score", :]` | Context7 → `examples/Finance Toolkit - 4. Models Module.ipynb` |
| `risk.get_value_at_risk(period=, rolling=)`, distributions `historical\|gaussian\|student-t\|cornish-fisher\|evt`; `get_conditional_drawdown_at_risk`; `get_tail_ratio` | Context7 → `examples/Finance Toolkit - 7. Risk Module.ipynb` + README APIDOC block |
| FMP free tier 250 req/day, 5 yr, US exchanges only; `enforce_source` semantics (FMP-first with Yahoo fallback) | Context7 → `examples/Finance Toolkit - 1. Getting Started.ipynb` API Requirements + README Installation |
| `models` = "over 10 different financial models … DuPont, WACC, EVA, Altman Z, Beneish M, Graham Number"; `technicals` = "over 40 technical indicators" in 4 groups | Context7 → README (note: README says 500+/150+ elsewhere — count differs by module) |
| ✅ **`base_url` is a real `FinanceDatabase.__init__` / `show_options` param** → `fd.Equities(base_url="/path/to/compression/", use_local_location=True)` | Context7 → `_autodocs/09-configuration-and-initialization.md`, `07-base-classes.md` |
| Documented 20-column Equities schema; ⚠️ **omits `summary`**, which I measured as a real column; `country` documented as "**Headquarters country**" | Context7 → `_autodocs/08-types-and-data.md` |
| ✅ `exchange` option list contains `'BSE'`, `'NSE'`, `'NSI'`; `market` contains `'BSE India'` — matches my measurement exactly | Context7 → README `show_options('equities')` output |
| `search(**kwargs)` flags: `case_sensitive`, `only_primary_listing`, `index='.F'`, `exclude_delisted`; `equities.search(index='.NS')` therefore works | Context7 → `_autodocs/02-equities-api.md` |
| ✅ **FinanceToolkit import is lazy** in `to_toolkit` → `ImportError: To use the 'to_toolkit' functionality, it requires installation of the FinanceToolkit` (mitigates but does not remove the hard-dep risk) | Context7 → `_autodocs/09-configuration-and-initialization.md` |
| `show_options(category, base_url, use_local_location)` is free (does not load big files) | Context7 → `_autodocs/07-base-classes.md` |
| FinanceToolkit version 2.2.0, deps, `pandas>=3.0`, MIT, classifiers | [`pyproject.toml`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/pyproject.toml) — **authoritative** |
| FinanceToolkit license text (MIT, © 2025) | [`LICENSE.txt`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/LICENSE.txt) |
| FinanceToolkit release dates, stars, issues, `pushed_at`, repo size | [releases API](https://api.github.com/repos/JerBouma/FinanceToolkit/releases) · [repo API](https://api.github.com/repos/JerBouma/FinanceToolkit) |
| FinanceToolkit PyPI metadata, wheel 0.97 MB `py3-none-any` | [PyPI JSON](https://pypi.org/pypi/financetoolkit/json) |
| FMP free-tier limits, `enforce_source` semantics, affiliate disclosure | [README](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/README.md) |
| Yahoo data path, `.history(auto_adjust=False)`, `YFRateLimitError` handling | [`yfinance_model.py`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/financetoolkit/yfinance_model.py) |
| Undeclared `scipy` import | [`risk/var_model.py`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/financetoolkit/risk/var_model.py) |
| Global cache registry, `%APPDATA%` path, `FINANCE_TOOLKIT_CACHE_DB` | [`cache/cache_controller.py`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/financetoolkit/cache/cache_controller.py) |
| `Toolkit.__init__` signature (20 params incl. `enforce_source`, `historical=`) | [`toolkit_controller.py`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/financetoolkit/toolkit_controller.py) |
| Method catalogues (technicals 59, risk 50, performance 37, models 27, ratios ~90) | `*/*_controller.py` on `main`, extracted programmatically |
| `Discovery` is FMP-only | [`discovery/discovery_model.py`](https://raw.githubusercontent.com/JerBouma/FinanceToolkit/main/financetoolkit/discovery/discovery_model.py) |
| FinanceDatabase version 2.4.0, `financetoolkit>=2.0.3,<3.0.0` | [`pyproject.toml`](https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/pyproject.toml) |
| FinanceDatabase license (MIT, © 2023) | [`LICENSE`](https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/LICENSE) |
| FinanceDatabase PyPI metadata, wheel 0.03 MB | [PyPI JSON](https://pypi.org/pypi/financedatabase/json) |
| FinanceDatabase commit cadence, last commit 2026-09-20 | [commits page](https://github.com/JerBouma/FinanceDatabase/commits/main) |
| `DATA_REPO`, `compression/`, `bz2` read args, no memoisation | [`financedatabase/helpers.py`](https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/financedatabase/helpers.py) |
| `Equities.FILE_NAME = "equities.bz2"`, `select()` signature, `raise ValueError` on unknown country | [`financedatabase/Equities.py`](https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/financedatabase/Equities.py) |
| `FinanceFrame.to_toolkit` defaults (`risk_free_rate="10y"`, `benchmark_ticker="SPY"`) | [`financedatabase/helpers.py`](https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/financedatabase/helpers.py) |
| **All FinanceDatabase numbers** (112,707 rows; India 5,680; `.NS` 1,716; `.BO` 3,793; 187 MB RAM; ISIN 2.4%; `industry` 33%; `sector` 91.0%) | **Downloaded `equities.bz2` (14,289,215 B) and parsed with pandas 3.0.6 using the library's own `read_csv` arguments. Raw output reproduced in the Data dependency chain section.** |
| bz2 sizes for all 7 asset classes | HTTP `HEAD` on `raw.githubusercontent.com/.../compression/*.bz2` |
| shashankvemuri/Finance `version = "0.0.0"`, `requires-python = ">=3.12"`, `pandas>=2.2,<4`, `numpy>=2.0,<3`, extras incl. `ta>=0.11,<1` | [`pyproject.toml`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/pyproject.toml) |
| shashankvemuri/Finance license (MIT, © 2021 Shashank Vemuri) | [`LICENSE`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/LICENSE) |
| **Commit history: 2024-08 → 2025-05-12 → 2026-09-07 rewrite → 2026-09-12; default branch `master`; 1,279 commits; 0 open issues** | [commits page](https://github.com/shashankvemuri/Finance/commits/master) · [repo page](https://github.com/shashankvemuri/Finance) |
| `normalize_ticker` `.replace(".", "-")` + regex | [`src/finance/data/normalize.py`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/src/finance/data/normalize.py) |
| `YahooFinance._ticker` uses `normalize_ticker` + `curl_cffi` | [`src/finance/data/providers.py`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/src/finance/data/providers.py) |
| `exchange_universe` = Nasdaq Trader; `sp500_constituents` = Wikipedia; `dividend_calendar` = api.nasdaq.com | same |
| "normalize_ticker … not every exchange suffix convention"; US-only provider list; no cross-provider fallback | [`docs/providers.md`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/docs/providers.md) |
| 70-function indicator catalogue + exact signatures (`rsi` body, `macd`, `stochastic`, …) | [`src/finance/indicators/__init__.py`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/src/finance/indicators/__init__.py) · [`momentum.py`](https://raw.githubusercontent.com/shashankvemuri/Finance/master/src/finance/indicators/momentum.py) — **official-source fallback; no Context7 entry exists** |
| "Technical-indicator references include Stock_Analysis_For_Quant by LastAncientOne" (GPL-3.0 upstream) | [README](https://raw.githubusercontent.com/shashankvemuri/Finance) |
| **PyPI `finance` 0.2502 is by Niels Henrik Bruun, uploaded 2014-03-24, sdist-only, `requires_python: null`, py2 syntax in description** | [PyPI `finance`](https://pypi.org/project/finance/) |
| `finance-toolkit` / `finance-toolkit-py` / `shashank-finance` not on PyPI (HTTP 404) | [PyPI 404s](https://pypi.org/project/finance-toolkit/) |
| `ta` 0.11.0 uploaded 2023-11-02, MIT, no `requires_dist` | [PyPI `ta`](https://pypi.org/pypi/ta/json) |
| FinEngine local stack versions (Python 3.12.9, pandas 3.0.6, numpy 2.5.3, …) | `uv run python -c "import importlib.metadata"` in `backend/` |
| FinEngine `SUPPORTED_INDICATORS` (13), `mfi × 100` fix, row-count assertion, NaN masking | [`services/indicators_service.py`](C:/es/coding/finengine/backend/app/services/indicators_service.py) L34-53, L136-137, L154-176 |
| FinEngine `company_data_service.py` ₹ house contract + `getattr(t, 'piotroski_score')` | L183-186, L201-205 |
| FinEngine `optimization_service.py` strategies, `_min_cvar` LP, `expected_sharpe_basis` provenance | L53, L348-362, L652-666 |
| FinEngine `analytics_engine.py` bootstrap/block-bootstrap/effective-N | L628, L661, L793, L1053, L1155, L1190 |
| FinEngine `backend/data/nse/` exists (empty); `daisy.db` 16 MB + `backups/` | `Get-ChildItem backend\data -Recurse` |
| FinEngine dependency pins + two-extra-table rule | [`backend/pyproject.toml`](C:/es/coding/finengine/backend/pyproject.toml) · `AGENTS.md` |

**Not verified (flagged inline above):** FMP's current paid-tier pricing (the `site.financialmodelingprep.com/pricing` URLs 404'd); the redistribution rights of FinanceDatabase's vendor-derived ISIN/CUSIP/FIGI identifiers; shashankvemuri/Finance's behaviour under pandas 3.0.6 / numpy 2.5.3.
