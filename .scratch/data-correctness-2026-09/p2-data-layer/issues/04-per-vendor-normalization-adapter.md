# 04 — Per-vendor normalization adapter

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **CRITICAL**

## What

`data_service.py:680` calls `self._normalize_yfinance_data(raw, normalized_ticker)` for
**both** tiers. There is one normalizer for two vendors, it is named for one of them, and it has
no real-vendor test.

```python
# data_service.py:1397-1456
required_columns = ['Open','High','Low','Close','Adj Close','Volume']   # :1416
if missing_columns:
    logger.warning(f"Missing columns for {ticker}: {missing_columns}")
    return pd.DataFrame()                                              # :1421
df = df.rename(columns={'Date':'date','Open':'open', ..., 'Adj Close':'adj_close', ...})
```

## Why

Three compounding problems.

**a) The acceptance gate runs before normalization.**
`_download_with_timeout` applies `accept_vendor_frame` to the **raw** frame (`:1249`) *before*
normalization. So a shape-mismatched bfinance frame is **accepted** at `:1255`, returned, and
only then discarded at `:681-683` — after which the whole cascade retries (`:662`, 3 attempts).
Three wasted bfinance round-trips per fetch, with no error surfaced.

**b) A bfinance column or index change silently disables Tier-1 for the entire product.**
The cascade then "succeeds" via yfinance and **nothing in the logs says Tier-1 is dead** — only a
per-attempt `logger.warning` at `:1420`. The app looks healthy while running entirely on the
fallback vendor.

**c) The contract is asserted only in a comment.**
`tests/test_source_preference_and_cache.py:37-38` says *"exactly how bfinance/yfinance hand frames
to `_normalize_yfinance_data`"* — against a **hand-built** `pd.DataFrame` (`:42-53`). There is no
recorded fixture and no live test. So the actual vendor frame shape is never verified.

Additionally, `auto_adjust=False` is passed to both vendors (`:1232-1242`) and `Adj Close` is
**required** at `:1416`. If either vendor's `auto_adjust=False` frame omits `Adj Close`, the whole
frame is discarded. And if either vendor's `Adj Close == Close` — i.e. it does not adjust — every
return series is unadjusted while the note at `:1174` asserts the opposite.
`_structural_invalid_mask` (`:1555-1575`) validates OHLC *relationships*, not adjustment, so it
cannot detect this.

## Change

Split into one adapter per vendor behind a common protocol:

```python
class VendorFrameAdapter(Protocol):
    name: str
    def accepts(self, raw: pd.DataFrame) -> bool: ...
    def normalize(self, raw: pd.DataFrame, ticker: str) -> pd.DataFrame: ...
```

- `accepts()` runs on the **raw** frame and is the only gate.
- `normalize()` either returns a valid normalized frame or raises `ProviderInvalidInputError`. It
  never returns an empty DataFrame.
- Move `accept_vendor_frame` **after** the adapter's own acceptance, so a rejected frame does not
  trigger a cascade retry.
- Record which adapter handled the frame, and whether adjustment was actually applied.
- Add recorded fixtures: capture one real frame per vendor, commit as test data, assert both
  adapters accept them.

## Proof of done

- [ ] One adapter per vendor, each with its own `accepts()` and `normalize()`.
- [ ] A structurally-invalid frame is rejected by `accepts()` and does **not** consume a retry
      from the 3-attempt loop.
- [ ] A bfinance column change disables Tier-1 **loudly** — a `fetch_logs` row, a warning at
      `logger.error` or above, and a health signal on the settings page.
- [ ] Recorded real-vendor fixtures exist for both vendors and are asserted against.
- [ ] The adjustment provenance of a frame is recorded: whether `Adj Close` was present, and
      whether it differed from `Close`. A frame where they are identical is labelled
      `unadjusted`, and analytics that require adjustment either gate on that or say so.
- [ ] `normalize()` never returns an empty DataFrame. It raises.
- [ ] The stale comment in `tests/test_source_preference_and_cache.py:37-38` is replaced with a
      real assertion.
- [ ] The name `_normalize_yfinance_data` is gone. A grep confirms no yfinance-specific naming on
      a shared code path.

## Notes

This is the seam that makes Phase 1 issue 03 safe. Without it, a bfinance frame change is an
invisible product-wide regression.

Refs: `../spec.md`, `app/services/data_service.py:680,681-683,662,1232-1242,1249,1255,1397-1456,1555-1575,1174`, `tests/test_source_preference_and_cache.py:37-53`
