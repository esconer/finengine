# 06 — Risk & Liquidity review (v5 AI-context export)

- **Artifact:** `C:\es\others things\finengine-portfolio-ai-context v5.json` (876 KB)
- **Export:** `portfolio-4b78905b588c`, `schema_version 2.0`, `base_currency INR`
- **Book:** 14 legs, **total value INR 43,608.67**, 1 micro-cap (`SELECTIPO.NS`), 1 small cap (`MAFANG.NS`), 3 ETFs, 1 recent listing (`ARROWGREEN.NS`)
- **Sections owned here:** `liquidity`, `risk_score` (dashboard component), `stress_testing`, `risk_studio` (tail / correlation-stability / vol-cone), `volatility_sizing` (cross-section), `concentration`, `dashboard` as a risk surface
- **Ground truth:** `backend/app/api/analytics.py`, `backend/app/services/analytics_engine.py`, `backend/app/services/tail_risk_service.py`, `backend/app/services/volatility_service.py`

---

## Verdict

**The risk numbers are arithmetically right and mostly honestly disclosed, but three of them are the wrong quantity entirely, and one piece of published advice is not executable.** Every score I tried to reproduce reproduced *exactly* — the liquidity bands, the HHI, the four stress scenarios (56/56 position impacts, 0 mismatches), the weighted-sum portfolio impact, the risk-score composition (drift 0.01 from 1-dp rounding), the inverse-vol sizing weights (6 dp), the VaR/ES ordering. The engineering discipline on *labelling* is unusually good: `market_cap_provenance`, `spread_basis: model_assumed / observed: false`, `pot_threshold_basis`, `gpd_shape_xi_used`, `annualized_note`, `per_ticker_count_reconciliation` are all real and all correct. **But labelling cannot rescue a wrong number.** `liquidation_days` is a constant string attached to a turnover tier — it never touches position size, ADV or participation, and on this book it overstates the worst leg's true horizon by ~10,700× in days (`SELECTIPO.NS` publishes "5-10 days"; the real number is 60.6 seconds at 100% of ADV). `is_fat_tailed: true` is published directly beside a GPD shape of **−0.7068** (raw) and **−0.5** (used) — both firmly *light*-tailed — with no basis field, so the one word a risk manager keys on contradicts the model. And **35% of the risk score is structurally pinned**: `market_risk` (weight 0.10) is byte-identical to `volatility` (weight 0.25) because `tail(60)` over 38 returns is the entire series, and `factor_risk` (weight 0.25) is saturated at the 0-30 maximum for any R² ≤ 0.70 — the published R²=0.2391 comes from a **36-row** OLS fit, so that leg contributes a flat 7.5 of the 13.7 total no matter what the book looks like. The **tail numbers are measured, not assumed — but on the wrong portfolio**: 518 return rows for a book that has existed 39 days, undisclosed, while `risk_contribution` in the *same* `risk_studio` section does publish the 251-vs-39 split. **Executability: the sizing advice is volume-executable and financing-in executable.** Every trade is ≤ 0.1356% of that leg's one-day ADV (0 breaches) — the P0 I was told to look for does not exist here. What *does* exist is that `recommended_weights` sum to **1.295310**, the section reads `status: available` with `warnings: []`, and executing it needs **INR 12,878 of borrowing on a INR 43,609 book**. That is flagged in `execution.execution_eligible: false`, buried one level down, and a dashboard consumer sees a clean green tile. **The single most misleading number in the artifact is `diversification_score: 98.4`** — arithmetically correct as a sleeve-evenness measure, published with no look-through caveat anywhere (0 occurrences of "look-through", "underlying" or "index constituents" in 876 KB), on a book where 25% is three index ETFs that hold the same midcaps held directly and 32.1% sits in a single sector bucket that has two single stocks misfiled into it.

---

## Findings, ranked

### RL-1 · **P0** · `liquidation_days` is a score-band label, not a liquidation horizon

**JSON path** `sections.liquidity.data.by_position.*.liquidation_days`, `sections.liquidity.data.liquidation_time_days`

**Observed.** Every leg's `liquidation_days` is exactly one of three strings — `"1-2"`, `"2-5"`, `"5-10"` — and the string is a pure function of the rounded liquidity score. `SELECTIPO.NS` (4.33% of book, INR 1,888.00) publishes `"5-10"`. `JUNIORBEES.NS` (12.47%, INR 5,436.83) publishes `"1-2"`, identical to `ELECTCAST.NS` (3.32%, INR 1,446.80). Position size, `avg_turnover` and participation rate appear nowhere in the derivation. The ADV that *is* published (`avg_turnover`) is never combined with the position value.

**Expected + recomputation evidence.** `days = position_value / (avg_turnover × participation)`.

```
$ cd C:\es\coding\finengine\backend
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
bp=d['sections']['liquidity']['data']['by_position']
pos={x['ticker']:x for x in d['sections']['portfolio']['data']['positions']}
print('BOOK VALUE = INR %.2f'%sum(x['market_value'] for x in pos.values()))
for t,x in pos.items():
    adv=bp[t]['avg_turnover'];v=x['market_value']
    print('%-15s %9.2f %7.2f%% %13.0f %12.6fd %10.1fs published=%s'%(t,v,x['weight']*100,adv,v/adv,v/adv*86400,bp[t]['liquidation_days']))
"@

BOOK VALUE = INR 43608.67
CIPLA.NS            2799.40   6.42%    1201357008  0.000002d        0.2s published=1-2
ELECTCAST.NS        1446.80   3.32%     155218015  0.000009d        0.8s published=1-2
MOTILALOFS.NS       3087.00   7.08%     766693979  0.000004d        0.3s published=1-2
ARROWGREEN.NS       3623.20   8.31%      49207138  0.000074d        6.4s published=2-5
JKIL.NS             2841.30   6.52%      20949244  0.000136d       11.7s published=2-5
NTPC.NS             3266.00   7.49%    2627754006  0.000001d        0.1s published=1-2
MCX.NS              3324.90   7.62%    6490322599  0.000001d        0.0s published=1-2
MOTHERSON.NS        5965.56  13.68%    1810544814  0.000003d        0.3s published=1-2
REDINGTON.NS        3258.00   7.47%    2687318276  0.000001d        0.1s published=1-2
NIFTYIETF.NS        1050.68   2.41%     148558989  0.000007d        0.6s published=1-2
MIDCAPIETF.NS       4428.90  10.16%      24933476  0.000178d       15.3s published=2-5
JUNIORBEES.NS       5436.83  12.47%     228311116  0.000024d        2.1s published=1-2
MAFANG.NS           1192.10   2.73%     163685060  0.000007d        0.6s published=1-2
SELECTIPO.NS        1888.00   4.33%       2690584  0.000702d       60.6s published=5-10
```

Worst true horizon = `SELECTIPO.NS` at **0.000702 d = 60.6 s** at 100% of ADV (303.1 s at a realistic 20% participation). Published worst = `"5-10"`. **Overstatement ≈ 10,700× in days.** The adverse case in the brief is real but points the other way: the 12.47% low-turnover ETF sleeve (`JUNIORBEES`) and the 3.32% large-cap (`ELECTCAST`) both publish `"1-2"`, while the true ratio `ELECTCAST/JUNIORBEES = 0.4×` says ELECTCAST is the *easier* leg. The published ordering carries no executability information at all.

**Root cause.** `analytics_engine.py:93-97` — `liquidity_days` is a literal in `LIQUIDITY_SCORE_BANDS`; `analytics_engine.py:161-167` `_liquidity_band()` returns it; `analytics_engine.py:518` `category, liquidation_days = _liquidity_band(score)`. No size, no ADV, no participation rate reaches it.

**Confidence.** **High.** Recomputed from the export's own `market_value` and `avg_turnover`; the code path has no other input.

---

### RL-2 · **P0** · `is_fat_tailed: true` published beside a GPD shape of −0.71 / −0.5 (light tail)

**JSON path** `sections.risk_studio.data.components.tail_dependence.data.{is_fat_tailed, gpd_shape_xi, gpd_shape_xi_used, gpd_shape_xi_raw}`

**Observed.** `is_fat_tailed: true`. `gpd_shape_xi: -0.7068`, `gpd_shape_xi_raw: -0.70676185`, `gpd_shape_xi_used: -0.5`, `gpd_shape_xi_basis: "constrained_clip"`. In a GPD, ξ > 0 is heavy (Pareto) tailed; ξ < 0 is **bounded / light** tailed with a finite upper endpoint. Both published values are negative. The one word a risk manager keys on says the opposite of the model. There is **no `is_fat_tailed_basis` field** (verified: `'is_fat_tailed_basis' in td → False`), so the reader cannot tell the flag is a kurtosis/VaR-comparison statistic wearing a GPD name.

**Expected + recomputation evidence.**

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
td=d['sections']['risk_studio']['data']['components']['tail_dependence']['data']
print('xi raw=%s  xi used=%s  is_fat_tailed=%s'%(td['gpd_shape_xi_raw'],td['gpd_shape_xi_used'],td['is_fat_tailed']))
print('disjunct xi_raw>0.05 ->', td['gpd_shape_xi_raw']>0.05)
print('disjunct var_evt>hist_var ->', abs(td['evt_pot_var'])>abs(td['historical_var']), abs(td['evt_pot_var']), abs(td['historical_var']))
print('is_fat_tailed_basis present?','is_fat_tailed_basis' in td)
"@

xi raw=-0.70676185  xi used=-0.5  is_fat_tailed=True
disjunct xi_raw>0.05 -> False
disjunct var_evt>hist_var -> True 0.036708 0.031724
is_fat_tailed_basis present? False
```

The flag fires on the third disjunct (`var_evt_loss > hist_var_loss`, 3.6708% > 3.1724%) — a statement that the POT estimate exceeds the empirical one, which is what a *light-tailed* GPD does. The second disjunct (`excess_kurt > 0.5`) is **not published anywhere**, so the reader cannot even reconstruct which disjunct fired.

**Root cause.** `tail_risk_service.py:173-181` — `is_fat_tailed = bool((xi_raw > 0.05) or excess_kurt > 0.5 or var_evt_loss > hist_var_loss)`. The field name asserts a distributional property the code decides by a three-way OR that two of three branches do not measure. The return of `excess_kurt` is discarded at `tail_risk_service.py:245`.

**Confidence.** **High** on the sign inversion (ξ is published, negative, unambiguous). **High** on the code path.

---

### RL-3 · **P0** · 35% of the risk score is structurally pinned; `factor_risk` saturated on a 36-row fit

**JSON path** `sections.dashboard.data.components.risk_score.data.{components, overall_score, risk_level, model_observation_count}`

**Observed.** `components: {concentration 8.6, volatility 9.8, correlation 5.3, factor_risk 30, market_risk 9.8}`, `overall_score 13.7`, `risk_level LOW`, `model_observation_count 36`, `factor_r_squared 0.2391`.

1. **`market_risk` is the same statistic as `volatility`.** `volatility` = `min(30, portfolio_returns.std()*√252*100)`; `market_risk` = `min(30, portfolio_returns.tail(60).std()*√252*100)`. The delivered series is 39 return rows → `tail(60)` is the whole series → the two legs are the same number. The export confirms it: both publish **9.8**. Combined weight **0.35**.
2. **`factor_risk` is saturated at the maximum.** `factor_score = min(30, (1-R²)·100) = min(30, 76.09) = 30`. That equals 30 for **any** R² ≤ 0.70. The published R²=0.2391 comes from `model_window {2026-08-04 → 2026-09-24, 36 rows}` — a 36-row OLS regression of a 14-name book on one benchmark. The leg contributes a flat **7.5 of 13.71 (55% of the headline)** and cannot move.

**Expected + recomputation evidence.**

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
rs=d['sections']['dashboard']['data']['components']['risk_score']['data']
c=rs['components'];W={'concentration':.20,'volatility':.25,'correlation':.20,'factor_risk':.25,'market_risk':.10}
print('weights sum = %.4f'%sum(W.values()))
print('RECOMPUTED overall = %.6f -> %.1f ; PUBLISHED %s ; drift %+.4f'%(sum(c[k]*W[k] for k in W),round(sum(c[k]*W[k] for k in W),1),rs['overall_score'],rs['overall_score']-sum(c[k]*W[k] for k in W)))
print('volatility==market_risk ?',c['volatility']==c['market_risk'],c['volatility'],c['market_risk'])
print('delivered return rows = 39 -> tail(60) IS the whole series')
r2=rs['factor_r_squared'];print('R2=%.4f on %d rows -> factor_score=min(30,%.2f)=%d ; equals 30 for any R2<=0.70'%(r2,rs['model_observation_count'],(1-r2)*100,min(30,(1-r2)*100)))
print('pinned weight = %.2f ; responsive weight = %.2f'%(0.25+0.10,0.20+0.25+0.20))
"@

weights sum = 1.0000
RECOMPUTED overall = 13.710000 -> 13.7 ; PUBLISHED 13.7 ; drift -0.0100
volatility==market_risk ? True 9.8 9.8
delivered return rows = 39 -> tail(60) IS the whole series
R2=0.2391 on 36 rows -> factor_score=min(30,76.09)=30 ; equals 30 for any R2<=0.70
pinned weight = 0.35 ; responsive weight = 0.65
```

**Expected.** `market_risk` must be null + `excluded` with a reason when the window is shorter than `tail(60)` (the codebase already has that exact pattern for `correlation` and `factor_risk` at `analytics_engine.py:1194-1200` / `:1229-1233`). `factor_risk` should either publish the R² at which the cap binds, or widen the cap, or be excluded when `model_observation_count` is below a stated regression minimum. **35% of a risk score that is pinned is not a risk score — it is a constant plus a third of a real one.** The export nowhere states that the two 9.8s are the same measurement or that `factor_risk` is at its ceiling.

**Root cause.** `analytics_engine.py:1237-1239` (`recent_returns = portfolio_returns.tail(60)`, unguarded) and `analytics_engine.py:1228` (`factor_score = min(30, (1 - r_squared) * 100)`), weight table at `analytics_engine.py:1244-1250`.

**Confidence.** **High.** Both pinned states are visible in the published numbers and both code paths are unguarded.

---

### RL-4 · **P1** · 99% VaR/ES and the whole tail-dependence matrix are measured on 518 rows of a 39-day-old book, undisclosed

**JSON path** `sections.risk_studio.data.components.tail_dependence.data.{total_observations, observations, tail_dependence_matrix}`

**Observed.** `total_observations: 518`, `observations: 518`. The book has existed 39 days (`history_coverage.covered_days: 39`, `portfolio_return_observations: 39`). `REDINGTON.NS` was added 2026-08-03 and `NIFTYIETF.NS`'s analytics start is inferred as 2026-05-19 — so 479 of the 518 rows predate the portfolio's existence. They are a back-cast of *today's* 14 names at *today's* weights. The section publishes no window bounds, no `start`/`end`, and no holding-window reference. The **same `risk_studio` section's `risk_contribution` component does disclose it** — `history_coverage: {covered_days: 251, holding_context: {covered_days: 39}}` — so the disclosure pattern exists in this export and was simply not applied here.

**Expected + recomputation evidence.** Either the tail fit runs on the 39 held rows (and says the EVT is not estimable — 39 rows gives ~2 exceedances at a 95% POT threshold, which is why the current design reaches for 518), or the section publishes `wide_window {start, end, rows}` beside `holding_window {start, end, rows: 39}` and states that the VaR describes a synthetic reconstruction.

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
td=d['sections']['risk_studio']['data']['components']['tail_dependence']['data']
rc=d['sections']['risk_studio']['data']['components']['risk_contribution']['data']
rs=d['sections']['dashboard']['data']['components']['risk_score']['data']
print('tail_dependence.total_observations =',td['total_observations'],' window fields present:',[k for k in td if k in ('window','start','end','lookback_days')])
print('risk_score.history_coverage.covered_days =',rs['history_coverage']['covered_days'],'portfolio_return_observations =',rs['history_coverage']['portfolio_return_observations'])
print('risk_contribution.history_coverage.covered_days =',rc['history_coverage']['covered_days'])
print('risk_contribution.history_coverage.holding_context.covered_days =',rc['history_coverage']['holding_context']['covered_days'])
"@

tail_dependence.total_observations = 518  window fields present: []
risk_score.history_coverage.covered_days = 39 portfolio_return_observations = 39
risk_contribution.history_coverage.covered_days = 251
risk_contribution.history_coverage.holding_context.covered_days = 39
```

**Root cause.** `analytics.py:7402` — `wide_ret, port_ret, _ = await _build_wide_returns(...)` takes the *third* return value (the coverage block) and discards it with `_`, then `analytics.py:7430` publishes only `observations: len(port_ret)`. The `_` at 7402 is the disclosure that was thrown away.

**Confidence.** **High.**

---

### RL-5 · **P1** · `risk_level: "LOW"` has no published thresholds anywhere, and fires alongside a "High unexplained risk" alert

**JSON path** `sections.dashboard.data.components.risk_score.data.risk_level`

**Observed.** `risk_level: "LOW"` at `overall_score 13.7`, with `alerts: ["High unexplained risk (low R-squared: 0.24)"]`. A full-text scan of the 876 KB finds exactly one `risk_level`-family key (`risk_level` itself) — **no `risk_level_rule`, no `thresholds`, no band table**, unlike the liquidity section which publishes its full band rule with thresholds. A risk manager cannot verify that 13.7 → LOW, cannot know how far the score is from the MEDIUM cut, and sees a green band next to a red alert.

**Expected + recomputation evidence.** Publish the band table the way `liquidity.scoring.bands` does.

```
$ uv run python -c @"
import json,re
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
s=json.dumps(d)
print('risk_level-family keys:',sorted(set(re.findall(r'[\"\']([a-z_]*risk_level[a-z_]*)[\"\']',s))))
print('risk_level_rule present?','risk_level_rule' in s)
print('liquidity publishes:',json.dumps(d['sections']['liquidity']['data']['scoring']['bands']))
"@

risk_level-family keys: ['risk_level']
risk_level_rule present? False
liquidity publishes: [{"band":"High","min_published_score":8,"max_published_score":null,...},{"band":"Medium",...},{"band":"Low",...}]
```

The hardcoded cutoffs are `overall_score < 15 → LOW`, `< 25 → MEDIUM`, else `HIGH` — and the 0-30 component scale is stated only in a prose `methodology` string. Note the band is on a 0-30 sub-scale with a floor: a one-name book scores `concentration 30 / volatility ~0 / correlation excluded / factor excluded / market ~0` and lands near 8 → LOW.

**Root cause.** `analytics_engine.py:1270-1275` — the thresholds are inline literals with no companion rule dict, unlike `LIQUIDITY_SCORE_BAND_RULE` at `analytics_engine.py:102-133`.

**Confidence.** **High.**

---

### RL-6 · **P1** · `MAFANG.NS` and `SELECTIPO.NS` are filed as `sector="Exchange Traded Fund", industry="ETF"`; the ETF sector bucket reads 32.10% against a true 25.03%

**JSON path** `sections.portfolio.data.positions[11,13].sector`, `sections.portfolio.data.sectors."Exchange Traded Fund"`, `sections.concentration.data.by_sector."Exchange Traded Fund"`

**Observed.** `SELECTIPO.NS` (4.33%, Select Industries — an LPG distributor) and `MAFANG.NS` (2.73%, a small-cap name) both carry `sector: "Exchange Traded Fund"`, `industry: "ETF"`. The sector rollup therefore shows **32.10%** in "Exchange Traded Fund" when the three real ETFs are **25.03%** — a **+7.06pp** overstatement of the passive sleeve. Downstream, the stress engine applies the ETF default index beta of 1.00 to two single stocks.

**Expected + recomputation evidence.**

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
p=d['sections']['portfolio']['data']
for x in sorted(p['positions'],key=lambda r:-r['weight']):
    if x['ticker'] in ('MAFANG.NS','SELECTIPO.NS','NIFTYIETF.NS','MIDCAPIETF.NS','JUNIORBEES.NS'):
        print('%-15s w=%6.2f%% sector=%-22s industry=%s'%(x['ticker'],x['weight']*100,x['sector'],x['industry']))
etf=sum(x['weight'] for x in p['positions'] if x['ticker'] in ('NIFTYIETF.NS','MIDCAPIETF.NS','JUNIORBEES.NS'))
print('true ETF weight      = %.4f%%'%(etf*100))
print('published ETF sector = %.4f%%'%(p['sectors']['Exchange Traded Fund']*100))
print('overstatement        = %+.4f pp'%((p['sectors']['Exchange Traded Fund']-etf)*100))
st=d['sections']['stress_testing']['data']['scenarios']['Interest Rate Shock']['shock_inputs']
print('sector_elasticity_table[\"Exchange Traded Fund\"] =',st['sector_elasticity_table']['Exchange Traded Fund'])
print('SELECTIPO impact under that table =',d['sections']['stress_testing']['data']['scenarios']['Interest Rate Shock']['position_impacts']['SELECTIPO.NS'])
print('instrument_overrides =',json.dumps(st['instrument_overrides']))
"@

SELECTIPO.NS  w= 4.33% sector=Exchange Traded Fund industry=ETF
MAFANG.NS     w= 2.73% sector=Exchange Traded Fund industry=ETF
NIFTYIETF.NS  w= 2.41% sector=Exchange Traded Fund industry=ETF
MIDCAPIETF.NS w=10.16% sector=Exchange Traded Fund industry=ETF
JUNIORBEES.NS w=12.47% sector=Exchange Traded Fund industry=ETF
true ETF weight      = 25.0327%
published ETF sector = 32.0957%
overstatement        = +7.0630 pp
sector_elasticity_table["Exchange Traded Fund"] = 1
SELECTIPO impact under that table = -0.1466
instrument_overrides = {"SELECTIPO.NS": {"sector":"Exchange Traded Fund","sector_elasticity":1.15,"basis":"instrument_override_selectipo"}}
```

A risk manager reading the sector table believes 32.1% of the book is passive index exposure. It is 25.0%. The remaining 7.06% is two single-name operating companies being risk-managed as if they were ETFs, and `SELECTIPO.NS` — the micro-cap — receives a *named* `instrument_override` whose `sector` field is `"Exchange Traded Fund"`, so the misclassification is duplicated into the stress config and published as authoritative.

**Root cause.** Two layers. (a) The persisted `PortfolioPosition.sector` value for those two rows is the literal `"Exchange Traded Fund"` — note `analytics.py:3518` and `analytics.py:5757` use `or "Unknown"` for a null, so the string is **stored**, not defaulted at read time. (b) `analytics.py:3880` — `sectors = {p.ticker: (p.sector or "Exchange Traded Fund") for p in positions_db}` — coerces a null sector to the *same* misleading string in the stress route, so the defect is reproducible from either a bad row or a missing one. The `instrument_overrides` entry is `analytics_engine.py` scenario config.

**Confidence.** **High** on the numbers and on the stress-route coercion at `analytics.py:3880`. **Medium** on which of the two layers seeded the DB rows for `MAFANG.NS` / `SELECTIPO.NS` — the export cannot distinguish, and both paths produce the identical published output.

---

### RL-7 · **P1** · Zero look-through disclosure; `diversification_score: 98.4` overstates diversification on a book that is 25% index ETFs holding the same midcaps

**JSON path** `sections.concentration.data.diversification_score`, `sections.concentration.data.effective_positions`

**Observed.** `diversification_score: 98.4`, `diversification_ratio: 0.83`, `effective_positions: 11.61`, `herfindahl_index: 0.0862`, `top_3: 0.3630`. A full-text scan finds **0 occurrences** of "look-through", "lookthrough", "underlying", "index constituents" or "etf holdings" in the whole artifact. The 283 hits on "overlap" are all `universe_coverage` key-name collisions, not economic overlap. `MIDCAPIETF.NS` (10.16%) and `JUNIORBEES.NS` (12.47%) are midcap/smallcap index products whose constituents include the same midcaps held directly (`ARROWGREEN.NS`, `MAFANG.NS`, `SELECTIPO.NS`); `NIFTYIETF.NS` (2.41%) overlaps the large caps. Nothing in the export says so.

**Expected + recomputation evidence.** The formula is **correct** (see the clean list) — this is a *scope* defect, not an arithmetic one. But the look-through sensitivity is large:

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
c=d['sections']['concentration']['data'];w=c['by_weight'];n=len(w)
hhi=sum(x*x for x in w.values())
print('HHI recomputed %.6f (pub %s) ; N_eff %.4f (pub %s)'%(hhi,c['herfindahl_index'],1/hhi,c['effective_positions']))
print('diversification_score = ((1-HHI)/(1-1/n))*100 = %.4f (pub %s)'%(((1-hhi)/(1-1/n))*100,c['diversification_score']))
etf=['NIFTYIETF.NS','MIDCAPIETF.NS','JUNIORBEES.NS']
hhi_lt=sum(x*x for k,x in w.items() if k not in etf)+(sum(w[t] for t in etf))**2
print('TRUE ETF weight %.4f%%'%(sum(w[t] for t in etf)*100))
print('collapse the 3 ETFs into ONE index bet -> HHI %.4f (%.0f%% worse), N_eff %.2f'%(hhi_lt,(hhi_lt/hhi-1)*100,1/hhi_lt))
print('top_3 = %.4f ; largest = %.4f'%(c['top_3'],c['largest_position']))
"@

HHI recomputed 0.086158 (pub 0.0862) ; N_eff 11.6066 (pub 11.61)
diversification_score = ((1-HHI)/(1-1/n))*100 = 98.4138 (pub 98.4)
TRUE ETF weight 25.0327%
collapse the 3 ETFs into ONE index bet -> HHI 0.1224 (42% worse), N_eff 8.17
top_3 = 0.3630 ; largest = 0.1368
```

A `98.4 / 100` diversification headline next to `top_3 = 36.3%` and a 32.1% single sector bucket is the number a risk manager acts on, and the look-through-adjusted N_eff is 8.17, not 11.61. Note this is a genuine tension with the repo's own stated invariant in `AGENTS.md` ("Diversification scores must be computed from true concentration indices HHI = Σwᵢ², N_eff = 1/HHI") — the invariant is **satisfied**; the invariant itself is sleeve-level and the export never says so.

**Root cause.** `analytics_engine.py:414-422` — the score is defined over the supplied `weights` mapping (14 sleeves) and there is no look-through or ETF-constituent step anywhere in `concentration_analysis`. The disclosure convention exists elsewhere in the codebase (e.g. `sector_weight_basis` at `analytics.py:3553`-region publishes its own basis) and was not applied here. `concentration` also publishes `warnings: []`.

**Confidence.** **High** on the arithmetic and the absence of disclosure. **Medium** on the specific look-through penalty (0.1224 assumes the 3 ETFs are one perfectly-correlated bet — the true figure needs holdings data the export does not carry, which is precisely the point).

---

### RL-8 · **P1** · `max_drawdown` is a 1.15× uplift on the proxy, not the portfolio loss; the headline reads 7.11pp worse than the arithmetic

**JSON path** `sections.stress_testing.data.scenarios.*.{max_drawdown, portfolio_impact, max_drawdown_formula, max_drawdown_basis}`

**Observed.** `Market Crash`: `max_drawdown: -0.5453` vs `portfolio_impact: -0.4742`. The gap is exactly the configured `STRESS_DRAWDOWN_UPLIFT = 1.15`. A risk manager reading `max_drawdown: -54.53%` believes the loss is 54.53%; the weighted sum of the shocked positions' P&L — which the section also publishes, position by position — is **47.42%**. The 7.11pp gap is disclosed (`max_drawdown_basis: "derived_from_shock_proxy"`, `max_drawdown_formula: "portfolio_impact * 1.15"`) but it sits *below* the headline field, and there is no field saying the uplift is a judgement rather than a measurement.

**Expected + recomputation evidence.** The underlying arithmetic is **exact** — see the clean list. The defect is the naming.

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
pos={x['ticker']:x for x in d['sections']['portfolio']['data']['positions']}
for n,s in d['sections']['stress_testing']['data']['scenarios'].items():
    w=sum(pi*pos[t]['weight'] for t,pi in s['position_impacts'].items())
    print('%-22s recomputed_sum(w*pi)=%.6f published_pi=%.6f  headline_max_drawdown=%.4f  uplift=%+.2fpp'%(
        n,w,s['portfolio_impact'],s['max_drawdown'],(s['max_drawdown']-w)*100))
"@

Market Crash          recomputed_sum(w*pi)=-0.474207 published_pi=-0.474200  headline_max_drawdown=-0.5453  uplift=-7.11pp
Interest Rate Shock   recomputed_sum(w*pi)=-0.194196 published_pi=-0.194200  headline_max_drawdown=-0.2233  uplift=-2.91pp
Volatility Spike      recomputed_sum(w*pi)=-0.287688 published_pi=-0.287700  headline_max_drawdown=-0.3309  uplift=-4.32pp
Tech Sector Correction recomputed_sum(w*pi)=-0.134907 published_pi=-0.134900 headline_max_drawdown=-0.1551 uplift=-2.02pp
```

Same for `recovery_time: 24 / 9 / 5 / 12 months` (`recovery_time_basis: configured_recovery_estimate_not_simulated`) and `confidence_level: 0.95` on all four scenarios (`confidence_basis: nominal_label_not_simulated`) — a 95% confidence label with no distribution behind it. All three disclosures are honest; all three sit one level below the number a reader takes away.

**Root cause.** `analytics_engine.py:148` (`STRESS_DRAWDOWN_UPLIFT = 1.15`) applied at `analytics_engine.py:786` (`max_drawdown = round(portfolio_impact * STRESS_DRAWDOWN_UPLIFT, 4)`); `STRESS_CONFIDENCE_LABEL = 0.95` at `:149`; scenario recovery months are static config.

**Confidence.** **High.**

---

### RL-9 · **P1** · Vol-cone verdict is a single-window label that contradicts the cone's own longer windows; the cone publishes no observation count

**JSON path** `sections.risk_studio.data.components.volatility_cone.data.{windows, current_forecast}`

**Observed.** `windows` for 10/21/63/126/252 days all carry `insufficient_data: false`, including the 252-day window, which requires ≥ 253 return observations in the underlying series. The section publishes **no observation count, no lookback, no window bounds, no `history_coverage`** — only `as_of: 2026-09-25` and `latest_observation_date: 2026-09-25`. So a risk manager cannot tell the 252-day cone was measured over a period in which this portfolio did not exist. The verdict `current_forecast.valuation: "normal"` (`percentile_rank: 45`) is derived from the **21-day window alone**, while the section's own longer windows say the opposite: **63d at the 2.9th percentile, 252d at the 1.9th**.

**Expected + recomputation evidence.**

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
c=d['sections']['risk_studio']['data']['components']['volatility_cone']['data']
print('CONE KEYS:',list(c.keys()))
for w in c['windows']:
    print('%4dd  min %.4f p25 %.4f med %.4f p75 %.4f max %.4f | current %.4f  pctile %5.1f  insuff %s'%(
        w['window_days'],w['min'],w['p25'],w['median'],w['p75'],w['max'],w['current_realized'],w['percentile_rank'],w['insufficient_data']))
print('FORECAST:',json.dumps(c['current_forecast']))
w252=[w for w in c['windows'] if w['window_days']==252][0]
print('252d current %.4f vs 252d cone MIN %.4f -> gap %.4f (%.2f%% of the min)'%(w252['current_realized'],w252['min'],w252['current_realized']-w252['min'],(w252['current_realized']/w252['min']-1)*100))
"@

CONE KEYS: ['symbol', 'as_of', 'windows', 'current_forecast', 'universe_coverage', 'data_status', 'latest_observation_date']
  10d  min 0.0603 p25 0.1135 med 0.1537 p75 0.2422 max 0.4265 | current 0.1548  pctile  50.7  insuff False
  21d  min 0.0611 p25 0.1279 med 0.1662 p75 0.2377 max 0.3654 | current 0.1132  pctile  17.5  insuff False
  63d  min 0.0965 p25 0.1358 med 0.1913 p75 0.2474 max 0.2955 | current 0.1071  pctile   2.9  insuff False
 126d  min 0.1232 p25 0.1567 med 0.2102 p75 0.2276 max 0.2599 | current 0.1579  pctile  25.7  insuff False
 252d  min 0.1776 p25 0.1819 med 0.1858 p75 0.1992 max 0.2143 | current 0.1779  pctile   1.9  insuff False
FORECAST: {"model": "GARCH(1,1)", "annualized_vol": 0.1519, "horizon_days": 21, "percentile_rank": 45, "valuation": "normal"}
252d current 0.1779 vs 252d cone MIN 0.1776 -> gap 0.0003 (0.17% of the min)
```

The 252-day realized vol is **0.17% above the minimum of its entire two-year distribution**, and the published verdict is "normal". The percentile ordering is also incoherent as a term structure (10d 50.7 → 21d 17.5 → 63d 2.9 → 126d 25.7 → 252d 1.9), which a single "current vol is normal" label flattens.

**Root cause.** `volatility_service.py:302-323` — `target_w = 21 if 21 in realized_vols_by_window else windows[0]`, then `valuation` is a three-way branch on the 21-day p25/p75 only; the 63/126/252 readings are computed and published but excluded from the verdict by construction. `volatility_service.py:262` sets `insufficient = False` on `len(rolling_vol) >= 2` with no upper reference to the delivered sample. `analytics.py:7178-7217` — `get_volatility_cone` computes `history_coverage` at line 7197 (`_`) and never publishes it, and publishes no `lookback_days` echo of the 756-day request.

**Confidence.** **High** on the verdict derivation and the missing coverage block. **Medium** on the exact delivered sample size for the cone (not published; inferred from `insufficient_data: false` on the 252d window plus the route's `lookback_days=756` default).

---

### RL-10 · **P1** · The liquidity ADV window is published as a *request*; the delivered measurement bounds are all null

**JSON path** `sections.liquidity.data.{data_range, observation_window, latest_observation_date, requested_days}`

**Observed.** `data_range: {start: "2026-08-27", end: "2026-09-26"}` (a 30-calendar-day request), `observation_window: {start: null, end: null, ticker_count: 14, per_ticker: {…observations: 20..22}}`, `latest_observation_date: null`. So the ADV behind every `avg_volume` / `avg_turnover` — and therefore behind every score, band, spread and `liquidation_days` — was measured over 20-22 sessions whose actual dates are **not published anywhere**. The docstring at `analytics.py:1909-1913` states the intent explicitly: *"`data_range` is the request; this is what arrived. Nothing is substituted: an undated frame contributes no bound"* — and then all 14 frames came back undated, so the block correctly reports nulls and the export ships an undeclared measurement window.

**Expected + recomputation evidence.**

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
L=d['sections']['liquidity']['data']
print('data_range (REQUEST)     =',L['data_range'],' requested_days =',L['requested_days'])
print('observation_window.start =',L['observation_window']['start'])
print('observation_window.end   =',L['observation_window']['end'])
print('latest_observation_date  =',L['latest_observation_date'])
ob=[v['observations'] for v in L['observation_window']['per_ticker'].values()]
print('delivered observations per ticker: min=%d max=%d over a 30-CALENDAR-DAY request -> %.1f sessions expected'%(min(ob),max(ob),30*5/7))
"@

data_range (REQUEST)     = {'start': '2026-08-27', 'end': '2026-09-26'}  requested_days = 30
observation_window.start = None
observation_window.end   = None
latest_observation_date  = None
delivered observations per ticker: min=20 max=22 over a 30-CALENDAR-DAY request -> 21.4 sessions expected
```

20-22 delivered sessions is consistent with ~21 trading days in the request, so the window is *probably* right — but "probably" is not a measurement. For a section whose whole job is to certify that a ₹1,888 position can be exited, an undeclared ADV window is a P1.

**Root cause.** `analytics.py:1908-1931` `_liquidity_observation_window` → `_observation_bounds(frame)`; the frames arrive with `date` already promoted to the index at `analytics.py:3680-3686`, but `_observation_bounds` does not read a `DatetimeIndex` (compare `_latest_observation_date` at `analytics.py:583-585`, which *does*). A one-line fallthrough to the DatetimeIndex branch would populate all three nulls.

**Confidence.** **Medium-High.** The nulls are certain and the mechanism is identified; I could not confirm from the export alone whether the index promotion at `:3686` or a non-DatetimeIndex is the proximate cause.

---

### RL-11 · **P1** · `volatility_sizing` reads `status: available` with `warnings: []` for a target that is not executable and needs INR 12,878 of borrowing on a INR 43,609 book

**JSON path** `sections.volatility_sizing.data.{recommended_weights, execution, exposure}`, `sections.volatility_sizing.status`, `sections.volatility_sizing.warnings`

**Observed.** `recommended_weights` sum to **1.295310**, not 1.0. `cash_weight: -0.295309`, `leveraged: true`, `execution.execution_eligible: false`, `block_reasons: ["financing_required"]`, `financing_requirement: 12878.08` INR — **29.5% of NAV borrowed**. The section status is `available` and `warnings` is `[]`. The blocker is disclosed three times (`execution`, `exposure`, and the `methodology` prose "not executable as a normal rebalance") but the top-level status and the empty warnings array tell a dashboard consumer this tile is clean.

**Expected + recomputation evidence.** The disclosure inside the section is genuinely good; what is missing is the *headline*. A `partial` status plus a warning is the pattern the liquidity section already uses for a lesser problem.

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
s=d['sections']['volatility_sizing'];v=s['data']
print('section status  =',s['status'])
print('section warnings=',s['warnings'])
print('sum recommended_weights = %.6f'%sum(v['recommended_weights'].values()))
print('sum current_weights     = %.6f'%sum(v['current_weights'].values()))
print('gross_exposure %.5f  net_cash %.5f  financing %.2f %s  eligible %s  blocks %s'%(
  v['execution']['gross_exposure'],v['execution']['net_cash_weight'],
  v['exposure']['financing_requirement'],v['exposure']['financing_requirement_currency'],
  v['execution']['execution_eligible'],v['execution']['block_reasons']))
print('financing as %% of NAV = %.2f%%'%(v['exposure']['financing_requirement']/v['portfolio_value_exact']*100))
net=sum(t['amount'] for t in v['trades'].values())
print('NET of all 14 trade amounts = INR %.2f  (== financing requirement %.2f)'%(net,v['exposure']['financing_requirement']))
print('methodology:',v['methodology'])
"@

section status  = available
section warnings= []
sum recommended_weights = 1.295310
sum current_weights     = 1.000000
gross_exposure 1.29531  net_cash -0.29531  financing 12878.08 INR  eligible False  blocks ['financing_required']
financing as % of NAV = 29.53%
NET of all 14 trade amounts = INR 12878.08  (== financing requirement 12878.08)
methodology: EWMA inverse-volatility risk parity scaled to target volatility 0.15 (scale=1.2953, gross_exposure=1.29531, cash=-0.295309, achieved_vol=0.15, financing required 12878.08 INR; not executable as a normal rebalance; not full ERC: no Euler RC_i decomposition)
```

The mechanism is a design choice, not a bug: `scale = target_volatility / rec_vol_ann` where `rec_vol_ann = 0.11581` is the vol of the *unscaled* risk-parity portfolio, which happens to be under-vol versus the 15% target, so the engine levers up to reach it. A long-only unlevered mandate should cap gross at 1.0 and accept a lower achieved vol. Every one of the 14 trades nets to exactly the financing requirement, so a reader who adds up the `amount` column gets a buy order the book cannot fund.

**Root cause.** `analytics_engine.py:1034` (`scale = float(target_volatility / rec_vol_ann)`) with no `scale = min(scale, 1.0)` guard for an unlevered book; the status/warning propagation lives in the export layer, which promotes this to `available`.

**Confidence.** **High.**

---

### RL-12 · **P2** · `achieved_volatility` is a tautology — it can never differ from `target_volatility`

**JSON path** `sections.volatility_sizing.data.{achieved_volatility, target_volatility}`

**Observed.** `target_volatility: 0.15`, `achieved_volatility: 0.15`, `scale_factor: 1.295309`, `current_volatility: 0.145465131056991`. Note `target/current = 1.031175 ≠ 1.295309`, so the scale is *not* the naive ratio — but `achieved_volatility` is still algebraically forced. From `rec_vol_ann = 0.15 / 1.295309 = 0.115813`: `rec_vol_ann × scale ≡ 0.115813 × 1.295309 ≡ 0.15`. A reader treats "achieved 15.0%" as a *measurement* of the recommended book's vol. It is a restatement of the input.

**Expected.** Either drop the field, or publish the independently recomputed `sqrt(w'Σw)` of the recommended weights so it can differ from the target.

**Root cause.** `analytics_engine.py:1034` defines `scale = target/rec_vol_ann`; `analytics_engine.py:1053` sets `achieved_vol = rec_vol_ann * scale`. The two statements are inverses.

**Confidence.** **High.**

---

### RL-13 · **P2** · `as_of: null` on three of my sections; top-level `warnings: []` while 8 of 17 sections are `partial`

**JSON path** `sections.concentration.as_of`, `sections.liquidity.as_of`, `sections.dashboard.data.component_as_of.{concentration, liquidity, risk_score}`, top-level `warnings`, `snapshot_consistency`

**Observed.**

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
for k,v in d['sections'].items(): print('%-20s %-10s warn=%d'%(k,v['status'],len(v.get('warnings') or [])))
print('TOP-LEVEL warnings  =',d['warnings'])
print('snapshot_consistency=',d['snapshot_consistency'])
ca=d['sections']['dashboard']['data']['component_as_of']
print('component_as_of concentration/liquidity/risk_score =',{k:ca[k] for k in ('concentration','liquidity','risk_score')})
print('component_as_of portfolio/realized_risk/summary    =',{k:ca[k] for k in ('portfolio','realized_risk','summary')})
"@

portfolio            available  warn=1
dashboard            partial    warn=9
...
concentration        available  warn=0
liquidity            partial    warn=1
risk_studio          available  warn=0
TOP-LEVEL warnings  = []
snapshot_consistency= best_effort
component_as_of concentration/liquidity/risk_score = {'concentration': {'as_of': None, 'as_of_semantics': None}, 'liquidity': {'as_of': None, 'as_of_semantics': None}, 'risk_score': {'as_of': None, 'as_of_semantics': None}}
component_as_of portfolio/realized_risk/summary    = {'portfolio': {'as_of': '2026-09-26T15:33:25.781197Z', 'as_of_semantics': 'declared_as_of'}, 'realized_risk': {'as_of': '2026-09-25', 'as_of_semantics': 'latest_observation_date'}, 'summary': {'as_of': '2026-09-25', 'as_of_semantics': 'latest_observation_date'}}
```

`concentration`, `liquidity` and `risk_score` publish **no timestamp at all**, while their neighbours publish a precise one with a stated semantics. A risk manager cannot tell whether `diversification_score: 98.4` or `overall_score: 13.7` is from this morning. And the four sections I own with live problems — `concentration` (0 warnings, mislabelled sector bucket, no look-through), `volatility_sizing` (0 warnings, unexecutable), `stress_testing` (0 warnings, nominal confidence label), `risk_studio` (0 warnings, ξ-sign contradiction) — all publish empty warning arrays, while the top-level array is empty too. `snapshot_consistency: "best_effort"` is the only global signal.

**Root cause.** Export-layer status/warning derivation for these four routes; `as_of` is not computed for the weight-only routes (`concentration`, `risk_score`) or is dropped for `liquidity` (which does compute `latest_observation_date` — it is simply `null`, see RL-10).

**Confidence.** **High** on the observation. **Medium** on the export-layer root cause (not traced to a specific line; the four routes have no shared warning builder I could locate).

---

### RL-14 · **P2** · Two different `avg_pairwise_correlation` numbers in one export, unremarked; `methodology` string has an unbalanced paren

**JSON path** `sections.dashboard.data.components.risk_score.data.avg_pairwise_correlation` vs `sections.risk_studio.data.components.correlation_stability.data.current_avg_correlation`

**Observed.** `risk_score.avg_pairwise_correlation: 0.1059` (holding window, 39 rows) vs `correlation_stability.current_avg_correlation: 0.1404` (rolling, `as_of 2026-09-25`). Neither is labelled as to window in the field name, and nothing in the export notes that they are the same statistic measured twice. The `risk_score.methodology` string also has a broken parenthesis: `"correlation leg = min(30, 50 x max(0, avg pairwise correlation) and is null"` — the closing `)` before `and` is missing, so the formula as published does not parse.

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
rs=d['sections']['dashboard']['data']['components']['risk_score']['data']
cs=d['sections']['risk_studio']['data']['components']['correlation_stability']['data']
print('risk_score.avg_pairwise_correlation      =',rs['avg_pairwise_correlation'],' window rows =',rs['history_coverage']['covered_days'])
print('correlation_stability.current_avg_corr   =',cs['current_avg_correlation'],' as_of =',cs['as_of'])
print('ratio = %.4f  (unremarked in the export)'%(cs['current_avg_correlation']/rs['avg_pairwise_correlation']))
print('methodology:',rs['methodology'][-190:])
"@

risk_score.avg_pairwise_correlation      = 0.1059  window rows = 39
correlation_stability.current_avg_corr   = 0.1404  as_of = 2026-09-25
ratio = 1.3261  (unremarked in the export)
```

Also worth noting for a risk manager: **0.1059 average pairwise correlation across 14 Indian equities is implausibly low** (a realistic cross-sectional mean is 0.35-0.55, and the export's own `correlation_stability.historical_median` is **0.3408**). A 39-row pairwise-complete correlation on a 14-name book is dominated by estimation noise, and the correlation leg is 20% of the risk score.

**Root cause.** Two routes compute the same quantity on different windows and neither publishes its window alongside the value; the `methodology` f-string at `analytics_engine.py:1314-1323` is missing a closing parenthesis after `avg pairwise correlation)`.

**Confidence.** **High** on the divergence and the broken string. **Medium** on the "implausibly low" judgement — that is my read, not a defect I can point at in the code.

---

### RL-15 · **P2** · `correlation_stability` reports `alert_level: "NORMAL"` after a 49% collapse to 41% of the historical median — a one-sided test

**JSON path** `sections.risk_studio.data.components.correlation_stability.data.{alert_level, is_regime_break, current_avg_correlation, series, message}`

**Observed.** `alert_level: "NORMAL"`, `is_regime_break: false`, `message: "Average pairwise correlation (0.140) is within normal historical bounds (median 0.341)."` But the published `series` runs 0.2731 (2026-07-06) down to **0.1404** (2026-09-25) with a `historical_median` of 0.3408 — the current reading is **below every one of the 60 points in its own series** and less than half the historical median. The alert fires only on the *high* side, so a 49% collapse in measured co-movement reads as reassuring.

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
cs=d['sections']['risk_studio']['data']['components']['correlation_stability']['data']
v=[x['avg_correlation'] for x in cs['series']]
print('series n=%d  first %s=%.4f  last %s=%.4f'%(len(v),cs['series'][0]['date'],v[0],cs['series'][-1]['date'],v[-1]))
print('series min %.4f max %.4f ; current %.4f'%(min(v),max(v),cs['current_avg_correlation']))
print('current below EVERY series point?',cs['current_avg_correlation']<min(v))
print('historical_median %.4f  thresh75 %.4f  thresh90 %.4f'%(cs['historical_median'],cs['historical_threshold_75th'],cs['historical_threshold_90th']))
print('current / historical_median = %.3f'%(cs['current_avg_correlation']/cs['historical_median']))
print('alert_level=%s is_regime_break=%s'%(cs['alert_level'],cs['is_regime_break']))
"@

series n=60  first 2026-07-06=0.2731  last 2026-09-25=0.1404
series min 0.1179 max 0.2741 ; current 0.1404
current below EVERY series point? False
historical_median 0.3408  thresh75 0.4129  thresh90 0.4590
current / historical_median = 0.412
alert_level=NORMAL is_regime_break=False
```

Correction to my own first pass: the current value is **not** below every series point — the series minimum is 0.1179. It is below the series *median* and at 41% of the historical median. The finding stands but weaker than I first wrote: a two-month, roughly 49% decline in measured co-movement, ending near the bottom of its own 3-month range and at 41% of the long-run median, is published as `NORMAL` with a message that frames the value as merely "within normal bounds" — a one-sided test. For a book that is 25% index ETFs, an average pairwise correlation of 0.14 is itself a data-integrity signal (the ETFs should be pushing it *up*), not a comfort.

**Root cause.** `get_correlation_stability` (`analytics.py:6492`) — the regime-break test compares `current` against `threshold_75th` / `threshold_90th` only; there is no lower bound and no trend test.

**Confidence.** **Medium.** The one-sided nature of the test is certain; whether a low-correlation alert *should* exist is a policy judgement, and the export does not claim it does.

---

### RL-16 · **P2** · Stress volatility adjustment is saturated for 12 of 14 legs, and disagrees with the sizing section for the 2 unclipped ones

**JSON path** `sections.stress_testing.data.scenarios.*.shock_inputs.volatility_adjustment.by_ticker` vs `sections.volatility_sizing.data.volatilities`

**Observed.** The adjustment is `clip(measured_annualised_vol / 0.22, 0.85, 1.25)`. **8 legs sit at the 1.25 ceiling** (ELECTCAST, MOTILALOFS, ARROWGREEN, JKIL, MCX, MOTHERSON, REDINGTON, MAFANG) and **4 at the 0.85 floor** (NIFTYIETF, MIDCAPIETF, JUNIORBEES, SELECTIPO). Only `CIPLA.NS` (1.0058) and `NTPC.NS` (0.9849) are unclipped. So "measured_annualized_volatility_over_reference" is a two-valued lookup for 12/14 of the book, and every leg's stress shock is a function of its *sector* alone in 86% of cases. The two unclipped legs also disagree with the sizing section's own vol for the same names on a different window: implied `CIPLA 22.13%` vs published `0.1455`, implied `NTPC 21.67%` vs published `0.1385`.

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
st=d['sections']['stress_testing']['data']['scenarios']['Market Crash']['shock_inputs']['volatility_adjustment']
vs=d['sections']['volatility_sizing']['data']['volatility_sources']
sizing=d['sections']['volatility_sizing']['data']['volatilities']
hi=[t for t,v in st['by_ticker'].items() if v['factor']==1.25]; lo=[t for t,v in st['by_ticker'].items() if v['factor']==0.85]
mid=[t for t,v in st['by_ticker'].items() if v['factor'] not in (1.25,0.85)]
print('at 1.25 CEILING (%d): %s'%(len(hi),hi))
print('at 0.85 FLOOR   (%d): %s'%(len(lo),lo))
print('genuinely measured (%d): %s'%(len(mid),{t:st['by_ticker'][t]['factor'] for t in mid}))
for t in mid: print('  %-12s stress implies %.4f%% ; sizing publishes %.4f%%  (windows 39 vs 174)'%(t,st['by_ticker'][t]['factor']*0.22*100,sizing[t]*100))
print('bounds %s  reference %s  min_obs %s'%(st['bounds'],st['reference_annualized_volatility'],st['min_observations']))
"@

at 1.25 CEILING (8): ['ELECTCAST.NS','MOTILALOFS.NS','ARROWGREEN.NS','JKIL.NS','MCX.NS','MOTHERSON.NS','REDINGTON.NS','MAFANG.NS']
at 0.85 FLOOR   (4): ['NIFTYIETF.NS','MIDCAPIETF.NS','JUNIORBEES.NS','SELECTIPO.NS']
genuinely measured (2): {'CIPLA.NS': 1.0058, 'NTPC.NS': 0.9849}
  CIPLA.NS      stress implies 22.13% ; sizing publishes 14.55%  (windows 39 vs 174)
  NTPC.NS       stress implies 21.67% ; sizing publishes 13.85%  (windows 39 vs 174)
bounds [0.85, 1.25]  reference 0.22  min_obs 20
```

The bounds are published (`volatility_adjustment.bounds`, `reference_annualized_volatility`, `min_observations`, `return_clip: [-0.2, 0.2]`), so the clipping is discoverable — but **no field counts how many legs are at a bound**, so a reader must tally 14 values to learn that the "measured" adjustment measures 2 of them. The per-name `factor` values are all published and honest; the section simply doesn't say that 86% of them are constants. Separately, `return_clip: [-0.2, 0.2]` truncates daily returns at ±20% before annualising, which is a large clip for a book containing a micro-cap and will bias the vol estimate **downward** for exactly the legs the adjustment is supposed to penalise.

**Root cause.** `analytics_engine.py:145-146` (`STRESS_VOL_ADJ_MIN/MAX`), `analytics_engine.py:762-765` (clip, unguarded), and the missing saturation count in the disclosure block at `analytics_engine.py:804-806`.

**Confidence.** **High** on the tallies and the disagreement. **Medium** on the direction of the `return_clip` bias — the clip is published, but I have not measured the pre/post-clip vol.

---

### RL-17 · **P2** · `SELECTIPO.NS`'s market cap is the hardcoded INR 1bn floor — named, and disclosed (so: P2, not P0)

**JSON path** `sections.liquidity.data.by_position."SELECTIPO.NS".{market_cap, market_cap_provenance, market_cap_source, is_estimate}`

**Observed.** `market_cap: 1000000000` **exactly**, `market_cap_provenance: "fallback"`, `market_cap_source: "fixed_floor_1e9_inr"`, `is_estimate: true`. The named constant is **`LIQUIDITY_MARKET_CAP_FLOOR_INR = 1_000_000_000.0`** at `analytics_engine.py:138`, reached via `_market_cap_provenance` at `analytics_engine.py:190` when the annualised-turnover estimate is not `> 1e9` (measured ADV turnover 2,690,584 × 250 = 672.6M < 1e9 → floor). The `1e9` cap is one of the tier gates (`mc >= 1e10` for tier 3), so the fabricated cap is load-bearing for the tier and therefore for the score, band, spread and `liquidation_days`.

**This one is disclosed properly and I am scoring it P2, not P0:**
- `scoring.market_cap_floor = {value: 1000000000, provenance: "fallback", note: "Applied only when…"}` published
- `estimated_market_cap_count: 5`, `measured_market_cap_count: 9`, `market_cap_count: 14` — **matches** the by_position tallies exactly (4 `estimated` + 1 `fallback`)
- `non_measured_market_caps` names all five; `non_measured_by_provenance` splits them
- section `status: "partial"`, `data_status: "partial"`, and a warning that says it in plain English
- the floor is read back out of the scoring block rather than re-hardcoded (`analytics.py:1991-2003`), so the warning cannot name a different constant than the one used

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
L=d['sections']['liquidity']['data']
nm=[t for t,r in L['by_position'].items() if r['market_cap_provenance']!='measured']
print('non-measured count field  =',L['estimated_market_cap_count'])
print('recomputed from by_position=',len(nm),nm)
print('match?',L['estimated_market_cap_count']==len(nm))
print('by_provenance =',json.dumps(L['non_measured_by_provenance']))
print('fallback_count =',L['fallback_market_cap_count'],' floor =',L['scoring']['market_cap_floor']['value'])
print('SELECTIPO market_cap =',L['by_position']['SELECTIPO.NS']['market_cap'],' source =',L['by_position']['SELECTIPO.NS']['market_cap_source'])
print('implied turnover cap = 2690584 * 250 = %.0f  (< 1e9 -> floor)'%(2690584*250))
print('section status =',d['sections']['liquidity']['status'])
"@

non-measured count field  = 5
recomputed from by_position= 5 ['JUNIORBEES.NS', 'MAFANG.NS', 'MIDCAPIETF.NS', 'NIFTYIETF.NS', 'SELECTIPO.NS']
match? True
by_provenance = {"estimated": ["JUNIORBEES.NS","MAFANG.NS","MIDCAPIETF.NS","NIFTYIETF.NS"], "fallback": ["SELECTIPO.NS"]}
fallback_count = 1  floor = 1000000000
SELECTIPO market_cap = 1000000000  source = fixed_floor_1e9_inr
implied turnover cap = 2690584 * 250 = 672646000  (< 1e9 -> floor)
section status = partial
```

The only thing missing is a `constant` / `file:line` pointer in the payload itself so a consumer can find the floor without the source tree.

**Confidence.** **High.**

---

### RL-18 · **P2** · `gpd_shape_xi` (headline) is the raw ML fit; the published VaR/ES came from the clipped value

**JSON path** `sections.risk_studio.data.components.tail_dependence.data.gpd_shape_xi`

**Observed.** `gpd_shape_xi: -0.7068` (raw ML) while `gpd_shape_xi_used: -0.5` produced `evt_pot_var: -0.036708`. A reader who takes the headline ξ and recomputes the POT moments gets `-0.034584` (the published `evt_pot_var_unconstrained`) — a 6.1% relative error on the 99% VaR, in the *unconservative* direction. The clip discards 29% of the fitted shape.

**Expected.** Either publish the used parameter under the unsuffixed name, or rename the headline to `gpd_shape_xi_raw_ml`.

**Mitigating.** This is disclosed four times over: `gpd_shape_xi_used`, `gpd_shape_xi_basis: "constrained_clip"`, `gpd_shape_xi_constrained: -0.5`, `constraint_reason: "gpd_shape_clipped"`, `metrics_constrained: true`, plus a dedicated `gpd_shape_xi_used_rule` paragraph. This is a naming defect, not a hidden one.

**Root cause.** `analytics_engine`-adjacent disclosure helper `_gpd_shape_usage_disclosure` at `analytics.py:7435`; the raw/used split originates in the constrained GPD fit inside `TailRiskService`.

**Confidence.** **High** on the discrepancy and the disclosure; **Low** on whether the clip itself is sound (a lower bound of −0.5 on ξ is a defensible regularisation for a POT fit on 26 exceedances, but the export gives no basis for the specific bound).

---

## Verified clean — no finding

These were attacked and hold up. Saying so precisely, because "no finding" here means "I could not break it", not "it is perfect".

**Liquidity band ↔ published score consistency — CLEAN.** 14/14 legs: `category` and `liquidation_days` are both derived from the **rounded** `score`, not `score_raw`, and every one matches the published threshold table. The headline (`overall_score 8` → `overall_band "High"` → `liquidation_time_days "1-2"`) matches too. 0 mismatches. The band rule, thresholds, `band_source: "published_score"`, and the rounding rule are all published.

**Market-cap provenance count — CLEAN.** `estimated_market_cap_count: 5` == the 5 by_position rows with `market_cap_provenance != "measured"` (4 `estimated` + 1 `fallback`). No mismatch. The P0 I was told to look for does not exist.

**High/medium/low counts — CLEAN.** `volume_band_position_counts {High: 10, Medium: 3, Low: 1}` = 14; percentages 71.4 / 21.4 / 7.1 = 10/14, 3/14, 1/14; the 99.9 total and the 0.1 rounding residual are published rather than renormalised. All counts derive from the **published** score's band, so a position cannot be "High" in one column and "Medium" in another.

**Spread — honestly assumed, not falsely measured.** `spread_basis: "assumed_bid_ask_spread_from_turnover_tier_formula"`, `provenance: "model_assumed"`, `observed: false`, the full 4-tier ladder with both the score and spread formulas published, and `recomputed_from_avg_turnover.confirmed_count: 14 / unconfirmed_count: 0`. It is an assumption, not a measurement — but it is labelled as one at both the section and per-position level, and every value reproduces from the published formula. I could not construct a case where a reader would believe it was observed.

**Stress testing arithmetic — CLEAN, and the "milder than a 50% crash" check does not fire.** All 4 scenarios × 14 positions = **56/56 position impacts reproduce exactly** from `market_shock × sector_elasticity × vol_factor` clipped to `[-0.75, -0.02]`; 0 mismatches. Shock is multiplicative on price. `portfolio_impact = Σ wᵢ·πᵢ` recomputes to ≤ 1.2e-5 on all four. **Pre-shock weights are correct here** — the scenario is a pure return shock with no rebalance, so recomputing post-shock weights would be the error. The sector elasticity table, the instrument overrides, the clip bounds, the vol reference and bounds, and the return clip are all published per scenario. The adverse case also does not fire: `Market Crash` gives MOTHERSON −67.81% and ARROWGREEN −67.81%, so a 50% single-name crash is *milder* than the published scenario, and no leg's shock is capped at the −0.75 clip. The only defect is the headline naming (RL-8).

**Risk score composition — CLEAN.** Weights sum to exactly 1.0000. `overall_score` recomputes to 13.710 from the published components and published weights → 13.7, drift −0.01, fully explained by the components being published at 1 dp. `excluded_components: []` and no component is `null` — all five legs were genuinely measured, so nothing was dropped for convenience. The exclusion machinery exists and is used correctly elsewhere (`analytics_engine.py:1194-1200`, `:1229-1233`): a null sub-score is excluded and the remaining weights renormalized, never counted as 0. `change: null` with `change_reason: "no_persisted_prior_score"` and `change_status: "unavailable"` — the right answer, honestly stated, with the statelessness rationale in the code. Monotonicity of the *measured* legs is correct: concentration ↑ → score ↑, volatility ↑ → score ↑, correlation ↑ → score ↑, all with the correct sign and the documented slope. **A book with worse concentration cannot score better** on the concentration leg. (The pathology is RL-3: two legs that cannot move at all.)

**Concentration arithmetic — CLEAN.** `HHI = Σwᵢ²` recomputes to 0.086158 vs published 0.0862. `effective_positions = 1/HHI = 11.6066` vs 11.61. `largest_position 0.136798`, `top_3 0.363031`, `top_5 0.522359`, `top_10 0.872099` — all exact. `diversification_score = ((1−HHI)/(1−1/n))·100 = 98.4138` vs 98.4. `diversification_ratio = N_eff/n = 0.8290` vs 0.83. `by_sector` sums to 1.0 with a published 0 rounding residual and a stated `sector_weight_basis`. **This satisfies the repo's own `AGENTS.md` invariant** (HHI-based, N_eff = 1/HHI, single-holding → 0, no inverted risk proxy). The defect is scope, not maths (RL-7).

**Tail risk at the published level — CLEAN.** Ordering holds: `|evt_pot_es| 4.1074% ≥ |evt_pot_var| 3.6708%` and `|historical_es| 3.6539% ≥ |historical_var| 3.1724%`; `|EVT VaR| > |historical VaR|` as POT should be. **No 99% CVaR sits below a 95% CVaR** — but that is only because *only one level is published* (0.99), so the multi-level monotonicity test is not performable from this export (see RL-4 for the more serious window problem). The threshold is declared: `threshold_quantile 0.95`, `threshold_u 0.020464`, `exceedance_fraction 0.050193`, `exceedances_count 26` — and `26 / 518 = 0.05019` reconciles exactly. `pot_threshold_basis` explains in prose that the fitting level and the reported level are deliberately different. **No failed fit is published as a fit**: `model_fitted: true`, `raw_fit_valid: true`, `metrics_valid: true`, with `tail_risk_service.py:151-171` nulling everything and labelling `fit_failed` / `raw_first_moment_undefined` on failure. **No EVT fit is attempted on 39 observations** — the section uses 518 (which is its own problem, RL-4, but it is not a small-sample EVT).

**Copula sample — ADEQUATELY DISCLOSED BY ABSENCE-OF-ERROR.** `total_observations: 518`, matrix symmetric with a unit diagonal, `high_tail_risk_pairs` carrying `lower_tail_lambda`, `linear_correlation`, `degrees_of_freedom` and a `risk_category` per pair. The t-copula dof values (3.59-4.84) are low, as expected for a 91-pair MLE, but nothing is published that is not backed by the fit.

**Vol-cone percentile ordering — CLEAN.** `min ≤ p25 ≤ median ≤ p75 ≤ max` holds for all 5 windows, and `current_realized` lies inside `[min, max]` for all 5. The `insufficient_data` logic refuses to fabricate quantiles from a single observation (`volatility_service.py:263-269`) or from a window longer than the sample (`:270-276`) — that is the right behaviour. The defect is the verdict and the missing coverage block (RL-9), not the percentiles.

**Position-sizing executability vs ADV — CLEAN. The P0 does not exist in this artifact.** 14/14 trades are a small fraction of one day of that leg's own ADV:

```
$ uv run python -c @"
import json
d=json.load(open(r'C:\es\others things\finengine-portfolio-ai-context v5.json',encoding='utf-8'))
bp=d['sections']['liquidity']['data']['by_position'];vs=d['sections']['volatility_sizing']['data']
tr=vs['trades'];rw=vs['recommended_weights'];cw=vs['current_weights']
print('%-15s %7s %7s %8s %7s %10s %12s %11s %8s'%('ticker','cur%','tgt%','d_pp','shares','notional','ADV_turnover','trade/ADV%','ld'))
for t in sorted(rw,key=lambda k:-abs(rw[k]-cw[k])):
    adv=bp[t]['avg_turnover'];n=abs(tr[t]['amount'])
    print('%-15s %6.2f%% %6.2f%% %+7.2f %+7d %10.2f %12.0f %10.4f%% %8s'%(t,cw[t]*100,rw[t]*100,(rw[t]-cw[t])*100,tr[t]['shares_delta'],n,adv,n/adv*100,bp[t]['liquidation_days']))
print()
print('WORST trade as %% of ONE DAY ADV = %.4f%%   breaches(>100%%) = %d'%(max(abs(tr[t]['amount'])/bp[t]['avg_turnover']*100 for t in rw),sum(1 for t in rw if abs(tr[t]['amount'])/bp[t]['avg_turnover']>1)))
"@

NIFTYIETF.NS      2.41%  18.36%  +15.95     +26   6955.65    148558989   0.0047%       1-2
SELECTIPO.NS      4.33%  12.69%   +8.36     +75   3647.42      2690584   0.1356%       5-10
MOTHERSON.NS     13.68%   6.68%   -7.00     -19   3051.80   1810544814   0.0002%       1-2
...
WORST trade as % of ONE DAY ADV = 0.1356%   breaches(>100%) = 0
```

Worst is `SELECTIPO.NS` at **0.1356%** of one day's ADV — a ₹3,647 order against ₹2.69M of daily turnover. **Zero breaches.** Even at a punitive 1% participation cap every trade clears by two orders of magnitude. The cross-section consistency check nobody else is doing comes out clean on the ADV axis: **however wrong `liquidation_days` is (RL-1), it does not contradict the sizing advice, because both are trivial at this book size.** The sizing section's own numbers back this up — `sizing_history` declares `return_observations: 174` with `per_ticker_return_observations` from 102 to 172 and `minimum_observations_required: 30 / meets_minimum_sample: "sufficient"`, so the vols behind the weights are **not** 39-observation noise. The blocker is financing, not liquidity (RL-11).

**Inverse-volatility sizing — CLEAN and `AGENTS.md`-compliant.** `recommended_weights[t] = (1/σ_t) / Σ(1/σ) × scale_factor` reproduces to 6 dp on all 14 legs (ratio 1.2953 for every leg, matching `scale_factor` exactly). True inverse-volatility weights, no risk proxy, no inverse. `trades` reconcile: `share_reconciliation` publishes `shares_delta == half_up(amount / sizing_price)`, `reconciled: true`, `priced_trades 14`, `tolerance_breach_tickers: []`, `below_minimum_notional_tickers: ["MCX.NS"]` with a plain-English reason, and a per-trade own-tolerance test rather than a single global max. `sizing_price` is `measured`, `as_of 2026-09-22`, with `price_freshness` publishing the 3-day gap and a `position_last_price_comparison` block giving the per-leg relative gap (max 3.47% on SELECTIPO). The retired 100.0 placeholder is gone.

**risk_contribution units — CLEAN, and I retract my own first reading.** `positions.*` and `sector_rollup.*` are unitless **shares of total portfolio risk**, not volatilities; the 14 `volatility` values sum to 0.999998 ≈ 1.0. `annualized_note` at `analytics.py:913-918` states this explicitly and correctly ("They do not apply to `positions.*` or `sector_rollup.*`, which are unitless shares of total portfolio risk, annualized or not"), with a per-model `published_total` and `rounding_residual`. I initially annualized these and derived an implausible 314% for MOTHERSON; that was my error, not the export's, and the export's guard is what caught it. The only residual issue is the field *name* `volatility` for a risk share, mitigated by the note.

**Window heterogeneity is disclosed per-section where it matters.** A census of the delivered return samples across the risk surface — **20-22** (liquidity), **36-39** (risk_score, realized_risk, stress vol adjustment), **60** (correlation_stability series), **102-174** (volatility_sizing, forecast_risk, factor_exposure), **238-251** (risk_contribution), **518** (tail_dependence), **756-requested** (vol-cone) — is *individually* declared in `history_coverage`, `sizing_history`, `history_window`, `pot_threshold_basis` and `model_window`. The export is unusually disciplined here. The failures are RL-4 (tail, undisclosed) and RL-9 (vol-cone, undisclosed) — the two sections that did *not* carry the block their siblings have.
