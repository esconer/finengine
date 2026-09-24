# Financial Reconciliation

Status: complete with explicit `UNVERIFIABLE` / `NOT TESTED` limitations. Every checked value receives one verdict: `VERIFIED`, `DISCREPANCY`, `STALE`, `UNVERIFIABLE`, `MOCK/DEMO`, or `NOT TESTED`. The explicit count ledger is `evidence/calculations/outputs/financial-verdict-ledger.md`.

## Confirmed calculations

### Zero-state first position

| Value | Expected | Observed | Difference | Verdict |
|---|---:|---:|---:|---|
| First-position weight | `1.0` / `100.00%` | `1.0` / `100.00%` | 0 | `VERIFIED` |
| First-position market value | `10 × 1227 = ₹12,270` | `₹12,270` | ₹0 | `VERIFIED` |
| First-position cost basis | `10 × 1000 = ₹10,000` | Implied ₹10,000 | ₹0 | `VERIFIED` |
| First-position unrealized P&L | `₹12,270 − ₹10,000 = ₹2,270` | `+₹2,270` | ₹0 | `VERIFIED` |

Evidence: `evidence/network/pages/desktop/states/single-holding-after-add.txt` and raw add request.

### Single-holding diversification

| Value | Expected | Observed | Verdict |
|---|---:|---:|---|
| Diversification score | `0%` for N≤1 | `0.0%` | `VERIFIED` |
| Weight | `100%` | `100.00%` | `VERIFIED` |

### Empty portfolio diversification

| Value | Expected | Observed | Verdict |
|---|---|---|---|
| Diversification score | N/A / unavailable | `0.0%` | `DISCREPANCY` |

### Seeded concentration

Independent Decimal replay from the INR portfolio and returned FX snapshot:

- HHI: `0.5956494140543129443` (API `0.5956`).
- Effective holdings: `1.6788398954234802` (API `1.68`).
- N-normalized diversification: `50.5436%` (API concentration endpoint `50.5`).
- Gini: `0.629...` (API `0.629`).

The concentration API is arithmetically correct for FinEngine's returned quotes, but Dashboard uses a separate native-value/effective-N/sector-multiplier heuristic and displayed `18.7%`. This is a reproducible `DISCREPANCY`, not rounding: the dashboard calculation mixes native USD market values with an INR-converted total and does not use the canonical HHI diversification field. Because AAPL's quote is itself discrepant, neither 50.5% nor 18.7% is externally validated as true real-market diversification.

Evidence: `evidence/calculations/outputs/portfolio-reconciliation.md` and `evidence/network/pages/desktop/states/concentration-api.json`.

### Native position arithmetic

| Ticker | Formula | Expected native value | API value | Verdict |
|---|---|---:|---:|---|
| RELIANCE.NS | `10 × 1227` | ₹12,270 | ₹12,270 | `VERIFIED` |
| HDFCBANK.NS | `20 × 730` | ₹14,600 | ₹14,600 | `VERIFIED` |
| TCS.BO | `15 × 2089` | ₹31,335 | ₹31,335 | `VERIFIED` |
| AAPL | `5 × 4.89` | $24.45 | $24.45 | Arithmetic `VERIFIED`; quote `DISCREPANCY` versus ~$336.16 external observation |
| MSFT | `4 × 493.19000244140625` | $1,972.760009765625 | $1,972.760009765625 | Arithmetic `VERIFIED`; quote `STALE`/timing-sensitive versus $495.07 observation |

### Mixed-currency portfolio P&L

| Value | Same-current-FX INR reference | Observed Dashboard | Difference | Verdict |
|---|---:|---:|---:|---|
| Cost basis | ₹244,592.7494 | Implied mixed-native ₹59,450 used by frontend | ₹185,142.7494 | `DISCREPANCY` |
| Unrealized P&L | ₹5,234.5644 | +₹190,377.31 | ₹185,142.7456 | `DISCREPANCY` |
| Unrealized return | ~2.14% | +320.23% | ~318.09 percentage points | `DISCREPANCY` |

The reference intentionally uses the same current FX snapshot for both current value and cost and is conditional on the discrepant AAPL quote. True acquisition-date historical-FX cost/P&L is `UNVERIFIABLE` because dated USD/INR costs were not returned. The displayed result remains a core financial-reporting error because it subtracts values denominated in different currencies.

### Mixed-currency portfolio

Observed live FX provenance: `USD→INR = 95.94499969482422`, source yfinance, provenance live, fetched `2026-09-24T15:11:58.368908+00:00`.

- Sum of native position values: `12,270 + 14,600 + 31,335 + 24.45 + 1,972.760009765625 = 60,202.21000976563` in mixed native units.
- Correctly converted INR total from API: `249,827.31377746275`.
- Headline USD conversion: `$2,603.8596547198676` using reciprocal rate.
- INR→USD reciprocal from the same returned pair is `0.010422638002821791`; total replay error is approximately `-2.55e-13` USD: `VERIFIED`.

### USD Portfolio Management page

| Value | Expected consistent USD total | Observed | Verdict |
|---|---:|---:|---|
| Headline total | $2,603.86 | $2,603.86 | `VERIFIED` |
| Sum of displayed row current values | $2,603.86 | $60,202.21 | `DISCREPANCY` |
| Total investment card | $2,549.3017 | $59,450.00 native mixed sum | `DISCREPANCY` |
| Current value card | $2,603.8597 | $60,202.21 native mixed sum | `DISCREPANCY` |
| Total gain/loss | $54.5580 / ~2.14% | $752.21 / +1.27% | `DISCREPANCY` |
| Indian row values under USD selection | Converted or explicitly native-labeled | INR values with `$` prefix | `DISCREPANCY` |

Evidence: `evidence/screenshots/states/portfolio-manage-usd.png`, `portfolio-manage-usd.txt`, and `portfolio-usd-api.json`.

### External quote spot checks

| Ticker | FinEngine | Independent observation | Difference | Verdict |
|---|---:|---:|---:|---|
| AAPL | $4.89 | ~$336.16 | ~$331.27 / ~98.5% | `DISCREPANCY` |
| MSFT | $493.1900 | $495.07 | $1.88 / ~0.38% | `STALE` / timing-sensitive |
| RELIANCE.NS | ₹1,227.00 | ₹1,238.40 | ₹11.40 / ~0.92% | `STALE` / `DISCREPANCY` |
| HDFCBANK.NS | ₹730.00 | ₹727.70–₹729.80 | ~₹0.20–₹2.30 | `VERIFIED` within intraday timing tolerance |
| TCS.BO | ₹2,089.00 | ₹2,090.60 | ₹1.60 / ~0.08% | `VERIFIED` within intraday timing tolerance |

Official Nasdaq/NSE numeric pages were not available to the fetcher; values are secondary-source spot checks and not represented as official exchange certification. See `evidence/calculations/inputs/external-market-crosscheck.md`.

## Direct API and independent replay coverage

- Direct API capture: **79/79 calls returned 2xx**; no HTTP or transport errors. Latency was 2.6 ms minimum, 82.3 ms median, and 21,704.4 ms maximum.
- Core replay: **253 checks — 153 VERIFIED/MATCH, 73 DISCREPANCY, 27 UNVERIFIABLE/UNDERDETERMINED**.
- Advanced replay: **248 checks — 187 VERIFIED/PASS, 5 DISCREPANCY/FAIL, 56 UNVERIFIABLE/UNDERDETERMINED**.
- The replay labels are conservative: a model-family mismatch is not promoted to a confirmed implementation bug when the response omits the required alignment, annualization, fit, or raw-sample contract.

### Advanced replay highlights

- `VERIFIED` under the captured rounded-data convention: EVT/POT VaR `0.034130` and ES `0.048014`; 10 cointegration pairs scanned with 0 selected; all five optimizer long-only weight/trade/Sharpe invariants; rounded backtest CAGR, volatility, drawdown, Calmar, benchmark, event-count, and turnover invariants.
- `VERIFIED` as deterministic invariants: Monte Carlo returned 2,000 paths and 11 fan checkpoints for each method, with success counts `1240`, `1222`, and `1207`.
- `UNVERIFIABLE`: exact stochastic paths, HRP/CVaR/Black-Litterman objectives, unrounded backtest path, regime fit, exact correlation/coint/vol-cone frames, Amihud thresholds, and empty India delivery/flow rows.


| Model family | Checks | VERIFIED/MATCH | DISCREPANCY | UNVERIFIABLE |
|---|---:|---:|---:|---:|
| Concentration | 9 | 8 | 0 | 1 |
| Factor exposure | 27 | 6 | 19 | 2 |
| EWMA forecast | 20 | 19 | 0 | 1 |
| GARCH forecast | 20 | 17 | 2 | 1 |
| EGARCH forecast | 20 | 14 | 5 | 1 |
| Heuristic liquidity | 28 | 16 | 0 | 12 |
| Liquidity limits | 26 | 23 | 1 | 2 |
| Portfolio arithmetic | 4 | 3 | 1 | 0 |
| Realized risk | 48 | 13 | 33 | 2 |
| Risk contribution | 15 | 5 | 9 | 1 |
| Volatility sizing | 36 | 29 | 3 | 4 |

The largest confirmed input/model discrepancies are:

- `DISCREPANCY`: AAPL quote `4.89` versus same-date captured history near `336.29` and independent observation near `336.16`.
- `DISCREPANCY`: measured liquidity portfolio value `60,209.28` native-mixed versus INR portfolio `250,555.75`.
- `DISCREPANCY`: EGARCH portfolio/RELIANCE fallback values (`0.05` / `-0.001`) versus non-flat independent fits; exact fit metadata remains `UNVERIFIABLE`.
- `DISCREPANCY`/contract-dependent: realized-risk, factor-exposure, risk-contribution, and volatility-sizing fields with documented alignment/annualization/tail-method differences.
- `VERIFIED`: concentration HHI/effective-holdings/Gini arithmetic, most EWMA forecast fields, ADV/position-limit arithmetic, and the five-position/zero-state invariants.

Full ledgers, formulas, sample windows, tolerances, and every discrepancy key are in `evidence/calculations/outputs/independent-core-models.json` and `independent-advanced-models.json`.

## Financial verdict ledger

The following labels are used throughout the audit:

- `VERIFIED`: independently recomputed or directly cross-checked within the stated tolerance.
- `DISCREPANCY`: captured value conflicts with the independent calculation or another captured contract.
- `STALE`: timing/provider freshness cannot be established, or the value differs only by a time-sensitive market movement.
- `UNVERIFIABLE`: required raw history, FX, provider identity, or model contract was not returned.
- `MOCK/DEMO`: synthetic/demo-only evidence; not a real-market claim.
- `NOT TESTED`: workflow or value was not exercised.

The portfolio-level financial checks are `VERIFIED` for first-position 100% weight, single-holding 0% diversification, native row arithmetic, INR FX conversion, and concentration arithmetic. They are `DISCREPANCY` for Dashboard P&L, USD row labels, AAPL quote, and measured liquidity portfolio value. Historical mixed-currency returns, exact quote freshness, and several model fit contracts are `UNVERIFIABLE`; the isolated fixture itself is `MOCK/DEMO` evidence only.

## Underdetermined values

- True holding-period realized P&L/TWR/MWR: no transaction/cash/dividend/fee ledger.
- Mixed-currency historical portfolio returns: no daily historical FX series.
- AAPL quote `4.89`: arithmetic is internally consistent, but multiple secondary current observations indicate a material quote discrepancy; exact upstream provider remains unknown.
- Company/FII/delivery/shareholding fields: direct source reconciliation pending.
- Model metrics: direct API capture and offline replay completed; exact contracts remain underdetermined where raw fit/alignment metadata is absent.
- Optimizer, Monte Carlo, backtest, regime, tails/copula, and correlation/pairs outputs: 187 advanced checks passed, 5 failed, and 56 were underdetermined in the captured-evidence replay.

## Required final rate reporting

Report separately:

1. Total values checked.
2. `VERIFIED` count/rate.
3. `DISCREPANCY`, `STALE`, and `UNVERIFIABLE` counts.
4. `NOT TESTED` count.
5. Values whose provider matched the independent reference and values independently recalculated from raw data.
