# FinEngine UX 01 — Restrained Data-Terminal Design System

**Status:** Wave-1 architecture proposal; documentation only  
**Scope:** Current cash-equity portfolio, research, and analytics UI  
**Audience:** Frontend and backend engineers implementing the revamp  
**Non-goals:** Futures, options, crypto, multi-user accounts, and a new product identity

## 1. Product and design position

FinEngine is a personal, localhost-first, India-first cash-equity terminal. The interface should feel closer to a reliable research workstation than a marketing dashboard: dense enough for comparison, quiet enough for inspection, and explicit about what is measured, cached, stale, unavailable, or not yet shipped.

The target visual language is **flat, restrained, and data-terminal**:

- Surfaces and borders establish hierarchy; gradients, glass effects, and decorative glow do not.
- A number is the primary content. Labels, source, unit, and as-of metadata are close to the number.
- Color communicates role, not excitement. Up/down and risk states always have a second, non-color signal.
- Missing data is never converted into a plausible zero, safe score, or “low risk” conclusion.
- Controls expose only behavior that is actually implemented and persisted.

The current UI has the right ingredients but not yet a system. `frontend/src/app/globals.css` defines only `--background` and `--foreground`; the body overrides the configured Geist font with Arial. Components repeat `bg-white dark:bg-gray-800 rounded-lg shadow-md` shells, use dozens of local hex values, and split between light semantic chrome and permanently dark page heroes. The current sidebar also describes a flat list of pages rather than a decision-oriented hierarchy. The proposed system below turns those observations into a small vocabulary without adding a UI dependency.

### 1.1 Non-negotiable data contract

The visual system cannot make an unsupported claim look supported. The following rules are part of the design, not optional copy guidance:

1. `null`, missing, failed, and not-computed values render as `N/A` in metric surfaces or `—` in table/stat cells. They never render as `0`, a safe score, or a fabricated fallback.
2. A value is “live” only when the response includes a usable quote/market timestamp and the UI can say what it is. “Live” is not a decorative green badge.
3. Every page-level result carries a source/as-of treatment when that information is present in the response. If the current endpoint does not provide it, say “source/as-of not provided by API” rather than infer it.
4. Fractions and percentage points are different types. Use explicit formatter names such as `formatPctFraction` and `formatPctPoints`; never infer units from magnitude.
5. Indian rupee values use `en-IN`, the `₹` symbol, and Cr/L compaction where appropriate. A currency selector must not merely swap symbols around an unchanged number.
6. A chart shows only series supplied by the API or an explicitly labeled deterministic calculation. No synthetic frontier, confidence band, scenario, or “live” status is permitted.
7. Unsupported capabilities are either omitted from the primary surface or shown as a clearly labeled availability note. They are never represented as empty successful data.

## 2. Token architecture

Use CSS custom properties as the source of truth and map them into Tailwind 4's `@theme inline`. Components consume semantic names (`surface`, `text-muted`, `border-default`) rather than theme-specific utility classes. This permits the same component to work in both themes without a second visual language.

### 2.1 Semantic surface, text, border, and accent tokens

The values below are the proposed default palette. They are intentionally quiet: near-black ink, cool neutral surfaces, one blue action accent, and reserved status colors.

| Semantic token | Light value | Dark value | Use |
|---|---:|---:|---|
| `--color-canvas` | `#F6F8FA` | `#0B0F14` | App background behind panels |
| `--color-surface` | `#FFFFFF` | `#11161D` | Primary panel/table surface |
| `--color-surface-raised` | `#F8FAFC` | `#171E27` | Popovers, selected rows, elevated controls |
| `--color-surface-sunken` | `#EEF2F6` | `#0D1218` | Code blocks, table headers, inset regions |
| `--color-surface-inverse` | `#17202A` | `#F8FAFC` | Tooltip/inverse surface |
| `--color-text-primary` | `#17202A` | `#F3F6F9` | Headings and primary values |
| `--color-text-secondary` | `#52606D` | `#AAB7C4` | Supporting copy and table labels |
| `--color-text-muted` | `#718096` | `#8291A1` | Units, timestamps, helper text |
| `--color-text-disabled` | `#A0AEC0` | `#647181` | Disabled controls; never the only status cue |
| `--color-text-inverse` | `#F8FAFC` | `#17202A` | Text on inverse surfaces |
| `--color-border-subtle` | `#E4E9EF` | `#26313D` | Dividers and low-emphasis table rules |
| `--color-border-default` | `#CBD5E0` | `#354252` | Inputs, panel boundaries |
| `--color-border-strong` | `#94A3B8` | `#5A6B7D` | Selected or high-emphasis boundary |
| `--color-focus-ring` | `#2563EB` | `#7DD3FC` | 2px keyboard focus ring |
| `--color-accent` | `#1D4ED8` | `#60A5FA` | Primary action and active navigation |
| `--color-accent-hover` | `#1E40AF` | `#93C5FD` | Hover/pressed action |
| `--color-accent-subtle` | `#DBEAFE` | `#172554` | Selected navigation and informational tint |
| `--color-positive` | `#166534` | `#86EFAC` | Positive text/indicator only |
| `--color-positive-subtle` | `#DCFCE7` | `#14532D` | Positive background |
| `--color-negative` | `#991B1B` | `#FCA5A5` | Negative text/indicator only |
| `--color-negative-subtle` | `#FEE2E2` | `#4C1D1D` | Negative background |
| `--color-warning` | `#92400E` | `#FDE68A` | Limited/stale/partial warning |
| `--color-warning-subtle` | `#FEF3C7` | `#422006` | Warning background |
| `--color-info` | `#155E75` | `#67E8F9` | Neutral information |
| `--color-info-subtle` | `#CFFAFE` | `#164E63` | Information background |
| `--color-neutral-subtle` | `#E2E8F0` | `#273444` | Neutral/unknown status background |

Rules for semantic colors:

- `--color-positive` and `--color-negative` are not the palette for arbitrary chart categories. They mean a signed value, a pass/fail result, or a change whose sign is known.
- Warning means degraded confidence or incomplete input, not “bad” by itself.
- A neutral/unknown state is visually distinct from both a pass and a failure.
- Do not use a generic risk score to imply diversification. Diversification is derived from true `HHI = Σwᵢ²` and `N_eff = 1/HHI`; a portfolio with `N ≤ 1` displays `0%` diversification, not an inverted risk score.

### 2.2 Data-series tokens

Chart colors are separate from UI status colors. Categorical series are never assigned by page order without a stable semantic key.

| Token | Light stroke/fill | Dark stroke/fill | Suggested role |
|---|---:|---:|---|
| `--chart-series-1` | `#005A8D` | `#38BDF8` | Portfolio / primary line |
| `--chart-series-2` | `#8A3B00` | `#FB923C` | Comparison / benchmark alternative |
| `--chart-series-3` | `#0F766E` | `#5EEAD4` | Secondary factor or scenario |
| `--chart-series-4` | `#6D28D9` | `#C4B5FD` | Tertiary series |
| `--chart-series-5` | `#4B5563` | `#CBD5E1` | Neutral/reference series |
| `--chart-series-6` | `#A16207` | `#FDE68A` | Highlight, not small text |
| `--chart-series-7` | `#BE185D` | `#F9A8D4` | Additional categorical series |
| `--chart-series-8` | `#475569` | `#94A3B8` | Additional neutral series |
| `--chart-grid` | `#D8E0E8` | `#2A3745` | Axis/grid lines |
| `--chart-axis` | `#718096` | `#AAB7C4` | Axis labels |
| `--chart-zero` | `#64748B` | `#CBD5E1` | Zero/reference line |
| `--chart-missing` | `#E2E8F0` | `#273444` | Missing cells; add hatch/label, never zero fill |

**Checked up/down pair:**

| Meaning | Light token | Contrast on white/canvas | Dark token | Contrast on `#11161D` | Non-color encoding |
|---|---|---:|---|---:|---|
| Up / positive change | `--chart-series-1` `#005A8D` | 7.38:1 / 6.93:1 | `#38BDF8` | 8.48:1 | `▲`, `+`, solid stroke, “Up” text |
| Down / negative change | `--chart-series-2` `#8A3B00` | 7.76:1 / 7.29:1 | `#FB923C` | 8.02:1 | `▼`, `−`, dashed stroke or down marker, “Down” text |

These ratios are for the solid swatches against the stated light/dark surfaces and exceed the 4.5:1 text threshold. Blue/orange remains distinguishable in common red-green color-vision simulations, but color is still never the sole carrier of meaning. In tables and metric cards, pair the swatch with an explicit sign, arrow, and label. In charts, pair the line color with a marker or dash pattern and direct labels where space permits. Recheck contrast after any theme change.

### 2.3 Component-level tokens

Use these as layout/scale tokens rather than sprinkling arbitrary Tailwind values:

```text
--control-height-sm: 32px
--control-height-md: 40px
--control-height-lg: 48px
--content-max: 1440px
--sidebar-expanded: 240px
--sidebar-collapsed: 64px
--gutter-mobile: 16px
--gutter-desktop: 24px
--chart-height-sm: 220px
--chart-height-md: 320px
--chart-height-lg: 420px
--focus-ring-width: 2px
--focus-ring-offset: 2px
--skeleton-pulse: 1400ms
```

## 3. Typography and data typography

Use the already configured Geist Sans and Geist Mono families. Do not add a font. The current global `Arial, Helvetica, sans-serif` override should be removed when the token system is implemented; the existing font variables are otherwise dead configuration.

| Role | Size / line height | Weight | Notes |
|---|---|---:|---|
| Display | `32/38` | 600 | One page-level value only; not a hero slogan |
| Title 1 | `24/30` | 600 | Page title |
| Title 2 | `20/26` | 600 | Major section |
| Title 3 | `16/22` | 600 | Panel title |
| Body | `14/20` | 400 | Default UI copy |
| Body strong | `14/20` | 600 | Labels and selected values |
| Caption | `12/16` | 400 | Source, units, as-of, helper text |
| Micro | `11/14` | 500 | Dense table headers and status chips only |
| Data | `13/18` | 500 | Geist Mono or `font-variant-numeric: tabular-nums` |
| Data emphasis | `16/22` | 600 | Key metric values |

Typography rules:

- Use sentence case and short labels. Avoid marketing language such as “Bloomberg-grade” in page chrome.
- Use tabular numerals for prices, weights, returns, dates, and aligned table columns. Do not use a proportional font for numeric columns.
- Keep units next to the value (`12.4%`, `₹1.25 Cr`, `1.8 days`) or in a consistent column header.
- Use `—` for a missing table/stat value and `N/A` for a missing metric card. Use `Never` only for a timestamp that has genuinely never been refreshed.
- Do not truncate tickers in a way that hides the exchange suffix. `3MINDIA.NS`, `BAJAJ-AUTO.NS`, and `500112.BO` must remain legible; allow horizontal table scrolling instead.

## 4. Spacing, layout, radius, and elevation

### 4.1 Spacing scale

Use a 4px base scale. The values below are the complete spacing vocabulary for the first revamp:

```text
0   1px       1   4px       2   8px       3   12px
4   16px      5   20px      6   24px      8   32px
10  40px      12  48px      16  64px
```

- Page gutter: 16px on small screens, 24px at desktop.
- Panel padding: 16px for compact panels, 20–24px for major sections.
- Gap between related controls: 8px; gap between panels: 16px; gap between page bands: 32–48px.
- Dense tables may use 8px vertical cell padding; never remove the horizontal separation needed for scanning.
- Do not introduce arbitrary 18px, 22px, or 30px gaps during the migration.

### 4.2 Layout

- Expanded navigation is 240px; collapsed navigation is 64px with icon tooltips and accessible names.
- Content is centered at a maximum of 1440px. Wide tables and charts may use the full available width, but text blocks remain readable.
- Desktop grid: 12 columns with 16px gutters. Typical spans are 8/4 for a primary chart and supporting table, 6/6 for two analytical panels, and 3/3/3/3 for metric cards.
- Mobile: one column; tables use a deliberate horizontal scroll region with a visible edge/focus affordance. Do not squeeze a 10-column quant table into unreadable cells.
- The shell header stays compact: page title, base currency, as-of/source, connection/refresh state, and one primary action. Secondary export/settings actions may collapse into a menu on small screens.

### 4.3 Radius and elevation

| Element | Radius | Elevation |
|---|---:|---:|
| Input/button | 4px | 0 |
| Table cell/inset block | 2px | 0 |
| Card/panel | 6px | 0 |
| Popover/select | 6px | 1 |
| Dialog | 8px | 2 |
| Toast | 6px | 2 |
| Status pill | 999px | 0 |

Default panels are flat with a 1px border. Shadows are reserved for overlays that must sit above page content; do not use large shadows to create hierarchy on every card. There are no gradients, glass blur, neon glows, or decorative background illustrations in the target system.

## 5. Core component recipes

### 5.1 Shell and navigation

- The sidebar is a single source of route metadata: label, URL, section, icon, description, and page title.
- Sections are Portfolio, Risk, Performance & Allocation, Market Diagnostics, Research, and System. The current URLs remain unchanged; grouping is navigation metadata, not a route migration.
- Active navigation uses `aria-current="page"`, an accent text color, and a 2px left rule. Color is not the only active cue.
- The header shows the active route title and a compact data context strip: base currency, data source (only when known), as-of time, and connection state. A missing timestamp says “not provided”.
- The mobile drawer is inert/hidden when closed and returns focus to its trigger when closed.

### 5.2 Panel and card

A panel has, in order:

1. Title and optional one-line purpose.
2. Right-aligned controls or status.
3. Content region.
4. Footer with source, as-of, methodology, or quality note when relevant.

A card is not a decorative container for a single number. Metric cards include a label, value, unit, optional signed delta, and an explicit quality state. A missing delta is omitted; a missing value is `N/A`.

### 5.3 Metric card

```text
┌──────────────────────────────────────────────┐
│ Annualized volatility       [source/as-of]  │
│ 18.42%                                       │
│ ▲ +1.20 pp vs prior window   [same basis]   │
│ Window: 252 aligned sessions                 │
└──────────────────────────────────────────────┘
```

Required rules:

- `change` is rendered only when it is finite and its basis is known.
- Sign, arrow, and text all agree. Do not force a `+` before a negative number.
- A percentage-point delta is labeled `pp`; a relative return delta is labeled `%`.
- No placeholder `+0.00%`, `NaN%`, or fake “Low Risk” badge is allowed.
- If the underlying model did not fit, show the backend's `model_fitted=false`/`error` message and `N/A`, not a default volatility.

### 5.4 Status and quality indicators

Use a status component with text, not just a dot:

```text
[STALE] Last successful data: 24 Sep 2026, 16:30 IST
[PARTIAL] 8/10 positions have aligned sessions
[UNAVAILABLE] Endpoint returned no data for this window
[NOT SHIPPED] News and sentiment are not exposed by the current API
```

Status vocabulary:

- `LIVE` — only when a live quote/connection state is actually known.
- `CACHED` — response came from cache, with cache/as-of metadata if available.
- `STALE` — last successful data is displayed with its age and a refresh action.
- `PARTIAL` — some rows/fields are available; the missing scope is named.
- `UNAVAILABLE` — endpoint/provider returned no usable result.
- `NOT SHIPPED` — capability is absent from the current backend contract.

### 5.5 Forms and dialogs

- Use the existing Radix Dialog primitive for money and destructive actions. Every dialog has a title, description, labelled fields, focus trap, Escape behavior, and a named close button.
- Do not close a dirty money form on an outside click. A deliberate Cancel action is required.
- Primary action labels name the mutation: `Add position`, `Save changes`, `Run dry-run`, `Delete position`.
- Pending actions disable only the affected control and expose `aria-busy`; terminal success/failure goes through the existing notification system or an inline error.
- Never show a success banner for a control that was not persisted. The Settings page may only claim that the data-source preference was saved.

### 5.6 Tables

Every dense table follows the same contract:

- Use a semantic table or the installed TanStack Table, with a caption or accessible name.
- Column headers are text. Sortable headers contain a real button, `aria-sort`, and a visible sort direction; they are not click-only `<th>` elements.
- Numeric columns are right-aligned and use tabular numerals. Ticker, date, and action columns are left-aligned; actions are right-aligned.
- Show `Ticker` in a non-breaking/nowrap cell, including `.NS`/`.BO` suffixes.
- TanStack cell renderers read `const data = row.original || row;` before accessing values.
- Filtering changes the visible count and pagination footer. Empty pages say `No results` rather than “Showing 1 to 0 of 0”.
- A row-level source/as-of or quality badge is allowed when the payload provides it. Do not imply that a table row is live merely because it is rendered.
- Export uses the same rows, units, null policy, and source metadata as the screen. CSV cells are quoted and formula-prefixed through the existing shared escape helper.

### 5.7 Charts and chart frames

All charts sit in a shared `ChartFrame` that supplies:

- title, question/description, data window, source, as-of, and methodology;
- loading skeleton, partial-data notice, no-data notice, and retry state;
- a legend that names series and units;
- accessible text summary for the chart's key values.

Chart rules by type:

| Chart type | Required behavior | Prohibited shortcut |
|---|---|---|
| Performance line | One y-axis, explicit date window, benchmark as a separately named series | Dual axes without a stated reason |
| Allocation bar/donut | Sort or preserve backend order; show `Unknown` explicitly; include value labels | Hiding small categories with no `+N more` disclosure |
| Volatility/term structure | Plot only returned horizons; distinguish fitted, unavailable, and limited history | Synthetic log curve or ±20% pseudo-CI |
| Histogram/quantile | Label the estimator and sample count | Calling min/max P10/P90 |
| Scatter/frontier | Plot only real coordinate pairs; show a real current point only when computed from current data | Fabricated efficient-frontier geometry |
| Heatmap/matrix | Read `{ tickers, matrix }`; use `tickers` as headers and `matrix[i][j]`; show numeric values/tooltips | Iterating the outer response object as if it were the matrix |
| Fan chart | Show method, seed, paths, horizon, and percentile definitions | Calling a deterministic scenario a forecast without assumptions |
| Risk contribution | Preserve signed values and show `N/A` when tail observations are absent | `Math.abs` that reverses a negative deviation |

Recharts remains the installed chart engine. The revamp should extract common chart frames and tokens, not replace the library. Charts should render a stable empty state rather than axes-only zero lines.

## 6. Formatting and localization contracts

The formatting boundary belongs in one shared module, not page-local helpers. The target API is conceptually:

```text
formatINR(value, { notation: 'full' | 'cr-l' }) -> string
formatCurrency(value, currency) -> string
formatPctFraction(value) -> string       // 0.124 -> 12.40%
formatPctPoints(value) -> string          // 12.4 -> 12.40%
formatNumber(value, { digits }) -> string
formatQuantity(value) -> string
formatAsOf(value, timezone = 'Asia/Kolkata') -> string
formatUnavailable(kind) -> 'N/A' | '—'
```

Rules:

- `Intl.NumberFormat('en-IN', { currency: 'INR' })` is the default for Indian holdings and totals.
- Use Cr/L only when the unit is clear. Show the full value in a detail view or tooltip.
- A USD view requires a real conversion and provenance. The current backend has a currency service seam, but frontend currency behavior must not be described as converted until the value, rate, and as-of are actually available.
- Dates entered in a local calendar are formatted from local components, not by slicing `toISOString()`; the repository's prior UTC date bug is a known constraint.
- Ticker validation accepts alphanumeric scrip codes, hyphens, and `.NS`/`.BO` suffixes. Do not narrow it to `[A-Z]{3,5}`.
- CSV exports use one writer. Quote all cells, double embedded quotes, and neutralize cells beginning with `=`, `+`, `-`, `@`, CR, or tab.

## 7. Theme and motion rules

- Class-based dark mode is the intended behavior. The document baseline already has a Tailwind v4 custom variant; implementation must re-apply the persisted class on hydration and use semantic tokens rather than page-specific dark slate roots.
- The default theme may follow the system only until the user's explicit preference is known; once chosen, that preference wins.
- Transitions are short and functional: 120–180ms for hover/focus, 200ms for drawer movement. No looping gradient animation or attention-seeking motion.
- Reduced-motion users receive instant state changes and no decorative transitions.
- Color, animation, and position never carry an error or result without text/label support.

## 8. Acceptance checklist for the design system

- [ ] Every visible surface, text, border, accent, and status color resolves to a semantic token.
- [ ] No page owns a new hardcoded hex palette or a permanently dark hero that ignores the shell theme.
- [ ] Geist tokens are actually applied; the Arial override is removed.
- [ ] Light/dark values meet the documented contrast checks.
- [ ] Up/down uses the checked blue/orange pair plus arrow, sign, and text/line-style signals.
- [ ] Missing values use the documented `N/A`/`—` policy; no `|| 0` or “safe” fallback reaches a metric card.
- [ ] Sortable tables are keyboard-operable and cell renderers use `row.original || row`.
- [ ] Matrix charts use `tickers` and `matrix[i][j]`.
- [ ] All dialogs are Radix-backed, labelled, focus-managed, and Escape-safe.
- [ ] INR uses en-IN/₹/Cr/L; percent fraction and percent-point helpers are not interchangeable.
- [ ] Existing dependencies are sufficient; no new design-system, chart, table, or icon package is required.
