# Wave 2 — the deliverable surface and the measurement instrument

**Date:** 2026-09-30
**Status:** proposed, pending adversarial review
**Predecessor:** wave 1 (three in-flight fixes: `analytics_engine.py` annual_return/EWMA seed; `analytics.py` + `india_data_service.py` fabricated liquidity base; `cointegration_service.py` + `schemas.py` stationarity gate)

---

## 0. The framing, stated once so no task inherits a false premise

The standing ambition is "a true Bloomberg / JP Morgan / Jane Street Terminal alternative."
Four of the seven capabilities that phrase names are **correctly absent** from this
repository and cannot be added by any amount of engineering:

| Capability | Why it is a category error here |
|---|---|
| Entitlements / symbology | Single-user, no multi-tenancy, nothing to entitle. Indian symbology is already solved for this scope by the `.NS`/`.BO` suffix. |
| Real-time streaming | `yfinance` exposes no streaming API. `cache_ttl_minutes: 60` in `backend/app/config.py` is an honest statement of the real capability, not a gap. |
| Order / execution / pre-trade risk | A different product with a different regulatory surface. Cannot be built; only licensed or partnered. |
| Compliance / surveillance | Presupposes a duty to monitor other people's trades. A self-directed portfolio has none. |

A Terminal is ~90% data fabric and ~10% analytics. This repository is ~95% analytics and
~5% data access. **The leverage is inverted, and no agent can invert it.**

What remains after stripping those four is *"Zerodha Console meets a research notebook."*
That is a real and defensible product. It is one to two orders of magnitude smaller than
a Terminal. Every task below is valuable under **all three** possible futures for this
repo — single-user terminal, multi-user SaaS, multi-asset platform — which is why the
fork does not block the work. It is recorded here so no downstream agent mistakes the
ambition for a specification.

**Consequence for task design:** wave 2 adds no asset class, no broker integration, no
real-time path, and no user model. It hardens what exists and makes the product's primary
deliverable honest.

---

## 1. What wave 1 leaves open, and why it is not in this wave

| Finding | Why deferred |
|---|---|
| `STRESS_UNCLASSIFIED_SECTOR = "Exchange Traded Fund"` labels unclassified holdings as ETFs in the published payload | `analytics_engine.py` is owned by a wave-1 agent |
| VaR/CVaR horizon label on the realized-risk side (`backend/app/models/schemas.py` + engine) | `schemas.py` owned by a wave-1 agent; engine owned too |
| `india_data_service.py:403` `ddof=0` z-score | `india_data_service.py` owned by a wave-1 agent |
| `arch.bootstrap.MCS` as a dependently-valid third multiplicity correction | `cointegration_service.py` owned by a wave-1 agent |
| GJR-GARCH; quantstats metric additions; `annualized_alpha` scale | All in wave-1-owned files |
| QuantLib NSE trading calendar behind the `np.sqrt(252)` sites | **Blocked.** ~21 executable sites across three distinct meanings (de-annualisation divisor vs horizon scaling vs signature defaults), and the golden-value harness it depends on does not exist. M→L, not S. Not in this wave. |

---

## 2. Tasks

### T1 — The institutional PDF stops asserting, and starts computing

**Files (exclusive):** `frontend/src/lib/export.ts`, `frontend/src/components/layout/Header.tsx`,
`frontend/src/types/index.ts`
**New tests:** `frontend/src/test/unit/export-pdf-integrity.test.ts`
**Depends on:** nothing. Fully disjoint from wave 1.
**Depth:** needs autonomous judgement on the rasterization approach — see T1a.

Current state, verified by read on 2026-09-30:

- `export.ts:89-98` `addChart` is a stub drawing a grey rect and the literal text
  `"Chart Image"`. Zero callers repo-wide.
- `export.ts:319` `exportInstitutionalReviewPDF` is the live path; its only call site is
  `Header.tsx:61-65`.
- Its 124-line body (`:325-442`) contains **no** `addImage`, no canvas, no `toDataURL`.
- `:323` declares `riskMetrics?: any`; the identifier appears exactly once in the file
  (the annotation). It is **not passed** at the call site either. There is no code in the
  frontend that constructs a `riskMetrics` object.
- `:428`, `:430`, `:432` are three hardcoded prose strings, byte-identical for every
  portfolio, over a section header (`:423`) reading *"Quantitative Risk & Microstructure
  Summary"* above zero computed numbers. This is a direct violation of `AGENTS.md`:
  *"Metric Card Hygiene: keep metric cards deduplicated and strictly driven by live API
  responses without placeholder mock deltas."*

Scope:

1. **Delete the fiction.** `:423-432` must be driven by values that exist. Where a value
   is absent, say so — a withheld figure is a valid outcome; a fabricated sentence is not.
   Every sentence in the output must be traceable to a field the function received.
2. **Put real risk data in.** Wire `riskMetrics` and make the call site pass it. The
   minimum honest set is the numbers the prose currently claims to describe: the
   volatility contribution, the CVaR tail share, and the ADV liquidation horizon. If the
   backend does not supply one, the sentence is absent — it is **not** filled from another
   section, and **not** defaulted.
3. **Charts.** Follow **T1a as resolved** — it is a decision with a justification, not a
   menu. In short: attach the ref to the **chart component** (`<BarChart ref={r} />`), never
   to `ResponsiveContainer`; invert the `export.ts:265-271` guard so a non-`svg` or `null`
   input **rejects** instead of resolving a blank PNG; apply the capped-DPR fix at
   `:237-239`; call `doc.addImage(canvas, …)` with an explicit `compression`. **Do not use
   jsPDF's `addSvgAsImage`** — at 4.2.1 it is canvg rasterization at ~7.2 DPI with a hidden
   async rejection, not the vector API its name implies. **Add no new dependency.** And
   handle the **legend portal** (T1a finding 5) explicitly: a correct `<svg>` ref yields a
   chart with *no legend*, so either render the legend inside the export chart or state the
   limitation in the PDF. Ship a chart whose series identity is only in a missing legend
   and the PDF is misleading, which is the exact defect class this project exists to
   prevent.
4. **Currency and units.** `:344` `new Date().toLocaleString()` has no locale argument.
   `:357` emits the ASCII code `"INR "`, not `₹`, and the `: '$'` fallback prints a USD
   sign with no FX rate. `:400-401` prices use `toFixed(1)` with no thousands grouping and
   no symbol, adjacent to a grouped `en-IN` market-value column at `:402`. `:404`
   `p.sector || 'General'` fabricates a sector label in an artifact stamped CONFIDENTIAL.
   The holdings table prints no currency symbol on any of its 7 columns. The repo mandates
   `en-IN` with ₹/Cr/L — reuse `frontend/src/lib/utils.ts:23-46` (`formatCurrency`) and
   `:92-100` (`formatIndianRupees`) rather than hand-rolling a third implementation.
   `frontend/src/lib/utils.ts:107-118` `formatLargeNumber` is US-centric K/M/B with no ₹
   awareness and has zero call sites: do not introduce any.

**Verify:**
```
cd frontend
npx tsc --noEmit
npx vitest run src/test/unit/export-pdf-integrity.test.ts
npx eslint src/lib/export.ts src/components/layout/Header.tsx
```
Plus a grep that must return **zero** hits:
```
npx grep -n "Euler Decomposition\|Extreme Value Theory:\|Market Microstructure: ADV" src/lib/export.ts
```

**A vitest test that claims to check pixels is a defect, not a test.** `node_modules/canvas`
is not installed, so `getContext('2d')` returns `null` in jsdom and no pixel assertion can
run. Assert the observable pipeline instead (T1a finding 7): the ref is an `SVGElement`
with class `recharts-surface`; a non-`svg` or `null` input rejects; the DPR arithmetic is a
pure function asserted directly; the serialised SVG has substance; and
`doc.output('arraybuffer')` contains `/Subtype /Image`. If T1 wants a genuine blank-image
assertion, that is a Playwright E2E test with a real Chromium `getImageData` variance
check — say so in the report rather than shipping a vitest test that passes without
testing anything.

---

### T1a — RESOLVED. The rasterization route, and the architecture it forces.

*Resolved 2026-09-30 by `librarian` against the lockfile (`frontend/bun.lock`, Bun).*
**`recharts` resolves to exactly 3.10.1 and `jspdf` to exactly 4.2.1** — both at the floor
of their caret ranges, but nothing *holds* them: a future `bun install` can float up. If
T1 depends on the internals below, pin the ranges exactly.

**Finding 1 — the live bug is a `tagName` mismatch, and recharts v3 hands you the fix.**
`CategoricalChart` is `forwardRef<SVGSVGElement, …>`
([`CartesianChart.tsx:43`](https://github.com/recharts/recharts/blob/ffb918798051ef040bb7f9922d3850c9c189f39f/src/chart/CartesianChart.tsx#L43)),
and `BarChart`/`LineChart`/`AreaChart`/`ComposedChart`/`ScatterChart` re-type themselves as
`props & { ref?: React.Ref<SVGSVGElement> }`. The ref lands on `Surface`, whose root is
literally `React.createElement("svg", …, ref)`. So `<BarChart ref={r} />` gives
`r.current === <svg class="recharts-surface">` — **exactly the element the `export.ts:248`
guard is looking for and has never received.**

A ref to `ResponsiveContainer` yields the wrapper `div`
([`ResponsiveContainer.js:75,140`](https://github.com/recharts/recharts/blob/ffb918798051ef040bb7f9922d3850c9c189f39f/src/component/ResponsiveContainer.js#L75)),
or **`null` and permanently `null`** when width/height are fixed numbers, because
`ResponsiveContainer` then renders no DOM node at all
([`:202-216`](https://github.com/recharts/recharts/blob/ffb918798051ef040bb7f9922d3850c9c189f39f/src/component/ResponsiveContainer.js#L202-216)).
Either way control reaches `export.ts:265-271`: `canvas.toBlob` on a never-drawn canvas,
resolving a valid white PNG. **A PDF with a blank chart and no error.**

There is no `toSvg`/`toDataURL`/headless path. The 2018 export request
([#1245](https://github.com/recharts/recharts/issues/1245)) was closed unimplemented, and
`MainChartSurface` returns `null` unless the measured width and height are positive. **A
live, laid-out DOM is required. A live ref suffices; a live query does not.**

**Finding 2 — jsPDF v4 has no vector SVG support. `addSvgAsImage` is canvg *raster*.**
[`src/modules/svg.js:21321-21351`](https://github.com/MrRio/jsPDF/blob/v4.2.1/src/modules/svg.js)
ends in `doc.addImage(canvas.toDataURL("image/jpeg", 1.0), …)`. It hardcodes `image/jpeg`
at quality 1.0 regardless of what you asked for; sets `canvas.width` in **PDF units (mm)**
then draws back at that size, so the raster is **~1 px per mm ≈ 7.2 DPI** with no DPR knob;
paints a white background first; and `loadCanvg()` is a dynamic `import()` of an *optional*
dependency that **rejects** if `canvg` is absent — inside a method whose `.d.ts` claims a
synchronous `jsPDF` return. **Strictly worse than the manual path while looking like a
first-class API. Do not use it.**

**Finding 3 — decision: route (i), existing pipeline, plus DPR. Zero new dependencies.**
SVG → `Image` → canvas → `PNG` → `addImage`. It loses font fidelity — the shape is right,
the typography is not — and that is the accepted cost, stated rather than hidden.

> **TRAP — found by checking the official jsPDF docs *after* the route was chosen, and it
> sits in the route I picked.** The signature is `addImage(imageData, format, x, y, width,
> height, alias, compression, rotation)` and `imageData` does accept `HTMLCanvasElement`
> directly, so no `toDataURL` round-trip is needed. **But `format` is documented as
> "Required — format of file if filetype-recognition fails *or in case of a Canvas-Element
> needs to be specified (default for Canvas is JPEG)*".** Passing a canvas with no format
> **silently JPEG-compresses the chart** — lossy artifacts on exactly the thin antialiased
> strokes and small tick text a chart is made of. **`format` must be passed as `'PNG'`
> explicitly.** An earlier draft of this plan said "call `doc.addImage(canvas, …)`" with no
> format, which would have shipped a visibly degraded chart. `compression` is a real enum
> (`'NONE'|'FAST'|'MEDIUM'|'SLOW'`, defaulting to `NONE` via `checkCompressValue`) and must
> also be passed explicitly. `svg2pdf.js` (2,381 kB, 4 deps) would give true vector paths and real PDF text,
but its own README says it maps `font-family` to a font *already registered in the PDF* and
does not embed webfonts: **a recharts chart styled in Inter does not become Inter for
free**, so it buys vector fidelity, not the typography the document needs, at 8× the
bundle. `html-to-image` (308 kB, zero deps, 8.0M weekly, **19 months stale**) and
`dom-to-image-more` (975 kB, zero deps, 318k weekly, **published six days ago**, and
3.11.0 specifically fixes SVG `url(#id)` references that recharts v3's `ClipPathProvider`
and gradient defs depend on) both take a `foreignObject` path whose fragility is documented
by issue number in their own source. Against `AGENTS.md`'s YAGNI ladder, neither earns a
new dependency to solve a problem route (i) solves adequately once the ref is right.
**Neither library has any upstream statement of recharts-v3 compatibility — that is
unknown, not working.**

**Finding 4 — the DPR fix, at `export.ts:237-239`.** `canvas.width = rect.width` is CSS
pixels. Scale the backing store, not the CSS box:
`dpr = Math.min(window.devicePixelRatio || 1, 2)`, `canvas.width = round(rect.width * dpr)`,
then `ctx.scale(dpr, dpr)` before the existing 2-arg `drawImage` at `:255`, which inherits
the scale. **Cap the DPR at 2** — area scales with DPR² (2× = 4× pixels, 3× = 9×) and 3× is
not perceptible in a viewer that scales to fit. jsPDF `image_compression` defaults to
`NONE` and PNG is decoded and re-encoded, not passed through, so pass `compression`
explicitly. Budget ~+100–300 kB per chart at 2×.

**Finding 5 — the silent failure that would ship a *misleading* PDF, not a blank one.**
In v3 `Legend` renders through `createPortal(legendElement, legendPortal)` into an HTML
`div` **outside the `<svg>`**
([`Legend.tsx:305,389`](https://github.com/recharts/recharts/blob/ffb918798051ef040bb7f9922d3850c9c189f39f/src/component/Legend.tsx#L305))
whenever `position` is null or an outside position. **A perfect `<svg>` ref therefore
yields a chart with no legend at all** — colour keys missing, no exception. If series
identity lives only in the legend, the PDF is silently wrong. This must be handled
explicitly, not discovered later.

**The architecture this forces on T1.** The trigger is `Header.tsx:61`; the charts live on
other routes. Recharts needs a *live, laid-out* DOM, so T1 cannot call a static method and
be handed a chart. Three shapes, and **T1 must pick one and justify it**:
1. Mount a purpose-built offscreen export chart that renders from the same data the PDF
   prints, wait for layout, capture, unmount. Honest, and it means the PDF's chart and its
   numbers come from one source.
2. Capture a chart already on screen. **Rejected:** risks the stale render, the
   empty/loading state, and a `0×0` rect — a visually fine, semantically empty PDF.
3. Serialise chart data and render into a hidden container. Equivalent to (1) with more
   moving parts.

Whatever is chosen: `getBoundingClientRect()` returning `0×0` makes `canvas.width = 0`, and
`toBlob` on a 0×0 canvas **resolves a 0-byte blob rather than rejecting** — so the
`if (blob)` check at `:258` passes and a corrupt embed is written. That must be an explicit
error, not a fallback.

**Finding 6 — the guard must invert.** `export.ts:265-271` currently turns "I was handed
something that is not an SVG" into a blank PNG. That is the defect. It must **reject**. A
blank chart and no error is worse than a PDF that says it could not render one.

**Finding 7 — a true pixel assertion is impossible in this repo's test setup, and the
honest alternative is good.** `vitest.config.mts` is `environment: 'jsdom'`;
`node_modules/canvas` is **not installed**, so `HTMLCanvasElement.getContext('2d')` returns
`null` (`node_modules/jsdom@30.0.1/.../HTMLCanvasElement-impl.js:24`) and `export.ts:232-235`
rejects before reaching any testable logic. `getBoundingClientRect()` returns all zeros and
`img.onload` never fires. So: **unit tests assert the observable pipeline, not pixels** —
(a) the ref is an `SVGElement` with class `recharts-surface`; (b) a non-`svg` or `null`
input **rejects**; (c) DPR arithmetic extracted as a pure function, asserted directly;
(d) the serialised SVG has substance (`path.recharts-curve`/`path.recharts-rectangle` and
`text` nodes both non-zero) — this catches silent-empty and zero-size, the two failures
that actually bite, and **cannot** catch font fallback, which must be stated, not claimed;
(e) `doc.output('arraybuffer')` contains `/Subtype /Image`, proving `addImage` was really
called. **The blank-white-PNG assertion belongs in E2E, not vitest** — a real Chromium
`getImageData` variance check where a blank buffer yields zero non-white pixels. Do not
write a vitest test that pretends to check pixels; it cannot, and it will pass.

---

### T2 — The type that hides a regression

**Files (exclusive):** `frontend/src/types/index.ts`, `frontend/src/test/unit/ai-context-contract.test.ts`
**Depends on:** nothing. **Shares `types/index.ts` with T1 — must be serialized after T1,
or merged into T1.** Parent decides at dispatch.

`AIContextSection` (`types/index.ts:398-440`) declares `data: unknown` as a **required**
key (`:430`) and declares no `data_ref`, `data_inline` or `data_ref_status` field.

The backend's de-duplication pass now omits `data` entirely on referenced components
(`backend/app/services/ai_context_service.py:1718-1722` builds a projected dict with no
`data` key; `docs/ai-context.md:161` states it *"never publishes a `data` key at all when
it is referenced"*). Eight of seventeen sections are affected; the dashboard section has
eleven components of which the first eight are pointers
(`ai_context_service.py:1710`, `:2180-2287`).

Consequence: for those eight, `section.data` is `undefined` at runtime while TypeScript
says it is present. **Any future consumer that reads `sections.X.data` compiles clean and
renders nothing.** Today it is latent — the sole consumer,
`frontend/src/app/dashboard/ai-context/page.tsx`, never reads `.data` at all; it renders
`JSON.stringify(result, null, 2)` (`:44`). The de-duplication pass shipped with zero
frontend test acknowledgment of it: neither
`frontend/src/test/unit/ai-context-contract.test.ts:103-185` nor
`frontend/src/test/pages/AIContext.test.tsx:14-57` contains a single `data_ref` fixture.

Scope: make `data` optional; add the pointer fields; add a resolver helper; add
`data_ref` fixtures to the contract test. **The resolver is required** — a pointer a
consumer silently fails to follow is a broken feature, and the type fix alone only moves
the failure from silent to absent.

**Verify:**
```
cd frontend
npx tsc --noEmit
npx vitest run src/test/unit/ai-context-contract.test.ts src/test/pages/AIContext.test.tsx
```
Plus: a fixture in which every section carries either `data` or a resolvable `data_ref`,
and a test that a dangling `data_ref` resolves to a declared absence rather than
`undefined`.

---

### T3 — Two disclosure gaps where the fact is already written down

**Files (exclusive):** `backend/app/services/regime_service.py`, `backend/app/services/tail_risk_service.py`
**Depends on:** nothing. Disjoint from wave 1 and from T1/T2.
**Depth:** two files, no design decision — scoped unit.

Both facts are already in docstrings and never reach the consumer. Both are payload-shape
fixes; **no published number may change.**

1. **The regime transition matrix is configured, not estimated.**
   `regime_service.py:307-311` builds `sticky_trans` with a `0.96` diagonal;
   `:316-317` passes `init_params="mc", params="mc"` so Baum-Welch re-estimates only means
   and covariances and **never `transmat_`**; `:323` assigns `hmm.transmat_ = sticky_trans.copy()`.
   `:384` publishes `round(float(hmm.transmat_[i,j]) * 100, 1)` — so a consumer reading
   `/regime` sees "persistence 96.0%" with no statement that it was configured by hand.
   The docstring at `:222-227` says so; the payload declares only
   `transition_matrix: "percent_0_to_100"` (`:595`) and no basis key. Add a
   `transition_matrix_basis` next to the units entry stating it was not re-estimated.

2. **The "Student-t copula" is not a copula fit, and a failed fit gets a fabricated ν.**
   `tail_risk_service.py:499-501` fits two **univariate** `stats.t` MLEs and averages
   their degrees of freedom, then pushes the mean through a closed-form t-λ formula at
   `:511-512`. The signature at `:441-446` accepts exactly two series and the matrix caller
   at `:571-583` is an O(n²) pairwise loop — **it cannot extend past n=2.** The published
   return at `:613-617` carries only `tickers`/`matrix`/`high_tail_risk_pairs`; the
   approximation is disclosed only in the docstring at `:471-475`.
   Separately, `:502-503` catches a failed fit and sets `nu` to a **literal 4.0**, which is
   then published as `degrees_of_freedom` (`:599`) indistinguishable from a fitted value.
   And `:506-509` publishes `lambda_l = 0.0` when `rho <= -0.999` as an arithmetic artifact
   of the closed-form guard — an unmeasured 0.0 that reads as "measured, no lower-tail
   dependence", the same unmeasured-≠-zero violation the engine elsewhere refuses.

   Contrast `backend/app/api/analytics.py:1765-1920`
   (`_risk_contribution_tail_uncertainty`), which carefully declares `not_applicable`
   entries. The repo knows the pattern and missed it here. Match that pattern: a failed
   fit is `null` with a reason; the bivariate-only scope is published; a guarded λ is
   `null` with the guard named.

**Verify:**
```
cd backend
uv run --extra dev pytest tests/test_bugfix_quant_services.py tests/test_regime_service.py -q --no-cov
uv run --extra dev ruff check app tests
```
A leaf-level before/after diff is required. **Zero published numeric values may change** —
these tasks add keys and change `0.0`/`4.0` to `null` with a reason. Name every change.

---

### T4 — Black-Litterman publishes neither its prior nor its projection

**Files (exclusive):** `backend/app/services/optimization_service.py`
**Depends on:** nothing. Disjoint.
**Depth:** item 2 contains a real modelling decision — see below.

1. **The market portfolio is equal weight, undisclosed.** `:695` `w_mkt = np.ones(n) / n`,
   feeding `pi = delta * (cov_ann @ w_mkt)` at `:697`, so the prior biases every posterior
   return and every published weight. There is **no `market_portfolio` key anywhere in the
   file** — zero grep hits. `delta = 2.5` at `:676` is a second bare literal. The payload at
   `:813-838` carries `objective` and `moments_basis`; neither mentions the prior. Add
   both keys.

2. **CORRECTED AFTER ADVERSARIAL REVIEW — my original framing was false and is deleted.**
   I wrote that "the published weights are the solution of neither stated program" and
   proposed solving `sum(w) == 1` directly as the cleaner fix. **Both are wrong, and the
   "fix" was dangerous.** Adversarial review established numerically, and I accept it:

   - `min y'Σy s.t. excess'y = 1, y >= 0` (`:742-746`), clipped and renormalised
     (`:751-756`), **is** the long-only tangency portfolio — the standard construction.
     Its Sharpe (0.328023) is ≥ every point found by 400k random long-only samples plus a
     fine simplex grid.
   - `_max_sharpe` at `:632-649` solves the **identical** program and normalises, docstring
     at `:633` saying so. The two solutions agree to `0.0`.
   - `:67` `STRATEGY_OBJECTIVES["black_litterman"] = "maximum Sharpe of the
     Black-Litterman posterior"`, `:69` `SHARPE_OBJECTIVE_STRATEGIES` → `:353`
     `expected_sharpe_was_the_optimised_objective: true`, pinned by
     `backend/tests/test_pa1_optimizer_moments.py:326` (`("black_litterman", True)`).
   - `:688` docstring: *"Long-only tangency solution"*.

   **The code solves exactly the program it claims to solve. And the "solve `sum(w) == 1`
   directly" option I proposed IS `_min_vol` (`:619-629`)** — on a 5-asset test the weights
   differ by 0.079 and Sharpe drops 0.328 → 0.320, silently converting Black-Litterman
   into minimum-variance **while the payload kept declaring "maximum Sharpe of the
   Black-Litterman posterior."** No gate catches this: `tests/test_quantitative_invariants.py:278`
   exercises `_hrp/_min_vol/_max_sharpe/_min_cvar` and **never `_black_litterman`**, and
   `test_pa1_optimizer_moments.py:326` asserts only the flag. That is the twelfth wrong
   premise in this project, landing in the one task whose purpose is to stop code
   asserting a program it did not solve.

   **What remains is disclosure only:** the post-solve renormalisation at `:751-756` and
   the idempotent re-normalisation at `:805-809` are **undisclosed**. Publish them.
   Change no number.

3. **Required regression test, added because the gap above nearly shipped silently.** A
   test asserting `_black_litterman(...)` agrees with `_max_sharpe(mu, cov, rf)` on a
   common input, to a stated tolerance. Nothing pins the relationship between the two
   implementations today, which is exactly why the false premise survived review. **If any
   change to `_black_litterman` is ever proposed, this test must exist and pass before
   and after.**

**Verify:**
```
cd backend
uv run --extra dev pytest tests/test_pa1_optimizer_moments.py tests/test_quant_math_p1_batch.py tests/test_coverage_engines.py tests/test_quantitative_invariants.py -q --no-cov
uv run --extra dev ruff check app/services/optimization_service.py
```
`tests/test_optimization_service.py` **does not exist** — the earlier draft cited it and
pytest exits 4 before running anything.

Leaf-level before/after diff. **Zero published numeric values may change** — T4 is
disclosure. `expected_sharpe_was_the_optimised_objective: true` is already correct; do not
"fix" it.

---

### T5 — Measure the gate instead of counting it

**Files (exclusive):** `backend/tests/` (new file), and `backend/app/debugging/context_audit.py`
**Depends on:** nothing.
**Owner note:** `context_audit.py` is the parent's exclusive file. **T5 is dispatched to a
worker as a *report*, not an edit.** The worker builds the harness and reports which rules
fire; the parent adds the rules.

`55/55` is a **consistency** signal, not a correctness one. A perfectly self-consistent
export of entirely wrong numbers passes 55/55. The gate proves the export does not
contradict itself; it does not prove the numbers are right.

Build a **rule-coverage harness**: for each of the 17 sections in
`backend/app/services/ai_context_service.py:85-154` (`SECTION_CATALOG`), construct a
deliberately corrupted export and count how many rules catch it. Every rule that never
fires on injected-wrong data is decoration.

This is deterministic, immune to market movement, and unlike `overall_score` it has a
fixed point. It is the measurement instrument the rest of the project has been missing —
`overall_score` moved 12.8 → 13.0 → 13.1 across three exports as the cache refreshed, and
quoting it as progress means optimising a number nobody controls against a baseline
nobody can hold still.

**Verify:**
```
cd backend
uv run --extra dev pytest tests/test_audit_rule_coverage.py -q --no-cov
```
The harness must print, per section: rules fired, rules that should have fired and did not,
and rules that fired on nothing. The deliverable is that table, plus a ranked list of
classes the 55 rules do **not** cover.

---

## 3. Wave exit criteria

1. Every task's `Verify:` command run by the **parent**, output pasted, not summarised.
2. Full backend suite uncontended — the suite shares a file-backed `test.db` and concurrent
   runs produce phantom failures. Known baseline: the 3 order-dependent failures in
   `tests/test_bugfix_api_layer.py` plus
   `tests/integration/test_compose_services.py::test_published_backend_and_frontend`.
3. Full frontend type-check and test suite green.
4. Live re-export against a freshly restarted server — no `--reload`, a stale server
   invalidates audit evidence — and the 55-rule gate re-run against it.
5. `oracle` over the combined diff, because T1 and T4 both touch shared deliverable
   surfaces.

## 4. Deliberately not in this wave

- **Fixed income, derivatives, options chains, yield curves.** Require paid data this
  repo does not have. Would invalidate all 55 rules, which are calibrated to daily Indian
  equity returns.
- **Auth, multi-tenancy, entitlements.** Only meaningful under the SaaS fork, and that
  fork also requires a licence to redistribute `yfinance`-sourced data.
- **`ledoit_wolf` covariance shrinkage.** Changes every downstream number at once, and
  there is no golden-value harness to measure the change against until T5 and its
  successor exist. On short Indian histories the Ledoit-Wolf intensity frequently goes to
  ~1, overwriting the correlation structure with something close to equicorrelation —
  the number looks completely reasonable and nothing fails.
- **`qs.plots` / `qs.reports`.** Matplotlib objects on a JSON API surface. Not
  serialisable, not assertable. Appropriate only for a PDF surface, which is T1's job.
- **Substituting `statsmodels.stats.multitest.multipletests` for the hand-rolled
  Bonferroni/BH** at `cointegration_service.py:297-336`. Those are verified correct, and
  `:345-357` deliberately computes Bonferroni from `comparisons_made` rather than
  delivered rows — a family definition `multipletests` cannot express. Substituting it
  would be a regression.
- **Replacing the hand-rolled Parkinson estimator** at `regime_service.py:263-277` with
  `arch.roll_volatility.parkinson`. Four correct lines, already Jensen-pooled, with a
  non-positive guard the library lacks and a unit test pinning the pooling. Substituting
  it is a net loss under the repo's own YAGNI rule.
- **Consolidating the two EWMA implementations.** They are **not** the same estimator: the
  recursion clips returns to ±0.20, subtracts the mean and truncates to 60 rows; the
  service uses full-sample normalised exponential weights and does none of those.
  Canonicalising either way moves published numbers, and the engine's is the shared core
  the bootstrap resamples under a `point_tolerance` identity check. Wave 1 fixes the
  seeding defect and measures the divergence; consolidation is a separate decision.
- **Mounting or deleting the dead export surface** — `frontend/src/components/ui/ExportPanel.tsx`,
  `QuickExportButtons`, `ExportService.exportPDF/exportExcel/exportCSV/exportChart`,
  `ExportProgress`. All exported, imported by nobody. Worth doing, but it is a
  housekeeping task with no correctness content, and T1 may make part of it moot.
