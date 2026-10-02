# 19 — FX history instead of a single live rate

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: Phase 1 issue 15
Repo: `backend/`
Effort: S | Score: 30

## What

`performance-history` applies **one live FX rate to the entire return history**. Any non-INR leg
therefore has fabricated returns.

And the path is live: `region` defaults to `"US"` in the portfolio model.

## Why

Consider a portfolio with a US-listed position. Its INR return over 2024 is computed as
`price_return_2024 × fx_today`. The actual 2024 INR return used the 2024 FX rate. If USD/INR moved
5% over that year, the reported return is wrong by 5% — and the error is not a rounding difference,
it is the entire currency effect attributed to the wrong period.

This also corrupts anything derived from the return series: vol, beta, VaR, correlation, and
therefore every optimisation output.

The fix is small and the data is free.

## Change

- A USD/INR **series**, not a spot quote. Phase 1 issue 15 provides
  `usd_inr_reference_rate()` from RBI — the authoritative fixing, not an offshore quote.
- Apply the **rate as of each period** when converting historical returns. This is how
  Portfolio Performance and Asset Vantage both handle it: FX is kept on the account and
  time-varying rates are applied per account per period.
- Support multiple currencies, not just USD, if `region` permits others. `jugaad-data` covers
  USD/GBP/EUR/JPY → INR.
- The FX fallback (currently a hardcoded `83.0`) stays as a last resort, and its
  `provenance="fallback"` marking is preserved. That part is already implemented correctly — do not
  regress it.
- Report the FX basis in the response, consistent with the existing `provenance` convention.

## Proof of done

- [ ] A USD position's historical INR return uses the **period's** rate, not today's. A test with a
      known FX path and a known price path asserts the exact combined return.
- [ ] A period with no FX observation uses the **previous available** rate, and the response states
      which rate was used for which period.
- [ ] The hardcoded `83.0` fallback is still labelled `provenance="fallback"` and is still refused
      by `coerce_live_fx_rate`. **This already works — verify it still does after the change.**
- [ ] An INR-only portfolio is completely unaffected. A test confirms the output is byte-identical
      to before.
- [ ] Multi-currency is supported if `region` allows it, with per-currency series.
- [ ] The response states the FX source and the rate applied per period.

## Notes

The existing FX provenance handling in `currency_service.py` is the **one place in the data layer
where the disclosure contract fully holds** — the fallback is honestly labelled and refused as a
live rate. Use it as the template for the rest of Phase 2.

This is small and mostly mechanical, but it silently corrupts an entire class of numbers today.

Refs: `../spec.md`, `backend/app/services/currency_service.py:27,76-124,334-343,362,380-381`, `backend/app/services/data_service.py:211`, Phase 1 issue 15
