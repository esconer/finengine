## Agent skills

### Issue tracker

Local markdown: issues live as files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.

## Execution & Command Rules

- All `uv` commands (`uv run`, `uv sync`, `uv tool run`, `uvx`) are pre-approved and should run non-interactively without user confirmation prompts.
- Always include `-y` or `--yes` when executing `uv tool run` or `uvx` tools.
- Prefer adding permanent unit and regression tests in `tests/` over running one-off throwaway debug scripts.

## Quantitative & Terminal UI Invariants

- **Zero-State Portfolio Weights**: When adding the initial asset to an empty portfolio (`positions.length === 0` or `total_value === 0`), the auto-calculated portfolio weight must always be `100.00%` (`1.0`). Never use hardcoded arbitrary portfolio totals (e.g. `100000`) as fallbacks.
- **Concentration & Diversification Bounds**: Diversification scores must be computed from true concentration indices ($HHI = \sum w_i^2$, $N_{\text{eff}} = 1/HHI$). A single-holding portfolio ($N \le 1$) must strictly render `0%` diversification score. Never invert generic risk scores as a proxy for diversification.
- **Inverse-Volatility Risk Parity**: Volatility-adjusted allocations must compute true inverse-volatility weights ($w_i \propto 1/\sigma_i$).
- **Deterministic Return Compounding**: Monthly returns must be grouped and compounded geometrically via `(1 + r).groupby([year, month]).prod() - 1` rather than relying on variable dataframe schemas.
- **TanStack Table Accessors**: Table cell renderers must always read row data through `const data = row.original || row;` to prevent `NaN` or unrendered values.
- **Bivariate Matrix Parsing**: Matrix endpoints returning `{ tickers, matrix }` must bind `tickers` as headers and index `matrix[i][j]`, avoiding `Object.keys()` iteration on the outer response object.
- **NSE/BSE Ticker Formats**: Ticker validation regexes must support alphanumeric scrip codes, numbers, hyphens, and exchange suffixes (e.g., `3MINDIA.NS`, `MOTHERSON.NS`, `BAJAJ-AUTO.NS`, `500112.BO`).
- **Currency & Market Microstructure**: Indian equities (`.NS`, `.BO`) must format prices and market caps in Indian Rupee notation (`₹`, `Cr`, `L`) using `en-IN` localization.
- **Metric Card Hygiene**: Keep metric cards deduplicated and strictly driven by live API responses without placeholder mock deltas.


