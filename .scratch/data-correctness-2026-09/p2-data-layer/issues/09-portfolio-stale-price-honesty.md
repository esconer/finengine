# 09 — Portfolio refresh must not serve stale prices as live

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: 03
Repo: `backend/`
Severity: **CRITICAL**

## What

`portfolio.py:1659-1678`:
```python
async def update_one(position: PortfolioPosition):
    async with sem:
        try:
            quote_data = await data_service.fetch_quote(position.ticker)
            if quote_data and quote_data.get("current_price"):
                position.last_price = quote_data["current_price"]
                position.market_value = (position.quantity or 0) * position.last_price
                position.updated_on = datetime.now(timezone.utc).replace(tzinfo=None)
        except Exception:
            logger.error("Portfolio price refresh failed")   # ← no ticker in the message
```

`fetch_quote` raises `ProviderUnavailableError` / `UnknownTickerError` (`data_service.py:1036-1037`)
on a full cascade failure. All of it is swallowed.

## Why

On failure the row **keeps its previous `last_price` and `market_value`**. `GET /api/v1/portfolio`
(`:363-515`) then computes `total_value`, `sectors`, `live_weight`, `unrealized_gain_loss`, and
`unrealized_gain_loss_pct` from that mix of fresh and stale prices and returns **HTTP 200**.

The `as_of` stamp makes it worse:
```python
# portfolio.py:94-105, used at :514
as_of = max(position.updated_on for position in positions)
```

`max(updated_on)` means **one freshly-refreshed position makes the entire book look freshly
quoted.**

No `fetch_logs` row is written (issue 08).

**User-visible symptom:** the portfolio header shows a plausible total and "as of <now>", and one
holding's market value and P&L is from last week — with no error, no toast, and no per-position
staleness indicator.

## Change

- A failed refresh must mark the position **stale**, not silently retain the old price as if it
  were current.
- Per-position `price_as_of` and a `stale` flag, exposed on the position DTO.
- The portfolio-level `as_of` must reflect the **oldest** stale position, not the newest fresh one.
  A book is only as fresh as its least fresh leg.
- A partial failure should surface as a visible warning, not a silent partial refresh.
- The bare `except Exception` must name the ticker and the underlying error type (see issue 19).
- Consider whether a failed refresh should be a partial `200` with a warning, or a `503`. Given
  that the app already has a `data_status` convention, a partial `200` with an explicit
  `data_status: "stale"` and a warnings list is more consistent and more useful.

## Proof of done

- [ ] A test forces a quote failure for one position. That position returns a `stale: true` flag
      and a `price_as_of` reflecting the last successful refresh.
- [ ] The portfolio-level `as_of` equals the **oldest** `price_as_of` across positions, not the
      newest. A test with one fresh and one stale position asserts this.
- [ ] The response carries a warning naming the affected tickers.
- [ ] The test asserts the response is not a bare `200` with no signal — either a `data_status` of
      `stale`/`partial` or an explicit warnings entry.
- [ ] Total value, P&L, and weights are computed from prices that are individually labelled, so a
      consumer can see which components are stale.
- [ ] The frontend renders the stale state. Currently `/portfolio/manage` has no concept of a stale
      position.
- [ ] A `fetch_logs` row exists for the failed attempt (depends on issue 08).
- [ ] The log line names the ticker and the error type.

## Notes

The same pattern — a swallowed exception retaining stale state and returning 200 — should be
grepped for across `portfolio.py`. This is the most user-visible instance.

Refs: `../spec.md`, `app/api/portfolio.py:94-105,363-515,514,1659-1678`, `app/services/data_service.py:1036-1037`
