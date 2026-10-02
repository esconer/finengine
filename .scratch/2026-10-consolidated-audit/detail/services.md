# Detail — Services layer (`backend/app/services/`)

**Scope of this file:** `analytics_engine.py` (6,772 lines / 336.7 KB), `data_service.py`,
`screener_service.py`, `india_data_service.py`, `backtest_service.py`, `correlation_service.py`,
`equity_research_service.py`, `tail_risk_service.py`. Findings `SVC-1` … `SVC-11`.

**How these were produced.** The inventory
(`plans/2026-10-audit/inventory-a1-api-services.md`) is another agent's assertion. Every citation
below was **personally opened** at the cited line before emission. Two items (`SVC-1`, `SVC-2`)
carried a ✓ mark; both were re-opened anyway and **one of them did not survive as written**
(`SVC-1` — see `## Rejected on re-verification`).

**Runtime arithmetic.** The rules forbid `pytest` and the audit CLI, so no service function was
executed. Two mechanisms turn on how Python evaluates `min`/`max` against a NaN, and those were
settled by evaluating the *expression* under `backend\.venv\Scripts\python.exe` (CPython 3.12.9) —
pure arithmetic, no application code, no I/O. Both results are quoted inline and the command is
reproduced so a reader can re-run it. Nothing else in this file is executed.

**Type discipline (plan §3.5).** Where a mechanism turns on a type, the resolved type is named.
This is load-bearing twice here: `float()` on a **Python** `float` NaN does not raise (it *is* a
float), and `min`/`max` with a NaN operand return the **non-NaN** argument, not the NaN.

---

## Findings

### SVC-2 — `sharpe_ratio` and `sortino_ratio` publish a hard `0.0` on a zero or NaN denominator
- **Class**: bug
- **Severity**: BLOCKER
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/analytics_engine.py:5468` and `:5476`; the contradicting docstring at `:5439-5447`; the sibling branch that was fixed at `:5460-5461`
- **Symptom**: A realized-risk block publishes `sharpe_ratio: 0.0` — indistinguishable from a
  measured zero — for a flat window, a frozen/stale price frame, or an all-NaN return series.
- **Evidence**:
  ```python
  5464:                annual_return = float(returns.mean() * 252)
  5465:                annual_volatility = float(returns.std() * np.sqrt(252))
  5466:
  5467:                # Sharpe ratio
  5468:                sharpe_ratio = float((annual_return - self.risk_free_rate) / annual_volatility) if annual_volatility > 0 else 0.0
  ```
- **Mechanism**: (1) `annual_volatility` is a **Python `float`** — the numpy `float64` from `returns.std() * np.sqrt(252)` is narrowed by `float()` at 5465. (2) The guard at 5468 tests `annual_volatility > 0`; for a flat series `std()` is ~1e-19 so the test is False, and for an all-NaN series it is `nan` so the test is **also** False (`float('nan') > 0` evaluates to `False`, confirmed on CPython 3.12.9). Either way control reaches the `else 0.0`. (3) The same holds at 5476 for `sortino_ratio` on `downside_deviation`. The `< 10`-observation branch nine lines above does the opposite and publishes `None` (`:5460-5461`).
- **Impact**: `sharpe_ratio` and `sortino_ratio` on every realized-risk block — the two figures a reader acts on most. The published `0.0` is not merely unmeasured, it is **directionally wrong**: it asserts "no risk-adjusted return" about a series that had return and no measured dispersion. The method's own docstring at `:5439-5447` states the rule this violates verbatim: *"a 0.0 Sharpe is indistinguishable from a measured zero, which is what makes a hard zero on an unmeasured quantity the one number a reader must never be handed."* The fix was applied to the short-sample path and **not** to the zero-variance path. Amplifier: `_estimate_uncertainty_block` bootstraps around the published value, so the published interval is centred on the fabricated number.
- **Suggested fix**: Shape only — publish `None` on both guards, matching the `< 10` branch 20 lines above, and add the reason token alongside it. Blast radius is every consumer of these two keys; nothing else in the method changes. **Do not** substitute a sentinel (`.real`, `0.0`, `-1.0`): the sibling branch at 5460-5461 already establishes `None` as the correct in-repo convention. **Do not** widen the `< 10` gate — the docstring at 5451-5457 explicitly assigns that policy to `apply_annualization_gate` / `MIN_ANNUALIZE_DAYS`, and widening it here would change published numbers on the ≥ 30-day path.

### SVC-1 — A NaN mean volume is not caught before the tier ladder and publishes a *measured-looking* score
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/analytics_engine.py:3945` (source of the NaN) and `:3972` (where the wrong number is born); band table at `:308-312`; caller `backend/app/api/analytics.py:7557`
- **Symptom**: When `Volume` is present but entirely unparseable, the position publishes a
  confident liquidity verdict — `score`, `category`, `liquidation_days`, `risk_level` — derived from
  no data at all, with nothing on the payload marking the score as fabricated.
- **Evidence**:
  ```python
  3944:                # Calculate liquidity score based on volume, price, and daily turnover
  3945:                volume = float(df[vol_col].mean())
  3946:                price = float(df[close_col].iloc[-1]) if close_col and not df.empty else 0.0
  3947:                daily_turnover = volume * price
  ```
- **Mechanism**: (1) `df[vol_col]` is a pandas `Series`; on an all-NaN column `.mean()` (default `skipna=True`) returns NaN, and `float()` at 3945 is a no-op on a value that is **already a Python `float` NaN** — it does not raise. (2) `daily_turnover` at 3947 is therefore a Python `float` NaN; every tier test at 3959/3963/3967 is `nan >= X`, which is `False`, so control reaches the Tier-4 `else` at 3971. (3) At 3972 the expression is `max(2.5, min(5.9, 3.0 + (nan/2e7)*2.9))`. Python's two-argument `min(a, b)` returns `a` unless `b < a`, and `nan < 5.9` is `False`, so `min(5.9, nan)` evaluates to **`5.9`**, and `max(2.5, 5.9)` to **`5.9`**. Measured on CPython 3.12.9: `score_raw = 5.9`.
- **Impact**: `score`, `category`, `liquidation_days` and `risk_level` on the position, and `overall_score` (`:4000`, the mean over all published scores) on the portfolio. At 5.9 the position bands as `("Low", "5-10")` per `LIQUIDITY_SCORE_BANDS` (`:308-312`) and `risk_level` inverts to `"High"` (`:315`). **The published score is 5.9, not the 3.0 the tier intends** — the failure pushes the number *up* by 2.9 points and lands it 0.1 below the `Medium` cut of 6.0, so a value of 5.95 would round into `"Medium"` at `LIQUIDITY_SCORE_PRECISION = 1` (`:305`). `avg_volume` and `avg_turnover` are published as NaN alongside (`:3983-3984`). Mitigations that keep this at DEFECT rather than BLOCKER: the same object publishes `market_cap_provenance: "fallback"` and `is_estimate: true` (`:3986-3988`) because `_market_cap_provenance` correctly returns the INR 1bn floor with `"fallback"` provenance (`:2593-2595`), so a careful consumer can tell the *cap* was not measured — but nothing discloses that the **score** itself came from a NaN.
- **Suggested fix**: Shape only — test the resolved value for finiteness before the ladder and refuse the score when it is not finite, mirroring the guard the same function already applies to volume statistics at `:4002` (`... if volume_stats['volumes'] else 0.0`). Publish the refusal as `None` plus a reason token. Blast radius is one position block plus `overall_score`. **Do not** substitute `.real`, `0.0` or `or 0` — that is the defect. **Hazard**: the NaN also reaches `volume_stats['total_volume']` (`:3995`), so a fix that only guards the ladder still leaves a NaN in the aggregate.

### SVC-6 — `backtest_service` silently shortens `lookback_days`, and the payload discloses the wrong quantity
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/backtest_service.py:65-67`; disclosure field at `backend/app/api/analytics.py:10495`
- **Symptom**: A caller who requests a 252-day lookback can receive a run computed over a much
  shorter window, and the response reports the *input frame's* length as the number of days analysed.
- **Evidence**:
  ```python
  10492:        return {
  10493:            **res,
  10494:            "universe": ticker_list,
  10495:            "history_days_analyzed": len(returns_df),
  10496:        }
  ```
- **Mechanism**: (1) `if len(returns) < lookback_days + rebalance_freq_days` at 65 rebinds both parameters to `max(20, int(len(returns)*0.4))` and `max(5, int(len(returns)*0.1))` at 66-67, with no flag, no log line and no return value carrying either. (2) The simulation loop at `:92` then rebalances on that shortened schedule, so `rebalance_events[].weights` and the equity curve are built from a window the caller never asked for. (3) The route publishes `history_days_analyzed: len(returns_df)` — the length of the **input** frame, before any shortening — under a name that reads as the simulated sample size.
- **Impact**: Every figure in the backtest response (`cagr`, `sharpe_ratio`, `max_drawdown`, `calmar_ratio`, `total_turnover`, `rebalance_events`) is correctly computed **for the run that actually happened** but not for the run that was requested, and the one field that looks like a disclosure names the wrong quantity. Partial mitigation: the response's `equity_curve` (`:234`) has one entry per simulated out-of-sample day, so a consumer counting entries can recover the true `n_days` — but nothing in the payload says that. This is the same disclosure-mismatch family as `SVC-7`.
- **Suggested fix**: Shape only — return the effective `lookback_days` / `rebalance_freq_days` / simulated `n_days` alongside the figures, and rename or drop `history_days_analyzed` so it no longer claims to be the analysed sample. Blast radius is one response schema plus the frontend card that reads it. **Ordering hazard**: `n_days` at `backtest_service.py:185` is the correct disclosure value and must be read after the loop, not from the request.

### SVC-7 — The backtest annualises without the `MIN_ANNUALIZE_DAYS` gate the codebase already defines
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/backtest_service.py:185-188`; the rule being skipped at `backend/app/utils/holdings.py:32-35`; the route's mis-targeted gate at `backend/app/api/analytics.py:10479`
- **Symptom**: A backtest over a short simulated window publishes a triple-digit CAGR as though it
  were measured over a year.
- **Evidence**:
  ```python
  185:    n_days = len(strat_rets)
  186:    years = n_days / TRADING_DAYS
  187:
  188:    strat_cagr = float((strat_cum[-1]) ** (1.0 / years) - 1.0) if years > 0 else 0.0
  ```
- **Mechanism**: (1) `n_days` counts **simulated out-of-sample days**, not input rows; after `SVC-6`'s shortening, `n_days` is roughly `0.6 × len(returns)`, so a 30-row input yields about 10 simulated days. (2) `years = 10/252 = 0.0397`; the only guard is `years > 0`, which is true for any `n_days ≥ 1`, so `strat_cum[-1] ** 25.2` is published. (3) `MIN_ANNUALIZE_DAYS = 30` (`holdings.py:35`) is applied by the route to the **input frame** at `analytics.py:10479`, never to `n_days` — so the gate exists, is named, and is applied to the wrong quantity.
- **Impact**: `cagr` and `benchmark_cagr` on the backtest response. Note the same function gets this right two ways at other sites: `strat_sharpe` at `:201` and `strat_calmar` at `:207` both publish `None` rather than a number when the denominator is unusable. That inconsistency inside one `return` dict is the strongest argument that `:188` is a defect rather than a policy. `MIN_ANNUALIZE_DAYS`'s own comment (`holdings.py:32-34`) states the rule in the first person: *"annualizing a week of history fabricates triple-digit percentages."*
- **Suggested fix**: Shape only — gate `strat_cagr` / `bench_cagr` on `n_days >= MIN_ANNUALIZE_DAYS` and publish `None` plus the existing reason token, matching the `strat_sharpe` / `strat_calmar` pattern. Blast radius is two response fields. **Fix `SVC-6` and `SVC-7` together**: gating on `n_days` alone is insufficient while the caller can silently shorten `n_days` in the first place.

### SVC-8 — `compute_rolling_avg_correlation` averages over a shrinking pair denominator
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/correlation_service.py:62`, produced by `:57`, with `min_periods` set at `:50`; endpoint `backend/app/api/analytics.py:10923`
- **Symptom**: A date on which only 2 of the book's pairwise correlations are measurable publishes
  the mean of those 2 under the label "average pairwise correlation", and that value then sets
  `alert_level` and `is_regime_break`.
- **Evidence**:
  ```python
  57:            pair_corr = s1.rolling(window=window_days, min_periods=min_periods).corr(s2)
  58:            pair_corrs.append(pair_corr)
  59:
  60:    # Average across all N*(N-1)/2 pairs
  61:    pairs_df = pd.concat(pair_corrs, axis=1)
  62:    avg_corr_series = pairs_df.mean(axis=1).dropna()
  ```
- **Mechanism**: (1) `min_periods = min(window_days, 30)` at `:50` means each pair's rolling correlation is NaN until its own window has 30 observations, so early in the sample **most pairs are NaN** and a shrinking minority are not. (2) `pairs_df` is a pandas `DataFrame` with one column per pair; `DataFrame.mean(axis=1)` defaults to `skipna=True`, so it averages **only the non-NaN pairs at that row** — the denominator is the number of measurable pairs at that date, not the `N(N-1)/2` the code comment at `:60` and the docstring formula at `:24` (`rho_bar_t = (2 / (N * (N - 1))) * sum_{i < j} rho_{i,j,t}`) both assume. (3) `dropna()` at 62 removes only fully-empty rows, so a row with 2 of 990 contributions survives and looks identical to a complete one.
- **Impact**: `series[].avg_correlation` on the correlation-stability response, and through it the 75th/90th/10th percentile comparisons that set `alert_level` and `is_regime_break` — a diversification-break alert the user acts on. The one present mitigation is the module's own `len(clean_returns) < 30` rejection at `:44-47`, which bounds the damage to the head of the series rather than eliminating it: for a 14-name book, 91 pairs exist and the transition region after 30 observations is where the denominator is still climbing.
- **Suggested fix**: Shape only — count non-NaN pairs per row and either drop rows below a declared minimum (e.g. half of `N(N-1)/2`) or publish the contributing-pair count alongside each point. Blast radius is one series and its percentile thresholds. **Do not** fill NaN pairs with `0.0`; a missing pair correlation is not a zero correlation.

### SVC-4 — `screener_service._filter` turns absent fundamentals into `0.0` against lower bounds, while `pe` is excluded
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/screener_service.py:317-320` with the comparisons at `:326-335`; the correct pattern in the same file at `:354-359`
- **Symptom**: A company whose fundamentals the provider could not supply passes a
  "ROCE ≥ X / ROE ≥ Y / market cap ≥ Z" screen on the strength of values that were never measured.
- **Evidence**:
  ```python
  316:
  317:            roce = info.get("returnOnCapitalEmployed") or 0.0
  318:            roe = (info.get("returnOnEquity") or 0.0) * 100
  319:            pe = info.get("trailingPE") or 999.0
  320:            mcap = info.get("marketCapInCr") or 0.0
  ```
- **Mechanism**: (1) bfinance types every one of these as `Optional[float]` — `market/quotes.py:236, 235, 244, 246` all emit `None` when the underlying field is unavailable (`company.py:14` shows `current_price: Optional[float] = None` is a normal value, not an error). (2) `None or 0.0` evaluates to the Python `float` `0.0`, which **admits** against the lower-bound tests at 326/328/332/334. (3) `pe` at 319 is treated the opposite way: `999.0` excludes, and line 330 additionally rejects `pe <= 0`. Two adjacent lines in one filter take opposite positions on what an absent value means.
- **Impact**: The screen result set — the list of companies a user is shown as passing their fundamentals criteria. The absence is disclosed nowhere: the `or 0.0` happens inside the filter closure, so the surviving rows publish only the measured fields. **The scale question in the inventory is now settled and is NOT a defect**: `info["returnOnEquity"]` is a decimal (`market/quotes.py:244` — `(r.roe / 100.0) if r.roe else None`) and `info["returnOnCapitalEmployed"]` is raw percent (`market/quotes.py:246` — `r.roce`), which is exactly what lines 317-318 assume. bfinance's own built-in screen applies the identical transform (`bfinance/screens.py:144-145`).
- **Suggested fix**: Shape only — return `None` for an absent fundamental and skip the comparison that needs it, recording the skip per ticker so the screen can publish "unscored on ROCE" rather than "passed". Blast radius is the filter closure and the custom-screen response. **Note**: the `or 0.0` idiom is also what bfinance uses in its own screens, so this is a finengine-side policy decision, not an upstream bug — but the asymmetry with `pe` at line 319 means the file already does not hold that policy consistently.

### SVC-9 — `equity_research_service` publishes `current_price: 0.0` as a real price
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/equity_research_service.py:57` (published at `:86`) and `:231` (published at `:247`); the correct guard at `:59`
- **Symptom**: An equity research card shows a current price of ₹0 for a ticker whose provider
  returned no quote.
- **Evidence**:
  ```python
  57:            cmp = r.current_price or info.get("currentPrice") or 0.0
  58:            graham_upside = None
  59:            if graham_num and cmp and cmp > 0:
  60:                graham_upside = round(((graham_num - cmp) / cmp) * 100, 2)
  ```
- **Mechanism**: (1) `r.current_price` is `Optional[float]` (bfinance `models/company.py:14`), and `info["currentPrice"]` is itself computed upstream as `r.current_price or latest_price or 0.0` (`bfinance/market/quotes.py:112`, emitted at `:214`) — so both fallbacks can be `0.0` or `None`. (2) The chain at 57 terminates in the Python `float` `0.0` and that value is published as `current_price` at `:86` and `:247`, indistinguishable from a measured ₹0. (3) The very next line at 59 correctly treats `cmp` as possibly unusable (`and cmp and cmp > 0`) and refuses to derive `graham_upside` — so **no derived figure is corrupted**; the raw field is the whole of the defect.
- **Impact**: `current_price` on both the profile response and the ratios response. The sibling fields at `:87-98` are correct — `r.market_cap or info.get("marketCapInCr")` and its siblings end as `None` when both sources are empty, with no `or 0.0` coercion — so the payload mixes a fabricated zero in one field with honest nulls in the rest. Prevalence is unmeasured: it depends on how often bfinance returns `current_price = None`.
- **Suggested fix**: Shape only — stop the chain at `None` and publish `None`, matching the fields at `:87-98`. The `cmp and cmp > 0` guard at 59 keeps working unchanged. Blast radius is one field on two responses. **Do not** substitute `0.0` or `.real`; the file's own convention four lines down is the correct one.

### SVC-10 — A failed t-fit substitutes `nu = 4.0`, which is indistinguishable from a fitted value
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/tail_risk_service.py:503`, returned unmarked at `:515`; the correct contrast in the same file at `:326-339`
- **Symptom**: When the t-fit raises, the lower-tail dependence coefficient is published as though
  it were fitted, with no marker on the payload.
- **Evidence**:
  ```python
  499:                df_a, _, _ = stats.t.fit(r_a)
  500:                df_b, _, _ = stats.t.fit(r_b)
  501:                nu = float(np.clip((df_a + df_b) / 2.0, 2.1, 30.0))
  502:            except Exception:
  503:                nu = 4.0
  ```
- **Mechanism**: (1) The bare `except Exception` at 502 catches any `stats.t.fit` failure and assigns the literal `4.0`. (2) `4.0` sits **inside** the `[2.1, 30.0]` clip range applied on the success path at 501, so it passes every downstream plausibility test — `lambda_l` at `:511-512` consumes it as `df=nu + 1.0` with no way to tell it apart from a fit. (3) The function then `return lambda_l, rho, nu` at `:515` with no fit-status field, so the substitution does not leave a trace.
- **Impact**: `lambda_l` (lower-tail dependence) and `nu` (degrees of freedom) on the tail-dependence matrix. The contrast is inside the same file and the same class: when the **GPD** fit fails, the code at `:326-339` sets `model_fitted = False` and appends `"fit_failed"` to `constraint_reasons`, and the payload discloses it. The t-fit path has no equivalent, so one kind of failed fit in this file is disclosed and the other is not.
- **Suggested fix**: Shape only — carry a `fit_succeeded` boolean alongside `nu` out of the function (it already returns a tuple) and surface it in the matrix payload alongside the existing `model_fitted` convention. Blast radius is one return-tuple signature and its two call sites. **Do not** re-order the tuple's third element into a different position; check the callers first.

### SVC-3 — `_store_timeseries_data` executes DB writes outside the lock the file's own comment says is required
- **Class**: risk
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/data_service.py:1700-1704` (unlocked writes), caller at `:1339`; the invariant stated at `:238-243`; the two conforming callers at `:706` and `:773`
- **Symptom**: None observed — an intermittent write collision would surface as a
  `"commit() can't be called here"` or `"transaction is closed"` error and a dropped cache write.
- **Evidence**:
  ```python
  1700:            await self.db.execute(stmt)
  1701:            if not cache_generation_is_current(write_generation):
  1702:                await self.db.rollback()
  1703:                return False
  1704:            await self.db.commit()
  ```
- **Mechanism**: (1) The comment at `:238-243` states the invariant in the authors' own words — *"SQLAlchemy sessions are not concurrency-safe: parallel commits/rollbacks on one session collide … only DB operations are serialized through this gate"* — and instantiates `self._db_lock` at 243. (2) `_store_timeseries_data` has exactly **three** call sites: 706 and 773, both reached inside an `async with self._db_lock:` block opened at 704 and 771, and 1339, which is not. (3) The function itself takes no lock and its signature (`:1619-1625`) has no lock parameter, so nothing in it re-establishes the invariant.
- **Impact**: Cache-write integrity on the Alpha Vantage persist path. **Not measured**: whether a collision actually occurs — the batch fetchers run concurrent workers over one session only under a specific interleaving, and no collision has been observed. Severity is RISK, not higher, for that reason; the *source fact* (three call sites, one unguarded, contradicting a stated invariant) is verified. `check_data_integrity` (`:1789`) has the same problem but is **dead code** — `Select-String` for `check_data_integrity` across `backend/app/**/*.py` returns exactly one hit, the definition itself — so it is not carried as a separate claim.
- **Suggested fix**: Shape only — acquire `self._db_lock` around the DB section of `_store_timeseries_data`, and make the lock re-entrant-or-absent for the two callers that already hold it. **Blast radius: this is the deadlock hazard in this file and it is the main reason the fix cannot be done naively.** `asyncio.Lock` is **not re-entrant** — wrapping the function body would deadlock the instant caller 706 or 773 reached the `await` while already holding the lock at 704/771. Either (a) split the DB section into a `_store_timeseries_data_locked` inner coroutine and have the existing lock-holding callers call that, keeping the wrapper for 1339, or (b) hoist the lock acquisition to the three call sites rather than into the shared function.

### SVC-5 — `IndiaDataService` has no lock at all, so the exclusion `data_service.py` was written to guarantee does not hold across the two services
- **Class**: risk
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/india_data_service.py:105-106`; unguarded write sites at `:164-225` and `:259-316`; constructed at `backend/app/api/analytics.py:12095`, `:12147`, `:12252`
- **Symptom**: None observed — the failure mode is the same write collision as `SVC-3`.
- **Evidence**:
  ```python
  102: class IndiaDataService:
  103:     """Service managing Indian microstructure, NSE archives, and liquidity limits."""
  104:
  105:     def __init__(self, db: AsyncSession):
  106:         self.db = db
  ```
- **Mechanism**: (1) `__init__` stores the request-scoped `AsyncSession` and nothing else — there is no lock, and `Select-String` for `Lock` in this file returns **zero** hits while the same cmdlet on the same file returns 23 hits for `db.execute|db.commit|db.rollback`. (2) None of those 23 sites is guarded. (3) All three construction sites pass the same request `db`, so the mutual exclusion `data_service.py:238-243` exists to guarantee is simply absent from the second service that shares the session.
- **Impact**: Write integrity on the NSE bhavcopy ingest and liquidity-limit persistence paths. **Not measured**: no collision has been observed and the file was never audited for this. Severity RISK. Note the inventory's count of "ten" `db.execute`/`commit` sites is an **undercount** — there are 23 — which makes the gap larger, not smaller.
- **Suggested fix**: Shape only — a single session-scoped lock shared with `DataService`, e.g. attached to the session or injected alongside it. **Blast radius / hazard: a per-instance lock does not fix this.** `IndiaDataService` is constructed fresh at three call sites with the same session, so two independent `asyncio.Lock` objects would not exclude each other and the invariant would still be violated — exactly the same non-re-entrancy and non-sharing trap as `SVC-3`. Whoever implements `SVC-3` and `SVC-5` should land one session-scoped primitive and have both services use it.

### SVC-11 — Dead `_l1_ttl` / `_L1_TTL_SECONDS` sit beside a comment asserting the live TTL as fact
- **Class**: maintainability
- **Severity**: NIT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/data_service.py:313-317`; the live value comes from `_l1_ttl_seconds` at `:259`, read at `:407` and `:627`
- **Symptom**: None — developer-facing.
- **Evidence**:
  ```python
  313:    # Deep-cache horizon: vendor-max backfills download up to 10y back from
  314:    # `end`, regardless of the requested window. L1 keeps a 5-min TTL.
  315:    DEEP_CACHE_YEARS = 10
  316:    _L1_TTL_SECONDS = 300
  317:    _l1_ttl = _L1_TTL_SECONDS
  ```
- **Mechanism**: (1) The comment at 314 asserts "L1 keeps a 5-min TTL" as a property of the system. (2) The enforced value is `_l1_ttl_seconds(config)`, which reads the persisted `cache_ttl_minutes` runtime config — so the TTL is operator-configurable and the comment is wrong the moment an operator changes it. (3) `_L1_TTL_SECONDS` and `_l1_ttl` are dead: `Select-String` for `_l1_ttl|_L1_TTL_SECONDS` across `backend/**/*.py` (excluding `.venv` and `__pycache__`) returns five hits — 259, 316, 317, 407, 627 — of which 316-317 are the definitions and 259/407/627 are the separate `_l1_ttl_seconds` **method**. The constant has no reader.
- **Impact**: None — developer-facing, no user-visible effect. The risk is purely that the comment reads as a documented invariant and a future reader tunes the dead constant believing it is live.
- **Suggested fix**: Delete `_L1_TTL_SECONDS` and `_l1_ttl` (lines 316-317) and amend the comment to name `_l1_ttl_seconds` and the `cache_ttl_minutes` setting it reads. Blast radius is nil once the zero-reader count is confirmed at implementation time.

---

## Rejected on re-verification

### 1. `SVC-1`'s published outcome — **REJECTED AS WRONG; the finding stands, corrected**
The inventory asserts the NaN path publishes `score = 3.0`, `category = "Low"`,
`liquidation_days = "5-10"`, `risk_level = "High"`. The last three are correct. **`score = 3.0` is
not** — the published score is **5.9**.

Reproduce (pure arithmetic, no application code, no I/O):
```
cd C:\es\coding\finengine\backend
.\.venv\Scripts\python.exe -c "nan=float('nan'); v=nan*1500.0; print(v, max(2.5, min(5.9, 3.0 + (v/2e7)*2.9)))"
```
Output on CPython 3.12.9: `nan 5.9`.

The resolved types are the reason, and they are the distinction plan §3.5 calls out. `volume` and
`price` at `analytics_engine.py:3945-3946` are both **Python `float`s** (not numpy scalars), so
`daily_turnover` is a Python `float` NaN. Python's two-argument `min(a, b)` returns `a` unless
`b < a`; `nan < 5.9` is `False`, so `min(5.9, nan)` returns **`5.9`**, and `max(2.5, 5.9)` returns
**`5.9`**. A numpy-scalar operand would have taken a different path through the comparison. The
finding above states 5.9 and the correction makes it *worse* than reported, not milder.

### 2. `SVC-4`'s "scale question … which this run could not read" — **RESOLVED, and it is NOT a defect**
The bfinance `info` schema is readable in `backend\.venv\Lib\site-packages\bfinance`:
`market/quotes.py:244` emits `"returnOnEquity": (r.roe / 100.0) if r.roe else None` — a **decimal** —
and `market/quotes.py:246` emits `"returnOnCapitalEmployed": r.roce` — **raw percent**.
`bfinance/screens.py:6-7` documents the same contract in prose, and `bfinance/screens.py:144-145`
applies the identical `roce = ... or 0.0` / `roe = (...) * 100` transform that
`screener_service.py:317-318` does. **The scaling is correct.** The finding is narrowed to the
`None → 0.0` admission asymmetry against the lower bounds.

### 3. `SVC-5`'s citation `portfolio.py:107` — **REJECTED (wrong file, wrong construct)**
`backend/app/api/portfolio.py:107` is `def get_data_service(db: AsyncSession = Depends(get_db_session)) -> DataService:`.
`Select-String` for `IndiaDataService` in `portfolio.py` returns **zero** hits. The only construction
sites are `analytics.py:12095`, `:12147` and `:12252`, all of the form
`india_svc = IndiaDataService(db=db)`. The finding above cites the three real sites.

### 4. `SVC-5`'s "ten `db.execute`/`commit` sites" — **REJECTED UNDERCOUNT**
There are **23** `db.execute` / `db.commit` / `db.rollback` sites in
`india_data_service.py`, at lines 164, 198, 200, 202, 206, 218, 219, 222, 225, 259, 271, 273, 275,
278, 290, 292, 295, 297, 310, 313, 316, 330 and 402. None is guarded. The gap is larger than
reported.

### 5. `SVC-3`'s `check_data_integrity` half — **NOT EMITTED (dead code)**
`check_data_integrity` is defined at `data_service.py:1789` and has **zero** call sites anywhere
under `backend/app/**`. Its unguarded DB reads therefore cannot fire. The finding above carries the
`_store_timeseries_data` half only and says so. (Removing dead code is a legitimate cleanup, but it
is not a defect with a symptom and it does not belong in a severity band.)

### 6. `SVC-2`'s `< 10` branch location — **CONFIRMED, no correction**
Stated here because it is the one inventory claim in this file that is load-bearing *and* exactly
right: the docstring at `analytics_engine.py:5439-5447` says in the authors' own words that a hard
`0.0` on an unmeasured ratio "is the one number a reader must never be handed", and the sibling
branch at `:5460-5461` publishes `None`. The zero-variance path at `:5468` and `:5476` does not.

### 7. Unmeasured claims **not carried** into the findings
Three inventory assertions are runtime claims that reading cannot settle, and none is asserted
anywhere in this file: whether the `SVC-3` write collision actually occurs; whether `SVC-1`'s NaN
volume condition occurs in production and how often; and `SVC-9`'s prevalence of
`current_price = None`. Each finding's Impact or Confidence field states the gap explicitly rather
than implying it was checked.

---

## Reviewed, not emitted as findings

**The services cache inventory.** The input file closes with a table concluding the cache layer is in
good shape, and a forward-looking note about `AnalyticsCache` being generic. **Positive claims are
not ledger rows**, and this section exists so the conclusion is neither silently dropped nor silently
endorsed.

**Every citation in that table names the wrong source file.** The line numbers are right; the
filename is not. Confirmed by locating each symbol:

| Cache | Inventory cited | Actually in |
|---|---|---|
| `_IN_MEMORY_COINT_CACHE` (TTL on read) | `data_service.py:1678` | `cointegration_service.py:1673-1680` |
| Cointegration DB contract token | `data_service.py:886` | `cointegration_service.py:886` and `:910` |
| `_cached_pair_satisfies_contract` | `data_service.py:1720-1766` | `cointegration_service.py:1720` |
| `_yf_fundamentals_cache` (TTL on read) | `data_service.py:226` | `company_data_service.py:218` |
| `_exchange_rates` | `data_service.py:319-323, 191, 199` | `currency_service.py:131, 170, 182` |
| `AnalyticsCache` (DB) | `data_service.py:291` | `models/database.py:140`, used via `cache_service.py:13` |
| `_in_memory_df_cache` (TTL on read) | `data_service.py:407, 627` | **correct** (`data_service.py:407`, `:627`) |
| `_quote_memo` (TTL + generation) | `data_service.py:905, 900, 907` | **correct** (`data_service.py:905`, `:900`, `:907`) |

The two rows marked *correct* are the two whose symbols are genuinely declared in `data_service.py`;
the rest live in four other modules. The `models/cache_service.py` clearing calls at
`:174` and `:196` confirm the cross-module ownership.

**What was and was not re-verified.** I opened 4 of the 8 caches directly and confirmed TTL
enforcement on the **read** path in each: `_in_memory_df_cache` (`:407`, `:627`, both comparing
against `_l1_ttl_seconds(config)`), `_quote_memo` (`:905` against `_quote_ttl_seconds(config)`, with
the generation fence at `:900` and `:907`), `_IN_MEMORY_COINT_CACHE`
(`cointegration_service.py:1677-1680`, TTL plus `_cached_pair_satisfies_contract`), and
`_yf_fundamentals_cache` (`company_data_service.py:218`). I did **not** re-verify the
`AnalyticsCache`, `ScreenerService._cache` and `_exchange_rates` rows. The table's *conclusion* —
TTLs enforced on read, contract versions on the two caches that hold derived analytics — is
consistent with everything I checked, but it is **not** a claim this file endorses as fully verified.

**The one forward-looking risk is real but is not a finding today.** `AnalyticsCache` is generic, so
a *future* metric whose writer omits a contract check would re-serve a stale row indefinitely. No
such writer exists today — the cointegration path is the only heavy user and it does supply a
contract version at `cointegration_service.py:886` and `:910`. This is a design property of a
working system, not a defect, and it is deliberately given **no `SVC-*` id**: it is not one of the
inventory's 11 items, and inventing an id for it would break the "every id appears exactly once"
gate the assembler checks. It is recorded here so it is not lost.

---

## Notes for the assembler

- **Ordering:** 1 BLOCKER, 7 DEFECT, 2 RISK, 1 NIT = 11 findings — all below the §1-§4 caps.
- **Dedup:** `SVC-2` and `SVC-1` are the same *class* of defect as `API-3` (a value published where
  the honest value is "unmeasured") but they are different defects at different locations with
  different payloads. They must remain three separate rows.
- **Pairing:** `SVC-6` and `SVC-7` are one bug in the backtest response seen from two angles —
  the disclosure names the wrong quantity, and the annualisation gate is applied to the wrong
  quantity. The two findings say so in their fix-shape fields; a reader fixing one without the
  other will not close the user-visible symptom.
- **Shared remediation, do not split:** `SVC-3` and `SVC-5` must land together. Both need a
  *session-scoped* lock, and `asyncio.Lock` is not re-entrant and a per-instance lock does not
  exclude across the two services. Landing either alone leaves the invariant broken and risks a
  deadlock at `data_service.py:704`/`:771`.
